"""
adjust_city_height.py

Shift city blocks to target ocean bed height without merging with terrain.
This is much simpler and faster than extracting/merging terrain.

Usage:
    python SunkenCityProject/adjust_city_height.py \
        --input city_exposed.bin \
        --output city_positioned.bin \
        --target-y 60 \
        --city-median 67
"""

import argparse
import numpy as np
from tqdm import tqdm
from city_utils import read_bin_generator, write_bin


def main():
    parser = argparse.ArgumentParser(description="Adjust city height to target Y level")
    parser.add_argument("--input", required=True, help="Input city .bin file")
    parser.add_argument("--output", required=True, help="Output .bin file")
    parser.add_argument("--target-y", type=int, required=True, 
                        help="Target Y level for city (e.g., ocean bed at 60)")
    parser.add_argument("--city-median", type=int, default=67,
                        help="Current median Y of city blocks (default: 67)")
    parser.add_argument("--min-y", type=int, default=40,
                        help="Minimum Y to include in output (default: 40)")
    parser.add_argument("--max-y", type=int, default=170,
                        help="Maximum Y to include in output (default: 170)")
    
    args = parser.parse_args()
    
    # Calculate shift
    y_shift = args.target_y - args.city_median
    output_min = args.min_y
    output_max = args.max_y
    output_height = output_max - output_min
    
    print("=" * 70)
    print("CITY HEIGHT ADJUSTMENT")
    print("=" * 70)
    print(f"\n📂 Input: {args.input}")
    print(f"📂 Output: {args.output}")
    print(f"📏 City median: Y={args.city_median}")
    print(f"📏 Target: Y={args.target_y}")
    print(f"📏 Shift: {y_shift:+d} blocks")
    print(f"📏 Output range: Y={output_min} to Y={output_max} ({output_height} blocks)\n")
    
    # Build palette
    palette = []
    palette_map = {}
    
    def get_id(block_name):
        if block_name not in palette_map:
            palette_map[block_name] = len(palette)
            palette.append(block_name)
        return palette_map[block_name]
    
    # Pre-register air
    air_idx = get_id("minecraft:air")
    
    def chunk_gen():
        total = sum(1 for _ in read_bin_generator(args.input))
        
        for cx, cz, blocks, old_palette in tqdm(
            read_bin_generator(args.input),
            total=total,
            desc="Adjusting height",
            unit="chunk"
        ):
            # Create output array
            output = np.full((16, output_height, 16), air_idx, dtype=np.uint16)
            
            # Map old palette to new
            remap = np.array([get_id(name) for name in old_palette], dtype=np.uint16)
            
            # Copy blocks with Y-shift
            for old_y in range(blocks.shape[1]):
                world_y = old_y - 64  # Array index to world Y
                new_world_y = world_y + y_shift  # Shift
                new_y = new_world_y - output_min  # World Y to output array index
                
                # Check if in output range
                if 0 <= new_y < output_height:
                    # Copy the slice
                    output[:, new_y, :] = remap[blocks[:, old_y, :]]
            
            yield cx, cz, output
    
    write_bin(args.output, chunk_gen(), palette)
    
    print("\n" + "=" * 70)
    print("HEIGHT ADJUSTMENT COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {args.output}")
    print(f"✓ Palette: {len(palette)} block types")
    print(f"\n💡 Next: Run blend_underwater.py to integrate with ocean terrain")


if __name__ == "__main__":
    main()
