import argparse
import json
import numpy as np
import sys
import os
from opensimplex import OpenSimplex
from city_utils import read_bin_generator, write_bin

# python SunkenCityProject/erode_city.py --input city_original.bin --config erosion_config_fixed.json --out city_eroded.bin

# Add parent directory to path to import normalise_block
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from normalise_block import normalise_block

class ErosionProcessor:
    def __init__(self, config):
        self.config = config
        self.categories = config['categories']
        self.global_settings = config['global_settings']
        self.ignored_blocks = set(config.get('ignored', []))
        
        # Setup Noise
        self.noise_gen = OpenSimplex(seed=self.global_settings.get('seed', 1234))
        
        # Internal Palette
        self.palette = ["minecraft:air"]
        self.palette_map = {"minecraft:air": 0}
    
    def get_id(self, block_name: str) -> int:
        """Get or create ID for block string."""
        # Normalize the block name to ensure it's a valid Minecraft ID
        # This handles generic names like 'minecraft:planks' -> 'minecraft:oak_planks'
        normalized_name, _ = normalise_block(block_name, {})
        
        if normalized_name not in self.palette_map:
            idx = len(self.palette)
            self.palette.append(normalized_name)
            self.palette_map[normalized_name] = idx
        return self.palette_map[normalized_name]
    
    def process_chunk(self, chunk_blocks, cx, cz):
        """Apply erosion rules to a 3D numpy array of IDs."""
        # Generate deterministic noise map based on chunk coords
        seed_val = ((cx * 34123) ^ (cz * 4231)) & 0xFFFFFFFF
        np.random.seed(seed_val)
        noise_map = np.random.random_sample(chunk_blocks.shape)
        
        result = chunk_blocks.copy()
        
        # Iterate Categories
        for cat_name, data in self.categories.items():
            blocks_in_cat = data['blocks']
            rules = data['replacements']
            
            if not rules:
                continue
            
            # Get valid IDs for this category
            valid_ids = [self.palette_map[b] for b in blocks_in_cat if b in self.palette_map]
            if not valid_ids:
                continue
            
            # Create Boolean Mask
            cat_mask = np.isin(chunk_blocks, valid_ids)
            
            if not np.any(cat_mask):
                continue
            
            # Apply Replacements
            current_threshold = 0.0
            
            for target_name, chance in rules:
                target_id = self.get_id(target_name)
                
                lower = current_threshold
                upper = current_threshold + chance
                
                change_mask = cat_mask & (noise_map >= lower) & (noise_map < upper)
                result[change_mask] = target_id
                
                current_threshold += chance
        
        return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="city_original.bin")
    parser.add_argument("--config", required=True, help="erosion_config.json")
    parser.add_argument("--out", default="city_eroded.bin")
    parser.add_argument("--peaks-out", default="peaks.json")
    parser.add_argument("--sea-level", type=int, default=63)
    parser.add_argument("--seed", type=int, default=13742)
    args = parser.parse_args()

    # Load Config
    with open(args.config) as f:
        cfg = json.load(f)
    
    eroder = ErosionProcessor(cfg)
    eroder.global_settings['seed'] = args.seed
    peaks = []

    def process_stream():
        # Generator that reads raw -> erodes -> yields eroded
        
        for cx, cz, blocks, palette in read_bin_generator(args.input):
            # Pre-process: Map input palette to eroder's internal palette
            lut = np.zeros(len(palette), dtype=np.uint16)
            for i, block_name in enumerate(palette):
                lut[i] = eroder.get_id(block_name)
            
            # Convert blocks to global IDs
            blocks_mapped = lut[blocks]
            
            # Apply Erosion
            eroded_blocks = eroder.process_chunk(blocks_mapped, cx, cz)
            
            # Peak Detection
            # Scan top-down for solid blocks
            heights = np.zeros((16, 16), dtype=int)
            for x in range(16):
                for z in range(16):
                    col = eroded_blocks[x, :, z]
                    non_zeros = np.nonzero(col)[0]
                    if len(non_zeros) > 0:
                        heights[x, z] = non_zeros[-1] - 64
            
            # Find local maxima in chunk
            mx, mz = np.unravel_index(np.argmax(heights), heights.shape)
            max_y = heights[mx, mz]
            
            # Save Peak if in support range
            if max_y > -40 and max_y < (args.sea_level - 5):
                peaks.append(((cx * 16) + int(mx), int(max_y), (cz * 16) + int(mz)))

            yield cx, cz, eroded_blocks
    
    # Write the eroded binary with final palette
    write_bin(args.out, process_stream(), eroder.palette)
    
    # Save Peaks
    with open(args.peaks_out, 'w') as f:
        json.dump(peaks, f)
    print(f"Saved {len(peaks)} potential island sites to {args.peaks_out}")

if __name__ == "__main__":
    main()