r"""
extract_terrain.py

Extracts terrain chunks from target Minecraft world for merging.
This gets the "destination" chunks where the city will be placed.

Usage:
    python SunkenCityProject/extract_terrain.py \
        --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" \
        --bounds -1500 -1600 1500 1600 \
        --output terrain_extracted.bin
        
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
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("TERRAIN EXTRACTION")
    print("=" * 70)
    print(f"\n🌍 World: {args.world}")
    print(f"📏 Bounds: {args.bounds}")
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
    
    def chunk_gen():
        x1, z1, x2, z2 = args.bounds
        cx1, cx2 = x1 >> 4, x2 >> 4
        cz1, cz2 = z1 >> 4, z2 >> 4
        
        total = (cx2 - cx1 + 1) * (cz2 - cz1 + 1)
        print(f"Extracting {total:,} chunks...")
        
        processed = 0
        success_count = 0
        
        for cx in range(cx1, cx2 + 1):
            for cz in range(cz1, cz2 + 1):
                processed += 1
                try:
                    chunk = level.get_chunk(cx, cz, args.dimension)
                    
                    # Get block array (already numpy)
                    blocks_idx = chunk.blocks
                    
                    # Build lookup table (vectorized)
                    local_p = chunk.block_palette
                    lut = np.array([get_id(b.namespaced_name) for b in local_p], dtype=np.uint16)
                    
                    # Translate to global palette (vectorized)
                    global_blocks = lut[blocks_idx]
                    
                    yield cx, cz, global_blocks
                    success_count += 1
                    
                except Exception as e:
                    if "ChunkDoesNotExist" in str(e):
                        # Create empty chunk (all air)
                        empty_chunk = np.zeros((16, 384, 16), dtype=np.uint16)
                        yield cx, cz, empty_chunk
                        success_count += 1
                    else:
                        print(f"\n[Error] Chunk {cx},{cz} failed: {e}")
                    continue
                
                if processed % 100 == 0:
                    print(f"  Processed {processed}/{total} ({success_count} saved)...", end='\r')
        
        print(f"\n✓ Extracted {success_count:,} chunks")
    
    write_bin(args.output, chunk_gen(), palette)
    
    print("\n" + "=" * 70)
    print("TERRAIN EXTRACTION COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {args.output}")
    print(f"✓ Palette: {len(palette)} block types")
    print("\n💡 Next: Run merge_chunks.py to combine with city")


if __name__ == "__main__":
    main()
