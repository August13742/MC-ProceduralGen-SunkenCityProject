import random
from opensimplex import OpenSimplex # pip install opensimplex
from copy import deepcopy

# --- TRANSFORMATION TABLE ---
# Source -> [(Target, Weight)]
DECAY_TABLE = {
    # CONCRETE
    "minecraft:white_concrete": [("minecraft:white_concrete_powder", 4), ("minecraft:calcite", 1), ("minecraft:air", 1)],
    "minecraft:black_concrete": [("minecraft:black_concrete_powder", 4), ("minecraft:obsidian", 1), ("minecraft:coal_block", 1)],
    # STONE
    "minecraft:stone_bricks": [("minecraft:cracked_stone_bricks", 5), ("minecraft:mossy_stone_bricks", 5), ("minecraft:cobblestone", 4), ("minecraft:air", 2)],
    "minecraft:cobblestone": [("minecraft:mossy_cobblestone", 6), ("minecraft:gravel", 4), ("minecraft:air", 3)],
    # WOOD (Rot fast)
    "minecraft:oak_planks": [("minecraft:dark_oak_planks", 2), ("minecraft:stripped_oak_log", 1), ("minecraft:air", 4)],
    "minecraft:spruce_planks": [("minecraft:spruce_slab", 2), ("minecraft:air", 5)],
    # GLASS (Shatters easily)
    "minecraft:glass": [("minecraft:air", 10), ("minecraft:glass_pane", 1)],
    "minecraft:glass_pane": [("minecraft:air", 10), ("minecraft:iron_bars", 1)],
    # METAL
    "minecraft:iron_block": [("minecraft:oxidized_copper", 6), ("minecraft:air", 1)],
    "minecraft:iron_bars": [("minecraft:air", 5), ("minecraft:chain", 1)],
}

def get_neighbors(x, y, z):
    return [
        (x+1, y, z), (x-1, y, z),
        (x, y+1, z), (x, y-1, z),
        (x, y, z+1), (x, y, z-1)
    ]

def erode_blueprint(blueprint_data, seed=1337, aggression=0.5, passes=3):
    """
    aggression: 0.0 (pristine) to 1.0 (total ruin)
    passes: How many times to simulate structural collapse.
    """
    
    # Deep copy to avoid mutating the original comparison object
    blocks_list = deepcopy(blueprint_data['blocks'])
    
    # Convert list to Dictionary for O(1) spatial lookup
    # key: (x,y,z) tuple -> val: block_dict
    grid = {}
    for b in blocks_list:
        pos = (b['dx'], b['dy'], b['dz'])
        grid[pos] = b

    noise = OpenSimplex(seed)
    random.seed(seed)
    
    # Scale: Higher = more "patchy" rot. Lower = smoother gradient.
    # 0.2 is a good balance for buildings.
    scale = 0.2

    for p in range(passes):
        
        # We collect mutations in a batch so we calculate stability based on
        # the START of the tick, not mid-tick (Synchronous Cellular Automata)
        to_delete = set()
        to_mutate = {} 

        for pos, block in grid.items():
            x, y, z = pos
            bid = block['id']
            
            # --- FACTOR 1: Perlin Noise (The random "Damage Map") ---
            # Normalized to 0.0 - 1.0
            n_val = (noise.noise3(x * scale, y * scale, z * scale) + 1) / 2
            
            # --- FACTOR 2: Air Exposure (The "Rot" Factor) ---
            air_neighbors = 0
            for n_pos in get_neighbors(x, y, z):
                if n_pos not in grid:
                    air_neighbors += 1
            
            # --- FACTOR 3: Gravity (The "Collapse" Factor) ---
            # If the block below me is missing, I am unstable.
            # (We treat y=0 as solid ground)
            is_floating = False
            if y > 0 and (x, y-1, z) not in grid:
                is_floating = True

            # --- CALCULATE INSTABILITY SCORE ---
            # Base instability from noise + aggression
            instability = (n_val * 0.4) + (aggression * 0.4)
            
            # Add exposure penalty (max +0.2 if fully exposed)
            instability += (air_neighbors / 6.0) * 0.2
            
            # Add gravity penalty (Huge penalty if floating)
            if is_floating:
                instability += 0.5 * aggression # At low aggression, floating blocks might stay (magic)

            # --- EXECUTION ---
            # If instability > 0.6, the block takes damage
            threshold = 1.0 - (aggression * 0.8) # agg 0.5 -> thresh 0.6. agg 1.0 -> thresh 0.2
            
            if instability > threshold:
                
                # Rule 1: Floating blocks usually just die
                if is_floating and random.random() < aggression:
                    to_delete.add(pos)
                    continue

                # Rule 2: Decay Table
                if bid in DECAY_TABLE:
                    choices = DECAY_TABLE[bid]
                    outcomes, weights = zip(*choices)
                    result_id = random.choices(outcomes, weights=weights, k=1)[0]
                    
                    if result_id == "minecraft:air":
                        to_delete.add(pos)
                    elif result_id != bid:
                        new_b = deepcopy(block)
                        new_b['id'] = result_id
                        to_mutate[pos] = new_b
                
                # Rule 3: Universal Entropy (Blocks not in table)
                else:
                    # Chance to vanish proportional to how unstable it is
                    if random.random() < (instability - threshold):
                        to_delete.add(pos)

        # Apply Batch
        for pos in to_delete:
            if pos in grid: del grid[pos]
        for pos, new_b in to_mutate.items():
            grid[pos] = new_b

    # Reconstruct List
    new_blocks_list = list(grid.values())
    
    # Update Meta
    new_data = deepcopy(blueprint_data)
    new_data['blocks'] = new_blocks_list
    new_data['meta']['eroded'] = True
    new_data['meta']['erosion_aggression'] = aggression
    
    return new_data