import argparse
import json
import numpy as np
import random
from opensimplex import OpenSimplex
from city_utils import read_bin_generator, write_bin

class HybridEroder:
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
        """Apply CA physics, using JSON rules for outcomes."""
        H = blocks.shape[1]
        
        # Map palette indices to Block Names for easy lookup
        # (Optimization: We could map indices to rule objects directly, but this is clearer)
        id_to_name = {i: name for i, name in enumerate(palette)}
        
        # Create a working copy
        current_grid = blocks.copy()
        
        for p in range(self.passes):
            snapshot = current_grid.copy()
            
            # Iterate Volume
            # (Note: Python loops are slow for 16x256x16. For production, use Numba or just wait)
            for x in range(16):
                for z in range(16):
                    for y in range(H - 1, -1, -1):
                        idx = snapshot[x, y, z]
                        if idx == 0: continue # Air
                        
                        name = id_to_name[idx]
                        if name in self.ignored: continue
                        
                        # --- PHYSICS CHECK ---
                        instability = 0.0
                        
                        # 1. Noise (The "Chaos" Factor)
                        n_val = (self.noise.noise3(x*0.1 + cx*16, y*0.1, z*0.1 + cz*16) + 1) / 2
                        instability += n_val * 0.4
                        
                        # 2. Gravity (The "Structure" Factor)
                        # If block below is Air/Water (assuming water is non-structural for bricks)
                        below_idx = snapshot[x, y-1, z] if y > 0 else 1 # Treat floor as solid
                        if below_idx == 0: 
                            instability += 1.0 # Massive penalty for floating
                            
                        # 3. Exposure (The "Rot" Factor)
                        # Simplified neighbor check (only checking up/down/NSEW within chunk)
                        neighbors = 0
                        if y < H-1 and snapshot[x, y+1, z] == 0: neighbors += 1
                        if x > 0 and snapshot[x-1, y, z] == 0: neighbors += 1
                        if x < 15 and snapshot[x+1, y, z] == 0: neighbors += 1
                        if z > 0 and snapshot[x, y, z-1] == 0: neighbors += 1
                        if z < 15 and snapshot[x, y, z+1] == 0: neighbors += 1
                        
                        instability += (neighbors * 0.1)
                        
                        # --- DECISION ---
                        threshold = 1.0 - self.settings.get("erosion_rate", 0.3)
                        
                        if instability > threshold:
                            new_name = self.get_replacement(name)
                            
                            # If the block changed
                            if new_name != name:
                                # Update Palette
                                if new_name not in palette:
                                    palette.append(new_name)
                                    id_to_name[len(palette)-1] = new_name
                                    new_idx = len(palette)-1
                                else:
                                    new_idx = palette.index(new_name)
                                
                                current_grid[x, y, z] = new_idx

        return current_grid, palette

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", default="city_eroded_hybrid.bin")
    args = parser.parse_args()
    
    with open(args.config) as f:
        config = json.load(f)
        
    eroder = HybridEroder(config)
    
    # Load all chunks into memory (file is ~4.5MB, easily fits in 64GB RAM)
    print("Loading city data into memory...")
    chunks = []
    global_palette = None
    
    for cx, cz, blocks, palette in read_bin_generator(args.input):
        chunks.append((cx, cz, blocks, list(palette)))
        global_palette = list(palette)  # Keep the latest palette
        
    print(f"Loaded {len(chunks)} chunks.")
    
    # Process all chunks
    print("Processing erosion...")
    import struct
    import zlib
    
    processed_chunks = []
    for i, (cx, cz, blocks, palette) in enumerate(chunks):
        new_blocks, new_palette = eroder.process_chunk(blocks, palette, cx, cz)
        processed_chunks.append((cx, cz, new_blocks, new_palette))
        
        # Update global palette with any new blocks
        for block in new_palette:
            if block not in global_palette:
                global_palette.append(block)
        
        print(f"Processed chunk {i+1}/{len(chunks)}...", end='\r')
    
    print("\nWriting output...")
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