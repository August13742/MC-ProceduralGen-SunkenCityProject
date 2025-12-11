"""
audit_world.py
Scans a Minecraft region and procedurally generates a complex Erosion Config.
"""
import argparse
import json
import amulet
from collections import Counter

# --- THE SMART CLASSIFIER ---
# Priority matters! (e.g., "iron_door" matches 'iron' before 'door')
CATEGORY_KEYWORDS = {
    "ignored":          ["air", "barrier", "structure", "bedrock", "portal", "gateway", "command", "jigsaw", "light", "void"],
    "ice_snow":         ["ice", "snow", "powder"],
    "fluid":            ["water", "lava", "bubble"],
    "tech_redstone":    ["piston", "redstone", "repeater", "comparator", "observer", "detector", "sensor", "sculk", "target", "wire", "dispenser", "dropper", "activator", "button", "lever", "switch", "pressure_plate"],
    "ore_veins":        ["_ore", "ancient_debris", "amethyst_cluster"],
    "vegetation":       ["leaves", "grass", "flower", "vine", "sapling", "lily", "kelp", "seagrass", "fern", "bush", "cactus", "melon", "pumpkin", "spore", "berry", "root", "azalea", "drip_leaf", "lichen"],
    "metal_structural": ["iron", "gold", "copper", "chain", "bars", "anvil", "cauldron", "hopper", "netherite", "steel"],
    "light_fixtures":   ["lantern", "torch", "candle", "lamp", "end_rod", "glowstone", "shroomlight", "froglight"],
    "fragile_glass":    ["glass", "pane", "beacon", "conduit", "mirror"],
    "functional_heavy": ["furnace", "smoker", "blast", "chest", "shulker", "barrel", "enchanting", "table", "loom", "stonecutter", "grindstone", "smithing", "cartography"],
    "organic_soft":     ["wool", "carpet", "bed", "banner", "canvas", "cake", "flesh", "slime", "honey", "sponge", "hay", "moss", "book", "painting"],
    "concrete":         ["concrete", "terracotta", "glazed"],
    "rot_wood":         ["log", "planks", "wood", "stem", "hyphae", "fence", "gate", "sign", "composter", "beehive", "bamboo", "scaffolding", "bookshelf", "door", "trapdoor"],
    "mineral_hard":     ["obsidian", "netherite", "diamond_block", "emerald_block", "quartz", "purpur", "prismarine", "amethyst_block"],
    "soil":             ["dirt", "sand", "gravel", "clay", "podzol", "mycelium", "mud", "soul_sand", "soul_soil", "path", "farmland"],
    "solid_stone":      ["stone", "cobble", "brick", "andesite", "diorite", "granite", "deepslate", "basalt", "blackstone", "tuff", "dripstone", "calcite", "nether_rack", "end_stone", "wall"]
}

# The complex ruleset we defined earlier
DEFAULT_RULES = {
    "rot_wood":         [["minecraft:air", 0.6], ["minecraft:spruce_slab", 0.15], ["minecraft:oak_stairs", 0.05]],
    "organic_soft":     [["minecraft:air", 0.85], ["minecraft:mud", 0.1], ["minecraft:gray_concrete_powder", 0.05]],
    "fragile_glass":    [["minecraft:air", 0.9], ["minecraft:cyan_stained_glass_pane", 0.1]],
    "solid_stone":      [["minecraft:mossy_stone_bricks", 0.25], ["minecraft:mossy_cobblestone", 0.15], ["minecraft:cracked_stone_bricks", 0.1], ["minecraft:gravel", 0.05]],
    "mineral_hard":     [["minecraft:crying_obsidian", 0.05]],
    "metal_structural": [["minecraft:oxidized_copper", 0.6], ["minecraft:air", 0.1], ["minecraft:orange_stained_glass_pane", 0.1]],
    "tech_redstone":    [["minecraft:air", 0.8], ["minecraft:cobblestone_slab", 0.1], ["minecraft:daylight_detector", 0.05]],
    "functional_heavy": [["minecraft:cobblestone", 0.3], ["minecraft:blackstone", 0.2]],
    "light_fixtures":   [["minecraft:air", 0.7], ["minecraft:chain", 0.2]],
    "concrete":         [["minecraft:concrete_powder", 0.6]],
    "vegetation":       [["minecraft:air", 0.8], ["minecraft:seagrass", 0.1], ["minecraft:kelp_plant", 0.05]],
    "ice_snow":         [["minecraft:water", 0.8], ["minecraft:air", 0.2]],
    "soil":             [["minecraft:sand", 0.2], ["minecraft:mud", 0.1]],
    "fluid":            [["minecraft:obsidian", 0.1]],
    "ore_veins":        [], # Preserve ores
    "ignored":          []  # Handled separately
}

def classify_block(block_name):
    """Returns the best matching category or 'uncategorized'."""
    simple_name = block_name.split(":")[-1].lower()
    
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for k in keywords:
            if k in simple_name:
                return cat
    return "uncategorized"

def main():
    parser = argparse.ArgumentParser(description="Scan world and generate procedural erosion rules.")
    parser.add_argument("--world", required=True, help="Path to world folder")
    parser.add_argument("--bounds", nargs=4, type=int, required=True, metavar=('X1', 'Z1', 'X2', 'Z2'))
    parser.add_argument("--dim", default="minecraft:overworld", help="Dimension")
    parser.add_argument("--out", default="erosion_config.json", help="Output JSON path")
    
    args = parser.parse_args()
    
    print(f"Loading world: {args.world}")
    level = amulet.load_level(args.world)
    
    min_x, min_z, max_x, max_z = args.bounds
    cx_min, cx_max = min_x >> 4, max_x >> 4
    cz_min, cz_max = min_z >> 4, max_z >> 4
    
    print(f"Scanning Chunk Grid: ({cx_min},{cz_min}) to ({cx_max},{cz_max})")
    
    unique_blocks = set()
    processed_chunks = 0
    
    for cx in range(cx_min, cx_max + 1):
        for cz in range(cz_min, cz_max + 1):
            try:
                # Fast Scan: Read Palette Only
                chunk = level.get_chunk(cx, cz, args.dim)
                for b in chunk.block_palette:
                    name = b.namespaced_name
                    if "universal_minecraft" in name:
                        name = "minecraft:" + name.split(":", 1)[1]
                    name = name.split("[")[0] # Remove properties
                    unique_blocks.add(name)
            except Exception:
                pass
        
        processed_chunks += 1
        if processed_chunks % 100 == 0:
            print(f"Scanned {processed_chunks} chunks...")

    print(f"Audit Complete. Found {len(unique_blocks)} unique block types.")

    # --- Build Config ---
    config = {
        "global_settings": {"noise_scale": 0.15, "seed": 8841},
        "ignored": [],
        "categories": {},
        "uncategorized": []
    }
    
    # Init categories
    for cat, rules in DEFAULT_RULES.items():
        if cat != "ignored":
            config["categories"][cat] = {"blocks": [], "replacements": rules}

    # Sort blocks
    for b in sorted(list(unique_blocks)):
        cat = classify_block(b)
        
        if cat == "ignored":
            config["ignored"].append(b)
        elif cat == "uncategorized":
            config["uncategorized"].append(b)
        else:
            config["categories"][cat]["blocks"].append(b)

    with open(args.out, 'w') as f:
        json.dump(config, f, indent=4)
        
    print(f"Config written to {args.out}")
    print(f"Uncategorized blocks: {len(config['uncategorized'])}")

if __name__ == "__main__":
    main()