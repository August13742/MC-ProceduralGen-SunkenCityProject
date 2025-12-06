"""
mc_world2db_region.py

Extract an entire region of a Minecraft world to a COMPACT format,
optimized for erosion processing (sunken city generation).

Requires:
    pip install amulet-map-editor

Usage example:

    python mc_world2db_region.py --world "C:\\path\\to\\world" \
        --dim overworld \
        --min 100 60 200 --max 200 120 300 \
        --out region_export.json

Output format (optimized for size):
    {
        "size": [x, y, z],
        "origin": [x, y, z],
        "palette": ["minecraft:stone", "minecraft:oak_planks", ...],
        "blocks": [[dx, dy, dz, palette_index], ...]
    }

This format:
- Uses a palette to avoid repeating block IDs
- Stores only position + palette index (no props - erosion doesn't need them)
- Uses arrays instead of objects for block data
- Typically 10-20x smaller than verbose format
"""

from __future__ import annotations
import argparse
import os
import json

from typing import Dict, List, Tuple, Set

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

# Default blocks to always filter out
AIR_IDS = {
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
}

# Common terrain/filler blocks filtered by default
COMMON_TERRAIN_BLOCKS = {
    "minecraft:dirt",
    "minecraft:grass_block",
    "minecraft:stone",
    "minecraft:deepslate",
    "minecraft:bedrock",
    "minecraft:gravel",
    "minecraft:sand",
    "minecraft:red_sand",
    "minecraft:clay",
    "minecraft:coarse_dirt",
    "minecraft:rooted_dirt",
    "minecraft:mud",
    "minecraft:podzol",
    "minecraft:mycelium",
    "minecraft:soul_sand",
    "minecraft:soul_soil",
    "minecraft:netherrack",
    "minecraft:end_stone",
    "minecraft:water",
    "minecraft:lava",
    "minecraft:flowing_water",
    "minecraft:flowing_lava",
    "minecraft:coal_ore",
    "minecraft:iron_ore",
    "minecraft:copper_ore",
    "minecraft:gold_ore",
    "minecraft:redstone_ore",
    "minecraft:emerald_ore",
    "minecraft:lapis_ore",
    "minecraft:diamond_ore",
    "minecraft:deepslate_coal_ore",
    "minecraft:deepslate_iron_ore",
    "minecraft:deepslate_copper_ore",
    "minecraft:deepslate_gold_ore",
    "minecraft:deepslate_redstone_ore",
    "minecraft:deepslate_emerald_ore",
    "minecraft:deepslate_lapis_ore",
    "minecraft:deepslate_diamond_ore",
    "minecraft:nether_gold_ore",
    "minecraft:nether_quartz_ore",
    "minecraft:ancient_debris",
}


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
    if not isinstance(ns, str):
        ns = str(ns) if ns is not None else "minecraft:air"

    if ns.startswith("universal_minecraft:"):
        return "minecraft:" + ns.split(":", 1)[1]

    return ns


# ---- Block extraction with filtering ---------------------------------------

def extract_region_compact(world,
                           dim: str,
                           x0: int, x1: int,
                           y0: int, y1: int,
                           z0: int, z1: int,
                           filter_blocks: Set[str],
                           include_common_terrain: bool = False
                           ) -> Tuple[List[str], List[List[int]]]:
    """
    Extract all blocks in the given region using compact format.
    
    Returns:
        palette: List of unique block IDs
        blocks: List of [dx, dy, dz, palette_idx] arrays
    """
    # Build complete filter set
    full_filter = set(AIR_IDS)
    if not include_common_terrain:
        full_filter.update(COMMON_TERRAIN_BLOCKS)
    full_filter.update(filter_blocks)
    
    # Palette: block_id -> index
    palette_map: Dict[str, int] = {}
    palette: List[str] = []
    
    # Blocks as compact arrays: [dx, dy, dz, palette_idx]
    blocks: List[List[int]] = []
    
    total_scanned = 0
    total_filtered = 0
    
    for wx in range(x0, x1 + 1):
        for wz in range(z0, z1 + 1):
            for y in range(y0, y1 + 1):
                total_scanned += 1
                
                b = get_block(world, wx, y, wz, dim)
                bid = get_block_id(b)
                
                # Check if block should be filtered
                if bid in full_filter:
                    total_filtered += 1
                    continue
                
                # Get or create palette index
                if bid not in palette_map:
                    palette_map[bid] = len(palette)
                    palette.append(bid)
                
                idx = palette_map[bid]
                dx, dy, dz = wx - x0, y - y0, wz - z0
                blocks.append([dx, dy, dz, idx])
        
        # Progress indicator every 100 X slices
        if (wx - x0) % 100 == 0:
            pct = ((wx - x0) / (x1 - x0 + 1)) * 100
            print(f"  {pct:.1f}% scanned...")
    
    print(f"[info] scanned {total_scanned} positions, filtered {total_filtered}, kept {len(blocks)}")
    print(f"[info] palette size: {len(palette)} unique block types")
    
    return palette, blocks


# ---- main ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Extract a Minecraft world region to compact format for erosion processing."
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
                    help="Output JSON file path")
    ap.add_argument("--filter-blocks", nargs="*", default=[],
                    metavar="BLOCK_ID",
                    help="Additional block IDs to filter out")
    ap.add_argument("--include-common-terrain", action="store_true",
                    help="Include common terrain blocks instead of filtering them")

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

    filter_blocks: Set[str] = set(args.filter_blocks)
    
    # Ensure output directory exists
    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    world = amulet.load_level(args.world)
    print(f"[info] loaded world {args.world}")
    print(f"[info] scanning region X[{x0},{x1}] Y[{y0},{y1}] Z[{z0},{z1}] in dim={dim}")
    
    region_size = (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)
    print(f"[info] region volume: {region_size:,} blocks")

    # Extract blocks
    print("[info] extracting blocks...")
    palette, blocks = extract_region_compact(
        world, dim,
        x0, x1, y0, y1, z0, z1,
        filter_blocks,
        include_common_terrain=args.include_common_terrain
    )

    if len(blocks) == 0:
        print("[warn] no blocks extracted after filtering")

    # Build compact output
    data = {
        "size": [x1 - x0 + 1, y1 - y0 + 1, z1 - z0 + 1],
        "origin": [x0, y0, z0],
        "palette": palette,
        "blocks": blocks,
    }

    # Write with minimal whitespace
    print(f"[info] writing to {args.out}...")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    
    # Report file size
    file_size = os.path.getsize(args.out)
    if file_size > 1024 * 1024:
        size_str = f"{file_size / (1024*1024):.1f} MB"
    else:
        size_str = f"{file_size / 1024:.1f} KB"
    
    print(f"[done] wrote {args.out} ({size_str})")
    print(f"[done] {len(blocks):,} blocks, {len(palette)} block types")


if __name__ == "__main__":
    main()
