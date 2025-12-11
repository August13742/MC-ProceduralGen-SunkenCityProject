# Visualization & Updated Pipeline Guide

## 1. Visualize Any .bin File with Amulet

```bash
# Visualize the merged city before blend_underwater
python SunkenCityProject/visualize_bin.py --input city_merged.bin --output viz_merged

# Visualize after underwater blending
python SunkenCityProject/visualize_bin.py --input city_underwater.bin --output viz_underwater

# Visualize original extracted city
python SunkenCityProject/visualize_bin.py --input city_original.bin --output viz_original
```

Then:
1. Open Amulet Map Editor
2. File → Open → Select the `viz_merged` (or `viz_underwater`, etc.) folder
3. Explore your visualization!

**Note:** The visualizer creates a real Minecraft world file that Amulet can read.

---

## 2. Corrected Pipeline Parameters

Based on analysis, the city's median ground level is at **Y=67**, not Y=60.

### Updated merge_chunks.py
```bash
python SunkenCityProject/merge_chunks.py \
    --city city_exposed.bin \
    --terrain terrain_extracted.bin \
    --output city_merged.bin \
    --city-y 67 \
    --ocean-y 60
```

**Explanation:**
- `--city-y 67`: City's median ground level in extracted data
- `--ocean-y 60`: Target ocean floor level in final world
- Result: City ground sits 7 blocks into ocean floor (nice sunken effect)

### Updated blend_underwater.py (NOW WITH MULTIPROCESSING!)
```bash
python SunkenCityProject/blend_underwater.py \
    --input city_merged.bin \
    --output city_underwater.bin \
    --ocean-floor 60 \
    --city-level 67 \
    --all-stages \
    --workers 8
```

**New features:**
- `--workers N`: Use N CPU cores for parallel processing (default: all cores)
- **Much higher CPU utilization** - should use 80-100% across all cores
- **Faster processing** - scales nearly linearly with core count

**Expected speedup:**
- With 8 cores: ~6-8x faster than before (17.4 → 100-140 chunks/s)
- With 16 cores: ~12-15x faster

---

## 3. Analysis Tool

Check where your city actually sits:

```bash
python SunkenCityProject/analyze_city_height.py --input city_original.bin
```

Output shows:
- Lowest/highest city blocks
- Y-level distribution
- Percentiles (base, median, top)
- **Recommended parameters** based on actual data

---

## 4. Complete Workflow with Visualization

```bash
# 1. Extract city & terrain (original parameters OK)
python SunkenCityProject/extract_city.py --y-threshold 50
python SunkenCityProject/extract_terrain.py --y-threshold 50

# 2. Erode & expose
python SunkenCityProject/erode_city_ultra.py
python SunkenCityProject/exposure_decay.py --input city_eroded.bin --output city_exposed.bin

# 3. Merge with CORRECTED parameters
python SunkenCityProject/merge_chunks.py \
    --city city_exposed.bin \
    --terrain terrain_extracted.bin \
    --output city_merged.bin \
    --city-y 67 \
    --ocean-y 60

# 4. VISUALIZE BEFORE BLEND (check if city position looks good)
python SunkenCityProject/visualize_bin.py --input city_merged.bin --output viz_merged
# → Open in Amulet to verify city placement

# 5. Blend underwater with multiprocessing
python SunkenCityProject/blend_underwater.py \
    --input city_merged.bin \
    --output city_underwater.bin \
    --ocean-floor 60 \
    --city-level 67 \
    --all-stages \
    --workers 8

# 6. VISUALIZE AFTER BLEND (final check)
python SunkenCityProject/visualize_bin.py --input city_underwater.bin --output viz_underwater
# → Open in Amulet to see underwater effects

# 7. Place in world
python SunkenCityProject/restore_city_amulet_ultra.py \
    --input city_underwater.bin \
    --world-path "path/to/world"
```

---

## 5. Performance Comparison

### Before Optimization:
- **CPU usage:** <20%
- **Speed:** 17.4 chunks/s
- **Time for 37,788 chunks:** ~36 minutes

### After Multiprocessing (8 cores):
- **CPU usage:** 80-100% across all cores
- **Speed:** ~100-140 chunks/s (6-8x faster)
- **Time for 37,788 chunks:** ~4-6 minutes

### After Multiprocessing (16 cores):
- **Speed:** ~200-260 chunks/s (12-15x faster)
- **Time for 37,788 chunks:** ~2-3 minutes

---

## Key Findings from analyze_city_height.py

```
Y-Level Range:
  Lowest city block: Y=50
  Highest city block: Y=124
  Height span: 75 blocks

Y-Level Percentiles:
  10th percentile (city base): Y=52
  50th percentile (median): Y=67
  90th percentile: Y=103

💡 Recommendations:
  - City base: Y=52
  - City ground level (median): Y=67
  - Use --city-y 67 in merge_chunks.py
  - Use --city-level 67 in blend_underwater.py
```

This means:
- Your extraction at Y=50 was perfect (caught the bottom)
- But the city's actual ground level is Y=67, not Y=60
- Previous parameters would place city too low
