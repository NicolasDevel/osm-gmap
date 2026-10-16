#!/usr/bin/env python3
"""
Convierte un extracto de OpenStreetMap (.osm.pbf) en el grafo vial binario (.gmap) que lee la placa.

Solo se conservan las vías por las que puede ir el vehículo (perfil moto o carro). Los nodos del grafo son las intersecciones
y los extremos de las vías; los puntos intermedios de cada tramo se guardan aparte como geometría
(para dibujar el cruce y calcular el ángulo de giro). Además se precalcula la jerarquía de contracción
(CH) con RoutingKit, para que la placa rutee distancias largas leyendo poco de la SD. El formato está
en FORMAT.md.

Uso:
  python build_graph.py --pbf colombia.osm.pbf --region bogota --out out/bogota.gmap [--profile carro]
"""
import argparse
import math
import struct
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

import osmium

from gmap_format import (
    CH_ARC, EDGE, FLAG_GEOM_REVERSED, FLAG_LINK, FLAG_ROUNDABOUT, GEOM_HEADER, HEADER, MAGIC, NODE, NONE, POINT,
    CHUNK_SIZE, SCALE, VERSION, travel_time_ds, write_chunks,
)

TOOLS_DIR = Path(__file__).resolve().parent
CH_TOOL = TOOLS_DIR / "ch" / "build_ch"
ROUTINGKIT = TOOLS_DIR / "third_party" / "RoutingKit"


# min_lat, min_lon, max_lat, max_lon
REGIONS = {
    "bogota": (4.45, -74.25, 4.84, -73.98),
    "cundinamarca": (3.70, -74.95, 5.90, -73.00),  # incluye Bogotá
    "colombia": (-4.5, -82.0, 13.6, -66.8),  # incluye San Andrés y Providencia
}

# highway -> (clase, km/h cuando la vía no trae maxspeed)
HIGHWAYS = {
    "motorway": (0, 80), "motorway_link": (0, 50),
    "trunk": (1, 60), "trunk_link": (1, 40),
    "primary": (2, 50), "primary_link": (2, 40),
    "secondary": (3, 40), "secondary_link": (3, 30),
    "tertiary": (4, 30), "tertiary_link": (4, 30),
    "unclassified": (5, 30),
    "residential": (6, 25),
    "living_street": (7, 10),
    "service": (7, 15),
}
EXCLUDED_SERVICE = {"parking_aisle", "driveway", "drive-through", "emergency_access"}
DENIED_ACCESS = {"no", "private", "agricultural", "forestry", "emergency"}
# Perfiles de vehículo: qué etiquetas de acceso y de sentido de OSM se consultan (de la más específica a la
# más general). El resto del filtro y del formato es igual para todos.
PROFILES = {
    "moto": {"access": ("motorcycle", "motor_vehicle", "vehicle", "access"), "oneway": "oneway:motorcycle"},
    "carro": {"access": ("motorcar", "motor_vehicle", "vehicle", "access"), "oneway": "oneway:motorcar"},
}

CELL_DEG = 0.0025          # celda del índice espacial: ≈ 280 m
SIMPLIFY_TOLERANCE_M = 2.0  # Douglas-Peucker sobre la geometría intermedia


def vehicle_allowed(tags, profile):
    for key in profile["access"]:
        value = tags.get(key)
        if value is not None:
            return value not in DENIED_ACCESS
    return True


def oneway_direction(tags, highway, profile):
    """1 = solo en el sentido en que está dibujada la vía, -1 = solo en contra, 0 = doble sentido."""
    value = tags.get(profile["oneway"]) or tags.get("oneway")
    if value in ("yes", "1", "true"):
        return 1
    if value == "-1":
        return -1
    if value == "no":
        return 0
    if tags.get("junction") in ("roundabout", "circular") or highway in ("motorway", "motorway_link"):
        return 1
    return 0


def parse_speed(value, default):
    if not value:
        return default
    digits = "".join(c for c in value.split(";")[0] if c.isdigit())
    if not digits:
        return default
    speed = int(digits)
    if "mph" in value:
        speed = round(speed * 1.609)
    # Hay vías con velocidades imposibles en OSM.
    return max(5, min(speed, 120))


def haversine_m(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def morton(row, col):
    """Índice en curva Z: intercala los bits de fila y columna."""
    z = 0
    for bit in range(16):
        z |= ((col >> bit) & 1) << (2 * bit) | ((row >> bit) & 1) << (2 * bit + 1)
    return z


def simplify(points, tolerance_m):
    """Douglas-Peucker en metros (proyección equirectangular local). Conserva siempre los extremos."""
    if len(points) <= 2:
        return points
    k = math.cos(math.radians(points[0][0]))
    xy = [(lon * k * 111_320, lat * 110_540) for lat, lon in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        best, best_d = -1, tolerance_m
        for m in range(i + 1, j):
            d = abs(dy * (xy[m][0] - x1) - dx * (xy[m][1] - y1)) / norm
            if d > best_d:
                best, best_d = m, d
        if best >= 0:
            keep[best] = True
            stack += [(i, best), (best, j)]
    return [p for p, k_ in zip(points, keep) if k_]


def ensure_ch_tool():
    """Compila ch/build_ch (con el código de RoutingKit) si todavía no existe."""
    if CH_TOOL.exists():
        return
    if not ROUTINGKIT.exists():
        print("Descargando RoutingKit...")
        subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/RoutingKit/RoutingKit.git",
                        str(ROUTINGKIT)], check=True)
    print("Compilando ch/build_ch...")
    src = ROUTINGKIT / "src"
    subprocess.run(["clang++", "-std=c++17", "-O3", "-DNDEBUG", f"-I{ROUTINGKIT / 'include'}", "-o", str(CH_TOOL),
                    str(CH_TOOL.with_suffix(".cpp")), *(str(src / f) for f in (
                        "contraction_hierarchy.cpp", "bit_vector.cpp", "timer.cpp", "vector_io.cpp", "graph_util.cpp"))],
                   check=True)


def build_contraction_hierarchy(node_count, tails, heads, weights):
    """Devuelve las secciones forward y backward de la CH (ver ch/build_ch.cpp y FORMAT.md)."""
    ensure_ch_tool()
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "grafo.bin", Path(tmp) / "ch.bin"
        with open(src, "wb") as f:
            f.write(struct.pack("<II", node_count, len(tails)))
            for arr in (tails, heads, weights):
                f.write(struct.pack(f"<{len(arr)}I", *arr))
        subprocess.run([str(CH_TOOL), str(src), str(dst)], check=True, stderr=subprocess.DEVNULL)
        data = dst.read_bytes()
    fwd_arcs = struct.unpack_from("<I", data, 0)[0]
    fwd_size = 4 + (node_count + 1) * 4 + fwd_arcs * CH_ARC.size
    return data[:fwd_size], data[fwd_size:]


class RoadCollector(osmium.SimpleHandler):
    """Recoge las vías aptas para el vehículo que tocan la región, con las coordenadas de sus nodos."""

    def __init__(self, bbox, profile):
        super().__init__()
        self.profile = profile
        self.min_lat, self.min_lon, self.max_lat, self.max_lon = bbox
        self.ways = []    # dicts con refs, clase, velocidad, sentido, glorieta, enlace, nombre
        self.coords = {}  # id OSM del nodo -> (lat, lon)

    def way(self, w):
        tags = w.tags
        highway = tags.get("highway")
        if highway not in HIGHWAYS:
            return
        if highway == "service" and tags.get("service") in EXCLUDED_SERVICE:
            return
        if tags.get("area") == "yes" or not vehicle_allowed(tags, self.profile):
            return

        refs, points, inside = [], [], False
        for n in w.nodes:
            loc = n.location
            if not loc.valid():
                continue
            lat, lon = loc.lat, loc.lon
            if not inside and self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon:
                inside = True
            refs.append(n.ref)
            points.append((lat, lon))
        if not inside or len(refs) < 2:
            return

        self.coords.update(zip(refs, points))
        road_class, default_speed = HIGHWAYS[highway]
        self.ways.append({
            "refs": refs,
            "class": road_class,
            "speed": parse_speed(tags.get("maxspeed"), default_speed),
            "oneway": oneway_direction(tags, highway, self.profile),
            "roundabout": tags.get("junction") in ("roundabout", "circular"),
            "link": highway.endswith("_link"),
            "name": tags.get("name") or tags.get("ref") or "",
        })


def split_into_segments(ways):
    """Parte cada vía en tramos entre nodos del grafo (intersecciones y extremos)."""
    usage = Counter()
    for way in ways:
        refs = way["refs"]
        usage.update(refs)  # un nodo repetido en la misma vía (lazo) también cuenta dos veces
        usage[refs[0]] += 1
        usage[refs[-1]] += 1

    segments = []  # (refs del tramo, vía)
    for way in ways:
        refs = way["refs"]
        start = 0
        for i in range(1, len(refs)):
            if usage[refs[i]] < 2:
                continue
            seg = refs[start:i + 1]
            start = i
            if seg[0] == seg[-1]:
                # Lazo cerrado sobre sí mismo: se parte por la mitad para que sea navegable.
                if len(seg) < 3:
                    continue
                mid = len(seg) // 2
                segments += [(seg[:mid + 1], way), (seg[mid:], way)]
            else:
                segments.append((seg, way))
    return segments


def build(pbf, bbox, out_path, profile):
    t0 = time.time()
    print(f"Leyendo {pbf} (región {bbox})...")
    collector = RoadCollector(bbox, profile)
    collector.apply_file(str(pbf), locations=True, idx="flex_mem")
    ways, coords = collector.ways, collector.coords
    print(f"  {len(ways):,} vías aptas ({time.time() - t0:.0f} s)")

    segments = split_into_segments(ways)
    graph_refs = {r for seg, _ in segments for r in (seg[0], seg[-1])}

    lats = [coords[r][0] for seg, _ in segments for r in seg]
    lons = [coords[r][1] for seg, _ in segments for r in seg]
    min_lat, max_lat, min_lon, max_lon = min(lats), max(lats), min(lons), max(lons)
    cols = int((max_lon - min_lon) / CELL_DEG) + 1
    rows = int((max_lat - min_lat) / CELL_DEG) + 1

    def cell_of(lat, lon):
        return int((lat - min_lat) / CELL_DEG), int((lon - min_lon) / CELL_DEG)

    # Nodos ordenados por curva Z (Morton) de su celda: lo que está cerca en el mapa, en cualquier dirección,
    # queda cerca en el archivo. Con un orden fila por fila, en un país cada fila cruza todo el mapa y una ruta
    # hacia el norte saltaría de un extremo del archivo al otro.
    order = sorted(graph_refs, key=lambda r: (morton(*cell_of(*coords[r])), coords[r]))
    node_id = {r: i for i, r in enumerate(order)}

    # Geometría y nombres: una sola copia por tramo, compartida por las dos direcciones. La geometría se
    # escribe después, en el orden de las aristas, para que también quede ordenada por cercanía.
    geom_blob, name_blob, name_off = bytearray(), bytearray(), {}
    seg_info = []  # (a, b, puntos intermedios, name_off, length, way)
    for seg, way in segments:
        pts = [coords[r] for r in seg]
        length = sum(haversine_m(pts[k], pts[k + 1]) for k in range(len(pts) - 1))
        g = simplify(pts, SIMPLIFY_TOLERANCE_M)[1:-1]
        name = way["name"]
        if not name:
            n = NONE
        elif name in name_off:
            n = name_off[name]
        else:
            n = name_off[name] = len(name_blob)
            name_blob += name.encode("utf-8") + b"\0"
        seg_info.append((node_id[seg[0]], node_id[seg[-1]], g, n, length, way))

    # Aristas dirigidas agrupadas por nodo de origen (CSR).
    out_edges = [[] for _ in order]
    for s_, (a, b, g, n, length, way) in enumerate(seg_info):
        flags = way["class"] | (FLAG_ROUNDABOUT if way["roundabout"] else 0) | (FLAG_LINK if way["link"] else 0)
        meters = round(length)
        if way["oneway"] >= 0:
            out_edges[a].append((b, g, n, meters, way["speed"], flags, s_))
        if way["oneway"] <= 0:
            out_edges[b].append((a, g, n, meters, way["speed"], flags | FLAG_GEOM_REVERSED, s_))

    nodes_blob, edges_blob = bytearray(), bytearray()
    tails, heads, weights = [], [], []
    seg_edge = {}  # tramo -> una de sus aristas, para el índice espacial
    seg_geom = {}  # tramo -> offset de su geometría (se escribe la primera vez que aparece)
    edge_count = 0
    for i, ref in enumerate(order):
        lat, lon = coords[ref]
        nodes_blob += NODE.pack(round(lat * SCALE), round(lon * SCALE), edge_count)
        for target, interior, n, meters, speed, flags, s_ in out_edges[i]:
            if s_ not in seg_geom:
                if interior:
                    seg_geom[s_] = len(geom_blob)
                    geom_blob += GEOM_HEADER.pack(len(interior), 0)
                    for plat, plon in interior:
                        geom_blob += POINT.pack(round(plat * SCALE), round(plon * SCALE))
                else:
                    seg_geom[s_] = NONE
            g = seg_geom[s_]
            weight = travel_time_ds(meters, speed)
            edges_blob += EDGE.pack(i, target, g, n, meters, weight, speed, flags, 0)
            tails.append(i)
            heads.append(target)
            weights.append(weight)
            seg_edge.setdefault(s_, edge_count)
            edge_count += 1
    nodes_blob += NODE.pack(0, 0, edge_count)  # centinela: fin de las aristas del último nodo

    # Índice espacial disperso: solo las celdas con vías (para un país, la cuadrícula completa sería enorme).
    # Por cada celda, las aristas cuyo tramo la toca (una arista por tramo).
    cells = {}
    for s_, (seg, _) in enumerate(segments):
        pts = [coords[r] for r in seg]
        r0, c0 = cell_of(min(p[0] for p in pts), min(p[1] for p in pts))
        r1, c1 = cell_of(max(p[0] for p in pts), max(p[1] for p in pts))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                cells.setdefault(r * cols + c, []).append(seg_edge[s_])
    cell_ids = sorted(cells)
    grid_blob = bytearray(struct.pack("<I", len(cell_ids)))
    grid_blob += struct.pack(f"<{len(cell_ids)}I", *cell_ids)
    total = 0
    starts = []
    for cid in cell_ids:
        starts.append(total)
        total += len(cells[cid])
    starts.append(total)
    grid_blob += struct.pack(f"<{len(starts)}I", *starts)
    for cid in cell_ids:
        grid_blob += struct.pack(f"<{len(cells[cid])}I", *cells[cid])

    print(f"  {len(order):,} nodos, {edge_count:,} aristas; calculando la jerarquía de contracción...")
    t_ch = time.time()
    ch_fwd, ch_bwd = build_contraction_hierarchy(len(order), tails, heads, weights)
    print(f"  jerarquía lista en {time.time() - t_ch:.0f} s")

    nodes_off = HEADER.size
    edges_off = nodes_off + len(nodes_blob)
    grid_off = edges_off + len(edges_blob)
    geom_off = grid_off + len(grid_blob)
    names_off = geom_off + len(geom_blob)
    ch_fwd_off = names_off + len(name_blob)
    ch_fwd_off += -ch_fwd_off % 4  # secciones de la CH alineadas a 4 bytes
    ch_bwd_off = ch_fwd_off + len(ch_fwd)
    file_size = ch_bwd_off + len(ch_bwd)
    header = HEADER.pack(
        MAGIC, VERSION, HEADER.size, len(order), edge_count,
        round(min_lat * SCALE), round(min_lon * SCALE), round(max_lat * SCALE), round(max_lon * SCALE),
        round(CELL_DEG * SCALE), cols, rows,
        nodes_off, edges_off, grid_off, geom_off, names_off, ch_fwd_off, ch_bwd_off, file_size,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        for part in (header, nodes_blob, edges_blob, grid_blob, geom_blob, name_blob):
            f.write(part)
        f.write(b"\0" * (ch_fwd_off - names_off - len(name_blob)))
        f.write(ch_fwd)
        f.write(ch_bwd)

    mb = lambda b: f"{len(b) / 1048576:,.1f} MB"
    print(f"  nodos {mb(nodes_blob)}, aristas {mb(edges_blob)}, índice {len(cell_ids):,} celdas ({mb(grid_blob)}), "
          f"geometría {mb(geom_blob)}, {len(name_off):,} nombres ({mb(name_blob)})")
    print(f"  jerarquía: forward {mb(ch_fwd)}, backward {mb(ch_bwd)}")
    chunks_dir = out_path.with_suffix("")
    chunks = write_chunks(out_path, chunks_dir)
    print(f"Listo: {out_path} ({file_size / 1048576:.1f} MB) en {time.time() - t0:.0f} s")
    print(f"Para la SD: {chunks_dir}/ ({chunks} archivos de {CHUNK_SIZE >> 20} MB) -> copiar a /maps/{chunks_dir.name}/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pbf", required=True, type=Path, help="extracto .osm.pbf (por ejemplo, Colombia de Geofabrik)")
    parser.add_argument("--region", default="bogota", choices=sorted(REGIONS))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--profile", default="moto", choices=sorted(PROFILES), help="vehículo (por defecto moto)")
    args = parser.parse_args()
    build(args.pbf, REGIONS[args.region], args.out, PROFILES[args.profile])
