import sys
import os
import json
import argparse
from typing import List, Dict, Any, Tuple

from gdpc.editor import Editor
from gdpc.block import Block
from gdpc.vector_tools import ivec3

# Import our custom logic
from erosion_logic import erode_blueprint

def load_blueprint(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_fill(editor: Editor, x1, y1, z1, x2, y2, z2, block_id: str):
    """
    Splits a large volume into chunks smaller than 32,768 blocks 
    to bypass vanilla Minecraft command limits.
    """
    # 16x16x256 is roughly 65k, which is too big. 
    # 16x16x60 (our height) is ~15k, which is safe.
    STEP_X = 16
    STEP_Z = 16
    
    # Ensure coordinates are ordered min -> max
    x_min, x_max = min(x1, x2), max(x1, x2)
    y_min, y_max = min(y1, y2), max(y1, y2)
    z_min, z_max = min(z1, z2), max(z1, z2)

    total_chunks = ((x_max - x_min) // STEP_X + 1) * ((z_max - z_min) // STEP_Z + 1)
    print(f"Split {block_id} fill into {total_chunks} chunks to fit command limits...")

    for x in range(x_min, x_max + 1, STEP_X):
        for z in range(z_min, z_max + 1, STEP_Z):
            # Calculate chunk boundaries, clamping to the max
            cx_end = min(x + STEP_X - 1, x_max)
            cz_end = min(z + STEP_Z - 1, z_max)
            
            # Run the command for this sub-chunk
            cmd = f"fill {x} {y_min} {z} {cx_end} {y_max} {cz_end} {block_id}"
            try:
                editor.runCommand(cmd)
            except Exception as e:
                print(f"Chunk fill failed at {x},{z}: {e}")

def clear_gallery_area(editor: Editor, size_x=200, size_z=200):
    """Wipes the slate clean safely."""
    print(f"Clearing area {size_x}x{size_z}... (This might take a moment)")
    
    # 1. Fill Air (Safe Chunked)
    # We go up to Y=60 to clear trees/terrain
    safe_fill(editor, 0, 1, 0, size_x, 60, size_z, "minecraft:air")
    
    # 2. Place Floor (Safe Chunked)
    safe_fill(editor, 0, 0, 0, size_x, 0, size_z, "minecraft:black_concrete")
    
    # 3. Place Grid (Loops are fine here as they are linear lines)
    # Sea lanterns every 10 blocks
    for x in range(0, size_x + 1, 10):
        # We use strict bounds to prevent overflow errors
        editor.runCommand(f"fill {x} 0 0 {x} 0 {size_z} minecraft:sea_lantern")
    for z in range(0, size_z + 1, 10):
        editor.runCommand(f"fill 0 0 {z} {size_x} 0 {z} minecraft:sea_lantern")

def place_blueprint_gdpc(editor: Editor, origin: Tuple[int, int, int], bp_data: Dict[str, Any]):
    """Places a single blueprint at origin."""
    blocks = bp_data['blocks']
    ox, oy, oz = origin
    
    # Batch the placement for speed
    with editor.pushTransform((ox, oy, oz)):
        for b in blocks:
            # Simple prop conversion
            props = {k: str(v) for k, v in b.get('props', {}).items()}
            
            try:
                # Direct placement logic
                editor.placeBlock((b['dx'], b['dy'], b['dz']), Block(b['id'], props))
            except Exception as e:
                pass # Ignore occasional invalid block states

def main():
    parser = argparse.ArgumentParser(description="Deterministic Gallery Viewer")
    parser.add_argument("path", help="File or Folder of JSON blueprints")
    parser.add_argument("--erosion", type=float, default=0.0, help="Erosion aggression (0.0 to 1.0). 0 = Clean.")
    parser.add_argument("--seed", type=int, default=999, help="Erosion seed")
    parser.add_argument("--gap", type=int, default=5, help="Gap between buildings")
    args = parser.parse_args()

    editor = Editor(buffering=True)
    
    # 1. Gather Blueprints
    blueprints = []
    if os.path.isfile(args.path):
        blueprints.append(load_blueprint(args.path))
    elif os.path.isdir(args.path):
        for f in sorted(os.listdir(args.path)):
            if f.endswith(".json") and "index" not in f:
                try:
                    blueprints.append(load_blueprint(os.path.join(args.path, f)))
                except Exception as e:
                    print(f"Failed to load {f}: {e}")
    
    if not blueprints:
        print("No blueprints found.")
        return

    # 2. Calculate Grid
    import math
    count = len(blueprints)
    row_target = math.ceil(math.sqrt(count))
    if row_target == 0: row_target = 1
    
    # 3. Clear Area
    est_max_w = 25 
    total_dim = (row_target * est_max_w) + (row_target * args.gap) + 20
    # Ensure divisible by 16 for clean chunks (optional but nice)
    total_dim = ((total_dim // 16) + 1) * 16 
    
    clear_gallery_area(editor, size_x=total_dim, size_z=total_dim)

    # 4. Place Loop
    cursor_x = 5
    cursor_z = 5
    max_row_height = 0
    items_in_row = 0
    
    print(f"Placing {count} blueprints...")
    
    for bp in blueprints:
        meta = bp['meta']
        sx, sy, sz = meta['size']
        name = meta.get('name', 'Unknown')
        
        # Apply Erosion
        final_bp = bp
        if args.erosion > 0:
            final_bp = erode_blueprint(bp, seed=args.seed, aggression=args.erosion)
            
        # Place
        place_blueprint_gdpc(editor, (cursor_x, 1, cursor_z), final_bp)
        
        # Draw Label (Gold marker)
        editor.placeBlock((cursor_x, 1, cursor_z - 2), Block("minecraft:gold_block"))
        
        print(f"Placed {name} at {cursor_x}, {cursor_z}")

        # Update cursors
        cursor_x += sx + args.gap
        max_row_height = max(max_row_height, sz)
        items_in_row += 1
        
        if items_in_row >= row_target:
            cursor_x = 5
            cursor_z += max_row_height + args.gap
            max_row_height = 0
            items_in_row = 0

    editor.flushBuffer()
    print("Gallery Generation Complete.")

if __name__ == "__main__":
    main()