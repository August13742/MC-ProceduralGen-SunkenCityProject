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
from animation.controller import BuildLifecycleController, LifecycleAction
from animation.diff import diff_as_placement_sequence
from animation.session import SessionState, save_session, save_session_blocks
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
    clear_item_drops: bool = True,
) -> None:
    """Fill the bounding box with air without creating support-break drops."""
    from gdpc.block import Block

    min_dx, min_dy, min_dz, max_dx, max_dy, max_dz = compute_bounding_box(blocks)
    ox, oy, oz = origin

    editor.doBlockUpdates = False
    editor.spawnDrops = False

    air = Block("minecraft:air")
    for dx in range(min_dx, max_dx + 1):
        for dy in range(min_dy, max_dy + 1):
            for dz in range(min_dz, max_dz + 1):
                editor.placeBlock((ox + dx, oy + dy, oz + dz), air)

    editor.flushBuffer()
    editor.doBlockUpdates = True

    if clear_item_drops:
        _clear_item_entities_in_box(
            editor,
            (ox + min_dx, oy + min_dy, oz + min_dz),
            (ox + max_dx, oy + max_dy, oz + max_dz),
        )

    print(
        f"[clear] Cleared area: "
        f"({ox + min_dx},{oy + min_dy},{oz + min_dz}) to "
        f"({ox + max_dx},{oy + max_dy},{oz + max_dz})"
    )


def _clear_item_entities_in_box(
    editor: Any,
    min_pos: tuple[int, int, int],
    max_pos: tuple[int, int, int],
) -> None:
    """Remove dropped item entities from a cleared build volume."""
    min_x, min_y, min_z = min_pos
    max_x, max_y, max_z = max_pos
    from gdpc import interface

    result = interface.runCommand(
        "kill @e[type=item,"
        f"x={min_x},y={min_y},z={min_z},"
        f"dx={max_x - min_x},dy={max_y - min_y},dz={max_z - min_z}]",
        host=str(editor.host),
    )
    if not result:
        return
    success, message = result[0]
    if success:
        return
    if "No entity was found" in str(message):
        return
    print(f"[clear] Item purge failed: {message}")


# ---------------------------------------------------------------------------
# Session persistence
# ---------------------------------------------------------------------------


def _persist_session(
    config: AnimationConfig,
    config_path: str,
    origin: tuple[int, int, int],
    blocks: list[dict[str, Any]],
    stages_count: int = 0,
) -> None:
    """Write session state to disk after a successful placement run."""
    bbox = compute_bounding_box(blocks) if blocks else (0, 0, 0, 0, 0, 0)
    state = SessionState(
        origin_x=origin[0],
        origin_y=origin[1],
        origin_z=origin[2],
        config_path=config_path,
        source_file=config.source_file,
        bbox_min_dx=bbox[0],
        bbox_min_dy=bbox[1],
        bbox_min_dz=bbox[2],
        bbox_max_dx=bbox[3],
        bbox_max_dy=bbox[4],
        bbox_max_dz=bbox[5],
        block_count=len(blocks),
        stages_count=stages_count,
        gdmc_host=config.gdmc_host,
    )
    p = save_session(state)
    save_session_blocks(blocks, state.state_file)
    print(f"[session] Saved to {p}")


def clear_from_session(session: "SessionState") -> None:
    """
    Clear the bounding-box area recorded in a previous session.

    Connects to the GDMC server specified in the session and fills
    the entire bounding box with air.
    """
    from gdpc import Editor
    from gdpc.block import Block

    editor = Editor(buffering=True, host=session.gdmc_host)
    ox, oy, oz = session.origin_x, session.origin_y, session.origin_z
    min_pos = (
        ox + session.bbox_min_dx,
        oy + session.bbox_min_dy,
        oz + session.bbox_min_dz,
    )
    max_pos = (
        ox + session.bbox_max_dx,
        oy + session.bbox_max_dy,
        oz + session.bbox_max_dz,
    )

    editor.doBlockUpdates = False
    editor.spawnDrops = False
    air = Block("minecraft:air")

    for dx in range(session.bbox_min_dx, session.bbox_max_dx + 1):
        for dy in range(session.bbox_min_dy, session.bbox_max_dy + 1):
            for dz in range(session.bbox_min_dz, session.bbox_max_dz + 1):
                editor.placeBlock((ox + dx, oy + dy, oz + dz), air)

    editor.flushBuffer()
    editor.doBlockUpdates = True
    _clear_item_entities_in_box(editor, min_pos, max_pos)
    print(
        f"[clear] Cleared area: "
        f"({min_pos[0]},{min_pos[1]},{min_pos[2]}) to "
        f"({max_pos[0]},{max_pos[1]},{max_pos[2]})"
    )


def try_load_session_origin(config_path: str) -> tuple[int, int, int] | None:
    """Return the last resolved origin for this config if one exists."""
    from animation.session import load_session

    try:
        session = load_session()
    except FileNotFoundError:
        return None

    if session.config_path != config_path:
        return None
    return session.origin_x, session.origin_y, session.origin_z


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
        from animation.player_tracking import poll_player_pose

        pose = poll_player_pose(
            host=config.gdmc_host,
            max_attempts=10,
            poll_interval_s=1.0,
        )
        ox, oy, oz = pose.x, pose.y, pose.z
        print(f"[animate] Origin from player: ({ox}, {oy}, {oz})")
    else:
        print(f"[animate] Origin from config: ({ox}, {oy}, {oz})")

    return ox, oy, oz


def resolve_origin_for_run(
    config: AnimationConfig,
    blocks: list[dict[str, Any]],
    config_path: str,
    force_new_origin: bool = False,
) -> tuple[int, int, int]:
    """
    Resolve a sticky placement origin.

    If a previous session exists for the same config, reuse it by default so the
    build stays anchored between runs. `clear` removes that sticky origin by
    deleting the session file.
    """
    if not force_new_origin:
        remembered = try_load_session_origin(config_path)
        if remembered is not None:
            print(
                f"[animate] Reusing stored origin from session: "
                f"({remembered[0]}, {remembered[1]}, {remembered[2]})"
            )
            return remembered

    if config.use_player_tracking:
        from animation.player_tracking import resolve_player_spawn_origin

        return resolve_player_spawn_origin(
            host=config.gdmc_host,
            blocks=blocks,
            clearance_blocks=config.player_clearance_blocks,
            margin_blocks=config.player_spawn_margin_blocks,
            use_ground_raycast=config.use_ground_raycast,
        )

    return _resolve_origin(config)


# ---------------------------------------------------------------------------
# Single-stage animation (backward compatible)
# ---------------------------------------------------------------------------


def run_animation(config: AnimationConfig, config_path: str = "") -> None:
    """
    Execute a construction animation against a live GDMC server.

    Single-stage mode: loads blocks from the configured source and places
    them using the configured strategy.  Persists session state on completion.
    """
    from gdpc import Editor

    blocks = load_blocks(config)
    if not blocks:
        print("[animate] No blocks to place.")
        return

    print(f"[animate] Loaded {len(blocks)} blocks from {config.source_file}")
    print(f"[animate] Strategy: {config.strategy.value}")

    origin = resolve_origin_for_run(config, blocks, config_path)
    editor = Editor(buffering=True, host=config.gdmc_host)

    if config.clear_area_first:
        clear_area(
            editor,
            blocks,
            origin,
            clear_item_drops=config.clear_item_drops_first,
        )

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

    _persist_session(config, config_path, origin, blocks, stages_count=0)


# ---------------------------------------------------------------------------
# Multi-stage animation
# ---------------------------------------------------------------------------


def run_multistage_animation(
    config: AnimationConfig,
    stages: list,
    config_path: str = "",
) -> None:
    """
    Execute a multi-stage construction animation.

    Each stage builds on the result of the previous one.  For example:
      Stage 1 (build):  Construct the original blueprint.
      Stage 2 (erode):  Erode it, then animate only the changes.
    """
    from gdpc import Editor
    from animation.stages import Stage, iterate_stages

    first_blocks = load_blocks(config)
    origin = resolve_origin_for_run(config, first_blocks, config_path)
    editor = Editor(buffering=True, host=config.gdmc_host)

    # Clear once before all stages (using the first stage's blocks
    # would require resolving it twice — just clear the full area from
    # the source blueprint).
    if config.clear_area_first:
        if first_blocks:
            clear_area(
                editor,
                first_blocks,
                origin,
                clear_item_drops=config.clear_item_drops_first,
            )

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

    # Persist session using the first stage's blocks for bounding box
    first_blocks = load_blocks(config)
    _persist_session(
        config, config_path, origin, first_blocks, stages_count=len(stages)
    )


def run_modify_animation(
    config: AnimationConfig, stages: list, config_path: str = ""
) -> None:
    """
    Apply only modify/decay stages against the persisted session state.

    This is intended for upgrade-style experiments where the existing build is
    transformed in place rather than torn down and reconstructed.
    """
    from dataclasses import replace
    from gdpc import Editor
    from animation.session import load_session, load_session_blocks
    from animation.stages import iterate_stages, resolve_final_stage_state

    session = load_session()
    current_state = load_session_blocks(session.state_file)
    origin = (session.origin_x, session.origin_y, session.origin_z)
    editor = Editor(buffering=True, host=config.gdmc_host)
    filtered_stages = [stage for stage in stages if stage.mode != "build"]

    if not filtered_stages:
        target_source = config.modify_source_file or config.source_file
        target_config = replace(config, source_file=target_source)
        target_blocks = load_blocks(target_config)
        diff_blocks = diff_as_placement_sequence(current_state, target_blocks)
        if not diff_blocks:
            print(f"[modify] No changes detected against target: {target_source}")
            return

        print(
            f"[modify] Diffing current session state against target blueprint: "
            f"{target_source} ({len(diff_blocks)} block updates)"
        )
        _place_block_list(
            editor=editor,
            blocks=diff_blocks,
            origin=origin,
            strategy_name=config.strategy.value,
            per_block_delay_ms=config.per_block_delay_ms,
            per_layer_delay_ms=config.per_layer_delay_ms,
            flush_every=config.flush_every_n_blocks,
            label="modify",
        )
        _persist_session(
            config,
            config_path,
            origin,
            target_blocks,
            stages_count=0,
        )
        print("[modify] Target diff applied and session state updated.")
        return

    total_all = 0
    for i, (stage, blocks) in enumerate(
        iterate_stages(filtered_stages, config, initial_state=current_state)
    ):
        print(
            f"\n[modify {i + 1}/{len(filtered_stages)}] "
            f"'{stage.name}' (mode={stage.mode}, strategy={stage.strategy}, {len(blocks)} blocks)"
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

    final_state = resolve_final_stage_state(
        filtered_stages,
        config,
        initial_state=current_state,
    )
    _persist_session(
        config,
        config_path,
        origin,
        final_state,
        stages_count=len(filtered_stages),
    )
    print(
        f"\n[modify] All modify stages complete. {total_all} block updates placed total."
    )


def run_rebuild_loop(config: AnimationConfig, config_path: str = "") -> None:
    """
    Keep an in-game rebuild controller alive.

    The control loop is intentionally simple: trigger clear or rebuild from
    Minecraft, without needing to tab back to the shell.
    """
    controller = BuildLifecycleController(
        host=config.gdmc_host,
        objective=config.control_objective,
    )
    controller.setup()
    print("[animate] Waiting for in-game rebuild controls...")

    while True:
        action = controller.wait_for_action()
        if action.kind == "clear":
            from animation.session import delete_session_bundle, load_session

            try:
                session = load_session()
            except FileNotFoundError:
                print("[control] No session available to clear.")
                continue
            clear_from_session(session)
            delete_session_bundle()
            print("[control] Cleared build and forgot sticky origin.")
            continue

        if action.kind == "rebuild":
            from animation.config import load_config_with_stages

            rebuild_config_path = config_path
            if not rebuild_config_path:
                print("[control] No stored config path available for rebuild.")
                continue

            loaded_config, stages = load_config_with_stages(rebuild_config_path)

            # If a sticky session exists, animate will reuse its origin.
            # If clear removed the session, animate will resolve a fresh
            # player-relative origin from the current pose.
            if stages:
                run_multistage_animation(loaded_config, stages, rebuild_config_path)
            else:
                run_animation(loaded_config, rebuild_config_path)

        if action.kind == "modify":
            from animation.config import load_config_with_stages

            modify_config_path = config_path
            if not modify_config_path:
                print("[control] No stored config path available for modify.")
                continue

            loaded_config, stages = load_config_with_stages(modify_config_path)
            run_modify_animation(loaded_config, stages, modify_config_path)
