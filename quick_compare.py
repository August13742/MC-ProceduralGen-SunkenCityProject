import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'SunkenCityProject'))

from city_utils import read_bin_generator
from collections import Counter
import numpy as np

blocks1 = Counter()
for _, _, b, p in read_bin_generator('city_original.bin'):
    unique, counts = np.unique(b, return_counts=True)
    for i, c in zip(unique, counts):
        blocks1[p[i]] += c

blocks2 = Counter()
for _, _, b, p in read_bin_generator('city_exposed.bin'):
    unique, counts = np.unique(b, return_counts=True)
    for i, c in zip(unique, counts):
        blocks2[p[i]] += c

print(f"city_original.bin: {blocks1['minecraft:small_amethyst_bud']:,}")
print(f"city_exposed.bin:  {blocks2['minecraft:small_amethyst_bud']:,}")
print(f"Reduction: {(1 - blocks2['minecraft:small_amethyst_bud']/blocks1['minecraft:small_amethyst_bud'])*100:.1f}%")
