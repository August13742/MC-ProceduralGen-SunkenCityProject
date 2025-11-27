"""
mc_world2db.py

Requires:
    pip install amulet-map-editor

Usage example:

    python mc_world2db.py --world "C:\\Users\\augus\\AppData\\Roaming\\.minecraft\\saves\\SordrinBuildingSet" \
        --dim overworld \
        --min 0 1 -500 --max 900 100 256 \
        --out-dir blueprints_out \
        --min-size 10 \
        --style-tag medieval \
        --mode overwrite \
        --forward-axis +z

Pipeline:

1. Detect gallery base Y by raycasting down from the top of the scan box on random XZ columns.
2. Build a 2D occupancy grid: a column is "occupied" if there is any non-air block above base_y in that column.
3. Flood-fill the occupancy grid into connected XZ components ("islands" → candidate buildings).
4. For each component, compute a 3D bounding box from base_y up to the highest non-air block.
5. Dump each component as a blueprint JSON with relative coordinates.

All later processing (classifying, scoring, heuristics, foundation shaving) operates only
on these blueprint JSONs, not on the world save.
"""

from __future__ import annotations
import argparse
import os
import json
import random

from collections import Counter, deque
from typing import Dict, List, Tuple, Any

import amulet
from amulet.api.errors import ChunkDoesNotExist
from normalise_block import normalise_block


AXIS_TO_VEC: Dict[str, Tuple[int, int, int]] = {
    "+x": (1, 0, 0),
    "-x": (-1, 0, 0),
    "+z": (0, 0, 1),
    "-z": (0, 0, -1),
}

# ---- Dimension mapping -----------------------------------------------------

DIM_MAP = {
    "overworld": "minecraft:overworld",
    "nether":    "minecraft:the_nether",
    "end":       "minecraft:the_end",
    "0":         "minecraft:overworld",
    "-1":        "minecraft:the_nether",
    "1":         "minecraft:the_end",
}

AIR_IDS = {
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
}

# Direction → world-space vector (dx, dy, dz) — kept for potential future use
DIR_TO_VEC: Dict[str, Tuple[int, int, int]] = {
    "north": (0, 0, -1),
    "south": (0, 0,  1),
    "west":  (-1, 0, 0),
    "east":  (1,  0, 0),
}


# ---- Low-level helpers -----------------------------------------------------

def get_block(world, x: int, y: int, z: int, dim: str):
    """Safe wrapper: treat missing chunks as air."""
    try:
        return world.get_block(x, y, z, dim)
    except ChunkDoesNotExist:
        return None


def get_block_id(b) -> str:
    """Extract namespaced block id from amulet block (None => air).

    - Amulet uses 'universal_minecraft:' as its internal namespace.
    - We normalize that to 'minecraft:' because GDPC expects vanilla IDs.
    """
    if b is None:
        return "minecraft:air"

    ns = getattr(b, "namespaced_name", None)
    if not isinstance(ns, str):
        ns = str(ns) if ns is not None else "minecraft:air"

    if ns.startswith("universal_minecraft:"):
        return "minecraft:" + ns.split(":", 1)[1]

    # For modded content, keep the original namespace (modid:foo).
    return ns


def _normalise_nbt_value(v: Any) -> Any:
    """
    Try to convert Amulet NBT tags to plain Python types.
    Fallback: string representation.
    """
    if hasattr(v, "value"):
        return v.value
    if hasattr(v, "py"):
        try:
            return v.py()
        except Exception:
            pass
    return str(v)


def get_block_props(b) -> Dict[str, Any]:
    if b is None:
        return {}
    props = getattr(b, "properties", None)
    if not props:
        return {}
    raw = dict(props)
    return {k: _normalise_nbt_value(v) for k, v in raw.items()}


# ---- Base Y detection via downward raycasts --------------------------------

def raycast_down_column(world,
                        dim: str,
                        x: int,
                        z: int,
                        y_top: int,
                        y_bottom: int) -> int | None:
    """
    From (x, y_top, z) downwards to y_bottom, return first Y where block != air.
    Returns None if the entire column is air in this range.
    """
    for y in range(y_top, y_bottom - 1, -1):
        b = get_block(world, x, y, z, dim)
        bid = get_block_id(b)
        if bid not in AIR_IDS:
            return y
    return None


def detect_base_y_by_raycast(world,
                             dim: str,
                             x0: int, x1: int,
                             y0: int, y1: int,
                             z0: int, z1: int,
                             samples: int = 512) -> int:
    """
    Heuristic: detect the 'gallery base' Y by raycasting down on random XZ columns
    and taking the minimum Y where we hit *any* non-air block.

    Assumes a superflat-style gallery where everything sits on a common floor.
    """
    width = x1 - x0 + 1
    length = z1 - z0 + 1
    total_columns = width * length

    if total_columns <= 0:
        raise RuntimeError("Invalid scan region (no columns).")

    rand = random.Random(1337)  # deterministic

    hits = []

    # If region is small, just brute-force every column.
    if total_columns <= samples:
        for xi in range(width):
            wx = x0 + xi
            for zi in range(length):
                wz = z0 + zi
                y_hit = raycast_down_column(world, dim, wx, wz, y1, y0)
                if y_hit is not None:
                    hits.append(y_hit)
    else:
        # Sample random columns
        for _ in range(samples):
            xi = rand.randint(0, width - 1)
            zi = rand.randint(0, length - 1)
            wx = x0 + xi
            wz = z0 + zi
            y_hit = raycast_down_column(world, dim, wx, wz, y1, y0)
            if y_hit is not None:
                hits.append(y_hit)

    if not hits:
        raise RuntimeError(
            "Could not detect base Y (no non-air blocks found in sampled columns)."
        )

    base_y = min(hits)
    return base_y


# ---- Column occupancy + components ("islands") -----------------------------

def build_occupancy_grid(world,
                         dim: str,
                         x0: int, x1: int,
                         z0: int, z1: int,
                         base_y: int,
                         y_max: int) -> List[List[bool]]:
    """
    Return a 2D grid marking columns that contain any non-air block ABOVE base_y.

    Grid indices:
        width  = x1 - x0 + 1
        length = z1 - z0 + 1
        grid[xi][zi] -> bool
    """
    width = x1 - x0 + 1
    length = z1 - z0 + 1
    grid = [[False] * length for _ in range(width)]

    for xi in range(width):
        wx = x0 + xi
        for zi in range(length):
            wz = z0 + zi

            # Check from base_y+1 up to y_max
            for y in range(base_y + 1, y_max + 1):
                b = get_block(world, wx, y, wz, dim)
                bid = get_block_id(b)
                if bid not in AIR_IDS:
                    grid[xi][zi] = True
                    break

    return grid


def find_components_from_grid(occ_grid: List[List[bool]]
                              ) -> List[List[Tuple[int, int]]]:
    """
    Flood-fill connected components in a boolean occupancy grid.

    Returns list of components; each component is a list of (xi, zi) index coords.
    """
    if not occ_grid:
        return []

    width = len(occ_grid)
    length = len(occ_grid[0])

    labels = [[-1] * length for _ in range(width)]
    components: List[List[Tuple[int, int]]] = []

    for xi in range(width):
        for zi in range(length):
            if not occ_grid[xi][zi] or labels[xi][zi] != -1:
                continue

            comp_id = len(components)
            q = deque([(xi, zi)])
            labels[xi][zi] = comp_id
            cells: List[Tuple[int, int]] = []

            while q:
                cx, cz = q.popleft()
                cells.append((cx, cz))

                for nx, nz in ((cx + 1, cz), (cx - 1, cz),
                               (cx, cz + 1), (cx, cz - 1)):
                    if 0 <= nx < width and 0 <= nz < length:
                        if occ_grid[nx][nz] and labels[nx][nz] == -1:
                            labels[nx][nz] = comp_id
                            q.append((nx, nz))

            components.append(cells)

    return components


# ---- Building bbox + block extraction --------------------------------------

def compute_building_bbox_3d(world,
                             dim: str,
                             x0: int, z0: int,
                             base_y: int, y_max: int,
                             comp_cells: List[Tuple[int, int]]
                             ) -> Tuple[int, int, int, int, int, int]:
    """
    Compute 3D bbox for a component, starting from base_y (to capture foundation,
    basements, etc.) up to the highest non-air block.

    Returns (min_x, max_x, y_bottom, y_top, min_z, max_z).
    """
    xs = [x0 + xi for (xi, _) in comp_cells]
    zs = [z0 + zi for (_, zi) in comp_cells]

    min_x, max_x = min(xs), max(xs)
    min_z, max_z = min(zs), max(zs)

    # Scan downwards from y_max to base_y to find actual top.
    actual_top = base_y
    for wx in range(min_x, max_x + 1):
        for wz in range(min_z, max_z + 1):
            for y in range(y_max, base_y - 1, -1):
                b = get_block(world, wx, y, wz, dim)
                bid = get_block_id(b)
                if bid not in AIR_IDS:
                    if y > actual_top:
                        actual_top = y
                    break

    y_bottom = base_y
    y_top = actual_top

    return min_x, max_x, y_bottom, y_top, min_z, max_z


def extract_relative_blocks(world,
                            dim: str,
                            bbox: Tuple[int, int, int, int, int, int]
                            ) -> List[Dict[str, Any]]:
    """
    Extract all non-air blocks inside bbox as relative coordinates.

    Returns list of dicts:
        {
            "dx": int,
            "dy": int,
            "dz": int,
            "id": "minecraft:whatever",   # vanilla-normalised
            "props": {...}                # vanilla-valid blockstates
        }
    """
    min_x, max_x, y0, y1, min_z, max_z = bbox
    blocks_out: List[Dict[str, Any]] = []

    for wx in range(min_x, max_x + 1):
        for y in range(y0, y1 + 1):
            for wz in range(min_z, max_z + 1):
                b = get_block(world, wx, y, wz, dim)
                raw_id = get_block_id(b)
                if raw_id in AIR_IDS:
                    continue
                raw_props = get_block_props(b)
                bid, props = normalise_block(raw_id, raw_props)

                dx, dy, dz = wx - min_x, y - y0, wz - min_z
                blocks_out.append({
                    "dx": dx,
                    "dy": dy,
                    "dz": dz,
                    "id": bid,
                    "props": props,
                })

    return blocks_out


# ---- File writers ----------------------------------------------------------

def write_blueprint_json(path: str,
                         meta: Dict[str, Any],
                         blocks: List[Dict[str, Any]]) -> None:
    data = {
        "meta": meta,
        "blocks": blocks,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_index_json(out_dir: str,
                     index: Dict[str, Dict[str, Any]]) -> None:
    """
    index: id -> { "file": "bp_000.json", "meta": {...} }
    """
    idx_path = os.path.join(out_dir, "blueprints_index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump({"blueprints": index}, f, ensure_ascii=False, indent=2)


# ---- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--world", required=True,
                    help="Path to Java world root (contains level.dat)")
    ap.add_argument("--dim", default="overworld",
                    help="overworld|nether|end or 0|-1|1")
    ap.add_argument("--min", nargs=3, type=int,
                    metavar=("X0", "Y0", "Z0"), required=True)
    ap.add_argument("--max", nargs=3, type=int,
                    metavar=("X1", "Y1", "Z1"), required=True)
    ap.add_argument(
        "--base-y",
        type=int,
        default=None,
        help="Gallery base Y. If omitted, auto-detect via downward raycasts."
    )
    # Backwards-compat aliases; treated as base_y if provided.
    ap.add_argument("--flat-y", type=int, default=None,
                    help="(Deprecated) Alias for --base-y.")
    ap.add_argument("--platform-y", type=int, default=None,
                    help="(Deprecated) Alias for --base-y.")
    ap.add_argument("--out-dir", required=True,
                    help="Directory to output bp_XXX.json + blueprints_index.json")
    ap.add_argument("--min-size", type=int, default=50,
                    help="Minimum number of non-air blocks to treat as a building")
    ap.add_argument("--style-tag", type=str, default="generic",
                    help="Freeform style tag stored into META['style'] (e.g. 'medieval')")
    ap.add_argument("--mode",
                    choices=["overwrite", "append"],
                    default="overwrite",
                    help="overwrite: clear output dir first; append: add to existing blueprints")
    ap.add_argument(
        "--forward-axis",
        choices=["+x", "-x", "+z", "-z"],
        default="+z",
        help="World-space forward direction of building façades.",
    )

    args = ap.parse_args()

    dim = DIM_MAP.get(str(args.dim).lower(), args.dim)
    (x0, y0, z0) = args.min
    (x1, y1, z1) = args.max

    # Normalise ranges
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    if z0 > z1:
        z0, z1 = z1, z0

    forward_axis: str = args.forward_axis
    forward_vec = AXIS_TO_VEC[forward_axis]

    os.makedirs(args.out_dir, exist_ok=True)

    # Load or initialize index
    index_path = os.path.join(args.out_dir, "blueprints_index.json")
    if args.mode == "append" and os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f).get("blueprints", {})
        print(f"[info] appending to existing index with {len(index)} blueprints")
        existing_nums = []
        for key in index.keys():
            if key.startswith("bp_"):
                try:
                    existing_nums.append(int(key.split("_")[1]))
                except (ValueError, IndexError):
                    pass
        start_idx = max(existing_nums) + 1 if existing_nums else 0
    else:
        index = {}
        start_idx = 0
        if args.mode == "overwrite":
            print("[info] overwrite mode: starting fresh index")

    world = amulet.load_level(args.world)
    print(f"[info] loaded world {args.world}")
    print(f"[info] scanning box X[{x0},{x1}] Y[{y0},{y1}] Z[{z0},{z1}] in dim={dim}")
    print(f"[info] forward_axis={forward_axis}, forward_vec={forward_vec}")

    # Determine base level:
    # precedence: --base-y > --flat-y > --platform-y > auto-detect via raycasts.
    base_y = args.base_y
    if base_y is None and args.flat_y is not None:
        base_y = args.flat_y
    if base_y is None and args.platform_y is not None:
        base_y = args.platform_y

    if base_y is not None:
        print(f"[info] using user-specified base Y = {base_y}")
    else:
        print("[info] auto-detecting gallery base Y via downward raycasts...")
        base_y = detect_base_y_by_raycast(world, dim, x0, x1, y0, y1, z0, z1)
        print(f"[info] detected base Y = {base_y}")

    # Build occupancy grid and extract components
    print("[info] building occupancy grid...")
    occ_grid = build_occupancy_grid(world, dim, x0, x1, z0, z1, base_y, y1)

    print("[info] flood-filling components (islands)...")
    comps = find_components_from_grid(occ_grid)
    print(f"[info] found {len(comps)} components")

    if len(comps) == 0:
        print("[warn] no components found - nothing to process")
        write_index_json(args.out_dir, index)
        print(f"[done] index: {index_path}")
        return

    kept = 0

    for idx, comp_cells in enumerate(comps):
        actual_idx = start_idx + idx

        bbox = compute_building_bbox_3d(
            world, dim,
            x0, z0,
            base_y, y1,
            comp_cells
        )

        min_x, max_x, yb, yt, min_z, max_z = bbox
        blocks_rel = extract_relative_blocks(world, dim, bbox)

        if len(blocks_rel) < args.min_size:
            print(f"[skip] component {actual_idx} too small ({len(blocks_rel)} blocks)")
            continue

        mod_name = f"bp_{actual_idx:03d}"
        json_path = os.path.join(args.out_dir, f"{mod_name}.json")

        # --- META construction ---
        size_x = max_x - min_x + 1
        size_y = yt - yb + 1
        size_z = max_z - min_z + 1

        if blocks_rel:
            top_y_local = max(b["dy"] for b in blocks_rel)
        else:
            top_y_local = 0

        top_y_world = yb + top_y_local

        block_counts = Counter(b["id"] for b in blocks_rel)

        meta = {
            "id": mod_name,
            "name": mod_name,
            "style": args.style_tag,
            "world_origin": (min_x, yb, min_z),
            "base_y": base_y,
            # Backwards compat: treat flat/platform as base level now.
            "flat_y": base_y,
            "platform_y": base_y,
            "size": (size_x, size_y, size_z),
            "top_y_local": top_y_local,
            "top_y_world": top_y_world,
            "block_counts": dict(block_counts),
            "forward_axis": forward_axis,
            "forward_vec": forward_vec,
            "category": None,
            "landmass": None,
            "tags": [],
            "notes": "",
        }

        write_blueprint_json(json_path, meta, blocks_rel)

        index[mod_name] = {
            "file": f"{mod_name}.json",
            "meta": meta,
        }

        kept += 1
        print(f"[ok] wrote {json_path} with {len(blocks_rel)} blocks")

    write_index_json(args.out_dir, index)
    print(f"[done] kept {kept} buildings")
    print(f"[done] index: {index_path}")


if __name__ == "__main__":
    main()
