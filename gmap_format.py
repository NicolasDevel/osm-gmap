"""Constantes del formato .gmap, compartidas por el generador y el lector. La especificación está en FORMAT.md."""
import struct

MAGIC = b"GMAP"
VERSION = 1

# Coordenadas como enteros: grados × 1e7 (≈ 1,1 cm de resolución), igual que OSM.
SCALE = 10_000_000

# Valor para "no hay" en referencias de 32 bits (geometría, nombre).
NONE = 0xFFFFFFFF

# magic, version, header_size, node_count, edge_count,
# min_lat, min_lon, max_lat, max_lon, cell_size, grid_cols, grid_rows,
# nodes_off, edges_off, grid_off, geom_off, names_off, file_size
HEADER = struct.Struct("<4sHHII4iIHH6I")
assert HEADER.size == 64

# lat, lon, first_edge (hay node_count + 1 registros: el último es el centinela)
NODE = struct.Struct("<iiI")

# target, geom, name, length_m, speed_kmh, flags
EDGE = struct.Struct("<IIIHBB")

# Cabecera de cada geometría: cantidad de puntos intermedios y relleno; luego count × (lat i32, lon i32).
GEOM_HEADER = struct.Struct("<HH")
POINT = struct.Struct("<ii")

# Byte de flags de cada arista.
CLASS_MASK = 0x0F
FLAG_GEOM_REVERSED = 0x10  # la geometría guardada va de target a source: recorrerla al revés
FLAG_ROUNDABOUT = 0x20
FLAG_LINK = 0x40  # rampa o enlace (*_link)

ROAD_CLASSES = [
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service",
]
