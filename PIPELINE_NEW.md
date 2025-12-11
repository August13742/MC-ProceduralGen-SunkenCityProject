# COMPLETE SUNKEN CITY PIPELINE
## Work entirely with .bin files - visualize in Amulet Editor before placing!

---

## 🎯 **NEW WORKFLOW** (Recommended)

### **Phase 1: Extraction** (~5 min)

```powershell
# Extract source city
python SunkenCityProject/extract_city.py `
    --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\Weston City V0.3" `
    --bounds -1500 -1600 1500 1600 `
    --min-y 50 `
    --prune-terrain `
    --out city_original.bin

# Extract target terrain (where city will be placed)
python SunkenCityProject/extract_terrain.py `
    --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" `
    --bounds -1500 -1600 1500 1600 `
    --output terrain_extracted.bin
```

### **Phase 2: City Processing** (~3 min)

```powershell
# 1. Erode city (~1.6 min)
python SunkenCityProject/erode_city_ultra.py `
    --input city_original.bin `
    --config erosion_config_merged.json `
    --out city_eroded.bin `
    --workers 8

# 2. Remove floating blocks (~1 min)
python SunkenCityProject/exposure_decay.py `
    --input city_eroded.bin `
    --output city_exposed.bin `
    --threshold 4 `
    --decay-chance 0.6
```

### **Phase 3: Merge & Blend** (~4 min)

```powershell
# 3. Merge city with terrain (~1 min)
python SunkenCityProject/merge_chunks.py `
    --city city_exposed.bin `
    --terrain terrain_extracted.bin `
    --output city_merged.bin `
    --city-y 20 `
    --strategy underwater

# 4. Underwater blending (~2-3 min)
python SunkenCityProject/blend_underwater.py `
    --input city_merged.bin `
    --output city_final.bin `
    --ocean-floor 60 `
    --city-level 20 `
    --all-stages
```

### **Phase 4: Visualization** (Optional - 0 min)

```powershell
# Open city_final.bin in Amulet Editor to preview before placing
# File > Open > Navigate to city_final.bin
# No need to load Minecraft!
```

### **Phase 5: Final Placement** (~66 min)

```powershell
# Place merged result (CLOSE MINECRAFT FIRST!)
python SunkenCityProject/restore_city_amulet_ultra.py `
    --input city_final.bin `
    --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" `
    --y-start -64 `
    --batch-size 100
```

**IMPORTANT:** Use `--y-start -64` because city_final.bin contains ABSOLUTE Y coordinates from the merge!

---

## **Total Time: ~78 minutes**
- Extraction: 5 min
- Processing: 3 min
- Merge/Blend: 4 min
- Placement: 66 min

---

## ✨ **Benefits of New Workflow**

### 1. **No World Backup Needed**
- Work with .bin files only
- Experiment freely without risking world corruption

### 2. **Amulet Preview**
- See exact result before placing
- Iterate on blending without touching Minecraft
- No game boot needed!

### 3. **True Underwater Adaptation**
- Reads actual ocean terrain
- Ground connections go to REAL ocean floor
- Vegetation placed in correct positions
- Sediment settles on surfaces

### 4. **Modular Pipeline**
```
Source City  ──> Erode ──> Exposure Decay ─┐
                                           ├──> Merge ──> Underwater Blend ──> Final
Target World ──> Extract Terrain ─────────┘
```

---

## 🎨 **Underwater Blending Stages**

### Stage 1: Ground Connection
- Vertical pillars from structures to ocean floor
- Stone/cobblestone at bottom
- Transitions to prismarine/mossy variants at top
- Noise-based distribution (70% chance per column)

### Stage 2: Vegetation Overgrowth
- Kelp, seagrass, coral on horizontal surfaces
- 1-4 blocks tall
- Natural clustering via noise
- Only where water is above

### Stage 3: Sediment Accumulation
- Gravel/sand/dirt on flat surfaces
- Simulates settling over time
- Noise-based for realism

---

## 🔧 **Tuning Parameters**

### More Aggressive Ground Support
```powershell
# Edit blend_underwater.py line ~42:
if noise_val < 0.5:  # was 0.3 = more columns
```

### Denser Vegetation
```powershell
# Edit blend_underwater.py line ~142:
if noise_val < 0.0:  # was -0.2 = 60% coverage
```

### More Sediment
```powershell
# Edit blend_underwater.py line ~229:
if noise_val + random.random() * 0.3 > 0.4:  # was 0.6 = more sediment
```

---

## 🎯 **Run Individual Stages**

You can run blending stages separately for fine control:

```powershell
# Just ground connection
python SunkenCityProject/blend_underwater.py --input city_merged.bin --output city_ground.bin --ground-connection

# Then add vegetation
python SunkenCityProject/blend_underwater.py --input city_ground.bin --output city_veg.bin --vegetation

# Finally add sediment
python SunkenCityProject/blend_underwater.py --input city_veg.bin --output city_final.bin --sediment
```

---

## 📋 **File Flow**

```
city_original.bin       (extracted city)
    ↓
city_eroded.bin        (after erosion rules)
    ↓
city_exposed.bin       (floating blocks removed)
    ↓                  ↙
city_merged.bin       ← terrain_extracted.bin (target world)
    ↓
city_final.bin         (underwater adapted)
    ↓
[Place in world or view in Amulet]
```

---

## 💡 **Pro Tips**

1. **Iterate on blending without re-processing city**
   - Keep `city_exposed.bin` 
   - Re-run merge + blend with different parameters
   - Much faster than full pipeline!

2. **Preview in Amulet before placing**
   - Install Amulet Editor
   - File > Open > city_final.bin
   - Check results visually
   - Iterate if needed

3. **Adjust ocean floor dynamically**
   - If terrain varies, blend_underwater finds real floor per column
   - `--ocean-floor` is just a hint for search range

4. **Match bounds exactly**
   - City bounds and terrain bounds MUST match
   - Otherwise merge will have gaps

---

## 🆚 **Old vs New Pipeline**

### Old Way:
```
Extract → Erode → [Structural Blend?] → Place → Hope it looks good → Restore backup → Try again
```
**Problems:**
- No terrain awareness
- Can't preview
- Risk world corruption
- Slow iteration

### New Way:
```
Extract City + Terrain → Erode → Merge → Underwater Blend → Preview in Amulet → Place once
```
**Benefits:**
- ✅ Terrain-aware ground connection
- ✅ Preview before placing
- ✅ No world risk
- ✅ Fast iteration on blending
- ✅ True underwater feel

---

## 🚀 **Quick Start (Copy-Paste)**

```powershell
# Full pipeline - one shot
python SunkenCityProject/extract_city.py --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\Weston City V0.3" --bounds -1500 -1600 1500 1600 --min-y 50 --prune-terrain --out city_original.bin

python SunkenCityProject/extract_terrain.py --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" --bounds -1500 -1600 1500 1600 --output terrain_extracted.bin

python SunkenCityProject/erode_city_ultra.py --input city_original.bin --config erosion_config_merged.json --out city_eroded.bin --workers 8

python SunkenCityProject/exposure_decay.py --input city_eroded.bin --output city_exposed.bin --threshold 4 --decay-chance 0.6

python SunkenCityProject/merge_chunks.py --city city_exposed.bin --terrain terrain_extracted.bin --output city_merged.bin --city-y 20 --strategy underwater

python SunkenCityProject/blend_underwater.py --input city_merged.bin --output city_final.bin --ocean-floor 60 --city-level 20 --all-stages

# Preview in Amulet Editor (optional)
# Then place:
python SunkenCityProject/restore_city_amulet_ultra.py --input city_final.bin --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" --y-start -64 --batch-size 100
```
