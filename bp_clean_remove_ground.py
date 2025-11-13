import argparse
import json
import os
from collections import Counter
from typing import Dict, Any, List



"""
python bp_clean_remove_ground.py --bp-dir ./blueprints_out --out-dir ./blueprints_cleaned
"""

REMOVABLE_IDS = {
    "universal_minecraft:dirt",
    "universal_minecraft:grass_block",
}


def load_bp(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bp(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def filter_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # index by (x,y,z)
    by_pos = {(b["dx"], b["dy"], b["dz"]): b for b in blocks}

    # find removable that directly support non-removable above them
    supporting = set()
    for (x, y, z), b in by_pos.items():
        if b["id"] not in REMOVABLE_IDS:
            continue
        above = by_pos.get((x, y + 1, z))
        if above is not None and above["id"] not in REMOVABLE_IDS:
            supporting.add((x, y, z))

    new_blocks = []
    for (x, y, z), b in by_pos.items():
        if b["id"] not in REMOVABLE_IDS:
            new_blocks.append(b)
        else:
            if (x, y, z) in supporting:
                new_blocks.append(b)
            # else: drop

    return new_blocks


def recompute_meta(meta: Dict[str, Any], blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    if blocks:
        top_y_local = max(b["dy"] for b in blocks)
    else:
        top_y_local = 0
    block_counts = Counter(b["id"] for b in blocks)
    meta = dict(meta)
    meta["top_y_local"] = top_y_local
    meta["top_y_world"] = meta["world_origin"][1] + top_y_local
    meta["block_counts"] = dict(block_counts)
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bp-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    # Safety check: ensure output directory is different from input
    bp_dir_abs = os.path.abspath(args.bp_dir)
    out_dir_abs = os.path.abspath(args.out_dir)
    
    if bp_dir_abs == out_dir_abs:
        print("[error] Output directory must be different from input directory!")
        print(f"        Input:  {bp_dir_abs}")
        print(f"        Output: {out_dir_abs}")
        return

    os.makedirs(args.out_dir, exist_ok=True)

    # load index
    with open(os.path.join(args.bp_dir, "blueprints_index.json"), "r", encoding="utf-8") as f:
        index = json.load(f)

    new_index: Dict[str, Dict[str, Any]] = {}

    for bid, entry in index["blueprints"].items():  
        in_path = os.path.join(args.bp_dir, entry["file"])
        data = load_bp(in_path)
        meta = data["meta"]
        blocks = data["blocks"]

        print(f"[info] {bid}: {len(blocks)} blocks before clean")
        new_blocks = filter_blocks(blocks)
        new_meta = recompute_meta(meta, new_blocks)

        out_file = entry["file"]  # same name
        out_path = os.path.join(args.out_dir, out_file)

        save_bp(out_path, {"meta": new_meta, "blocks": new_blocks})

        new_index[bid] = {
            "file": out_file,
            "meta": new_meta,
        }

        print(f"[ok]  {bid}: {len(new_blocks)} blocks after clean")

    # write new index
    with open(os.path.join(args.out_dir, "blueprints_index.json"), "w", encoding="utf-8") as f:
        json.dump({"blueprints": new_index}, f, ensure_ascii=False, indent=2)

    print("[done] cleaned blueprints and wrote new index")


if __name__ == "__main__":
    main()
