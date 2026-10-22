"""Splitting a .gmap into fixed-size files for a FAT-formatted SD card.

Without FAT "fast seek" (the Arduino ESP32 core does not enable it), seeking backwards inside a file of
hundreds of MB walks the whole cluster chain: ~12 ms per read measured on an ESP32-S3. Small chunks keep the
seeks short; too small and the device spends its time opening files (~17 ms each). 4 MiB is the sweet spot.
"""
from pathlib import Path

CHUNK_SIZE = 4 << 20


def write_chunks(gmap_path: Path, out_dir: Path, chunk_size: int = CHUNK_SIZE) -> int:
    """Split a .gmap into out_dir/0000.bin, 0001.bin, ... (removing old chunks first). Returns the count."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.bin"):
        old.unlink()
    with open(gmap_path, "rb") as f:
        i = 0
        while chunk := f.read(chunk_size):
            (out_dir / f"{i:04d}.bin").write_bytes(chunk)
            i += 1
    return i


def join_chunks(chunk_dir: Path) -> bytes:
    """Concatenate the chunks of a directory back into the original .gmap bytes."""
    return b"".join(p.read_bytes() for p in sorted(chunk_dir.glob("*.bin")))
