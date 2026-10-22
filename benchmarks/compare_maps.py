#!/usr/bin/env python3
"""Checks that two .gmap files hold the same road graph when they are not byte-identical.

    python benchmarks/compare_maps.py reference.gmap current.gmap [--routes 200]

Two maps can differ in bytes and still be the same graph: OpenStreetMap has distinct nodes at exactly the same
coordinates, and the order of such ties among graph nodes is arbitrary (the original builder used the iteration
order of a Python set, roadpack uses the OSM id). Swapping two such nodes renumbers their edges and lets
RoutingKit pick a different, equally valid, contraction order. This script checks:

  1. nodes: the same coordinates, in the same order;
  2. edges: the same multiset of (source and target coordinates, length, weight, speed, flags, name, geometry);
  3. routes: the same cost between random pairs of nodes in both hierarchies (nodes outside ties have the same
     number in both files).
"""
import argparse
import random
import sys
from collections import Counter

import numpy as np

from roadpack.format import Gmap
from roadpack.format.spec import NONE
from roadpack.routing import route_ch


def edge_key(g, e):
    geom = g.geom[e]
    shape = tuple(g.polyline(e)[1:-1]) if geom != NONE else ()
    return (g.point(g.source[e]), g.point(g.target[e]), g.length[e], g.weight[e], g.speed[e], g.flags[e],
            g.name(e), shape)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("a")
    parser.add_argument("b")
    parser.add_argument("--routes", type=int, default=200)
    args = parser.parse_args()
    a, b = Gmap(args.a), Gmap(args.b)
    ok = True

    lat_a, lon_a = np.asarray(a.lat), np.asarray(a.lon)
    same_nodes = a.node_count == b.node_count and (lat_a == np.asarray(b.lat)).all() and \
        (lon_a == np.asarray(b.lon)).all()
    ties = np.flatnonzero((lat_a[1:-1] == lat_a[:-2]) & (lon_a[1:-1] == lon_a[:-2]))
    tied = set(ties.tolist()) | set((ties + 1).tolist())
    print(f"nodes: {a.node_count:,} vs {b.node_count:,}, same coordinates in the same order: {same_nodes}; "
          f"{len(ties)} pairs of nodes share exact coordinates")
    ok &= bool(same_nodes)

    differing = [e for e in range(a.edge_count) if e >= b.edge_count or
                 (a.source[e], a.target[e]) != (b.source[e], b.target[e])]
    if a.edge_count == b.edge_count:
        # Only the edges whose numbering differs need the full comparison; the rest are compared directly.
        skip = set(differing)
        same_rest = all(edge_key(a, e) == edge_key(b, e) for e in range(a.edge_count) if e not in skip)
        same_differing = Counter(edge_key(a, e) for e in differing) == Counter(edge_key(b, e) for e in differing)
        touch_ties_only = all(a.source[e] in tied or a.target[e] in tied for e in differing)
        print(f"edges: {a.edge_count:,}; {len(differing)} numbered differently, all touching tied nodes: "
              f"{touch_ties_only}; same edges as a multiset: {same_rest and same_differing}")
        ok &= same_rest and same_differing and touch_ties_only
    else:
        print(f"edges: {a.edge_count:,} vs {b.edge_count:,}")
        ok = False

    rng = random.Random(1)
    checked = mismatches = 0
    while checked < args.routes:
        s, t = rng.randrange(a.node_count), rng.randrange(a.node_count)
        if s in tied or t in tied:
            continue
        ca, cb = route_ch(a, s, t)[1], route_ch(b, s, t)[1]
        checked += 1
        mismatches += ca != cb
    print(f"routes: {checked} random pairs, {mismatches} with a different cost "
          f"(hierarchies byte-identical: {a.data[a.ch_fwd_off:] == b.data[b.ch_fwd_off:]})")
    ok &= mismatches == 0

    print("EQUIVALENT" if ok else "NOT EQUIVALENT")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
