
# extract_city.py

# Extracts a Minecraft region to a compressed binary format.
# Optimized to filter out underground terrain to save space.

# Usage:
#     python SunkenCityProject/extract_city.py --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\Weston City V0.3" --bounds -1500 -1600 1500 1600 --min-y 30 --prune-terrain --out city_original.bin
#
# Note: No hardcoded size limits. Extract areas as large as needed.
# Bounds format: x1 z1 x2 z2 (in block coordinates)
# Example: --bounds -1000 -1600 1000 1600 extracts 2000x3200 area
# Example: --bounds -3000 -3000 3000 3000 extracts 6000x6000 area

"""
Extracts Minecraft regions to compressed binary format.
Optimized for memory stability on massive datasets (30k+ chunks).

Changes from original:
1. Implements aggressive Garbage Collection (GC) to prevent RAM creep.
2. Optimizes string lookups to reduce CPU overhead.
3. Inlines writing logic to prevent generator buffering issues.
"""

import argparse
import numpy as np
import amulet
import sys
import os
import warnings
import struct
import json
import zlib
import gc
import time
from tqdm import tqdm

# Suppress warnings
warnings.filterwarnings("ignore")

# Add parent directory to path to import normalise_block
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from normalise_block import normalise_block
except ImportError:
    print("Warning: normalise_block.py not found. Using fallback normalization.")
    def normalise_block(block_id, props):
        return block_id, props

# Terrain to prune
TERRAIN_BLOCKS = {
    "minecraft:bedrock",
    "minecraft:deepslate",
    "minecraft:tuff",
    "minecraft:andesite",
    "minecraft:diorite",
    "minecraft:granite",
    "minecraft:gravel",
    "minecraft:dirt",
}

class CityExtractor:
    def __init__(self, world_path, prune_terrain=False, ignore_blocks=None):
        self.world_path = world_path
        self.prune_terrain = prune_terrain
        self.ignored_blocks = set(TERRAIN_BLOCKS) if prune_terrain else set()
        if ignore_blocks:
            self.ignored_blocks.update(ignore_blocks)
            
        # Global Palette: Maps "minecraft:stone" -> 1
        self.palette = ["minecraft:air"]
        self.p_map = {"minecraft:air": 0}
        
        # Memoization for string parsing
        self.normalize_cache = {}

    def _get_id_fast(self, raw_name):
        """
        Optimized ID lookup. 
        Uses caching to avoid string parsing on repeat blocks.
        """
        # 1. Check if we have seen this exact block string before
        # This bypasses all string splitting logic for 99% of calls
        norm_name = self.normalize_cache.get(raw_name)
        
        if norm_name is None:
            # SLOW PATH: First time seeing this block state
            temp_name = raw_name
            if "universal_minecraft:" in temp_name:
                temp_name = temp_name.replace("universal_minecraft:", "minecraft:")
            elif "universal_" in temp_name:
                temp_name = temp_name.replace("universal_", "")
                
            block_id = temp_name.split("[")[0]
            
            # Parse properties
            props = {}
            if "[" in temp_name:
                try:
                    state_str = temp_name.split("[", 1)[1].rstrip("]")
                    for pair in state_str.split(","):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            props[k.strip()] = v.strip()
                except:
                    pass

            # Normalize using user's helper
            norm_id, _ = normalise_block(block_id, props)
            
            # Check ignore list
            if norm_id in self.ignored_blocks:
                self.normalize_cache[raw_name] = "IGNORE"
                return 0
            
            norm_name = norm_id
            self.normalize_cache[raw_name] = norm_name

        # 2. Return 0 if it was marked as ignored
        if norm_name == "IGNORE":
            return 0

        # 3. Map to Integer ID
        # fast dict lookup
        pid = self.p_map.get(norm_name)
        if pid is not None:
            return pid
            
        # New block type found, add to palette
        pid = len(self.palette)
        self.palette.append(norm_name)
        self.p_map[norm_name] = pid
        return pid

    def run(self, bounds, output_path, min_y, max_y):
        print(f"Loading world: {self.world_path}")
        try:
            level = amulet.load_level(self.world_path)
        except Exception as e:
            print(f"Failed to load world: {e}")
            return

        x1, z1, x2, z2 = bounds
        cx1, cx2 = x1 >> 4, x2 >> 4
        cz1, cz2 = z1 >> 4, z2 >> 4
        
        total_chunks = (cx2 - cx1 + 1) * (cz2 - cz1 + 1)
        print(f"Target Area: {total_chunks} chunks ({cx1},{cz1} to {cx2},{cz2})")
        print(f"Output: {output_path}")

        # Prepare File Header
        f = open(output_path, 'wb')
        f.write(b'EROS')
        f.write(struct.pack('<Q', 0)) # Placeholder for palette ptr
        
        chunks_saved = 0
        chunks_processed = 0
        
        # World limits
        WORLD_MIN_Y = -64
        WORLD_HEIGHT = 384
        
        # Pre-calculate cutoff index
        cutoff_idx = max(0, min_y - WORLD_MIN_Y)
        
        t_start = time.time()
        
        # Main Loop
        pbar = tqdm(total=total_chunks, unit="chunk")
        
        for cx in range(cx1, cx2 + 1):
            for cz in range(cz1, cz2 + 1):
                chunks_processed += 1
                
                try:
                    # Load chunk
                    chunk = level.get_chunk(cx, cz, "minecraft:overworld")
                    
                    # Materialize Block Array (Copies to RAM)
                    # We slice [:, 0:384, :] to get the full vertical column
                    blocks_raw = chunk.blocks[:, 0:WORLD_HEIGHT, :]
                    
                    # 1. Build Local Look-Up Table (LUT)
                    # Maps chunk's internal IDs -> Our Global IDs
                    # This replaces the slow list comprehension with a cached loop
                    local_palette = chunk.block_palette
                    lut = np.zeros(len(local_palette), dtype=np.uint16)
                    
                    for i, block_obj in enumerate(local_palette):
                        lut[i] = self._get_id_fast(block_obj.namespaced_name)
                    
                    # 2. Vectorized Translation (Fastest part)
                    # Use NumPy advanced indexing to translate the whole array at once
                    global_blocks = lut[blocks_raw] # Implicitly casts to uint16
                    
                    # 3. Apply Min-Y Cutoff
                    if cutoff_idx > 0:
                        global_blocks[:, :cutoff_idx, :] = 0
                    
                    # 4. Compress & Write immediately
                    # We do not yield. We write now to clear RAM.
                    raw_bytes = global_blocks.tobytes()
                    comp_bytes = zlib.compress(raw_bytes)
                    
                    f.write(struct.pack('<iiiI', cx, cz, len(raw_bytes), len(comp_bytes)))
                    f.write(comp_bytes)
                    
                    chunks_saved += 1
                    
                    # 5. MEMORY MANAGEMENT
                    # Delete Amulet's cached chunk
                    key = (cx, cz, "minecraft:overworld")
                    if hasattr(level, "_chunks") and key in level._chunks:
                        del level._chunks[key]
                        
                except Exception as e:
                    if "ChunkDoesNotExist" not in str(e):
                        # Only print real errors
                        tqdm.write(f"Error at {cx},{cz}: {e}")
                
                pbar.update(1)
                
                # 6. CRITICAL: Force Garbage Collection
                # Every 500 chunks, force Python to clean up fragmentation.
                # This prevents the "25GB RAM" death spiral.
                if chunks_processed % 500 == 0:
                    gc.collect()

        pbar.close()
        
        # Write Palette at end of file
        print("Writing palette...")
        palette_ptr = f.tell()
        f.write(json.dumps(self.palette).encode('utf-8'))
        
        # Update pointer
        f.seek(4)
        f.write(struct.pack('<Q', palette_ptr))
        f.close()
        level.close()
        
        print("="*50)
        print(f"Done! Saved {chunks_saved} chunks.")
        print(f"Palette size: {len(self.palette)} unique blocks.")
        print(f"Time: {(time.time() - t_start):.1f}s")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", required=True)
    parser.add_argument("--out", default="city_original.bin")
    parser.add_argument("--bounds", nargs=4, type=int, required=True, metavar=('x1', 'z1', 'x2', 'z2'))
    parser.add_argument("--min-y", type=int, default=-64)
    parser.add_argument("--max-y", type=int, default=320)
    parser.add_argument("--prune-terrain", action="store_true")
    parser.add_argument("--ignore-blocks", nargs="*", default=[])

    args = parser.parse_args()

    extractor = CityExtractor(
        args.world, 
        prune_terrain=args.prune_terrain, 
        ignore_blocks=args.ignore_blocks
    )
    
    extractor.run(args.bounds, args.out, args.min_y, args.max_y)

if __name__ == "__main__":
    main()