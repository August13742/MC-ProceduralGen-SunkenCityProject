# mc_world2code.py
# python -m pip install amulet-map-editor

'''
python mc_world2code.py --world "F:\...\saves\Beta" --dim overworld --min 0 64 0 --max 16 75 16 --out out_gdpc.py
python mc_world2code.py --skip-preset terrain_basic ...
python mc_world2code.py --skip-preset terrain_aggressive --keep minecraft:oak_log,minecraft:lantern ...
python mc_world2code.py --skip-add minecraft:diorite,minecraft:andesite ...



'''


from __future__ import annotations
import argparse
import amulet

DIM_MAP = {
    "overworld": "minecraft:overworld",
    "nether":    "minecraft:the_nether",
    "end":       "minecraft:the_end",
    "0":         "minecraft:overworld",
    "-1":        "minecraft:the_nether",
    "1":         "minecraft:the_end",
}

# --- Skip presets -----------------------------------------------------------
SKIP_PRESETS = {
    "air_only": {
        "minecraft:air", "minecraft:cave_air", "minecraft:void_air", "universal_minecraft:air", "universal_minecraft:cave_air", "universal_minecraft:void_air",
    },
    "terrain_basic": {
        # air
        "minecraft:air", "minecraft:cave_air", "minecraft:void_air",
        # fluids
        "minecraft:water", "minecraft:flowing_water",
        "minecraft:lava",  "minecraft:flowing_lava",
        # overworld terrain
        "minecraft:stone", "minecraft:deepslate",
        "minecraft:dirt", "minecraft:coarse_dirt", "minecraft:rooted_dirt",
        "minecraft:grass_block", "minecraft:podzol", "minecraft:mycelium",
        "minecraft:sand", "minecraft:red_sand", "minecraft:gravel", "minecraft:clay",
        "minecraft:snow", "minecraft:snow_block", "minecraft:ice",
        "minecraft:packed_ice", "minecraft:blue_ice",
        # nether/end base terrain
        "minecraft:netherrack", "minecraft:basalt", "minecraft:blackstone",
        "minecraft:end_stone",
    },
    "terrain_aggressive": {
        # start from basic
        *{
            "minecraft:air","minecraft:cave_air","minecraft:void_air",
            "minecraft:water","minecraft:flowing_water","minecraft:lava","minecraft:flowing_lava",
            "minecraft:stone","minecraft:deepslate","minecraft:dirt","minecraft:coarse_dirt","minecraft:rooted_dirt",
            "minecraft:grass_block","minecraft:podzol","minecraft:mycelium",
            "minecraft:sand","minecraft:red_sand","minecraft:gravel","minecraft:clay",
            "minecraft:snow","minecraft:snow_block","minecraft:ice","minecraft:packed_ice","minecraft:blue_ice",
            "minecraft:netherrack","minecraft:basalt","minecraft:blackstone","minecraft:end_stone",
        },
        # ores (both stone & deepslate variants)
        "minecraft:coal_ore","minecraft:iron_ore","minecraft:copper_ore","minecraft:gold_ore",
        "minecraft:redstone_ore","minecraft:emerald_ore","minecraft:lapis_ore","minecraft:diamond_ore",
        "minecraft:nether_gold_ore","minecraft:nether_quartz_ore",
        "minecraft:deepslate_coal_ore","minecraft:deepslate_iron_ore","minecraft:deepslate_copper_ore",
        "minecraft:deepslate_gold_ore","minecraft:deepslate_redstone_ore","minecraft:deepslate_emerald_ore",
        "minecraft:deepslate_lapis_ore","minecraft:deepslate_diamond_ore",
        # foliage & naturals
        "minecraft:grass","minecraft:tall_grass","minecraft:fern","minecraft:large_fern",
        "minecraft:seagrass","minecraft:tall_seagrass","minecraft:kelp","minecraft:kelp_plant",
        "minecraft:sugar_cane","minecraft:cactus","minecraft:bamboo","minecraft:bamboo_sapling",
        "minecraft:vine","minecraft:glow_lichen","minecraft:moss_block","minecraft:moss_carpet",
        # logs/leaves (aggressive only – beware: will remove player builds using wood)
        "minecraft:oak_log","minecraft:spruce_log","minecraft:birch_log","minecraft:jungle_log",
        "minecraft:acacia_log","minecraft:dark_oak_log","minecraft:mangrove_log",
        "minecraft:cherry_log","minecraft:crimson_stem","minecraft:warped_stem",
        "minecraft:stripped_oak_log","minecraft:stripped_spruce_log","minecraft:stripped_birch_log",
        "minecraft:stripped_jungle_log","minecraft:stripped_acacia_log","minecraft:stripped_dark_oak_log",
        "minecraft:stripped_mangrove_log","minecraft:stripped_cherry_log",
        "minecraft:stripped_crimson_stem","minecraft:stripped_warped_stem",
        "minecraft:oak_leaves","minecraft:spruce_leaves","minecraft:birch_leaves","minecraft:jungle_leaves",
        "minecraft:acacia_leaves","minecraft:dark_oak_leaves","minecraft:mangrove_leaves","minecraft:cherry_leaves",
        "minecraft:azalea_leaves","minecraft:flowering_azalea_leaves",
    },
}

def states_to_literal(props: dict) -> str:
    if not props:
        return "{}"
    items = []
    for k, v in sorted(props.items()):
        if isinstance(v, bool):
            sv = "true" if v else "false"
        else:
            sv = str(v)
        items.append(f"\"{k}\":\"{sv}\"")
    return "{%s}" % (",".join(items))

def parse_csv_ids(s: str | None) -> set[str]:
    if not s:
        return set()
    return {tok.strip() for tok in s.split(",") if tok.strip()}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True, help="Path to Java world root (contains level.dat)")
    ap.add_argument("--dim", default="overworld", help="overworld|nether|end or 0|-1|1")
    ap.add_argument("--min", nargs=3, type=int, metavar=("X0","Y0","Z0"), required=True)
    ap.add_argument("--max", nargs=3, type=int, metavar=("X1","Y1","Z1"), required=True)
    ap.add_argument("--out", default="gdpc_dump.py", help="Output .py file with GDPC calls")
    ap.add_argument("--skip-preset", choices=list(SKIP_PRESETS.keys()), default="air_only",
                    help="Set of block IDs to skip (default: air_only).")
    ap.add_argument("--skip-add", default="", help="Comma-separated extra namespaced IDs to skip.")
    ap.add_argument("--keep", default="", help="Comma-separated namespaced IDs to force-keep (overrides skip).")
    args = ap.parse_args()

    dim = DIM_MAP.get(str(args.dim).lower(), args.dim)
    (x0, y0, z0) = args.min
    (x1, y1, z1) = args.max
    if x0 > x1: x0, x1 = x1, x0
    if y0 > y1: y0, y1 = y1, y0
    if z0 > z1: z0, z1 = z1, z0

    skip_set = set(SKIP_PRESETS[args.skip_preset])
    skip_set |= parse_csv_ids(args.skip_add)
    keep_set = parse_csv_ids(args.keep)

    world = amulet.load_level(args.world)

    lines = []
    total = 0
    placed = 0

    for y in range(y0, y1 + 1):
        for z in range(z0, z1 + 1):
            for x in range(x0, x1 + 1):
                total += 1
                try:
                    b = world.get_block(x, y, z, dim)
                except Exception:
                    continue
                ns = getattr(b, "namespaced_name", None)
                if not ns:
                    continue

                # Skip if in skip_set *and not* force-kept
                if ns in skip_set and ns not in keep_set:
                    continue

                props = dict(getattr(b, "properties", {}) or {})
                lit = states_to_literal(props)
                lines.append(f'editor.placeBlock(({x},{y},{z}), Block("{ns}", {lit}))')
                placed += 1

    header = [
        "# Auto-generated GDPC calls (no cuboid fusing).",
        "# Can be run standalone or pasted into an existing GDPC script.",
        "try:",
        "    editor  # reuse if already defined",
        "except NameError:",
        "    from gdpc import Editor",
        "    editor = Editor(buffering=True)",
        "from gdpc.block import Block",
        "",
    ]

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(header + lines) + "\n")

    print(f"[done] scanned {total} blocks, emitted {placed} placeBlock() lines -> {args.out}")
    print(f"[skip preset] {args.skip_preset}  | extra skip: {len(parse_csv_ids(args.skip_add))} | keep: {len(keep_set)}")

if __name__ == "__main__":
    main()
