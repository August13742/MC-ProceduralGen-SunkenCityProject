import argparse
import amulet
import numpy as np

def debug():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", required=True)
    args = parser.parse_args()

    print(f"Loading world: {args.world}")
    level = amulet.load_level(args.world)
    
    # We choose -10, -10 because it is definitely inside r.-1.-1.mca (which is 7MB)
    cx, cz = -10, -10
    
    print(f"\n--- INSPECTING CHUNK {cx}, {cz} ---")
    
    try:
        chunk = level.get_chunk(cx, cz, "minecraft:overworld")
        
        # 1. Check Dimensions
        print(f"Chunk Shape (X, Y, Z): {chunk.blocks.shape}")
        
        # 2. Check Raw Palette (What Amulet sees)
        palette = chunk.block_palette
        print(f"Palette Size: {len(palette)}")
        print("First 10 blocks in palette:")
        for i, block in enumerate(palette[:10]):
            print(f"  {i}: {block.namespaced_name}")

        # 3. Check for actual block usage
        unique_indices = np.unique(chunk.blocks)
        print(f"\nUnique Block Indices used in grid: {len(unique_indices)}")
        
        # 4. Check a specific Y-level slice (e.g., Y=50, likely underground/water)
        # Note: Amulet Y index usually maps 0 -> -64 for 1.18 worlds
        sample_y_index = 100 # Roughly Y = 36 if world starts at -64
        slice_data = chunk.blocks[:, sample_y_index, :]
        print(f"\nSample Slice at Index 100 (approx Y=36):")
        print(slice_data)
        
        # Check if slice is all 0 (Air)
        if np.all(slice_data == 0):
            print("\n[CRITICAL] This slice is ALL AIR. Amulet is not reading the data.")
        else:
            print("\n[SUCCESS] Data detected. The extraction logic was the issue.")

    except Exception as e:
        print(f"Error loading chunk: {e}")

if __name__ == "__main__":
    debug()