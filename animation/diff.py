"""
Blueprint diff computation for multi-stage animation.

Compares two blueprint block lists (same coordinate space) and produces:
  - ``removed``:  blocks present in ``before`` but absent in ``after``.
  - ``added``:    blocks present in ``after`` but absent in ``before``.
  - ``mutated``:  blocks at the same position whose ``id`` changed.

This powers the erosion overlay animation: build the original, then animate
only the *changes* introduced by erosion (removals shown as air placement,
mutations shown as block replacements).
"""

from __future__ import annotations

from typing import Any


def _blocks_to_grid(
    blocks: list[dict[str, Any]],
) -> dict[tuple[int, int, int], dict[str, Any]]:
    """Index a block list by (dx, dy, dz) for O(1) lookup."""
    grid: dict[tuple[int, int, int], dict[str, Any]] = {}
    for b in blocks:
        pos = (b["dx"], b["dy"], b["dz"])
        grid[pos] = b
    return grid


def diff_blueprints(
    before_blocks: list[dict[str, Any]],
    after_blocks: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Compute the block-level diff between two blueprint states.

    Both inputs are lists of ``{dx, dy, dz, id, props}`` dicts in the same
    coordinate space (relative blueprint coordinates).

    Returns a dict with three keys:
      - ``removed``:  blocks in ``before`` not present in ``after``.
      - ``added``:    blocks in ``after`` not present in ``before``.
      - ``mutated``:  blocks at the same position with a different ``id`` in
                      ``after``.  Each entry has the *after* state.
    """
    grid_before = _blocks_to_grid(before_blocks)
    grid_after = _blocks_to_grid(after_blocks)

    removed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    mutated: list[dict[str, Any]] = []

    # Blocks in before but not in after → removed
    for pos, b in grid_before.items():
        if pos not in grid_after:
            removed.append(b)
        elif grid_after[pos]["id"] != b["id"]:
            mutated.append(grid_after[pos])

    # Blocks in after but not in before → added
    for pos, b in grid_after.items():
        if pos not in grid_before:
            added.append(b)

    return {
        "removed": removed,
        "added": added,
        "mutated": mutated,
    }


def diff_as_placement_sequence(
    before_blocks: list[dict[str, Any]],
    after_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Convert a blueprint diff into a flat block list suitable for the animation
    strategy system.

    Removed blocks become ``minecraft:air`` placements.
    Mutated blocks become their new ``id``.
    Added blocks are included as-is.

    The returned list can be fed directly into ``get_strategy_generator()``
    for animated placement of the erosion overlay.
    """
    diff = diff_blueprints(before_blocks, after_blocks)

    sequence: list[dict[str, Any]] = []

    # Removals → air
    for b in diff["removed"]:
        sequence.append(
            {
                "dx": b["dx"],
                "dy": b["dy"],
                "dz": b["dz"],
                "id": "minecraft:air",
                "props": {},
            }
        )

    # Mutations → new block
    for b in diff["mutated"]:
        sequence.append(b)

    # Additions → new block
    for b in diff["added"]:
        sequence.append(b)

    return sequence
