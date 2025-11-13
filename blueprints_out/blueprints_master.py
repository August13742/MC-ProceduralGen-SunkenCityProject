# Auto-generated master blueprint database
import bp_000
import bp_001
import bp_002
import bp_003
import bp_004
import bp_005
import bp_006
import bp_007
import bp_008
import bp_009
import bp_010
import bp_011
import bp_012
import bp_013
import bp_014
import bp_015
import bp_016
import bp_017
import bp_018
import bp_019
import bp_020
import bp_021
import bp_022
import bp_023

BLUEPRINTS = {
    bp_000.NAME: bp_000.BLOCKS,
    bp_001.NAME: bp_001.BLOCKS,
    bp_002.NAME: bp_002.BLOCKS,
    bp_003.NAME: bp_003.BLOCKS,
    bp_004.NAME: bp_004.BLOCKS,
    bp_005.NAME: bp_005.BLOCKS,
    bp_006.NAME: bp_006.BLOCKS,
    bp_007.NAME: bp_007.BLOCKS,
    bp_008.NAME: bp_008.BLOCKS,
    bp_009.NAME: bp_009.BLOCKS,
    bp_010.NAME: bp_010.BLOCKS,
    bp_011.NAME: bp_011.BLOCKS,
    bp_012.NAME: bp_012.BLOCKS,
    bp_013.NAME: bp_013.BLOCKS,
    bp_014.NAME: bp_014.BLOCKS,
    bp_015.NAME: bp_015.BLOCKS,
    bp_016.NAME: bp_016.BLOCKS,
    bp_017.NAME: bp_017.BLOCKS,
    bp_018.NAME: bp_018.BLOCKS,
    bp_019.NAME: bp_019.BLOCKS,
    bp_020.NAME: bp_020.BLOCKS,
    bp_021.NAME: bp_021.BLOCKS,
    bp_022.NAME: bp_022.BLOCKS,
    bp_023.NAME: bp_023.BLOCKS,
}

def place_blueprint(editor, origin, blocks):
    """Place a blueprint at origin using GDPC editor."""
    from gdpc.block import Block
    ox, oy, oz = origin
    for (dx, dy, dz), block_id, props in blocks:
        editor.placeBlock((ox+dx, oy+dy, oz+dz), Block(block_id, props))
