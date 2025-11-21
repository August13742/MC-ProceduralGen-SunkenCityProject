from __future__ import annotations
from typing import Tuple, List, Dict, Any
import math
import random

from gdpc.editor import Editor
from gdpc.block import Block

from blueprint_db import iter_blueprints, place_blueprint

# /setbuildarea ~0 ~0 ~0 ~800 255 ~800

MAX_BUILDINGS = 512



BP_DIR = "blueprints_cleaned"

GROUND_CANDIDATES = {
    "minecraft:grass_block",
    "minecraft:dirt",
    "minecraft:farmland",
    "minecraft:dirt_path",
    "minecraft:coarse_dirt",
    "minecraft:podzol",
    "minecraft:stone",
    "minecraft:andesite",
    "minecraft:diorite",
    "minecraft:granite",
    "minecraft:gravel",
    "minecraft:sand",
    "minecraft:red_sand",
}


def detect_ground_y(
    editor: Editor,
    x: int,
    z: int,
    y_min: int = -64,
    y_max: int = 255,
) -> int:
    """
    Heuristic ground detection:

    1) Highest block in GROUND_CANDIDATES.
    2) Otherwise: highest non-air.
    3) Otherwise: y_min.
    """
    for y in range(y_max, y_min - 1, -1):
        blk = editor.getBlock((x, y, z))
        if blk.id in GROUND_CANDIDATES:
            return y

    for y in range(y_max, y_min - 1, -1):
        blk = editor.getBlock((x, y, z))
        if blk.id != "minecraft:air":
            return y

    return y_min


# ---------------------------------------------------------------------------
# Blueprint loading & selection
# ---------------------------------------------------------------------------

def load_blueprints() -> List[Tuple[str, Dict[str, Any], list]]:
    """Load all blueprints into a list for easy selection."""
    bps = list(iter_blueprints(BP_DIR))
    if not bps:
        raise RuntimeError("No blueprints found in BP_DIR.")
    return bps


def filter_blueprints_by_max_size(
    blueprints: List[Tuple[str, Dict[str, Any], list]],
    max_size_x: int,
    max_size_z: int,
) -> List[Tuple[str, Dict[str, Any], list]]:
    """Drop obviously gigantic ones, keep anything that fits the area."""
    out: List[Tuple[str, Dict[str, Any], list]] = []
    for bp_id, meta, blocks in blueprints:
        size_x, size_y, size_z = meta["size"]
        if size_x <= max_size_x and size_z <= max_size_z:
            out.append((bp_id, meta, blocks))
    return out


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def rects_overlap(a: Tuple[int, int, int, int],
                  b: Tuple[int, int, int, int]) -> bool:
    """
    Axis-aligned rectangle overlap in XZ.

    a, b = (min_x, max_x, min_z, max_z)
    """
    ax0, ax1, az0, az1 = a
    bx0, bx1, bz0, bz1 = b

    if ax1 < bx0 or bx1 < ax0:
        return False
    if az1 < bz0 or bz1 < az0:
        return False
    return True


def compute_building_rect(
    origin_x: int,
    origin_z: int,
    size_x: int,
    size_z: int,
) -> Tuple[int, int, int, int]:
    """World-space XZ rect of a placed building."""
    return (
        origin_x,
        origin_x + size_x - 1,
        origin_z,
        origin_z + size_z - 1,
    )


def get_meta_forward_axis(meta: Dict[str, Any]) -> str:
    """Meta may or may not contain forward_axis; default to '+z'."""
    axis = meta.get("forward_axis", "+z")
    if axis not in ("+z", "-z", "+x", "-x"):
        axis = "+z"
    return axis


def compute_front_midpoint(
    origin_x: int,
    origin_z: int,
    size_x: int,
    size_z: int,
    forward_axis: str,
) -> Tuple[int, int]:
    """
    Returns (fx, fz) = midpoint of the front edge, in world coords.
    """
    if forward_axis == "+z":
        fx = origin_x + size_x // 2
        fz = origin_z
    elif forward_axis == "-z":
        fx = origin_x + size_x // 2
        fz = origin_z + size_z - 1
    elif forward_axis == "+x":
        fx = origin_x + size_x - 1
        fz = origin_z + size_z // 2
    elif forward_axis == "-x":
        fx = origin_x
        fz = origin_z + size_z // 2
    else:
        # Fallback: assume +z
        fx = origin_x + size_x // 2
        fz = origin_z
    return fx, fz


# ---------------------------------------------------------------------------
# Placement: organic scattering
# ---------------------------------------------------------------------------

class PlacedBuilding:
    __slots__ = ("bp_id", "meta", "blocks", "origin", "rect", "front")

    def __init__(
        self,
        bp_id: str,
        meta: Dict[str, Any],
        blocks: list,
        origin: Tuple[int, int, int],
        rect: Tuple[int, int, int, int],
        front: Tuple[int, int],
    ) -> None:
        self.bp_id = bp_id
        self.meta = meta
        self.blocks = blocks
        self.origin = origin      # (x, y, z)
        self.rect = rect          # (min_x, max_x, min_z, max_z)
        self.front = front        # (fx, fz)


def scatter_buildings(
    editor: Editor,
    blueprints: List[Tuple[str, Dict[str, Any], list]],
    area_x0: int,
    area_x1: int,
    area_z0: int,
    area_z1: int,
    ground_y: int,
    max_buildings: int = 40,
    max_attempts: int = 2000,
) -> List[PlacedBuilding]:
    """
    Rejection-sampling placement:
        - Random origin inside area
        - Reject if rect overlaps existing rects
        - Place, record, repeat
    """
    placed: List[PlacedBuilding] = []

    # Slight inset so we don't clip outside the area when placing big buildings
    area_width = area_x1 - area_x0 + 1
    area_depth = area_z1 - area_z0 + 1

    # Pre-sort blueprints by footprint area (big first) for nicer packing.
    bps_sorted = sorted(
        blueprints,
        key=lambda b: b[1]["size"][0] * b[1]["size"][2],
        reverse=True,
    )

    attempts = 0
    while attempts < max_attempts and len(placed) < max_buildings:
        attempts += 1

        # Pick a blueprint with bias towards larger ones
        bp_id, meta, blocks = random.choice(bps_sorted)
        size_x, size_y, size_z = meta["size"]

        if size_x > area_width or size_z > area_depth:
            continue  # impossible in this area

        # Random origin such that the building fully fits in the area
        ox = random.randint(area_x0, area_x1 - size_x + 1)
        oz = random.randint(area_z0, area_z1 - size_z + 1)
        oy = ground_y  # flat for now

        rect = compute_building_rect(ox, oz, size_x, size_z)

        # Check overlap
        conflict = False
        for pb in placed:
            if rects_overlap(rect, pb.rect):
                conflict = True
                break
        if conflict:
            continue

        forward_axis = get_meta_forward_axis(meta)
        fx, fz = compute_front_midpoint(ox, oz, size_x, size_z, forward_axis)

        # Place in world
        place_blueprint(editor, (ox, oy, oz), blocks)
        print(f"[place] {bp_id} at ({ox}, {oy}, {oz}), size={meta['size']}, forward_axis={forward_axis}")

        placed.append(
            PlacedBuilding(
                bp_id=bp_id,
                meta=meta,
                blocks=blocks,
                origin=(ox, oy, oz),
                rect=rect,
                front=(fx, fz),
            )
        )

    print(f"[scatter] placed {len(placed)} buildings after {attempts} attempts")
    return placed


# ---------------------------------------------------------------------------
# Road carving between front points
# ---------------------------------------------------------------------------

def carve_road_segment_x(
    editor: Editor,
    x0: int,
    x1: int,
    z_center: int,
    width: int,
    y: int,
    block: Block,
) -> None:
    if x0 > x1:
        x0, x1 = x1, x0
    half = width // 2
    z_start = z_center - half
    z_end = z_center + half

    for x in range(x0, x1 + 1):
        for z in range(z_start, z_end + 1):
            editor.placeBlock((x, y, z), block)


def carve_road_segment_z(
    editor: Editor,
    z0: int,
    z1: int,
    x_center: int,
    width: int,
    y: int,
    block: Block,
) -> None:
    if z0 > z1:
        z0, z1 = z1, z0
    half = width // 2
    x_start = x_center - half
    x_end = x_center + half

    for z in range(z0, z1 + 1):
        for x in range(x_start, x_end + 1):
            editor.placeBlock((x, y, z), block)


def connect_buildings_with_roads(
    editor: Editor,
    placed: List[PlacedBuilding],
    ground_y: int,
    road_width: int = 3,
    block_id: str = "minecraft:stone_bricks",
) -> None:
    """
    Build an MST-ish graph over building front points, carve L-shaped roads.
    """
    n = len(placed)
    if n <= 1:
        return

    road_block = Block(block_id)

    # Use building closest to area center as root.
    xs = [pb.front[0] for pb in placed]
    zs = [pb.front[1] for pb in placed]
    center_x = sum(xs) / n
    center_z = sum(zs) / n

    root_idx = min(
        range(n),
        key=lambda i: (placed[i].front[0] - center_x) ** 2 + (placed[i].front[1] - center_z) ** 2,
    )

    connected = {root_idx}
    remaining = set(range(n)) - connected

    print(f"[roads] root building index = {root_idx}")

    while remaining:
        best_pair = None
        best_dist2 = math.inf

        for i in connected:
            fx_i, fz_i = placed[i].front
            for j in remaining:
                fx_j, fz_j = placed[j].front
                dx = fx_i - fx_j
                dz = fz_i - fz_j
                d2 = dx * dx + dz * dz
                if d2 < best_dist2:
                    best_dist2 = d2
                    best_pair = (i, j)

        if best_pair is None:
            break

        i, j = best_pair
        connected.add(j)
        remaining.remove(j)

        fx_i, fz_i = placed[i].front
        fx_j, fz_j = placed[j].front

        print(f"[roads] connect {i} -> {j} via ({fx_i},{fz_i}) -> ({fx_j},{fz_j})")

        # L-shape: horizontal then vertical (you can randomize order if you like)
        carve_road_segment_x(
            editor,
            x0=fx_i,
            x1=fx_j,
            z_center=fz_i,
            width=road_width,
            y=ground_y,
            block=road_block,
        )

        carve_road_segment_z(
            editor,
            z0=fz_i,
            z1=fz_j,
            x_center=fx_j,
            width=road_width,
            y=ground_y,
            block=road_block,
        )


# ---------------------------------------------------------------------------
# Debug marker
# ---------------------------------------------------------------------------

def place_debug_marker(editor: Editor, x: int, y: int, z: int) -> None:
    for dy in range(0, 20):
        editor.placeBlock((x, y + dy, z), Block("minecraft:gold_block"))
    print(f"[debug] marker pillar at ({x}, {y}, {z})")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    editor = Editor(buffering=True)

    # Define an area in which to scatter buildings and roads
    build_area = editor.getBuildArea()
    print(f"[info] buildArea: X=[{build_area.begin.x},{build_area.end.x}), "
          f"Y=[{build_area.begin.y},{build_area.end.y}), "
          f"Z=[{build_area.begin.z},{build_area.end.z})")

    # Slightly inset from the build area to avoid edges
    area_x0 = build_area.begin.x + 5
    area_x1 = build_area.end.x - 6
    area_z0 = build_area.begin.z + 5
    area_z1 = build_area.end.z - 6

    # Ground detection near one corner
    ground_y = detect_ground_y(
        editor,
        x=area_x0,
        z=area_z0,
        y_min=build_area.begin.y,
        y_max=build_area.end.y - 1,
    )

    print(f"[info] using area: X=[{area_x0},{area_x1}], Z=[{area_z0},{area_z1}], ground_y={ground_y}")
    place_debug_marker(editor, area_x0, ground_y, area_z0)

    # Load blueprints, filter by area size
    all_bps = load_blueprints()
    max_size_x = area_x1 - area_x0 + 1
    max_size_z = area_z1 - area_z0 + 1
    bps_filtered = filter_blueprints_by_max_size(all_bps, max_size_x, max_size_z)
    print(f"[info] {len(bps_filtered)} blueprints fit into this area")

    # 1) Scatter buildings organically
    placed = scatter_buildings(
        editor,
        bps_filtered,
        area_x0=area_x0,
        area_x1=area_x1,
        area_z0=area_z0,
        area_z1=area_z1,
        ground_y=ground_y,
        max_buildings=MAX_BUILDINGS,
        max_attempts=2000,
    )

    # 2) Connect their front directions with roads
    connect_buildings_with_roads(
        editor,
        placed=placed,
        ground_y=ground_y,
        road_width=3,
        block_id="minecraft:stone_bricks",
    )

    editor.flushBuffer()
    print("[done] organic district generated")


if __name__ == "__main__":
    main()
