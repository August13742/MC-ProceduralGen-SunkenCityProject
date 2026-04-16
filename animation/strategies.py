"""
Construction ordering strategies.

Each strategy is a generator function that receives a list of block dicts
(blueprint format: {dx, dy, dz, id, props}) and yields batches (lists of
block dicts).  Each yielded batch represents one "step" — all blocks in a
batch are placed simultaneously, then the inter-batch delay fires.

The consumer (placer or preview renderer) iterates the generator, applying
per-block and per-layer timing as configured.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Generator

# Type alias for a single block dict (blueprint_db format)
Block = dict[str, Any]
Batch = list[Block]
BatchGenerator = Generator[Batch, None, None]


# ---------------------------------------------------------------------------
# Y-Up: bottom layer to top layer
# ---------------------------------------------------------------------------


def y_up(blocks: list[Block]) -> BatchGenerator:
    """Yield blocks grouped by ascending Y coordinate (dy)."""
    by_y: dict[int, list[Block]] = defaultdict(list)
    for b in blocks:
        by_y[b["dy"]].append(b)

    for y_key in sorted(by_y.keys()):
        yield by_y[y_key]


# ---------------------------------------------------------------------------
# Y-Down: top layer to bottom layer (demolition / reveal style)
# ---------------------------------------------------------------------------


def y_down(blocks: list[Block]) -> BatchGenerator:
    """Yield blocks grouped by descending Y coordinate."""
    by_y: dict[int, list[Block]] = defaultdict(list)
    for b in blocks:
        by_y[b["dy"]].append(b)

    for y_key in sorted(by_y.keys(), reverse=True):
        yield by_y[y_key]


# ---------------------------------------------------------------------------
# Radial outward: expanding shells from centroid
# ---------------------------------------------------------------------------


def radial_out(blocks: list[Block], shells: int = 0) -> BatchGenerator:
    """
    Yield blocks in expanding distance shells from the XZ centroid.

    If `shells` is 0, the number of shells equals the max XZ extent.
    Blocks within each shell are unordered.
    """
    if not blocks:
        return

    cx = sum(b["dx"] for b in blocks) / len(blocks)
    cz = sum(b["dz"] for b in blocks) / len(blocks)

    # Compute max distance for shell sizing
    max_dist = 0.0
    dists: list[tuple[float, Block]] = []
    for b in blocks:
        d = math.sqrt((b["dx"] - cx) ** 2 + (b["dz"] - cz) ** 2)
        dists.append((d, b))
        if d > max_dist:
            max_dist = d

    if shells <= 0:
        shells = max(1, int(math.ceil(max_dist)))

    shell_width = (max_dist + 0.01) / shells

    shell_buckets: dict[int, list[Block]] = defaultdict(list)
    for d, b in dists:
        idx = min(int(d / shell_width), shells - 1)
        shell_buckets[idx].append(b)

    for i in range(shells):
        if i in shell_buckets:
            yield shell_buckets[i]


# ---------------------------------------------------------------------------
# Random: every block in random order, one at a time
# ---------------------------------------------------------------------------


def random_order(blocks: list[Block], batch_size: int = 1) -> BatchGenerator:
    """
    Yield blocks in random order.

    `batch_size` controls how many blocks per step.  Default 1 for maximum
    visual granularity; increase for faster animations.
    """
    shuffled = list(blocks)
    random.shuffle(shuffled)

    for i in range(0, len(shuffled), batch_size):
        yield shuffled[i : i + batch_size]


# ---------------------------------------------------------------------------
# Structural phases: foundation -> walls -> roof -> interior
# ---------------------------------------------------------------------------


def structural_phases(
    blocks: list[Block],
    foundation_ids: tuple[str, ...] = (),
    roof_ids: tuple[str, ...] = (),
    interior_ids: tuple[str, ...] = (),
) -> BatchGenerator:
    """
    Classify blocks into structural phases, then yield each phase
    layer-by-layer (Y-up within each phase).

    Phase order: foundation -> walls (everything else) -> roof -> interior.
    Within each phase, blocks are grouped by ascending Y.
    """
    foundation_set = frozenset(foundation_ids)
    roof_set = frozenset(roof_ids)
    interior_set = frozenset(interior_ids)

    phases: dict[str, list[Block]] = {
        "foundation": [],
        "walls": [],
        "roof": [],
        "interior": [],
    }

    for b in blocks:
        bid = b["id"]
        if bid in foundation_set:
            phases["foundation"].append(b)
        elif bid in interior_set:
            phases["interior"].append(b)
        elif bid in roof_set:
            phases["roof"].append(b)
        else:
            phases["walls"].append(b)

    for phase_name in ("foundation", "walls", "roof", "interior"):
        phase_blocks = phases[phase_name]
        if not phase_blocks:
            continue
        # Sub-sort by Y within each phase
        by_y: dict[int, list[Block]] = defaultdict(list)
        for b in phase_blocks:
            by_y[b["dy"]].append(b)
        for y_key in sorted(by_y.keys()):
            yield by_y[y_key]


# ---------------------------------------------------------------------------
# Strategy dispatcher
# ---------------------------------------------------------------------------

STRATEGY_MAP = {
    "y_up": y_up,
    "y_down": y_down,
    "radial_out": radial_out,
    "random": random_order,
    "structural_phases": structural_phases,
}


def get_strategy_generator(
    strategy_name: str,
    blocks: list[Block],
    **kwargs: Any,
) -> BatchGenerator:
    """
    Resolve a strategy name to a generator over the given blocks.

    Raises KeyError if the strategy name is not recognised.
    Additional keyword arguments are forwarded to the strategy function
    (e.g. foundation_ids for structural_phases).
    """
    if strategy_name not in STRATEGY_MAP:
        raise KeyError(
            f"Unknown strategy '{strategy_name}'. "
            f"Available: {sorted(STRATEGY_MAP.keys())}"
        )

    fn = STRATEGY_MAP[strategy_name]

    # Only pass kwargs the function accepts
    import inspect

    sig = inspect.signature(fn)
    accepted = set(sig.parameters.keys()) - {"blocks"}
    filtered_kwargs = {k: v for k, v in kwargs.items() if k in accepted}

    return fn(blocks, **filtered_kwargs)
