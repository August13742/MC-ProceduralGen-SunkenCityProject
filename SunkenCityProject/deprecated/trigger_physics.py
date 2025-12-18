"""
trigger_physics.py

Triggers physics updates in Minecraft world for waterlogged/bubble-wrapped blocks.
This is a post-placement step to fix visual glitches.

Two methods:
1. Force block updates by replacing blocks with themselves
2. Create marker blocks that force neighbor updates

Usage:
    python SunkenCityProject/trigger_physics.py \
        --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" \
        --chunks-file city_eroded.bin \
        --method force-update
"""

import argparse
import amulet
from amulet.api.block import Block
from tqdm import tqdm
import time
import struct
import json
import numpy as np


def read_chunk_positions(bin_file):
    """Extract just chunk coordinates from binary file."""
    chunk_coords = []
    
    with open(bin_file, 'rb') as f:
        magic = f.read(4)
        if magic != b'EROS':
            raise ValueError("Invalid file format")
        
        chunk_count = struct.unpack('<I', f.read(4))[0]
        
        for _ in range(chunk_count):
            # Read chunk size
            chunk_size = struct.unpack('<I', f.read(4))[0]
            chunk_data = f.read(chunk_size)
            
            # Decompress and parse just coordinates
            import zlib
            decompressed = zlib.decompress(chunk_data)
            chunk_dict = json.loads(decompressed.decode('utf-8'))
            
            chunk_coords.append((chunk_dict['cx'], chunk_dict['cz']))
    
    return chunk_coords


def force_block_updates(level, dimension, chunk_coords, y_range):
    """
    Force block updates by setting each block to itself.
    This triggers Minecraft's block update logic.
    """
    print(f"🔄 Forcing block updates for {len(chunk_coords)} chunks...")
    
    water_block = Block("minecraft", "water")
    air_block = Block("minecraft", "air")
    
    blocks_updated = 0
    
    pbar = tqdm(chunk_coords, desc="Updating blocks", unit="chunk")
    for cx, cz in pbar:
        try:
            # Get chunk
            chunk = level.get_chunk(cx, cz, dimension)
            
            # Scan for waterlogged or problematic blocks
            for lx in range(16):
                for lz in range(16):
                    wx = cx * 16 + lx
                    wz = cz * 16 + lz
                    
                    for wy in y_range:
                        try:
                            # Get current block
                            block, _ = level.get_version_block(
                                wx, wy, wz, dimension,
                                ("java", (1, 20, 1))
                            )
                            
                            # Check if it's waterlogged or a special block
                            if block.namespace == "minecraft":
                                # Check for waterlogged property
                                if "waterlogged" in block.properties:
                                    # Force update by setting to air then back
                                    level.set_version_block(
                                        wx, wy, wz, dimension,
                                        ("java", (1, 20, 1)), air_block
                                    )
                                    level.set_version_block(
                                        wx, wy, wz, dimension,
                                        ("java", (1, 20, 1)), block
                                    )
                                    blocks_updated += 1
                                
                                # Special handling for specific blocks
                                elif block.base_name in [
                                    "kelp", "seagrass", "tall_seagrass",
                                    "amethyst_cluster", "amethyst_bud",
                                    "large_amethyst_bud", "medium_amethyst_bud", "small_amethyst_bud"
                                ]:
                                    # These often don't render correctly underwater
                                    level.set_version_block(
                                        wx, wy, wz, dimension,
                                        ("java", (1, 20, 1)), air_block
                                    )
                                    level.set_version_block(
                                        wx, wy, wz, dimension,
                                        ("java", (1, 20, 1)), block
                                    )
                                    blocks_updated += 1
                        except:
                            pass
                
        except Exception as e:
            pass
    
    pbar.close()
    print(f"✓ Updated {blocks_updated:,} blocks across {len(chunk_coords):,} chunks")
    return blocks_updated


def place_temporary_markers(level, dimension, chunk_coords, y_range):
    """
    Place temporary marker blocks that force neighbor updates,
    then remove them. This is a lighter approach.
    """
    print(f"🔄 Using temporary marker method...")
    
    marker_block = Block("minecraft", "structure_void")
    air_block = Block("minecraft", "air")
    
    marker_positions = []
    
    # Phase 1: Place markers at intervals
    print("   Phase 1: Placing markers...")
    for cx, cz in chunk_coords:
        # Place markers in a grid pattern (every 8 blocks)
        for lx in range(0, 16, 8):
            for lz in range(0, 16, 8):
                for wy in range(y_range[0], y_range[1], 8):
                    wx = cx * 16 + lx
                    wz = cz * 16 + lz
                    
                    try:
                        level.set_version_block(
                            wx, wy, wz, dimension,
                            ("java", (1, 20, 1)), marker_block
                        )
                        marker_positions.append((wx, wy, wz))
                    except:
                        pass
    
    print(f"   Placed {len(marker_positions)} markers")
    
    # Save to trigger updates
    print("   Saving...")
    level.save()
    
    # Phase 2: Remove markers
    print("   Phase 2: Removing markers...")
    for wx, wy, wz in marker_positions:
        try:
            level.set_version_block(
                wx, wy, wz, dimension,
                ("java", (1, 20, 1)), air_block
            )
        except:
            pass
    
    print(f"✓ Completed marker-based updates")


def main():
    parser = argparse.ArgumentParser(description="Trigger physics updates for placed blocks")
    parser.add_argument("--world", required=True, help="Path to Minecraft world folder")
    parser.add_argument("--chunks-file", required=True, help="Path to .bin file with chunk coordinates")
    parser.add_argument("--dimension", default="minecraft:overworld", help="Dimension")
    parser.add_argument("--y-start", type=int, default=20, help="Starting Y coordinate")
    parser.add_argument("--y-end", type=int, default=100, help="Ending Y coordinate")
    parser.add_argument("--method", choices=["force-update", "markers"], default="force-update",
                        help="Update method to use")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("PHYSICS UPDATE TRIGGER")
    print("=" * 70)
    print(f"\n🌍 World: {args.world}")
    print(f"📦 Chunks: {args.chunks_file}")
    print(f"📏 Y Range: {args.y_start} to {args.y_end}")
    print(f"🔧 Method: {args.method}\n")
    
    # Read chunk coordinates
    print("📂 Reading chunk positions...")
    chunk_coords = read_chunk_positions(args.chunks_file)
    print(f"   Found {len(chunk_coords):,} chunks")
    
    # Load world
    print(f"\n🌍 Opening world...")
    level = amulet.load_level(args.world)
    print(f"   ✓ Loaded")
    
    # Apply updates
    t_start = time.time()
    y_range = range(args.y_start, args.y_end)
    
    if args.method == "force-update":
        force_block_updates(level, args.dimension, chunk_coords, y_range)
    else:
        place_temporary_markers(level, args.dimension, chunk_coords, y_range)
    
    # Save changes
    print(f"\n💾 Saving world...")
    level.save()
    level.close()
    
    t_end = time.time()
    
    print("\n" + "=" * 70)
    print("UPDATE COMPLETE")
    print("=" * 70)
    print(f"✓ Time taken: {t_end - t_start:.1f}s")
    print(f"✓ Chunks processed: {len(chunk_coords):,}")
    print("=" * 70)
    print("\n⚠️  NOTE: Some visual issues may only fix when chunks are reloaded")
    print("   in-game. Try flying away and returning, or restarting Minecraft.")


if __name__ == "__main__":
    main()
