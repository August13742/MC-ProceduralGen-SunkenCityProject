"""Export all unique block types found inside a compressed .bin dump."""

import argparse
import json
from collections import Counter

import numpy as np

from city_utils import read_bin_generator, read_bin_palette


def collect_block_counts(filename):
    """Return block counts and chunk tally for an entire dump."""
    palette = read_bin_palette(filename)
    counts = Counter()
    chunk_count = 0

    for _, _, blocks, _ in read_bin_generator(filename):
        chunk_count += 1
        unique_indices, frequencies = np.unique(blocks, return_counts=True)
        for idx, freq in zip(unique_indices, frequencies):
            counts[palette[idx]] += int(freq)

    return palette, counts, chunk_count


def main():
    parser = argparse.ArgumentParser(
        description="Create a JSON file describing the unique blocks in an .bin dump"
    )
    parser.add_argument("--input", "-i", required=True, help="Input .bin file")
    parser.add_argument(
        "--output", "-o", default="unique_blocks.json", help="Output JSON path"
    )
    parser.add_argument(
        "--include-counts", action="store_true", help="Add per-block counts and chunk totals"
    )

    args = parser.parse_args()

    palette = read_bin_palette(args.input)
    payload = {
        "source": args.input,
        "unique_blocks": palette,
        "palette_size": len(palette),
    }

    if args.include_counts:
        block_palette, counts, chunks = collect_block_counts(args.input)
        payload.update(
            {
                "chunks_analyzed": chunks,
                "counts": dict(counts),
            }
        )
        # palette should already match read_bin_palette
        assert block_palette == palette, "Palette mismatch while counting"

    with open(args.output, "w", encoding="utf-8") as out_file:
        json.dump(payload, out_file, indent=2)

    print(f"Wrote {len(palette)} unique blocks to {args.output}")
    if args.include_counts:
        print(f"Counted {sum(payload['counts'].values()):,} blocks across {payload['chunks_analyzed']} chunks")


if __name__ == "__main__":
    main()
