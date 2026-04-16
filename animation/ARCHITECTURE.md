# Animation System — Architecture & Onboarding

Quick-start reference for the GDMC **Construction Animation System**.
Generates frame-by-frame construction sequences from block blueprints,
outputting to GIF/MP4 for offline preview or placing blocks live in
Minecraft via the GDMC-HTTP interface.

## Directory Layout

```
animation/
├── cli.py               # Argparse CLI (animate / preview subcommands)
├── config.py            # TOML → frozen dataclass config loader
├── strategies.py        # Block ordering generators (5 strategies)
├── preview.py           # Offline renderer: IncrementalScene → GIF/MP4/PNG
├── placer.py            # GDMC live placement engine (gdpc Editor)
├── stages.py            # Multi-stage orchestrator (build → erode → diff)
├── diff.py              # Block-level diff between two blueprint states
├── player_tracking.py   # Player position polling via GDMC HTTP
├── __main__.py          # Entry: python -m animation → cli.main()
└── test_building.json   # Sample 974-block blueprint fixture
```

## Pipeline Overview

```
  TOML Config
       │
       ├── load_config_with_stages()
       │     AnimationConfig (frozen dataclass)
       │     list[Stage] (optional — empty = single-stage mode)
       │
       ▼
  Origin Resolution
       │
       ├── Static: origin_x/y/z from config
       └── Dynamic: poll_player_position() via GDMC HTTP
       │
       ▼
  Block Loading
       │
       └── load_blocks(config) → list[{dx, dy, dz, id, properties}]
             Supports: blueprint_json, vps_prefab, raw_block_array
       │
       ▼
  Strategy Generator
       │
       └── get_strategy_generator(name, blocks) → BatchGenerator
             Yields batches of blocks in animation order
       │
       ├────────────────────┐
       ▼                    ▼
   [preview]            [animate]
       │                    │
   IncrementalScene     gdpc Editor
   + render_single_view    placeBlock per batch
   per-batch frame         flush + sleep
       │                    │
       ▼                    ▼
   _write_output()      Minecraft world
   → GIF / MP4 / PNG
```

## Ordering Strategies

| Strategy | Behaviour | Typical use |
|----------|-----------|-------------|
| `y_up` | Batches grouped by ascending Y | Standard bottom-up construction |
| `y_down` | Batches grouped by descending Y | Top-down demolition/erosion |
| `radial_out` | Expanding XZ distance shells from centroid | Circular growth effect |
| `random` | Shuffled order, configurable batch size | Organic/chaotic appearance |
| `structural_phases` | Foundation → walls → roof → interior, Y-up within each | Realistic build sequence |

All strategies yield `list[dict]` batches. The strategy system auto-filters
kwargs to match each function's signature (e.g. `structural_phases` receives
`foundation_ids`, `roof_ids`, `interior_ids`; others ignore them).

## IncrementalScene (preview.py)

The core rendering primitive for frame-by-frame animation. Maintains a
`trimesh.Scene` incrementally — O(batch_size) per frame, not O(total_blocks).

```
IncrementalScene(adjacency_enabled=True)
       │
       ├── add_block({x, y, z, id, properties})
       │     1. Register in BlockGrid spatial index
       │     2. resolve_connections() if connectable (fence/wall/pane)
       │     3. create_coloured_block_mesh(id, props) via VPS
       │     4. Translate mesh to (x, y, z), insert into Scene
       │     5. _update_neighbours(): re-resolve affected neighbours
       │
       ├── remove_block(x, y, z)
       │     1. Delete scene node "b_{x}_{y}_{z}"
       │     2. Remove from BlockGrid
       │     3. Re-resolve affected neighbours
       │
       └── .scene → trimesh.Scene (pass to render_single_view)
```

Each frame, `render_single_view()` is called on the scene to produce a
base64 PNG, which is decoded into a PIL Image and accumulated.

## Multi-Stage System

Stages enable sequencing of different animation phases (build, then erode,
then overlay modifications). Each stage has its own strategy and timing.

| Mode | Behaviour |
|------|-----------|
| `build` | Load blueprint from `source_file`, animate all blocks |
| `erode` | Run `erosion_logic.erode_blueprint()` on previous state, animate only the diff |
| `diff_overlay` | Generic diff between previous state and a new source file |

**State threading:** `iterate_stages()` maintains `current_state` across
stages. Each stage receives the previous state and returns both the blocks
to animate and the resulting state for the next stage.

**Diff computation** (`diff.py`): compares two block lists by position.
Removals become `minecraft:air` placements so the strategy system handles
them without special-casing.

## TOML Configuration

```toml
[source]
source_file = "blueprints_cleaned/bp_000.json"
source_format = "blueprint_json"              # blueprint_json | vps_prefab | raw_block_array

[placement]
origin_x = 0
origin_y = 64
origin_z = 0
gdmc_host = "localhost:9000"
clear_area_first = true
use_player_tracking = false                   # true → origin from player position

[strategy]
strategy = "y_up"                             # y_up | y_down | radial_out | random | structural_phases

[timing]
per_block_delay_ms = 0                        # Delay between individual blocks in a batch
per_layer_delay_ms = 200                      # Delay between batches/layers
flush_every_n_blocks = 64                     # GDMC buffer flush interval

[preview]
preview_enabled = false
preview_output_dir = "frames"
preview_view = "iso_right"                    # Any view from CAMERA_VIEWS
preview_width = 512
preview_height = 512
preview_bg_colour = [30, 30, 30]
preview_output_format = "gif"                 # gif | mp4 | png
preview_fps = 10
preview_hold_last_frames = 15                 # Pause on final frame

[structural]                                  # Only for structural_phases strategy
foundation_ids = ["minecraft:stone", ...]
roof_ids = ["minecraft:dark_oak_stairs", ...]
interior_ids = ["minecraft:torch", ...]

# Multi-stage (optional — overrides [strategy] when present)
[[stages]]
name = "construct"
mode = "build"
strategy = "y_up"
per_layer_delay_ms = 200

[[stages]]
name = "erode"
mode = "erode"
strategy = "y_down"
erosion_seed = 1337
erosion_aggression = 0.6
erosion_passes = 3
```

## Player Tracking

When `use_player_tracking = true`, the system polls the GDMC server to find
the nearest player's position and uses it as the placement origin.

Two strategies are tried in order:
1. `GET /players` — clean JSON endpoint (GDMC-HTTP 1.x+)
2. `POST /command` with `data get entity @p Pos` — regex-parses NBT response

`poll_player_position()` retries up to 10 times at 1-second intervals.
Raises `RuntimeError` if no player is found.

## GDMC Live Placer

`run_animation()` / `run_multistage_animation()` in `placer.py`:

1. Create `gdpc.Editor(buffering=True, host=config.gdmc_host)`
2. If `clear_area_first`: fill bounding box with air, flush
3. Iterate strategy batches:
   - `editor.placeBlock((ox+dx, oy+dy, oz+dz), Block(id, props))`
   - Flush every `flush_every_n_blocks` blocks
   - Sleep `per_block_delay_ms` between blocks, `per_layer_delay_ms` between batches
4. Progress logged every 5 batches

## CLI Usage

```bash
# Offline preview (no Minecraft server needed)
python -m animation preview --config animation_config.toml
python -m animation preview --config animation_config.toml --format mp4 --output output/

# Live placement (requires GDMC-HTTP mod running)
python -m animation animate --config animation_config.toml
```

## Dependencies

- **VPS renderer** (`vps.*`) — mesh generation + single-view rendering
- **gdpc** — GDMC-HTTP client library (live placement only)
- **Pillow** — frame assembly + GIF output
- **ffmpeg** — MP4 encoding (must be on PATH; GIF works without it)

Manage with UV:
```bash
cd Minecraft-Voxel-Renderer && uv sync
```

## Key Design Decisions

1. **Incremental scene updates** — only modified blocks are re-meshed per frame. Adjacency re-resolution is scoped to affected neighbours only.
2. **Strategy/timing separation** — ordering logic is pure (generators yielding batches), timing is applied by the consumer (placer or preview renderer). This makes strategies testable and reusable.
3. **Frozen config** — `AnimationConfig` is a frozen dataclass. Use `dataclasses.replace()` to derive variants.
4. **Diff-based erosion** — erosion stages do not re-animate the entire structure. Only the delta (removed/mutated blocks) is animated, with removals converted to air placements.
