"""What a .gmap costs a device: size per section and, over random routes, how many nodes the contraction
hierarchy settles and how much of the file a route actually reads (in SD card pages).
"""
import random
import time
from collections import Counter

from .format.reader import Gmap
from .format.spec import EDGE, GEOM_HEADER, NONE, POINT, ROAD_CLASSES
from .routing.search import route_astar, route_ch

PAGE_SIZE = 4096


def _pages(reads, page_size=PAGE_SIZE):
    pages = set()
    for off, size in reads:
        if size > 0:
            pages.update(range(off // page_size, (off + size - 1) // page_size + 1))
    return pages


def _route_reads(g: Gmap, path):
    """What a device reads to follow a route once it has its edges: edge records and their geometry."""
    reads = []
    for e in path:
        reads.append((g.edges_off + e * EDGE.size, EDGE.size))
        if g.geom[e] != NONE:
            off = g.geom_off + g.geom[e]
            count = GEOM_HEADER.unpack_from(g.data, off)[0]
            reads.append((off, GEOM_HEADER.size + count * POINT.size))
    return reads


def _percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(p / 100 * len(s)))]


def summary(g: Gmap) -> dict:
    classes = Counter(f & 0x0F for f in g.flags)
    return {
        "nodes": g.node_count,
        "edges": g.edge_count,
        "size": len(g.data),
        "sections": g.section_sizes(),
        "bytes_per_node": len(g.data) / g.node_count,
        "directed_km": sum(g.length) / 1000,
        "ch_arcs": {"forward": g.ch_fwd.arc_count, "backward": g.ch_bwd.arc_count},
        "edges_by_class": {ROAD_CLASSES[c]: n for c, n in sorted(classes.items())},
    }


def sample_routes(g: Gmap, count=100, seed=1, check=0) -> dict:
    """Route between `count` random pairs of nodes. The first `check` reachable ones are also solved with A*
    on the full graph, which must give the same cost."""
    rng = random.Random(seed)
    settled, km, ms, kb_query, kb_route, mismatches = [], [], [], [], [], 0
    unreachable = checked = astar_settled = 0
    for _ in range(count):
        start, goal = rng.randrange(g.node_count), rng.randrange(g.node_count)
        if start == goal:
            continue
        st, reads = {}, []
        t = time.perf_counter()
        path, cost = route_ch(g, start, goal, st, reads)
        elapsed = time.perf_counter() - t
        if path is None:
            unreachable += 1
            continue
        settled.append(st["settled"])
        km.append(sum(g.length[e] for e in path) / 1000)
        ms.append(elapsed * 1000)
        kb_query.append(len(_pages(reads)) * PAGE_SIZE / 1024)
        kb_route.append(len(_pages(reads + _route_reads(g, path))) * PAGE_SIZE / 1024)
        if checked < check:
            ref = {}
            _, ref_cost = route_astar(g, start, goal, ref)
            mismatches += ref_cost != cost
            astar_settled += ref["settled"]
            checked += 1
    stats = lambda v: {"median": _percentile(v, 50), "p95": _percentile(v, 95), "max": max(v) if v else None}
    return {
        "routes": len(settled),
        "unreachable": unreachable,
        "route_km": stats(km),
        "settled_nodes": stats(settled),
        "query_kb_read": stats(kb_query),
        "route_kb_read": stats(kb_route),
        "python_ms": stats(ms),
        "astar_checked": checked,
        "astar_mismatches": mismatches,
        "astar_settled_mean": astar_settled / checked if checked else None,
        "page_size": PAGE_SIZE,
    }
