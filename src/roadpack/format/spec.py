"""Binary layout of the .gmap format, shared by the writer and the reader. The full specification is FORMAT.md."""
import struct

MAGIC = b"GMAP"
VERSION = 2

# Coordinates are stored as integers: degrees × 1e7 (≈ 1.1 cm resolution), same as OSM.
SCALE = 10_000_000

# "Nothing here" in 32-bit references (geometry, name).
NONE = 0xFFFFFFFF

# magic, version, header_size, node_count, edge_count,
# min_lat, min_lon, max_lat, max_lon, cell_size, grid_cols, grid_rows,
# nodes_off, edges_off, grid_off, geom_off, names_off, ch_fwd_off, ch_bwd_off, file_size
HEADER = struct.Struct("<4sHHII4iIHH8I")
assert HEADER.size == 72

# lat, lon, first_edge (there are node_count + 1 records: the last one is a sentinel)
NODE = struct.Struct("<iiI")

# source, target, geom, name, length_m, weight_ds (travel time in tenths of a second), speed_kmh, flags, padding
EDGE = struct.Struct("<IIIIIIBBH")

# Header of each geometry: number of interior points and padding; then count × (lat i32, lon i32).
GEOM_HEADER = struct.Struct("<HH")
POINT = struct.Struct("<ii")

# Contraction hierarchy arc: other (head in forward, tail in backward), weight_ds, a, b.
CH_ARC = struct.Struct("<IIII")
CH_ORIGINAL = 0x80000000  # in `a`: the arc is an original edge (a & ~CH_ORIGINAL = edge id)

# Edge flags byte.
CLASS_MASK = 0x0F
FLAG_GEOM_REVERSED = 0x10  # the stored geometry runs from target to source: walk it backwards
FLAG_ROUNDABOUT = 0x20
FLAG_LINK = 0x40  # ramp or link road (*_link)

ROAD_CLASSES = [
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service",
]


def travel_time_ds(length_m, speed_kmh):
    """Travel time in tenths of a second (integer, at least 1): the routing weight of an edge."""
    return max(1, round(length_m * 36 / speed_kmh))
