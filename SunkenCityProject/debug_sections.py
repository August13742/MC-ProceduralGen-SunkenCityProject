import argparse
import amulet
import numpy as np

def debug():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", required=True)
    args = parser.parse_args()

    print(f"Loading world: {args.world}")
    level = amulet.load_level(args.world)
    
    cx, cz = -10, -10
    print(f"\n--- INSPECTING SECTIONS IN CHUNK {cx}, {cz} ---")
    
    try:
        chunk = level.get_chunk(cx, cz, "minecraft:overworld")
        
        # Check if sections attribute exists (it should for Anvil chunks)
        if hasattr(chunk, "sections"):
            sections = chunk.sections
            print(f"Total Sections Found: {len(sections)}")
            
            # Print the Y-index of every section found
            # (Y=0 is sea level area, Y=-4 is bottom of world in 1.18+)
            section_indices = sorted(sections.keys())
            print(f"Section Y-Indices: {section_indices}")
            
            if len(section_indices) > 0:
                # Grab the first valid section
                first_y = section_indices[0]
                sub_chunk = sections[first_y]
                
                # Check palette of this specific sub-chunk
                print(f"\n--- Inspecting Section Y={first_y} ---")
                print(f"Sub-chunk palette size: {len(sub_chunk.block_palette)}")
                print(f"First 5 blocks in this section:")
                for i, b in enumerate(sub_chunk.block_palette[:5]):
                     print(f"  {i}: {b.namespaced_name}")
                
                print("\n[CONCLUSION] Data exists in sections. The extractor must be rewritten to loop over sections.")
            else:
                print("\n[CRITICAL] Chunk has 'sections' attribute but it is empty.")
        else:
            print("[CRITICAL] Chunk object has no 'sections' attribute.")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug()