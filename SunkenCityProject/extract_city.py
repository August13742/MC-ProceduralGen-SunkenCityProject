
# extract_city.py

# Extracts a Minecraft region to a compressed binary format.
# Optimized to filter out underground terrain to save space.

# Usage:
#     python SunkenCityProject/extract_city.py --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\Weston City V0.3" --bounds -1000 -1600 1200 1200 --min-y 30 --out city_original.bin
#
# Note: No hardcoded size limits. Extract areas as large as needed.
# Bounds format: x1 z1 x2 z2 (in block coordinates)
# Example: --bounds -1000 -1600 1000 1600 extracts 2000x3200 area
# Example: --bounds -3000 -3000 3000 3000 extracts 6000x6000 area


import argparse
import numpy as np
import amulet
import sys
import os

# Add parent directory to path to import normalise_block
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from normalise_block import normalise_block
from city_utils import write_bin

# Useless underground blocks to save space
TERRAIN_BLOCKS = {
    "minecraft:bedrock",
    "minecraft:stone",
    "minecraft:granite",
    "minecraft:diorite",
    "minecraft:andesite",
    "minecraft:deepslate",
    "minecraft:tuff",
    "minecraft:dirt",
    "minecraft:gravel",
    "minecraft:water",
    "minecraft:lava"
}

_normalize_cache = {}

def normalize_name(name):
    """Convert Amulet block names to valid Minecraft IDs (cached)."""
    if name in _normalize_cache: return _normalize_cache[name]
    
    original_name = name
    if "universal_minecraft:" in name:
        name = name.replace("universal_minecraft:", "minecraft:")
    
    block_id = name.split("[")[0]
    props = {}
    if "[" in name:
        state_str = name.split("[", 1)[1].rstrip("]")
        for pair in state_str.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                props[k.strip()] = v.strip()
    
    normalized_id, _ = normalise_block(block_id, props)
    _normalize_cache[original_name] = normalized_id
    return normalized_id

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", required=True)
    parser.add_argument("--out", default="city_original.bin")
    parser.add_argument("--bounds", nargs=4, type=int, required=True, metavar=('x1', 'z1', 'x2', 'z2'))
    parser.add_argument("--min-y", type=int, default=-64, help="Lowest Y to save (Default -64)")
    parser.add_argument("--max-y", type=int, default=320, help="Highest Y to save (Default 320)")
    parser.add_argument("--prune-terrain", action="store_true", help="Remove stone/dirt/etc")
    
    args = parser.parse_args()

    ignored_blocks = set()
    if args.prune_terrain:
        ignored_blocks.update(TERRAIN_BLOCKS)

    print(f"Loading world: {args.world}")
    level = amulet.load_level(args.world)
    
    palette = ["minecraft:air"]
    p_map = {"minecraft:air": 0}

    def get_id(name):
        name = normalize_name(name)
        if name in ignored_blocks: return 0
        if name not in p_map:
            p_map[name] = len(palette)
            palette.append(name)
        return p_map[name]

    def chunk_gen():
        x1, z1, x2, z2 = args.bounds
        cx1, cx2 = x1 >> 4, x2 >> 4
        cz1, cz2 = z1 >> 4, z2 >> 4
        
        total = (cx2 - cx1 + 1) * (cz2 - cz1 + 1)
        print(f"Extracting {total} chunks (Height: {args.min_y} to {args.max_y})...")
        
        processed = 0
        success_count = 0
        
        # Determine slice indices relative to Y=0
        # Amulet Infinite chunks are accessed via slice objects
        # We want absolute coordinates from args.min_y to args.max_y
        
        for cx in range(cx1, cx2 + 1):
            for cz in range(cz1, cz2 + 1):
                processed += 1
                try:
                    chunk = level.get_chunk(cx, cz, "minecraft:overworld")
                    
                    # --- THE FIX: FORCE A SLICE ---
                    # Instead of chunk.blocks (which is inf), we request a specific range.
                    # This returns a standard numpy array of shape (16, Height, 16)
                    # Note: The 2nd dimension is Y.
                    
                    # Amulet's get_sub_chunk or direct slicing might behave differently depending on version.
                    # The most robust way for "inf" chunks in Amulet is using the 'blocks' property with a slice.
                    
                    # We slice from min_y to max_y.
                    # Note: We must handle if the chunk doesn't actually go that high/low, 
                    # but for 'inf' chunks, slicing usually returns air for empty space.
                    
                    # Slicing syntax: [x, y, z]
                    raw_blocks = chunk.blocks[:, args.min_y : args.max_y, :]
                    
                    # Check if we actually got data (not just air)
                    if np.all(raw_blocks == 0):
                        # It's an empty chunk, yield it as air but count it
                        pass 
                    
                    # 2. Build LUT
                    local_p = chunk.block_palette
                    lut = np.array([get_id(b.namespaced_name) for b in local_p], dtype=np.uint16)
                    
                    # 3. Translate
                    global_blocks = lut[raw_blocks]
                    
                    yield cx, cz, global_blocks
                    success_count += 1
                    
                except Exception as e:
                    if "ChunkDoesNotExist" not in str(e):
                        # print(f"\n[Error] Chunk {cx},{cz}: {e}")
                        pass
                    continue
                
                if processed % 50 == 0:
                    print(f"  Processed {processed}/{total}...", end='\r')

    write_bin(args.out, chunk_gen(), palette)
    print(f"\nDone! Saved to {args.out}")

if __name__ == "__main__":
    main()