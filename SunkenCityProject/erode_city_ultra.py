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
                # Pick transition based on weights (cached if possible)
                choices, weights = zip(*replacements)
                new_block = random.choices(choices, weights=weights, k=1)[0]
        
        # Then, apply universal decay to ALL blocks (even after category replacement)
        # This ensures structures aren't too intact
        if self.universal_decay > 0 and new_block != "minecraft:air":
            if random.random() < self.universal_decay:
                return "minecraft:air"
        
        return new_block
    
    def get_replacement_batch(self, block_names):
        """Batch version for better performance."""
        return [self.get_replacement(name) for name in block_names]

    def process_chunk(self, blocks, palette, cx, cz):
        """Apply CA physics with Numba optimization."""
        H = blocks.shape[1]
        
        # Pre-compute noise field for entire chunk
        noise_field = self._compute_noise_field(cx, cz, H)
        
        # Build mappings
        id_to_name = {i: name for i, name in enumerate(palette)}
        name_to_idx = {name: i for i, name in enumerate(palette)}
        
        # Create boolean array for ignored indices
        max_idx = len(palette)
        ignored_arr = np.zeros(max_idx, dtype=np.bool_)
        for i in range(max_idx):
            if palette[i] in self.ignored:
                ignored_arr[i] = True
        
        # Process with Numba
        current_grid = blocks.copy()
        threshold = 1.0 - self.erosion_rate
        
        for p in range(self.passes):
            snapshot = current_grid.copy()
            
            # Call JIT-compiled function
            change_x, change_y, change_z, change_idx = compute_instability_and_changes(
                snapshot, noise_field, threshold, ignored_arr, H
            )
            
            # Batch process replacements
            num_changes = len(change_x)
            if num_changes == 0:
                continue
            
            # Get all block names that need replacement
            block_names = [id_to_name[change_idx[i]] for i in range(num_changes)]
            new_names = self.get_replacement_batch(block_names)
            
            # Apply replacements
            for i in range(num_changes):
                x, y, z = change_x[i], change_y[i], change_z[i]
                name = block_names[i]
                new_name = new_names[i]
                
                if new_name != name:
                    # Get or add to palette
                    if new_name not in name_to_idx:
                        new_idx = len(palette)
                        palette.append(new_name)
                        name_to_idx[new_name] = new_idx
                        id_to_name[new_idx] = new_name
                        # Expand ignored_arr if needed
                        if new_idx >= len(ignored_arr):
                            old_len = len(ignored_arr)
                            new_ignored = np.zeros(new_idx + 10, dtype=np.bool_)  # Extra buffer
                            new_ignored[:old_len] = ignored_arr
                            ignored_arr = new_ignored
                            if new_name in self.ignored:
                                ignored_arr[new_idx] = True
                    else:
                        new_idx = name_to_idx[new_name]
                    
                    current_grid[x, y, z] = new_idx

        # MATERIAL-BASED DECAY PASS: Apply decay to ALL blocks based on category
        # This ensures even structurally-stable blocks get weathered
        material_decay_rate = self.settings.get("material_decay_rate", 0.3)
        if material_decay_rate > 0:
            ignored_len = len(ignored_arr)
            for y in range(H):  # Y-first for better cache locality
                for x in range(16):
                    for z in range(16):
                        idx = current_grid[x, y, z]
                        if idx == 0:  # Skip air
                            continue
                        if idx < ignored_len and ignored_arr[idx]:
                            continue
                        
                        name = id_to_name.get(idx)
                        if name and name in self.block_to_category:
                            # Block has a category - apply material decay
                            if random.random() < material_decay_rate:
                                new_name = self.get_replacement(name)
                                if new_name != name:
                                    if new_name not in name_to_idx:
                                        new_idx = len(palette)
                                        palette.append(new_name)
                                        name_to_idx[new_name] = new_idx
                                        id_to_name[new_idx] = new_name
                                    else:
                                        new_idx = name_to_idx[new_name]
                                    current_grid[x, y, z] = new_idx

        return current_grid, palette
    
    def _compute_noise_field(self, cx, cz, H):
        """Pre-compute noise for entire chunk (optimized)."""
        noise_field = np.zeros((16, H, 16), dtype=np.float32)
        
        # Create coordinate grids
        cx_offset = cx * 16
        cz_offset = cz * 16
        
        # Compute noise in chunks for better cache locality
        for y in range(H):
            y_scaled = y * 0.1
            for x in range(16):
                x_scaled = (x + cx_offset) * 0.1
                for z in range(16):
                    z_scaled = (z + cz_offset) * 0.1
                    n_val = (self.noise.noise3(x_scaled, y_scaled, z_scaled) + 1) / 2
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
    
    # Calculate optimal chunk size for imap
    chunksize = max(1, len(chunks) // (num_workers * 4))
    
    # Use multiprocessing pool with progress bar
    with Pool(processes=num_workers, initializer=_init_worker, initargs=(config,)) as pool:
        processed_chunks = list(tqdm(
            pool.imap(_process_chunk_worker, chunks, chunksize=chunksize),
            total=len(chunks),
            desc="Eroding chunks",
            unit="chunk",
            smoothing=0.1
        ))
    
    # Update global palette efficiently using a set
    print("Building global palette...")
    global_palette_set = set(global_palette)
    new_blocks = []
    
    for _, _, _, palette in processed_chunks:
        for block in palette:
            if block not in global_palette_set:
                global_palette_set.add(block)
                new_blocks.append(block)
    
    global_palette.extend(new_blocks)
    if new_blocks:
        print(f"  Added {len(new_blocks)} new blocks to palette")
    
    elapsed = time.time() - start_time
    print(f"\nProcessing completed in {elapsed:.2f} seconds")
    print(f"  Average: {elapsed/len(chunks):.3f}s per chunk")
    print(f"  Throughput: {len(chunks)/elapsed:.1f} chunks/sec")
    
    print("Writing output...")
    total_compressed = 0
    total_uncompressed = 0
    
    with open(args.out, 'wb') as f:
        f.write(b'EROS')
        f.write(struct.pack('<Q', 0))  # Placeholder for palette pointer
        
        for cx, cz, blocks, palette in tqdm(processed_chunks, desc="Writing chunks", unit="chunk"):
            raw = blocks.astype(np.uint16).tobytes()
            comp = zlib.compress(raw, level=6)  # Balance speed/compression
            total_uncompressed += len(raw)
            total_compressed += len(comp)
            f.write(struct.pack('<iiiI', cx, cz, len(raw), len(comp)))
            f.write(comp)
            
        ptr = f.tell()
        palette_json = json.dumps(global_palette)
        f.write(palette_json.encode('utf-8'))
        f.seek(4)
        f.write(struct.pack('<Q', ptr))
    
    compression_ratio = 100 * (1 - total_compressed / total_uncompressed) if total_uncompressed > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"Done! Saved to {args.out}")
    print(f"  Chunks: {len(processed_chunks)}")
    print(f"  Palette: {len(global_palette)} unique blocks")
    print(f"  Compression: {compression_ratio:.1f}% ({total_compressed:,} / {total_uncompressed:,} bytes)")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
