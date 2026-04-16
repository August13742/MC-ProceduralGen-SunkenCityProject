"""
Session state persistence for the animation system.

After each successful placement run, the resolved origin, bounding box,
and config metadata are written to a JSON file so that subsequent
commands (clear, replay, status) can operate without re-specifying
the placement location.

Default session file: ``.animation_session.json`` in the working directory.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SESSION_FILE = ".animation_session.json"
SESSION_BLOCKS_FILE = ".animation_session_blocks.json"


@dataclass
class SessionState:
    """Mutable record of the most recent placement run."""

    # Resolved absolute origin
    origin_x: int = 0
    origin_y: int = 64
    origin_z: int = 0

    # Config that produced this session
    config_path: str = ""
    source_file: str = ""

    # Bounding box (relative to origin)
    bbox_min_dx: int = 0
    bbox_min_dy: int = 0
    bbox_min_dz: int = 0
    bbox_max_dx: int = 0
    bbox_max_dy: int = 0
    bbox_max_dz: int = 0

    # Metadata
    block_count: int = 0
    stages_count: int = 0
    timestamp: float = field(default_factory=time.time)
    gdmc_host: str = "localhost:9000"
    state_file: str = SESSION_BLOCKS_FILE


def save_session(
    state: SessionState,
    path: str | Path = SESSION_FILE,
) -> Path:
    """Serialise session state to JSON.  Returns the written path."""
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump(asdict(state), f, indent=2)
    return p


def load_session(path: str | Path = SESSION_FILE) -> SessionState:
    """
    Load session state from disk.

    Raises ``FileNotFoundError`` if the session file does not exist.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"No session file found at '{p}'.  Run 'animate' first to create a session."
        )
    with p.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)

    # Filter to known fields only (forward-compatible)
    known = {fld.name for fld in SessionState.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in known}
    return SessionState(**filtered)


def save_session_blocks(
    blocks: list[dict[str, Any]],
    path: str | Path = SESSION_BLOCKS_FILE,
) -> Path:
    """Serialise the current logical block state to JSON."""
    p = Path(path)
    with p.open("w", encoding="utf-8") as f:
        json.dump({"blocks": blocks}, f, indent=2)
    return p


def load_session_blocks(path: str | Path = SESSION_BLOCKS_FILE) -> list[dict[str, Any]]:
    """Load the persisted logical block state for the current session."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"No session block-state file found at '{p}'.  Run 'animate' first to create one."
        )
    with p.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    blocks = data.get("blocks", [])
    if not isinstance(blocks, list):
        raise ValueError(f"Invalid session block-state file: '{p}'")
    return blocks


def delete_session(path: str | Path = SESSION_FILE) -> bool:
    """Delete the persisted session file if it exists."""
    p = Path(path)
    if not p.exists():
        return False
    p.unlink()
    return True


def delete_session_bundle(path: str | Path = SESSION_FILE) -> bool:
    """Delete the session metadata and its persisted block-state snapshot."""
    deleted_any = False
    session_path = Path(path)
    state_file = Path(SESSION_BLOCKS_FILE)

    if session_path.exists():
        try:
            state_file = Path(load_session(session_path).state_file)
        except Exception:
            state_file = Path(SESSION_BLOCKS_FILE)

    if session_path.exists():
        session_path.unlink()
        deleted_any = True
    if state_file.exists():
        state_file.unlink()
        deleted_any = True
    return deleted_any
