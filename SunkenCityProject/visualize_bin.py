"""
visualize_bin.py

Visualizes a .bin file by loading it into an Amulet world for inspection.
Creates a temporary world that can be opened in Amulet Map Editor.

python SunkenCityProject/visualize_bin.py --input city_merged.bin
"""

import argparse
import os
import shutil
from pathlib import Path
from tqdm import tqdm
from amulet import load_level
from amulet.api.block import Block
from city_utils import read_bin_generator
import struct


def visualize_bin(input_file, output_world, game_version=("java", (1, 20, 4))):
    """
    Load a .bin file into an Amulet world for visualization.
    
    Args:
        input_file: Path to .bin file
        output_world: Path to output world directory
        game_version: Tuple of (platform, version_tuple)
    """
    
    print(f"Visualizing: {input_file}")
    print(f"Output world: {output_world}")
    print("=" * 70)
    
    # Remove existing world if it exists
    if os.path.exists(output_world):
        print(f"⚠️  Removing existing world: {output_world}")
        shutil.rmtree(output_world)
    
    # Create minimal world structure
    print(f"Creating new world...")
    os.makedirs(output_world, exist_ok=True)
    os.makedirs(os.path.join(output_world, "region"), exist_ok=True)
    os.makedirs(os.path.join(output_world, "data"), exist_ok=True)
    
    # Create a very minimal level.dat using struct
    level_dat_path = os.path.join(output_world, "level.dat")
    import gzip
    
    # Minimal NBT structure for level.dat (just enough for Amulet to load it)
    # This is a hand-crafted minimal NBT that Amulet can parse
    nbt_data = b'\x0a\x00\x00' + \
               b'\x0a\x00\x04Data' + \
               b'\x03\x00\x07version\x00\x00J\xbd' + \
               b'\x03\x00\x0bDataVersion\x00\x00\r\x89' + \
               b'\x08\x00\tLevelName\x00\rVisualization' + \
               b'\x03\x00\x08GameType\x00\x00\x00\x01' + \
               b'\x03\x00\x06SpawnX\x00\x00\x00\x00' + \
               b'\x03\x00\x06SpawnY\x00\x00\x00@' + \
               b'\x03\x00\x06SpawnZ\x00\x00\x00\x00' + \
               b'\x00\x00'
    
    with open(level_dat_path, 'wb') as f:
        f.write(gzip.compress(nbt_data))
    
    # Load the world with Amulet
    level = load_level(output_world)
    
    try:
        # Count chunks first
        print("Counting chunks...")
        chunk_count = sum(1 for _ in read_bin_generator(input_file))
        print(f"✓ Found {chunk_count:,} chunks to load")
        
        # Load chunks with progress bar
        print("\nLoading chunks into world...")
        loaded = 0
        
        with tqdm(total=chunk_count, desc="Loading", unit="chunks") as pbar:
            for cx, cz, blocks, palette in read_bin_generator(input_file):
                W, H, D = blocks.shape
                
                # Place blocks directly
                for x in range(W):
                    for y in range(H):
                        for z in range(D):
                            block_idx = blocks[x, y, z]
                            block_name = palette[block_idx]
                            
                            # Skip air for performance
                            if "air" in block_name:
                                continue
                            
                            # Clean block name
                            block_name_clean = block_name.replace("minecraft:", "")
                            
                            # Create block
                            block = Block("minecraft", block_name_clean)
                            
                            # World coordinates
                            world_x = cx * 16 + x
                            world_y = y - 64  # Convert from array index to world Y
                            world_z = cz * 16 + z
                            
                            # Set block
                            level.set_version_block(world_x, world_y, world_z, "minecraft:overworld", 
                                                   game_version, block)
                
                loaded += 1
                pbar.update(1)
                pbar.set_postfix({"chunks": f"{loaded:,}"})
        
        print(f"\n✓ Loaded {loaded:,} chunks")
        
        # Save world
        print("\nSaving world...")
        level.save()
        level.close()
        
        print(f"\n✅ Success!")
        print(f"\n📂 World saved to: {output_world}")
        print(f"\n💡 To view:")
        print(f"   1. Open Amulet Map Editor")
        print(f"   2. File → Open → Select: {output_world}")
        print(f"   3. Explore your visualization!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        level.close()
        raise


def main():
    parser = argparse.ArgumentParser(description="Visualize .bin file in Amulet")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--output", default="viz_world", help="Output world directory (default: viz_world)")
    parser.add_argument("--version", default="1.20.4", help="Minecraft version (default: 1.20.4)")
    
    args = parser.parse_args()
    
    # Parse version
    version_parts = args.version.split(".")
    version_tuple = tuple(int(p) for p in version_parts)
    
    visualize_bin(args.input, args.output, ("java", version_tuple))


if __name__ == "__main__":
    main()
