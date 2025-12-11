
# extract_city.py

# Extracts a Minecraft region to a compressed binary format.
# Optimized to filter out underground terrain to save space.

# Usage:
#     python SunkenCityProject/extract_city.py --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\Weston City V0.3" --bounds -1500 -1600 1500 1600 --min-y 50 --prune-terrain --out city_original.bin
#
# Note: No hardcoded size limits. Extract areas as large as needed.
# Bounds format: x1 z1 x2 z2 (in block coordinates)
# Example: --bounds -1000 -1600 1000 1600 extracts 2000x3200 area
# Example: --bounds -3000 -3000 3000 3000 extracts 6000x6000 area


import argparse
import numpy as np
import amulet
import traceback
import sys
import os
import warnings
from tqdm import tqdm
from city_utils import write_bin

# Suppress Amulet's NBT encoding warnings (harmless format variations)
warnings.filterwarnings("ignore", message=".*Encoded long array.*")
warnings.filterwarnings("ignore", category=UserWarning, module="amulet.*")

# Add parent directory to path to import normalise_block
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from normalise_block import normalise_block

# Blocks that are almost certainly useless underground filler
TERRAIN_BLOCKS = {
    "minecraft:bedrock",
}

# Cache for normalized block names
_normalize_cache = {}

def normalize_name(name):
    """Convert Amulet block names to valid Minecraft IDs (cached)."""
    if name in _normalize_cache:
        return _normalize_cache[name]
    
    original_name = name
    
    if "universal_minecraft:" in name:
        name = name.replace("universal_minecraft:", "minecraft:")
    
    # Split off block states
    block_id = name.split("[")[0]
    
    # Parse block states if present
    props = {}
    if "[" in name:
        state_str = name.split("[", 1)[1].rstrip("]")
        for pair in state_str.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                props[k.strip()] = v.strip()
    
    # Use normalise_block to convert generic names to specific ones
    # e.g., minecraft:planks -> minecraft:oak_planks
    normalized_id, _ = normalise_block(block_id, props)
    
    _normalize_cache[original_name] = normalized_id
    return normalized_id

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", required=True)
    parser.add_argument("--out", default="city_original.bin")
    parser.add_argument("--bounds", nargs=4, type=int, required=True, metavar=('x1', 'z1', 'x2', 'z2'))
    
    parser.add_argument("--min-y", type=int, default=-64, 
                        help="Blocks below this Y level will be forced to Air.")
    parser.add_argument("--prune-terrain", action="store_true", 
                        help="If set, removes bedrock, deepslate, ores, etc.")
    parser.add_argument("--ignore-blocks", nargs="*", default=[], 
                        help="Additional blocks to remove (e.g. minecraft:stone)")

    args = parser.parse_args()

    # Build the Ignore Set
    ignored_blocks = set()
    if args.prune_terrain:
        ignored_blocks.update(TERRAIN_BLOCKS)
    
    for b in args.ignore_blocks:
        ignored_blocks.add(b)

    print(f"Loading world: {args.world}")
    level = amulet.load_level(args.world)
    
    # Palette Init (0 is always Air)
    palette = ["minecraft:air"]
    p_map = {"minecraft:air": 0}

    def get_id(name):
        name = normalize_name(name)
        if name in ignored_blocks:
            return 0
        if name not in p_map:
            p_map[name] = len(palette)
            palette.append(name)
        return p_map[name]

    def chunk_gen():
        x1, z1, x2, z2 = args.bounds
        cx1, cx2 = x1 >> 4, x2 >> 4
        cz1, cz2 = z1 >> 4, z2 >> 4
        
        total = (cx2 - cx1 + 1) * (cz2 - cz1 + 1)
        print(f"Extracting {total} chunks...")
        
        processed = 0
        success_count = 0
        
        for cx in range(cx1, cx2 + 1):
            for cz in range(cz1, cz2 + 1):
                processed += 1
                try:
                    # 'minecraft:overworld' is the standard dimension ID
                    chunk = level.get_chunk(cx, cz, "minecraft:overworld")
                    
                    # 1. Get raw block indices (16, Height, 16) - already numpy
                    blocks_idx = chunk.blocks
                    
                    # 2. Build Lookup Table (LUT) - vectorized
                    local_p = chunk.block_palette
                    lut = np.array([get_id(b.namespaced_name) for b in local_p], dtype=np.uint16)
                        
                    # 3. Translate to Global Palette
                    global_blocks = lut[blocks_idx]
                    
                    # 4. Apply Min-Y Filter (Hard Cutoff)
                    # Amulet chunks (1.18+) usually start at Y=-64. 
                    # blocks_idx[x, y, z]. If we want to cut off below args.min_y:
                    # We need to know where the chunk starts.
                    # chunk.coordinates gives (cx, cz). 
                    # But the vertical range is implicit in the array size for AnvilChunk.
                    # Usually index 0 = Y min (-64 for 1.18, 0 for 1.16).
                    
                    # Calculate offset
                    # If arg.min_y is 0, and world bottom is -64, we zero out indices 0 to 64.
                    # Amulet generally exposes the lowest Y. Assuming standard 1.18 world:
                    chunk_min_y = -64 # This is an assumption for standard 1.18+ worlds
                    
                    # Calculate the index in the array corresponding to the cutoff Y
                    cutoff_index = args.min_y - chunk_min_y
                    
                    if cutoff_index > 0:
                        # Safety clip
                        cutoff_index = min(cutoff_index, global_blocks.shape[1])
                        # Set everything below cutoff to 0 (Air)
                        global_blocks[:, :cutoff_index, :] = 0
                    
                    yield cx, cz, global_blocks
                    success_count += 1
                    
                except Exception as e:
                    # If it's just a missing chunk, ignore it silently-ish
                    if "ChunkDoesNotExist" in str(e):
                        continue
                    # If it's a real error, print it so we know!
                    print(f"\n[Error] Chunk {cx},{cz} failed: {e}")
                    # traceback.print_exc()
                    continue
                
                if processed % 100 == 0:
                    print(f"  Processed {processed}/{total} (Saved: {success_count})...", end='\r')

    write_bin(args.out, chunk_gen(), palette)

if __name__ == "__main__":
    main()