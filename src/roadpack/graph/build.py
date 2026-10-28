"""Graph layer: turns drivable OSM ways into a compact routing graph.

- Nodes are only intersections and way endpoints; the points in between become segment geometry,
  simplified with Douglas-Peucker. This is what shrinks the network the most.
- Nodes are sorted along a Z-order (Morton) curve, so things that are close on the map, in any direction,
  are close in the file. Edges follow node order (CSR), so a page read from an SD card serves a whole area.
- A sparse spatial grid maps each cell to the edges that touch it (to snap a GPS fix to a road).

Everything is vectorized with numpy, except Douglas-Peucker on segments that have interior points.
"""
import time
from dataclasses import dataclass, field

import numpy as np

from ..format.spec import FLAG_GEOM_REVERSED, FLAG_LINK, FLAG_ROUNDABOUT
from ..arrays import first_occurrences, ranges, unique
from ..geo import simplify_indices
from ..osm.loader import COORD_SCALE, RoadNetwork

CELL_DEG = 0.0025          # spatial grid cell: ≈ 280 m
SIMPLIFY_TOLERANCE_M = 2.0  # Douglas-Peucker on the geometry between nodes
EARTH_RADIUS_M = 6_371_000


@dataclass
class Grid:
    min_lat: float
    min_lon: float
    cell_deg: float
    cols: int
    rows: int
    cell_ids: np.ndarray   # sorted non-empty cells (row * cols + col)
    cell_start: np.ndarray  # cell k lists items[cell_start[k]:cell_start[k + 1]]
    items: np.ndarray      # edge ids, one edge per segment touching the cell

    def cell_of(self, lat, lon):
        return int((lat - self.min_lat) / self.cell_deg), int((lon - self.min_lon) / self.cell_deg)

    def cell(self, cid):
        k = np.searchsorted(self.cell_ids, cid)
        if k == len(self.cell_ids) or self.cell_ids[k] != cid:
            return np.zeros(0, np.int64)
        return self.items[self.cell_start[k]:self.cell_start[k + 1]]


@dataclass
class RoadGraph:
    """Columnar routing graph. Segments are pieces of ways between two graph nodes; both directions of a
    two-way road share one segment (and its geometry)."""
    lat7: np.ndarray          # int32 per node, degrees × 1e7, in Morton order
    lon7: np.ndarray
    osm_ids: np.ndarray       # int64 OSM id per node
    seg_a: np.ndarray         # node at the start of the way's drawing direction
    seg_b: np.ndarray
    seg_length: np.ndarray    # float64 meters along the original (unsimplified) geometry
    seg_name: np.ndarray      # int32 index into names, or -1
    seg_geom_start: np.ndarray  # interior points of segment s: geom_*[seg_geom_start[s]:seg_geom_start[s + 1]]
    geom_lat7: np.ndarray
    geom_lon7: np.ndarray
    names: list
    source: np.ndarray        # edges, grouped by source node in node order (CSR)
    target: np.ndarray
    segment: np.ndarray
    length_m: np.ndarray      # uint32, rounded meters
    weight: np.ndarray        # uint32, travel time in tenths of a second
    speed: np.ndarray         # uint8 km/h
    flags: np.ndarray         # uint8: road class | FLAG_* (see format/spec.py)
    first_edge: np.ndarray    # edges of node n are first_edge[n]:first_edge[n + 1]
    bounds: tuple             # (min_lat, min_lon, max_lat, max_lon)
    grid: Grid
    seg_way: np.ndarray = None  # way index (into the RoadNetwork) of each segment
    stats: dict = field(default_factory=dict)
    # Turn restrictions (see restrictions.py): copies of junctions, sorted, and the original of each one.
    copy_nodes: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))
    copy_original: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int64))

    @property
    def node_count(self):
        return len(self.lat7)

    @property
    def edge_count(self):
        return len(self.source)

    def interior(self, s):
        """Simplified interior points of segment s as [(lat, lon)]."""
        a, b = self.seg_geom_start[s], self.seg_geom_start[s + 1]
        return list(zip((self.geom_lat7[a:b] / COORD_SCALE).tolist(), (self.geom_lon7[a:b] / COORD_SCALE).tolist()))


def split_into_segments(way_start, refs):
    """Split ways at graph nodes: nodes used twice or more (intersections, self-crossings) and way endpoints.

    Returns (starts, ends): inclusive positions in refs of each segment, in way order. A segment that closes on
    itself is split in half so it can be routed through; a two-point one is dropped.
    """
    n_ways = len(way_start) - 1
    if len(refs) == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64)
    first, last = way_start[:-1], way_start[1:] - 1
    usage = np.bincount(refs, minlength=refs.max() + 1)
    usage += np.bincount(refs[first], minlength=len(usage)) + np.bincount(refs[last], minlength=len(usage))
    cuts = np.flatnonzero(usage[refs] >= 2)  # always includes both ends of every way
    way_of = np.repeat(np.arange(n_ways), np.diff(way_start))
    s, e = cuts[:-1], cuts[1:]
    same_way = way_of[s] == way_of[e]
    s, e = s[same_way], e[same_way]

    closed = refs[s] == refs[e]
    halve = closed & (e - s + 1 >= 3)
    mid = s[halve] + (e[halve] - s[halve] + 1) // 2
    starts = np.concatenate([s[~closed], s[halve], mid])
    ends = np.concatenate([e[~closed], mid, e[halve]])
    order = np.argsort(starts, kind="stable")
    return starts[order], ends[order]


def _morton(row, col):
    """Z-order index of 16-bit row and column arrays (bits interleaved, column in the even bits)."""
    def spread(x):
        x = x.astype(np.uint64) & 0xFFFF
        x = (x | (x << 8)) & 0x00FF00FF
        x = (x | (x << 4)) & 0x0F0F0F0F
        x = (x | (x << 2)) & 0x33333333
        return (x | (x << 1)) & 0x55555555
    return spread(col) | (spread(row) << 1)


def _haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(v) for v in (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(h))


def _sequential_sums(values, offsets):
    """Sum of each slice values[offsets[k]:offsets[k + 1]], left to right with Neumaier compensation, exactly
    like Python's sum() of floats (3.12+). Accurate, and independent of numpy's pairwise summation."""
    counts = np.diff(offsets)
    order = np.argsort(-counts, kind="stable")
    sorted_counts, sorted_off = counts[order], offsets[:-1][order]
    f, c = np.zeros(len(counts)), np.zeros(len(counts))
    for j in range(int(sorted_counts[0]) if len(counts) else 0):
        n = int(np.searchsorted(-sorted_counts, -j, side="left"))  # slices longer than j come first
        x, fn = values[sorted_off[:n] + j], f[:n]
        t = fn + x
        c[:n] += np.where(np.abs(fn) >= np.abs(x), (fn - t) + x, (x - t) + fn)
        f[:n] = t
    f += np.where(np.isfinite(c), c, 0.0)
    out = np.empty(len(counts))
    out[order] = f
    return out


GRID_STEP = 0.25  # sampling step along the geometry, in cells


def _cells_crossed(lat, lon, pt_off, min_lat, min_lon, cell_deg, rows, cols):
    """(segment, cell id) of every grid cell the polylines cross. Points of segment s are lat/lon[pt_off[s]:
    pt_off[s + 1]]. Each piece is sampled every GRID_STEP cells, both ends included; when two consecutive samples
    differ in both row and column, the two corner cells are added too, so no crossed cell is missed (a superset of
    the exact traversal, only ever by a cell the line passes within a quarter cell of). Pairs may repeat."""
    x = (lon - min_lon) / cell_deg
    y = (lat - min_lat) / cell_deg
    seg_of_point = np.repeat(np.arange(len(pt_off) - 1), np.diff(pt_off))
    starts = np.ones(len(lat), bool)
    starts[pt_off[1:] - 1] = False  # the last point of a segment starts no piece
    i = np.flatnonzero(starts[:-1])
    dx, dy = x[i + 1] - x[i], y[i + 1] - y[i]
    steps = np.maximum(1, np.ceil(np.hypot(dx, dy) / GRID_STEP)).astype(np.int64)
    piece = np.repeat(np.arange(len(i)), steps + 1)
    t = ranges(np.zeros(len(i), np.int64), steps + 1) / steps[piece]
    r = np.clip(np.floor(y[i][piece] + dy[piece] * t).astype(np.int64), 0, rows - 1)
    c = np.clip(np.floor(x[i][piece] + dx[piece] * t).astype(np.int64), 0, cols - 1)
    seg = seg_of_point[i][piece]
    # Diagonal moves between consecutive samples of a piece: add both corner cells.
    diag = np.flatnonzero((piece[1:] == piece[:-1]) & (r[1:] != r[:-1]) & (c[1:] != c[:-1]))
    seg = np.concatenate([seg, seg[diag], seg[diag]])
    cid = np.concatenate([r * cols + c, r[diag] * cols + c[diag + 1], r[diag + 1] * cols + c[diag]])
    return seg, cid


def build_graph(network: RoadNetwork, cell_deg=CELL_DEG, simplify_tolerance_m=SIMPLIFY_TOLERANCE_M) -> RoadGraph:
    t0 = time.time()
    refs = network.refs
    starts, ends = split_into_segments(network.way_start, refs)
    if len(starts) == 0:
        raise ValueError("no drivable roads in the selected area")
    lat_all, lon_all = network.lat(), network.lon()
    seg_way = np.repeat(np.arange(network.way_count), np.diff(network.way_start))[starts]

    # Every point of every segment, segment after segment (shared endpoints repeated).
    npts = ends - starts + 1
    pos = ranges(starts, npts)
    pt_off = np.zeros(len(starts) + 1, np.int64)
    np.cumsum(npts, out=pt_off[1:])
    plat, plon = lat_all[refs[pos]], lon_all[refs[pos]]
    min_lat, max_lat, min_lon, max_lon = plat.min(), plat.max(), plon.min(), plon.max()
    cols = int((max_lon - min_lon) / cell_deg) + 1
    rows = int((max_lat - min_lat) / cell_deg) + 1

    # Graph nodes in Morton order of their cell (ties: by position, then OSM id). With a row-by-row order each
    # row of a country spans the whole map, and a route heading north would jump from one end of the file to the
    # other; the Z-order keeps both directions local.
    gnodes = unique(np.concatenate([refs[starts], refs[ends]]))
    glat, glon = lat_all[gnodes], lon_all[gnodes]
    code = _morton(((glat - min_lat) / cell_deg).astype(np.int64), ((glon - min_lon) / cell_deg).astype(np.int64))
    order = np.lexsort((network.node_ids[gnodes], glon, glat, code))
    gnodes = gnodes[order]
    node_index = np.full(network.node_count, -1, np.int64)
    node_index[gnodes] = np.arange(len(gnodes))
    seg_a, seg_b = node_index[refs[starts]], node_index[refs[ends]]

    # Lengths along the original geometry, summed point by point like the reference (rounding stays identical).
    pair = np.ones(len(plat), bool)
    pair[pt_off[1:] - 1] = False  # the last point of a segment starts no pair
    d = _haversine(plat[:-1], plon[:-1], plat[1:], plon[1:])
    d = d[pair[:-1]]
    pair_off = np.zeros(len(starts) + 1, np.int64)
    np.cumsum(npts - 1, out=pair_off[1:])
    seg_length = _sequential_sums(d, pair_off)

    # Douglas-Peucker on segments with interior points.
    keep = np.zeros(len(plat), bool)
    curved = np.flatnonzero(npts > 2)
    for batch in np.array_split(curved, max(1, len(curved) // 50_000)):  # lists of a batch at a time
        if not len(batch):
            continue
        base = pt_off[batch[0]]
        blat, blon = plat[base:pt_off[batch[-1] + 1]].tolist(), plon[base:pt_off[batch[-1] + 1]].tolist()
        for k in batch.tolist():
            a, b = pt_off[k] - base, pt_off[k + 1] - base
            for i in simplify_indices(blat[a:b], blon[a:b], simplify_tolerance_m)[1:-1]:
                keep[base + a + i] = True
    kept = np.flatnonzero(keep)
    seg_geom_start = np.searchsorted(kept, pt_off)
    geom_lat7, geom_lon7 = network.lat7[refs[pos[kept]]], network.lon7[refs[pos[kept]]]

    # Directed edges: forward unless the way is one-way against its drawing, backward unless one-way along it.
    oneway = network.oneway[seg_way]
    fwd, bwd = np.flatnonzero(oneway >= 0), np.flatnonzero(oneway <= 0)
    segment = np.concatenate([fwd, bwd])
    reversed_ = np.concatenate([np.zeros(len(fwd), bool), np.ones(len(bwd), bool)])
    source = np.where(reversed_, seg_b[segment], seg_a[segment])
    order = np.lexsort((segment, source))
    segment, reversed_, source = segment[order], reversed_[order], source[order]
    target = np.where(reversed_, seg_a[segment], seg_b[segment])
    way = seg_way[segment]
    flags = (network.road_class[way] | np.where(network.roundabout[way], FLAG_ROUNDABOUT, 0)
             | np.where(network.link[way], FLAG_LINK, 0) | np.where(reversed_, FLAG_GEOM_REVERSED, 0)).astype(np.uint8)
    length_m = np.round(seg_length[segment]).astype(np.uint32)
    speed = network.speed[way]
    weight = np.maximum(1, np.round(length_m.astype(np.float64) * 36 / speed)).astype(np.uint32)
    first_edge = np.searchsorted(source, np.arange(len(gnodes) + 1)).astype(np.int64)

    # Sparse spatial grid: each segment is listed (through its first edge) in every cell its original geometry
    # crosses. (Listing it in every cell of its bounding box, as before, put a long diagonal road in hundreds of cells
    # it never touches: 36 % of Canada's map was the grid.)
    seg_edge = np.full(len(starts), -1, np.int64)
    segs, first = first_occurrences(segment)
    seg_edge[segs] = first
    seg_cell, cid = _cells_crossed(plat, plon, pt_off, min_lat, min_lon, cell_deg, rows, cols)
    key = unique(cid * len(starts) + seg_cell)  # sorted by cell, then by segment; each pair once
    cid, items = key // len(starts), seg_edge[key % len(starts)]
    cell_ids, cell_first = first_occurrences(cid)
    grid = Grid(float(min_lat), float(min_lon), cell_deg, cols, rows, cell_ids,
                np.append(cell_first, len(cid)), items)

    stats = {
        "osm_ways": network.way_count,
        "osm_nodes": network.node_count,
        "segments": len(starts),
        "shape_points": int((npts - 2).sum()),
        "shape_points_kept": len(kept),
        "graph_seconds": time.time() - t0,
    }
    return RoadGraph(
        lat7=network.lat7[gnodes], lon7=network.lon7[gnodes], osm_ids=network.node_ids[gnodes],
        seg_a=seg_a, seg_b=seg_b, seg_length=seg_length, seg_name=network.name_id[seg_way],
        seg_geom_start=seg_geom_start, geom_lat7=geom_lat7, geom_lon7=geom_lon7, names=network.names,
        source=source, target=target, segment=segment, length_m=length_m, weight=weight, speed=speed, flags=flags,
        first_edge=first_edge, bounds=(float(min_lat), float(min_lon), float(max_lat), float(max_lon)),
        grid=grid, seg_way=seg_way, stats=stats,
    )
