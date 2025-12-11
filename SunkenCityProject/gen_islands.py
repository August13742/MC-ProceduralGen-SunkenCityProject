import argparse
import json
import random
import math
from gdpc import Editor, Block
from blueprint_db import load_index, iter_blueprints, place_blueprint

PILLAR_MATS = ["minecraft:oxidized_copper", "minecraft:warped_hyphae", "minecraft:prismarine"]
PLATFORM_MATS = ["minecraft:spruce_planks", "minecraft:dark_oak_planks"]

def build_organic_pillar(editor, x, y_start, y_end, z):
    """Wobbly Sine-wave pillar representing rust/coral growth."""
    height = y_end - y_start
    phase = random.random() * 10
    
    for y in range(height):
        wy = y_start + y
        # Wobble
        off_x = math.sin((y / 8) + phase) * 1.5
        off_z = math.cos((y / 8) + phase) * 1.5
        
        # Thickness varies
        thick = 2 if y < height - 5 else 4
        
        cx, cz = int(x + off_x), int(z + off_z)
        
        for dx in range(-thick//2, thick//2 + 1):
            for dz in range(-thick//2, thick//2 + 1):
                editor.placeBlock((cx+dx, wy, cz+dz), Block(random.choice(PILLAR_MATS)))

def build_platform(editor, x, y, z):
    """Irregular raft shape."""
    radius = random.randint(7, 12)
    for dx in range(-radius, radius+1):
        for dz in range(-radius, radius+1):
            dist = math.sqrt(dx*dx + dz*dz)
            noise = random.uniform(-1, 1)
            if dist < (radius + noise):
                editor.placeBlock((x+dx, y, z+dz), Block(random.choice(PLATFORM_MATS)))
    return radius

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--peaks", required=True, help="peaks.json from eroder")
    parser.add_argument("--blueprints", required=True, help="Folder of scrap blueprints")
    args = parser.parse_args()
    
    editor = Editor(buffering=True)
    
    # 1. Load Data
    with open(args.peaks) as f:
        peaks = json.load(f)
    
    bps = list(iter_blueprints(args.blueprints))
    if not bps:
        print("No blueprints found!")
        return

    print(f"Loaded {len(peaks)} peaks. Filtering and building...")

    # 2. Filter Peaks (Distance check)
    islands = []
    random.shuffle(peaks)
    
    for px, py, pz in peaks:
        # Don't build too close to existing islands
        if any(math.dist((px,pz), (ix,iz)) < 30 for ix, iy, iz, r in islands):
            continue
            
        # 3. Build Foundation
        sea_level = 63
        build_organic_pillar(editor, px, py, sea_level, pz)
        radius = build_platform(editor, px, sea_level, pz)
        
        islands.append((px, sea_level, pz, radius))
        
        # 4. Place Building
        # Pick blueprint fitting radius
        valid_bps = [b for b in bps if max(b[1]['size'][0], b[1]['size'][2]) < (radius*1.8)]
        if valid_bps:
            bp_id, meta, blocks = random.choice(valid_bps)
            # Center on island
            ox = px - meta['size'][0]//2
            oz = pz - meta['size'][2]//2
            place_blueprint(editor, (ox, sea_level + 1, oz), blocks)
            print(f"Built island at {px},{pz} with {bp_id}")

    # 5. Bridges (Simple Nearest Neighbor)
    # (Bridge logic omitted for brevity, use previous code)

    editor.flushBuffer()
    print("Done.")

if __name__ == "__main__":
    main()