r"""
restore_city_amulet_ultra.py

ULTRA-FAST block placement using direct chunk manipulation.
Bypasses individual block placement for maximum speed.

This version directly manipulates Amulet's internal chunk format,
which is 10-100x faster than placing blocks individually.

Usage:
    python SunkenCityProject/restore_city_amulet_ultra.py \
        --input city_eroded.bin \
        --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (1)" \
        --y-start 45

python SunkenCityProject/restore_city_amulet_ultra.py --input city_eroded.bin --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" --y-start 20 --batch-size 100

python SunkenCityProject/restore_city_amulet_ultra.py --input city_merged.bin --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test_Visualiser" --batch-size 100

Note: World MUST be closed before running this!

"""

import argparse
import struct
import json
import zlib
import numpy as np
import time
from tqdm import tqdm
import amulet
from amulet.api.block import Block

def parse_block_name(block_name):
    """Parse Minecraft block string into Amulet format."""
    if block_name.startswith("universal_minecraft:"):
        block_name = block_name.replace("universal_minecraft:", "minecraft:")
    elif block_name.startswith("universal_"):
        block_name = block_name.replace("universal_", "")
    
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
    
    if ':' in block_id:
        namespace, base_name = block_id.split(':', 1)
    else:
        namespace = "minecraft"
        base_name = block_id
    
    return Block(namespace, base_name, props)


class ChunkBatcher:
    def __init__(self, level, dimension, y_start, batch_size=256):
        self.level = level
        self.dimension = dimension
        self.y_start = y_start
        self.batch_size = batch_size
        self.pending_chunks = []
        self.total_saved = 0
        
    def add_chunk(self, cx, cz, chunk_blocks, amulet_palette):
        self.pending_chunks.append((cx, cz, chunk_blocks, amulet_palette))
        if len(self.pending_chunks) >= self.batch_size:
            self.flush()
    
    def flush(self):
        if not self.pending_chunks:
            return 0
        
        blocks_placed = 0
        chunks_to_unload = []
        
        # 1. Place blocks in memory
        for cx, cz, chunk_blocks, amulet_palette in self.pending_chunks:
            blocks = self._place_chunk_direct(cx, cz, chunk_blocks, amulet_palette)
            blocks_placed += blocks
            chunks_to_unload.append((cx, cz))
        
        # 2. Save to disk
        self.level.save()
        
        # 3. CRITICAL: Manually unload from internal RAM cache
        # Amulet caches everything in a dictionary called `_chunks`.
        # We must delete entries here or RAM usage will never go down.
        for cx, cz in chunks_to_unload:
            key = (cx, cz, self.dimension)
            if hasattr(self.level, "_chunks") and key in self.level._chunks:
                del self.level._chunks[key]
        
        self.total_saved += len(self.pending_chunks)
        self.pending_chunks = []
        
        return blocks_placed
    
    def _place_chunk_direct(self, cx, cz, chunk_blocks, amulet_palette):
        height = chunk_blocks.shape[1]
        
        # OPTIMIZATION: Use NumPy to find ALL non-air blocks at once
        # This is O(1) vs O(n) for the old triple-nested loop
        non_air_mask = chunk_blocks != 0
        non_air_coords = np.argwhere(non_air_mask)  # Returns (N, 3) array of [lx, ly, lz]
        
        if len(non_air_coords) == 0:
            return 0  # Empty chunk, nothing to do
        
        try:
            chunk = self.level.get_chunk(cx, cz, self.dimension)
        except:
            chunk = self.level.create_chunk(cx, cz, self.dimension)
        
        # Build index map only for blocks we actually need
        unique_indices = np.unique(chunk_blocks[non_air_mask])
        index_map = {}
        for our_idx in unique_indices:
            if our_idx == 0: continue
            chunk_idx = chunk.block_palette.get_add_block(amulet_palette[our_idx])
            index_map[our_idx] = chunk_idx
        
        # Place only non-air blocks (vectorized coordinate access)
        blocks_placed = 0
        for lx, ly, lz in non_air_coords:
            our_idx = chunk_blocks[lx, ly, lz]
            wy = self.y_start + ly
            if wy < -64 or wy >= 320: continue
            
            chunk.blocks[lx, wy, lz] = index_map[our_idx]
            blocks_placed += 1
        
        chunk.changed = True
        return blocks_placed


def load_chunks_from_bin(input_file):
    chunks_data = []
    with open(input_file, 'rb') as f:
        magic = f.read(4)
        if magic != b'EROS': raise ValueError("Invalid file format")
        palette_ptr = struct.unpack('<Q', f.read(8))[0]
        
        current_pos = f.tell()
        f.seek(palette_ptr)
        palette = json.loads(f.read().decode('utf-8'))
        amulet_palette = [parse_block_name(b) for b in palette]
        
        f.seek(current_pos)
        pbar = tqdm(desc="Loading chunks", unit="chunk")
        skipped_empty = 0
        while f.tell() < palette_ptr:
            header = f.read(16)
            if len(header) < 16: break
            cx, cz, _, comp_len = struct.unpack('<iiiI', header)
            raw_data = zlib.decompress(f.read(comp_len))
            indices = np.frombuffer(raw_data, dtype=np.uint16)
            
            # OPTIMIZATION: Skip chunks that are 100% air
            if np.all(indices == 0):
                skipped_empty += 1
                pbar.update(1)
                continue
                
            height = len(indices) // 256
            chunks_data.append((cx, cz, indices.reshape((16, height, 16))))
            pbar.update(1)
        pbar.close()
        
        if skipped_empty > 0:
            print(f"✓ Skipped {skipped_empty:,} empty chunks (100% air)")
    return chunks_data, amulet_palette

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--world", required=True)
    parser.add_argument("--y-start", type=int, default=-64)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--chunk-limit", type=int, default=0, help="Stop after N chunks (0 = all)")
    parser.add_argument("--save-at-end", action="store_true", help="Only save once at the end (faster but risky)")
    args = parser.parse_args()
    
    print("Loading Data...")
    chunks_data, amulet_palette = load_chunks_from_bin(args.input)
    
    # Apply chunk limit
    if args.chunk_limit > 0:
        print(f"Limiting to first {args.chunk_limit:,} chunks.")
        chunks_data = chunks_data[:args.chunk_limit]
    
    print(f"Opening World: {args.world}")
    try:
        level = amulet.load_level(args.world)
    except Exception as e:
        print(f"Error opening world: {e}")
        return

    print("Restoring...")
    # If save-at-end, set batch size to total chunks to force single save
    batch_size = len(chunks_data) + 1 if args.save_at_end else args.batch_size
    batcher = ChunkBatcher(level, "minecraft:overworld", args.y_start, batch_size)
    
    pbar = tqdm(chunks_data, unit="chunk")
    for cx, cz, chunk_blocks in pbar:
        batcher.add_chunk(cx, cz, chunk_blocks, amulet_palette)
        if batcher.total_saved % args.batch_size == 0:
            pbar.set_postfix({"saved": batcher.total_saved})
            
    batcher.flush()
    level.close()
    print("\nDone!")

if __name__ == "__main__":
    main()