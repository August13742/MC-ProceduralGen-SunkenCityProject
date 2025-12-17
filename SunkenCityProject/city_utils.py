import struct
import json
import zlib
import numpy as np

# Format: [MAGIC (4)][PALETTE_PTR (8)][CHUNKS...][PALETTE (N)]
# Chunk: [CX (4)][CZ (4)][RAW_SIZE (4)][COMP_SIZE (4)][DATA (N)]

def write_bin(filename, chunk_iterator, palette):
    """
    Writes compressed chunks to disk.
    chunk_iterator: yields (cx, cz, numpy_array_uint16)
    """
    with open(filename, 'wb') as f:
        f.write(b'EROS')
        f.write(struct.pack('<Q', 0)) # Palette ptr placeholder
        
        count = 0
        for cx, cz, blocks in chunk_iterator:
            raw = blocks.astype(np.uint16).tobytes()
            comp = zlib.compress(raw)
            # Write Chunk Header
            f.write(struct.pack('<iiiI', cx, cz, len(raw), len(comp)))
            f.write(comp)
            count += 1
            
        # Write Palette
        ptr = f.tell()
        f.write(json.dumps(palette).encode('utf-8'))
        
        # Update Pointer
        f.seek(4)
        f.write(struct.pack('<Q', ptr))
        print(f"Saved {filename}: {count} chunks, {len(palette)} block types.")

def read_bin_generator(filename):
    """
    Yields (cx, cz, blocks_3d_numpy, palette_list)
    """
    with open(filename, 'rb') as f:
        if f.read(4) != b'EROS': raise ValueError("Invalid magic")
        ptr = struct.unpack('<Q', f.read(8))[0]
        
        # Read Palette first
        cur = f.tell()
        f.seek(ptr)
        palette = json.loads(f.read().decode('utf-8'))
        f.seek(cur)
        
        while f.tell() < ptr:
            head = f.read(16)
            if len(head) < 16: break
            cx, cz, r_len, c_len = struct.unpack('<iiiI', head)
            
            raw = zlib.decompress(f.read(c_len))
            arr = np.frombuffer(raw, dtype=np.uint16)
            
            # Assume 16x16 footprint, calculate height
            height = len(arr) // 256
            yield cx, cz, arr.reshape((16, height, 16)), palette


def read_bin_palette(filename):
    """Return the stored palette for a compressed .bin dump."""
    with open(filename, 'rb') as f:
        if f.read(4) != b'EROS':
            raise ValueError("Invalid magic while reading palette")
        ptr = struct.unpack('<Q', f.read(8))[0]
        f.seek(ptr)
        return json.loads(f.read().decode('utf-8'))