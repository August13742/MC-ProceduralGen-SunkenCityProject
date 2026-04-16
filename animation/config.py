"""
Configuration schema for the animation system.

Loads a TOML file into a validated dataclass.  All timing values are in
milliseconds.  Strategy names map to generator functions in strategies.py.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Strategy(str, Enum):
    """Block ordering strategy for construction animation."""

    Y_UP = "y_up"
    Y_DOWN = "y_down"
    RADIAL_OUT = "radial_out"
    RANDOM = "random"
    STRUCTURAL_PHASES = "structural_phases"


class SourceFormat(str, Enum):
    """Input block data format."""

    BLUEPRINT_JSON = "blueprint_json"
    VPS_PREFAB = "vps_prefab"
    RAW_BLOCK_ARRAY = "raw_block_array"


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnimationConfig:
    """Immutable configuration for a single animation run."""

    # --- Source ---
    source_file: str
    source_format: SourceFormat = SourceFormat.BLUEPRINT_JSON

    # --- Placement target ---
    origin_x: int = 0
    origin_y: int = 64
    origin_z: int = 0
    gdmc_host: str = "localhost:9000"

    # --- Strategy ---
    strategy: Strategy = Strategy.Y_UP

    # --- Timing (milliseconds) ---
    per_block_delay_ms: int = 0
    per_layer_delay_ms: int = 200
    flush_every_n_blocks: int = 64

    # --- Pre-animation ---
    clear_area_first: bool = True

    # --- Preview renderer ---
    preview_enabled: bool = False
    preview_output_dir: str = "frames"
    preview_view: str = "iso_right"
    preview_width: int = 512
    preview_height: int = 512
    preview_bg_colour: tuple[int, int, int] = (30, 30, 30)
    preview_output_format: str = "gif"  # "gif", "mp4", or "png"
    preview_fps: int = 10
    preview_hold_last_frames: int = 15  # Extra copies of last frame to pause at end

    # --- Player tracking ---
    use_player_tracking: bool = False  # Auto-detect origin from player position

    # --- Structural phases config (only used when strategy == STRUCTURAL_PHASES) ---
    foundation_ids: tuple[str, ...] = (
        "minecraft:stone",
        "minecraft:cobblestone",
        "minecraft:deepslate_bricks",
        "minecraft:stone_bricks",
        "minecraft:mossy_stone_bricks",
        "minecraft:cracked_stone_bricks",
        "minecraft:smooth_stone",
        "minecraft:bricks",
        "minecraft:dirt",
        "minecraft:gravel",
        "minecraft:grass_block",
    )
    roof_ids: tuple[str, ...] = (
        "minecraft:dark_oak_stairs",
        "minecraft:oak_stairs",
        "minecraft:spruce_stairs",
        "minecraft:birch_stairs",
        "minecraft:cobblestone_stairs",
        "minecraft:stone_brick_stairs",
        "minecraft:brick_stairs",
        "minecraft:dark_oak_slab",
        "minecraft:oak_slab",
        "minecraft:spruce_slab",
        "minecraft:cobblestone_slab",
        "minecraft:stone_brick_slab",
    )
    interior_ids: tuple[str, ...] = (
        "minecraft:torch",
        "minecraft:wall_torch",
        "minecraft:lantern",
        "minecraft:chest",
        "minecraft:crafting_table",
        "minecraft:furnace",
        "minecraft:bookshelf",
        "minecraft:red_bed",
        "minecraft:flower_pot",
        "minecraft:anvil",
        "minecraft:white_carpet",
        "minecraft:red_wool",
    )


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _coerce_tuple(val: Any) -> tuple[str, ...]:
    if isinstance(val, (list, tuple)):
        return tuple(str(v) for v in val)
    return ()


def load_config(path: str | Path) -> AnimationConfig:
    """
    Parse a TOML file into an AnimationConfig.

    Unknown keys are silently ignored — forward-compatible with future
    schema extensions.
    """
    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)

    # Flatten sections: [source], [placement], [timing], [strategy], [preview], [structural]
    flat: dict[str, Any] = {}

    for section_key in (
        "source",
        "placement",
        "timing",
        "strategy",
        "preview",
        "structural",
    ):
        if section_key in raw:
            flat.update(raw[section_key])

    # Top-level overrides (non-section keys)
    for k, v in raw.items():
        if not isinstance(v, dict):
            flat[k] = v

    # Map string enums
    if "strategy" in flat:
        flat["strategy"] = Strategy(flat["strategy"])
    if "source_format" in flat:
        flat["source_format"] = SourceFormat(flat["source_format"])

    # Coerce tuples
    for tuple_key in ("foundation_ids", "roof_ids", "interior_ids"):
        if tuple_key in flat:
            flat[tuple_key] = _coerce_tuple(flat[tuple_key])

    # Coerce bg colour
    if "preview_bg_colour" in flat:
        c = flat["preview_bg_colour"]
        if isinstance(c, (list, tuple)) and len(c) == 3:
            flat["preview_bg_colour"] = (int(c[0]), int(c[1]), int(c[2]))

    # Filter to only known fields
    known = {f.name for f in AnimationConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in flat.items() if k in known}

    return AnimationConfig(**filtered)


def load_config_with_stages(
    path: str | Path,
) -> tuple["AnimationConfig", list]:
    """
    Parse a TOML file into an AnimationConfig *and* an optional stage list.

    Returns ``(config, stages)`` where ``stages`` may be empty (single-stage
    mode).  Import is deferred to avoid circular dependency.
    """
    from animation.stages import parse_stages_from_toml

    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)

    # Parse stages before flattening (they live at [[stages]])
    stages = parse_stages_from_toml(raw)

    # Reuse the normal loader for the config portion
    config = load_config(path)

    return config, stages
