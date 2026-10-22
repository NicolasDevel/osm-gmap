"""Command line: roadpack build | info | route."""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from . import __version__
from .format.spec import ROAD_CLASSES

def _mb(n):
    return f"{n / 1048576:,.1f} MB"


def _point(text):
    try:
        lat, lon = (float(v) for v in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("expected lat,lon") from None
    return lat, lon


def _bbox(text):
    from .regions import parse_bbox
    try:
        return parse_bbox(text)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _print_sections(sections, total):
    for name, size in sections.items():
        print(f"    {name:<12} {_mb(size):>10}  {size / total:6.1%}")


COORDINATE_OPTIONS = ("--bbox", "--from", "--to")
WHOLE_WORLD = (-90.0, -180.0, 90.0, 180.0)


def _join_coordinate_values(argv):
    """argparse takes "-12.1,-77.0" for an option: glue coordinates to their flag (--from=-12.1,-77.0)."""
    out, i = [], 0
    while i < len(argv):
        if argv[i] in COORDINATE_OPTIONS and i + 1 < len(argv):
            out.append(f"{argv[i]}={argv[i + 1]}")
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def cmd_build(args):
    from .osm import PROFILES
    from .pipeline import build
    from .regions import REGIONS

    bbox = args.bbox or (REGIONS[args.region] if args.region else WHOLE_WORLD)
    chunk_dir = None if args.no_chunks else (args.chunk_dir or args.output.with_suffix(""))
    stats = build(args.pbf, bbox, PROFILES[args.profile], args.output, chunk_dir)

    s = stats["sections"]
    print(f"\nWrote {args.output} ({_mb(s['total'])}) in {stats['total_seconds']:.0f} s")
    print(f"  OSM:   {stats['osm_ways']:,} drivable ways, {stats['osm_nodes']:,} nodes")
    print(f"  graph: {stats['nodes']:,} nodes ({stats['nodes'] / stats['osm_nodes']:.0%} of the OSM nodes), "
          f"{stats['edges']:,} directed edges")
    print(f"  shape: {stats['shape_points_kept']:,} of {stats['shape_points']:,} points between nodes kept")
    print("  sections:")
    _print_sections({k: s[k] for k in ("nodes", "edges", "grid", "geometry", "names", "ch_forward", "ch_backward")},
                    s["total"])
    if chunk_dir is not None:
        print(f"  SD card: {chunk_dir}/ ({stats['chunks']} chunks) -> copy it to /maps/{chunk_dir.name}/")
    if args.stats_json:
        args.stats_json.write_text(json.dumps(stats, indent=2) + "\n")


def cmd_info(args):
    from .format import Gmap

    g = Gmap(args.gmap)
    sections = g.section_sizes()
    total = len(g.data)
    classes = Counter(f & 0x0F for f in g.flags)
    km = sum(g.length) / 1000
    if args.json:
        print(json.dumps({
            "nodes": g.node_count, "edges": g.edge_count,
            "bounds": [g.min_lat, g.min_lon, g.max_lat, g.max_lon],
            "grid": {"cell_deg": g.cell, "cols": g.cols, "rows": g.rows, "non_empty": len(g.cell_ids)},
            "ch_arcs": {"forward": g.ch_fwd.arc_count, "backward": g.ch_bwd.arc_count},
            "directed_km": km, "sections": sections, "size": total,
            "edges_by_class": {ROAD_CLASSES[c]: n for c, n in sorted(classes.items())},
        }, indent=2))
        return
    print(f"{args.gmap}: .gmap v2, {_mb(total)}")
    print(f"  {g.node_count:,} nodes, {g.edge_count:,} directed edges ({km:,.0f} km), "
          f"{total / g.node_count:.0f} bytes per node in total")
    print(f"  bounds: {g.min_lat:.4f},{g.min_lon:.4f} – {g.max_lat:.4f},{g.max_lon:.4f}")
    print(f"  grid: {g.cols} × {g.rows} cells of {g.cell:g}°, {len(g.cell_ids):,} non-empty")
    print(f"  contraction hierarchy: {g.ch_fwd.arc_count:,} forward + {g.ch_bwd.arc_count:,} backward arcs")
    print("  sections:")
    _print_sections({k: v for k, v in sections.items() if k != "header"}, total)
    print("  edges by road class:")
    for c, n in sorted(classes.items()):
        print(f"    {ROAD_CLASSES[c]:<12} {n:>10,}  {n / g.edge_count:6.1%}")


def cmd_stats(args):
    from .format import Gmap
    from .stats import sample_routes

    g = Gmap(args.gmap)
    r = sample_routes(g, args.routes, args.seed, args.check)
    if args.json:
        print(json.dumps(r, indent=2))
        return
    print(f"{args.gmap}: {g.node_count:,} nodes, {_mb(len(g.data))}")
    print(f"  {r['routes']} random routes ({r['unreachable']} pairs without a route)")
    rows = [("route length (km)", "route_km", "{:,.1f}"), ("nodes settled", "settled_nodes", "{:,}"),
            ("KB read by the query", "query_kb_read", "{:,.0f}"), ("KB read incl. geometry", "route_kb_read", "{:,.0f}"),
            ("Python time (ms)", "python_ms", "{:,.1f}")]
    print(f"    {'':<24}{'median':>10}{'p95':>10}{'max':>10}")
    for label, key, fmt in rows:
        v = r[key]
        cells = "".join(f"{fmt.format(v[q]):>10}" if v[q] is not None else f"{'-':>10}" for q in ("median", "p95", "max"))
        print(f"    {label:<24}{cells}")
    print(f"  pages of {r['page_size']} bytes; what a device reads with an empty cache")
    if r["astar_checked"]:
        verdict = "all the same cost" if not r["astar_mismatches"] else f"{r['astar_mismatches']} MISMATCHES"
        print(f"  A* on the full graph: {r['astar_checked']} routes, {verdict}, "
              f"{r['astar_settled_mean']:,.0f} nodes settled on average")
    if r["astar_mismatches"]:
        sys.exit(1)


def cmd_route(args):
    from .format import Gmap
    from .preview import format_distance
    from .routing import maneuvers, route_astar, route_ch

    g = Gmap(args.gmap)
    start, goal = g.nearest_node(*args.origin), g.nearest_node(*args.dest)
    stats = {}
    t = time.perf_counter()
    path, cost = route_ch(g, start, goal, stats)
    elapsed = time.perf_counter() - t
    if path is None:
        sys.exit("No route between those points.")
    if not path:
        sys.exit("Both points snap to the same node.")
    ms = maneuvers(g, path)

    total_m = sum(g.length[e] for e in path)
    print(f"Route: {format_distance(total_m)}, ~{cost / 600:.0f} min, {len(path)} edges, {len(ms)} maneuvers")
    print(f"  contraction hierarchy settled {stats['settled']:,} nodes in {elapsed * 1000:.0f} ms (Python)")
    if args.check:
        astar = {}
        t = time.perf_counter()
        _, ref_cost = route_astar(g, start, goal, astar)
        elapsed = time.perf_counter() - t
        verdict = "same cost" if ref_cost == cost else f"MISMATCH: {ref_cost} vs {cost}"
        print(f"  A* on the full graph settled {astar['settled']:,} nodes in {elapsed * 1000:.0f} ms: {verdict}")
    print()
    for prev, m in zip([None, *ms], ms):
        gap = m.at_m - prev.at_m if prev else 0
        print(f"  {m.at_m / 1000:6.2f} km  (+{format_distance(gap):>7})  {m.text()}")

    if args.images:
        from .preview import render
        count = render(g, path, ms, args.images)
        print(f"\n{count} images in {args.images}/")
    if args.check and ref_cost != cost:
        sys.exit(1)


def main(argv=None):
    from .osm import PROFILES
    from .regions import REGIONS

    parser = argparse.ArgumentParser(
        prog="roadpack",
        description="Compact OpenStreetMap road graphs for microcontrollers: build, inspect and test .gmap files.")
    parser.add_argument("--version", action="version", version=f"roadpack {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    b = sub.add_parser("build", help="OSM extract -> .gmap (and SD card chunks)",
                       description="Build a .gmap from an OpenStreetMap extract (.osm.pbf), e.g. from Geofabrik.")
    b.add_argument("pbf", type=Path, help="OpenStreetMap extract (.osm.pbf)")
    b.add_argument("-o", "--output", required=True, type=Path, help="output .gmap file")
    area = b.add_mutually_exclusive_group()
    area.add_argument("--bbox", type=_bbox, metavar="MINLAT,MINLON,MAXLAT,MAXLON",
                      help="keep the roads that touch this rectangle (default: the whole extract)")
    area.add_argument("--region", choices=sorted(REGIONS), help="predefined bounding box")
    b.add_argument("--profile", choices=sorted(PROFILES), default="motorcycle",
                   help="vehicle whose access and oneway rules apply (default: motorcycle)")
    b.add_argument("--chunk-dir", type=Path, help="where to write the SD card chunks (default: output without .gmap)")
    b.add_argument("--no-chunks", action="store_true", help="do not split the file into SD card chunks")
    b.add_argument("--stats-json", type=Path, metavar="FILE", help="also write the build statistics as JSON")
    b.set_defaults(func=cmd_build)

    i = sub.add_parser("info", help="what is inside a .gmap", description="Counts, bounds and section sizes.")
    i.add_argument("gmap", type=Path, help=".gmap file or directory of SD card chunks")
    i.add_argument("--json", action="store_true", help="machine-readable output")
    i.set_defaults(func=cmd_info)

    st = sub.add_parser("stats", help="cost of random routes: nodes settled and KB read",
                        description="Route between random pairs of nodes like a device would and report how many "
                                    "nodes the contraction hierarchy settles and how much of the file it reads.")
    st.add_argument("gmap", type=Path, help=".gmap file or directory of SD card chunks")
    st.add_argument("--routes", type=int, default=100, help="random node pairs (default: 100)")
    st.add_argument("--seed", type=int, default=1)
    st.add_argument("--check", type=int, default=0, metavar="N", help="also run A* on the first N routes")
    st.add_argument("--json", action="store_true", help="machine-readable output")
    st.set_defaults(func=cmd_stats)

    r = sub.add_parser("route", help="route between two points and print the maneuvers",
                       description="Route with the contraction hierarchy, like a device would.")
    r.add_argument("gmap", type=Path, help=".gmap file or directory of SD card chunks")
    r.add_argument("--from", dest="origin", required=True, type=_point, metavar="LAT,LON")
    r.add_argument("--to", dest="dest", required=True, type=_point, metavar="LAT,LON")
    r.add_argument("--check", action="store_true", help="also run A* on the full graph and compare the cost")
    r.add_argument("--images", type=Path, metavar="DIR", help="render the route and each maneuver screen as PNG")
    r.set_defaults(func=cmd_route)

    args = parser.parse_args(_join_coordinate_values(sys.argv[1:] if argv is None else argv))
    try:
        args.func(args)
    except (OSError, ValueError, RuntimeError) as e:
        sys.exit(f"roadpack: {e}")


if __name__ == "__main__":
    main()
