"""
exposure_decay.py

OPTIONAL SEPARATE STAGE: Removes isolated/floating blocks based on neighbor exposure.
This creates more realistic erosion by removing blocks that are surrounded by air.

Run this AFTER regular erosion to:
- Remove floating blocks
- Make structures look less "too sturdy"
- Avoid grid-like holes by using exposure-based logic instead of uniform random decay

Logic: If a block has N or more air neighbors (out of 6), it has a chance to decay to air.
Threshold 3: Aggressive (removes many blocks)
Threshold 4: Moderate (removes floating/isolated) ← Recommended
Threshold 5: Conservative (only very exposed)
Threshold 6: Extreme (completely isolated only)

Usage:
    python SunkenCityProject/exposure_decay.py \
        --input city_eroded.bin \
        --output city_exposed.bin \
        --threshold 4 \
        --decay-chance 0.6
        
python SunkenCityProject/exposure_decay.py --input city_eroded.bin --output city_exposed.bin --threshold 4 --decay-chance 0.6
"""

import argparse
import numpy as np
from numba import jit
from tqdm import tqdm
from city_utils import read_bin_generator
import struct
import zlib
import json


@jit(nopython=True)
def count_air_neighbors_fast(blocks, air_idx, preserve_indices):
    """
    Count air neighbors for all blocks using vectorized operations.
    Returns array of air neighbor counts.
    """
    W, H, D = blocks.shape
    air_counts = np.zeros((W, H, D), dtype=np.int8)
    
    # Check all 6 directions
    directions = [
        (-1, 0, 0), (1, 0, 0),  # x
        (0, -1, 0), (0, 1, 0),  # y
        (0, 0, -1), (0, 0, 1)   # z
    ]
    
    for dx, dy, dz in directions:
        for x in range(W):
            for y in range(H):
                for z in range(D):
                    # Skip preserved blocks
                    if blocks[x, y, z] in preserve_indices:
                        continue
                    
                    nx, ny, nz = x + dx, y + dy, z + dz
                    
                    # Out of bounds = air
                    if nx < 0 or nx >= W or ny < 0 or ny >= H or nz < 0 or nz >= D:
                        air_counts[x, y, z] += 1
                    elif blocks[nx, ny, nz] == air_idx:
                        air_counts[x, y, z] += 1
    
    return air_counts


@jit(nopython=True)
def apply_decay_fast(blocks, air_counts, air_idx, threshold, decay_chance, preserve_indices, seed):
    """
    Apply decay to blocks based on air neighbor counts.
    Uses Numba for speed.
    """
    np.random.seed(seed)
    W, H, D = blocks.shape
    changes = 0
    
    for x in range(W):
        for y in range(H):
            for z in range(D):
                block_idx = blocks[x, y, z]
                
                # Skip air and preserved blocks
                if block_idx == air_idx or block_idx in preserve_indices:
                    continue
                
                # Check threshold
                if air_counts[x, y, z] >= threshold:
                    if np.random.random() < decay_chance:
                        blocks[x, y, z] = air_idx
                        changes += 1
    
    return changes


def process_chunk_optimized(blocks, palette, threshold, decay_chance, preserve_set, seed):
    """
    Optimized chunk processing using Numba.
    """
    # Make writable copy
    blocks = blocks.copy()
    
    # Build index mappings
    name_to_idx = {name: i for i, name in enumerate(palette)}
    air_idx = name_to_idx.get("minecraft:air", 0)
    
    # Find indices of preserved blocks
    preserve_indices = set()
    for block_name in preserve_set:
        if block_name in name_to_idx:
            preserve_indices.add(name_to_idx[block_name])
    
    # Convert to numpy array for Numba
    preserve_arr = np.array(list(preserve_indices), dtype=np.uint16)
    
    # Count air neighbors (fast)
    air_counts = count_air_neighbors_fast(blocks, air_idx, preserve_arr)
    
    # Apply decay (fast)
    changes = apply_decay_fast(blocks, air_counts, air_idx, threshold, decay_chance, preserve_arr, seed)
    
    return blocks, palette, changes


def main():
    parser = argparse.ArgumentParser(description="Apply exposure-based decay to remove floating blocks")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--output", required=True, help="Output .bin file")
    parser.add_argument("--threshold", type=int, default=4,
                        help="Number of air neighbors (0-6) to trigger decay. Default: 4 (moderate)")
    parser.add_argument("--decay-chance", type=float, default=0.6,
                        help="Probability of decay when threshold met. Default: 0.6 (60%%)")
    parser.add_argument("--passes", type=int, default=1,
                        help="Number of exposure decay passes. Default: 1")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("EXPOSURE-BASED DECAY (Anti-Floating Block Treatment)")
    print("=" * 70)
    print(f"\n📂 Input: {args.input}")
    print(f"📂 Output: {args.output}")
    print(f"🎯 Threshold: {args.threshold}/6 air neighbors")
    print(f"🎲 Decay Chance: {args.decay_chance * 100:.0f}%")
    print(f"🔄 Passes: {args.passes}")
    print()
    
    # Note about threshold
    thresholds_guide = {
        3: "Aggressive (removes many blocks, even slightly exposed)",
        4: "Moderate (removes floating/isolated blocks)",
        5: "Conservative (only removes very exposed blocks)",
        6: "Extreme (only removes completely isolated blocks)"
    }
    if args.threshold in thresholds_guide:
        print(f"   Note: Threshold {args.threshold} = {thresholds_guide[args.threshold]}\n")
    
    # Preserved blocks set
    preserve_set = {
        "minecraft:air",
        "minecraft:cave_air", 
        "minecraft:void_air",
        "minecraft:water",
        "minecraft:lava",
        "minecraft:bedrock"
    }
    
    for pass_num in range(args.passes):
        if args.passes > 1:
            print(f"\n{'=' * 70}")
            print(f"PASS {pass_num + 1}/{args.passes}")
            print('=' * 70)
        
        # Read chunks
        chunks_data = []
        total_changes = 0
        
        # Seed for this pass
        current_seed = 13742 + pass_num * 1000
        
        pbar = tqdm(desc=f"Pass {pass_num+1}/{args.passes}", unit="chunk")
        chunk_idx = 0
        for cx, cz, blocks, palette in read_bin_generator(args.input if pass_num == 0 else args.output):
            pbar.update(1)
            
            # Process chunk with optimized function
            blocks, palette, changes = process_chunk_optimized(
                blocks, palette, args.threshold, args.decay_chance,
                preserve_set, current_seed + chunk_idx
            )
            total_changes += changes
            chunk_idx += 1
            
            chunks_data.append((cx, cz, blocks, palette))
        
        pbar.close()
        print(f"✓ Processed {len(chunks_data):,} chunks")
        print(f"✓ Blocks decayed: {total_changes:,}")
        
        # Write output using standard format
        print(f"\nWriting to {args.output}...")
        
        # Build global palette from all chunks
        global_palette = []
        palette_set = set()
        for cx, cz, blocks, palette in chunks_data:
            for block_name in palette:
                if block_name not in palette_set:
                    palette_set.add(block_name)
                    global_palette.append(block_name)
        
        # Remap all chunks to global palette
        remapped_chunks = []
        for cx, cz, blocks, palette in chunks_data:
            # Create mapping from local to global palette
            local_to_global = np.zeros(len(palette), dtype=np.uint16)
            for local_idx, block_name in enumerate(palette):
                local_to_global[local_idx] = global_palette.index(block_name)
            
            # Remap blocks
            remapped_blocks = local_to_global[blocks]
            remapped_chunks.append((cx, cz, remapped_blocks))
        
        # Write using city_utils standard format
        from city_utils import write_bin
        
        def chunk_gen():
            for cx, cz, blocks in remapped_chunks:
                yield cx, cz, blocks
        
        write_bin(args.output, chunk_gen(), global_palette)
    
    print("\n" + "=" * 70)
    print("EXPOSURE DECAY COMPLETE")
    print("=" * 70)
    print("\n💡 Tip: If structures still look too intact, try:")
    print("   - Lower --threshold (try 3 for more aggressive)")
    print("   - Increase --decay-chance (try 0.8)")
    print("   - Add more --passes (try 2-3)")
    print("\n💡 If too many holes, try:")
    print("   - Raise --threshold (try 5)")
    print("   - Decrease --decay-chance (try 0.4)")


if __name__ == "__main__":
    main()
