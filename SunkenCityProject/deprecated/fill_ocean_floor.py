"""
fill_ocean_floor.py

Fill the gap between floating city ruins and the ocean floor with support rubble.
Simple and fast - just extend downward from lowest city blocks to ocean floor.

Usage:
    python SunkenCityProject/fill_ocean_floor.py \
        --input city_positioned.bin \
        --output city_grounded.bin \
        --ocean-floor 60
"""

import argparse
import numpy as np
import random
from numba import jit
from tqdm import tqdm
from city_utils import read_bin_generator, write_bin
from multiprocessing import Pool, cpu_count


# Materials for fill (rubble/sediment under ruins)
FILL_MATERIALS = [
    ("minecraft:cobblestone", 0.25),
    ("minecraft:stone", 0.20),
    ("minecraft:gravel", 0.15),
    ("minecraft:andesite", 0.10),
    ("minecraft:mossy_cobblestone", 0.10),
    ("minecraft:dirt", 0.08),
    ("minecraft:sand", 0.07),
    ("minecraft:prismarine", 0.05),
]


@jit(nopython=True, cache=True)
def _find_lowest_blocks(blocks, air_idx):
    """Find lowest non-air block in each column. Returns (16, 16) array of Y indices."""
    lowest = np.full((16, 16), -1, dtype=np.int32)
    H = blocks.shape[1]
    
    for x in range(16):
        for z in range(16):
            for y in range(H):
                if blocks[x, y, z] != air_idx:
                    lowest[x, z] = y
                    break
    
    return lowest


def fill_chunk(cx, cz, blocks, palette, ocean_floor_y, world_y_min=-64):
    """
    Fill gap between city and ocean floor with rubble.
    
    Args:
        cx, cz: Chunk coordinates
        blocks: Block array (16, H, 16)
        palette: List of block names
        ocean_floor_y: Ocean floor world Y coordinate (e.g., 60)
        world_y_min: World minimum Y (default -64)
    
    Returns:
        (cx, cz, blocks, palette, fill_count)
    """
    blocks = blocks.copy()
    name_to_idx = {n: i for i, n in enumerate(palette)}
    air_idx = name_to_idx.get("minecraft:air", 0)
    
    # Convert ocean floor from world Y to array index
    ocean_floor_idx = ocean_floor_y - world_y_min
    H = blocks.shape[1]
    
    if ocean_floor_idx < 0 or ocean_floor_idx >= H:
        return cx, cz, blocks, palette, 0
    
    # Find lowest block in each column
    lowest = _find_lowest_blocks(blocks, air_idx)
    
    fill_count = 0
    
    for x in range(16):
        for z in range(16):
            lowest_y = lowest[x, z]
            
            # If no blocks in this column, skip
            if lowest_y < 0:
                continue
            
            # If already at or below ocean floor, skip
            if lowest_y <= ocean_floor_idx:
                continue
            
            # Fill from ocean floor to just below lowest block
            for y in range(ocean_floor_idx, lowest_y):
                if blocks[x, y, z] != air_idx:
                    continue  # Don't overwrite existing blocks
                
                # Pick random fill material
                choices, weights = zip(*FILL_MATERIALS)
                chosen = random.choices(choices, weights=weights, k=1)[0]
                
                # Add to palette if needed
                if chosen not in name_to_idx:
                    palette.append(chosen)
                    name_to_idx[chosen] = len(palette) - 1
                
                blocks[x, y, z] = name_to_idx[chosen]
                fill_count += 1
    
    return cx, cz, blocks, palette, fill_count


# Global state for multiprocessing
_ocean_floor = None
_world_y_min = None

def _init_worker(ocean_floor, world_y_min):
    global _ocean_floor, _world_y_min
    _ocean_floor = ocean_floor
    _world_y_min = world_y_min

def _fill_worker(chunk_data):
    global _ocean_floor, _world_y_min
    cx, cz, blocks, palette = chunk_data
    return fill_chunk(cx, cz, blocks, palette, _ocean_floor, _world_y_min)


def main():
    parser = argparse.ArgumentParser(description="Fill gap between city and ocean floor")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--output", required=True, help="Output .bin file")
    parser.add_argument("--ocean-floor", type=int, default=60, 
                        help="Ocean floor Y level (default: 60)")
    parser.add_argument("--world-y-min", type=int, default=-64,
                        help="World minimum Y (default: -64)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of worker processes (default: CPU count)")
    
    args = parser.parse_args()
    
    num_workers = args.workers or cpu_count()
    
    print("=" * 70)
    print("OCEAN FLOOR FILL")
    print("=" * 70)
    print(f"\n📂 Input: {args.input}")
    print(f"📂 Output: {args.output}")
    print(f"🌊 Ocean Floor: Y={args.ocean_floor}")
    print(f"⚡ Workers: {num_workers}\n")
    
    # Load chunks
    print("Loading chunks...")
    chunks_data = []
    for cx, cz, blocks, palette in tqdm(read_bin_generator(args.input), desc="Loading", unit="chunk"):
        chunks_data.append((cx, cz, blocks, list(palette)))
    print(f"✓ Loaded {len(chunks_data):,} chunks\n")
    
    # Process with multiprocessing
    print("Filling ocean floor gaps...")
    total_fill = 0
    processed = []
    
    with Pool(processes=num_workers, initializer=_init_worker, 
              initargs=(args.ocean_floor, args.world_y_min)) as pool:
        results = list(tqdm(
            pool.imap(_fill_worker, chunks_data, chunksize=16),
            total=len(chunks_data),
            desc="Filling",
            unit="chunk"
        ))
    
    for cx, cz, blocks, palette, fill_count in results:
        processed.append((cx, cz, blocks, palette))
        total_fill += fill_count
    
    print(f"\n✓ Filled {total_fill:,} blocks")
    
    # Build global palette
    print("\nBuilding global palette...")
    global_palette = []
    palette_set = set()
    for cx, cz, blocks, palette in processed:
        for name in palette:
            if name not in palette_set:
                palette_set.add(name)
                global_palette.append(name)
    
    # Write output
    print(f"Writing to {args.output}...")
    
    def chunk_generator():
        for cx, cz, blocks, palette in tqdm(processed, desc="Remapping", unit="chunk"):
            local_to_global = np.array([global_palette.index(n) for n in palette], dtype=np.uint16)
            remapped = local_to_global[blocks]
            yield cx, cz, remapped
    
    write_bin(args.output, chunk_generator(), global_palette)
    
    print("\n" + "=" * 70)
    print("FILL COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {args.output}")
    print(f"✓ Palette: {len(global_palette)} unique blocks")


if __name__ == "__main__":
    main()
