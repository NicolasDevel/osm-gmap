"""Reference reader of the .gmap format: nodes, edges, geometry, names, the spatial grid and the contraction
hierarchy. A device does the same with seek + read instead of loading the whole file.
"""
import bisect
import math
from pathlib import Path

import numpy as np

from ..geo import local_xy
from .chunks import join_chunks
from .spec import (CLASS_MASK, COPY, FLAG_GEOM_REVERSED, FLAG_ROUNDABOUT, GEOM_HEADER, HEADER, HEADER_V2, MAGIC, NONE,
                   POINT, READ_VERSIONS, SCALE)

NODE_DTYPE = np.dtype([("lat", "<i4"), ("lon", "<i4"), ("first_edge", "<u4")])
EDGE_DTYPE = np.dtype([
    ("source", "<u4"), ("target", "<u4"), ("geom", "<u4"), ("name", "<u4"), ("length", "<u4"), ("weight", "<u4"),
    ("speed", "u1"), ("flags", "u1"), ("pad", "<u2"),
])
CH_ARC_DTYPE = np.dtype([("other", "<u4"), ("weight", "<u4"), ("a", "<u4"), ("b", "<u4")])


def _column(values):
    """Read-only column with fast element access that returns Python numbers, at 4–8 bytes per value
    (a list would take ~32): big maps fit in memory."""
    return memoryview(np.ascontiguousarray(values))


class ChSide:
    """One side of the contraction hierarchy: upward adjacency lists, indexed by node."""

    def __init__(self, data, offset, node_count):
        arcs = int(np.frombuffer(data, "<u4", 1, offset)[0])
        first = np.frombuffer(data, "<u4", node_count + 1, offset + 4)
        recs = np.frombuffer(data, CH_ARC_DTYPE, arcs, offset + 4 + (node_count + 1) * 4)
        self.first = _column(first)
        self.other = _column(recs["other"])
        self.weight = _column(recs["weight"])
        self.a = _column(recs["a"])
        self.b = _column(recs["b"])
        self.arc_count = arcs
        self.first_off = offset + 4  # file offsets, to measure what a device reads
        self.arcs_off = offset + 4 + (node_count + 1) * 4


class Gmap:
    """A .gmap loaded in memory. `path` may be the .gmap file or a directory of SD card chunks."""

    def __init__(self, path):
        path = Path(path)
        self.data = join_chunks(path) if path.is_dir() else path.read_bytes()
        invalid = ValueError(f"{path} is not a valid .gmap (versions {', '.join(map(str, READ_VERSIONS))})")
        if len(self.data) < HEADER_V2.size:
            raise invalid
        (magic, self.version, _, self.node_count, self.edge_count,
         min_lat, min_lon, max_lat, max_lon, cell, self.cols, self.rows,
         self.nodes_off, self.edges_off, self.grid_off, self.geom_off, self.names_off, self.ch_fwd_off,
         self.ch_bwd_off, file_size) = HEADER_V2.unpack_from(self.data)
        if magic != MAGIC or self.version not in READ_VERSIONS or file_size != len(self.data):
            raise invalid
        self.copies_off, copy_count = HEADER.unpack_from(self.data)[-2:] if self.version >= 3 else (file_size, 0)
        self.min_lat, self.min_lon = min_lat / SCALE, min_lon / SCALE
        self.max_lat, self.max_lon = max_lat / SCALE, max_lon / SCALE
        self.cell = cell / SCALE

        nodes = np.frombuffer(self.data, NODE_DTYPE, self.node_count + 1, self.nodes_off)
        edges = np.frombuffer(self.data, EDGE_DTYPE, self.edge_count, self.edges_off)

        # Sparse spatial grid: sorted non-empty cells, where each one starts, and the edges.
        grid_off = self.grid_off
        cell_count = int(np.frombuffer(self.data, "<u4", 1, grid_off)[0])
        self.cell_ids = _column(np.frombuffer(self.data, "<u4", cell_count, grid_off + 4))
        self.cell_start = np.frombuffer(self.data, "<u4", cell_count + 1, grid_off + 4 + cell_count * 4)
        self.cell_items = np.frombuffer(self.data, "<u4", int(self.cell_start[-1]),
                                        grid_off + 4 + (2 * cell_count + 1) * 4)

        # Element access on numpy arrays is slow inside Python loops; memoryviews are as fast as lists.
        self.lat = _column(nodes["lat"] / SCALE)
        self.lon = _column(nodes["lon"] / SCALE)
        self.first_edge = _column(nodes["first_edge"])
        self.source = _column(edges["source"])
        self.target = _column(edges["target"])
        self.geom = _column(edges["geom"])
        self.name_ref = _column(edges["name"])
        self.length = _column(edges["length"])
        self.weight = _column(edges["weight"])
        self.speed = _column(edges["speed"])
        self.flags = _column(edges["flags"])
        self._in_edges = None

        self.ch_fwd = ChSide(self.data, self.ch_fwd_off, self.node_count)
        self.ch_bwd = ChSide(self.data, self.ch_bwd_off, self.node_count)

        # Junction copies made by turn restrictions: original of every node (itself if it is not a copy).
        copies = np.frombuffer(self.data, "<u4", 2 * copy_count, self.copies_off).reshape(-1, 2)
        assert COPY.size == 8
        self.copy_count = copy_count
        original = np.arange(self.node_count, dtype=np.int64)
        original[copies[:, 0]] = copies[:, 1]
        self._original = _column(original)

    def section_sizes(self):
        """Bytes used by each section of the file."""
        offs = [("header", 0), ("nodes", self.nodes_off), ("edges", self.edges_off), ("grid", self.grid_off),
                ("geometry", self.geom_off), ("names", self.names_off), ("ch_forward", self.ch_fwd_off),
                ("ch_backward", self.ch_bwd_off), ("copies", self.copies_off)]
        ends = [o for _, o in offs[1:]] + [len(self.data)]
        return {name: end - off for (name, off), end in zip(offs, ends)}

    def original(self, node):
        """The junction a node stands for: itself, or the node it is a copy of (turn restrictions)."""
        return self._original[node]

    def is_copy(self, node):
        return self._original[node] != node

    def copies_of(self, node):
        """Copies of a junction: they follow it in node order."""
        out = []
        n = node + 1
        while n < self.node_count and self._original[n] == node:
            out.append(n)
            n += 1
        return out

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
        """Points of the edge from its source to its target, endpoints included."""
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
        """Closest node to a position, searching the neighbouring cells of the spatial grid."""
        for radius in (1, 2, 4, 8):
            candidates = {self.original(n) for e in self.edges_near(lat, lon, radius)
                          for n in (self.source[e], self.target[e])}
            if candidates:
                return min(candidates, key=lambda n: math.hypot(*local_xy((lat, lon), self.point(n))))
        raise ValueError(f"no roads near {lat}, {lon}")
