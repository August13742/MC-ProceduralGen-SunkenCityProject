"""
Player-tracking origin detection for GDMC placement.

Resolves the player's current block position from the GDMC HTTP interface,
enabling animation placement relative to the player without requiring
``/setbuildarea``.

Ported from SunkenCityProject/generate_sunken_world_infinite.py with
modifications:
  - Returns block coordinates (not chunk coordinates).
  - Adds a polling retry loop with configurable timeout.
  - Decoupled from gdpc Editor (operates on raw host string).
"""

from __future__ import annotations

import re
import time
from typing import Optional

import requests


def get_player_position(
    host: str = "localhost:9000",
    timeout_s: float = 0.5,
) -> Optional[tuple[int, int, int]]:
    """
    Retrieve the nearest player's block-level position (x, y, z).

    Uses a dual-strategy fallback:
      1. ``GET /players`` — clean JSON endpoint (GDMC-HTTP 1.x+).
      2. ``POST /command`` — ``data get entity @p Pos`` with regex parsing.

    Returns ``None`` if both strategies fail.
    """
    # Normalise host URL
    if not host.startswith("http"):
        host = f"http://{host}"
    host = host.rstrip("/")

    # --- Strategy 1: GET /players ---
    try:
        resp = requests.get(f"{host}/players", timeout=timeout_s)
        if resp.status_code == 200:
            data = resp.json()
            if data and len(data) > 0:
                p = data[0]
                pos = p.get("pos", p.get("position"))
                if pos and len(pos) >= 3:
                    return int(pos[0]), int(pos[1]), int(pos[2])
    except Exception:
        pass

    # --- Strategy 2: POST /command (brute force) ---
    try:
        # Suppress in-game chat feedback
        requests.post(
            f"{host}/command",
            data="gamerule sendCommandFeedback false",
            timeout=0.1,
        )

        resp = requests.post(
            f"{host}/command",
            data="data get entity @p Pos",
            timeout=timeout_s,
        )

        if resp.status_code == 200 and resp.text:
            # Match pattern: [-123.5d, 64.0d, 456.9d]
            match = re.search(
                r"\[\s*(-?\d+(?:\.\d+)?)[dD]?\s*,"
                r"\s*(-?\d+(?:\.\d+)?)[dD]?\s*,"
                r"\s*(-?\d+(?:\.\d+)?)[dD]?\s*\]",
                resp.text,
            )
            if match:
                x = int(float(match.group(1)))
                y = int(float(match.group(2)))
                z = int(float(match.group(3)))
                return x, y, z
    except Exception:
        pass

    return None


def poll_player_position(
    host: str = "localhost:9000",
    max_attempts: int = 10,
    poll_interval_s: float = 1.0,
) -> tuple[int, int, int]:
    """
    Block until the player position is successfully resolved.

    Raises ``RuntimeError`` if all attempts are exhausted.
    """
    for attempt in range(1, max_attempts + 1):
        pos = get_player_position(host)
        if pos is not None:
            print(
                f"[player-track] Detected player at "
                f"({pos[0]}, {pos[1]}, {pos[2]}) "
                f"(attempt {attempt}/{max_attempts})"
            )
            return pos

        if attempt < max_attempts:
            print(
                f"[player-track] Player not found, retrying in "
                f"{poll_interval_s}s ({attempt}/{max_attempts})..."
            )
            time.sleep(poll_interval_s)

    raise RuntimeError(
        f"[player-track] Failed to detect player position after "
        f"{max_attempts} attempts on {host}."
    )
