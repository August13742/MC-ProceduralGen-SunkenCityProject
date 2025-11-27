import sys
import os
import json
import argparse
from typing import Dict, Any

from gdpc.editor import Editor
from gdpc.block import Block

# Import updated logic
from erosion_logic import erode_blueprint

def load_blueprint(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def safe_fill(editor: Editor, x1, y1, z1, x2, y2, z2, block_id: str):
    """Vanilla-limit safe fill"""
    STEP = 16
    x_min, x_max = min(x1, x2), max(x1, x2)
    y_min, y_max = min(y1, y2), max(y1, y2)
    z_min, z_max = min(z1, z2), max(z1, z2)

    for x in range(x_min, x_max + 1, STEP):
        for z in range(z_min, z_max + 1, STEP):
            cx_end = min(x + STEP - 1, x_max)
            cz_end = min(z + STEP - 1, z_max)
            try:
                editor.runCommand(f"fill {x} {y_min} {z} {cx_end} {y_max} {cz_end} {block_id}")
            except: pass

def place_blueprint_gdpc(editor, origin, bp_data):
    blocks = bp_data['blocks']
    ox, oy, oz = origin
    with editor.pushTransform((ox, oy, oz)):
        for b in blocks:
            props = {k: str(v) for k, v in b.get('props', {}).items()}
            try:
                editor.placeBlock((b['dx'], b['dy'], b['dz']), Block(b['id'], props))
            except: pass

def main():
    parser = argparse.ArgumentParser(description="Clean vs Eroded Comparison")
    parser.add_argument("path", help="Path to single JSON blueprint")
    parser.add_argument("--erosion", type=float, default=0.7, help="Erosion aggression (0.0 - 1.0)")
    parser.add_argument("--seed", type=int, default=123, help="Random seed")
    
    # Save options
    parser.add_argument("--no-save", action="store_true", help="Don't save the JSON file")
    parser.add_argument("--out-dir", default="blueprints_eroded", help="Output directory")
    
    args = parser.parse_args()

    # 1. Load Data
    if not os.path.isfile(args.path):
        print(f"Error: {args.path} is not a file.")
        return
        
    clean_bp = load_blueprint(args.path)
    
    # 2. Process Erosion
    print(f"Applying Erosion (Aggression: {args.erosion}, Seed: {args.seed})...")
    eroded_bp = erode_blueprint(clean_bp, seed=args.seed, aggression=args.erosion, passes=3)
    
    # 3. Save JSON (Optional)
    if not args.no_save:
        os.makedirs(args.out_dir, exist_ok=True)
        filename = os.path.basename(args.path)
        out_path = os.path.join(args.out_dir, filename)
        
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(eroded_bp, f, indent=2)
        print(f"[Saved] Eroded blueprint -> {out_path}")

    # 4. Visualization
    editor = Editor(buffering=True)
    
    # Dimensions
    sx, sy, sz = clean_bp['meta']['size']
    gap = 5
    total_width = (sx * 2) + gap + 10
    total_depth = sz + 10
    
    # Clear Canvas
    print("Clearing canvas...")
    safe_fill(editor, -5, 1, -5, total_width, 60, total_depth, "minecraft:air")
    safe_fill(editor, -5, 0, -5, total_width, 0, total_depth, "minecraft:black_concrete")
    
    # Place Clean
    print(f"Placing CLEAN version at 0, 0...")
    place_blueprint_gdpc(editor, (0, 1, 0), clean_bp)
    editor.placeBlock((0, 1, -2), Block("minecraft:gold_block")) # Marker

    # Place Eroded
    offset_x = sx + gap
    print(f"Placing ERODED version at {offset_x}, 0...")
    place_blueprint_gdpc(editor, (offset_x, 1, 0), eroded_bp)
    editor.placeBlock((offset_x, 1, -2), Block("minecraft:diamond_block")) # Marker

    editor.flushBuffer()
    print("Comparison Ready.")

if __name__ == "__main__":
    main()