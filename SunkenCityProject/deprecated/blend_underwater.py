"""
blend_underwater.py

Creates realistic underwater environment for merged city+terrain chunks.

Stages:
1. Ground Connection - Vertical support pillars from structures to ocean floor
2. Vegetation Overgrowth - Kelp, seagrass, coral on and around structures
3. Sediment Accumulation - Gravel/sand settling on flat surfaces
4. Natural Erosion - Smooth out unnatural vertical edges

All processing happens on .bin files - no world placement needed!

Usage:
    python SunkenCityProject/blend_underwater.py \
        --input city_merged.bin \
        --output city_underwater.bin \
        --ocean-floor 60 \
        --city-level 20 \
        --all-stages
"""

import argparse
import numpy as np
import random
from numba import jit
from tqdm import tqdm
from opensimplex import OpenSimplex
from city_utils import read_bin_generator
import struct
import zlib
import json
from multiprocessing import Pool, cpu_count


class UnderwaterBlender:
    def __init__(self, ocean_floor=60, city_level=20, seed=13742):
        self.ocean_floor = ocean_floor
        self.city_level = city_level
        self.noise = OpenSimplex(seed=seed)
        
        # Cache for palette lookups
        self._palette_cache = {}
        
        # Underwater vegetation materials
        self.vegetation_blocks = [
            ("minecraft:kelp_plant", 0.3),
            ("minecraft:seagrass", 0.4),
            ("minecraft:tall_seagrass", 0.2),
            ("minecraft:sea_pickle", 0.05),
            ("minecraft:tube_coral", 0.05)
        ]
        
        # Support column materials (ocean floor to structure)
        self.support_materials = [
            ("minecraft:stone", 0.25),
            ("minecraft:cobblestone", 0.2),
            ("minecraft:mossy_cobblestone", 0.25),
            ("minecraft:prismarine", 0.15),
            ("minecraft:dark_prismarine", 0.1),
            ("minecraft:gravel", 0.05)
        ]
        
        # Sediment materials
        self.sediment_materials = [
            ("minecraft:gravel", 0.5),
            ("minecraft:sand", 0.3),
            ("minecraft:dirt", 0.15),
            ("minecraft:clay", 0.05)
        ]
    
    def get_palette_indices(self, palette):
        """Get cached name_to_idx mapping for palette."""
        # Use tuple of palette as cache key
        palette_key = tuple(palette)
        if palette_key not in self._palette_cache:
            self._palette_cache[palette_key] = {name: i for i, name in enumerate(palette)}
        return self._palette_cache[palette_key]
    
    def stage_ground_connection(self, blocks, palette, cx, cz):
        """Create vertical supports from structures down to ocean floor."""
        # Make writable copy
        blocks = blocks.copy()
        
        name_to_idx = self.get_palette_indices(palette)
        air_idx = name_to_idx.get("minecraft:air", 0)
        water_idx = name_to_idx.get("minecraft:water", air_idx)
        
        H = blocks.shape[1]
        changes = 0
        
        # Convert Y levels to array indices (world starts at -64)
        ocean_floor_idx = self.ocean_floor + 64
        city_level_idx = self.city_level + 64
        
        for x in range(16):
            for z in range(16):
                # Find lowest structure block above city level
                lowest_structure = -1
                for y in range(city_level_idx, min(H, ocean_floor_idx + 50)):
                    block_idx = blocks[x, y, z]
                    if block_idx != air_idx and block_idx != water_idx:
                        lowest_structure = y
                        break
                
                if lowest_structure < 0:
                    continue
                
                # Find ocean floor (highest non-water below structure)
                ocean_floor_here = ocean_floor_idx
                for y in range(ocean_floor_idx, -1, -1):
                    if y >= H:
                        continue
                    block_idx = blocks[x, y, z]
                    if block_idx != water_idx and block_idx != air_idx:
                        ocean_floor_here = y
                        break
                
                # Create support column with noise variation
                world_x = cx * 16 + x
                world_z = cz * 16 + z
                noise_val = self.noise.noise3(world_x * 0.1, 0, world_z * 0.1)
                
                # Should we create support here?
                if noise_val < 0.3:  # 70% chance
                    continue
                
                # Build column from ocean floor to structure
                for y in range(ocean_floor_here, lowest_structure):
                    if y < 0 or y >= H:
                        continue
                    
                    current_block = blocks[x, y, z]
                    if current_block != water_idx and current_block != air_idx:
                        continue  # Don't replace existing terrain
                    
                    # Choose material based on height
                    height_ratio = (y - ocean_floor_here) / max(1, lowest_structure - ocean_floor_here)
                    
                    if height_ratio < 0.3:
                        # Bottom: stone/cobble
                        choices = [
                            ("minecraft:stone", 0.4),
                            ("minecraft:cobblestone", 0.4),
                            ("minecraft:gravel", 0.2)
                        ]
                    elif height_ratio < 0.7:
                        # Middle: mix
                        choices = self.support_materials
                    else:
                        # Top: more organic
                        choices = [
                            ("minecraft:mossy_cobblestone", 0.4),
                            ("minecraft:prismarine", 0.3),
                            ("minecraft:dark_prismarine", 0.3)
                        ]
                    
                    block_names, weights = zip(*choices)
                    chosen = random.choices(block_names, weights=weights, k=1)[0]
                    
                    # Add to palette if needed
                    if chosen not in name_to_idx:
                        palette.append(chosen)
                        name_to_idx[chosen] = len(palette) - 1
                    
                    blocks[x, y, z] = name_to_idx[chosen]
                    changes += 1
        
        return blocks, palette, changes
    
    def stage_vegetation(self, blocks, palette, cx, cz):
        """Add kelp, seagrass, coral around structures."""
        # Make writable copy
        blocks = blocks.copy()
        
        name_to_idx = self.get_palette_indices(palette)
        air_idx = name_to_idx.get("minecraft:air", 0)
        water_idx = name_to_idx.get("minecraft:water", air_idx)
        
        H = blocks.shape[1]
        changes = 0
        
        city_level_idx = self.city_level + 64
        ocean_floor_idx = self.ocean_floor + 64
        
        for x in range(16):
            for z in range(16):
                world_x = cx * 16 + x
                world_z = cz * 16 + z
                
                # Use noise for natural distribution
                noise_val = self.noise.noise3(world_x * 0.05, 0, world_z * 0.05)
                
                if noise_val < -0.2:  # Only 40% of locations get vegetation
                    continue
                
                # Find ground level (top of structure or ocean floor)
                ground_y = -1
                for y in range(min(H-1, ocean_floor_idx + 50), city_level_idx - 1, -1):
                    block_idx = blocks[x, y, z]
                    if block_idx != water_idx and block_idx != air_idx:
                        ground_y = y
                        break
                
                if ground_y < 0:
                    continue
                
                # Check if there's water above
                if ground_y + 1 >= H:
                    continue
                if blocks[x, ground_y + 1, z] != water_idx:
                    continue
                
                # Determine vegetation height (1-4 blocks)
                height = random.randint(1, 4)
                
                # Choose vegetation type
                veg_names, veg_weights = zip(*self.vegetation_blocks)
                chosen_veg = random.choices(veg_names, weights=veg_weights, k=1)[0]
                
                # Add to palette if needed
                if chosen_veg not in name_to_idx:
                    palette.append(chosen_veg)
                    name_to_idx[chosen_veg] = len(palette) - 1
                
                # Place vegetation
                for dy in range(1, height + 1):
                    y = ground_y + dy
                    if y >= H:
                        break
                    if blocks[x, y, z] != water_idx:
                        break
                    
                    blocks[x, y, z] = name_to_idx[chosen_veg]
                    changes += 1
        
        return blocks, palette, changes
    
    def stage_sediment(self, blocks, palette, cx, cz):
        """Add sediment layers on flat horizontal surfaces."""
        # Make writable copy
        blocks = blocks.copy()
        
        name_to_idx = self.get_palette_indices(palette)
        air_idx = name_to_idx.get("minecraft:air", 0)
        water_idx = name_to_idx.get("minecraft:water", air_idx)
        
        H = blocks.shape[1]
        changes = 0
        
        city_level_idx = self.city_level + 64
        ocean_floor_idx = self.ocean_floor + 64
        
        for x in range(16):
            for z in range(16):
                world_x = cx * 16 + x
                world_z = cz * 16 + z
                
                # Noise for sediment distribution
                noise_val = self.noise.noise3(world_x * 0.08, 0, world_z * 0.08)
                
                # Find horizontal surfaces
                for y in range(city_level_idx, min(H-1, ocean_floor_idx + 40)):
                    block_idx = blocks[x, y, z]
                    above_idx = blocks[x, y + 1, z]
                    
                    # Is this a horizontal surface with water above?
                    if block_idx == water_idx or block_idx == air_idx:
                        continue
                    if above_idx != water_idx:
                        continue
                    
                    # Check if it's relatively flat (neighbors at similar height)
                    is_flat = True
                    for dx, dz in [(1,0), (-1,0), (0,1), (0,-1)]:
                        nx, nz = x + dx, z + dz
                        if 0 <= nx < 16 and 0 <= nz < 16:
                            if blocks[nx, y, nz] == water_idx or blocks[nx, y, nz] == air_idx:
                                is_flat = False
                                break
                    
                    if not is_flat:
                        continue
                    
                    # Apply sediment with probability based on noise
                    if noise_val + random.random() * 0.3 > 0.6:
                        # Choose sediment
                        sed_names, sed_weights = zip(*self.sediment_materials)
                        chosen_sed = random.choices(sed_names, weights=sed_weights, k=1)[0]
                        
                        # Add to palette if needed
                        if chosen_sed not in name_to_idx:
                            palette.append(chosen_sed)
                            name_to_idx[chosen_sed] = len(palette) - 1
                        
                        blocks[x, y + 1, z] = name_to_idx[chosen_sed]
                        changes += 1
        
        return blocks, palette, changes


def process_chunk_worker(args_tuple):
    """Worker function for multiprocessing."""
    cx, cz, blocks, palette, ocean_floor, city_level, seed, stages = args_tuple
    
    # Create blender for this worker
    blender = UnderwaterBlender(
        ocean_floor=ocean_floor,
        city_level=city_level,
        seed=seed
    )
    
    # Apply stages
    total_changes = 0
    
    if "ground" in stages:
        blocks, palette, changes = blender.stage_ground_connection(blocks, palette, cx, cz)
        total_changes += changes
    
    if "vegetation" in stages:
        blocks, palette, changes = blender.stage_vegetation(blocks, palette, cx, cz)
        total_changes += changes
    
    if "sediment" in stages:
        blocks, palette, changes = blender.stage_sediment(blocks, palette, cx, cz)
        total_changes += changes
    
    return cx, cz, blocks, palette, total_changes


def main():
    parser = argparse.ArgumentParser(description="Create underwater environment blending")
    parser.add_argument("--input", required=True, help="Input merged .bin file")
    parser.add_argument("--output", required=True, help="Output .bin file")
    parser.add_argument("--ocean-floor", type=int, default=60, help="Ocean floor Y level")
    parser.add_argument("--city-level", type=int, default=20, help="City placement Y level")
    parser.add_argument("--seed", type=int, default=13742, help="Random seed")
    parser.add_argument("--workers", type=int, default=None, help="Number of worker processes (default: CPU count)")
    
    # Stage selection
    parser.add_argument("--all-stages", action="store_true", help="Run all stages")
    parser.add_argument("--ground-connection", action="store_true", help="Stage 1: Ground connection")
    parser.add_argument("--vegetation", action="store_true", help="Stage 2: Vegetation")
    parser.add_argument("--sediment", action="store_true", help="Stage 3: Sediment")
    
    args = parser.parse_args()
    
    # Determine which stages to run
    if args.all_stages:
        stages = ["ground", "vegetation", "sediment"]
    else:
        stages = []
        if args.ground_connection:
            stages.append("ground")
        if args.vegetation:
            stages.append("vegetation")
        if args.sediment:
            stages.append("sediment")
    
    if not stages:
        print("❌ No stages selected! Use --all-stages or specify individual stages.")
        return
    
    # Determine worker count
    workers = args.workers if args.workers else cpu_count()
    
    print("=" * 70)
    print("UNDERWATER BLENDING")
    print("=" * 70)
    print(f"\n📂 Input: {args.input}")
    print(f"📂 Output: {args.output}")
    print(f"🌊 Ocean Floor: Y={args.ocean_floor}")
    print(f"🏛️  City Level: Y={args.city_level}")
    print(f"🎯 Stages: {', '.join(stages)}")
    print(f"👷 Workers: {workers}\n")
    
    # Load all chunks first
    print("Loading chunks...")
    chunk_list = []
    for cx, cz, blocks, palette in tqdm(read_bin_generator(args.input), desc="Loading", unit="chunk"):
        chunk_list.append((cx, cz, blocks, palette))
    
    print(f"✓ Loaded {len(chunk_list):,} chunks")
    
    # Prepare worker arguments
    worker_args = [
        (cx, cz, blocks, palette, args.ocean_floor, args.city_level, args.seed, stages)
        for cx, cz, blocks, palette in chunk_list
    ]
    
    # Process chunks with multiprocessing
    print(f"\nProcessing with {workers} workers...")
    chunks_data = []
    total_changes_sum = 0
    
    with Pool(workers) as pool:
        results = list(tqdm(
            pool.imap(process_chunk_worker, worker_args),
            total=len(worker_args),
            desc="Blending underwater",
            unit="chunk"
        ))
    
    # Collect results
    for cx, cz, blocks, palette, changes in results:
        chunks_data.append((cx, cz, blocks, palette))
        total_changes_sum += changes
    
    print(f"✓ Processed {len(chunks_data):,} chunks")
    print(f"  Total blocks modified: {total_changes_sum:,}")
    
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
    print("UNDERWATER BLENDING COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {args.output}")
    print("\n💡 Next: View in Amulet Editor or place with restore_city_amulet_ultra.py")


if __name__ == "__main__":
    main()
