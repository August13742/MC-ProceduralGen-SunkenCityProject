"""
Performance test: Compare original vs Numba-accelerated erosion
"""
import json
import time
import sys
sys.path.insert(0, 'SunkenCityProject')

from city_utils import read_bin_generator
from erode_city import HybridEroder
from erode_city_fast import FastEroder

# Load config
with open('erosion_config_merged.json') as f:
    config = json.load(f)

# Load first chunk only for testing
print("Loading test chunk...")
for cx, cz, blocks, palette in read_bin_generator('city_original.bin'):
    test_chunk = (cx, cz, blocks.copy(), list(palette))
    break

print(f"Test chunk size: {blocks.shape}")
print(f"Palette size: {len(palette)}")

# Test original version
print("\n=== Testing Original Version ===")
eroder_old = HybridEroder(config)
start = time.time()
result_old = eroder_old.process_chunk(test_chunk[2].copy(), list(test_chunk[3]), test_chunk[0], test_chunk[1])
time_old = time.time() - start
print(f"Time: {time_old:.3f} seconds")

# Test Numba version
print("\n=== Testing Numba-Optimized Version ===")
eroder_fast = FastEroder(config)

# First run (includes JIT compilation)
print("First run (includes JIT compilation)...")
start = time.time()
result_fast = eroder_fast.process_chunk(test_chunk[2].copy(), list(test_chunk[3]), test_chunk[0], test_chunk[1])
time_first = time.time() - start
print(f"Time (with JIT compilation): {time_first:.3f} seconds")

# Second run (JIT already compiled)
print("Second run (JIT cached)...")
start = time.time()
result_fast2 = eroder_fast.process_chunk(test_chunk[2].copy(), list(test_chunk[3]), test_chunk[0], test_chunk[1])
time_fast = time.time() - start
print(f"Time (cached): {time_fast:.3f} seconds")

# Compare results
print("\n=== Performance Comparison ===")
print(f"Original:     {time_old:.3f}s")
print(f"Numba (1st):  {time_first:.3f}s")
print(f"Numba (2nd):  {time_fast:.3f}s")
print(f"Speedup:      {time_old/time_fast:.1f}x faster")

print("\n=== Validation ===")
blocks_changed_old = (result_old[0] != test_chunk[2]).sum()
blocks_changed_fast = (result_fast2[0] != test_chunk[2]).sum()
print(f"Blocks changed (original): {blocks_changed_old}")
print(f"Blocks changed (fast):     {blocks_changed_fast}")
print(f"Results similar: {abs(blocks_changed_old - blocks_changed_fast) < blocks_changed_old * 0.1}")
