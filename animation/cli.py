"""
CLI entry point for the animation system.

Usage:
    python -m animation animate --config animation_config.toml
    python -m animation modify --config animation_config.toml
    python -m animation control --config animation_config.toml
    python -m animation preview --config animation_config.toml [--output frames/]
    python -m animation clear   [--session .animation_session.json]
    python -m animation replay  [--config ...] [--session ...]
    python -m animation status  [--session .animation_session.json]
"""

from __future__ import annotations

import argparse
import sys
import time


def cmd_animate(args: argparse.Namespace) -> None:
    """Run live GDMC animation (single-stage or multi-stage)."""
    from animation.config import load_config_with_stages

    config, stages = load_config_with_stages(args.config)

    if stages:
        from animation.placer import run_multistage_animation

        print(f"[cli] Multi-stage mode: {len(stages)} stages defined.")
        run_multistage_animation(config, stages, config_path=args.config)
    else:
        from animation.placer import run_animation

        run_animation(config, config_path=args.config)


def cmd_preview(args: argparse.Namespace) -> None:
    """Generate offline preview (GIF / MP4 / PNG)."""
    from animation.config import load_config_with_stages

    config, stages = load_config_with_stages(args.config)

    # CLI overrides for format
    if args.format:
        from dataclasses import asdict
        from animation.config import AnimationConfig

        d = asdict(config)
        d["preview_output_format"] = args.format
        config = AnimationConfig(**d)

    output_dir = args.output or config.preview_output_dir

    if stages:
        from animation.preview import render_multistage_preview

        print(f"[cli] Multi-stage preview: {len(stages)} stages defined.")
        result = render_multistage_preview(config, stages, output_dir=output_dir)
    else:
        from animation.preview import render_preview

        result = render_preview(config, output_dir=output_dir)

    if result:
        print(f"[cli] Output: {result}")


def cmd_control(args: argparse.Namespace) -> None:
    """Run the in-game rebuild control loop."""
    from animation.config import load_config
    from animation.placer import run_rebuild_loop

    config = load_config(args.config)
    run_rebuild_loop(config, config_path=args.config)


def cmd_modify(args: argparse.Namespace) -> None:
    """Apply configured modify/decay stages in-place to the current build."""
    from animation.config import load_config_with_stages
    from animation.placer import run_modify_animation

    config, stages = load_config_with_stages(args.config)
    run_modify_animation(config, stages, config_path=args.config)


def cmd_clear(args: argparse.Namespace) -> None:
    """Clear the area from the most recent placement session."""
    from animation.session import delete_session, load_session
    from animation.placer import clear_from_session

    session = load_session(args.session)
    print(
        f"[clear] Clearing session area at origin "
        f"({session.origin_x}, {session.origin_y}, {session.origin_z})"
    )
    clear_from_session(session)
    if delete_session(args.session):
        print(f"[clear] Removed session file: {args.session}")


def cmd_replay(args: argparse.Namespace) -> None:
    """Clear the previous area and replay the animation from scratch.

    Uses the session file for origin (so the build lands in the same
    location), and the config file for strategy / timing / source.
    If ``--config`` is omitted, falls back to the config path stored
    in the session.
    """
    from animation.session import load_session
    from animation.placer import clear_from_session

    session = load_session(args.session)

    config_path = args.config or session.config_path
    if not config_path:
        print(
            "[replay] Error: no config path provided and none stored in session.",
            file=sys.stderr,
        )
        sys.exit(1)

    from animation.config import load_config_with_stages
    from dataclasses import replace

    config, stages = load_config_with_stages(config_path)

    # Override origin from session so we rebuild in the same location
    config = replace(
        config,
        origin_x=session.origin_x,
        origin_y=session.origin_y,
        origin_z=session.origin_z,
        use_player_tracking=False,  # origin is already resolved
        clear_area_first=False,  # we clear explicitly below
    )

    print(
        f"[replay] Origin from session: "
        f"({session.origin_x}, {session.origin_y}, {session.origin_z})"
    )

    # Step 1: clear
    print("[replay] Clearing previous area...")
    clear_from_session(session)

    # Step 2: re-animate
    print("[replay] Replaying animation...")
    if stages:
        from animation.placer import run_multistage_animation

        run_multistage_animation(config, stages, config_path=config_path)
    else:
        from animation.placer import run_animation

        run_animation(config, config_path=config_path)


def cmd_status(args: argparse.Namespace) -> None:
    """Display information about the most recent placement session."""
    from animation.session import load_session

    try:
        session = load_session(args.session)
    except FileNotFoundError as e:
        print(str(e))
        return

    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(session.timestamp))

    ox, oy, oz = session.origin_x, session.origin_y, session.origin_z
    abs_min = (
        ox + session.bbox_min_dx,
        oy + session.bbox_min_dy,
        oz + session.bbox_min_dz,
    )
    abs_max = (
        ox + session.bbox_max_dx,
        oy + session.bbox_max_dy,
        oz + session.bbox_max_dz,
    )
    size = (
        session.bbox_max_dx - session.bbox_min_dx + 1,
        session.bbox_max_dy - session.bbox_min_dy + 1,
        session.bbox_max_dz - session.bbox_min_dz + 1,
    )

    print("=== Animation Session ===")
    print(f"  Timestamp:    {ts}")
    print(f"  Config:       {session.config_path or '(not recorded)'}")
    print(f"  Source:       {session.source_file}")
    print(f"  GDMC host:    {session.gdmc_host}")
    print(f"  Origin:       ({ox}, {oy}, {oz})")
    print(f"  Bounding box: {abs_min} to {abs_max}  ({size[0]}x{size[1]}x{size[2]})")
    print(f"  Blocks:       {session.block_count}")
    if session.stages_count > 0:
        print(f"  Stages:       {session.stages_count}")
    print("=========================")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="animation",
        description="GDMC Construction Animation System",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- animate ---
    p_animate = subparsers.add_parser(
        "animate",
        help="Run live construction animation against a GDMC server.",
    )
    p_animate.add_argument(
        "--config", required=True, help="Path to TOML configuration file."
    )
    p_animate.set_defaults(func=cmd_animate)

    # --- preview ---
    p_preview = subparsers.add_parser(
        "preview",
        help="Generate offline preview frames (PNG sequence).",
    )
    p_preview.add_argument(
        "--config", required=True, help="Path to TOML configuration file."
    )
    p_preview.add_argument(
        "--output", default=None, help="Output directory for frames."
    )
    p_preview.add_argument(
        "--format",
        default=None,
        choices=["gif", "mp4", "png"],
        help="Output format (overrides config).",
    )
    p_preview.set_defaults(func=cmd_preview)

    # --- control ---
    p_control = subparsers.add_parser(
        "control",
        help="Wait for in-game clear/rebuild trigger commands.",
    )
    p_control.add_argument(
        "--config", required=True, help="Path to TOML configuration file."
    )
    p_control.set_defaults(func=cmd_control)

    # --- modify ---
    p_modify = subparsers.add_parser(
        "modify",
        help="Apply configured modify/decay stages in-place to the current build.",
    )
    p_modify.add_argument(
        "--config", required=True, help="Path to TOML configuration file."
    )
    p_modify.set_defaults(func=cmd_modify)

    # --- clear ---
    p_clear = subparsers.add_parser(
        "clear",
        help="Clear the area from the most recent placement session.",
    )
    p_clear.add_argument(
        "--session",
        default=".animation_session.json",
        help="Path to session state file (default: .animation_session.json).",
    )
    p_clear.set_defaults(func=cmd_clear)

    # --- replay ---
    p_replay = subparsers.add_parser(
        "replay",
        help="Clear the previous area and replay the animation from scratch.",
    )
    p_replay.add_argument(
        "--config",
        default=None,
        help="Path to TOML config (defaults to session's stored config).",
    )
    p_replay.add_argument(
        "--session",
        default=".animation_session.json",
        help="Path to session state file (default: .animation_session.json).",
    )
    p_replay.set_defaults(func=cmd_replay)

    # --- status ---
    p_status = subparsers.add_parser(
        "status",
        help="Show info about the most recent placement session.",
    )
    p_status.add_argument(
        "--session",
        default=".animation_session.json",
        help="Path to session state file (default: .animation_session.json).",
    )
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
