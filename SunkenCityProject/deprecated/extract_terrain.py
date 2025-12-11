r"""
extract_terrain.py

Extracts terrain chunks from target Minecraft world for merging.
This gets the "destination" chunks where the city will be placed.

Usage:
    python SunkenCityProject/extract_terrain.py \
        --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" \
        --bounds -1500 -1600 1500 1600 \
        --output terrain_extracted.bin \
        --y-min 40 --y-max 80
        
    # For ocean floor at Y=60, extract Y=40-80 (20 below, 20 above)
    # This reduces file size 10x and speeds up merge/restore significantly!
        
python SunkenCityProject/extract_terrain.py --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_OCEAN_BACKUP" --bounds -1500 -1600 1500 1600 --output terrain_extracted.bin
"""

import argparse
import numpy as np
import amulet
import sys
import os
import warnings
from tqdm import tqdm

# Suppress Amulet warnings
warnings.filterwarnings("ignore", message=".*Encoded long array.*")
warnings.filterwarnings("ignore", category=UserWarning, module="amulet.*")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from city_utils import write_bin


def main():
    parser = argparse.ArgumentParser(description="Extract terrain from target world")
    parser.add_argument("--world", required=True, help="Path to Minecraft world")
    parser.add_argument("--bounds", nargs=4, type=int, required=True, 
                        metavar=('x1', 'z1', 'x2', 'z2'),
                        help="Extraction bounds (should match city bounds)")
    parser.add_argument("--output", default="terrain_extracted.bin", help="Output file")
    parser.add_argument("--dimension", default="minecraft:overworld", help="Dimension")
    parser.add_argument("--y-min", type=int, default=40, help="Minimum Y level to extract (default: 40)")
    parser.add_argument("--y-max", type=int, default=80, help="Maximum Y level to extract (default: 80)")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("TERRAIN EXTRACTION")
    print("=" * 70)
    print(f"\n🌍 World: {args.world}")
    print(f"📏 Bounds: {args.bounds}")
    print(f"📏 Y-range: {args.y_min} to {args.y_max} ({args.y_max - args.y_min} blocks tall)")
    print(f"📂 Output: {args.output}\n")
    
    level = amulet.load_level(args.world)
    
    # Palette
    palette = ["minecraft:air"]
    p_map = {"minecraft:air": 0}
    
    def get_id(block_name):
        if block_name not in p_map:
            p_map[block_name] = len(palette)
            palette.append(block_name)
        return p_map[block_name]
    
    # Cache LUTs for identical palettes (many chunks share same palette)
    lut_cache = {}
    
    def chunk_gen():
        x1, z1, x2, z2 = args.bounds
        cx1, cx2 = x1 >> 4, x2 >> 4
        cz1, cz2 = z1 >> 4, z2 >> 4
        
        total = (cx2 - cx1 + 1) * (cz2 - cz1 + 1)
        
        success_count = 0
        chunk_list = [(cx, cz) for cx in range(cx1, cx2 + 1) for cz in range(cz1, cz2 + 1)]
        
        with tqdm(total=total, desc="Extracting terrain", unit="chunk") as pbar:
            for cx, cz in chunk_list:
                try:
                    chunk = level.get_chunk(cx, cz, args.dimension)
                    
                    # Get block array - extract only requested Y range
                    blocks_idx = chunk.blocks[:, args.y_min:args.y_max, :]
                    
                    # Build lookup table (vectorized) - cache by palette object
                    local_p = chunk.block_palette
                    palette_key = id(local_p)
                    
                    if palette_key not in lut_cache:
                        lut_cache[palette_key] = np.array(
                            [get_id(b.namespaced_name) for b in local_p], 
                            dtype=np.uint16
                        )
                    
                    # Translate to global palette (vectorized)
                    global_blocks = lut_cache[palette_key][blocks_idx]
                    
                    yield cx, cz, global_blocks
                    success_count += 1
                    
                except Exception as e:
                    if "ChunkDoesNotExist" in str(e):
                        # Create empty chunk (all air) with requested height
                        empty_chunk = np.zeros((16, args.y_max - args.y_min, 16), dtype=np.uint16)
                        yield cx, cz, empty_chunk
                        success_count += 1
                    else:
                        tqdm.write(f"[Error] Chunk {cx},{cz} failed: {e}")
                    
                pbar.update(1)
        
        print(f"✓ Extracted {success_count:,} chunks")
    
    write_bin(args.output, chunk_gen(), palette)
    
    print("\n" + "=" * 70)
    print("TERRAIN EXTRACTION COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {args.output}")
    print(f"✓ Palette: {len(palette)} block types")
    print("\n💡 Next: Run merge_chunks.py to combine with city")


if __name__ == "__main__":
    main()
