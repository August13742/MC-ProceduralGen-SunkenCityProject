"""
generate_sunken_world_infinite.py

REAL-TIME Sunken City Generator.
1. Tracks player movement.
2. Generates city shards in unvisited chunks around the player.
3. Adapts to terrain heightmap on the fly.

Usage:
  python SunkenCityProject/generate_sunken_world_infinite.py --shards shards/WestonSunken --radius 5
"""
import argparse
import json
import struct
import zlib
import numpy as np
import os
import time
import random
import requests
import re
import sys
from opensimplex import OpenSimplex
from gdpc import Editor, Block
from gdpc.vector_tools import ivec2, ivec3, Rect

# Add parent directory to path for normalise_block import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from normalise_block import normalise_block

# --- CONFIG ---
CITY_SCALE = 0.01       # Lower = Larger contiguous city areas
CLUSTER_THRESHOLD = 0.4  # Lower = More land, less ocean gap
FOUNDATION_BLOCK = Block("minecraft:deepslate")
ORIGINAL_STREET_Y = 10 
HISTORY_FILE = "generated_chunks.json"

class ShardLoader:
    def __init__(self, shards_dir):
        print(f"Loading Shard Index from {shards_dir}...")
        with open(os.path.join(shards_dir, "manifest.json"), 'r') as f:
            data = json.load(f)
            self.palette = [self._parse_block(b) for b in data['palette']]
            self.index = {(s['x'], s['z']): s['file'] for s in data['shards']}
        self.shards_dir = shards_dir
        self.cache = {}

    def _parse_block(self, name):
        # Parse the block string format: "minecraft:block[prop1=val1,prop2=val2]" or just "minecraft:block"
        waterlog = "true" if name in ["minecraft:oak_fence", "minecraft:iron_bars", "minecraft:chest", "minecraft:ladder"] else None
        if '[' in name:
            base, props = name.rstrip(']').split('[')
            p_dict = {k: v for k, v in [pair.split('=') for pair in props.split(',')]}
            if waterlog: p_dict["waterlogged"] = waterlog
        else:
            base = name
            p_dict = {"waterlogged": waterlog} if waterlog else {}
        
        # Apply normalization to fix compatibility issues (e.g., minecraft:chain -> proper format)
        normalized_id, normalized_props = normalise_block(base, p_dict)
        
        return Block(normalized_id, normalized_props)

    def get_shard(self, cx, cz):
        if (cx, cz) not in self.index: return None
        if (cx, cz) in self.cache: return self.cache[(cx, cz)]
        
        path = os.path.join(self.shards_dir, self.index[(cx, cz)])
        if not os.path.exists(path): return None
        
        with open(path, 'rb') as f:
            _, _, h, c_len = struct.unpack('<iiiI', f.read(16))
            raw = zlib.decompress(f.read(c_len))
            blocks = np.frombuffer(raw, dtype=np.uint16).reshape((16, h, 16))
            self.cache[(cx, cz)] = blocks
            if len(self.cache) > 200: self.cache.pop(next(iter(self.cache)))
            return blocks

def get_source_coord(wx, wz, noise):
    # Cluster Check
    val = (noise.noise2(wx * CITY_SCALE, wz * CITY_SCALE) + 1) / 2
    if val < CLUSTER_THRESHOLD:
        return None
        
    cell_x, cell_z = int(wx * CITY_SCALE), int(wz * CITY_SCALE)
    random.seed(cell_x * 341 + cell_z * 4521)
    # Map to source coordinates
    sx = wx + random.randint(-500, 500)
    sz = wz + random.randint(-500, 500)
    return sx >> 4, sz >> 4

def get_player_chunk(editor):
    """
    Manual override to get player position.
    Bypasses editor.runCommand to strictly handle HTTP response parsing.
    """
    # Normalize host URL (handle missing http or trailing slashes)
    host = str(editor.host)
    if not host.startswith("http"):
        host = f"http://{host}"
    host = host.rstrip('/')

    # --- ATTEMPT 1: The Clean Way (GET /players) ---
    try:
        response = requests.get(f"{host}/players", timeout=0.5)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                # Support both 'pos' and 'position' keys depending on GDMC version
                p = data[0]
                pos = p.get('pos', p.get('position'))
                if pos:
                    return int(pos[0]) >> 4, int(pos[2]) >> 4
        else:
            # Print failure only once per second to avoid console spam
            if int(time.time()) % 2 == 0:
                print(f"[DEBUG] HTTP /players failed: {response.status_code}")

    except Exception as e:
        pass # Silently fail over to Attempt 2

    # --- ATTEMPT 2: The Brute Force Way (POST /command) ---
    # We manually POST the command and read the text response
    try:
        # Toggle feedback OFF to stop the chat spam, but we only do it once
        # (This is a "blind" command, we don't care about the response)
        requests.post(f"{host}/command", data="gamerule sendCommandFeedback false", timeout=0.1)

        # Execute 'data get' and capture the raw string response
        resp = requests.post(f"{host}/command", data="data get entity @p Pos", timeout=0.5)
        
        if resp.status_code == 200 and resp.text:
            text = resp.text
            # Regex to find: [-123.5d, 64.0d, 456.9d]
            match = re.search(r'\[\s*(-?\d+(?:\.\d+)?)[dD]?\s*,\s*[^,]+\s*,\s*(-?\d+(?:\.\d+)?)[dD]?\s*\]', text)
            if match:
                x, z = float(match.group(1)), float(match.group(2))
                return int(x) >> 4, int(z) >> 4
            else:
                 if int(time.time()) % 2 == 0:
                    print(f"[DEBUG] Command output unreadable: {text[:50]}...")
        else:
             if int(time.time()) % 2 == 0:
                print(f"[DEBUG] Command endpoint failed: {resp.status_code}")

    except Exception as e:
        if int(time.time()) % 2 == 0:
            print(f"[DEBUG] Connection Error: {e}")

    # Critical failure: Sleep to prevent CPU/Network spam
    time.sleep(1.0)
    return None, None


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                return set(json.load(f))
        except: return set()
    return set()

def save_history(history):
    with open(HISTORY_FILE, 'w') as f:
        json.dump(list(history), f)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards", required=True)
    parser.add_argument("--radius", type=int, default=8)
    args = parser.parse_args()

    # Disable buffering so we can see immediate errors
    editor = Editor(buffering=True) 
    loader = ShardLoader(args.shards)
    noise = OpenSimplex(seed=1337)
    
    generated_chunks = load_history()
    print(f"Loaded history: {len(generated_chunks)} chunks.")
    print("Watcher started. Move around in-game.")

    last_cx, last_cz = -99999, -99999

    while True:
        try:
            res = get_player_chunk(editor)
            if res is None or res[0] is None or res[1] is None:
                time.sleep(1)
                continue
            cx, cz = res
        except KeyboardInterrupt:
            break
        
        if cx == last_cx and cz == last_cz:
            time.sleep(0.5)
            continue
            
        last_cx, last_cz = cx, cz
        print(f"Player entered chunk {cx}, {cz}. Scanning...")

        chunks_to_gen = []
        for dx in range(-args.radius, args.radius + 1):
            for dz in range(-args.radius, args.radius + 1):
                tx, tz = cx + dx, cz + dz
                # Square scan is faster/easier for checking
                if f"{tx},{tz}" not in generated_chunks:
                    chunks_to_gen.append((tx, tz))

        if not chunks_to_gen:
            continue

        print(f"Found {len(chunks_to_gen)} new chunks.")

        # Batch Bounds
        min_tx = min(c[0] for c in chunks_to_gen)
        max_tx = max(c[0] for c in chunks_to_gen)
        min_tz = min(c[1] for c in chunks_to_gen)
        max_tz = max(c[1] for c in chunks_to_gen)
        
        box_x = min_tx * 16
        box_z = min_tz * 16
        box_sx = (max_tx - min_tx + 1) * 16
        box_sz = (max_tz - min_tz + 1) * 16
        
        seabed_map = None
        try:
            load_rect = Rect(ivec2(box_x, box_z), ivec2(box_sx, box_sz))
            world_slice = editor.loadWorldSlice(rect=load_rect)
            # Try to get OCEAN_FLOOR heightmap, but fall back gracefully if corrupted
            if 'OCEAN_FLOOR' in world_slice.heightmaps:
                seabed_map = world_slice.heightmaps['OCEAN_FLOOR']
            else:
                print("Warning: OCEAN_FLOOR heightmap not available, using default seabed height")
        except Exception as e:
            print(f"Warning: Could not load world slice heightmap ({e}), using default seabed height")

        count = 0
        for tx, tz in chunks_to_gen:
            wx, wz = tx * 16, tz * 16
            
            source = get_source_coord(wx, wz, noise)
            if not source:
                generated_chunks.add(f"{tx},{tz}")
                continue

            blocks = loader.get_shard(*source)
            if blocks is None:
                generated_chunks.add(f"{tx},{tz}")
                continue

            # Local coordinates relative to slice
            local_x_center = (tx * 16) + 8 - box_x
            local_z_center = (tz * 16) + 8 - box_z
            
            seabed_y = 30
            if seabed_map is not None and (0 <= local_x_center < seabed_map.shape[0] and 
                0 <= local_z_center < seabed_map.shape[1]):
                seabed_y = seabed_map[local_x_center, local_z_center]
            
            H = blocks.shape[1]

            # Find lowest block in entire chunk to anchor it to ground
            lowest_block_y = H
            for x in range(16):
                for z in range(16):
                    for y in range(H):
                        if blocks[x, y, z] != 0:
                            lowest_block_y = min(lowest_block_y, y)
                            break

            # Calculate chunk-wide Y offset so lowest block lands at seabed
            if lowest_block_y < H:
                y_offset = seabed_y - lowest_block_y
            else:
                # No blocks in chunk, use default offset
                y_offset = seabed_y - ORIGINAL_STREET_Y

            for x in range(16):
                for z in range(16):
                    # Place Blocks
                    for y in range(H):
                        idx = blocks[x, y, z]
                        if idx == 0: continue
                        block = loader.palette[idx]
                        # Skip water blocks
                        if block.id == "minecraft:water":
                            continue
                        world_y = y + y_offset
                        if 0 <= world_y < 320:
                            editor.placeBlock(ivec3(wx+x, world_y, wz+z), block)

            generated_chunks.add(f"{tx},{tz}")
            count += 1
            if count % 5 == 0: print(f"Buffered {count} chunks...", end='\r')

        if count > 0:
            print(f"Flushing {count} chunks...")
            editor.flushBuffer()
            save_history(generated_chunks)

if __name__ == "__main__":
    main()