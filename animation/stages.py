"""
Multi-stage animation orchestrator.

A stage sequence describes a series of animation steps, each operating on a
different block set.  The canonical use case is:

  Stage 1 — ``build``:  Animate the original blueprint being constructed.
  Stage 2 — ``erode``:  Apply erosion, then animate only the *diff* (block
                        removals and mutations).

Each stage remembers the final state of the previous stage, so overlays
compose correctly.

Stage definitions live in the TOML config under ``[[stages]]`` array tables.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generator

from animation.config import AnimationConfig, Strategy
from animation.diff import diff_as_placement_sequence
from animation.placer import load_blocks
from animation.strategies import get_strategy_generator


# ---------------------------------------------------------------------------
# Stage descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Stage:
    """Description of a single animation stage."""

    name: str
    mode: str  # "build", "erode", "diff_overlay"
    strategy: str = "y_up"
    per_layer_delay_ms: int = 200
    per_block_delay_ms: int = 0

    # Erosion parameters (only for mode == "erode")
    erosion_seed: int = 1337
    erosion_aggression: float = 0.5
    erosion_passes: int = 3

    # For mode == "build", optionally override source file.
    source_file: str | None = None


# ---------------------------------------------------------------------------
# Stage execution helpers
# ---------------------------------------------------------------------------


def _load_blueprint_data(path: str | Path) -> dict[str, Any]:
    """Load raw blueprint JSON (blocks + meta)."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _filter_air(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [b for b in blocks if b["id"] != "minecraft:air"]


def resolve_stage_blocks(
    stage: Stage,
    config: AnimationConfig,
    previous_blocks: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Resolve the block list for a given stage.

    Returns ``(blocks_to_animate, resulting_state)`` where:
      - ``blocks_to_animate`` is the list to feed into the strategy generator.
      - ``resulting_state`` is the full block state after this stage completes
        (used as input to the next stage).
    """
    if stage.mode == "build":
        src = stage.source_file or config.source_file
        bp_data = _load_blueprint_data(src)
        blocks = _filter_air(bp_data["blocks"])
        return blocks, blocks

    elif stage.mode == "erode":
        if previous_blocks is None:
            raise ValueError(
                f"Stage '{stage.name}' (mode=erode) requires a preceding "
                f"stage to provide the 'before' state."
            )
        # Import erosion logic — lives in project root
        from erosion_logic import erode_blueprint

        # Reconstruct blueprint_data structure for erode_blueprint()
        bp_data = {
            "blocks": deepcopy(previous_blocks),
            "meta": {},
        }
        eroded = erode_blueprint(
            bp_data,
            seed=stage.erosion_seed,
            aggression=stage.erosion_aggression,
            passes=stage.erosion_passes,
        )
        after_blocks = _filter_air(eroded["blocks"])

        # Compute diff → only animate the changes
        diff_blocks = diff_as_placement_sequence(previous_blocks, after_blocks)
        return diff_blocks, after_blocks

    elif stage.mode == "diff_overlay":
        # Generic diff between previous state and a new source file.
        if previous_blocks is None:
            raise ValueError(
                f"Stage '{stage.name}' (mode=diff_overlay) requires a preceding stage."
            )
        src = stage.source_file or config.source_file
        bp_data = _load_blueprint_data(src)
        after_blocks = _filter_air(bp_data["blocks"])

        diff_blocks = diff_as_placement_sequence(previous_blocks, after_blocks)
        return diff_blocks, after_blocks

    else:
        raise ValueError(f"Unknown stage mode: '{stage.mode}'")


def iterate_stages(
    stages: list[Stage],
    config: AnimationConfig,
) -> Generator[tuple[Stage, list[dict[str, Any]]], None, None]:
    """
    Yield ``(stage, blocks_to_animate)`` for each stage in sequence.

    Maintains the running block state across stages.
    """
    current_state: list[dict[str, Any]] | None = None

    for stage in stages:
        blocks, current_state = resolve_stage_blocks(stage, config, current_state)
        yield stage, blocks


# ---------------------------------------------------------------------------
# TOML parsing
# ---------------------------------------------------------------------------


def parse_stages_from_toml(raw: dict[str, Any]) -> list[Stage]:
    """
    Parse ``[[stages]]`` array from raw TOML dict.

    Falls back to a single implicit ``build`` stage if no stages are defined.
    """
    raw_stages = raw.get("stages", [])

    if not raw_stages:
        return []  # Caller should fall back to single-stage mode

    stages: list[Stage] = []
    for i, s in enumerate(raw_stages):
        stages.append(
            Stage(
                name=s.get("name", f"stage_{i}"),
                mode=s.get("mode", "build"),
                strategy=s.get("strategy", "y_up"),
                per_layer_delay_ms=s.get("per_layer_delay_ms", 200),
                per_block_delay_ms=s.get("per_block_delay_ms", 0),
                erosion_seed=s.get("erosion_seed", 1337),
                erosion_aggression=s.get("erosion_aggression", 0.5),
                erosion_passes=s.get("erosion_passes", 3),
                source_file=s.get("source_file"),
            )
        )

    return stages
