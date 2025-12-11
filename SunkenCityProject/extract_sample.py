r"""
extract_sample.py

Extract a small sample of chunks from a .bin file for quick visualization.
Much faster than loading all 37k chunks!

Usage:
    python SunkenCityProject/extract_sample.py --input city_merged.bin --world-path "path/to/world" --chunks 100
    
python SunkenCityProject/extract_sample.py --input city_merged.bin --world-path "$env:APPDATA\.minecraft\saves\GDMC_Test_Visualiser" --chunks 500
"""

import argparse
import os
import sys
from city_utils import read_bin_generator, write_bin
from tqdm import tqdm


def extract_sample(input_file, output_file, num_chunks=100, center_x=0, center_z=0, prefer_nonempty=True):
    """
    Extract a sample of chunks near a center point.
    
    Args:
        input_file: Input .bin file
        output_file: Output .bin file
        num_chunks: Number of chunks to extract
        center_x: Center X chunk coordinate
        center_z: Center Z chunk coordinate
        prefer_nonempty: Prefer chunks with non-air blocks
    """
    
    print(f"Extracting {num_chunks} chunks from {input_file}")
    print(f"Center: chunk ({center_x}, {center_z})")
    print("=" * 70)
    
    # Load all chunks and find closest to center
    print("Loading chunks...")
    all_chunks = []
    for cx, cz, blocks, palette in tqdm(read_bin_generator(input_file), desc="Loading", unit="chunk"):
        # Calculate distance from center
        dist = ((cx - center_x)**2 + (cz - center_z)**2)**0.5
        
        # Count non-air blocks if prefer_nonempty
        non_air_count = 0
        if prefer_nonempty:
            import numpy as np
            # Find air block index
            air_idx = 0
            for i, name in enumerate(palette):
                if 'air' in name.lower():
                    air_idx = i
                    break
            non_air_count = np.sum(blocks != air_idx)
        
        all_chunks.append((dist, cx, cz, blocks, palette, non_air_count))
    
    print(f"✓ Loaded {len(all_chunks):,} chunks")
    
    # Sort by non-air count (descending) then distance
    if prefer_nonempty:
        all_chunks.sort(key=lambda x: (-x[5], x[0]))  # More non-air first, then closest
        print(f"✓ Sorted by density (preferring chunks with content)")
    else:
        all_chunks.sort(key=lambda x: x[0])  # Just by distance
    
    sample_chunks = all_chunks[:num_chunks]
    
    print(f"✓ Selected {len(sample_chunks)} chunks")
    if prefer_nonempty:
        avg_blocks = sum(x[5] for x in sample_chunks) / len(sample_chunks)
        print(f"  Average non-air blocks per chunk: {avg_blocks:.1f}")
    
    # Extract unique blocks for global palette
    print("Building palette...")
    global_palette = []
    palette_set = set()
    
    for dist, cx, cz, blocks, palette, non_air_count in sample_chunks:
        for block_name in palette:
            if block_name not in palette_set:
                palette_set.add(block_name)
                global_palette.append(block_name)
    
    print(f"✓ Global palette: {len(global_palette)} unique blocks")
    
    # Remap chunks to global palette
    print("Remapping chunks...")
    remapped_chunks = []
    
    for dist, cx, cz, blocks, palette, non_air_count in tqdm(sample_chunks, desc="Remapping", unit="chunk"):
        import numpy as np
        
        # Create mapping from local to global palette
        local_to_global = np.zeros(len(palette), dtype=np.uint16)
        for local_idx, block_name in enumerate(palette):
            local_to_global[local_idx] = global_palette.index(block_name)
        
        # Remap blocks
        remapped_blocks = local_to_global[blocks]
        remapped_chunks.append((cx, cz, remapped_blocks))
    
    # Write output
    print(f"\nWriting to {output_file}...")
    
    def chunk_gen():
        for cx, cz, blocks in remapped_chunks:
            yield cx, cz, blocks
    
    write_bin(output_file, chunk_gen(), global_palette)
    
    # Show chunk range
    min_cx = min(cx for cx, cz, blocks in remapped_chunks)
    max_cx = max(cx for cx, cz, blocks in remapped_chunks)
    min_cz = min(cz for cx, cz, blocks in remapped_chunks)
    max_cz = max(cz for cx, cz, blocks in remapped_chunks)
    
    print("\n" + "=" * 70)
    print("SAMPLE EXTRACTION COMPLETE")
    print("=" * 70)
    print(f"✓ Output: {output_file}")
    print(f"✓ Chunks: {len(remapped_chunks)}")
    print(f"✓ Chunk range: ({min_cx}, {min_cz}) to ({max_cx}, {max_cz})")
    print(f"✓ World coords: ({min_cx*16}, {min_cz*16}) to ({max_cx*16+15}, {max_cz*16+15})")


def main():
    parser = argparse.ArgumentParser(description="Extract sample chunks and place in world for visualization")
    parser.add_argument("--input", required=True, help="Input .bin file")
    parser.add_argument("--world-path", required=True, help="Path to Minecraft world directory")
    parser.add_argument("--output", default="sample_temp.bin", help="Temporary output .bin file (default: sample_temp.bin)")
    parser.add_argument("--chunks", type=int, default=200, help="Number of chunks to extract (default: 200)")
    parser.add_argument("--center-x", type=int, default=0, help="Center X chunk coordinate (default: 0)")
    parser.add_argument("--center-z", type=int, default=0, help="Center Z chunk coordinate (default: 0)")
    parser.add_argument("--y-start", type=int, default=-64, help="World Y coordinate for array index 0 (default: -64 for ocean floor placement)")
    
    args = parser.parse_args()
    
    # Extract sample
    extract_sample(args.input, args.output, args.chunks, args.center_x, args.center_z)
    
    # Now place it in the world
    print("\n" + "=" * 70)
    print("PLACING IN WORLD")
    print("=" * 70)
    
    # Import and run restore_city_amulet_ultra
    script_dir = os.path.dirname(os.path.abspath(__file__))
    restore_script = os.path.join(script_dir, "restore_city_amulet_ultra.py")
    
    if not os.path.exists(restore_script):
        print(f"❌ Could not find restore_city_amulet_ultra.py at {restore_script}")
        print(f"   Please run manually:")
        print(f"   python SunkenCityProject/restore_city_amulet_ultra.py --input {args.output} --world-path {args.world_path}")
        return
    
    # Run it by importing
    import subprocess
    result = subprocess.run([
        sys.executable,
        restore_script,
        "--input", args.output,
        "--world", args.world_path,
        "--y-start", str(args.y_start)
    ])
    
    if result.returncode == 0:
        print("\n" + "=" * 70)
        print("✅ VISUALIZATION COMPLETE!")
        print("=" * 70)
        print(f"✓ World: {args.world_path}")
        print("\n💡 Open in Amulet Map Editor or Minecraft to view!")
        
        # Clean up temp file
        if args.output == "sample_temp.bin" and os.path.exists(args.output):
            os.remove(args.output)
            print(f"✓ Cleaned up temporary file: {args.output}")
    else:
        print(f"\n❌ Failed to place chunks in world")
        print(f"   Temporary file saved at: {args.output}")


if __name__ == "__main__":
    main()
