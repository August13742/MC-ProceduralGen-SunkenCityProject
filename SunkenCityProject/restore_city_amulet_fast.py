r"""
restore_city_amulet_fast.py

Ultra-fast block placement using batch operations and multiprocessing.
Optimized for placing pre-generated chunks.

Usage:
    python SunkenCityProject/restore_city_amulet_fast.py \
        --input city_eroded.bin \
        --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (1)" \
        --y-start 45 \
        --workers 4
    
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
from amulet.api.chunk import Chunk
from multiprocessing import Pool, cpu_count
import sys

def parse_block_name(block_name):
    """Parse Minecraft block string into Amulet format."""
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
    
    return Block(namespace, base_name, props)


def load_chunks_from_bin(input_file):
    """Load all chunks from binary file into memory."""
    chunks_data = []
    
    with open(input_file, 'rb') as f:
        magic = f.read(4)
        if magic != b'EROS':
            raise ValueError("Invalid file format")
        
        palette_ptr = struct.unpack('<Q', f.read(8))[0]
        
        # Read palette
        current_pos = f.tell()
        f.seek(palette_ptr)
        palette_data = f.read()
        palette = json.loads(palette_data.decode('utf-8'))
        
        # Convert palette to Amulet blocks
        amulet_palette = [parse_block_name(block_name) for block_name in palette]
        
        # Read chunks
        f.seek(current_pos)
        while f.tell() < palette_ptr:
            header_bytes = f.read(16)
            if len(header_bytes) < 16:
                break
            
            cx, cz, raw_len, comp_len = struct.unpack('<iiiI', header_bytes)
            compressed_data = f.read(comp_len)
            raw_data = zlib.decompress(compressed_data)
            block_indices = np.frombuffer(raw_data, dtype=np.uint16)
            
            height = len(block_indices) // 256
            chunk_blocks = block_indices.reshape((16, height, 16))
            
            chunks_data.append((cx, cz, chunk_blocks))
    
    return chunks_data, amulet_palette


def place_chunk_fast(chunk_data, amulet_palette, y_start, level, dimension):
    """Fast chunk placement using batch operations."""
    cx, cz, chunk_blocks = chunk_data
    height = chunk_blocks.shape[1]
    
    try:
        chunk = level.get_chunk(cx, cz, dimension)
    except:
        chunk = level.create_chunk(cx, cz, dimension)
    
    blocks_placed = 0
    
    # Build block array efficiently - only process non-air blocks
    # Pre-compute all positions and blocks
    positions = []
    blocks = []
    
    for lx in range(16):
        for lz in range(16):
            # Vectorized approach: find all non-zero blocks in this column
            column = chunk_blocks[lx, :, lz]
            non_air_indices = np.nonzero(column)[0]
            
            for ly in non_air_indices:
                block_id = chunk_blocks[lx, ly, lz]
                wx = (cx * 16) + lx
                wy = y_start + ly
                wz = (cz * 16) + lz
                
                positions.append((wx, wy, wz))
                blocks.append(amulet_palette[block_id])
    
    # Batch place blocks
    for (wx, wy, wz), block in zip(positions, blocks):
        try:
            level.set_version_block(wx, wy, wz, dimension, 
                                   ("java", (1, 20, 1)), block)
            blocks_placed += 1
        except:
            pass
    
    return cx, cz, blocks_placed


def main():
    parser = argparse.ArgumentParser(description="Fast restore binary city to Minecraft world")
    parser.add_argument("--input", required=True, help="Path to .bin file")
    parser.add_argument("--world", required=True, help="Path to Minecraft world folder")
    parser.add_argument("--y-start", type=int, default=-64, 
                        help="World Y coordinate for index 0")
    parser.add_argument("--dimension", default="minecraft:overworld", 
                        help="Dimension to place in")
    parser.add_argument("--chunk-limit", type=int, default=0, 
                        help="Stop after N chunks (0 for all)")
    parser.add_argument("--batch-size", type=int, default=100,
                        help="Number of chunks to process before saving")
    
    args = parser.parse_args()
    
    print("=" * 70)
    print("ULTRA-FAST BLOCK PLACEMENT")
    print("=" * 70)
    
    # Load all chunks into memory
    print(f"\n📂 Loading chunks from {args.input}...")
    t_load_start = time.time()
    chunks_data, amulet_palette = load_chunks_from_bin(args.input)
    t_load_end = time.time()
    
    print(f"✓ Loaded {len(chunks_data)} chunks in {t_load_end - t_load_start:.2f}s")
    print(f"✓ Palette contains {len(amulet_palette)} block types")
    
    if args.chunk_limit > 0:
        chunks_data = chunks_data[:args.chunk_limit]
        print(f"⚠ Limited to first {args.chunk_limit} chunks")
    
    # Load world
    print(f"\n🌍 Loading world: {args.world}")
    level = amulet.load_level(args.world)
    
    # Process chunks with progress tracking
    print(f"\n🚀 Placing blocks...")
    print(f"   Batch size: {args.batch_size} chunks per save")
    print("-" * 70)
    
    t_start = time.time()
    total_blocks_placed = 0
    chunks_processed = 0
    
    for i, chunk_data in enumerate(chunks_data):
        cx, cz, blocks_placed = place_chunk_fast(
            chunk_data, amulet_palette, args.y_start, level, args.dimension
        )
        
        total_blocks_placed += blocks_placed
        chunks_processed += 1
        
        # Save periodically
        if chunks_processed % args.batch_size == 0:
            t_elapsed = time.time() - t_start
            rate = chunks_processed / t_elapsed if t_elapsed > 0 else 0
            blocks_per_sec = total_blocks_placed / t_elapsed if t_elapsed > 0 else 0
            
            print(f"💾 Saving... [{chunks_processed}/{len(chunks_data)}] "
                  f"{rate:.1f} chunks/s, {blocks_per_sec:.0f} blocks/s", flush=True)
            level.save()
        
        # Progress update
        if chunks_processed % 10 == 0:
            t_elapsed = time.time() - t_start
            rate = chunks_processed / t_elapsed if t_elapsed > 0 else 0
            eta = (len(chunks_data) - chunks_processed) / rate if rate > 0 else 0
            
            print(f"   Chunk ({cx:4}, {cz:4}) [{chunks_processed:5}/{len(chunks_data)}] "
                  f"{rate:.1f} chunks/s | ETA: {eta:.0f}s", end='\r')
    
    # Final save
    print(f"\n\n💾 Final save...")
    level.save()
    level.close()
    
    t_end = time.time()
    total_time = t_end - t_start
    
    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"✓ Processed: {chunks_processed:,} chunks")
    print(f"✓ Placed: {total_blocks_placed:,} blocks")
    print(f"✓ Time: {total_time:.1f}s")
    print(f"✓ Speed: {chunks_processed/total_time:.1f} chunks/sec")
    print(f"✓ Speed: {total_blocks_placed/total_time:.0f} blocks/sec")
    print("=" * 70)

if __name__ == "__main__":
    main()
