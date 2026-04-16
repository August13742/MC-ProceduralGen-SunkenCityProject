# Animation System — Architecture & Onboarding

Quick-start reference for the GDMC **Construction Animation System**.
It supports three practical workflows:

1. build a structure live in Minecraft
2. clear / rebuild it in-game without tabbing back to the shell
3. apply in-place modifications by diffing the current built state against a
   target blueprint or configured stage sequence

Offline preview still renders GIF/MP4 without needing Minecraft.

## Directory Layout

```
animation/
├── cli.py               # Argparse CLI (animate / modify / control / preview / clear / status)
├── config.py            # TOML → frozen dataclass config loader
├── controller.py        # In-game trigger controller (clear / rebuild / modify)
├── session.py           # Persisted origin + logical block-state snapshot
├── strategies.py        # Block ordering generators (5 strategies)
├── preview.py           # Offline renderer: IncrementalScene → GIF/MP4/PNG
├── placer.py            # GDMC live placement engine (gdpc Editor)
├── stages.py            # Multi-stage orchestrator (build → erode → diff)
├── diff.py              # Block-level diff between two blueprint states
├── player_tracking.py   # Player pose polling + grounded player-relative spawn
├── __main__.py          # Entry: python -m animation → cli.main()
└── test_building.json   # Sample 974-block blueprint fixture
```

## Pipeline Overview

```
  TOML Config
       │
       ├── load_config_with_stages()
       │     AnimationConfig (frozen dataclass)
       │     list[Stage] (optional)
       │
       ▼
  Session State
       │
       ├── .animation_session.json         # origin + bounds + metadata
       └── .animation_session_blocks.json  # current logical block state
       │
       ▼
  Origin Resolution
       │
       ├── Reuse sticky origin from session if present
       ├── Otherwise resolve from config origin
       └── Or resolve player-relative spawn:
             pose -> facing -> footprint-aware offset -> ground raycast
       │
       ▼
  Block Loading / Target State
       │
       ├── build: load_blocks(config)
       ├── modify: current session state vs target blueprint diff
       └── multi-stage: resolve_stage_blocks(...)
       │
       ▼
  Strategy Generator
       │
       └── get_strategy_generator(name, blocks) -> batch generator
       │
       ├────────────────────┐
       ▼                    ▼
    [preview]      [animate / modify / control]
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

## Modes

### 1. Build

`animate` builds the configured `source_file`.

- if a matching session exists: reuse its stored origin
- otherwise: resolve a fresh origin (usually player-relative)
- after completion: persist both session metadata and the resulting block state

### 2. Rebuild / Clear (in-game)

`control` keeps a lightweight trigger listener alive:

- `/trigger animctl set 1` -> clear current build and forget sticky origin
- `/trigger animctl set 2` -> build/rebuild from config
- `/trigger animctl set 3` -> modify current build in place

This minimises shell usage to a single long-running process.

### 3. Modify / Upgrade

`modify` transforms the currently-built structure in place.

Two resolution paths exist:

1. if non-`build` stages are configured: run those stages against the persisted
   current state
2. otherwise: diff the persisted current state against a target blueprint and
   place only changed blocks

Target blueprint selection order:

1. `modify_source_file` if set
2. otherwise `source_file`

This is the current "upgrade" path: no full clear, no full rebuild, only the
delta is placed.

## Multi-Stage System

Stages enable sequencing of different animation phases (build, then erode,
then overlay modifications). Each stage has its own strategy and timing.

| Mode | Behaviour |
|------|-----------|
| `build` | Load blueprint from `source_file`, animate all blocks |
| `erode` | Run `erosion_logic.erode_blueprint()` on previous state, animate only the diff |
| `diff_overlay` | Generic diff between previous state and a new source file |

**State threading:** `iterate_stages()` maintains `current_state` across
stages. The live placer also persists the final resulting state to
`.animation_session_blocks.json`, so later modify passes can start from the
actual previously-built logical state.

**Diff computation** (`diff.py`): compares two block lists by position.
Removals become `minecraft:air` placements so the strategy system handles
them without special-casing.

## TOML Configuration

```toml
[source]
source_file = "blueprints_cleaned/bp_000.json"
modify_source_file = "blueprints_cleaned/bp_001.json"  # Optional mode-3 target blueprint
source_format = "blueprint_json"              # blueprint_json | vps_prefab | raw_block_array

[placement]
origin_x = 0
origin_y = 64
origin_z = 0
gdmc_host = "http://localhost:9000"
clear_area_first = true
use_player_tracking = true                    # resolve relative to player by default
use_ground_raycast = true                     # raycast target XZ down to ground
player_clearance_blocks = 3                   # keep footprint away from player
player_spawn_margin_blocks = 2                # extra gap beyond footprint depth
enable_in_game_controls = true
control_objective = "animctl"
clear_item_drops_first = true

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

## Player-Relative Placement

When `use_player_tracking = true`, placement is not on the player's face and
not simply at the player's block position. The resolver computes a safe spawn:

1. poll nearest player pose (`Pos` + `Rotation`)
2. derive facing direction from yaw
3. compute a forward offset from the actual structure footprint depth
4. add configured clearance + margin so the player is outside the build bounds
5. raycast the chosen X/Z column downward to stable ground
6. anchor the blueprint so its lowest layer sits on that ground

After the first build, the resolved origin is sticky and reused until `clear`
deletes the session.

## Session State

Two files are persisted in the working directory:

- `.animation_session.json`: origin, bounds, source/config metadata
- `.animation_session_blocks.json`: current logical block list

This enables:

- sticky placement origin between builds
- in-game clear/rebuild behaviour
- in-place modify/upgrade passes without rebuilding from scratch

## GDMC Live Placer

`run_animation()` / `run_multistage_animation()` / `run_modify_animation()` in `placer.py`:

1. Create `gdpc.Editor(buffering=True, host=config.gdmc_host)`
2. If clearing is required: fill bounding box with air with `doBlockUpdates=False`
   and `spawnDrops=False`, then purge dropped item entities in the cleared box
3. Iterate strategy batches:
   - `editor.placeBlock((ox+dx, oy+dy, oz+dz), Block(id, props))`
   - Flush every `flush_every_n_blocks` blocks
   - Sleep `per_block_delay_ms` between blocks, `per_layer_delay_ms` between batches
4. Persist resulting logical state to session files

## CLI Usage

```bash
# Offline preview (no Minecraft server needed)
python -m animation preview --config animation_config.toml
python -m animation preview --config animation_config.toml --format mp4 --output output/

# Live placement (requires GDMC-HTTP mod running)
uv run python -m animation animate --config animation_config.toml

# In-place modify / upgrade
uv run python -m animation modify --config animation_config.toml

# One-shell in-game controller
uv run python -m animation control --config animation_config.toml

# Hard reset build + sticky origin
uv run python -m animation clear
```

## In-Game Controls

With `control` running:

- `/trigger animctl set 1` -> clear current build and forget origin/state
- `/trigger animctl set 2` -> build/rebuild from config
- `/trigger animctl set 3` -> modify current build in place

## Dependencies

- **VPS renderer** (`vps.*`) — mesh generation + single-view rendering
- **gdpc** — GDMC-HTTP client library (live placement only)
- **Pillow** — frame assembly + GIF output
- **ffmpeg** — MP4 encoding (must be on PATH; GIF works without it)

Manage with UV:
```bash
uv sync
```

## Key Design Decisions

1. **Incremental scene updates** — only modified blocks are re-meshed per frame. Adjacency re-resolution is scoped to affected neighbours only.
2. **Strategy/timing separation** — ordering logic is pure (generators yielding batches), timing is applied by the consumer (placer or preview renderer). This makes strategies testable and reusable.
3. **Frozen config** — `AnimationConfig` is a frozen dataclass. Use `dataclasses.replace()` to derive variants.
4. **Diff-based modification** — erosion, overlay, and upgrade flows all reduce to a block diff. Only the delta is animated or placed; the whole structure is not rebuilt unless explicitly requested.
