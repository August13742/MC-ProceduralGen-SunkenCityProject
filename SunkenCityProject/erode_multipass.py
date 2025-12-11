"""
erode_multipass.py

Multi-pass erosion with clean separation of concerns:

PASS ORDER:
1. MATERIAL DECAY - Pure aging/weathering (copper oxidizes, wood rots)
   - Independent of structure - every categorized block has a chance to transform
   - Multiple iterations to accumulate weathering
   
2. STRUCTURAL DECAY - Physics-based collapse
   - Blocks with no support below decay
   - Blocks floating in air decay
   
3. EXPOSURE DECAY - Cleanup floating debris
   - Blocks with N+ air neighbors get removed
   - Creates natural erosion patterns

Usage:
    python SunkenCityProject/erode_multipass.py \
        --input city_original.bin \
        --output city_eroded.bin \
        --config erosion_config_merged.json \
        --material-passes 3 \
        --structural-passes 2 \
        --exposure-passes 2
"""

import argparse
import json
import numpy as np
import random
from numba import jit, prange
from tqdm import tqdm
from city_utils import read_bin_generator, write_bin
import struct
import zlib
from multiprocessing import Pool, cpu_count, get_context
from functools import partial


# ============================================================================
# JIT-COMPILED CORE FUNCTIONS
# ============================================================================

@jit(nopython=True, cache=True)
def _material_decay_kernel(blocks, categorized_mask, decay_rate, replacement_map, rng_seed):
    """
    JIT kernel for material decay.
    - categorized_mask: boolean array where True = block has a category
    - replacement_map: array mapping idx -> replacement_idx (0 = no replacement)
    """
    np.random.seed(rng_seed)
    changes = 0
    H = blocks.shape[1]
    
    for x in range(16):
        for z in range(16):
            for y in range(H):
                idx = blocks[x, y, z]
                if idx == 0:
                    continue
                if not categorized_mask[idx]:
                    continue
                
                # Roll for decay
                if np.random.random() < decay_rate:
                    new_idx = replacement_map[idx]
                    if new_idx != idx and new_idx != 0:
                        blocks[x, y, z] = new_idx
                        changes += 1
    
    return changes


@jit(nopython=True, cache=True)
def _structural_decay_kernel(blocks, ignored_mask, air_idx, decay_rate, replacement_map, rng_seed):
    """
    JIT kernel for structural decay.
    Process top-down for gravity effects.
    """
    np.random.seed(rng_seed)
    changes = 0
    H = blocks.shape[1]
    
    # Process top-down for gravity effects
    for y in range(H - 1, -1, -1):
        for x in range(16):
            for z in range(16):
                idx = blocks[x, y, z]
                if idx == 0 or ignored_mask[idx]:
                    continue
                
                # Calculate instability
                instability = 0.0
                
                # No support below = very unstable
                if y > 0:
                    below = blocks[x, y-1, z]
                    if below == air_idx:
                        instability += 0.6
                
                # Count air neighbors
                air_neighbors = 0
                if y < H-1 and blocks[x, y+1, z] == air_idx:
                    air_neighbors += 1
                if y > 0 and blocks[x, y-1, z] == air_idx:
                    air_neighbors += 1
                if x > 0 and blocks[x-1, y, z] == air_idx:
                    air_neighbors += 1
                if x < 15 and blocks[x+1, y, z] == air_idx:
                    air_neighbors += 1
                if z > 0 and blocks[x, y, z-1] == air_idx:
                    air_neighbors += 1
                if z < 15 and blocks[x, y, z+1] == air_idx:
                    air_neighbors += 1
                
                instability += air_neighbors * 0.1
                
                # Decay based on instability
                if np.random.random() < instability * decay_rate:
                    new_idx = replacement_map[idx]
                    if new_idx != 0:
                        blocks[x, y, z] = new_idx
                        changes += 1
    
    return changes


@jit(nopython=True, cache=True)
def _exposure_decay_kernel(blocks, ignored_mask, air_idx, threshold, decay_chance, rng_seed):
    """
    JIT kernel for exposure decay.
    Remove blocks with too many air neighbors.
    """
    np.random.seed(rng_seed)
    changes = 0
    H = blocks.shape[1]
    
    for x in range(16):
        for z in range(16):
            for y in range(H):
                idx = blocks[x, y, z]
                if idx == 0 or ignored_mask[idx]:
                    continue
                
                # Count air neighbors
                air_count = 0
                if y > 0 and blocks[x, y-1, z] == air_idx:
                    air_count += 1
                if y < H-1 and blocks[x, y+1, z] == air_idx:
                    air_count += 1
                if x > 0 and blocks[x-1, y, z] == air_idx:
                    air_count += 1
                if x < 15 and blocks[x+1, y, z] == air_idx:
                    air_count += 1
                if z > 0 and blocks[x, y, z-1] == air_idx:
                    air_count += 1
                if z < 15 and blocks[x, y, z+1] == air_idx:
                    air_count += 1
                
                # Boundaries count as air
                if y == 0:
                    air_count += 1
                if y == H-1:
                    air_count += 1
                
                # Decay if enough air neighbors
                if air_count >= threshold:
                    if np.random.random() < decay_chance:
                        blocks[x, y, z] = air_idx
                        changes += 1
    
    return changes


# ============================================================================
# ERODER CLASS
# ============================================================================


class MultiPassEroder:
    def __init__(self, config):
        self.config = config
        self.settings = config.get("global_settings", {})
        self.ignored = set(config.get("ignored", []))
        
        # Build block -> category mapping
        self.block_to_category = {}
        self.category_replacements = {}
        
        for cat_name, cat_data in config.get("categories", {}).items():
            blocks = cat_data.get("blocks", [])
            replacements = cat_data.get("replacements", [])
            
            for block in blocks:
                self.block_to_category[block] = cat_name
            self.category_replacements[cat_name] = replacements
    
    def _build_replacement_map(self, palette, name_to_idx):
        """Build array mapping each palette idx to its replacement idx."""
        max_idx = len(palette)
        replacement_map = np.zeros(max_idx + 100, dtype=np.uint16)  # Extra space for new blocks
        
        for i, name in enumerate(palette):
            if name in self.ignored:
                replacement_map[i] = i  # Map to self (no change)
                continue
            
            category = self.block_to_category.get(name)
            if not category:
                replacement_map[i] = i
                continue
            
            replacements = self.category_replacements.get(category, [])
            if not replacements:
                replacement_map[i] = i
                continue
            
            # Pick replacement based on weights
            choices, weights = zip(*replacements)
            new_name = random.choices(choices, weights=weights, k=1)[0]
            
            # Ensure replacement is in palette
            if new_name not in name_to_idx:
                palette.append(new_name)
                new_idx = len(palette) - 1
                name_to_idx[new_name] = new_idx
            else:
                new_idx = name_to_idx[new_name]
            
            replacement_map[i] = new_idx
        
        return replacement_map
    
    def _build_categorized_mask(self, palette):
        """Build boolean array: True if block has a category."""
        mask = np.zeros(len(palette) + 100, dtype=np.bool_)
        for i, name in enumerate(palette):
            if name in self.block_to_category and name not in self.ignored:
                mask[i] = True
        return mask
    
    def _build_ignored_mask(self, palette):
        """Build boolean array: True if block should be ignored."""
        mask = np.zeros(len(palette) + 100, dtype=np.bool_)
        for i, name in enumerate(palette):
            if name in self.ignored:
                mask[i] = True
        return mask
    
    def get_material_replacement(self, block_name):
        """Get replacement based on material category."""
        if block_name in self.ignored:
            return block_name
        
        category = self.block_to_category.get(block_name)
        if not category:
            return block_name
        
        replacements = self.category_replacements.get(category, [])
        if not replacements:
            return block_name
        
        # Pick replacement based on weights
        choices, weights = zip(*replacements)
        return random.choices(choices, weights=weights, k=1)[0]
    
    def material_decay_pass(self, blocks, palette, decay_rate):
        """
        MATERIAL DECAY: Age/weather blocks based on their material type.
        Uses JIT-compiled kernel for speed.
        """
        blocks = blocks.copy()
        name_to_idx = {n: i for i, n in enumerate(palette)}
        
        # Build lookup arrays for JIT
        categorized_mask = self._build_categorized_mask(palette)
        replacement_map = self._build_replacement_map(palette, name_to_idx)
        
        # Run JIT kernel
        rng_seed = random.randint(0, 2**31 - 1)
        changes = _material_decay_kernel(blocks, categorized_mask, decay_rate, replacement_map, rng_seed)
        
        return blocks, palette, changes
    
    def structural_decay_pass(self, blocks, palette, decay_rate):
        """
        STRUCTURAL DECAY: Decay blocks based on physical instability.
        Uses JIT-compiled kernel for speed.
        """
        blocks = blocks.copy()
        name_to_idx = {n: i for i, n in enumerate(palette)}
        air_idx = name_to_idx.get("minecraft:air", 0)
        
        # Build lookup arrays for JIT
        ignored_mask = self._build_ignored_mask(palette)
        replacement_map = self._build_replacement_map(palette, name_to_idx)
        
        # Run JIT kernel
        rng_seed = random.randint(0, 2**31 - 1)
        changes = _structural_decay_kernel(blocks, ignored_mask, air_idx, decay_rate, replacement_map, rng_seed)
        
        return blocks, palette, changes
    
    def exposure_decay_pass(self, blocks, palette, threshold, decay_chance):
        """
        EXPOSURE DECAY: Remove blocks with too many air neighbors.
        Uses JIT-compiled kernel for speed.
        """
        blocks = blocks.copy()
        name_to_idx = {n: i for i, n in enumerate(palette)}
        air_idx = name_to_idx.get("minecraft:air", 0)
        
        # Build lookup arrays for JIT
        ignored_mask = self._build_ignored_mask(palette)
        
        # Run JIT kernel
        rng_seed = random.randint(0, 2**31 - 1)
        changes = _exposure_decay_kernel(blocks, ignored_mask, air_idx, threshold, decay_chance, rng_seed)
        
        return blocks, palette, changes


def process_chunk(eroder, cx, cz, blocks, palette, 
                  material_passes, material_rate,
                  structural_passes, structural_rate,
                  exposure_passes, exposure_threshold, exposure_chance):
    """Process a single chunk through all decay passes."""
    
    total_material = 0
    total_structural = 0
    total_exposure = 0
    
    # 1. MATERIAL DECAY - multiple passes for accumulated weathering
    for _ in range(material_passes):
        blocks, palette, changes = eroder.material_decay_pass(blocks, palette, material_rate)
        total_material += changes
    
    # 2. STRUCTURAL DECAY - physics-based collapse
    for _ in range(structural_passes):
        blocks, palette, changes = eroder.structural_decay_pass(blocks, palette, structural_rate)
        total_structural += changes
    
    # 3. EXPOSURE DECAY - cleanup floating debris
    for _ in range(exposure_passes):
        blocks, palette, changes = eroder.exposure_decay_pass(blocks, palette, exposure_threshold, exposure_chance)
        total_exposure += changes
    
    return cx, cz, blocks, palette, total_material, total_structural, total_exposure


# Global state for multiprocessing workers
_worker_config = None
_worker_params = None

def _init_worker(config, params):
    """Initialize worker with config."""
    global _worker_config, _worker_params
    _worker_config = config
    _worker_params = params

def _process_chunk_worker(chunk_data):
    """Worker function for multiprocessing."""
    global _worker_config, _worker_params
    cx, cz, blocks, palette = chunk_data
    
    eroder = MultiPassEroder(_worker_config)
    return process_chunk(
        eroder, cx, cz, blocks, palette,
        _worker_params['material_passes'], _worker_params['material_rate'],
        _worker_params['structural_passes'], _worker_params['structural_rate'],
        _worker_params['exposure_passes'], _worker_params['exposure_threshold'], 
        _worker_params['exposure_chance']
    )


def main():
    parser = argparse.ArgumentParser(description="Multi-pass erosion with clean separation")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--output", required=True, help="Output .bin file")
    parser.add_argument("--config", required=True, help="Erosion config JSON")
    parser.add_argument("--workers", type=int, default=None,
                        help="Number of worker processes (default: CPU count)")
    
    # Material decay settings
    parser.add_argument("--material-passes", type=int, default=3,
                        help="Number of material weathering passes (default: 3)")
    parser.add_argument("--material-rate", type=float, default=0.4,
                        help="Chance per pass for categorized blocks to weather (default: 0.4)")
    
    # Structural decay settings
    parser.add_argument("--structural-passes", type=int, default=2,
                        help="Number of structural collapse passes (default: 2)")
    parser.add_argument("--structural-rate", type=float, default=0.8,
                        help="Multiplier for structural instability decay (default: 0.8)")
    
    # Exposure decay settings
    parser.add_argument("--exposure-passes", type=int, default=2,
                        help="Number of exposure cleanup passes (default: 2)")
    parser.add_argument("--exposure-threshold", type=int, default=4,
                        help="Air neighbors needed to trigger exposure decay (default: 4)")
    parser.add_argument("--exposure-chance", type=float, default=0.7,
                        help="Chance to decay when exposure threshold met (default: 0.7)")
    
    args = parser.parse_args()
    
    num_workers = args.workers or cpu_count()
    
    # Load config
    with open(args.config) as f:
        config = json.load(f)
    
    print("=" * 70)
    print("MULTI-PASS EROSION (Parallel)")
    print("=" * 70)
    print(f"\n📂 Input: {args.input}")
    print(f"📂 Output: {args.output}")
    print(f"⚡ Workers: {num_workers}")
    print(f"\n🔧 Material Decay: {args.material_passes} passes @ {args.material_rate*100:.0f}% rate")
    print(f"🔧 Structural Decay: {args.structural_passes} passes @ {args.structural_rate*100:.0f}% rate")
    print(f"🔧 Exposure Decay: {args.exposure_passes} passes, threshold={args.exposure_threshold}, {args.exposure_chance*100:.0f}% chance")
    print()
    
    # Load chunks
    print("Loading chunks...")
    chunks_data = []
    for cx, cz, blocks, palette in tqdm(read_bin_generator(args.input), desc="Loading", unit="chunk"):
        chunks_data.append((cx, cz, blocks, list(palette)))
    print(f"✓ Loaded {len(chunks_data):,} chunks\n")
    
    # Prepare worker params
    worker_params = {
        'material_passes': args.material_passes,
        'material_rate': args.material_rate,
        'structural_passes': args.structural_passes,
        'structural_rate': args.structural_rate,
        'exposure_passes': args.exposure_passes,
        'exposure_threshold': args.exposure_threshold,
        'exposure_chance': args.exposure_chance
    }
    
    # Process chunks in parallel
    print("Processing with multiprocessing...")
    total_material = 0
    total_structural = 0
    total_exposure = 0
    processed_chunks = []
    
    # Process chunks in parallel
    with Pool(processes=num_workers, initializer=_init_worker, initargs=(config, worker_params)) as pool:
        results = list(tqdm(
            pool.imap(_process_chunk_worker, chunks_data),
            total=len(chunks_data),
            desc="Eroding",
            unit="chunk"
        ))
    
    for cx, cz, blocks, palette, mat, struct, exp in results:
        processed_chunks.append((cx, cz, blocks, palette))
        total_material += mat
        total_structural += struct
        total_exposure += exp
    
    print(f"\n✓ Material decay: {total_material:,} block transformations")
    print(f"✓ Structural decay: {total_structural:,} block transformations")
    print(f"✓ Exposure decay: {total_exposure:,} blocks removed")
    print(f"✓ Total changes: {total_material + total_structural + total_exposure:,}")
    
    # Build global palette
    print("\nBuilding global palette...")
    global_palette = []
    palette_set = set()
    for cx, cz, blocks, palette in processed_chunks:
        for name in palette:
            if name not in palette_set:
                palette_set.add(name)
                global_palette.append(name)
    
    # Remap and write
    print(f"Writing to {args.output}...")
    
    def chunk_generator():
        for cx, cz, blocks, palette in tqdm(processed_chunks, desc="Remapping", unit="chunk"):
            # Remap to global palette
            local_to_global = np.array([global_palette.index(n) for n in palette], dtype=np.uint16)
            remapped = local_to_global[blocks]
            yield cx, cz, remapped
    
    write_bin(args.output, chunk_generator(), global_palette)
    
    print("\n" + "=" * 70)
    print("EROSION COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {args.output}")
    print(f"✓ Palette: {len(global_palette)} unique blocks")


if __name__ == "__main__":
    main()
