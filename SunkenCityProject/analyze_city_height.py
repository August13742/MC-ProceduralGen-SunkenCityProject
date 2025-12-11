"""
analyze_city_height.py

Analyzes a .bin file to find the Y-level distribution of non-terrain blocks.
This helps determine where the city actually sits.
"""

import argparse
import numpy as np
from city_utils import read_bin_generator
from collections import Counter

# Common terrain blocks that are NOT city structures
TERRAIN_BLOCKS = {
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
    "minecraft:stone",
    "minecraft:deepslate",
    "minecraft:granite",
    "minecraft:diorite",
    "minecraft:andesite",
    "minecraft:dirt",
    "minecraft:grass_block",
    "minecraft:water",
    "minecraft:bedrock",
    "minecraft:gravel",
    "minecraft:sand",
    "minecraft:sandstone",
    "minecraft:coal_ore",
    "minecraft:iron_ore",
    "minecraft:copper_ore",
    "minecraft:gold_ore",
    "minecraft:lapis_ore",
    "minecraft:redstone_ore",
    "minecraft:diamond_ore",
    "minecraft:emerald_ore",
    "minecraft:deepslate_coal_ore",
    "minecraft:deepslate_iron_ore",
    "minecraft:deepslate_copper_ore",
    "minecraft:deepslate_gold_ore",
    "minecraft:deepslate_lapis_ore",
    "minecraft:deepslate_redstone_ore",
    "minecraft:deepslate_diamond_ore",
    "minecraft:deepslate_emerald_ore",
    "minecraft:tuff",
    "minecraft:calcite",
    "minecraft:dripstone_block",
    "minecraft:pointed_dripstone",
}


def analyze_city_height(filename, sample_size=1000):
    """Analyze the Y distribution of city blocks."""
    
    print(f"Analyzing: {filename}")
    print("=" * 70)
    
    # Track Y-level statistics
    y_block_counts = Counter()  # Y level -> count of non-terrain blocks
    total_chunks = 0
    sampled_chunks = 0
    total_blocks = 0
    city_blocks = 0
    
    min_y = float('inf')
    max_y = float('-inf')
    
    # First pass: count total chunks
    print("Counting chunks...")
    chunk_count = 0
    for _ in read_bin_generator(filename):
        chunk_count += 1
    
    print(f"✓ Found {chunk_count:,} total chunks")
    
    # Determine sampling interval
    if chunk_count <= sample_size:
        sample_interval = 1
        print(f"→ Analyzing all chunks")
    else:
        sample_interval = chunk_count // sample_size
        print(f"→ Sampling every {sample_interval} chunks ({sample_size} samples)")
    
    print("\nReading chunks...")
    for cx, cz, blocks, palette in read_bin_generator(filename):
        total_chunks += 1
        
        # Sample chunks
        if total_chunks % sample_interval != 0:
            continue
        
        sampled_chunks += 1
        
        W, H, D = blocks.shape
        
        # Check each block
        for x in range(W):
            for y in range(H):
                for z in range(D):
                    block_idx = blocks[x, y, z]
                    block_name = palette[block_idx]
                    
                    total_blocks += 1
                    
                    # Skip terrain blocks
                    if block_name in TERRAIN_BLOCKS:
                        continue
                    
                    # This is a city block
                    city_blocks += 1
                    
                    # World Y = array index - 64
                    world_y = y - 64
                    
                    y_block_counts[world_y] += 1
                    min_y = min(min_y, world_y)
                    max_y = max(max_y, world_y)
        
        if sampled_chunks % 100 == 0:
            print(f"  Processed {sampled_chunks}/{sample_size} sampled chunks...", end='\r')
    
    print(f"\n✓ Sampled {sampled_chunks:,} chunks (out of {total_chunks:,} total)")
    print(f"✓ Total blocks scanned: {total_blocks:,}")
    print(f"✓ City blocks (non-terrain): {city_blocks:,}")
    
    if city_blocks == 0:
        print("\n⚠️  No city blocks found!")
        return
    
    print(f"\nY-Level Range:")
    print(f"  Lowest city block: Y={min_y}")
    print(f"  Highest city block: Y={max_y}")
    print(f"  Height span: {max_y - min_y + 1} blocks")
    
    # Find the Y level with most city blocks
    most_common_y = y_block_counts.most_common(10)
    
    print(f"\nTop 10 Y-levels by city block count:")
    for y, count in most_common_y:
        percentage = (count / city_blocks) * 100
        print(f"  Y={y:4d}: {count:8,} blocks ({percentage:5.2f}%)")
    
    # Calculate percentiles
    sorted_ys = []
    for y, count in y_block_counts.items():
        sorted_ys.extend([y] * count)
    sorted_ys.sort()
    
    p10 = sorted_ys[len(sorted_ys) // 10]
    p25 = sorted_ys[len(sorted_ys) // 4]
    p50 = sorted_ys[len(sorted_ys) // 2]
    p75 = sorted_ys[3 * len(sorted_ys) // 4]
    p90 = sorted_ys[9 * len(sorted_ys) // 10]
    
    print(f"\nY-Level Percentiles:")
    print(f"  10th percentile: Y={p10}")
    print(f"  25th percentile: Y={p25}")
    print(f"  50th percentile (median): Y={p50}")
    print(f"  75th percentile: Y={p75}")
    print(f"  90th percentile: Y={p90}")
    
    print(f"\n💡 Recommendations:")
    print(f"  - City base (bottom structures): Y={p10}")
    print(f"  - City ground level (median): Y={p50}")
    print(f"  - For sunken city at ocean floor Y=60:")
    print(f"    → Use --city-y {p50} in merge_chunks.py")
    print(f"    → Use --city-level {p50} in blend_underwater.py")
    

def main():
    parser = argparse.ArgumentParser(description="Analyze city Y-level distribution")
    parser.add_argument("--input", required=True, help="Input .bin file to analyze")
    parser.add_argument("--sample-size", type=int, default=1000, help="Number of chunks to sample (default: 1000)")
    
    args = parser.parse_args()
    
    analyze_city_height(args.input, args.sample_size)


if __name__ == "__main__":
    main()
