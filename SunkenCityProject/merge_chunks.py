"""
merge_chunks.py

Merges city chunks with terrain chunks, creating a blended result.
This allows working entirely with .bin files without touching the actual world.

The merge happens in layers:
1. Load terrain chunks from target world
2. Load city chunks
3. Blend them together based on strategy
4. Output merged result

Usage:
    python SunkenCityProject/merge_chunks.py \
        --city city_blended.bin \
        --terrain terrain_extracted.bin \
        --output city_merged.bin \
        --city-y 20 \
        --strategy underwater
"""

import argparse
import numpy as np
from numba import jit
from tqdm import tqdm
from city_utils import read_bin_generator
import struct
import zlib
import json


@jit(nopython=True)
def merge_blocks_fast(terrain_blocks, terrain_remap, city_blocks, city_remap, y_offset, air_idx):
    """
    Fast block merging using Numba.
    
    Args:
        terrain_blocks: Terrain chunk blocks
        terrain_remap: Mapping from terrain palette to unified palette
        city_blocks: City chunk blocks  
        city_remap: Mapping from city palette to unified palette
        y_offset: Y offset for city placement
        air_idx: Index of air block in unified palette
    """
    H = max(terrain_blocks.shape[1], city_blocks.shape[1] + y_offset)
    result = np.zeros((16, H, 16), dtype=np.uint16)
    
    # Copy terrain blocks
    for x in range(16):
        for y in range(min(terrain_blocks.shape[1], H)):
            for z in range(16):
                result[x, y, z] = terrain_remap[terrain_blocks[x, y, z]]
    
    # Overlay city blocks
    for x in range(16):
        for y in range(city_blocks.shape[1]):
            world_y = y + y_offset
            if world_y >= H:
                continue
            for z in range(16):
                city_idx = city_blocks[x, y, z]
                if city_idx != air_idx:  # Don't overlay air
                    result[x, world_y, z] = city_remap[city_idx]
    
    return result


class ChunkMerger:
    def __init__(self, city_y_start, strategy="underwater"):
        """
        Args:
            city_y_start: Y level where city was designed (e.g., 20)
            strategy: Merging strategy - "underwater", "replace", "overlay"
        """
        self.city_y_start = city_y_start
        self.strategy = strategy
        
        # Build global palette incrementally
        self.global_palette = []
        self.palette_lookup = {}  # block_name -> index
        
    def add_to_palette(self, block_name):
        """Add block to global palette if not already present."""
        if block_name not in self.palette_lookup:
            idx = len(self.global_palette)
            self.global_palette.append(block_name)
            self.palette_lookup[block_name] = idx
        return self.palette_lookup[block_name]
    
    def build_remap(self, local_palette):
        """Build remapping array from local to global palette."""
        remap = np.zeros(len(local_palette), dtype=np.uint16)
        for local_idx, block_name in enumerate(local_palette):
            remap[local_idx] = self.add_to_palette(block_name)
        return remap
        
    def merge_underwater(self, terrain_blocks, terrain_palette, city_blocks, city_palette, cx, cz):
        """
        Underwater strategy - optimized version.
        """
        # Build remapping arrays
        terrain_remap = self.build_remap(terrain_palette)
        city_remap = self.build_remap(city_palette)
        
        # Get air index in city's local palette
        city_air_idx = 0
        for i, name in enumerate(city_palette):
            if name == "minecraft:air":
                city_air_idx = i
                break
        
        # Y offset for city placement
        y_offset = self.city_y_start + 64  # +64 because world starts at -64
        
        # Fast merge using Numba
        result = merge_blocks_fast(
            terrain_blocks, terrain_remap,
            city_blocks, city_remap,
            y_offset, city_air_idx
        )
        
        return result, self.global_palette
    
    def merge_replace(self, terrain_blocks, terrain_palette, city_blocks, city_palette, cx, cz):
        """Replace strategy - same as underwater for now."""
        return self.merge_underwater(terrain_blocks, terrain_palette, city_blocks, city_palette, cx, cz)
    
    def merge(self, terrain_blocks, terrain_palette, city_blocks, city_palette, cx, cz):
        """Merge based on selected strategy."""
        if self.strategy == "underwater":
            return self.merge_underwater(terrain_blocks, terrain_palette, city_blocks, city_palette, cx, cz)
        elif self.strategy == "replace":
            return self.merge_replace(terrain_blocks, terrain_palette, city_blocks, city_palette, cx, cz)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")


def main():
    parser = argparse.ArgumentParser(description="Merge city and terrain chunks")
    parser.add_argument("--city", required=True, help="City .bin file")
    parser.add_argument("--terrain", required=True, help="Terrain .bin file (extracted from target world)")
    parser.add_argument("--output", required=True, help="Output merged .bin file")
    parser.add_argument("--city-y", type=int, default=20, 
                        help="Y level where city starts (default: 20)")
    parser.add_argument("--strategy", choices=["underwater", "replace"], default="underwater",
                        help="Merge strategy")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("CHUNK MERGER")
    print("=" * 70)
    print(f"\n🏛️  City: {args.city}")
    print(f"🌍 Terrain: {args.terrain}")
    print(f"📦 Output: {args.output}")
    print(f"📏 City Y: {args.city_y}")
    print(f"🔧 Strategy: {args.strategy}\n")
    
    merger = ChunkMerger(city_y_start=args.city_y, strategy=args.strategy)
    
    # Load terrain chunks into dict
    terrain_dict = {}
    
    pbar_terrain = tqdm(desc="Loading terrain", unit="chunk")
    for cx, cz, blocks, palette in read_bin_generator(args.terrain):
        terrain_dict[(cx, cz)] = (blocks, palette)
        pbar_terrain.update(1)
    
    pbar_terrain.close()
    print(f"✓ Loaded {len(terrain_dict):,} terrain chunks")
    
    # Process city chunks and merge
    merged_chunks = []
    merged_count = 0
    
    pbar_merge = tqdm(desc="Merging chunks", unit="chunk")
    for cx, cz, city_blocks, city_palette in read_bin_generator(args.city):
        pbar_merge.update(1)
        
        # Get corresponding terrain chunk
        if (cx, cz) in terrain_dict:
            terrain_blocks, terrain_palette = terrain_dict[(cx, cz)]
            
            # Merge (returns blocks already using global palette)
            merged_blocks, _ = merger.merge(
                terrain_blocks, terrain_palette,
                city_blocks, city_palette,
                cx, cz
            )
            
            merged_chunks.append((cx, cz, merged_blocks))
            merged_count += 1
        else:
            # No terrain, just use city
            tqdm.write(f"⚠️  Warning: No terrain chunk at ({cx}, {cz}), using city only")
            # Need to remap city to global palette
            city_remap = merger.build_remap(city_palette)
            remapped_city = city_remap[city_blocks]
            merged_chunks.append((cx, cz, remapped_city))
    
    pbar_merge.close()
    print(f"✓ Merged {merged_count:,} chunks")
    
    # Write output using standard format (blocks already use global palette)
    print(f"\nWriting to {args.output}...")
    
    from city_utils import write_bin
    
    def chunk_gen():
        for cx, cz, blocks in merged_chunks:
            yield cx, cz, blocks
    
    write_bin(args.output, chunk_gen(), merger.global_palette)
    
    print("\n" + "=" * 70)
    print("MERGE COMPLETE")
    print("=" * 70)
    print(f"✓ City chunks: {len(merged_chunks):,}")
    print(f"✓ Merged chunks: {merged_count:,}")
    print(f"✓ Output: {args.output}")
    print("\n💡 Next: Run blend_underwater.py for ground connection & vegetation")


if __name__ == "__main__":
    main()
