"""
inspect_bin.py

Quick inspection tool to see what's actually in a .bin file.
"""

import argparse
from city_utils import read_bin_generator
from collections import Counter


def inspect_bin(filename, sample_chunks=5):
    """Inspect a .bin file to see what blocks it contains."""
    
    print(f"Inspecting: {filename}")
    print("=" * 70)
    
    chunk_count = 0
    total_blocks = Counter()
    sample_data = []
    
    for cx, cz, blocks, palette in read_bin_generator(filename):
        chunk_count += 1
        
        # Count blocks in this chunk
        if chunk_count <= sample_chunks:
            unique, counts = blocks.ravel(), None
            import numpy as np
            unique_indices, counts = np.unique(blocks, return_counts=True)
            
            chunk_blocks = Counter()
            for idx, count in zip(unique_indices, counts):
                block_name = palette[idx]
                chunk_blocks[block_name] = count
                total_blocks[block_name] += count
            
            # Store sample
            sample_data.append({
                'pos': (cx, cz),
                'blocks': chunk_blocks,
                'height': blocks.shape[1],
                'palette_size': len(palette)
            })
        else:
            # Just count total blocks
            import numpy as np
            unique_indices, counts = np.unique(blocks, return_counts=True)
            for idx, count in zip(unique_indices, counts):
                total_blocks[palette[idx]] += count
        
        if chunk_count % 1000 == 0:
            print(f"  Processed {chunk_count:,} chunks...", end='\r')
    
    print(f"\n✓ Total chunks: {chunk_count:,}")
    print(f"✓ Unique block types: {len(total_blocks)}")
    
    # Show top blocks
    print(f"\nTop 20 most common blocks:")
    for block_name, count in total_blocks.most_common(20):
        pct = (count / sum(total_blocks.values())) * 100
        print(f"  {block_name:50s} {count:12,} ({pct:5.2f}%)")
    
    # Search for city blocks
    city_keywords = ['white_concrete', 'oak_planks', 'oak_log', 'spruce', 'birch', 'stone_brick']
    city_blocks = {name: count for name, count in total_blocks.items() 
                   if any(kw in name for kw in city_keywords)}
    if city_blocks:
        print(f"\nCity-related blocks found ({len(city_blocks)} types):")
        for block_name, count in sorted(city_blocks.items(), key=lambda x: -x[1])[:20]:
            pct = (count / sum(total_blocks.values())) * 100
            print(f"  {block_name:50s} {count:12,} ({pct:5.2f}%)")
    else:
        print("\n⚠ No obvious city blocks found!")
    
    # Show sample chunks
    print(f"\nSample chunks (first {len(sample_data)}):")
    for i, sample in enumerate(sample_data, 1):
        print(f"\n  Chunk {i} at {sample['pos']}:")
        print(f"    Height: {sample['height']} blocks")
        print(f"    Palette: {sample['palette_size']} types")
        print(f"    Top 5 blocks:")
        for block_name, count in Counter(sample['blocks']).most_common(5):
            print(f"      {block_name:40s} {count:6,}")


def main():
    parser = argparse.ArgumentParser(description="Inspect .bin file contents")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--sample", type=int, default=5, help="Number of chunks to show details for")
    
    args = parser.parse_args()
    
    inspect_bin(args.input, args.sample)


if __name__ == "__main__":
    main()
