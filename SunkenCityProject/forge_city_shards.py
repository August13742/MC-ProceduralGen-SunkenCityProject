"""
forge_city_shards.py

1. Chunk-Wide Density Analysis: Finds the true 'Foundation Level' of the chunk.
2. Smart Purge: Removes deep terrain below the foundation, keeping the soil plug intact.
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

# Add local directory to path so we can import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Add parent directory to path for normalise_block import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from normalise_block import normalise_block

# Try importing your erosion engine
try:
    from erode_city_ultra import UltraFastEroder
except ImportError:
    print("WARNING: Could not import 'erode_city_ultra.py'.")
    print("Please ensure it is in the same folder as this script.")
    sys.exit(1)

# ==========================================
# 1. CONSTANTS
# ==========================================

# Blocks to treat as "Terrain" (will be purged below the foundation)
TERRAIN_BLOCKS = {
    "minecraft:stone", "minecraft:granite", "minecraft:diorite", "minecraft:andesite",
    "minecraft:deepslate", "minecraft:tuff", "minecraft:calcite", "minecraft:gravel",
    "minecraft:dirt", "minecraft:grass_block", "minecraft:coarse_dirt", "minecraft:podzol", 
    "minecraft:sand", "minecraft:red_sand", "minecraft:clay", "minecraft:water", "minecraft:lava",
    "minecraft:bedrock", "minecraft:iron_ore", "minecraft:coal_ore", "minecraft:copper_ore",
    "minecraft:oak_leaves", "minecraft:spruce_leaves", "minecraft:birch_leaves" # Treat leaves as purgeable terrain
}

# Blocks that count as "The City"
CITY_ANCHORS = {
    "concrete", "terracotta", "plank", "brick", "glass", "wool", "carpet", 
    "slab", "stairs", "fence", "door", "iron", "gold", "lantern", "lamp",
    "book", "chest", "furnace", "bed", "shulker", "quartz", "purpur", "prismarine",
    "stone_bricks", "polished", "cobblestone"
}

VEGETATION_OPTIONS = [
    ("minecraft:seagrass", 50), ("minecraft:tall_seagrass", 30),
    ("minecraft:kelp_plant", 40), ("minecraft:sea_pickle", 15),
    ("minecraft:tube_coral", 5), ("minecraft:brain_coral", 5)
]

FOUNDATION_BUFFER = 5     # Keep 5 blocks of stone below the lowest city block
MIN_CITY_BLOCKS = 30      # Threshold to consider a chunk "City"

# ==========================================
# 2. NUMBA KERNELS (Purge & Populate)
# ==========================================

@jit(nopython=True)
def analyze_and_purge(blocks, terrain_mask, anchor_mask, H):
    """
    1. Scan: Find the lowest Y level that contains significant city blocks.
    2. Purge: Delete all terrain blocks below (Lowest_Y - Buffer).
    Returns: The modified blocks and validity flag.
    """
    # Histogram of Anchor Y-levels
    y_counts = np.zeros(H, dtype=np.int32)
    total_anchors = 0
    mask_len = len(anchor_mask)
    
    # Single pass: count anchors and build histogram
    for y in range(H):
        for x in range(16):
            for z in range(16):
                idx = blocks[x, y, z]
                if idx == 0: 
                    continue
                # Check if anchor (with bounds check)
                if idx < mask_len and anchor_mask[idx]:
                    y_counts[y] += 1
                    total_anchors += 1

    # Filter: Is this chunk mostly nature?
    if total_anchors < MIN_CITY_BLOCKS:
        return blocks, False

    # Find the "City Floor" - first significant concentration of anchors
    count_accum = 0
    city_floor_y = 0
    threshold = max(5, int(total_anchors * 0.05))
    
    for y in range(H):
        count_accum += y_counts[y]
        if count_accum >= threshold:
            city_floor_y = y
            break
            
    cutoff_y = max(0, city_floor_y - FOUNDATION_BUFFER)

    # Execute Purge - delete terrain below cutoff
    if cutoff_y > 0:
        terrain_mask_len = len(terrain_mask)
        for y in range(cutoff_y):
            for x in range(16):
                for z in range(16):
                    idx = blocks[x, y, z]
                    # If terrain, delete
                    if idx > 0 and idx < terrain_mask_len and terrain_mask[idx]:
                        blocks[x, y, z] = 0
                        
    return blocks, True

@jit(nopython=True)
def populate_vegetation(blocks, veg_ids, veg_weights, seed, density, air_idx, H):
    """Adds underwater vegetation to top surfaces."""
    if len(veg_ids) == 0:
        return blocks
        
    state = seed
    num_choices = len(veg_weights)
    
    for x in range(16):
        for z in range(16):
            # Scan top-down to find first air-over-solid
            for y in range(H - 2, 0, -1):
                # Look for [Air] on top of [Solid]
                if blocks[x, y, z] != air_idx and blocks[x, y+1, z] == air_idx:
                    # RNG - density check
                    state = (state * 1103515245 + 12345) & 0x7FFFFFFF
                    if (state / 2147483648.0) < density:
                        # Weighted Choice
                        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
                        pick = (state / 2147483648.0) * 100.0
                        cum = 0.0
                        chosen = veg_ids[0]
                        
                        for i in range(num_choices):
                            cum += veg_weights[i]
                            if pick <= cum:
                                chosen = veg_ids[i]
                                break
                        blocks[x, y+1, z] = chosen
                    break # Only one plant per column
    return blocks

# ==========================================
# 3. WORKER LOGIC
# ==========================================

class WorkerContext:
    eroder = None
    terrain_mask = None
    anchor_mask = None
    veg_ids = None
    veg_weights = None
    air_id = 0

def init_worker(config, palette):
    global ctx
    ctx = WorkerContext()
    
    # 1. Initialize Erosion Engine
    ctx.eroder = UltraFastEroder(config)
    
    # 2. Normalize palette entries for compatibility
    normalized_palette = []
    for block_name in palette:
        normalized_id, _ = normalise_block(block_name, {})
        normalized_palette.append(normalized_id)
    palette[:] = normalized_palette  # Update in-place
    
    # 3. Build Masks - size to 65536 (max uint16) for safety
    ctx.terrain_mask = np.zeros(65536, dtype=np.bool_)
    ctx.anchor_mask = np.zeros(65536, dtype=np.bool_)
    
    # Vectorized mask building where possible
    for i, name in enumerate(palette):
        if name in TERRAIN_BLOCKS: 
            ctx.terrain_mask[i] = True
        
        # Check if any anchor keyword appears in block name
        name_lower = name.lower()
        if any(k in name_lower for k in CITY_ANCHORS):
            ctx.anchor_mask[i] = True
        
        if name == "minecraft:air": 
            ctx.air_id = i

    # 3. Prep Vegetation - build mapping
    p_map = {n: i for i, n in enumerate(palette)}
    v_ids = []
    v_weights = []
    
    for name, w in VEGETATION_OPTIONS:
        if name in p_map:
            v_ids.append(p_map[name])
            v_weights.append(float(w))
    
    # Only create arrays if we have vegetation
    if v_ids:
        ctx.veg_ids = np.array(v_ids, dtype=np.int32)
        ctx.veg_weights = np.array(v_weights, dtype=np.float64)
    else:
        ctx.veg_ids = np.array([], dtype=np.int32)
        ctx.veg_weights = np.array([], dtype=np.float64)

def process_chunk_safe(args):
    cx, cz, raw_data, height, palette_snapshot = args
    
    # Work on a local copy of the palette
    local_palette = list(palette_snapshot)
    
    # Decompress and validate
    try:
        decompressed = zlib.decompress(raw_data)
        expected_size = 16 * height * 16 * 2  # uint16
        if len(decompressed) != expected_size:
            return None
        blocks = np.frombuffer(decompressed, dtype=np.uint16).reshape((16, height, 16)).copy()
    except Exception:
        return None

    # --- STEP 1: PURGE ---
    # Delete deep terrain below city foundation
    blocks, keep = analyze_and_purge(blocks, ctx.terrain_mask, ctx.anchor_mask, height)
    if not keep:
        return None  # Discard empty/nature chunk

    # --- STEP 2: ERODE ---
    # Apply erosion physics
    try:
        blocks, local_palette = ctx.eroder.process_chunk(blocks, local_palette, cx, cz)
    except Exception:
        return None

    # --- STEP 3: POPULATE ---
    # Add underwater vegetation to exposed surfaces
    if len(ctx.veg_ids) > 0:
        # Use XOR for better seed distribution
        chunk_seed = (cx * 99) ^ (cz * 77) ^ 42
        blocks = populate_vegetation(
            blocks, ctx.veg_ids, ctx.veg_weights, 
            chunk_seed, 0.2, ctx.air_id, height
        )

    # --- PACK ---
    # Compress and return with local palette
    try:
        new_raw = zlib.compress(blocks.tobytes(), level=6)  # Balance speed/size
    except Exception:
        return None
        
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
        
        # Pre-seed palette with vegetation to ensure IDs exist
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

    print(f"Processing {len(chunks)} chunks with {args.workers} workers...")
    
    manifest = {"shards": [], "stats": {}}
    saved_count = 0
    discarded_count = 0
    
    # Prepare task arguments (each gets a copy of the pre-seeded palette)
    tasks = [(c[0], c[1], c[2], c[3], global_palette) for c in chunks]
    
    # Track new blocks added during processing
    new_blocks_added = set()
    
    with Pool(args.workers, initializer=init_worker, initargs=(config, global_palette)) as pool:
        # Use imap_unordered for better performance
        pbar = tqdm(pool.imap_unordered(process_chunk_safe, tasks, chunksize=max(1, len(tasks) // (args.workers * 4))), 
                    total=len(tasks), desc="Forging shards", unit="chunk")
        
        for result in pbar:
            if result is None:
                discarded_count += 1
                continue
                
            cx, cz, raw_bytes, height, chunk_palette = result
            
            # PALETTE MERGE - Maintain global palette consistency
            # Since workers start with same base palette and only append,
            # we just need to add any new blocks they discovered
            if len(chunk_palette) > len(global_palette):
                for block_name in chunk_palette[len(global_palette):]:
                    if block_name not in p_set:
                        global_palette.append(block_name)
                        p_set.add(block_name)
                        new_blocks_added.add(block_name)
            
            # Save shard to disk
            fname = f"shard_{cx}_{cz}.bin"
            shard_path = os.path.join(args.out_dir, fname)
            try:
                with open(shard_path, 'wb') as f:
                    f.write(struct.pack('<iiiI', cx, cz, height, len(raw_bytes)))
                    f.write(raw_bytes)
                
                manifest["shards"].append({"x": cx, "z": cz, "file": fname})
                saved_count += 1
            except Exception as e:
                print(f"\nError saving shard ({cx}, {cz}): {e}")
                discarded_count += 1
        
        pbar.close()

    # Save final global palette and statistics
    manifest["palette"] = global_palette
    manifest["stats"] = {
        "total_chunks": len(chunks),
        "saved_shards": saved_count,
        "discarded_chunks": discarded_count,
        "palette_size": len(global_palette),
        "new_blocks_added": len(new_blocks_added)
    }
    
    manifest_path = os.path.join(args.out_dir, "manifest.json")
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"FORGE COMPLETE")
    print(f"{'='*60}")
    print(f"  Total chunks processed: {len(chunks)}")
    print(f"  Shards saved: {saved_count}")
    print(f"  Chunks discarded: {discarded_count} ({100*discarded_count/len(chunks):.1f}%)")
    print(f"  Final palette size: {len(global_palette)} blocks")
    if new_blocks_added:
        print(f"  New blocks added: {len(new_blocks_added)}")
    print(f"  Output: {args.out_dir}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()