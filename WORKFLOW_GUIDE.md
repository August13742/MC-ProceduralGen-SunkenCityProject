# Sunken City Pipeline - Complete Workflow

## Overview
Complete pipeline for creating an overgrown, structurally-connected sunken city with proper physics.

## Pipeline Steps

### 1. **Erosion** (Required)
Applies decay rules to create the sunken city aesthetic.

```powershell
python SunkenCityProject/erode_city_ultra.py `
    --input city_original.bin `
    --config erosion_config_merged.json `
    --out city_eroded.bin `
    --workers 8
```

**Time:** ~1.6 minutes  
**What it does:**
- Applies 3 passes of erosion
- Organic materials (leaves, plants) → 100% decay to air
- Fragile blocks (glass, amethyst buds) → 90% decay
- Universal 25% decay chance for all uncategorized blocks
- Creates weathered, overgrown appearance

---

### 2. **Structural Blending** (Optional but Recommended)
Connects floating structures to the ground with organic support columns.

```powershell
python SunkenCityProject/structural_blend.py `
    --input city_eroded.bin `
    --output city_blended.bin `
    --ground-level 60 `
    --city-level 20 `
    --blend-radius 3
```

**Time:** ~2-3 minutes  
**What it does:**
- Creates vertical support pillars from city (Y=20) to ground (Y=60)
- Uses stone/cobblestone at bottom, transitions to dirt/mud at top
- Adds hanging vines and moss for organic feel
- Prevents "floating structure" appearance

**Parameters:**
- `--ground-level 60`: Natural terrain height
- `--city-level 20`: Where city was placed
- `--blend-radius 3`: How far to blend horizontally

---

### 3. **Block Placement** (Required)
Places the processed city into your Minecraft world.

```powershell
python SunkenCityProject/restore_city_amulet_ultra.py `
    --input city_blended.bin `
    --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" `
    --y-start 20 `
    --batch-size 100
```

**Time:** ~66 minutes  
**What it does:**
- Loads all chunks into memory
- Places blocks in batches (100 chunks per save)
- Updates world files

**⚠️ CRITICAL:** World must be closed in Minecraft before running!

---

### 4. **Physics Update** (Optional - Fixes Visual Glitches)
Triggers block updates to fix waterlogging and bubble-wrap effects.

```powershell
python SunkenCityProject/trigger_physics.py `
    --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" `
    --chunks-file city_blended.bin `
    --y-start 20 `
    --y-end 100 `
    --method force-update
```

**Time:** ~10-20 minutes  
**What it does:**
- Forces block updates for waterlogged blocks
- Fixes visual glitches with kelp, seagrass, amethyst
- Updates neighbor blocks to show correctly

**Methods:**
- `force-update`: More thorough, slower (recommended)
- `markers`: Faster, less comprehensive

---

## Quick Reference: Complete Pipeline

### Full Pipeline (with all stages)
```powershell
# Step 1: Erode
python SunkenCityProject/erode_city_ultra.py --input city_original.bin --config erosion_config_merged.json --out city_eroded.bin --workers 8

# Step 2: Remove floating blocks (OPTIONAL)
python SunkenCityProject/exposure_decay.py --input city_eroded.bin --output city_exposed.bin --threshold 4 --decay-chance 0.6

# Step 3: Blend structures to ground (OPTIONAL)
python SunkenCityProject/structural_blend.py --input city_exposed.bin --output city_blended.bin --ground-level 60 --city-level 20 --blend-radius 3

# Step 4: Place (CLOSE MINECRAFT FIRST!)
python SunkenCityProject/restore_city_amulet_ultra.py --input city_blended.bin --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" --y-start 20 --batch-size 100

# Step 5: Fix physics (OPTIONAL, CLOSE MINECRAFT FIRST!)
python SunkenCityProject/trigger_physics.py --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" --chunks-file city_blended.bin --y-start 20 --y-end 100
```

**Total Time:** ~75-95 minutes

### Recommended Pipeline (balanced)
```powershell
# 1. Erode
python SunkenCityProject/erode_city_ultra.py --input city_original.bin --config erosion_config_merged.json --out city_eroded.bin --workers 8

# 2. Remove floating blocks
python SunkenCityProject/exposure_decay.py --input city_eroded.bin --output city_exposed.bin --threshold 4 --decay-chance 0.6

# 3. Place
python SunkenCityProject/restore_city_amulet_ultra.py --input city_exposed.bin --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" --y-start 20 --batch-size 100
```

**Total Time:** ~69 minutes

### Fast Pipeline (minimal)
```powershell
# Erode
python SunkenCityProject/erode_city_ultra.py --input city_original.bin --config erosion_config_merged.json --out city_eroded.bin --workers 8

# Place
python SunkenCityProject/restore_city_amulet_ultra.py --input city_eroded.bin --world "C:\Users\augus\AppData\Roaming\.minecraft\saves\GDMC_Test (2)" --y-start 20 --batch-size 100
```

**Total Time:** ~68 minutes

---

## Erosion Config Highlights

### New Features in `erosion_config_merged.json`:

1. **Organic Complete Decay** (NEW)
   - All leaves, grass, flowers, vines → 100% air
   - Creates "long abandoned" feel
   - 67 plant types affected

2. **Universal Decay** (NEW)
   - 25% decay chance for ALL uncategorized blocks
   - Prevents structures from being too intact
   - Configurable via `universal_decay_chance`

3. **Fragile Decorative** (NEW)
   - Amethyst buds/clusters → 90% air, 10% amethyst block
   - No longer immune to decay

4. **16 Total Categories:**
   - `organic_complete_decay` (NEW) - plants/leaves
   - `rot_wood` - wood → air, mossy variants
   - `organic_soft` - wool/beds → air, mud
   - `fragile_glass` - glass → air, prismarine
   - `fragile_decorative` (NEW) - amethyst → air
   - `stone_base` - stone → cracked/mossy
   - `mineral_hard` - ores/obsidian → minimal decay
   - `metal_structural` - iron → air, prismarine
   - `clay_ceramic` - terracotta → cracked
   - `concrete` - concrete → powder, mud
   - `vegetation` - blocks → air, dirt, mud
   - `ice_snow` - ice → water
   - `soil` - dirt → mud, gravel
   - `sand_gravel` - sand → gravel
   - `fluid` - water/lava preservation
   - `coral` - coral → air, cobble

---

## Performance Stats

| Step | Time | Speed |
|------|------|-------|
| Erosion (15,876 chunks) | 95s | 167 chunks/s |
| Blending | ~2-3 min | - |
| Placement | 66 min | 240 chunks/s |
| Physics | 10-20 min | - |
| **Total** | **~70-90 min** | - |

---

## Troubleshooting

### "universal_minecraft" Warnings
Delete Python cache:
```powershell
Remove-Item -Recurse -Force SunkenCityProject\__pycache__
```

### Structures Still Floating
- Increase `--blend-radius` (try 4-5)
- Lower `--ground-level` if terrain is lower than 60
- Check `--city-level` matches placement Y

### Too Much Intact Structure
- Increase `universal_decay_chance` in config (try 0.35-0.5)
- Increase `passes` in config (try 4-5)
- Increase `erosion_rate` (try 0.7)

### Not Enough Overgrown Feel
- Structural blending adds vines/moss automatically
- Consider manually adding more vegetation post-placement

### Physics Issues Persist
- Reload chunks in-game (fly away, return)
- Restart Minecraft
- Some waterlogging is a Minecraft limitation

---

## Config Tuning Guide

### For MORE Decay:
```json
{
    "global_settings": {
        "erosion_rate": 0.7,        // was 0.5
        "passes": 4,                 // was 3
        "universal_decay_chance": 0.4  // was 0.25
    }
}
```

### For LESS Decay:
```json
{
    "global_settings": {
        "erosion_rate": 0.3,        // was 0.5
        "passes": 2,                 // was 3
        "universal_decay_chance": 0.15  // was 0.25
    }
}
```

### For More Structural Variation:
Adjust category replacements. Example for stone:
```json
"stone_base": {
    "replacements": [
        ["minecraft:air", 0.3],              // was 0.2
        ["minecraft:mossy_cobblestone", 0.3], // was 0.15
        ["minecraft:cracked_stone_bricks", 0.2], // was 0.1
        ["minecraft:gravel", 0.2]            // was 0.05
    ]
}
```

---

## File Outputs

- `city_eroded.bin` - After erosion (4.5MB)
- `city_blended.bin` - After structural blending (5-6MB)
- Minecraft world files - Modified region files

**Backup your world before running placement!**
