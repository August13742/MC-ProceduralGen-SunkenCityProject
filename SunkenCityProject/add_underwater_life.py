"""
add_underwater_life.py

Add underwater vegetation (kelp, seagrass, coral) to sunken city ruins.
Works directly on .bin files - no terrain data needed!

Usage:
    python SunkenCityProject/add_underwater_life.py \
        --input city_grounded.bin \
        --output city_underwater.bin \
        --density 0.3
"""

import argparse
import numpy as np
import random
from numba import jit
from tqdm import tqdm
from city_utils import read_bin_generator, write_bin
from multiprocessing import Pool, cpu_count
from opensimplex import OpenSimplex


# Underwater vegetation (block_name, weight)
VEGETATION = [
    ("minecraft:kelp_plant", 0.30),
    ("minecraft:seagrass", 0.35),
    ("minecraft:tall_seagrass", 0.20),
    ("minecraft:sea_pickle", 0.08),
    ("minecraft:tube_coral", 0.04),
    ("minecraft:brain_coral", 0.03),
]


@jit(nopython=True, cache=True)
def _find_surface_blocks(blocks, air_idx, water_idx, min_y, max_y):
    """
    Find surface blocks (top of structures/rubble) where vegetation can grow.
    Returns array of (x, z, y) tuples.
    """
    surfaces = []
    H = blocks.shape[1]
    
    for x in range(16):
        for z in range(16):
            # Scan from bottom up to find first solid block
            for y in range(min(min_y, H), min(max_y, H)):
                if y < 0 or y >= H:
                    continue
                    
                block = blocks[x, y, z]
                if block != air_idx and block != water_idx:
                    # Found solid block - check if it has air/water above
                    if y + 1 < H:
                        above = blocks[x, y + 1, z]
                        if above == air_idx or above == water_idx:
                            surfaces.append((x, z, y + 1))  # Place vegetation on top
                            break
    
    return surfaces


def add_vegetation(cx, cz, blocks, palette, density, seed, min_y_idx=0, max_y_idx=200):
    """
    Add underwater vegetation to chunk surfaces.
    
    Args:
        cx, cz: Chunk coordinates
        blocks: Block array (16, H, 16)
        palette: List of block names
        density: Vegetation density 0.0-1.0
        seed: Random seed
        min_y_idx: Minimum Y index to scan
        max_y_idx: Maximum Y index to scan
    
    Returns:
        (cx, cz, blocks, palette, veg_count)
    """
    blocks = blocks.copy()
    name_to_idx = {n: i for i, n in enumerate(palette)}
    air_idx = name_to_idx.get("minecraft:air", 0)
    water_idx = name_to_idx.get("minecraft:water", air_idx)
    
    H = blocks.shape[1]
    
    # Find surface blocks
    surfaces = _find_surface_blocks(blocks, air_idx, water_idx, min_y_idx, max_y_idx)
    
    if len(surfaces) == 0:
        return cx, cz, blocks, palette, 0
    
    # Use noise for natural distribution
    noise = OpenSimplex(seed=seed)
    veg_count = 0
    
    for x, z, y in surfaces:
        if y >= H:
            continue
            
        # World coordinates for noise
        world_x = cx * 16 + x
        world_z = cz * 16 + z
        
        # Noise-based placement (creates clusters)
        noise_val = noise.noise2(world_x * 0.05, world_z * 0.05)
        
        # Combine density and noise
        if random.random() > density * (0.5 + 0.5 * noise_val):
            continue
        
        # Pick vegetation type
        choices, weights = zip(*VEGETATION)
        chosen = random.choices(choices, weights=weights, k=1)[0]
        
        # Add to palette if needed
        if chosen not in name_to_idx:
            palette.append(chosen)
            name_to_idx[chosen] = len(palette) - 1
        
        # Place vegetation
        blocks[x, y, z] = name_to_idx[chosen]
        veg_count += 1
        
        # Kelp can grow upward
        if chosen == "minecraft:kelp_plant":
            kelp_height = random.randint(1, 5)
            for dy in range(1, kelp_height):
                if y + dy >= H:
                    break
                if blocks[x, y + dy, z] in (air_idx, water_idx):
                    blocks[x, y + dy, z] = name_to_idx["minecraft:kelp_plant"]
                    veg_count += 1
                else:
                    break  # Hit solid block
    
    return cx, cz, blocks, palette, veg_count


# Global state for multiprocessing
_density = None
_seed = None
_min_y = None
_max_y = None

def _init_worker(density, seed, min_y, max_y):
    global _density, _seed, _min_y, _max_y
    _density = density
    _seed = seed
    _min_y = min_y
    _max_y = max_y

def _veg_worker(chunk_data):
    global _density, _seed, _min_y, _max_y
    cx, cz, blocks, palette = chunk_data
    return add_vegetation(cx, cz, blocks, palette, _density, _seed + cx * 1000 + cz, _min_y, _max_y)


def main():
    parser = argparse.ArgumentParser(description="Add underwater vegetation to sunken city")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--output", required=True, help="Output .bin file")
    parser.add_argument("--density", type=float, default=0.3,
                        help="Vegetation density 0.0-1.0 (default: 0.3)")
    parser.add_argument("--seed", type=int, default=13742,
                        help="Random seed (default: 13742)")
    parser.add_argument("--min-y", type=int, default=0,
                        help="Minimum Y index to add vegetation (default: 0)")
    parser.add_argument("--max-y", type=int, default=200,
                        help="Maximum Y index to add vegetation (default: 200)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of worker processes (default: CPU count)")
    
    args = parser.parse_args()
    
    num_workers = args.workers or cpu_count()
    
    print("=" * 70)
    print("ADD UNDERWATER VEGETATION")
    print("=" * 70)
    print(f"\n📂 Input: {args.input}")
    print(f"📂 Output: {args.output}")
    print(f"🌿 Density: {args.density:.1%}")
    print(f"🎲 Seed: {args.seed}")
    print(f"⚡ Workers: {num_workers}\n")
    
    # Load chunks
    print("Loading chunks...")
    chunks_data = []
    for cx, cz, blocks, palette in tqdm(read_bin_generator(args.input), desc="Loading", unit="chunk"):
        chunks_data.append((cx, cz, blocks, list(palette)))
    print(f"✓ Loaded {len(chunks_data):,} chunks\n")
    
    # Process with multiprocessing
    print("Adding vegetation...")
    total_veg = 0
    processed = []
    
    with Pool(processes=num_workers, initializer=_init_worker,
              initargs=(args.density, args.seed, args.min_y, args.max_y)) as pool:
        results = list(tqdm(
            pool.imap(_veg_worker, chunks_data, chunksize=16),
            total=len(chunks_data),
            desc="Planting",
            unit="chunk"
        ))
    
    for cx, cz, blocks, palette, veg_count in results:
        processed.append((cx, cz, blocks, palette))
        total_veg += veg_count
    
    print(f"\n✓ Planted {total_veg:,} vegetation blocks")
    
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
    print("UNDERWATER LIFE COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {args.output}")
    print(f"✓ Palette: {len(global_palette)} unique blocks")
    print(f"\n💡 Next: Place in world with restore_city_amulet_ultra.py")


if __name__ == "__main__":
    main()
