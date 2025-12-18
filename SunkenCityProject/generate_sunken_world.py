"""
generate_sunken_world.py

Real-Time Generator with Terrain Adaptation.
1. Uses WorldSlice to get OCEAN_FLOOR heightmap (Seabed).
2. Snaps City Shards to the seabed Y-level.
3. Performs 'Foundation Extrusion': If a building block hangs in water, 
   generates a Deepslate foundation downwards to the floor.

Usage:
  python SunkenCityProject/generate_sunken_world.py --shards shards/WestonSunken --radius 64
"""

import argparse
import json
import struct
import zlib
import numpy as np
import os
import random
from opensimplex import OpenSimplex
from gdpc import Editor, Block
# from gdpc.vector_tools import Vec3i

# --- CONFIG ---
CITY_SCALE = 0.005
CLUSTER_THRESHOLD = 0.55
FOUNDATION_BLOCK = Block("minecraft:deepslate")
# Original extraction Y-level (roughly where the street was)
# We align this to the Seabed.
ORIGINAL_STREET_Y = 10 

class ShardLoader:
    def __init__(self, shards_dir):
        with open(os.path.join(shards_dir, "manifest.json"), 'r') as f:
            data = json.load(f)
            self.palette = [self._parse_block(b) for b in data['palette']]
            self.index = {(s['x'], s['z']): s['file'] for s in data['shards']}
        self.shards_dir = shards_dir
        self.cache = {}

    def _parse_block(self, name):
        # Auto-Waterlogging
        waterlog = "true" if name in ["minecraft:oak_fence", "minecraft:iron_bars", "minecraft:chest", "minecraft:ladder"] else None
        if '[' in name:
            base, props = name.rstrip(']').split('[')
            p_dict = {k: v for k, v in [pair.split('=') for pair in props.split(',')]}
            if waterlog: p_dict["waterlogged"] = waterlog
            return Block(base, p_dict)
        return Block(name, {"waterlogged": waterlog} if waterlog else {})

    def get_shard(self, cx, cz):
        if (cx, cz) not in self.index: return None
        if (cx, cz) in self.cache: return self.cache[(cx, cz)]
        
        with open(os.path.join(self.shards_dir, self.index[(cx, cz)]), 'rb') as f:
            _, _, h, c_len = struct.unpack('<iiiI', f.read(16))
            raw = zlib.decompress(f.read(c_len))
            blocks = np.frombuffer(raw, dtype=np.uint16).reshape((16, h, 16))
            self.cache[(cx, cz)] = blocks
            return blocks

def get_source_coord(wx, wz, noise):
    if (noise.noise2(wx * CITY_SCALE, wz * CITY_SCALE) + 1) / 2 < CLUSTER_THRESHOLD:
        return None
    
    cell_x, cell_z = int(wx * CITY_SCALE), int(wz * CITY_SCALE)
    random.seed(cell_x * 341 + cell_z * 4521)
    sx = wx + random.randint(-500, 500)
    sz = wz + random.randint(-500, 500)
    return sx >> 4, sz >> 4

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards", required=True)
    parser.add_argument("--radius", type=int, default=64, help="Radius in chunks")
    args = parser.parse_args()

    editor = Editor(buffering=True)
    loader = ShardLoader(args.shards)
    noise = OpenSimplex(seed=random.randint(0, 9999))
    
    # Get Build Area from Player Position
    origin = editor.getBuildArea().begin
    print(f"Scanning terrain around {origin} (Radius: {args.radius} chunks)...")
    
    # Load Heightmap for the whole area
    # Note: We request a box of 256 height to ensure we capture the floor
    # radius * 16 blocks
    rect = (origin.x - args.radius*16, 0, origin.z - args.radius*16, 
            (args.radius*2)*16, 256, (args.radius*2)*16)
    
    # Efficiently load the world slice
    # buildRect is roughly: origin, size
    bx, by, bz = origin.x - args.radius*16, 0, origin.z - args.radius*16
    bsx, bsz = args.radius*32, args.radius*32
    
    print("Downloading World Slice (this may take a moment)...")
    world_slice = editor.loadWorldSlice(box=None) # Loads entire build area defined in GDMC
    # Ideally, user should setbuildarea in game first: /setbuildarea ~-200 ~ ~-200 ~200 ~256 ~200
    
    # Get Seabed Heightmap
    # GDPC keys: 'OCEAN_FLOOR', 'MOTION_BLOCKING'
    seabed_map = world_slice.heightmaps['OCEAN_FLOOR']
    
    # To map global coords to local heightmap coords, we need the slice's offset
    slice_x, _, slice_z = world_slice.box.begin

    print("Generating Sunken City...")
    chunks_placed = 0
    
    # Iterate Chunks
    # We use the slice bounds to determine loop
    min_cx = slice_x >> 4
    min_cz = slice_z >> 4
    max_cx = (slice_x + world_slice.box.size.x) >> 4
    max_cz = (slice_z + world_slice.box.size.z) >> 4

    for cx in range(min_cx, max_cx):
        for cz in range(min_cz, max_cz):
            
            # 1. Project Source
            wx, wz = cx * 16, cz * 16
            source = get_source_coord(wx, wz, noise)
            if not source: continue
            
            blocks = loader.get_shard(*source)
            if blocks is None: continue

            # 2. Determine Seabed Height (Anchor)
            # Sample the center of the chunk in the heightmap
            # Local map coords
            lx, lz = (cx * 16) - slice_x + 8, (cz * 16) - slice_z + 8
            
            # Boundary check
            if 0 <= lx < seabed_map.shape[0] and 0 <= lz < seabed_map.shape[1]:
                seabed_y = seabed_map[lx, lz]
            else:
                seabed_y = 30 # Default fallback
            
            # Alignment: Place shard so ORIGINAL_STREET_Y matches seabed_y
            y_offset = seabed_y - ORIGINAL_STREET_Y
            
            # 3. Place & Adapt
            for x in range(16):
                for z in range(16):
                    # Local Heightmap lookup for this specific column
                    hm_x = (cx * 16) + x - slice_x
                    hm_z = (cz * 16) + z - slice_z
                    
                    try:
                        floor_y = seabed_map[hm_x, hm_z]
                    except:
                        floor_y = seabed_y

                    # Find bottom-most block in this shard column
                    # We iterate the shard to find the structure bottom
                    col_bottom_y = -1
                    for y in range(blocks.shape[1]):
                        if blocks[x, y, z] != 0:
                            # Found first block
                            # Calculate where it will be placed
                            world_y = y + y_offset
                            
                            # TERRAIN ADAPTATION:
                            # If this block is above the floor, extend foundation down
                            if world_y > floor_y:
                                for fill_y in range(floor_y, world_y):
                                    if 0 <= fill_y < 320:
                                        editor.placeBlock((wx+x, fill_y, wz+z), FOUNDATION_BLOCK)
                            
                            # Place the actual block
                            if 0 <= world_y < 320:
                                editor.placeBlock((wx+x, world_y, wz+z), loader.palette[blocks[x, y, z]])
                            
                            # Mark that we have placed the bottom
                            # We continue the loop to place the rest of the column
            
            chunks_placed += 1
            if chunks_placed % 10 == 0: print(f"Placed {chunks_placed} chunks...", end='\r')

    print(f"\nFlushing {chunks_placed} chunks to server...")
    # Buffer flush happens automatically on exit or full buffer
    
if __name__ == "__main__":
    main()