from __future__ import annotations
import os
import json
from typing import Dict, Any, Tuple

from normalise_block import normalise_block

BP_DIR = "blueprints_cleaned"


def process_blueprint_file(path: str) -> int:
    """
    Load a blueprint JSON, normalise all blocks, and write it back.
    Returns the number of blocks that changed (id or props).
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    blocks = data.get("blocks", [])
    changed = 0

    for b in blocks:
        old_id = b.get("id")
        old_props = b.get("props", {})

        new_id, new_props = normalise_block(old_id, old_props)

        if new_id != old_id or new_props != old_props:
            b["id"] = new_id
            b["props"] = new_props
            changed += 1

    if changed > 0:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return changed


def main() -> None:
    index_path = os.path.join(BP_DIR, "blueprints_index.json")
    if not os.path.isfile(index_path):
        raise SystemExit(f"Index not found: {index_path}")

    with open(index_path, "r", encoding="utf-8") as f:
        idx_data = json.load(f)

    blueprints: Dict[str, Dict[str, Any]] = idx_data.get("blueprints", {})

    total_files = 0
    total_blocks_changed = 0

    for bp_id, entry in sorted(blueprints.items()):
        rel_path = entry.get("file")
        if not rel_path:
            continue

        path = os.path.join(BP_DIR, rel_path)
        if not os.path.isfile(path):
            print(f"[warn] file for {bp_id} not found: {path}")
            continue

        total_files += 1
        changed = process_blueprint_file(path)
        total_blocks_changed += changed
        print(f"[post] {bp_id}: {changed} blocks normalised")

    print(f"[post] processed {total_files} blueprints, {total_blocks_changed} blocks changed")


if __name__ == "__main__":
    main()
