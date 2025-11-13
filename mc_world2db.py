"""
mc_world2db.py

Requires:
    pip install amulet-map-editor

Usage example:

    python mc_world2db.py --world "C:\\Users\\augus\\AppData\\Roaming\\.minecraft\\saves\\SordrinBuildingSet" \
        --dim overworld \
        --min 0 1 -500 --max 900 100 256 \
        --platform-y 2 \
        --out-dir blueprints_out \
        --min-size 10 \
        --style-tag medieval \
        --mode overwrite \
        --forward-axis +z

mode option: overwrite, append
Note:
- Won't work (stuck forever) if the world save is loaded (opened in MC).
- platform-y specification is -1 from what you see in F3 view 
  (because your character is standing on it, which means ground is 1 lower).

All later processing (classifying residential/commercial/etc., computing
utility scores, city-planning heuristics) should operate purely on the
generated JSON blueprints and not touch the world save again.
"""

from __future__ import annotations
import argparse
import os
import json

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

PLATFORM_BLOCK_IDS = {
    "minecraft:grass_block",
    "minecraft:dirt",
}

AIR_IDS = {
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
}

# Direction → world-space vector (dx, dy, dz)
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
                            bbox: Tuple[int, int, int, int, int, int]) -> List[Dict[str, Any]]:
    """
    Extract all non-air blocks inside bbox as relative coordinates.

    Return list of dicts:
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

def write_blueprint_json(path: str, meta: Dict[str, Any], blocks: List[Dict[str, Any]]) -> None:
    data = {
        "meta": meta,
        "blocks": blocks,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_index_json(out_dir: str, index: Dict[str, Dict[str, Any]]) -> None:
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
    ap.add_argument("--min", nargs=3, type=int, metavar=("X0", "Y0", "Z0"), required=True)
    ap.add_argument("--max", nargs=3, type=int, metavar=("X1", "Y1", "Z1"), required=True)
    ap.add_argument("--platform-y", type=int, default=None,
                    help="Y-level of the grass platform. If omitted, auto-detect (slow).")
    ap.add_argument("--out-dir", required=True,
                    help="Directory to output bp_XXX.json + blueprints_index.json")
    ap.add_argument("--min-size", type=int, default=50,
                    help="Minimum number of non-air blocks to treat as a building")
    ap.add_argument("--style-tag", type=str, default="generic",
                    help="Freeform style tag stored into META['style'] (e.g. 'medieval')")
    ap.add_argument("--mode", choices=["overwrite", "append"], default="overwrite",
                    help="overwrite: clear output dir first; append: add to existing blueprints")

    ap.add_argument(
        "--forward-axis",
        choices=["+x", "-x", "+z", "-z"],
        default="+z",
        help="World-space forward direction of building façades (e.g. +z means façades face increasing Z).",
    )

    args = ap.parse_args()

    dim = DIM_MAP.get(str(args.dim).lower(), args.dim)
    (x0, y0, z0) = args.min
    (x1, y1, z1) = args.max

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
            print(f"[info] overwrite mode: starting fresh index")

    world = amulet.load_level(args.world)
    print(f"[info] loaded world {args.world}")
    print(f"[info] scanning box X[{x0},{x1}] Y[{y0},{y1}] Z[{z0},{z1}] in dim={dim}")
    print(f"[info] forward_axis={forward_axis}, forward_vec={forward_vec}")

    if args.platform_y is not None:
        platform_y = args.platform_y
        print(f"[info] using user-specified platform Y = {platform_y}")
    else:
        print("[warn] no --platform-y given, auto-detecting (slow)...")
        platform_y = detect_platform_y(world, dim, x0, x1, y0, y1, z0, z1)
        print(f"[info] detected platform Y = {platform_y}")

    comps = find_platform_components(world, dim, x0, x1, z0, z1, platform_y)
    print(f"[info] found {len(comps)} grass components")

    if len(comps) == 0:
        print("[warn] no components found - nothing to process")
        print(f"[done] index: {index_path}")
        return

    # Y-range for extraction: include platform-1 (dirt) up to max Y bound
    y_bottom = max(y0, platform_y - 1)
    y_top = y1

    kept = 0

    for idx, comp_cells in enumerate(comps):
        actual_idx = start_idx + idx
        bbox = compute_building_bbox(
            x0, z0,
            y_bottom, y_top,
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
            "platform_y": platform_y,
            "size": (size_x, size_y, size_z),
            "top_y_local": top_y_local,
            "top_y_world": top_y_world,
            "block_counts": dict(block_counts),

            # Orientation info in pure coordinate terms
            "forward_axis": forward_axis,   # "+z", "-z", "+x", "-x"
            "forward_vec": forward_vec,     # [dx, dy, dz]

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
