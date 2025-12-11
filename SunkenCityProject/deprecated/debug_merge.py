"""
debug_merge.py

Debug version of merge to see what's actually happening.
"""

import argparse
import numpy as np
from city_utils import read_bin_generator
from collections import Counter


def debug_merge(city_file, terrain_file, city_y=-71):
    """Debug the merge process to see what's happening."""
    
    print(f"=" * 70)
    print("DEBUG MERGE")
    print(f"=" * 70)
    print(f"City file: {city_file}")
    print(f"Terrain file: {terrain_file}")
    print(f"City Y offset: {city_y}")
    print()
    
    # Load first chunk from each
    print("Loading first chunk from city...")
    city_chunk = None
    for cx, cz, blocks, palette in read_bin_generator(city_file):
        # Find first non-empty chunk
        air_idx = 0
        for i, name in enumerate(palette):
            if 'air' in name.lower():
                air_idx = i
                break
        
        non_air = np.sum(blocks != air_idx)
        if non_air > 100:  # At least 100 non-air blocks
            city_chunk = (cx, cz, blocks, palette)
            print(f"  Found chunk at ({cx}, {cz}) with {non_air:,} non-air blocks")
            break
    
    if not city_chunk:
        print("  ❌ No city chunks with content found!")
        return
    
    cx, cz, city_blocks, city_palette = city_chunk
    
    print("\n  City chunk details:")
    print(f"    Shape: {city_blocks.shape}")
    print(f"    Palette size: {len(city_palette)}")
    
    # Find Y range of city blocks
    air_idx = 0
    for i, name in enumerate(city_palette):
        if 'air' in name.lower():
            air_idx = i
            break
    
    city_heights = []
    for x in range(16):
        for z in range(16):
            for y in range(city_blocks.shape[1]):
                if city_blocks[x, y, z] != air_idx:
                    city_heights.append(y)
    
    if city_heights:
        print(f"    City Y range (array indices): {min(city_heights)} to {max(city_heights)}")
        print(f"    City Y range (world coords): {min(city_heights)-64} to {max(city_heights)-64}")
        
        # Show distribution
        unique, counts = np.unique(city_heights, return_counts=True)
        print(f"    Most common Y levels:")
        sorted_y = sorted(zip(counts, unique), reverse=True)[:5]
        for count, y in sorted_y:
            print(f"      Y={y} (world {y-64}): {count} blocks")
    
    # Show top blocks
    block_counts = Counter()
    for x in range(16):
        for y in range(city_blocks.shape[1]):
            for z in range(16):
                idx = city_blocks[x, y, z]
                block_counts[city_palette[idx]] += 1
    
    print(f"\n    Top 10 blocks:")
    for block, count in block_counts.most_common(10):
        print(f"      {block:40s} {count:6,}")
    
    # Load corresponding terrain chunk
    print(f"\nLoading terrain chunk at ({cx}, {cz})...")
    terrain_chunk = None
    for tcx, tcz, tblocks, tpalette in read_bin_generator(terrain_file):
        if tcx == cx and tcz == cz:
            terrain_chunk = (tcx, tcz, tblocks, tpalette)
            break
    
    if not terrain_chunk:
        print(f"  ❌ No terrain chunk found at ({cx}, {cz})")
        return
    
    _, _, terrain_blocks, terrain_palette = terrain_chunk
    
    print(f"  Found terrain chunk")
    print(f"\n  Terrain chunk details:")
    print(f"    Shape: {terrain_blocks.shape}")
    print(f"    Palette size: {len(terrain_palette)}")
    
    # Show top terrain blocks
    terrain_counts = Counter()
    for x in range(16):
        for y in range(terrain_blocks.shape[1]):
            for z in range(16):
                idx = terrain_blocks[x, y, z]
                terrain_counts[terrain_palette[idx]] += 1
    
    print(f"\n    Top 10 blocks:")
    for block, count in terrain_counts.most_common(10):
        print(f"      {block:40s} {count:6,}")
    
    # Simulate merge
    print(f"\n{'=' * 70}")
    print("SIMULATING MERGE")
    print(f"{'=' * 70}")
    
    y_offset = city_y + 64
    print(f"Y offset calculation: {city_y} + 64 = {y_offset}")
    print(f"This means:")
    print(f"  City array[0] (world Y=-64) -> world Y={y_offset-64}")
    print(f"  City array[64] (world Y=0) -> world Y={y_offset}")
    print(f"  City array[131] (world Y=67) -> world Y={y_offset+67}")
    
    if city_heights:
        min_city_y = min(city_heights)
        max_city_y = max(city_heights)
        print(f"\n  City blocks (array {min_city_y}-{max_city_y}) will be placed at world Y={min_city_y+y_offset-64} to {max_city_y+y_offset-64}")
    
    # Check if city will be placed
    H = max(terrain_blocks.shape[1], city_blocks.shape[1] + y_offset)
    print(f"\n  Result array height: {H}")
    print(f"  Terrain height: {terrain_blocks.shape[1]}")
    print(f"  City height: {city_blocks.shape[1]} + offset {y_offset} = {city_blocks.shape[1] + y_offset}")
    
    # Count how many city blocks would be placed
    placed = 0
    skipped_air = 0
    skipped_oob = 0
    
    for y in range(city_blocks.shape[1]):
        world_y = y + y_offset
        if world_y >= H:
            skipped_oob += 16 * 16
            continue
        for x in range(16):
            for z in range(16):
                city_idx = city_blocks[x, y, z]
                if city_idx == air_idx:
                    skipped_air += 1
                else:
                    placed += 1
    
    print(f"\n  Merge simulation:")
    print(f"    City blocks that would be placed: {placed:,}")
    print(f"    Skipped (air): {skipped_air:,}")
    print(f"    Skipped (out of bounds): {skipped_oob:,}")
    
    if placed == 0:
        print(f"\n  ⚠️  WARNING: NO CITY BLOCKS WOULD BE PLACED!")
        print(f"     This means the merge will only contain terrain!")


def main():
    parser = argparse.ArgumentParser(description="Debug merge process")
    parser.add_argument("--city", required=True, help="City .bin file")
    parser.add_argument("--terrain", required=True, help="Terrain .bin file")
    parser.add_argument("--city-y", type=int, default=-71, help="City Y offset")
    
    args = parser.parse_args()
    
    debug_merge(args.city, args.terrain, args.city_y)


if __name__ == "__main__":
    main()
