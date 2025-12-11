"""
structural_blend.py

Creates organic ground connection for sunken city structures.
Generates vertical support pillars and gradual terrain blending
to prevent floating structures.

Usage:
    python SunkenCityProject/structural_blend.py \
        --input city_eroded.bin \
        --output city_blended.bin \
        --ground-level 60 \
        --city-level 20 \
        --blend-radius 3
"""

import argparse
import numpy as np
import random
from opensimplex import OpenSimplex
from tqdm import tqdm
from city_utils import read_bin_generator
import struct
import zlib
import json

class StructuralBlender:
    def __init__(self, ground_level=60, city_level=20, blend_radius=3, seed=13742):
        self.ground_level = ground_level
        self.city_level = city_level
        self.blend_radius = blend_radius
        self.noise = OpenSimplex(seed=seed)
        
        # Blending materials (weighted choices)
        self.support_materials = [
            ("minecraft:stone", 0.3),
            ("minecraft:cobblestone", 0.25),
            ("minecraft:mossy_cobblestone", 0.2),
            ("minecraft:andesite", 0.15),
            ("minecraft:dirt", 0.05),
            ("minecraft:mud", 0.05)
        ]
        
        self.vine_materials = [
            ("minecraft:vine", 0.6),
            ("minecraft:moss_carpet", 0.2),
            ("minecraft:glow_lichen", 0.15),
            ("minecraft:air", 0.05)
        ]
    
    def should_create_support(self, x, y, z, has_block_above):
        """Determine if support column should be placed here."""
        if not has_block_above:
            return False
        
        # Use noise to create irregular support pattern
        noise_val = self.noise.noise3(x * 0.1, y * 0.1, z * 0.1)
        
        # More support near edges of structures
        if y < self.city_level + 5:
            threshold = 0.3
        else:
            threshold = 0.5
        
        return noise_val > threshold
    
    def get_support_block(self, y):
        """Get material for support based on height."""
        # Transition from stone at bottom to organic materials at top
        height_ratio = (y - self.city_level) / (self.ground_level - self.city_level)
        
        if height_ratio < 0.3:
            # Lower section: mostly stone
            choices = [
                ("minecraft:stone", 0.5),
                ("minecraft:cobblestone", 0.4),
                ("minecraft:andesite", 0.1)
            ]
        elif height_ratio < 0.7:
            # Middle section: mix
            choices = self.support_materials
        else:
            # Upper section: more organic
            choices = [
                ("minecraft:dirt", 0.4),
                ("minecraft:mud", 0.3),
                ("minecraft:mossy_cobblestone", 0.2),
                ("minecraft:moss_block", 0.1)
            ]
        
        blocks, weights = zip(*choices)
        return random.choices(blocks, weights=weights, k=1)[0]
    
    def add_vegetation_detail(self, x, y, z):
        """Add hanging vegetation to support columns."""
        noise_val = self.noise.noise3(x * 0.2, y * 0.2, z * 0.2)
        
        # Only add vegetation in upper portions
        height_ratio = (y - self.city_level) / (self.ground_level - self.city_level)
        if height_ratio < 0.5 or noise_val < 0.2:
            return None
        
        blocks, weights = zip(*self.vine_materials)
        return random.choices(blocks, weights=weights, k=1)[0]
    
    def process_chunk(self, blocks, palette, cx, cz):
        """Add structural supports to a chunk."""
        H = blocks.shape[1]
        
        # Create name mappings
        name_to_idx = {name: i for i, name in enumerate(palette)}
        air_idx = name_to_idx.get("minecraft:air", 0)
        
        # Track which columns need support
        for x in range(16):
            for z in range(16):
                # Find highest non-air block
                highest_block_y = -1
                for y in range(H - 1, -1, -1):
                    if blocks[x, y, z] != air_idx:
                        highest_block_y = y
                        break
                
                if highest_block_y < 0:
                    continue
                
                # Convert to world coordinates
                world_x = cx * 16 + x
                world_z = cz * 16 + z
                
                # Check if we should create support column
                # Support columns go from city_level down to ground_level
                for y in range(self.city_level, self.ground_level):
                    if y >= H:
                        break
                    
                    # Check if there's a structure block above
                    has_structure_above = False
                    for check_y in range(y + 1, min(highest_block_y + 1, H)):
                        if blocks[x, check_y, z] != air_idx:
                            has_structure_above = True
                            break
                    
                    if has_structure_above and self.should_create_support(world_x, y, world_z, True):
                        # Place support block
                        support_block = self.get_support_block(y)
                        
                        # Add to palette if needed
                        if support_block not in name_to_idx:
                            palette.append(support_block)
                            name_to_idx[support_block] = len(palette) - 1
                        
                        blocks[x, y, z] = name_to_idx[support_block]
                        
                        # Maybe add vegetation on sides
                        for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                            nx, nz = x + dx, z + dz
                            if 0 <= nx < 16 and 0 <= nz < 16:
                                if blocks[nx, y, nz] == air_idx:
                                    veg = self.add_vegetation_detail(world_x + dx, y, world_z + dz)
                                    if veg and veg != "minecraft:air":
                                        if veg not in name_to_idx:
                                            palette.append(veg)
                                            name_to_idx[veg] = len(palette) - 1
                                        blocks[nx, y, nz] = name_to_idx[veg]
        
        return blocks, palette


def main():
    parser = argparse.ArgumentParser(description="Add structural blending to sunken city")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--output", required=True, help="Output .bin file")
    parser.add_argument("--ground-level", type=int, default=60, help="Ground level Y coordinate")
    parser.add_argument("--city-level", type=int, default=20, help="City placement Y coordinate")
    parser.add_argument("--blend-radius", type=int, default=3, help="Blending radius")
    parser.add_argument("--seed", type=int, default=13742, help="Random seed")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("STRUCTURAL BLENDING TOOL")
    print("=" * 70)
    print(f"\n📂 Input: {args.input}")
    print(f"📂 Output: {args.output}")
    print(f"🌍 Ground Level: Y={args.ground_level}")
    print(f"🏛️  City Level: Y={args.city_level}")
    print(f"🔄 Blend Radius: {args.blend_radius} blocks\n")
    
    blender = StructuralBlender(
        ground_level=args.ground_level,
        city_level=args.city_level,
        blend_radius=args.blend_radius,
        seed=args.seed
    )
    
    # Read input file
    chunks_data = []
    
    pbar = tqdm(desc="Processing chunks", unit="chunk")
    for cx, cz, blocks, palette in read_bin_generator(args.input):
        pbar.update(1)
        
        # Apply blending
        blocks, palette = blender.process_chunk(blocks, palette, cx, cz)
        chunks_data.append((cx, cz, blocks, palette))
    
    pbar.close()
    print(f"✓ Processed {len(chunks_data)} chunks")
    
    # Write output file
    print(f"\nWriting to {args.output}...")
    
    with open(args.output, 'wb') as f:
        # Write header
        f.write(b'EROS')
        f.write(struct.pack('<I', len(chunks_data)))
        
        for cx, cz, blocks, palette in chunks_data:
            # Encode chunk data
            chunk_dict = {
                'cx': int(cx),
                'cz': int(cz),
                'blocks': blocks.tolist(),
                'palette': palette
            }
            chunk_json = json.dumps(chunk_dict, separators=(',', ':')).encode('utf-8')
            chunk_compressed = zlib.compress(chunk_json, level=6)
            
            # Write chunk
            f.write(struct.pack('<I', len(chunk_compressed)))
            f.write(chunk_compressed)
    
    print("✓ Done!")
    print(f"\nStructural blending complete. Output saved to: {args.output}")


if __name__ == "__main__":
    main()
