"""
Expands generic block names in erosion_config.json to actual Minecraft IDs.

This script scans the erosion config and replaces placeholder names like:
- minecraft:planks -> minecraft:oak_planks, minecraft:spruce_planks, etc.
- minecraft:concrete -> minecraft:white_concrete, minecraft:red_concrete, etc.

Usage:
    python expand_erosion_config.py --input erosion_config.json --output erosion_config_fixed.json
"""

import argparse
import json

# Minecraft color variants (16 colors)
COLORS = [
    "white", "orange", "magenta", "light_blue", "yellow", "lime",
    "pink", "gray", "light_gray", "cyan", "purple", "blue",
    "brown", "green", "red", "black"
]

# Wood types
WOOD_TYPES = [
    "oak", "spruce", "birch", "jungle", "acacia", "dark_oak",
    "mangrove", "cherry", "bamboo", "crimson", "warped"
]

# Stone types
STONE_TYPES = [
    "stone", "granite", "diorite", "andesite", "cobblestone",
    "mossy_cobblestone", "stone_brick", "mossy_stone_brick",
    "deepslate", "cobbled_deepslate", "polished_deepslate",
    "blackstone", "polished_blackstone", "end_stone_brick",
    "sandstone", "red_sandstone", "smooth_sandstone",
    "smooth_red_sandstone", "brick", "nether_brick",
    "red_nether_brick", "prismarine"
]

# Expansion rules: generic name -> list of actual IDs
EXPANSIONS = {
    # Concrete
    "minecraft:concrete": [f"minecraft:{c}_concrete" for c in COLORS],
    "minecraft:concrete_powder": [f"minecraft:{c}_concrete_powder" for c in COLORS],
    
    # Terracotta
    "minecraft:terracotta": ["minecraft:terracotta"] + [f"minecraft:{c}_terracotta" for c in COLORS],
    "minecraft:glazed_terracotta": [f"minecraft:{c}_glazed_terracotta" for c in COLORS],
    
    # Wool & Carpet
    "minecraft:wool": [f"minecraft:{c}_wool" for c in COLORS],
    "minecraft:carpet": [f"minecraft:{c}_carpet" for c in COLORS],
    
    # Glass
    "minecraft:stained_glass": [f"minecraft:{c}_stained_glass" for c in COLORS],
    "minecraft:stained_glass_pane": [f"minecraft:{c}_stained_glass_pane" for c in COLORS],
    
    # Wood
    "minecraft:planks": [f"minecraft:{w}_planks" for w in WOOD_TYPES],
    "minecraft:log": [f"minecraft:{w}_log" for w in WOOD_TYPES] + [f"minecraft:stripped_{w}_log" for w in WOOD_TYPES],
    "minecraft:wood": [f"minecraft:{w}_wood" for w in WOOD_TYPES] + [f"minecraft:stripped_{w}_wood" for w in WOOD_TYPES],
    
    # Stairs
    "minecraft:stairs": [f"minecraft:{w}_stairs" for w in WOOD_TYPES] + [f"minecraft:{s}_stairs" for s in STONE_TYPES],
    
    # Slabs
    "minecraft:slab": [f"minecraft:{w}_slab" for w in WOOD_TYPES] + [f"minecraft:{s}_slab" for s in STONE_TYPES],
    
    # Fences
    "minecraft:fence": [f"minecraft:{w}_fence" for w in WOOD_TYPES],
    "minecraft:fence_gate": [f"minecraft:{w}_fence_gate" for w in WOOD_TYPES],
    
    # Walls
    "minecraft:wall": [f"minecraft:{s}_wall" for s in [
        "cobblestone", "mossy_cobblestone", "stone_brick", "mossy_stone_brick",
        "andesite", "diorite", "granite", "sandstone", "red_sandstone",
        "brick", "prismarine", "nether_brick", "red_nether_brick",
        "end_stone_brick", "blackstone", "polished_blackstone",
        "cobbled_deepslate", "polished_deepslate"
    ]],
    
    # Doors
    "minecraft:door": [f"minecraft:{w}_door" for w in WOOD_TYPES] + ["minecraft:iron_door"],
    
    # Trapdoors
    "minecraft:trapdoor": [f"minecraft:{w}_trapdoor" for w in WOOD_TYPES] + ["minecraft:iron_trapdoor"],
    
    # Buttons
    "minecraft:button": [f"minecraft:{w}_button" for w in WOOD_TYPES] + ["minecraft:stone_button", "minecraft:polished_blackstone_button"],
    "minecraft:wooden_button": [f"minecraft:{w}_button" for w in WOOD_TYPES],
    
    # Pressure Plates
    "minecraft:pressure_plate": [f"minecraft:{w}_pressure_plate" for w in WOOD_TYPES] + ["minecraft:stone_pressure_plate", "minecraft:light_weighted_pressure_plate", "minecraft:heavy_weighted_pressure_plate"],
    "minecraft:wooden_pressure_plate": [f"minecraft:{w}_pressure_plate" for w in WOOD_TYPES],
    
    # Signs
    "minecraft:sign": [f"minecraft:{w}_sign" for w in WOOD_TYPES],
    "minecraft:wall_sign": [f"minecraft:{w}_wall_sign" for w in WOOD_TYPES],
    "minecraft:hanging_sign": [f"minecraft:{w}_hanging_sign" for w in WOOD_TYPES],
    "minecraft:wall_hanging_sign": [f"minecraft:{w}_wall_hanging_sign" for w in WOOD_TYPES],
    
    # Beds
    "minecraft:bed": [f"minecraft:{c}_bed" for c in COLORS],
    
    # Banners
    "minecraft:banner": [f"minecraft:{c}_banner" for c in COLORS],
    "minecraft:wall_banner": [f"minecraft:{c}_wall_banner" for c in COLORS],
    
    # Candles
    "minecraft:candle": ["minecraft:candle"] + [f"minecraft:{c}_candle" for c in COLORS],
    
    # Shulker Boxes
    "minecraft:shulker_box": ["minecraft:shulker_box"] + [f"minecraft:{c}_shulker_box" for c in COLORS],
}

def expand_block_list(blocks):
    """Expand generic names to full IDs."""
    result = []
    for b in blocks:
        if b in EXPANSIONS:
            result.extend(EXPANSIONS[b])
        else:
            result.append(b)
    return result

def expand_replacement_list(replacements):
    """Expand generic names in replacement rules."""
    result = []
    for block_name, chance in replacements:
        if block_name in EXPANSIONS:
            # Use the first variant as the default replacement
            result.append([EXPANSIONS[block_name][0], chance])
        else:
            result.append([block_name, chance])
    return result

def main():
    parser = argparse.ArgumentParser(description="Expand generic block names in erosion config")
    parser.add_argument("--input", default="erosion_config.json", help="Input config file")
    parser.add_argument("--output", default="erosion_config_fixed.json", help="Output config file")
    args = parser.parse_args()
    
    print(f"Reading {args.input}...")
    with open(args.input) as f:
        config = json.load(f)
    
    # Expand all category block lists
    for cat_name, cat_data in config.get("categories", {}).items():
        if "blocks" in cat_data:
            original_count = len(cat_data["blocks"])
            cat_data["blocks"] = expand_block_list(cat_data["blocks"])
            expanded_count = len(cat_data["blocks"])
            print(f"  {cat_name}: {original_count} -> {expanded_count} blocks")
        
        # Expand replacements too
        if "replacements" in cat_data:
            cat_data["replacements"] = expand_replacement_list(cat_data["replacements"])
    
    print(f"\nWriting {args.output}...")
    with open(args.output, 'w') as f:
        json.dump(config, f, indent=4)
    
    print(f"Done! Use this config for erosion: {args.output}")

if __name__ == "__main__":
    main()
