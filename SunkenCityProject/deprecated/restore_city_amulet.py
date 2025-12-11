r"""
restore_city_amulet.py

Restore a binary city file directly to a Minecraft world using Amulet.
MUCH faster than GDPC (direct world file access instead of HTTP).

Usage:
    python SunkenCityProject/restore_city_amulet.py --input city_eroded.bin --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (1)" --y-start 45
    
Note: World MUST be closed before running this!
"""

import argparse
import struct
import json
import zlib
import numpy as np
import time
import amulet
from amulet.api.block import Block

def main():
    parser = argparse.ArgumentParser(description="Restore binary city to Minecraft world via Amulet")
    parser.add_argument("--input", required=True, help="Path to .bin file")
    parser.add_argument("--world", required=True, help="Path to Minecraft world folder")
    parser.add_argument("--y-start", type=int, default=-64, 
                        help="World Y coordinate for index 0 (usually -64 for 1.18+)")
    parser.add_argument("--dimension", default="minecraft:overworld", 
                        help="Dimension to place in (minecraft:overworld, minecraft:the_nether, etc.)")
    parser.add_argument("--chunk-limit", type=int, default=0, 
                        help="Stop after N chunks (0 for all)")
    
    args = parser.parse_args()
    
    print(f"Loading world: {args.world}")
    level = amulet.load_level(args.world)
    
    print(f"Opening {args.input}...")
    
    t_start = time.time()
    total_blocks_placed = 0
    chunks_processed = 0
    
    with open(args.input, 'rb') as f:
        # Read Header
        magic = f.read(4)
        if magic != b'EROS':
            print("Error: Invalid file format")
            return
        
        # Read Palette Pointer
        palette_ptr = struct.unpack('<Q', f.read(8))[0]
        
        # Read Palette
        current_pos = f.tell()
        f.seek(palette_ptr)
        palette_data = f.read()
        palette = json.loads(palette_data.decode('utf-8'))
        print(f"Loaded palette with {len(palette)} block types.")
        
        # Convert palette to Amulet Block objects
        amulet_palette = []
        for block_name in palette:
            # Parse block ID and properties
            if '[' in block_name:
                block_id = block_name.split('[')[0]
                props_str = block_name.split('[', 1)[1].rstrip(']')
                props = {}
                for pair in props_str.split(','):
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        props[k.strip()] = amulet.StringTag(v.strip())
            else:
                block_id = block_name
                props = {}
            
            # Parse namespace and base name
            if ':' in block_id:
                namespace, base_name = block_id.split(':', 1)
            else:
                namespace = "minecraft"
                base_name = block_id
            
            amulet_palette.append(Block(namespace, base_name, props))
        
        # Jump back to chunks
        f.seek(current_pos)
        
        # Process chunks
        while f.tell() < palette_ptr:
            if args.chunk_limit > 0 and chunks_processed >= args.chunk_limit:
                print(f"\nReached chunk limit ({args.chunk_limit})")
                break
            
            # Read chunk header
            header_bytes = f.read(16)
            if len(header_bytes) < 16:
                break
            
            cx, cz, raw_len, comp_len = struct.unpack('<iiiI', header_bytes)
            
            # Read and decompress data
            compressed_data = f.read(comp_len)
            raw_data = zlib.decompress(compressed_data)
            block_indices = np.frombuffer(raw_data, dtype=np.uint16)
            
            # Reshape to (16, Height, 16)
            height = len(block_indices) // 256
            chunk_blocks = block_indices.reshape((16, height, 16))
            
            # Get or create chunk
            try:
                chunk = level.get_chunk(cx, cz, args.dimension)
            except:
                # Chunk doesn't exist, create it
                print(f"\nWarning: Chunk ({cx}, {cz}) doesn't exist, creating new chunk")
                chunk = level.create_chunk(cx, cz, args.dimension)
            
            # Build the chunk's block array
            # We need to convert our data to Amulet's format
            blocks_placed = 0
            
            for lx in range(16):
                for lz in range(16):
                    for ly in range(height):
                        block_id = chunk_blocks[lx, ly, lz]
                        
                        # Skip air (ID 0)
                        if block_id == 0:
                            continue
                        
                        # Get world coordinates
                        wx = (cx * 16) + lx
                        wy = args.y_start + ly
                        wz = (cz * 16) + lz
                        
                        # Get the Amulet block
                        block = amulet_palette[block_id]
                        
                        # Place block
                        try:
                            level.set_version_block(wx, wy, wz, args.dimension, 
                                                   ("java", (1, 20, 1)), block)
                            blocks_placed += 1
                        except Exception as e:
                            # Skip blocks that can't be placed
                            pass
            
            total_blocks_placed += blocks_placed
            chunks_processed += 1
            
            # Save every 10 chunks to avoid memory issues
            if chunks_processed % 10 == 0:
                print(f"\nSaving progress... ({chunks_processed} chunks)", end='')
                level.save()
                print(" Done!")
            
            print(f"Chunk ({cx:4}, {cz:4}) - {blocks_placed:5} blocks | Total: {chunks_processed} chunks", end='\r')
    
    # Final save
    print(f"\n\nSaving world...")
    level.save()
    level.close()
    
    t_end = time.time()
    print(f"Done! Processed {chunks_processed} chunks.")
    print(f"Placed {total_blocks_placed} blocks in {t_end - t_start:.1f} seconds.")
    print(f"Average: {total_blocks_placed / (t_end - t_start):.0f} blocks/sec")

if __name__ == "__main__":
    main()
