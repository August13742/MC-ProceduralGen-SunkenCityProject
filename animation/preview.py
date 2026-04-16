"""
Offline preview renderer — GIF / MP4 / PNG output.

Generates an animated construction preview using the VPS visualiser backend
(trimesh / pyrender).  Each frame adds the blocks from one strategy batch.

Output formats:
  - gif:  Single animated GIF (PIL).
  - mp4:  H.264 video via ffmpeg subprocess.
  - png:  Numbered PNG sequence (legacy fallback).

This module does NOT require a Minecraft server.
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

# Ensure the VPS package is importable
_VPS_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Minecraft-Voxel-Renderer",
    "src",
)
if _VPS_SRC not in sys.path:
    sys.path.insert(0, _VPS_SRC)

from animation.config import AnimationConfig, Strategy
from animation.placer import load_blocks
from animation.strategies import get_strategy_generator


# ---------------------------------------------------------------------------
# Incremental scene builder
# ---------------------------------------------------------------------------


class IncrementalScene:
    """
    Maintains a trimesh Scene incrementally with adjacency-aware connections.

    Supports adding blocks (construction) and removing blocks (erosion)
    without rebuilding the entire scene each frame.  Node names encode the
    grid position for O(1) lookup on removal.

    When a connectable block (fence, wall, pane) is placed or removed,
    the ``BlockGrid`` adjacency resolver re-evaluates connections for
    affected neighbours and re-generates their meshes.
    """

    def __init__(self, adjacency_enabled: bool = True) -> None:
        import trimesh
        from vps.adjacency import BlockGrid

        self.scene = trimesh.Scene()
        self._node_count = 0
        self._grid = BlockGrid()
        self._adjacency_enabled = adjacency_enabled

    def add_block(self, semantic_block: dict[str, Any]) -> None:
        """Add a single VPS-format block to the scene, updating adjacency."""
        import numpy as np
        from vps.block_registry import create_coloured_block_mesh

        block_id = semantic_block["id"]
        if block_id == "minecraft:air":
            return

        props = semantic_block.get("properties") or {}
        x = int(semantic_block["x"])
        y = int(semantic_block["y"])
        z = int(semantic_block["z"])

        # Register in spatial grid
        self._grid.set(x, y, z, block_id, props)

        if self._adjacency_enabled:
            self._resolve_and_place(x, y, z)
            self._update_neighbours(x, y, z)
        else:
            self._place_mesh(x, y, z, block_id, props)

    def remove_block(self, x: int, y: int, z: int) -> None:
        """Remove the block at grid position (x, y, z), updating adjacency."""
        node_name = f"b_{x}_{y}_{z}"
        self._remove_node(node_name)
        self._grid.remove(x, y, z)

        if self._adjacency_enabled:
            self._update_neighbours(x, y, z)

    def _place_mesh(
        self, x: int, y: int, z: int, block_id: str, props: dict[str, str]
    ) -> None:
        """Create mesh for a block and insert into the scene."""
        import numpy as np
        from vps.block_registry import create_coloured_block_mesh

        mesh = create_coloured_block_mesh(block_id, props)
        mesh.apply_translation(np.array([x, y, z], dtype=float))

        node_name = f"b_{x}_{y}_{z}"
        self._remove_node(node_name)
        self.scene.add_geometry(mesh, node_name=node_name)
        self._node_count += 1

    def _resolve_and_place(self, x: int, y: int, z: int) -> None:
        """Resolve connections for a block and place its mesh."""
        from vps.adjacency import resolve_connections

        entry = self._grid.get(x, y, z)
        if entry is None:
            return

        resolved_props = resolve_connections(self._grid, x, y, z)
        props = resolved_props if resolved_props is not None else entry["props"]

        # Update grid with resolved properties
        if resolved_props is not None:
            entry["props"] = resolved_props

        self._place_mesh(x, y, z, entry["id"], props)

    def _update_neighbours(self, x: int, y: int, z: int) -> None:
        """Re-resolve and re-place connectable neighbours affected by a change."""
        from vps.adjacency import get_affected_neighbours

        affected = get_affected_neighbours(x, y, z, self._grid)
        for nx, ny, nz in affected:
            if (nx, ny, nz) != (x, y, z):  # Don't re-place the block we just placed
                self._resolve_and_place(nx, ny, nz)

    def _remove_node(self, node_name: str) -> None:
        """Remove a named node from the scene graph if it exists."""
        if node_name in self.scene.graph.nodes:
            try:
                self.scene.delete_geometry(node_name)
                self._node_count -= 1
            except (KeyError, ValueError):
                pass

    @property
    def has_geometry(self) -> bool:
        return bool(self.scene.geometry)


# ---------------------------------------------------------------------------
# Format conversion helpers
# ---------------------------------------------------------------------------


def _blueprint_to_semantic(block: dict[str, Any]) -> dict[str, Any]:
    """
    Convert a blueprint_db block dict to the VPS semantic format.

    blueprint_db uses {dx, dy, dz, id, props}.
    VPS uses {x, y, z, id, properties}.
    """
    entry: dict[str, Any] = {
        "x": block["dx"],
        "y": block["dy"],
        "z": block["dz"],
        "id": block["id"],
    }
    props = block.get("props")
    if props:
        entry["properties"] = dict(props)
    return entry


def _b64png_to_pil(b64_png: str) -> Image.Image:
    """Decode a base64 PNG string into a PIL Image (RGBA)."""
    png_bytes = base64.b64decode(b64_png)
    return Image.open(io.BytesIO(png_bytes)).convert("RGBA")


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def _write_gif(
    frames: list[Image.Image],
    output_path: Path,
    fps: int,
    hold_last: int,
) -> None:
    """Write frames as an animated GIF."""
    if not frames:
        return

    # Convert RGBA → RGB with composited background (GIF has no alpha).
    rgb_frames: list[Image.Image] = []
    for f in frames:
        bg = Image.new("RGB", f.size, (30, 30, 30))
        bg.paste(f, mask=f.split()[3] if f.mode == "RGBA" else None)
        rgb_frames.append(bg)

    # Hold last frame
    for _ in range(hold_last):
        rgb_frames.append(rgb_frames[-1])

    duration_ms = max(1, 1000 // fps)
    rgb_frames[0].save(
        output_path,
        save_all=True,
        append_images=rgb_frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )
    print(f"[preview] Wrote GIF: {output_path} ({len(rgb_frames)} frames, {fps} fps)")


def _write_mp4(
    frames: list[Image.Image],
    output_path: Path,
    fps: int,
    hold_last: int,
) -> None:
    """Write frames as H.264 MP4 via ffmpeg (stdin pipe)."""
    if not frames:
        return

    # Hold last frame
    all_frames = list(frames)
    for _ in range(hold_last):
        all_frames.append(all_frames[-1])

    w, h = all_frames[0].size

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{w}x{h}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "fast",
        "-crf",
        "18",
        str(output_path),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print(
            "[preview] ffmpeg not found. Install ffmpeg or use 'gif' format. "
            "Falling back to GIF."
        )
        _write_gif(frames, output_path.with_suffix(".gif"), fps, hold_last)
        return

    assert proc.stdin is not None
    for f in all_frames:
        rgb = f.convert("RGB")
        proc.stdin.write(rgb.tobytes())
    proc.stdin.close()

    retcode = proc.wait()
    if retcode != 0:
        err_text = proc.stderr.read().decode() if proc.stderr else ""
        print(f"[preview] ffmpeg exited with code {retcode}: {err_text[:200]}")
    else:
        print(
            f"[preview] Wrote MP4: {output_path} ({len(all_frames)} frames, {fps} fps)"
        )


def _write_pngs(
    frames: list[Image.Image],
    output_dir: Path,
) -> None:
    """Write numbered PNG sequence (legacy fallback)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        path = output_dir / f"frame_{i:05d}.png"
        f.save(path)
    print(f"[preview] Wrote {len(frames)} PNGs to {output_dir}/")


# ---------------------------------------------------------------------------
# Output dispatch
# ---------------------------------------------------------------------------


def _write_output(
    pil_frames: list[Image.Image],
    out_path: Path,
    config: AnimationConfig,
) -> Path:
    """Dispatch to the appropriate output writer based on config."""
    fmt = config.preview_output_format.lower()
    fps = config.preview_fps
    hold = config.preview_hold_last_frames

    if fmt == "mp4":
        out_path.mkdir(parents=True, exist_ok=True)
        video_path = out_path / "construction.mp4"
        _write_mp4(pil_frames, video_path, fps, hold)
        return video_path

    elif fmt == "gif":
        out_path.mkdir(parents=True, exist_ok=True)
        gif_path = out_path / "construction.gif"
        _write_gif(pil_frames, gif_path, fps, hold)
        return gif_path

    else:
        _write_pngs(pil_frames, out_path)
        return out_path


# ---------------------------------------------------------------------------
# Main render pipeline
# ---------------------------------------------------------------------------


def render_preview(
    config: AnimationConfig,
    output_dir: str = "frames",
) -> Path | None:
    """
    Render a construction animation preview using incremental scene building.

    Returns the path to the output file/directory, or None on failure.

    Frame N contains all blocks from batches 0..N (cumulative).
    Output format is determined by ``config.preview_output_format``.
    """
    from vps.visualiser import render_single_view

    blocks = load_blocks(config)
    if not blocks:
        print("[preview] No blocks to render.")
        return None

    # Strategy kwargs
    strategy_kwargs: dict[str, Any] = {}
    if config.strategy == Strategy.STRUCTURAL_PHASES:
        strategy_kwargs["foundation_ids"] = config.foundation_ids
        strategy_kwargs["roof_ids"] = config.roof_ids
        strategy_kwargs["interior_ids"] = config.interior_ids

    gen = get_strategy_generator(config.strategy.value, blocks, **strategy_kwargs)

    inc_scene = IncrementalScene()
    pil_frames: list[Image.Image] = []

    view = config.preview_view
    width = config.preview_width
    height = config.preview_height
    bg = config.preview_bg_colour

    for batch in gen:
        for b in batch:
            inc_scene.add_block(_blueprint_to_semantic(b))

        if not inc_scene.has_geometry:
            continue

        b64_png = render_single_view(
            scene=inc_scene.scene,
            view_name=view,
            width=width,
            height=height,
            bg_colour=bg,
        )

        pil_frames.append(_b64png_to_pil(b64_png))

        if len(pil_frames) % 10 == 0:
            print(
                f"  rendered frame {len(pil_frames)} ({inc_scene._node_count} blocks)"
            )

    if not pil_frames:
        print("[preview] No frames generated.")
        return None

    print(f"[preview] Rendered {len(pil_frames)} frames total.")

    return _write_output(pil_frames, Path(output_dir), config)


# Backwards-compatible alias
render_preview_frames = render_preview


# ---------------------------------------------------------------------------
# Multi-stage preview
# ---------------------------------------------------------------------------


def render_multistage_preview(
    config: AnimationConfig,
    stages: list,
    output_dir: str = "frames",
) -> Path | None:
    """
    Render a multi-stage construction animation preview.

    Each stage's block list is animated incrementally.  The cumulative scene
    carries across stages (build → erode shows construction then erosion).

    Uses IncrementalScene for O(batch_size) per-frame updates instead of
    O(total_blocks) full rebuilds.
    """
    from vps.visualiser import render_single_view
    from animation.stages import Stage, iterate_stages

    view = config.preview_view
    width = config.preview_width
    height = config.preview_height
    bg = config.preview_bg_colour

    inc_scene = IncrementalScene()
    pil_frames: list[Image.Image] = []

    for stage_idx, (stage, blocks) in enumerate(iterate_stages(stages, config)):
        print(
            f"[preview] Stage {stage_idx + 1}/{len(stages)}: "
            f"'{stage.name}' ({len(blocks)} blocks)"
        )

        gen = get_strategy_generator(stage.strategy, blocks)

        for batch in gen:
            for b in batch:
                if b["id"] == "minecraft:air":
                    inc_scene.remove_block(b["dx"], b["dy"], b["dz"])
                else:
                    inc_scene.add_block(_blueprint_to_semantic(b))

            if not inc_scene.has_geometry:
                continue

            b64_png = render_single_view(
                scene=inc_scene.scene,
                view_name=view,
                width=width,
                height=height,
                bg_colour=bg,
            )
            pil_frames.append(_b64png_to_pil(b64_png))

            if len(pil_frames) % 10 == 0:
                print(
                    f"  rendered frame {len(pil_frames)} "
                    f"({inc_scene._node_count} blocks in scene)"
                )

    if not pil_frames:
        print("[preview] No frames generated.")
        return None

    print(f"[preview] Rendered {len(pil_frames)} frames total across all stages.")

    return _write_output(pil_frames, Path(output_dir), config)
