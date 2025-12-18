"""
forge_city_shards.py

1. Chunk-Wide Density Analysis: Finds the true 'Foundation Level' of the chunk.
2. Smart Purge: Removes deep terrain below the foundation, keeping the soil plug intact.
 SOFT THINNING: "Penetrates" dirt layers. 
   - If a dirt block has terrain above it -> DELETE (It's underground).
   - If a dirt block has Air/City above it -> KEEP (It's the surface).
   - Result: All terrain becomes a 1-block thick shell.
   
3. Green Filter: Discards chunks that are statistically just nature.
4. Full Physics Erosion: Uses the complex JSON config and CA engine.
5. Life Injection: Adds underwater vegetation.

Usage:
  python SunkenCityProject/forge_city_shards.py --input city_original.bin --out-dir shards/WestonSunken --config erosion_config_city.json
"""

import argparse
import struct
import json
import zlib
import numpy as np
import os
import sys
import shutil
from numba import jit
from tqdm import tqdm
from multiprocessing import Pool, cpu_count

# Add local directory to path FIRST
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
# Add parent directory to path for normalise_block import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from normalise_block import normalise_block

try:
    from erode_city_ultra import UltraFastEroder
except ImportError:
    print("WARNING: Could not import 'erode_city_ultra.py'.")
    sys.exit(1)

# ==========================================
# 1. CONFIGURATION
# ==========================================

# HARD TERRAIN: Delete on sight (The crust)
HARD_TERRAIN = {
    "minecraft:stone", "minecraft:granite", "minecraft:diorite", "minecraft:andesite",
    "minecraft:deepslate", "minecraft:tuff", "minecraft:calcite", "minecraft:bedrock",
    "minecraft:iron_ore", "minecraft:coal_ore", "minecraft:copper_ore", "minecraft:gold_ore",
    "minecraft:diamond_ore", "minecraft:redstone_ore", "minecraft:lapis_ore", "minecraft:emerald_ore",
    "minecraft:deepslate_iron_ore", "minecraft:deepslate_coal_ore", "minecraft:deepslate_copper_ore",
    "minecraft:deepslate_gold_ore", "minecraft:deepslate_redstone_ore", "minecraft:deepslate_lapis_ore",
    "minecraft:deepslate_diamond_ore", "minecraft:deepslate_emerald_ore", "minecraft:cobbled_deepslate"
}

# SOFT TERRAIN: Apply Thinning Logic
SOFT_TERRAIN = {
    "minecraft:dirt", "minecraft:grass_block", "minecraft:coarse_dirt", "minecraft:podzol", 
    "minecraft:rooted_dirt", "minecraft:sand", "minecraft:red_sand", "minecraft:clay", 
    "minecraft:gravel", "minecraft:mud", "minecraft:moss_block", "minecraft:mycelium",
    "minecraft:soul_sand", "minecraft:soul_soil", "minecraft:snow", "minecraft:snow_block"
}

# FLUIDS: Delete
FLUIDS = {
    "minecraft:water", "minecraft:lava", "minecraft:bubble_column"
}

VEGETATION_OPTIONS = [
    ("minecraft:seagrass", 50), ("minecraft:tall_seagrass", 30),
    ("minecraft:kelp_plant", 40), ("minecraft:sea_pickle", 15),
    ("minecraft:tube_coral", 5), ("minecraft:brain_coral", 5)
]

MIN_BLOCKS_THRESHOLD = 5 # If chunk has < 5 blocks total after purge, discard

# ==========================================
# 2. NUMBA KERNELS
# ==========================================

@jit(nopython=True)
def thinning_purge(blocks, hard_mask, soft_mask, fluid_mask, air_idx, H):
    """
    Scans chunk.
    - Hard/Fluid -> Delete.
    - Soft -> Delete if blocked above by more terrain. Keep if exposed to Air/City.
    """
    for x in range(16):
        for z in range(16):
            # Scan Bottom-Up
            for y in range(H):
                idx = blocks[x, y, z]
                if idx == 0 or idx == air_idx: continue
                
                # 1. Check Hard/Fluid
                is_hard = (idx < len(hard_mask) and hard_mask[idx])
                is_fluid = (idx < len(fluid_mask) and fluid_mask[idx])
                
                if is_hard or is_fluid:
                    blocks[x, y, z] = 0
                    continue
                
                # 2. Check Soft Thinning
                # "Penetrate until it finds air or valid city block"
                if idx < len(soft_mask) and soft_mask[idx]:
                    # Look at block above
                    if y + 1 < H:
                        above_idx = blocks[x, y+1, z]
                        
                        # Is above Air?
                        is_above_air = (above_idx == 0 or above_idx == air_idx)
                        
                        # Is above Terrain? (Hard or Soft or Fluid)
                        is_above_hard = (above_idx < len(hard_mask) and hard_mask[above_idx])
                        is_above_soft = (above_idx < len(soft_mask) and soft_mask[above_idx])
                        is_above_fluid = (above_idx < len(fluid_mask) and fluid_mask[above_idx])
                        is_above_terrain = is_above_hard or is_above_soft or is_above_fluid
                        
                        # Logic:
                        # If above is Air -> KEEP (It's surface)
                        # If above is City (Not Terrain, Not Air) -> KEEP (It's foundation)
                        # If above is Terrain -> DELETE (It's buried filler)
                        
                        if is_above_terrain:
                            blocks[x, y, z] = 0
                    else:
                        # Top of chunk, keep it safe
                        pass

    return blocks

@jit(nopython=True)
def populate_vegetation(blocks, veg_ids, veg_weights, seed, density, air_idx, H):
    if len(veg_ids) == 0: return blocks
    state = seed
    for x in range(16):
        for z in range(16):
            # Scan top-down
            for y in range(H - 2, 0, -1):
                if blocks[x, y, z] != air_idx and blocks[x, y+1, z] == air_idx:
                    state = (state * 1103515245 + 12345) & 0x7FFFFFFF
                    if (state / 2147483648.0) < density:
                        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
                        pick = (state / 2147483648.0) * 100.0
                        cum = 0.0
                        chosen = veg_ids[0]
                        for i in range(len(veg_weights)):
                            cum += veg_weights[i]
                            if pick <= cum:
                                chosen = veg_ids[i]
                                break
                        blocks[x, y+1, z] = chosen
                    break
    return blocks

# ==========================================
# 3. WORKER LOGIC
# ==========================================

class WorkerCtx:
    eroder = None
    hard_mask = None
    soft_mask = None
    fluid_mask = None
    veg_ids = None
    veg_weights = None
    air_id = 0

def init_worker(config, palette):
    global ctx
    ctx = WorkerCtx()
    ctx.eroder = UltraFastEroder(config)
    
    # Masks
    MAX_ID = 65536
    ctx.hard_mask = np.zeros(MAX_ID, dtype=np.bool_)
    ctx.soft_mask = np.zeros(MAX_ID, dtype=np.bool_)
    ctx.fluid_mask = np.zeros(MAX_ID, dtype=np.bool_)
    
    for i, name in enumerate(palette):
        if name in HARD_TERRAIN: ctx.hard_mask[i] = True
        elif name in SOFT_TERRAIN: ctx.soft_mask[i] = True
        elif name in FLUIDS: ctx.fluid_mask[i] = True
        if name == "minecraft:air": ctx.air_id = i

    # Veg
    p_map = {n: i for i, n in enumerate(palette)}
    v_ids, v_w = [], []
    for n, w in VEGETATION_OPTIONS:
        if n in p_map:
            v_ids.append(p_map[n])
            v_w.append(float(w))
    if v_ids:
        ctx.veg_ids = np.array(v_ids, dtype=np.int32)
        ctx.veg_weights = np.array(v_w, dtype=np.float64)
    else:
        ctx.veg_ids = np.array([], dtype=np.int32)
        ctx.veg_weights = np.array([], dtype=np.float64)

def process_chunk_safe(args):
    cx, cz, raw_data, height, palette_snapshot = args
    local_palette = list(palette_snapshot)
    
    try:
        blocks = np.frombuffer(zlib.decompress(raw_data), dtype=np.uint16).reshape((16, height, 16)).copy()
    except: return None

    # 1. THINNING PURGE
    blocks = thinning_purge(blocks, ctx.hard_mask, ctx.soft_mask, ctx.fluid_mask, ctx.air_id, height)
    
    if np.count_nonzero(blocks) < MIN_BLOCKS_THRESHOLD: return None

    # 2. EROSION
    try:
        blocks, local_palette = ctx.eroder.process_chunk(blocks, local_palette, cx, cz)
    except: return None

    # NORMALIZE LOCAL PALETTE AFTER EROSION
    # Erosion may add unnormalized blocks from config, so normalize them now
    normalized_palette = []
    for block_name in local_palette:
        normalized_id, _ = normalise_block(block_name, {})
        normalized_palette.append(normalized_id)
    local_palette = normalized_palette

    # 3. POPULATE
    if len(ctx.veg_ids) > 0:
        chunk_seed = (cx * 99) ^ (cz * 77) ^ 101
        blocks = populate_vegetation(blocks, ctx.veg_ids, ctx.veg_weights, chunk_seed, 0.2, ctx.air_id, height)

    new_raw = zlib.compress(blocks.tobytes())
    return (cx, cz, new_raw, height, local_palette)

# ==========================================
# 4. MAIN
# ==========================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--workers", type=int, default=cpu_count())
    args = parser.parse_args()
    
    if os.path.exists(args.out_dir): shutil.rmtree(args.out_dir)
    os.makedirs(args.out_dir)
    
    print("Loading Config & Header...")
    with open(args.config) as f: config = json.load(f)
    
    chunks = []
    with open(args.input, 'rb') as f:
        f.read(4)
        ptr = struct.unpack('<Q', f.read(8))[0]
        f.seek(ptr)
        global_palette = json.loads(f.read().decode('utf-8'))
        f.seek(12)
        
        # Pre-seed palette
        p_set = set(global_palette)
        for v, _ in VEGETATION_OPTIONS:
            if v not in p_set:
                global_palette.append(v)
                p_set.add(v)
        
        pbar = tqdm(desc="Scanning", unit="chk")
        while f.tell() < ptr:
            head = f.read(16)
            if len(head) < 16: break
            cx, cz, r_len, c_len = struct.unpack('<iiiI', head)
            chunks.append((cx, cz, f.read(c_len), r_len // 512))
            pbar.update(1)

    print(f"Thinning & Eroding {len(chunks)} chunks...")
    manifest = {"shards": [], "stats": {}}
    saved = 0
    
    tasks = [(c[0], c[1], c[2], c[3], global_palette) for c in chunks]
    
    with Pool(args.workers, initializer=init_worker, initargs=(config, global_palette)) as pool:
        for res in tqdm(pool.imap_unordered(process_chunk_safe, tasks), total=len(tasks)):
            if res is None: continue
            
            cx, cz, raw, h, pal = res
            
            if len(pal) > len(global_palette):
                for b in pal[len(global_palette):]:
                    if b not in p_set:
                        global_palette.append(b)
                        p_set.add(b)
            
            fname = f"shard_{cx}_{cz}.bin"
            with open(os.path.join(args.out_dir, fname), 'wb') as f:
                f.write(struct.pack('<iiiI', cx, cz, h, len(raw)))
                f.write(raw)
            
            manifest["shards"].append({"x": cx, "z": cz, "file": fname})
            saved += 1

    manifest["palette"] = global_palette
    with open(os.path.join(args.out_dir, "manifest.json"), 'w') as f:
        json.dump(manifest, f)
        
    print(f"\nSaved {saved} shards.")

if __name__ == "__main__":
    main()