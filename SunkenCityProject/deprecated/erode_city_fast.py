import argparse
import json
import numpy as np
import random
from opensimplex import OpenSimplex
from numba import jit, prange
from city_utils import read_bin_generator
import struct
import zlib

class FastEroder:
    def __init__(self, config):
        self.settings = config["global_settings"]
        self.ignored = set(config.get("ignored", []))
        
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
        
        # Look up category
        category = self.block_to_category.get(block_name)
        if not category:
            # Unknown block - default decay to air with 70% chance
            if random.random() < 0.7:
                return "minecraft:air"
            return block_name
        
        # Get replacements for this category
        replacements = self.category_replacements.get(category, [])
        if not replacements:
            return block_name  # No replacements defined
        
        # Pick transition based on weights
        choices, weights = zip(*replacements)
        return random.choices(choices, weights=weights, k=1)[0]

    def process_chunk(self, blocks, palette, cx, cz):
        """Apply CA physics with Numba optimization."""
        H = blocks.shape[1]
        
        # Pre-compute noise field for entire chunk (vectorized, much faster)
        noise_field = self._compute_noise_field(cx, cz, H)
        
        # Build index-to-name mapping and ignored array
        id_to_name = {i: name for i, name in enumerate(palette)}
        
        # Create boolean array for ignored indices
        max_idx = max(id_to_name.keys()) + 1
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
    """JIT-compiled function to compute which blocks should change.
    Returns arrays of x, y, z, block_idx for blocks that need replacement."""
    # Pre-allocate arrays for changes (worst case: all blocks)
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
                
                # Skip air
                if idx == 0:
                    continue
                
                # Skip ignored blocks
                if idx < len(ignored_arr) and ignored_arr[idx]:
                    continue
                
                # --- PHYSICS CHECK ---
                instability = noise_field[x, y, z]
                
                # 2. Gravity
                below_idx = snapshot[x, y-1, z] if y > 0 else 1
                if below_idx == 0:
                    instability += 1.0
                
                # 3. Exposure
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
                
                # --- DECISION ---
                if instability > threshold:
                    change_x[count] = x
                    change_y[count] = y
                    change_z[count] = z
                    change_idx[count] = idx
                    count += 1
    
    # Return only the filled portion
    return change_x[:count], change_y[:count], change_z[:count], change_idx[:count]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", default="city_eroded_fast.bin")
    args = parser.parse_args()
    
    with open(args.config) as f:
        config = json.load(f)
        
    eroder = FastEroder(config)
    
    # Load all chunks into memory (file is ~4.5MB, easily fits in 64GB RAM)
    print("Loading city data into memory...")
    chunks = []
    global_palette = None
    
    for cx, cz, blocks, palette in read_bin_generator(args.input):
        chunks.append((cx, cz, blocks, list(palette)))
        global_palette = list(palette)  # Keep the latest palette
        
    print(f"Loaded {len(chunks)} chunks.")
    
    # Process all chunks
    print("Processing erosion with Numba acceleration...")
    import time
    start_time = time.time()
    
    processed_chunks = []
    for i, (cx, cz, blocks, palette) in enumerate(chunks):
        new_blocks, new_palette = eroder.process_chunk(blocks, palette, cx, cz)
        processed_chunks.append((cx, cz, new_blocks, new_palette))
        
        # Update global palette with any new blocks
        for block in new_palette:
            if block not in global_palette:
                global_palette.append(block)
        
        print(f"Processed chunk {i+1}/{len(chunks)}...", end='\r')
    
    elapsed = time.time() - start_time
    print(f"\nProcessing completed in {elapsed:.2f} seconds ({elapsed/len(chunks):.3f}s per chunk)")
    
    print("Writing output...")
    with open(args.out, 'wb') as f:
        f.write(b'EROS')
        f.write(struct.pack('<Q', 0))  # Placeholder for palette offset
        
        for cx, cz, blocks, palette in processed_chunks:
            raw = blocks.astype(np.uint16).tobytes()
            comp = zlib.compress(raw)
            f.write(struct.pack('<iiiI', cx, cz, len(raw), len(comp)))
            f.write(comp)
            
        # Write global palette
        ptr = f.tell()
        f.write(json.dumps(global_palette).encode('utf-8'))
        f.seek(4)
        f.write(struct.pack('<Q', ptr))
        
    print(f"Done! Saved to {args.out}")
    print(f"Final palette contains {len(global_palette)} unique blocks.")

if __name__ == "__main__":
    main()
