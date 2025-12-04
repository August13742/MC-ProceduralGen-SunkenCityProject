"""
mc_world2db_region.py

Extract an entire region of a Minecraft world to a blueprint JSON file,
filtering out unwanted blocks (air, common terrain, user-specified blocks).

Requires:
    pip install amulet-map-editor

Usage example:

    python mc_world2db_region.py --world "C:\\path\\to\\world" \
        --dim overworld \
        --min 100 60 200 --max 200 120 300 \
        --out region_export.json \
        --filter-blocks minecraft:dirt minecraft:grass_block \
        --style-tag medieval

python mc_world2db_region.py --world "C:\\Users\\augus\\AppData\\Roaming\\.minecraft\\saves\\Weston City V0.3" --dim overworld --min -1000 40 -1000 --max 1000 200 1000 --out city_region.json

Pipeline:

1. Scan the entire bounding box from min to max coordinates.
2. Filter out air blocks and common terrain blocks (configurable).
3. Filter out any additional user-specified blocks.
4. Dump all remaining blocks as a single blueprint JSON with relative coordinates.
"""

from __future__ import annotations
import argparse
import os
import json

from collections import Counter
from typing import Dict, List, Tuple, Any, Set

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

# Default blocks to always filter out
AIR_IDS = {
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
}

# Common terrain/filler blocks that are typically unwanted in building exports
COMMON_TERRAIN_BLOCKS = {
    "minecraft:dirt",
    "minecraft:grass_block",
    "minecraft:bedrock",
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


# ---- Block extraction with filtering ---------------------------------------

def extract_region_blocks(world,
                          dim: str,
                          x0: int, x1: int,
                          y0: int, y1: int,
                          z0: int, z1: int,
                          filter_blocks: Set[str],
                          include_common_terrain: bool = False
                          ) -> List[Dict[str, Any]]:
    """
    Extract all blocks in the given region, filtering out unwanted blocks.
    
    Returns list of dicts with relative coordinates:
        {
            "dx": int,
            "dy": int,
            "dz": int,
            "id": "minecraft:whatever",
            "props": {...}
        }
    """
    # Build complete filter set
    full_filter = set(AIR_IDS)
    if not include_common_terrain:
        full_filter.update(COMMON_TERRAIN_BLOCKS)
    full_filter.update(filter_blocks)
    
    blocks_out: List[Dict[str, Any]] = []
    
    total_scanned = 0
    total_filtered = 0
    
    for wx in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for wz in range(z0, z1 + 1):
                total_scanned += 1
                
                b = get_block(world, wx, y, wz, dim)
                raw_id = get_block_id(b)
                
                # Check if block should be filtered
                if raw_id in full_filter:
                    total_filtered += 1
                    continue
                
                raw_props = get_block_props(b)
                bid, props = normalise_block(raw_id, raw_props)
                
                # Check normalized id as well
                if bid in full_filter:
                    total_filtered += 1
                    continue
                
                dx, dy, dz = wx - x0, y - y0, wz - z0
                blocks_out.append({
                    "dx": dx,
                    "dy": dy,
                    "dz": dz,
                    "id": bid,
                    "props": props,
                })
    
    print(f"[info] scanned {total_scanned} positions, filtered {total_filtered}, kept {len(blocks_out)}")
    
    return blocks_out


# ---- File writer -----------------------------------------------------------

def write_blueprint_json(path: str,
                         meta: Dict[str, Any],
                         blocks: List[Dict[str, Any]]) -> None:
    data = {
        "meta": meta,
        "blocks": blocks,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Extract a region of a Minecraft world to a blueprint JSON, filtering unwanted blocks."
    )
    ap.add_argument("--world", required=True,
                    help="Path to Java world root (contains level.dat)")
    ap.add_argument("--dim", default="overworld",
                    help="overworld|nether|end or 0|-1|1")
    ap.add_argument("--min", nargs=3, type=int,
                    metavar=("X0", "Y0", "Z0"), required=True,
                    help="Minimum corner of region to extract")
    ap.add_argument("--max", nargs=3, type=int,
                    metavar=("X1", "Y1", "Z1"), required=True,
                    help="Maximum corner of region to extract")
    ap.add_argument("--out", required=True,
                    help="Output JSON file path (e.g., region_export.json)")
    ap.add_argument("--filter-blocks", nargs="*", default=[],
                    metavar="BLOCK_ID",
                    help="Additional block IDs to filter out (e.g., minecraft:cobblestone)")
    ap.add_argument("--include-common-terrain", action="store_true",
                    help="Include common terrain blocks (dirt, stone, gravel, etc.) instead of filtering them")
    ap.add_argument("--style-tag", type=str, default="generic",
                    help="Freeform style tag stored into META['style'] (e.g., 'medieval')")
    ap.add_argument("--name", type=str, default=None,
                    help="Name for the blueprint (defaults to output filename)")
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

    # Parse additional filter blocks
    filter_blocks: Set[str] = set(args.filter_blocks)
    
    # Ensure output directory exists
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    world = amulet.load_level(args.world)
    print(f"[info] loaded world {args.world}")
    print(f"[info] scanning region X[{x0},{x1}] Y[{y0},{y1}] Z[{z0},{z1}] in dim={dim}")
    print(f"[info] forward_axis={forward_axis}, forward_vec={forward_vec}")
    
    if filter_blocks:
        print(f"[info] additional filter blocks: {filter_blocks}")
    if args.include_common_terrain:
        print("[info] including common terrain blocks (dirt, stone, etc.)")
    else:
        print("[info] filtering common terrain blocks")

    # Extract blocks
    print("[info] extracting blocks from region...")
    blocks_rel = extract_region_blocks(
        world, dim,
        x0, x1, y0, y1, z0, z1,
        filter_blocks,
        include_common_terrain=args.include_common_terrain
    )

    if len(blocks_rel) == 0:
        print("[warn] no blocks extracted after filtering - output will be empty")

    # Determine blueprint name
    if args.name:
        bp_name = args.name
    else:
        bp_name = os.path.splitext(os.path.basename(args.out))[0]

    # --- META construction ---
    size_x = x1 - x0 + 1
    size_y = y1 - y0 + 1
    size_z = z1 - z0 + 1

    if blocks_rel:
        top_y_local = max(b["dy"] for b in blocks_rel)
    else:
        top_y_local = 0

    top_y_world = y0 + top_y_local

    block_counts = Counter(b["id"] for b in blocks_rel)

    meta = {
        "id": bp_name,
        "name": bp_name,
        "style": args.style_tag,
        "world_origin": (x0, y0, z0),
        "size": (size_x, size_y, size_z),
        "top_y_local": top_y_local,
        "top_y_world": top_y_world,
        "block_counts": dict(block_counts),
        "forward_axis": forward_axis,
        "forward_vec": forward_vec,
        "filtered_blocks": list(filter_blocks),
        "included_common_terrain": args.include_common_terrain,
        "category": None,
        "landmass": None,
        "tags": [],
        "notes": "",
    }

    write_blueprint_json(args.out, meta, blocks_rel)
    print(f"[done] wrote {args.out} with {len(blocks_rel)} blocks")


if __name__ == "__main__":
    main()
