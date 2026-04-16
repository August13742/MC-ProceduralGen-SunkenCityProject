"""
GDMC Live Placement Engine.

Connects to a running GDMC HTTP server via gdpc and places blocks
incrementally according to a strategy generator, with configurable
inter-block and inter-batch delays.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from animation.config import AnimationConfig, Strategy
from animation.strategies import get_strategy_generator


# ---------------------------------------------------------------------------
# Block loading
# ---------------------------------------------------------------------------


def load_blocks_from_blueprint_json(path: str | Path) -> list[dict[str, Any]]:
    """
    Load block list from a blueprint JSON file (blueprint_db format).

    Returns list of dicts: {dx, dy, dz, id, props}.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    blocks: list[dict[str, Any]] = data["blocks"]

    # Filter air
    return [b for b in blocks if b["id"] != "minecraft:air"]


def load_blocks(config: AnimationConfig) -> list[dict[str, Any]]:
    """Load blocks according to the configured source format."""
    if config.source_format.value == "blueprint_json":
        return load_blocks_from_blueprint_json(config.source_file)
    else:
        # Extensibility point for VPS prefab / raw arrays
        raise NotImplementedError(
            f"Source format '{config.source_format.value}' not yet implemented."
        )


# ---------------------------------------------------------------------------
# Area clearing
# ---------------------------------------------------------------------------


def compute_bounding_box(
    blocks: list[dict[str, Any]],
) -> tuple[int, int, int, int, int, int]:
    """Return (min_dx, min_dy, min_dz, max_dx, max_dy, max_dz)."""
    xs = [b["dx"] for b in blocks]
    ys = [b["dy"] for b in blocks]
    zs = [b["dz"] for b in blocks]
    return min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)


def clear_area(
    editor: Any,
    blocks: list[dict[str, Any]],
    origin: tuple[int, int, int],
) -> None:
    """Fill the bounding box with air before animation starts."""
    from gdpc.block import Block

    min_dx, min_dy, min_dz, max_dx, max_dy, max_dz = compute_bounding_box(blocks)
    ox, oy, oz = origin

    air = Block("minecraft:air")
    for dx in range(min_dx, max_dx + 1):
        for dy in range(min_dy, max_dy + 1):
            for dz in range(min_dz, max_dz + 1):
                editor.placeBlock((ox + dx, oy + dy, oz + dz), air)

    editor.flushBuffer()
    print(
        f"[clear] Cleared area: "
        f"({ox + min_dx},{oy + min_dy},{oz + min_dz}) to "
        f"({ox + max_dx},{oy + max_dy},{oz + max_dz})"
    )


# ---------------------------------------------------------------------------
# Core placement loop (single block list)
# ---------------------------------------------------------------------------


def _place_block_list(
    editor: Any,
    blocks: list[dict[str, Any]],
    origin: tuple[int, int, int],
    strategy_name: str,
    per_block_delay_ms: int = 0,
    per_layer_delay_ms: int = 200,
    flush_every: int = 64,
    strategy_kwargs: dict[str, Any] | None = None,
    label: str = "",
) -> int:
    """
    Place a block list using a strategy generator with configured delays.

    Returns the number of blocks placed.
    """
    from gdpc.block import Block

    if not blocks:
        return 0

    gen = get_strategy_generator(strategy_name, blocks, **(strategy_kwargs or {}))

    ox, oy, oz = origin
    per_block_s = per_block_delay_ms / 1000.0
    per_layer_s = per_layer_delay_ms / 1000.0
    prefix = f"[{label}] " if label else ""

    total_placed = 0
    batch_index = 0

    for batch in gen:
        batch_index += 1

        for i, b in enumerate(batch):
            block_id = b["id"]
            props = b.get("props", {})
            dx, dy, dz = b["dx"], b["dy"], b["dz"]
            editor.placeBlock(
                (ox + dx, oy + dy, oz + dz),
                Block(block_id, props),
            )
            total_placed += 1

            if total_placed % flush_every == 0:
                editor.flushBuffer()

            if per_block_s > 0 and i < len(batch) - 1:
                editor.flushBuffer()
                time.sleep(per_block_s)

        editor.flushBuffer()

        if per_layer_s > 0:
            time.sleep(per_layer_s)

        if batch_index % 5 == 0 or batch_index <= 3:
            print(
                f"  {prefix}batch {batch_index}: "
                f"+{len(batch)} blocks (total: {total_placed})"
            )

    editor.flushBuffer()
    print(f"  {prefix}Complete. {total_placed} blocks in {batch_index} batches.")
    return total_placed


# ---------------------------------------------------------------------------
# Origin resolution
# ---------------------------------------------------------------------------


def _resolve_origin(config: AnimationConfig) -> tuple[int, int, int]:
    """Resolve placement origin from config or player tracking."""
    ox, oy, oz = config.origin_x, config.origin_y, config.origin_z

    if config.use_player_tracking:
        from animation.player_tracking import poll_player_position

        px, py, pz = poll_player_position(
            host=config.gdmc_host,
            max_attempts=10,
            poll_interval_s=1.0,
        )
        ox, oy, oz = px, py, pz
        print(f"[animate] Origin from player: ({ox}, {oy}, {oz})")
    else:
        print(f"[animate] Origin from config: ({ox}, {oy}, {oz})")

    return ox, oy, oz


# ---------------------------------------------------------------------------
# Single-stage animation (backward compatible)
# ---------------------------------------------------------------------------


def run_animation(config: AnimationConfig) -> None:
    """
    Execute a construction animation against a live GDMC server.

    Single-stage mode: loads blocks from the configured source and places
    them using the configured strategy.
    """
    from gdpc import Editor

    blocks = load_blocks(config)
    if not blocks:
        print("[animate] No blocks to place.")
        return

    print(f"[animate] Loaded {len(blocks)} blocks from {config.source_file}")
    print(f"[animate] Strategy: {config.strategy.value}")

    origin = _resolve_origin(config)
    editor = Editor(buffering=True, host=config.gdmc_host)

    if config.clear_area_first:
        clear_area(editor, blocks, origin)

    strategy_kwargs: dict[str, Any] = {}
    if config.strategy == Strategy.STRUCTURAL_PHASES:
        strategy_kwargs["foundation_ids"] = config.foundation_ids
        strategy_kwargs["roof_ids"] = config.roof_ids
        strategy_kwargs["interior_ids"] = config.interior_ids

    _place_block_list(
        editor=editor,
        blocks=blocks,
        origin=origin,
        strategy_name=config.strategy.value,
        per_block_delay_ms=config.per_block_delay_ms,
        per_layer_delay_ms=config.per_layer_delay_ms,
        flush_every=config.flush_every_n_blocks,
        strategy_kwargs=strategy_kwargs,
        label="animate",
    )


# ---------------------------------------------------------------------------
# Multi-stage animation
# ---------------------------------------------------------------------------


def run_multistage_animation(
    config: AnimationConfig,
    stages: list,
) -> None:
    """
    Execute a multi-stage construction animation.

    Each stage builds on the result of the previous one.  For example:
      Stage 1 (build):  Construct the original blueprint.
      Stage 2 (erode):  Erode it, then animate only the changes.
    """
    from gdpc import Editor
    from animation.stages import Stage, iterate_stages

    origin = _resolve_origin(config)
    editor = Editor(buffering=True, host=config.gdmc_host)

    # Clear once before all stages (using the first stage's blocks
    # would require resolving it twice — just clear the full area from
    # the source blueprint).
    if config.clear_area_first:
        first_blocks = load_blocks(config)
        if first_blocks:
            clear_area(editor, first_blocks, origin)

    total_all = 0

    for i, (stage, blocks) in enumerate(iterate_stages(stages, config)):
        print(
            f"\n[stage {i + 1}/{len(stages)}] "
            f"'{stage.name}' (mode={stage.mode}, "
            f"strategy={stage.strategy}, {len(blocks)} blocks)"
        )

        placed = _place_block_list(
            editor=editor,
            blocks=blocks,
            origin=origin,
            strategy_name=stage.strategy,
            per_block_delay_ms=stage.per_block_delay_ms,
            per_layer_delay_ms=stage.per_layer_delay_ms,
            flush_every=config.flush_every_n_blocks,
            label=stage.name,
        )
        total_all += placed

    print(f"\n[animate] All stages complete. {total_all} blocks placed total.")
