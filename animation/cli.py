"""
CLI entry point for the animation system.

Usage:
    python -m animation animate --config animation_config.toml
    python -m animation preview --config animation_config.toml [--output frames/]
"""

from __future__ import annotations

import argparse
import sys


def cmd_animate(args: argparse.Namespace) -> None:
    """Run live GDMC animation (single-stage or multi-stage)."""
    from animation.config import load_config_with_stages

    config, stages = load_config_with_stages(args.config)

    if stages:
        from animation.placer import run_multistage_animation

        print(f"[cli] Multi-stage mode: {len(stages)} stages defined.")
        run_multistage_animation(config, stages)
    else:
        from animation.placer import run_animation

        run_animation(config)


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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
