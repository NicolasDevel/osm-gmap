"""Constantes del formato .gmap, compartidas por el generador y el lector. La especificación está en FORMAT.md."""
import struct

MAGIC = b"GMAP"
VERSION = 2

# Coordenadas como enteros: grados × 1e7 (≈ 1,1 cm de resolución), igual que OSM.
SCALE = 10_000_000

# Valor para "no hay" en referencias de 32 bits (geometría, nombre).
NONE = 0xFFFFFFFF

# magic, version, header_size, node_count, edge_count,
# min_lat, min_lon, max_lat, max_lon, cell_size, grid_cols, grid_rows,
# nodes_off, edges_off, grid_off, geom_off, names_off, ch_fwd_off, ch_bwd_off, file_size
HEADER = struct.Struct("<4sHHII4iIHH8I")
assert HEADER.size == 72

# lat, lon, first_edge (hay node_count + 1 registros: el último es el centinela)
NODE = struct.Struct("<iiI")

# source, target, geom, name, length_m, weight_ds (tiempo en décimas de segundo), speed_kmh, flags, relleno
EDGE = struct.Struct("<IIIIIIBBH")

# Cabecera de cada geometría: cantidad de puntos intermedios y relleno; luego count × (lat i32, lon i32).
GEOM_HEADER = struct.Struct("<HH")
POINT = struct.Struct("<ii")

# Arco de la jerarquía de contracción: other (cabeza en forward, cola en backward), weight_ds, a, b.
CH_ARC = struct.Struct("<IIII")
CH_ORIGINAL = 0x80000000  # en `a`: el arco es una arista original (a & ~CH_ORIGINAL = id de la arista)

# Byte de flags de cada arista.
CLASS_MASK = 0x0F
FLAG_GEOM_REVERSED = 0x10  # la geometría guardada va de target a source: recorrerla al revés
FLAG_ROUNDABOUT = 0x20
FLAG_LINK = 0x40  # rampa o enlace (*_link)

ROAD_CLASSES = [
    "motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential", "service",
]


def travel_time_ds(length_m, speed_kmh):
    """Tiempo de recorrido en décimas de segundo (entero, mínimo 1): el peso de las aristas para rutear."""
    return max(1, round(length_m * 36 / speed_kmh))


# En la SD el .gmap se guarda partido en archivos de 4 MiB (<región>/0000.bin, 0001.bin, ...): sin el
# "fast seek" de FAT, saltar hacia atrás dentro de un archivo grande recorre toda la cadena de clústeres.
# Pedazos más chicos obligan a abrir muchos archivos (~17 ms cada apertura en la placa).
CHUNK_SIZE = 4 << 20


def write_chunks(gmap_path, out_dir):
    """Parte un .gmap en archivos de CHUNK_SIZE bytes dentro de out_dir (lo vacía antes)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.bin"):
        old.unlink()
    with open(gmap_path, "rb") as f:
        i = 0
        while chunk := f.read(CHUNK_SIZE):
            (out_dir / f"{i:04d}.bin").write_bytes(chunk)
            i += 1
    return i
