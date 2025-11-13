from __future__ import annotations
from typing import Tuple, List, Dict, Any
import random

from gdpc import Editor
from gdpc.block import Block

from blueprint_db import iter_blueprints, place_blueprint

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
    # add whatever else
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

    1) Scan from y_max downward for the highest block whose id is in GROUND_CANDIDATES.
    2) If none, scan downward for the highest non-air block.
    3) If *still* none, return y_min.
    """

    # Pass 1: “real surface” blocks
    for y in range(y_max, y_min - 1, -1):
        blk = editor.getBlock((x, y, z))
        bid = blk.id
        if bid in GROUND_CANDIDATES:
            return y

    # Pass 2: any non-air (fallback)
    for y in range(y_max, y_min - 1, -1):
        blk = editor.getBlock((x, y, z))
        if blk.id != "minecraft:air":
            return y

    # Absolute worst case
    return y_min
# ---------------------------------------------------------------------------
# Blueprint selection helpers
# ---------------------------------------------------------------------------

def load_blueprints() -> List[Tuple[str, Dict[str, Any], list]]:
    """Load all blueprints into a list for easy selection."""
    bps = list(iter_blueprints(BP_DIR))
    if not bps:
        raise RuntimeError("No blueprints found in BLUEPRINTS.")
    return bps


def filter_blueprints_for_width(
    blueprints: List[Tuple[str, Dict[str, Any], list]],
    max_size_x: int,
) -> List[Tuple[str, Dict[str, Any], list]]:
    """
    Filter blueprints only by X footprint.
    Z depth is ignored; buildings are allowed to stick out behind the plot.
    """
    out: List[Tuple[str, Dict[str, Any], list]] = []
    for bp_id, meta, blocks in blueprints:
        size_x, size_y, size_z = meta["size"]
        if size_x <= max_size_x:
            out.append((bp_id, meta, blocks))
    return out


class BlueprintSelector:
    """
    Stateful, round-robin blueprint selector.

    - Keeps a circular index over the candidate list.
    - For each call, tries up to N candidates to find one that fits remaining width.
    - Ensures all blueprints get chances over time.
    """

    def __init__(self, candidates: List[Tuple[str, Dict[str, Any], list]]) -> None:
        # Optional: shuffle so the starting order isn't deterministic
        random.shuffle(candidates)

        # Optional but useful: sort by width descending so big buildings
        # get earlier opportunities to fit.
        candidates.sort(key=lambda bp: bp[1]["size"][0], reverse=True)

        self._candidates: List[Tuple[str, Dict[str, Any], list]] = candidates
        self._idx: int = 0

    def pick(self, max_size_x: int) -> Tuple[str, Dict[str, Any], list] | None:
        if not self._candidates:
            return None

        n = len(self._candidates)
        tried = 0

        # Try at most N distinct blueprints per call
        while tried < n:
            bp_id, meta, blocks = self._candidates[self._idx]
            self._idx = (self._idx + 1) % n
            tried += 1

            size_x, size_y, size_z = meta["size"]
            if size_x <= max_size_x:
                return bp_id, meta, blocks

        # Nothing fits the remaining width
        return None


# ---------------------------------------------------------------------------
# Road carving
# ---------------------------------------------------------------------------

def carve_road(
    editor: Editor,
    x0: int,
    x1: int,
    z_center: int,
    width: int,
    y: int,
    block_id: str = "minecraft:stone_bricks",
) -> None:
    """Carve a straight road segment along X."""
    if width <= 0:
        return

    if x0 > x1:
        x0, x1 = x1, x0

    half = width // 2
    z_start = z_center - half
    z_end = z_center + half

    block = Block(block_id)

    for x in range(x0, x1 + 1):
        for z in range(z_start, z_end + 1):
            editor.placeBlock((x, y, z), block)


# ---------------------------------------------------------------------------
# Row filling along +Z of a given road
# ---------------------------------------------------------------------------

def fill_building_row(
    editor: Editor,
    selector: BlueprintSelector,
    row_x0: int,
    row_x1: int,
    front_z: int,
    ground_y: int,
    gap_x: int,
) -> None:
    if row_x0 > row_x1:
        row_x0, row_x1 = row_x1, row_x0

    x = row_x0
    max_x = row_x1

    while x <= max_x:
        remaining = max_x - x + 1
        choice = selector.pick(remaining)
        if choice is None:
            break

        bp_id, meta, blocks = choice
        size_x, size_y, size_z = meta["size"]

        origin_x = x
        origin_y = ground_y
        origin_z = front_z

        place_blueprint(editor, (origin_x, origin_y, origin_z), blocks)
        print(f"[row] placed {bp_id} at ({origin_x}, {origin_y}, {origin_z}), size={meta['size']}")

        x += size_x + gap_x




# ---------------------------------------------------------------------------
# 2D district generation
# ---------------------------------------------------------------------------
def generate_grid_district(
    editor: Editor,
    area_x0: int,
    area_x1: int,
    area_z0: int,
    area_z1: int,
    ground_y: int,
    road_width: int = 3,
    plot_depth: int = 16,       # now: just spacing, not a hard constraint
    road_spacing: int | None = None,
    building_gap_x: int = 2,
) -> None:
    if area_x0 > area_x1:
        area_x0, area_x1 = area_x1, area_x0
    if area_z0 > area_z1:
        area_z0, area_z1 = area_z1, area_z0

    if road_spacing is None:
        road_spacing = road_width + plot_depth

    all_bps = load_blueprints()

    # Only filter by width in X
    bps_for_plot = filter_blueprints_for_width(
        all_bps,
        max_size_x=(area_x1 - area_x0 + 1),
    )
    if not bps_for_plot:
        raise RuntimeError("No blueprints fit the requested width.")

    print(f"[district] using {len(bps_for_plot)} blueprints (width-filtered only)")

    selector = BlueprintSelector(bps_for_plot)

    road_half = road_width // 2

    # Only ensure the *road* is inside the area; ignore building depth.
    z_min = area_z0 + road_half
    z_max = area_z1 - road_half

    if z_min > z_max:
        print("[district] no space for roads in given Z range")
        return

    z = z_min
    while z <= z_max:
        # Carve the road
        carve_road(editor, area_x0, area_x1, z_center=z, width=road_width, y=ground_y)
        print(f"[district] carved road at z={z}")

        # Buildings go on +Z side
        front_z = z + road_half + 1

        fill_building_row(
            editor,
            selector=selector,
            row_x0=area_x0,
            row_x1=area_x1,
            front_z=front_z,
            ground_y=ground_y,
            gap_x=building_gap_x,
        )

        z += road_spacing




# ---------------------------------------------------------------------------
# Debug markers
# ---------------------------------------------------------------------------

def place_debug_marker(editor: Editor, x: int, y: int, z: int) -> None:
    """Place a tall pillar to help you find the generated area."""
    for dy in range(0, 20):
        editor.placeBlock((x, y + dy, z), Block("minecraft:gold_block"))
    print(f"[debug] marker pillar at ({x}, {y}, {z})")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    editor = Editor(buffering=True)

    # Hard-coded debug area (adjust as you like)
    area_x0 = -300
    area_x1 = 300
    area_z0 = -300
    area_z1 = 300

    # For your superflat debug: ground is basically -61/-62.
    ground_y = detect_ground_y(
        editor,
        x=area_x0,
        z=area_z0,
        y_min=-64,
        y_max=300,
    )

    generate_grid_district(
        editor,
        area_x0=area_x0,
        area_x1=area_x1,
        area_z0=area_z0,
        area_z1=area_z1,
        ground_y=ground_y,
        road_width=3,
        plot_depth=16,     # just spacing now
        road_spacing=None, # => road_width + plot_depth
        building_gap_x=2,
    )

    editor.flushBuffer()
    print("[done] grid district generated")



if __name__ == "__main__":
    main()