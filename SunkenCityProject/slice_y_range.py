"""
slice_y_range.py

Extract only a specific Y-range from a .bin file to reduce file size.

Usage:
    python SunkenCityProject/slice_y_range.py \
        --input city_exposed.bin \
        --output city_exposed_slim.bin \
        --y-min 40 --y-max 80
"""

import argparse
import numpy as np
from tqdm import tqdm
from city_utils import read_bin_generator, write_bin


def main():
    parser = argparse.ArgumentParser(description="Slice Y-range from .bin file")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--output", required=True, help="Output .bin file")
    parser.add_argument("--y-min", type=int, required=True, help="Minimum Y level (inclusive)")
    parser.add_argument("--y-max", type=int, required=True, help="Maximum Y level (exclusive)")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("Y-RANGE SLICER")
    print("=" * 70)
    print(f"\n📂 Input: {args.input}")
    print(f"📂 Output: {args.output}")
    print(f"📏 Y-range: {args.y_min} to {args.y_max} ({args.y_max - args.y_min} blocks tall)\n")
    
    # Build new palette
    palette = ["minecraft:air"]
    p_map = {"minecraft:air": 0}
    
    def get_id(block_name):
        if block_name not in p_map:
            p_map[block_name] = len(palette)
            palette.append(block_name)
        return p_map[block_name]
    
    def chunk_gen():
        total_chunks = 0
        
        # First pass to count
        for _ in read_bin_generator(args.input):
            total_chunks += 1
        
        # Second pass to slice
        for cx, cz, blocks, old_palette in tqdm(
            read_bin_generator(args.input), 
            total=total_chunks, 
            desc="Slicing chunks", 
            unit="chunk"
        ):
            # Slice Y-range
            sliced = blocks[:, args.y_min:args.y_max, :]
            
            # Remap to new palette
            remapped = np.zeros_like(sliced, dtype=np.uint16)
            for old_idx, block_name in enumerate(old_palette):
                new_idx = get_id(block_name)
                remapped[sliced == old_idx] = new_idx
            
            yield cx, cz, remapped
    
    write_bin(args.output, chunk_gen(), palette)
    
    print("\n" + "=" * 70)
    print("SLICING COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {args.output}")
    print(f"✓ Palette: {len(palette)} block types")


if __name__ == "__main__":
    main()
