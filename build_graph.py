#!/usr/bin/env python3
"""
Convierte un extracto de OpenStreetMap (.osm.pbf) en el grafo vial binario (.gmap) que lee la placa.

Solo se conservan las vías por las que puede ir una moto. Los nodos del grafo son las intersecciones
y los extremos de las vías; los puntos intermedios de cada tramo se guardan aparte como geometría
(para dibujar el cruce y calcular el ángulo de giro). El formato está en FORMAT.md.

Uso:
  python build_graph.py --pbf colombia.osm.pbf --region bogota --out out/bogota.gmap
"""
import argparse
import math
import time
from collections import Counter
from pathlib import Path

import osmium

from gmap_format import (
    EDGE, FLAG_GEOM_REVERSED, FLAG_LINK, FLAG_ROUNDABOUT, GEOM_HEADER, HEADER, MAGIC, NODE, NONE, POINT,
    SCALE, VERSION,
)

# min_lat, min_lon, max_lat, max_lon
REGIONS = {
    "bogota": (4.45, -74.25, 4.84, -73.98),
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
ACCESS_KEYS = ("motorcycle", "motor_vehicle", "vehicle", "access")  # del más específico al más general

CELL_DEG = 0.0025          # celda del índice espacial: ≈ 280 m
SIMPLIFY_TOLERANCE_M = 2.0  # Douglas-Peucker sobre la geometría intermedia


def moto_allowed(tags):
    for key in ACCESS_KEYS:
        value = tags.get(key)
        if value is not None:
            return value not in DENIED_ACCESS
    return True


def oneway_direction(tags, highway):
    """1 = solo en el sentido en que está dibujada la vía, -1 = solo en contra, 0 = doble sentido."""
    value = tags.get("oneway:motorcycle") or tags.get("oneway")
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


class RoadCollector(osmium.SimpleHandler):
    """Recoge las vías aptas para moto que tocan la región, con las coordenadas de sus nodos."""

    def __init__(self, bbox):
        super().__init__()
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
        if tags.get("area") == "yes" or not moto_allowed(tags):
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
            "oneway": oneway_direction(tags, highway),
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


def build(pbf, bbox, out_path):
    t0 = time.time()
    print(f"Leyendo {pbf} (región {bbox})...")
    collector = RoadCollector(bbox)
    collector.apply_file(str(pbf), locations=True, idx="flex_mem")
    ways, coords = collector.ways, collector.coords
    print(f"  {len(ways):,} vías aptas para moto ({time.time() - t0:.0f} s)")

    segments = split_into_segments(ways)
    graph_refs = {r for seg, _ in segments for r in (seg[0], seg[-1])}

    lats = [coords[r][0] for seg, _ in segments for r in seg]
    lons = [coords[r][1] for seg, _ in segments for r in seg]
    min_lat, max_lat, min_lon, max_lon = min(lats), max(lats), min(lons), max(lons)
    cols = int((max_lon - min_lon) / CELL_DEG) + 1
    rows = int((max_lat - min_lat) / CELL_DEG) + 1

    def cell_of(lat, lon):
        return int((lat - min_lat) / CELL_DEG), int((lon - min_lon) / CELL_DEG)

    # Nodos ordenados por celda: los que están cerca quedan cerca en la SD (menos lecturas al rutear).
    order = sorted(graph_refs, key=lambda r: (*cell_of(*coords[r]), coords[r]))
    node_id = {r: i for i, r in enumerate(order)}

    # Geometría y nombres: una sola copia por tramo, compartida por las dos direcciones.
    geom_blob, name_blob, name_off = bytearray(), bytearray(), {}
    seg_info = []  # (a, b, geom_off, name_off, length, way)
    for seg, way in segments:
        pts = [coords[r] for r in seg]
        length = sum(haversine_m(pts[k], pts[k + 1]) for k in range(len(pts) - 1))
        interior = simplify(pts, SIMPLIFY_TOLERANCE_M)[1:-1]
        if interior:
            g = len(geom_blob)
            geom_blob += GEOM_HEADER.pack(len(interior), 0)
            for lat, lon in interior:
                geom_blob += POINT.pack(round(lat * SCALE), round(lon * SCALE))
        else:
            g = NONE
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
    too_long = 0
    for s, (a, b, g, n, length, way) in enumerate(seg_info):
        flags = way["class"] | (FLAG_ROUNDABOUT if way["roundabout"] else 0) | (FLAG_LINK if way["link"] else 0)
        if length > 65_535:
            too_long += 1
        meters = min(round(length), 65_535)
        if way["oneway"] >= 0:
            out_edges[a].append((b, g, n, meters, way["speed"], flags, s))
        if way["oneway"] <= 0:
            out_edges[b].append((a, g, n, meters, way["speed"], flags | FLAG_GEOM_REVERSED, s))

    nodes_blob, edges_blob = bytearray(), bytearray()
    seg_edge = {}  # tramo -> una de sus aristas, para el índice espacial
    edge_count = 0
    for i, ref in enumerate(order):
        lat, lon = coords[ref]
        nodes_blob += NODE.pack(round(lat * SCALE), round(lon * SCALE), edge_count)
        for target, g, n, meters, speed, flags, s in out_edges[i]:
            edges_blob += EDGE.pack(target, g, n, meters, speed, flags)
            seg_edge.setdefault(s, edge_count)
            edge_count += 1
    nodes_blob += NODE.pack(0, 0, edge_count)  # centinela: fin de las aristas del último nodo

    # Índice espacial: por cada celda, las aristas cuyo tramo la toca (una arista por tramo).
    cells = [[] for _ in range(rows * cols)]
    for s, (seg, _) in enumerate(segments):
        pts = [coords[r] for r in seg]
        r0, c0 = cell_of(min(p[0] for p in pts), min(p[1] for p in pts))
        r1, c1 = cell_of(max(p[0] for p in pts), max(p[1] for p in pts))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                cells[r * cols + c].append(seg_edge[s])
    grid_index, grid_items = bytearray(), bytearray()
    total = 0
    for items in cells:
        grid_index += total.to_bytes(4, "little")
        for e in items:
            grid_items += e.to_bytes(4, "little")
        total += len(items)
    grid_index += total.to_bytes(4, "little")

    nodes_off = HEADER.size
    edges_off = nodes_off + len(nodes_blob)
    grid_off = edges_off + len(edges_blob)
    geom_off = grid_off + len(grid_index) + len(grid_items)
    names_off = geom_off + len(geom_blob)
    file_size = names_off + len(name_blob)
    header = HEADER.pack(
        MAGIC, VERSION, HEADER.size, len(order), edge_count,
        round(min_lat * SCALE), round(min_lon * SCALE), round(max_lat * SCALE), round(max_lon * SCALE),
        round(CELL_DEG * SCALE), cols, rows,
        nodes_off, edges_off, grid_off, geom_off, names_off, file_size,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        for part in (header, nodes_blob, edges_blob, grid_index, grid_items, geom_blob, name_blob):
            f.write(part)

    kb = lambda b: f"{len(b) / 1024:,.0f} KB"
    print(f"  {len(order):,} nodos ({kb(nodes_blob)}), {edge_count:,} aristas ({kb(edges_blob)})")
    print(f"  índice {cols}×{rows} celdas ({kb(grid_index + grid_items)}), "
          f"geometría {kb(geom_blob)}, {len(name_off):,} nombres ({kb(name_blob)})")
    if too_long:
        print(f"  aviso: {too_long} tramos de más de 65 km quedaron truncados a 65 535 m")
    print(f"Listo: {out_path} ({file_size / 1024 / 1024:.1f} MB) en {time.time() - t0:.0f} s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pbf", required=True, type=Path, help="extracto .osm.pbf (por ejemplo, Colombia de Geofabrik)")
    parser.add_argument("--region", default="bogota", choices=sorted(REGIONS))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    build(args.pbf, REGIONS[args.region], args.out)
