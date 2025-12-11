from typing import Dict, Any, Tuple

def _pop_material(props: Dict[str, Any], default: str = "oak") -> str:
    """
    Extract wood/material type from universal props if present.
    Tries several common keys, falls back to `default` if nothing found.
    """
    if props is None:
        return default

    for key in ("material", "wood", "wood_type", "plank"):
        if key in props:
            return str(props.pop(key))

    return default


def normalise_block(block_id: str, props: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Convert Amulet-style 'universal' blocks to real 1.13+ vanilla IDs/states
    that the GDPC / Minecraft server actually understands.

    Assumes get_block_id has already converted 'universal_minecraft:' to 'minecraft:'.
    """
    props = dict(props or {})
    bid = block_id

    # --- Stone bricks: variant -> separate blocks --------------------------
    if bid == "minecraft:stone_bricks":
        variant = props.pop("variant", "normal")
        if variant == "chiseled":
            bid = "minecraft:chiseled_stone_bricks"
        elif variant == "cracked":
            bid = "minecraft:cracked_stone_bricks"
        elif variant == "mossy":
            bid = "minecraft:mossy_stone_bricks"
        # "normal" => keep stone_bricks, but without a variant property

    # --- Old brick_block -> bricks -----------------------------------------
    if bid == "minecraft:brick_block":
        # 1.12 name; in modern versions this is simply "bricks"
        bid = "minecraft:bricks"
        props.clear()  # no blockstates on bricks

    # --- Logs ---------------------------------------------------------------
    if bid == "minecraft:log":
        mat = _pop_material(props, "oak")
        stripped = props.pop("stripped", "false")
        prefix = "stripped_" if str(stripped).lower() == "true" else ""
        bid = f"minecraft:{prefix}{mat}_log"
        # axis is valid on logs; keep it

    # --- Leaves -------------------------------------------------------------
    if bid == "minecraft:leaves":
        mat = _pop_material(props, "oak")
        props.pop("check_decay", None)  # legacy junk
        bid = f"minecraft:{mat}_leaves"

    # --- Planks -------------------------------------------------------------
    if bid == "minecraft:planks":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_planks"
        props.clear()  # planks have no states

    # --- Wood (stripped and regular) ----------------------------------------
    if bid == "minecraft:wood":
        mat = _pop_material(props, "oak")
        stripped = props.pop("stripped", "false")
        prefix = "stripped_" if str(stripped).lower() == "true" else ""
        bid = f"minecraft:{prefix}{mat}_wood"

    # --- Pressure Plates ----------------------------------------------------
    if bid == "minecraft:pressure_plate":
        mat = _pop_material(props, "oak")
        if mat in ["stone", "light_weighted", "heavy_weighted", "polished_blackstone"]:
            # Stone variants don't follow the pattern
            if mat == "stone":
                bid = "minecraft:stone_pressure_plate"
            else:
                bid = f"minecraft:{mat}_pressure_plate"
        else:
            # Wood variants
            bid = f"minecraft:{mat}_pressure_plate"

    if bid == "minecraft:wooden_pressure_plate":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_pressure_plate"

    # --- Hanging Signs ------------------------------------------------------
    if bid == "minecraft:hanging_sign":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_hanging_sign"
    
    if bid == "minecraft:wall_hanging_sign":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_wall_hanging_sign"

    # --- Shulker Boxes ------------------------------------------------------
    if bid == "minecraft:shulker_box":
        color = str(props.pop("color", "purple"))  # Default uncolored is just "shulker_box"
        if color != "purple":
            bid = f"minecraft:{color}_shulker_box"
        # else keep as minecraft:shulker_box

    # --- Candles ------------------------------------------------------------
    if bid == "minecraft:candle":
        color = str(props.pop("color", "none"))
        if color != "none":
            bid = f"minecraft:{color}_candle"
        # else keep as minecraft:candle

    # --- Terracotta ---------------------------------------------------------
    if bid == "minecraft:terracotta":
        color = str(props.pop("color", "none"))
        if color != "none":
            bid = f"minecraft:{color}_terracotta"
        # else keep as plain minecraft:terracotta

    # --- Coral & Coral Fans -------------------------------------------------
    if bid == "minecraft:coral_block":
        variant = str(props.pop("variant", "tube")).lower()
        dead = str(props.pop("dead", "false")).lower() == "true"
        prefix = "dead_" if dead else ""
        bid = f"minecraft:{prefix}{variant}_coral_block"
        props.clear()

    if bid == "minecraft:coral":
        variant = str(props.pop("variant", "tube")).lower()
        dead = str(props.pop("dead", "false")).lower() == "true"
        prefix = "dead_" if dead else ""
        bid = f"minecraft:{prefix}{variant}_coral"
        props.clear()

    if bid == "minecraft:coral_fan":
        variant = str(props.pop("variant", "tube")).lower()
        dead = str(props.pop("dead", "false")).lower() == "true"
        prefix = "dead_" if dead else ""
        bid = f"minecraft:{prefix}{variant}_coral_fan"

    if bid == "minecraft:wall_coral_fan":
        variant = str(props.pop("variant", "tube")).lower()
        dead = str(props.pop("dead", "false")).lower() == "true"
        prefix = "dead_" if dead else ""
        bid = f"minecraft:{prefix}{variant}_coral_wall_fan"

    # --- Stairs -------------------------------------------------------------
    if bid == "minecraft:stairs":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_stairs"
        # facing, half, shape are valid; keep them

    # --- Slabs --------------------------------------------------------------
    if bid == "minecraft:slab":
        mat = _pop_material(props, "stone")
        bid = f"minecraft:{mat}_slab"
        # type (top/bottom/double) is valid

    # --- Fences -------------------------------------------------------------
    if bid == "minecraft:fence":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_fence"

    # --- Fence gates --------------------------------------------------------
    if bid == "minecraft:fence_gate":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_fence_gate"
        # facing, open, powered, in_wall are valid; keep them

    # --- Trapdoors ----------------------------------------------------------
    if bid == "minecraft:trapdoor":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_trapdoor"

    # --- Doors --------------------------------------------------------------
    if bid == "minecraft:door":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_door"

    # --- Signs (standing and wall-mounted) ----------------------------------
    if bid == "minecraft:sign":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_sign"
    
    if bid == "minecraft:wall_sign":
        mat = _pop_material(props, "oak")
        bid = f"minecraft:{mat}_wall_sign"

    # --- Banners (standing and wall-mounted) --------------------------------
    if bid == "minecraft:banner":
        color = str(props.pop("color", "white"))
        bid = f"minecraft:{color}_banner"
    
    if bid == "minecraft:wall_banner":
        color = str(props.pop("color", "white"))
        bid = f"minecraft:{color}_wall_banner"

    # --- Walls --------------------------------------------------------------
    if bid == "minecraft:wall":
        mat = _pop_material(props, "cobblestone")
        bid = f"minecraft:{mat}_wall"

    # --- Bars (iron_bars in vanilla) ---------------------------------------
    if bid == "minecraft:bars":
        # In vanilla there's effectively only iron_bars.
        props.pop("material", None)
        bid = "minecraft:iron_bars"
        # connectivity flags (north/east/south/west) are valid; keep them

    # --- Buttons ------------------------------------------------------------
    if bid == "minecraft:button":
        # universal "button" => either stone_button or <wood>_button
        mat = _pop_material(props, "stone")
        if mat == "stone":
            bid = "minecraft:stone_button"
        else:
            bid = f"minecraft:{mat}_button"
        # facing, face (wall/floor/ceiling), powered are valid; keep them

    # --- Beds ---------------------------------------------------------------
    if bid == "minecraft:bed":
        # modern IDs are color_bed
        color = str(props.pop("color", "red"))
        bid = f"minecraft:{color}_bed"
        # keep facing, occupied, part (head/foot) if present

    # --- Wool & carpet (color -> ID) ---------------------------------------
    if bid == "minecraft:wool":
        color = props.pop("color", "white")
        bid = f"minecraft:{color}_wool"

    if bid == "minecraft:carpet":
        color = props.pop("color", "white")
        bid = f"minecraft:{color}_carpet"

    # --- Concrete & Concrete Powder -----------------------------------------
    if bid == "minecraft:concrete":
        color = props.pop("color", "white")
        bid = f"minecraft:{color}_concrete"
        props.clear()

    if bid == "minecraft:concrete_powder":
        color = props.pop("color", "white")
        bid = f"minecraft:{color}_concrete_powder"
        props.clear()

    # --- Stained Glass & Panes ----------------------------------------------
    if bid == "minecraft:stained_glass":
        color = props.pop("color", "white")
        bid = f"minecraft:{color}_stained_glass"
        props.clear()

    if bid == "minecraft:stained_glass_pane":
        color = props.pop("color", "white")
        bid = f"minecraft:{color}_stained_glass_pane"

    # --- Terracotta ---------------------------------------------------------
    if bid == "minecraft:stained_terracotta":
        color = props.pop("color", "white")
        bid = f"minecraft:{color}_terracotta"
        props.clear()

    if bid == "minecraft:glazed_terracotta":
        color = props.pop("color", "white")
        bid = f"minecraft:{color}_glazed_terracotta"

    # --- Torch / wall_torch -------------------------------------------------
    if bid == "minecraft:torch":
        facing = props.get("facing", "up")
        if facing in ("north", "south", "east", "west"):
            bid = "minecraft:wall_torch"
            # wall_torch has facing; keep it
        else:
            props.pop("facing", None)  # standing torch has no facing

    # --- Flower pot ---------------------------------------------------------
    if bid == "minecraft:flower_pot":
        plant = props.pop("plant", "none")
        props.pop("update", None)
        if plant != "none":
            bid = f"minecraft:potted_{plant}"
            props.clear()
        else:
            props.clear()

    # --- Chest --------------------------------------------------------------
    if bid == "minecraft:chest":
        props.pop("material", None)
        conn = props.pop("connection", None)
        # universal uses "connection": single|left|right|none|...
        if conn in ("single", "left", "right"):
            props["type"] = conn
        else:
            # "none" or unknown -> let vanilla default to single, no explicit type
            props.pop("type", None)
            
    # --- Generic head / skull ----------------------------------------------
    if bid == "minecraft:head":
        # Try a few likely keys that Amulet might use
        head_type = (
            str(props.pop("type", "") or
                props.pop("skull_type", "") or
                props.pop("head_type", ""))
            .lower()
        )

        # Map universal type → concrete vanilla ID stem
        # Default to skeleton skull if we can't tell.
        mapping = {
            "skeleton": "skeleton_skull",
            "wither_skeleton": "wither_skeleton_skull",
            "wither": "wither_skeleton_skull",
            "zombie": "zombie_head",
            "creeper": "creeper_head",
            "dragon": "dragon_head",
            "player": "player_head",
        }

        stem = mapping.get(head_type, "skeleton_skull")
        bid = f"minecraft:{stem}"

        # Standing heads in vanilla can have a 'rotation' blockstate 0–15.
        rot_raw = props.get("rotation", None)
        if rot_raw is not None:
            try:
                rot = int(rot_raw) % 16
                props = {"rotation": str(rot)}
            except (ValueError, TypeError):
                props = {}
        else:
            # Wall-vs-floor, facing, etc. we can ignore safely.
            props.clear()

    # --- Wall-mounted heads -------------------------------------------------
    if bid == "minecraft:wall_head":
        # Same as regular heads but wall-mounted variants
        head_type = (
            str(props.pop("type", "") or
                props.pop("skull_type", "") or
                props.pop("head_type", ""))
            .lower()
        )

        mapping = {
            "skeleton": "skeleton_wall_skull",
            "wither_skeleton": "wither_skeleton_wall_skull",
            "wither": "wither_skeleton_wall_skull",
            "zombie": "zombie_wall_head",
            "creeper": "creeper_wall_head",
            "dragon": "dragon_wall_head",
            "player": "player_wall_head",
        }

        stem = mapping.get(head_type, "skeleton_wall_skull")
        bid = f"minecraft:{stem}"
        # Keep 'facing' property for wall-mounted heads

    # --- Infested blocks ---------------------------------------------------
    if bid == "minecraft:infested_block":
        # universal probably gives "variant": stone|cobblestone|stone_bricks|mossy_stone_bricks|cracked_stone_bricks|chiseled_stone_bricks
        variant = str(props.pop("variant", "stone")).lower()

        mapping = {
            "stone": "infested_stone",
            "cobblestone": "infested_cobblestone",
            "stone_bricks": "infested_stone_bricks",
            "mossy_stone_bricks": "infested_mossy_stone_bricks",
            "cracked_stone_bricks": "infested_cracked_stone_bricks",
            "chiseled_stone_bricks": "infested_chiseled_stone_bricks",
        }

        stem = mapping.get(variant, "infested_stone")
        bid = f"minecraft:{stem}"
        props.clear()
        
    # --- Anvil damage level (universal: damage = 0/1/2) --------------------
    if bid == "minecraft:anvil":
        dmg_raw = props.pop("damage", "0")
        try:
            dmg = int(dmg_raw)
        except (ValueError, TypeError):
            dmg = 0

        if dmg <= 0:
            bid = "minecraft:anvil"
        elif dmg == 1:
            bid = "minecraft:chipped_anvil"
        else:
            bid = "minecraft:damaged_anvil"

        # vanilla anvil has facing only; keep if present.
        facing = props.get("facing", None)
        if facing:
            props = {"facing": facing}
        else:
            props.clear()

    # --- Fluids -------------------------------------------------------------
    if bid in ("minecraft:water", "minecraft:lava"):
        # Universal may give us: level, falling, flowing, etc.
        # Vanilla only understands 'level'. Nukes everything else.
        raw_level = props.get("level", "0")

        try:
            lvl = int(raw_level)
        except (ValueError, TypeError):
            lvl = 0

        lvl = max(0, min(15, lvl))

        # Only keep 'level' as a *string* (vanilla accepts that)
        props = {"level": str(lvl)}

    # --- Plants (generic -> specific) ---------------------------------------
    if bid == "minecraft:plant":
        # Amulet's generic "plant" - default to short_grass (was "grass" in old versions)
        plant_type = str(props.pop("plant_type", "grass")).lower()
        
        # Common mappings
        plant_map = {
            "grass": "minecraft:short_grass",  # Modern name
            "short_grass": "minecraft:short_grass",
            "fern": "minecraft:fern",
            "dead_bush": "minecraft:dead_bush",
            "dandelion": "minecraft:dandelion",
            "poppy": "minecraft:poppy",
            "blue_orchid": "minecraft:blue_orchid",
            "allium": "minecraft:allium",
            "azure_bluet": "minecraft:azure_bluet",
            "tulip": "minecraft:red_tulip",
            "oxeye_daisy": "minecraft:oxeye_daisy",
            "cornflower": "minecraft:cornflower",
            "lily_of_the_valley": "minecraft:lily_of_the_valley",
            "wither_rose": "minecraft:wither_rose",
        }
        
        bid = plant_map.get(plant_type, "minecraft:short_grass")
        props.clear()

    if bid == "minecraft:double_plant":
        # Tall plants (2-block tall)
        plant_type = str(props.pop("plant_type", "sunflower")).lower()
        
        plant_map = {
            "sunflower": "minecraft:sunflower",
            "lilac": "minecraft:lilac",
            "tall_grass": "minecraft:tall_grass",
            "large_fern": "minecraft:large_fern",
            "rose_bush": "minecraft:rose_bush",
            "peony": "minecraft:peony",
        }
        
        bid = plant_map.get(plant_type, "minecraft:sunflower")
        # Keep 'half' property if present (upper/lower)

    return bid, props
