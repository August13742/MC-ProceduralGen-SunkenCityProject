"""
Player-tracking origin detection for GDMC placement.

Resolves the player's current position and facing from the GDMC HTTP interface,
then computes a collision-safe spawn origin for the structure in front of the
player. The target X/Z is derived from the structure bounding box so the player
never starts inside the build footprint.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True, slots=True)
class PlayerPose:
    x: int
    y: int
    z: int
    yaw_degrees: float
    pitch_degrees: float


def _normalise_host(host: str) -> str:
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host.rstrip("/")


def _parse_player_pose_from_nbt(data: str) -> PlayerPose | None:
    pos_match = re.search(r"Pos:\[([^\]]+)\]", data)
    rot_match = re.search(r"Rotation:\[([^\]]+)\]", data)
    if not pos_match or not rot_match:
        return None

    pos_vals = [part.strip().rstrip("dD") for part in pos_match.group(1).split(",")]
    rot_vals = [part.strip().rstrip("fF") for part in rot_match.group(1).split(",")]
    if len(pos_vals) < 3 or len(rot_vals) < 2:
        return None

    return PlayerPose(
        x=int(math.floor(float(pos_vals[0]))),
        y=int(math.floor(float(pos_vals[1]))),
        z=int(math.floor(float(pos_vals[2]))),
        yaw_degrees=float(rot_vals[0]),
        pitch_degrees=float(rot_vals[1]),
    )


def get_player_pose(
    host: str = "http://localhost:9000", timeout_s: float = 0.5
) -> PlayerPose | None:
    """Retrieve the nearest player's block position and facing."""
    host = _normalise_host(host)

    try:
        resp = requests.get(
            f"{host}/players",
            params={"includeData": "true"},
            timeout=timeout_s,
        )
        if resp.status_code == 200:
            players = resp.json()
            if players:
                pose = _parse_player_pose_from_nbt(players[0].get("data", ""))
                if pose is not None:
                    return pose
    except Exception:
        pass

    try:
        requests.post(
            f"{host}/command",
            data="gamerule sendCommandFeedback false",
            timeout=0.1,
        )
        resp = requests.post(
            f"{host}/command",
            data="data get entity @p Pos\ndata get entity @p Rotation",
            timeout=timeout_s,
        )
        if resp.status_code == 200 and resp.text:
            payload = resp.json()
            if isinstance(payload, list) and len(payload) >= 2:
                pos_msg = str(payload[0].get("message", ""))
                rot_msg = str(payload[1].get("message", ""))
                pos_match = re.search(
                    r"\[\s*(-?\d+(?:\.\d+)?)d?\s*,\s*(-?\d+(?:\.\d+)?)d?\s*,\s*(-?\d+(?:\.\d+)?)d?\s*\]",
                    pos_msg,
                )
                rot_match = re.search(
                    r"\[\s*(-?\d+(?:\.\d+)?)f?\s*,\s*(-?\d+(?:\.\d+)?)f?\s*\]",
                    rot_msg,
                )
                if pos_match and rot_match:
                    return PlayerPose(
                        x=int(math.floor(float(pos_match.group(1)))),
                        y=int(math.floor(float(pos_match.group(2)))),
                        z=int(math.floor(float(pos_match.group(3)))),
                        yaw_degrees=float(rot_match.group(1)),
                        pitch_degrees=float(rot_match.group(2)),
                    )
    except Exception:
        pass

    return None


def poll_player_pose(
    host: str = "http://localhost:9000",
    max_attempts: int = 10,
    poll_interval_s: float = 1.0,
) -> PlayerPose:
    """Block until the player pose is successfully resolved."""
    for attempt in range(1, max_attempts + 1):
        pose = get_player_pose(host)
        if pose is not None:
            print(
                f"[player-track] Detected player at ({pose.x}, {pose.y}, {pose.z}) "
                f"yaw={pose.yaw_degrees:.1f} (attempt {attempt}/{max_attempts})"
            )
            return pose

        if attempt < max_attempts:
            print(
                f"[player-track] Player not found, retrying in {poll_interval_s}s "
                f"({attempt}/{max_attempts})..."
            )
            time.sleep(poll_interval_s)

    raise RuntimeError(
        f"[player-track] Failed to detect player position after {max_attempts} attempts on {host}."
    )


def _yaw_to_forward(yaw_degrees: float) -> tuple[int, int]:
    """Map Minecraft yaw to an axis-aligned forward vector."""
    yaw = yaw_degrees % 360.0
    if 45.0 <= yaw < 135.0:
        return -1, 0
    if 135.0 <= yaw < 225.0:
        return 0, -1
    if 225.0 <= yaw < 315.0:
        return 1, 0
    return 0, 1


def _raycast_ground_y(host: str, x: int, z: int) -> int:
    """Resolve stable ground Y by scanning downward from the world top."""
    host = _normalise_host(host)
    column = requests.get(
        f"{host}/blocks",
        params={"x": x, "y": -64, "z": z, "dx": 1, "dy": 385, "dz": 1},
        timeout=2.0,
    )
    column.raise_for_status()
    rows = column.json()
    solid_y = -64
    for row in rows:
        block_id = row.get("id", "minecraft:air")
        if block_id not in {
            "minecraft:air",
            "minecraft:cave_air",
            "minecraft:void_air",
            "minecraft:grass",
            "minecraft:tall_grass",
            "minecraft:fern",
            "minecraft:large_fern",
            "minecraft:dandelion",
            "minecraft:poppy",
        }:
            solid_y = int(row["y"])
    return solid_y + 1


def resolve_player_spawn_origin(
    host: str,
    blocks: list[dict[str, Any]],
    clearance_blocks: int,
    margin_blocks: int,
    use_ground_raycast: bool,
) -> tuple[int, int, int]:
    """
    Compute a collision-safe origin in front of the player.

    The offset is derived from the structure footprint plus an explicit margin
    and player clearance radius, so the player remains outside the placed box.
    """
    if not blocks:
        raise ValueError("Cannot resolve player-based origin for an empty block list.")

    from animation.placer import compute_bounding_box

    pose = poll_player_pose(host=host)
    min_dx, min_dy, min_dz, max_dx, max_dy, max_dz = compute_bounding_box(blocks)
    size_x = max_dx - min_dx + 1
    size_z = max_dz - min_dz + 1
    forward_x, forward_z = _yaw_to_forward(pose.yaw_degrees)

    depth = size_x if forward_x != 0 else size_z
    offset_distance = clearance_blocks + margin_blocks + depth

    target_x = pose.x + forward_x * offset_distance
    target_z = pose.z + forward_z * offset_distance

    if forward_x > 0:
        origin_x = target_x - min_dx
    elif forward_x < 0:
        origin_x = target_x - max_dx
    else:
        origin_x = target_x - min_dx - (size_x // 2)

    if forward_z > 0:
        origin_z = target_z - min_dz
    elif forward_z < 0:
        origin_z = target_z - max_dz
    else:
        origin_z = target_z - min_dz - (size_z // 2)

    if use_ground_raycast:
        ground_y = _raycast_ground_y(host, origin_x - min_dx, origin_z - min_dz)
        origin_y = ground_y - min_dy
        print(
            f"[player-track] Ground raycast at ({origin_x - min_dx}, {origin_z - min_dz}) "
            f"-> y={ground_y}"
        )
    else:
        origin_y = pose.y

    print(
        f"[player-track] Spawn origin resolved to ({origin_x}, {origin_y}, {origin_z}) "
        f"from footprint {size_x}x{max_dy - min_dy + 1}x{size_z}"
    )
    return origin_x, origin_y, origin_z
