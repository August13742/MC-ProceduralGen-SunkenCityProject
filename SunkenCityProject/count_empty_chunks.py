"""Count chunks that are entirely air in a compressed .bin dump."""

import argparse
import sys
import pathlib

# Ensure SunkenCityProject directory is importable when running from repo root
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from city_utils import read_bin_generator
import numpy as np


def main():
    parser = argparse.ArgumentParser(description="Count all-air chunks in .bin file")
    parser.add_argument("--input", "-i", default="city_original.bin", help="Input .bin file")
    args = parser.parse_args()

    total = 0
    empty = 0

    for cx, cz, blocks, palette in read_bin_generator(args.input):
        total += 1
        # Blocks stored as uint16 indices; index 0 is expected to be air
        if (blocks == 0).all():
            empty += 1

    print(f"Total chunks: {total}")
    print(f"Empty chunks (all air): {empty}")
    if total:
        pct = (empty / total) * 100
        print(f"Fraction empty: {pct:.2f}%")


if __name__ == "__main__":
    main()
