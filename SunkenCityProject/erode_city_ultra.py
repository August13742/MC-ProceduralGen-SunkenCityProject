import argparse
import json
import numpy as np
import random
from opensimplex import OpenSimplex
from numba import jit, prange
from tqdm import tqdm
from city_utils import read_bin_generator
import struct
import zlib
from multiprocessing import Pool, cpu_count
import os

class UltraFastEroder:
    def __init__(self, config):
        self.settings = config["global_settings"]
        self.ignored = set(config.get("ignored", []))
        self.universal_decay = self.settings.get("universal_decay_chance", 0.0)
        
        # Build reverse mapping from blocks to their categories and replacements
        self.block_to_category = {}
        self.category_replacements = {}
        
        for category_name, category_data in config.get("categories", {}).items():
            blocks = category_data.get("blocks", [])
            replacements = category_data.get("replacements", [])
            
            for block in blocks:
                self.block_to_category[block] = category_name
            
            self.category_replacements[category_name] = replacements
        
        self.noise = OpenSimplex(seed=self.settings.get("seed", 1234))
        self.passes = self.settings.get("passes", 2)
        self.erosion_rate = self.settings.get("erosion_rate", 0.3)

    def get_replacement(self, block_name):
        """Returns new block ID string based on config weights."""
        if block_name in self.ignored: 
            return block_name
        
        # First, apply category-specific replacements
        category = self.block_to_category.get(block_name)
        new_block = block_name  # Default to no change
        
        if category:
            # Get replacements for this category
            replacements = self.category_replacements.get(category, [])
            if replacements:
                # Pick transition based on weights
                choices, weights = zip(*replacements)
                new_block = random.choices(choices, weights=weights, k=1)[0]
        
        # Then, apply universal decay to ALL blocks (even after category replacement)
        # This ensures structures aren't too intact
        if self.universal_decay > 0 and new_block != "minecraft:air":
            if random.random() < self.universal_decay:
                return "minecraft:air"
        
        return new_block

    def process_chunk(self, blocks, palette, cx, cz):
        """Apply CA physics with Numba optimization."""
        H = blocks.shape[1]
        
        # Pre-compute noise field for entire chunk
        noise_field = self._compute_noise_field(cx, cz, H)
        
        # Build index-to-name mapping and ignored array
        id_to_name = {i: name for i, name in enumerate(palette)}
        
        # Create boolean array for ignored indices
        max_idx = max(id_to_name.keys()) + 1 if id_to_name else 1
        ignored_arr = np.zeros(max_idx, dtype=np.bool_)
        for i, name in id_to_name.items():
            if name in self.ignored:
                ignored_arr[i] = True
        
        # Create lookup table for palette index
        name_to_idx = {name: i for i, name in enumerate(palette)}
        
        # Process with Numba
        current_grid = blocks.copy()
        threshold = 1.0 - self.erosion_rate
        
        for p in range(self.passes):
            snapshot = current_grid.copy()
            
            # Call JIT-compiled function
            change_x, change_y, change_z, change_idx = compute_instability_and_changes(
                snapshot, noise_field, threshold, ignored_arr, H
            )
            
            # Apply replacements based on changes
            for i in range(len(change_x)):
                x, y, z, idx = change_x[i], change_y[i], change_z[i], change_idx[i]
                name = id_to_name[idx]
                new_name = self.get_replacement(name)
                
                if new_name != name:
                    # Update palette if needed
                    if new_name not in name_to_idx:
                        palette.append(new_name)
                        new_idx = len(palette) - 1
                        name_to_idx[new_name] = new_idx
                        id_to_name[new_idx] = new_name
                        # Expand ignored_arr if needed
                        if new_idx >= len(ignored_arr):
                            new_ignored = np.zeros(new_idx + 1, dtype=np.bool_)
                            new_ignored[:len(ignored_arr)] = ignored_arr
                            ignored_arr = new_ignored
                    else:
                        new_idx = name_to_idx[new_name]
                    
                    current_grid[x, y, z] = new_idx

        # MATERIAL-BASED DECAY PASS: Apply decay to ALL blocks based on category
        # This ensures even structurally-stable blocks get weathered
        material_decay_rate = self.settings.get("material_decay_rate", 0.3)
        if material_decay_rate > 0:
            for x in range(16):
                for z in range(16):
                    for y in range(H):
                        idx = current_grid[x, y, z]
                        if idx == 0:  # Skip air
                            continue
                        if idx < len(ignored_arr) and ignored_arr[idx]:
                            continue
                        
                        name = id_to_name.get(idx, "")
                        if name in self.block_to_category:
                            # Block has a category - apply material decay
                            if random.random() < material_decay_rate:
                                new_name = self.get_replacement(name)
                                if new_name != name:
                                    if new_name not in name_to_idx:
                                        palette.append(new_name)
                                        new_idx = len(palette) - 1
                                        name_to_idx[new_name] = new_idx
                                        id_to_name[new_idx] = new_name
                                    else:
                                        new_idx = name_to_idx[new_name]
                                    current_grid[x, y, z] = new_idx

        return current_grid, palette
    
    def _compute_noise_field(self, cx, cz, H):
        """Pre-compute noise for entire chunk (vectorized)."""
        noise_field = np.zeros((16, H, 16), dtype=np.float32)
        
        for x in range(16):
            for z in range(16):
                for y in range(H):
                    n_val = (self.noise.noise3(x*0.1 + cx*16, y*0.1, z*0.1 + cz*16) + 1) / 2
                    noise_field[x, y, z] = n_val * 0.4
        
        return noise_field


@jit(nopython=True, cache=True, parallel=True)
def compute_instability_and_changes(snapshot, noise_field, threshold, ignored_arr, H):
    """JIT-compiled function to compute which blocks should change."""
    max_changes = 16 * H * 16
    change_x = np.zeros(max_changes, dtype=np.int32)
    change_y = np.zeros(max_changes, dtype=np.int32)
    change_z = np.zeros(max_changes, dtype=np.int32)
    change_idx = np.zeros(max_changes, dtype=np.int32)
    count = 0
    
    for x in prange(16):
        for z in range(16):
            for y in range(H - 1, -1, -1):
                idx = snapshot[x, y, z]
                
                if idx == 0:
                    continue
                
                if idx < len(ignored_arr) and ignored_arr[idx]:
                    continue
                
                instability = noise_field[x, y, z]
                
                below_idx = snapshot[x, y-1, z] if y > 0 else 1
                if below_idx == 0:
                    instability += 1.0
                
                neighbors = 0
                if y < H-1 and snapshot[x, y+1, z] == 0:
                    neighbors += 1
                if x > 0 and snapshot[x-1, y, z] == 0:
                    neighbors += 1
                if x < 15 and snapshot[x+1, y, z] == 0:
                    neighbors += 1
                if z > 0 and snapshot[x, y, z-1] == 0:
                    neighbors += 1
                if z < 15 and snapshot[x, y, z+1] == 0:
                    neighbors += 1
                
                instability += neighbors * 0.1
                
                if instability > threshold:
                    change_x[count] = x
                    change_y[count] = y
                    change_z[count] = z
                    change_idx[count] = idx
                    count += 1
    
    return change_x[:count], change_y[:count], change_z[:count], change_idx[:count]


# Global config for multiprocessing
_global_config = None

def _init_worker(config):
    """Initialize worker process with config."""
    global _global_config
    _global_config = config

def _process_chunk_worker(args):
    """Worker function for multiprocessing."""
    cx, cz, blocks, palette = args
    eroder = UltraFastEroder(_global_config)
    new_blocks, new_palette = eroder.process_chunk(blocks, palette, cx, cz)
    return (cx, cz, new_blocks, new_palette)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", default="city_eroded_ultra.bin")
    parser.add_argument("--workers", type=int, default=None, 
                       help="Number of worker processes (default: CPU count)")
    args = parser.parse_args()
    
    with open(args.config) as f:
        config = json.load(f)
    
    num_workers = args.workers or cpu_count()
    print(f"Using {num_workers} worker processes")
    
    # Load all chunks into memory
    chunks = []
    global_palette = None
    
    pbar = tqdm(desc="Loading chunks", unit="chunk")
    for cx, cz, blocks, palette in read_bin_generator(args.input):
        chunks.append((cx, cz, blocks, list(palette)))
        global_palette = list(palette)
        pbar.update(1)
    
    pbar.close()
    print(f"Loaded {len(chunks)} chunks.")
    
    # Process all chunks in parallel
    print("Processing erosion with Numba + multiprocessing...")
    import time
    start_time = time.time()
    
    # Use multiprocessing pool with progress bar
    with Pool(processes=num_workers, initializer=_init_worker, initargs=(config,)) as pool:
        processed_chunks = list(tqdm(
            pool.imap(_process_chunk_worker, chunks),
            total=len(chunks),
            desc="Eroding chunks",
            unit="chunk"
        ))
    
    # Update global palette efficiently using a set
    print("Building global palette...")
    global_palette_set = set(global_palette)
    for _, _, _, palette in tqdm(processed_chunks, desc="Building palette", unit="chunk"):
        for block in palette:
            if block not in global_palette_set:
                global_palette_set.add(block)
                global_palette.append(block)
    
    elapsed = time.time() - start_time
    print(f"\nProcessing completed in {elapsed:.2f} seconds")
    print(f"  Average: {elapsed/len(chunks):.3f}s per chunk")
    print(f"  Throughput: {len(chunks)/elapsed:.1f} chunks/sec")
    
    print("Writing output...")
    with open(args.out, 'wb') as f:
        f.write(b'EROS')
        f.write(struct.pack('<Q', 0))
        
        for cx, cz, blocks, palette in tqdm(processed_chunks, desc="Writing chunks", unit="chunk"):
            raw = blocks.astype(np.uint16).tobytes()
            comp = zlib.compress(raw)
            f.write(struct.pack('<iiiI', cx, cz, len(raw), len(comp)))
            f.write(comp)
            
        ptr = f.tell()
        f.write(json.dumps(global_palette).encode('utf-8'))
        f.seek(4)
        f.write(struct.pack('<Q', ptr))
        
    print(f"Done! Saved to {args.out}")
    print(f"Final palette contains {len(global_palette)} unique blocks.")

if __name__ == "__main__":
    main()
