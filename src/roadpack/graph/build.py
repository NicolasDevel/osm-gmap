"""Graph layer: turns drivable OSM ways into a compact routing graph.

- Nodes are only intersections and way endpoints; the points in between become segment geometry,
  simplified with Douglas-Peucker. This is what shrinks the network the most.
- Nodes are sorted along a Z-order (Morton) curve, so things that are close on the map, in any direction,
  are close in the file. Edges follow node order (CSR), so a page read from an SD card serves a whole area.
- A sparse spatial grid maps each cell to the edges that touch it (to snap a GPS fix to a road).
"""
import time
from collections import Counter
from dataclasses import dataclass, field

from ..format.spec import FLAG_GEOM_REVERSED, FLAG_LINK, FLAG_ROUNDABOUT, travel_time_ds
from ..geo import haversine_m, morton, simplify
from ..osm.loader import RoadNetwork, Way

CELL_DEG = 0.0025          # spatial grid cell: ≈ 280 m
SIMPLIFY_TOLERANCE_M = 2.0  # Douglas-Peucker on the geometry between nodes


@dataclass(slots=True)
class Segment:
    """Piece of a way between two graph nodes. Both directions of a two-way road share it."""
    a: int            # node at the start of the way's drawing direction
    b: int
    interior: list    # simplified points strictly between a and b
    length_m: float   # along the original (unsimplified) geometry
    bbox: tuple       # (min_lat, min_lon, max_lat, max_lon) of the original geometry
    way: Way


@dataclass(slots=True)
class Edge:
    source: int
    target: int
    segment: int
    length_m: int
    weight: int       # travel time in tenths of a second
    speed: int
    flags: int        # road class | FLAG_* (see format/spec.py)


@dataclass
class Grid:
    min_lat: float
    min_lon: float
    cell_deg: float
    cols: int
    rows: int
    cells: dict       # cell id (row * cols + col) -> edge ids, one edge per segment touching the cell

    def cell_of(self, lat, lon):
        return int((lat - self.min_lat) / self.cell_deg), int((lon - self.min_lon) / self.cell_deg)


@dataclass
class RoadGraph:
    nodes: list           # (lat, lon), in Morton order
    osm_ids: list         # OSM node id of each graph node
    segments: list
    edges: list           # grouped by source node, in node order
    first_edge: list      # CSR: edges of node n are edges[first_edge[n]:first_edge[n + 1]]
    bounds: tuple         # (min_lat, min_lon, max_lat, max_lon)
    grid: Grid
    stats: dict = field(default_factory=dict)


def split_into_segments(ways):
    """Split each way at graph nodes (intersections and endpoints). Returns [(node refs, way)]."""
    usage = Counter()
    for way in ways:
        refs = way.refs
        usage.update(refs)  # a node repeated in the same way (a loop) also counts twice
        usage[refs[0]] += 1
        usage[refs[-1]] += 1

    segments = []
    for way in ways:
        refs = way.refs
        start = 0
        for i in range(1, len(refs)):
            if usage[refs[i]] < 2:
                continue
            seg = refs[start:i + 1]
            start = i
            if seg[0] == seg[-1]:
                # A segment that closes on itself: split it in half so it can be routed through.
                if len(seg) < 3:
                    continue
                mid = len(seg) // 2
                segments += [(seg[:mid + 1], way), (seg[mid:], way)]
            else:
                segments.append((seg, way))
    return segments


def build_graph(network: RoadNetwork, cell_deg=CELL_DEG, simplify_tolerance_m=SIMPLIFY_TOLERANCE_M) -> RoadGraph:
    t0 = time.time()
    coords = network.coords
    raw_segments = split_into_segments(network.ways)
    if not raw_segments:
        raise ValueError("no drivable roads in the selected area")
    graph_refs = {r for seg, _ in raw_segments for r in (seg[0], seg[-1])}

    lats = [coords[r][0] for seg, _ in raw_segments for r in seg]
    lons = [coords[r][1] for seg, _ in raw_segments for r in seg]
    min_lat, max_lat, min_lon, max_lon = min(lats), max(lats), min(lons), max(lons)
    grid = Grid(min_lat, min_lon, cell_deg,
                cols=int((max_lon - min_lon) / cell_deg) + 1, rows=int((max_lat - min_lat) / cell_deg) + 1, cells={})

    # With a row-by-row order each row of a country spans the whole map, and a route heading north would
    # jump from one end of the file to the other. The Z-order keeps both directions local.
    order = sorted(graph_refs, key=lambda r: (morton(*grid.cell_of(*coords[r])), coords[r]))
    node_id = {r: i for i, r in enumerate(order)}

    segments = []
    shape_points = 0
    for refs, way in raw_segments:
        pts = [coords[r] for r in refs]
        length = sum(haversine_m(pts[k], pts[k + 1]) for k in range(len(pts) - 1))
        bbox = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        shape_points += len(pts) - 2
        segments.append(Segment(node_id[refs[0]], node_id[refs[-1]], simplify(pts, simplify_tolerance_m)[1:-1],
                                length, bbox, way))

    # Directed edges grouped by source node (CSR).
    out_edges = [[] for _ in order]
    for s, seg in enumerate(segments):
        way = seg.way
        flags = way.road_class | (FLAG_ROUNDABOUT if way.roundabout else 0) | (FLAG_LINK if way.link else 0)
        meters = round(seg.length_m)
        weight = travel_time_ds(meters, way.speed)
        if way.oneway >= 0:
            out_edges[seg.a].append(Edge(seg.a, seg.b, s, meters, weight, way.speed, flags))
        if way.oneway <= 0:
            out_edges[seg.b].append(Edge(seg.b, seg.a, s, meters, weight, way.speed, flags | FLAG_GEOM_REVERSED))
    edges, first_edge = [], []
    for out in out_edges:
        first_edge.append(len(edges))
        edges += out
    first_edge.append(len(edges))
    del out_edges

    # Sparse spatial grid: only cells with roads (for a country, the full grid would be huge).
    seg_edge = {}
    for e, edge in enumerate(edges):
        seg_edge.setdefault(edge.segment, e)
    for s, seg in enumerate(segments):
        r0, c0 = grid.cell_of(seg.bbox[0], seg.bbox[1])
        r1, c1 = grid.cell_of(seg.bbox[2], seg.bbox[3])
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                grid.cells.setdefault(r * grid.cols + c, []).append(seg_edge[s])

    stats = {
        "osm_ways": len(network.ways),
        "osm_nodes": len(coords),
        "segments": len(segments),
        "shape_points": shape_points,
        "shape_points_kept": sum(len(seg.interior) for seg in segments),
        "graph_seconds": time.time() - t0,
    }
    return RoadGraph([coords[r] for r in order], order, segments, edges, first_edge,
                     (min_lat, min_lon, max_lat, max_lon), grid, stats)
