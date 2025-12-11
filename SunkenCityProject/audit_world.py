# audit_bin.py
import json
import argparse
from city_utils import read_bin_generator

# Heuristics to auto-sort unknown blocks
KEYWORDS = {
    "organic": ["leave", "grass", "log", "wood", "plank", "wool", "carpet", "bed", "book"],
    "fragile": ["glass", "pane", "ice", "glowstone", "lamp"],
    "metal": ["iron", "gold", "copper", "chain", "anvil", "bars"],
    "stone": ["stone", "brick", "cobble", "andesite", "diorite", "granite", "deepslate", "mud"],
    "fluid": ["water", "lava"]
}

def guess_category(block_id):
    lower = block_id.lower()
    for cat, words in KEYWORDS.items():
        for w in words:
            if w in lower:
                return cat
    return "uncategorized" # The catch-all for gilded_blackstone, etc.

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="city_original.bin")
    parser.add_argument("--out", default="erosion_config_complete.json")
    args = parser.parse_args()

    # 1. Collect ALL unique blocks from the extracted city
    print(f"Scanning {args.input}...")
    unique_blocks = set()
    
    # We only need to read the palette from the first chunk yielded, 
    # but since palettes can theoretically differ per chunk in some formats (though city_utils unifies them ideally),
    # let's be safe and scan the generator.
    # Actually, city_utils.read_bin_generator yields the *same* palette object every time if the file has one global palette.
    # Let's peek at the file structure or just run the generator once.
    
    gen = read_bin_generator(args.input)
    try:
        _, _, _, palette = next(gen)
        unique_blocks = set(palette)
        print(f"Found global palette with {len(unique_blocks)} unique blocks.")
    except StopIteration:
        print("Error: Empty file.")
        return

    # 2. Build the Config Structure
    config = {
        "global_settings": {"erosion_rate": 0.3, "passes": 3, "seed": 1337},
        "preserve": ["minecraft:air", "minecraft:bedrock", "minecraft:water", "minecraft:barrier"],
        "decay_rules": {
            "organic": {"chance": 0.8, "transitions": [["minecraft:air", 1.0]]},
            "fragile": {"chance": 0.9, "transitions": [["minecraft:air", 1.0]]},
            "metal":   {"chance": 0.2, "transitions": [["minecraft:oxidized_copper", 0.8], ["minecraft:air", 0.2]]},
            "stone":   {"chance": 0.4, "transitions": [["minecraft:cobblestone", 0.5], ["minecraft:mossy_cobblestone", 0.3], ["minecraft:gravel", 0.2]]},
            "fluid":   {"chance": 0.0, "transitions": []},
            "uncategorized": {"chance": 0.5, "transitions": [["minecraft:air", 0.8], ["minecraft:cobblestone", 0.2]]}
        },
        "block_mapping": {}
    }

    # 3. Map every block
    count_uncat = 0
    for block in sorted(list(unique_blocks)):
        if block in config["preserve"]:
            continue
            
        cat = guess_category(block)
        config["block_mapping"][block] = cat
        
        if cat == "uncategorized":
            count_uncat += 1
            print(f"  [?] Uncategorized: {block}")

    print(f"\nAudit Complete.")
    print(f"Mapped {len(config['block_mapping'])} blocks.")
    print(f"WARNING: {count_uncat} blocks are 'uncategorized'. Open the JSON and fix them!")
    
    with open(args.out, 'w') as f:
        json.dump(config, f, indent=4)
    print(f"Saved to {args.out}")

if __name__ == "__main__":
    main()