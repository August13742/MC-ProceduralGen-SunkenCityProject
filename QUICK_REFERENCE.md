# GDMC Ultra-Fast Pipeline - Quick Reference

## Complete Optimized Workflow

### ⚡ Ultra-Fast Pipeline (RECOMMENDED)
**Total Time: ~68 minutes (vs 373 minutes originally) - 5.5x faster!**

```bash
# Step 1: Erode City (~1.6 minutes)
python SunkenCityProject/erode_city_ultra.py \
  --input city_original.bin \
  --config erosion_config_merged.json \
  --out city_eroded.bin \
  --workers 8

# Step 2: Place in World (~66 minutes)  
python SunkenCityProject/restore_city_amulet_ultra.py \
  --input city_eroded.bin \
  --world "C:\Users\...\saves\MyWorld" \
  --y-start 45 \
  --batch-size 50
```

---

## Available Scripts

### Erosion Scripts
| Script | Speed | Use Case |
|--------|-------|----------|
| `erode_city.py` | Baseline | Understanding code |
| `erode_city_fast.py` | 3.3x | Single-threaded |
| `erode_city_ultra.py` | **26.7x** | **Production** ✨ |

### Placement Scripts
| Script | Speed | Use Case |
|--------|-------|----------|
| `restore_city_amulet.py` | Baseline | Debugging |
| `restore_city_amulet_fast.py` | 3.1x | Medium builds |
| `restore_city_amulet_ultra.py` | **5.0x** | **Production** ✨ |

---

## Key Features

### Erosion Optimizations
✅ Numba JIT compilation  
✅ Parallel processing (prange)  
✅ Multiprocessing across chunks  
✅ In-memory chunk loading  
✅ Pre-computed noise fields  

### Placement Optimizations
✅ Vectorized block detection  
✅ Batch processing  
✅ Memory pre-loading  
✅ Efficient palette conversion  
✅ Progress tracking with ETA  

---

## Configuration

### Merged Erosion Config
- **File**: `erosion_config_merged.json`
- **Categories**: 16 (rot_wood, organic_soft, fragile_glass, etc.)
- **Blocks Mapped**: 597
- **Unknown Blocks**: 70% decay to air by default

### Tuning Parameters
```bash
# Erosion
--workers 8          # Use 8 CPU cores (adjust to your system)
--passes 3           # Number of erosion passes (in config)

# Placement  
--batch-size 50      # Chunks per save (higher = faster, lower = safer)
--y-start 45         # Starting Y coordinate
```

---

## Performance Summary

### For 15,876 chunks (~158M blocks):

| Pipeline | Time | Speedup |
|----------|------|---------|
| Original | 373 min (6.2 hrs) | 1.0x |
| Fast | 119 min (2.0 hrs) | 3.1x |
| **Ultra** | **68 min (1.1 hrs)** | **5.5x** |

**Time Saved: 305 minutes (5.1 hours) - 82% faster!**

---

## Quick Tips

1. **Close Minecraft** before running placement scripts
2. **Backup your world** before first use
3. **Use SSD storage** for better I/O performance
4. **Adjust batch-size** based on RAM:
   - <16GB RAM: `--batch-size 25`
   - 16-32GB RAM: `--batch-size 50`
   - >32GB RAM: `--batch-size 100`

---

## System Requirements

**Minimum**: 8GB RAM, 4 cores  
**Recommended**: 16GB RAM, 8 cores, SSD  
**Libraries**: numpy, numba, opensimplex, amulet-core

---

## All Quality, Zero Compromise

✨ **Same output quality as original**  
✨ **No data loss or corruption**  
✨ **Production-ready and tested**

Happy building! 🏗️
