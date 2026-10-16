"""
Lector del formato .gmap. Es la implementación de referencia de lo que hará el firmware:
leer nodos y aristas, recorrer la geometría, buscar en el índice espacial y leer la jerarquía de contracción.
"""
import bisect
import math
from pathlib import Path

import numpy as np

from gmap_format import (
    CH_ARC, CLASS_MASK, FLAG_GEOM_REVERSED, FLAG_ROUNDABOUT, GEOM_HEADER, HEADER, MAGIC, NONE, POINT, SCALE, VERSION,
)

NODE_DTYPE = np.dtype([("lat", "<i4"), ("lon", "<i4"), ("first_edge", "<u4")])
EDGE_DTYPE = np.dtype([
    ("source", "<u4"), ("target", "<u4"), ("geom", "<u4"), ("name", "<u4"), ("length", "<u4"), ("weight", "<u4"),
    ("speed", "u1"), ("flags", "u1"), ("pad", "<u2"),
])
CH_ARC_DTYPE = np.dtype([("other", "<u4"), ("weight", "<u4"), ("a", "<u4"), ("b", "<u4")])


def local_xy(origin, point):
    """Metros (este, norte) de point respecto a origin. Suficiente a escala de ciudad."""
    k = math.cos(math.radians(origin[0]))
    return (point[1] - origin[1]) * 111_320 * k, (point[0] - origin[0]) * 110_540


def bearing(a, b):
    """Rumbo de a hacia b en grados: 0 = norte, 90 = este."""
    x, y = local_xy(a, b)
    return math.degrees(math.atan2(x, y)) % 360


class ChSide:
    """Un lado de la jerarquía de contracción: lista de adyacencia hacia arriba, indexada por nodo."""

    def __init__(self, data, offset, node_count):
        arcs = int(np.frombuffer(data, "<u4", 1, offset)[0])
        first = np.frombuffer(data, "<u4", node_count + 1, offset + 4)
        recs = np.frombuffer(data, CH_ARC_DTYPE, arcs, offset + 4 + (node_count + 1) * 4)
        self.first = first.tolist()
        self.other = recs["other"].tolist()
        self.weight = recs["weight"].tolist()
        self.a = recs["a"].tolist()
        self.b = recs["b"].tolist()
        self.arc_count = arcs


class Graph:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        (magic, version, _, self.node_count, self.edge_count,
         min_lat, min_lon, max_lat, max_lon, cell, self.cols, self.rows,
         nodes_off, edges_off, grid_off, self.geom_off, self.names_off, ch_fwd_off, ch_bwd_off,
         file_size) = HEADER.unpack_from(self.data)
        if magic != MAGIC or version != VERSION or file_size != len(self.data):
            raise ValueError(f"{path} no es un .gmap v{VERSION} válido")
        self.min_lat, self.min_lon = min_lat / SCALE, min_lon / SCALE
        self.max_lat, self.max_lon = max_lat / SCALE, max_lon / SCALE
        self.cell = cell / SCALE

        nodes = np.frombuffer(self.data, NODE_DTYPE, self.node_count + 1, nodes_off)
        edges = np.frombuffer(self.data, EDGE_DTYPE, self.edge_count, edges_off)

        # Índice espacial disperso: celdas no vacías ordenadas, inicio de cada una y las aristas.
        cell_count = int(np.frombuffer(self.data, "<u4", 1, grid_off)[0])
        self.cell_ids = np.frombuffer(self.data, "<u4", cell_count, grid_off + 4).tolist()
        self.cell_start = np.frombuffer(self.data, "<u4", cell_count + 1, grid_off + 4 + cell_count * 4)
        self.cell_items = np.frombuffer(self.data, "<u4", int(self.cell_start[-1]), grid_off + 4 + (2 * cell_count + 1) * 4)

        # Listas de Python: el acceso por elemento es mucho más rápido que con numpy dentro de los bucles.
        self.lat = (nodes["lat"] / SCALE).tolist()
        self.lon = (nodes["lon"] / SCALE).tolist()
        self.first_edge = nodes["first_edge"].tolist()
        self.source = edges["source"].tolist()
        self.target = edges["target"].tolist()
        self.geom = edges["geom"].tolist()
        self.name_ref = edges["name"].tolist()
        self.length = edges["length"].tolist()
        self.weight = edges["weight"].tolist()
        self.speed = edges["speed"].tolist()
        self.flags = edges["flags"].tolist()
        self._in_edges = None

        self.ch_fwd = ChSide(self.data, ch_fwd_off, self.node_count)
        self.ch_bwd = ChSide(self.data, ch_bwd_off, self.node_count)

    def point(self, node):
        return self.lat[node], self.lon[node]

    def out_edges(self, node):
        return range(self.first_edge[node], self.first_edge[node + 1])

    def in_edges(self, node):
        if self._in_edges is None:
            self._in_edges = [[] for _ in range(self.node_count)]
            for e, t in enumerate(self.target):
                self._in_edges[t].append(e)
        return self._in_edges[node]

    def road_class(self, e):
        return self.flags[e] & CLASS_MASK

    def is_roundabout(self, e):
        return bool(self.flags[e] & FLAG_ROUNDABOUT)

    def name(self, e):
        off = self.name_ref[e]
        if off == NONE:
            return ""
        start = self.names_off + off
        return self.data[start:self.data.index(b"\0", start)].decode("utf-8")

    def polyline(self, e):
        """Puntos de la arista desde su origen hasta su destino, incluidos los extremos."""
        inner = []
        g = self.geom[e]
        if g != NONE:
            off = self.geom_off + g
            count, _ = GEOM_HEADER.unpack_from(self.data, off)
            off += GEOM_HEADER.size
            for k in range(count):
                lat, lon = POINT.unpack_from(self.data, off + k * POINT.size)
                inner.append((lat / SCALE, lon / SCALE))
            if self.flags[e] & FLAG_GEOM_REVERSED:
                inner.reverse()
        return [self.point(self.source[e]), *inner, self.point(self.target[e])]

    def edges_in_cell(self, row, col):
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return []
        cid = row * self.cols + col
        k = bisect.bisect_left(self.cell_ids, cid)
        if k == len(self.cell_ids) or self.cell_ids[k] != cid:
            return []
        return self.cell_items[self.cell_start[k]:self.cell_start[k + 1]].tolist()

    def edges_near(self, lat, lon, radius_cells=1):
        row = int((lat - self.min_lat) / self.cell)
        col = int((lon - self.min_lon) / self.cell)
        found = set()
        for r in range(row - radius_cells, row + radius_cells + 1):
            for c in range(col - radius_cells, col + radius_cells + 1):
                found.update(self.edges_in_cell(r, c))
        return found

    def nearest_node(self, lat, lon):
        """Nodo más cercano a la posición, buscando en las celdas vecinas del índice espacial."""
        for radius in (1, 2, 4, 8):
            candidates = {n for e in self.edges_near(lat, lon, radius) for n in (self.source[e], self.target[e])}
            if candidates:
                return min(candidates, key=lambda n: math.hypot(*local_xy((lat, lon), self.point(n))))
        raise ValueError(f"No hay vías cerca de {lat}, {lon}")
