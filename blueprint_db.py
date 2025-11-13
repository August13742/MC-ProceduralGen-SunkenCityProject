import json
import os
from typing import Dict, Any, Iterable, Tuple, List


def load_index(bp_dir: str) -> Dict[str, Any]:
    path = os.path.join(bp_dir, "blueprints_index.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_blueprints(bp_dir: str) -> Iterable[Tuple[str, Dict[str, Any], List[Dict[str, Any]]]]:
    """
    Yield (id, meta, blocks_dict_list) for all blueprints.

    Each block is:
        {
            "dx": int, "dy": int, "dz": int,
            "id": str,
            "props": dict
        }
    """
    idx = load_index(bp_dir)
    root = os.path.abspath(bp_dir)

    for bid, entry in idx["blueprints"].items():
        file_name = entry["file"]
        path = os.path.join(root, file_name)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        meta = data["meta"]
        blocks = data["blocks"]
        yield bid, meta, blocks


def place_blueprint(editor, origin, blocks: List[Dict[str, Any]]) -> None:
    """
    Place a blueprint at origin using GDPC editor.

    origin: (ox, oy, oz)
    blocks: list of dicts as above.
    """
    from gdpc.block import Block
    ox, oy, oz = origin
    for b in blocks:
        dx = b["dx"]
        dy = b["dy"]
        dz = b["dz"]
        block_id = b["id"]
        props = b["props"]
        editor.placeBlock((ox + dx, oy + dy, oz + dz), Block(block_id, props))
