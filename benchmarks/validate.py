#!/usr/bin/env python3
"""Checks the contraction hierarchy of every built benchmark map against A* on the full graph.

    python benchmarks/validate.py              # 100 random routes per region
    python benchmarks/validate.py --only brazil --routes 20

Each route is solved twice, with the hierarchy (what a device runs) and with A* over every edge of the graph,
and the costs must be identical. Writes benchmarks/results/validation.json; run.py renders the table.
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import DATA, REGIONS, RESULTS  # noqa: E402

from roadpack.format import Gmap  # noqa: E402
from roadpack.routing import route_astar, route_ch  # noqa: E402


def validate(gmap, routes, seed):
    rng = random.Random(seed)
    checked = mismatches = unreachable = 0
    t = time.time()
    while checked < routes:
        start, goal = rng.randrange(gmap.node_count), rng.randrange(gmap.node_count)
        path, cost = route_ch(gmap, start, goal)
        if path is None:
            unreachable += 1  # not confirmed with A*: it would explore the whole component
            continue
        ref_path, ref_cost = route_astar(gmap, start, goal)
        checked += 1
        if ref_cost != cost or sum(gmap.weight[e] for e in path) != cost:
            mismatches += 1
            print(f"   MISMATCH {start} -> {goal}: CH {cost}, A* {ref_cost}", flush=True)
    return {"routes": checked, "mismatches": mismatches, "unreachable_skipped": unreachable, "seed": seed,
            "seconds": time.time() - t}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--routes", type=int, default=100)
    parser.add_argument("--seed", type=int, default=2)  # not the seed of run.py: other routes
    args = parser.parse_args()
    out_file = RESULTS / "validation.json"
    results = json.loads(out_file.read_text()) if out_file.exists() else {}
    for name, label, _, _ in REGIONS:
        path = DATA / "out" / f"{name}.gmap"
        if (args.only is not None and name not in args.only) or not path.exists():
            continue
        print(f"== {label}: {args.routes} routes", flush=True)
        results[name] = {"label": label, **validate(Gmap(path), args.routes, args.seed)}
        print(f"   {results[name]['mismatches']} mismatches in {results[name]['seconds']:.0f} s", flush=True)
        out_file.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
