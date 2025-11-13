"""
mc_world2db.py

Requires:
    pip install amulet-map-editor

Usage example:

    python mc_world2db.py ^
        --world "C:\\Users\\augus\\AppData\\Roaming\\.minecraft\\saves\\SordrinBuildingSet" ^
        --dim overworld ^
        --min 0 1 -500 ^
        --max 900 100 256 ^
        --platform-y 67 ^
        --out-dir blueprints_out ^
        --min-size 10
        
Note: 
Won't work (stuck forever) if the world save is loaded (opened in MC)
platform-y specification is -1 from what you see in F3 view (idk why but else it won't detect)

"""

from __future__ import annotations
import argparse
import os
from collections import Counter, deque
from typing import Dict, List, Tuple, Any

import amulet
from amulet.api.errors import ChunkDoesNotExist

# ---- Dimension mapping -----------------------------------------------------

DIM_MAP = {
    "overworld": "minecraft:overworld",
    "nether":    "minecraft:the_nether",
    "end":       "minecraft:the_end",
    "0":         "minecraft:overworld",
    "-1":        "minecraft:the_nether",
    "1":         "minecraft:the_end",
}

PLATFORM_BLOCK_IDS = {
    "universal_minecraft:grass_block",
    "universal_minecraft:dirt",
}

AIR_IDS = {
    "universal_minecraft:air",
    "universal_minecraft:cave_air",
    "universal_minecraft:void_air",
}

BlockTuple = Tuple[int, int, int, str, Dict[str, Any]]  # (dx,dy,dz, id, props)


# ---- Low-level helpers -----------------------------------------------------

def get_block(world, x: int, y: int, z: int, dim: str):
    """Safe wrapper: treat missing chunks as air."""
    try:
        return world.get_block(x, y, z, dim)
    except ChunkDoesNotExist:
        return None


def get_block_id(b) -> str:
    """Extract namespaced block id from amulet block (None => air)."""
    if b is None:
        return "minecraft:air"
    ns = getattr(b, "namespaced_name", None)
    if isinstance(ns, str):
        return ns
    return str(ns) if ns is not None else "minecraft:air"


def get_block_props(b) -> Dict[str, Any]:
    if b is None:
        return {}
    props = getattr(b, "properties", None)
    if not props:
        return {}
    return dict(props)


# ---- Optional (slow) platform detection -----------------------------------

def detect_platform_y(world, dim: str,
                      x0: int, x1: int,
                      y0: int, y1: int,
                      z0: int, z1: int) -> int:
    """Slow: scan all columns to find most common Y with PLATFORM_BLOCK_IDS."""
    hist = Counter()

    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            for y in range(y0, y1 + 1):
                b = get_block(world, x, y, z, dim)
                bid = get_block_id(b)
                if bid in PLATFORM_BLOCK_IDS:
                    hist[y] += 1
                    break

    if not hist:
        raise RuntimeError("Could not detect platform level (no PLATFORM_BLOCK_IDS found).")

    platform_y, _ = max(hist.items(), key=lambda kv: kv[1])
    return platform_y


# ---- Component detection on the platform plane -----------------------------

def find_platform_components(world, dim: str,
                             x0: int, x1: int,
                             z0: int, z1: int,
                             platform_y: int):
    """
    Return list of 2D connected components (grass islands) on the platform plane.

    Coords are in index-space:
        xi in [0, width), zi in [0, length)
    where world_x = x0 + xi, world_z = z0 + zi.
    """
    width = x1 - x0 + 1
    length = z1 - z0 + 1

    is_platform = [[False] * length for _ in range(width)]

    for xi in range(width):
        wx = x0 + xi
        for zi in range(length):
            wz = z0 + zi
            b = get_block(world, wx, platform_y, wz, dim)
            bid = get_block_id(b)
            if bid in PLATFORM_BLOCK_IDS:
                is_platform[xi][zi] = True

    labels = [[-1] * length for _ in range(width)]
    components: List[List[Tuple[int, int]]] = []

    for xi in range(width):
        for zi in range(length):
            if not is_platform[xi][zi] or labels[xi][zi] != -1:
                continue

            comp_id = len(components)
            q = deque([(xi, zi)])
            labels[xi][zi] = comp_id
            cells: List[Tuple[int, int]] = []

            while q:
                cx, cz = q.popleft()
                cells.append((cx, cz))

                for nx, nz in ((cx + 1, cz), (cx - 1, cz), (cx, cz + 1), (cx, cz - 1)):
                    if 0 <= nx < width and 0 <= nz < length:
                        if is_platform[nx][nz] and labels[nx][nz] == -1:
                            labels[nx][nz] = comp_id
                            q.append((nx, nz))

            components.append(cells)

    return components


# ---- Building bbox + block extraction --------------------------------------

def compute_building_bbox(x0: int, z0: int,
                          y_bottom: int, y_top: int,
                          comp_cells: List[Tuple[int, int]]):
    """
    Given component cells in index-space, compute *rectangular* world-space bbox:

        (min_x, max_x, y_bottom, y_top, min_z, max_z)

    No vertical scanning; we just take the full Y range and filter air later.
    """
    xs = [x0 + xi for (xi, _) in comp_cells]
    zs = [z0 + zi for (_, zi) in comp_cells]

    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)

    return min_x, max_x, y_bottom, y_top, min_z, max_z


def extract_relative_blocks(world, dim: str,
                            bbox: Tuple[int, int, int, int, int, int]) -> List[BlockTuple]:
    """
    Extract all non-air blocks inside bbox as relative coordinates
    (dx,dy,dz) from bbox origin (min_x, y0, min_z).
    """
    min_x, max_x, y0, y1, min_z, max_z = bbox
    blocks_out: List[BlockTuple] = []

    for wx in range(min_x, max_x + 1):
        for y in range(y0, y1 + 1):
            for wz in range(min_z, max_z + 1):
                b = get_block(world, wx, y, wz, dim)
                bid = get_block_id(b)
                if bid in AIR_IDS:
                    continue
                dx, dy, dz = wx - min_x, y - y0, wz - min_z
                props = get_block_props(b)
                blocks_out.append((dx, dy, dz, bid, props))

    return blocks_out


# ---- File writers ----------------------------------------------------------

def write_blueprint_file(path: str, name: str, blocks: List[BlockTuple]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Auto-generated building blueprint\n")
        f.write(f'NAME = "{name}"\n')
        f.write("BLOCKS = [\n")
        for (dx, dy, dz, block_id, props) in blocks:
            f.write(
                f"    (({dx}, {dy}, {dz}), "
                f'"{block_id}", '
                f"{repr(props)}),\n"
            )
        f.write("]\n")


def write_master_file(out_dir: str, module_names: List[str]) -> None:
    master_path = os.path.join(out_dir, "blueprints_master.py")
    with open(master_path, "w", encoding="utf-8") as f:
        f.write("# Auto-generated master blueprint database\n")
        for mod in module_names:
            f.write(f"import {mod}\n")
        f.write("\nBLUEPRINTS = {\n")
        for mod in module_names:
            f.write(f"    {mod}.NAME: {mod}.BLOCKS,\n")
        f.write("}\n\n")
        f.write(
            "def place_blueprint(editor, origin, blocks):\n"
            "    \"\"\"Place a blueprint at origin using GDPC editor.\"\"\"\n"
            "    from gdpc.block import Block\n"
            "    ox, oy, oz = origin\n"
            "    for (dx, dy, dz), block_id, props in blocks:\n"
            "        editor.placeBlock((ox+dx, oy+dy, oz+dz), Block(block_id, props))\n"
        )


# ---- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True,
                    help="Path to Java world root (contains level.dat)")
    ap.add_argument("--dim", default="overworld",
                    help="overworld|nether|end or 0|-1|1")
    ap.add_argument("--min", nargs=3, type=int, metavar=("X0", "Y0", "Z0"), required=True)
    ap.add_argument("--max", nargs=3, type=int, metavar=("X1", "Y1", "Z1"), required=True)
    ap.add_argument("--platform-y", type=int, default=None,
                    help="Y-level of the grass platform. If omitted, auto-detect (slow).")
    ap.add_argument("--out-dir", required=True,
                    help="Directory to output bp_XXX.py + blueprints_master.py")
    ap.add_argument("--min-size", type=int, default=50,
                    help="Minimum number of blocks to treat as a building")
    args = ap.parse_args()

    dim = DIM_MAP.get(str(args.dim).lower(), args.dim)
    (x0, y0, z0) = args.min
    (x1, y1, z1) = args.max

    if x0 > x1: x0, x1 = x1, x0
    if y0 > y1: y0, y1 = y1, y0
    if z0 > z1: z0, z1 = z1, z0

    os.makedirs(args.out_dir, exist_ok=True)

    world = amulet.load_level(args.world)
    print(f"[info] loaded world {args.world}")
    print(f"[info] scanning box X[{x0},{x1}] Y[{y0},{y1}] Z[{z0},{z1}] in dim={dim}")

    if args.platform_y is not None:
        platform_y = args.platform_y
        print(f"[info] using user-specified platform Y = {platform_y}")
    else:
        print("[warn] no --platform-y given, auto-detecting (slow)...")
        platform_y = detect_platform_y(world, dim, x0, x1, y0, y1, z0, z1)
        print(f"[info] detected platform Y = {platform_y}")

    comps = find_platform_components(world, dim, x0, x1, z0, z1, platform_y)
    print(f"[info] found {len(comps)} grass components")

    # Y-range for extraction: include platform-1 (dirt) up to max Y bound
    y_bottom = max(y0, platform_y - 1)
    y_top = y1

    blueprint_modules: List[str] = []
    kept = 0

    for idx, comp_cells in enumerate(comps):
        bbox = compute_building_bbox(
            x0, z0,
            y_bottom, y_top,
            comp_cells
        )
        blocks_rel = extract_relative_blocks(world, dim, bbox)

        if len(blocks_rel) < args.min_size:
            print(f"[skip] component {idx} too small ({len(blocks_rel)} blocks)")
            continue

        mod_name = f"bp_{idx:03d}"
        py_path = os.path.join(args.out_dir, f"{mod_name}.py")
        write_blueprint_file(py_path, mod_name, blocks_rel)
        blueprint_modules.append(mod_name)
        kept += 1
        print(f"[ok] wrote {py_path} with {len(blocks_rel)} blocks")

    write_master_file(args.out_dir, blueprint_modules)
    print(f"[done] kept {kept} buildings")
    print(f"[done] master DB: {os.path.join(args.out_dir, 'blueprints_master.py')}")


if __name__ == "__main__":
    main()
