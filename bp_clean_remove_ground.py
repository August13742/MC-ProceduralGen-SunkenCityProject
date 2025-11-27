import argparse
import json
import os
from collections import Counter
from typing import Dict, Any, List, Tuple, Set

"""
python bp_clean_remove_ground.py --bp-dir ./blueprints_out --out-dir ./blueprints_cleaned --keep-foundation-layers 1 --min-dy -1

Behaviour:

1. Interpret FOUNDATION_IDS as the set of "foundation" block IDs.
2. Scan local Y (dy) bottom-up.
3. Find a CONTIGUOUS prefix of layers starting from the minimum dy such that each
   layer contains at least one foundation block. These are "foundation layers".
   As soon as a layer contains no foundation blocks, we stop; higher layers are
   not considered foundation.
4. Let F = number of such foundation layers, and K = keep_foundation_layers:
   - If F <= K: keep all layers as-is (no shaving).
   - If F > K: we keep only the TOP K foundation layers (closest to the building),
     and delete all FOUNDATION_IDS from the lower (F - K) foundation layers.
     Non-foundation blocks are never deleted.
5. After shaving, shift all blocks in Y so that the new minimum dy == min_dy
   (default -1). This embeds the kept foundation layer slightly into the ground
   when you place the blueprint with world_origin.y on your surface.
"""

# Default foundation IDs if not overridden
DEFAULT_FOUNDATION_IDS = {
    "minecraft:dirt",
    "minecraft:grass_block",
    # "minecraft:coarse_dirt",
    # "minecraft:gravel",
}


def parse_foundation_ids(arg: str | None) -> Set[str]:
    if not arg:
        return set(DEFAULT_FOUNDATION_IDS)
    # comma-separated list
    parts = [s.strip() for s in arg.split(",") if s.strip()]
    return set(parts) if parts else set(DEFAULT_FOUNDATION_IDS)


def load_bp(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_bp(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def filter_blocks(
    blocks: List[Dict[str, Any]],
    foundation_ids: Set[str],
    keep_foundation_layers: int,
) -> List[Dict[str, Any]]:
    """
    Foundation logic (parameterised):

    - Let dy_values be all occupied dy sorted ascending: y0 < y1 < ...
    - Define foundation layers as the longest contiguous prefix [y0..yF-1] such that
      each yi in that prefix has at least one block with id in foundation_ids.
      Once we hit a layer with no foundation blocks, we stop.

    Let F = number of foundation layers (len(prefix)).
    Let K = keep_foundation_layers.

    - If F == 0: there is no foundation at all → nothing to shave.
    - If F <= K: we keep all foundation layers (no shaving).
    - If F > K:
        * We keep the top K foundation layers
          (the layers with the largest dy inside the prefix).
        * For the remaining (F - K) lower layers, we delete ONLY blocks whose
          id is in foundation_ids. Non-foundation blocks are preserved.

    This is independent from any later Y rebasing.
    """
    if not blocks:
        return []

    if keep_foundation_layers < 0:
        keep_foundation_layers = 0

    # Bucket indices by dy for layer-wise processing
    by_y: Dict[int, List[int]] = {}
    for idx, b in enumerate(blocks):
        y = b["dy"]
        by_y.setdefault(y, []).append(idx)

    sorted_ys = sorted(by_y.keys())
    if not sorted_ys:
        return blocks

    # 1) Detect contiguous prefix of foundation layers
    foundation_layers: List[int] = []
    for y in sorted_ys:
        indices = by_y[y]
        has_filler = any(blocks[idx]["id"] in foundation_ids for idx in indices)
        if has_filler:
            foundation_layers.append(y)
        else:
            # First layer with no foundation block → prefix ends here
            break

    F = len(foundation_layers)
    if F == 0:
        # No foundation-like blocks at the bottom at all
        return blocks

    if keep_foundation_layers == 0:
        # We want to strip *all* foundation layers
        keep_layers: Set[int] = set()
    elif F <= keep_foundation_layers:
        # We are allowed to keep all foundation layers; nothing to shave
        keep_layers = set(foundation_layers)
    else:
        # Keep only the top K foundation layers in the prefix
        keep_layers = set(foundation_layers[-keep_foundation_layers:])

    to_delete: Set[int] = set()

    for y in foundation_layers:
        if y in keep_layers:
            # Nothing to delete in kept foundation layers
            continue

        # Delete only foundation blocks in non-kept foundation layers
        for idx in by_y[y]:
            if blocks[idx]["id"] in foundation_ids:
                to_delete.add(idx)

    if not to_delete:
        # Nothing actually removed
        return blocks

    new_blocks = [
        b for idx, b in enumerate(blocks)
        if idx not in to_delete
    ]
    return new_blocks


def rebase_blocks_to_min_dy(
    blocks: List[Dict[str, Any]],
    target_min_dy: int,
) -> List[Dict[str, Any]]:
    """
    Shift all blocks in local Y so that the *new* minimum dy equals target_min_dy.

    new_dy = (old_dy - old_min) + target_min_dy

    This allows embedding by setting target_min_dy to a negative value
    (e.g. -1 to sink the lowest layer one block into the ground).
    """
    if not blocks:
        return blocks

    old_min = min(b["dy"] for b in blocks)
    # Even if old_min already equals target_min_dy, formula is harmless
    for b in blocks:
        b["dy"] = (b["dy"] - old_min) + target_min_dy

    return blocks


def recompute_meta(meta: Dict[str, Any],
                   blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Recompute size, top_y_local/world, and block_counts from remaining blocks.
    Does NOT move world_origin; world_origin.y stays as extracted base Y.
    """
    meta = dict(meta)

    if blocks:
        max_dx = max(b["dx"] for b in blocks)
        max_dy = max(b["dy"] for b in blocks)
        max_dz = max(b["dz"] for b in blocks)
        min_dx = min(b["dx"] for b in blocks)
        min_dy = min(b["dy"] for b in blocks)
        min_dz = min(b["dz"] for b in blocks)
        top_y_local = max_dy
    else:
        max_dx = max_dy = max_dz = 0
        min_dx = min_dy = min_dz = 0
        top_y_local = 0

    block_counts = Counter(b["id"] for b in blocks)

    meta["size"] = (
        max_dx - min_dx + 1,
        max_dy - min_dy + 1,
        max_dz - min_dz + 1,
    )
    meta["top_y_local"] = top_y_local
    meta["top_y_world"] = meta["world_origin"][1] + top_y_local
    meta["block_counts"] = dict(block_counts)

    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bp-dir", required=True,
                    help="Input directory with bp_XXX.json + blueprints_index.json")
    ap.add_argument("--out-dir", required=True,
                    help="Output directory for cleaned bp_XXX.json + new index")

    ap.add_argument(
        "--foundation-ids",
        type=str,
        default=None,
        help=(
            "Comma-separated list of block IDs treated as foundation. "
            "Default: "
            + ",".join(sorted(DEFAULT_FOUNDATION_IDS))
        ),
    )
    ap.add_argument(
        "--keep-foundation-layers",
        type=int,
        default=1,
        help=(
            "Number of topmost foundation layers (contiguous from bottom) to keep. "
            "0 = strip all foundation layers. Default: 1"
        ),
    )
    ap.add_argument(
        "--min-dy",
        type=int,
        default=-1,
        help=(
            "Target local dy for the lowest remaining block after cleaning. "
            "Default: -1 (embed lowest layer one block into the ground)."
        ),
    )

    args = ap.parse_args()

    foundation_ids = parse_foundation_ids(args.foundation_ids)
    keep_foundation_layers = args.keep_foundation_layers
    target_min_dy = args.min_dy

    bp_dir_abs = os.path.abspath(args.bp_dir)
    out_dir_abs = os.path.abspath(args.out_dir)

    if bp_dir_abs == out_dir_abs:
        print("[error] Output directory must be different from input directory!")
        print(f"        Input:  {bp_dir_abs}")
        print(f"        Output: {out_dir_abs}")
        return

    os.makedirs(args.out_dir, exist_ok=True)

    # Load existing index
    index_path = os.path.join(args.bp_dir, "blueprints_index.json")
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)

    new_index: Dict[str, Dict[str, Any]] = {}

    for bid, entry in index["blueprints"].items():
        in_path = os.path.join(args.bp_dir, entry["file"])
        data = load_bp(in_path)
        meta = data["meta"]
        blocks = data["blocks"]

        print(f"[info] {bid}: {len(blocks)} blocks before clean")

        # 1) Shave foundation according to parameters
        new_blocks = filter_blocks(
            blocks,
            foundation_ids=foundation_ids,
            keep_foundation_layers=keep_foundation_layers,
        )

        # 2) Rebase so lowest dy == target_min_dy
        new_blocks = rebase_blocks_to_min_dy(new_blocks, target_min_dy)

        # 3) Recompute meta
        new_meta = recompute_meta(meta, new_blocks)

        out_file = entry["file"]
        out_path = os.path.join(args.out_dir, out_file)

        save_bp(out_path, {"meta": new_meta, "blocks": new_blocks})

        new_index[bid] = {
            "file": out_file,
            "meta": new_meta,
        }

        removed = len(blocks) - len(new_blocks)
        print(
            f"[ok]  {bid}: {len(new_blocks)} blocks after clean "
            f"({removed} removed, min_dy={min(b['dy'] for b in new_blocks) if new_blocks else 'n/a'})"
        )

    # Write new index
    out_index_path = os.path.join(args.out_dir, "blueprints_index.json")
    with open(out_index_path, "w", encoding="utf-8") as f:
        json.dump({"blueprints": new_index}, f, ensure_ascii=False, indent=2)

    print("[done] cleaned blueprints and wrote new index")


if __name__ == "__main__":
    main()
