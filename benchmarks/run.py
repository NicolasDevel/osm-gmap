#!/usr/bin/env python3
"""Builds every region of REGIONS, measures it and writes benchmarks/results/<name>.json and the tables in
benchmarks/README.md.

    python benchmarks/run.py                 # regions without results yet
    python benchmarks/run.py --only bogota   # one region (rebuilds it)
    python benchmarks/run.py --tables        # only re-render the tables

Extracts are expected in data/ (benchmarks/download.sh fetches them): city extracts from BBBike, countries and US states
from Geofabrik. Each build runs in its own process so its time and peak memory are measured alone.
"""
import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RESULTS = Path(__file__).resolve().parent / "results"
README = Path(__file__).resolve().parent / "README.md"
SCALING = ROOT / "docs" / "SCALING.md"

# name, label, group, extract
REGIONS = [
    ("bogota", "Bogotá", "city", "cities/Bogota"),
    ("mexico-city", "Mexico City", "city", "cities/MexicoCity"),
    ("lima", "Lima", "city", "cities/Lima"),
    ("buenos-aires", "Buenos Aires", "city", "cities/BuenosAires"),
    ("santiago", "Santiago", "city", "cities/Santiago"),
    ("washington-dc", "Washington DC", "city", "cities/WashingtonDC"),
    ("ottawa", "Ottawa", "city", "cities/Ottawa"),
    ("toronto", "Toronto", "city", "cities/Toronto"),
    ("new-york", "New York", "city", "cities/NewYork"),
    ("madrid", "Madrid", "city", "cities/Madrid"),
    ("barcelona", "Barcelona", "city", "cities/Barcelona"),
    ("paris", "Paris", "city", "cities/Paris"),
    ("london", "London", "city", "cities/London"),
    ("berlin", "Berlin", "city", "cities/Berlin"),
    ("tokyo", "Tokyo", "city", "cities/Tokyo"),
    ("colombia", "Colombia", "country", "countries/colombia"),
    ("spain", "Spain", "country", "countries/spain"),
    ("brazil", "Brazil", "country", "countries/brazil"),
    ("canada", "Canada", "country", "countries/canada"),
    ("california", "California", "US state", "countries/california"),
    ("texas", "Texas", "US state", "countries/texas"),
    ("new-york-state", "New York State", "US state", "countries/new-york"),
]
ROUTES = 200
CHECK = 5


def extract_date(pbf):
    import osmium
    header = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING).header()
    return (header.get("osmosis_replication_timestamp") or "")[:10]


def run_measured(cmd):
    """Run a command; return (stdout, wall seconds, peak RSS in bytes) of that process alone."""
    t = time.time()
    proc = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, text=True)
    out = proc.stdout.read()
    _, status, usage = os.wait4(proc.pid, 0)
    proc.returncode = os.waitstatus_to_exitcode(status)
    if proc.returncode:
        raise RuntimeError(f"{' '.join(map(str, cmd))} failed ({proc.returncode})")
    rss = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    return out, time.time() - t, rss


def measure(name, label, group, extract):
    pbf = DATA / f"{extract}.osm.pbf"
    out = DATA / "out" / f"{name}.gmap"
    stats_file = DATA / "out" / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"== {label}: building from {pbf.name} ({pbf.stat().st_size / 1e6:,.0f} MB)", flush=True)
    _, build_s, build_rss = run_measured([sys.executable, "-m", "roadpack", "build", pbf, "-o", out, "--no-chunks",
                                          "--stats-json", stats_file])
    build = json.loads(stats_file.read_text())
    print(f"   built in {build_s:.0f} s, {build_rss / 2**30:.1f} GiB peak; sampling {ROUTES} routes", flush=True)
    routes_json, _, stats_rss = run_measured([sys.executable, "-m", "roadpack", "stats", out, "--routes", ROUTES,
                                              "--check", CHECK, "--json"])
    routes = json.loads(routes_json)
    info = json.loads(run_measured([sys.executable, "-m", "roadpack", "info", out, "--json"])[0])
    return {
        "name": name, "label": label, "group": group,
        "extract": {"file": pbf.name, "bytes": pbf.stat().st_size, "date": extract_date(pbf)},
        "build": {"seconds": build_s, "peak_rss": build_rss, **build},
        "map": info,
        "routes": {**routes, "reader_peak_rss": stats_rss},
        "machine": f"{platform.machine()} {platform.system()}, {os.cpu_count()} cores",
        "measured": datetime.date.today().isoformat(),
    }


def _mb(b):
    return f"{b / 1e6:,.0f}" if b >= 10e6 else f"{b / 1e6:,.1f}"


def render_tables(results):
    order = {name: i for i, (name, *_) in enumerate(REGIONS)}
    results = sorted((r for r in results if "build" in r), key=lambda r: order.get(r["name"], 99))
    lines = ["| Region | OSM extract | Road nodes in OSM | Graph nodes | Edges | `.gmap` | Bytes / node | Build | Peak RAM |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        b, m = r["build"], r["map"]
        lines.append(
            f"| {r['label']} | {_mb(r['extract']['bytes'])} MB | {b['osm_nodes']:,} | {b['nodes']:,} "
            f"({b['nodes'] / b['osm_nodes']:.0%}) | {b['edges']:,} | {_mb(m['size'])} MB | "
            f"{m['size'] / m['nodes']:.0f} | {b['seconds']:.0f} s | {b['peak_rss'] / 2**30:.1f} GB |")
    size_table = "\n".join(lines)

    lines = ["| Region | Routes | Median length | Nodes settled (median / p95 / max) | KB read, query (median / p95) "
             "| KB read with geometry (median) | A* nodes settled (mean) |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        q = r["routes"]
        astar = f"{q['astar_settled_mean']:,.0f}" if q["astar_settled_mean"] else "-"
        lines.append(
            f"| {r['label']} | {q['routes']} | {q['route_km']['median']:,.1f} km | "
            f"{q['settled_nodes']['median']:,} / {q['settled_nodes']['p95']:,} / {q['settled_nodes']['max']:,} | "
            f"{q['query_kb_read']['median']:,.0f} / {q['query_kb_read']['p95']:,.0f} | "
            f"{q['route_kb_read']['median']:,.0f} | {astar} |")
    route_table = "\n".join(lines)

    lines = ["| Region | Nodes | Edges | Grid | Geometry | Names | CH forward | CH backward | Copies |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        s, total = r["map"]["sections"], r["map"]["size"]
        cells = " | ".join(f"{s.get(k, 0) / total:.0%}" for k in ("nodes", "edges", "grid", "geometry", "names",
                                                                  "ch_forward", "ch_backward", "copies"))
        lines.append(f"| {r['label']} | {cells} |")
    section_table = "\n".join(lines)

    lines = ["| Region | Restrictions for the vehicle | Applied | Outside the network | Ambiguous | Unsupported "
             "| Junction copies | Extra edges | Extra bytes |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        b = r["build"]
        if "restrictions" not in b:
            continue
        # A copy is a node record (12 B) plus its table entry (8 B); each extra edge is a 28 B record. The
        # hierarchy grows too, but that is not separable from the rest of the CH.
        extra = b["node_copies"] * 20 + b["edge_copies"] * 28
        lines.append(f"| {r['label']} | {b['restrictions']:,} | {b['restrictions_applied']:,} | "
                     f"{b['restrictions_not_found']:,} | {b['restrictions_ambiguous']:,} | "
                     f"{b['restrictions_unsupported']:,} | {b['node_copies']:,} ({b['node_copies'] / b['nodes']:.2%}) | "
                     f"{b['edge_copies']:,} | {_mb(extra)} MB ({extra / r['map']['size']:.1%}) |")
    restriction_table = "\n".join(lines)

    admin_tables = {}
    for path in sorted(RESULTS.glob("admin-*.json")):
        a = json.loads(path.read_text())
        total = sum(x["nodes"] for x in a["areas"]) + a["nodes_outside"]
        lines = ["| Area | Graph nodes | Share | Edges | Map of just this area (est.) |", "|---|---:|---:|---:|---:|"]
        for x in a["areas"]:
            lines.append(f"| {x['name']} | {x['nodes']:,} | {x['nodes'] / total:.1%} | {x['edges']:,} | "
                         f"~{x['estimated_mb']:,.1f} MB |")
        admin_tables[f"ADMIN-{a['region']}"] = "\n".join(lines)

    validation_file = RESULTS / "validation.json"
    validation = json.loads(validation_file.read_text()) if validation_file.exists() else {}
    lines = ["| Region | Routes checked | Same cost | Pairs without a route (skipped) | Time |", "|---|---:|---:|---:|---:|"]
    for name, *_ in REGIONS:
        if name in validation:
            v = validation[name]
            same = "all" if not v["mismatches"] else f"**{v['routes'] - v['mismatches']}**"
            lines.append(f"| {v['label']} | {v['routes']} | {same} | {v['unreachable_skipped']} | {v['seconds']:.0f} s |")
    total = sum(v["routes"] for v in validation.values())
    bad = sum(v["mismatches"] for v in validation.values())
    lines.append(f"| **Total** | **{total:,}** | **{'all' if not bad else total - bad}** | | |")
    validation_table = "\n".join(lines)

    lines = ["| Region | Road nodes in OSM | Load | Graph | CH | Total | Peak RAM |", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in sorted((r for r in results if r["group"] != "city"), key=lambda r: r["build"]["osm_nodes"]):
        b = r["build"]
        lines.append(f"| {r['label']} | {b['osm_nodes'] / 1e6:,.1f} M | {b['load_seconds']:.0f} s | "
                     f"{b['graph_seconds']:.0f} s | {b['ch_seconds']:.0f} s | {b['seconds']:.0f} s | "
                     f"{b['peak_rss'] / 2**30:.1f} GB |")
    timing_table = "\n".join(lines)

    machines = sorted({r["machine"] for r in results})
    dates = sorted({r["extract"]["date"] for r in results if r["extract"]["date"]})
    tables = {"SIZE": size_table, "ROUTES": route_table, "SECTIONS": section_table,
              "RESTRICTIONS": restriction_table, "VALIDATION": validation_table,
              "TIMING": timing_table, **admin_tables,
              "META": f"Measured on {', '.join(machines)}; OSM data from {dates[0]} to {dates[-1]}." if dates else ""}
    for doc in (README, SCALING):
        text = doc.read_text()
        for tag, table in tables.items():
            start, end = f"<!-- {tag} -->", f"<!-- /{tag} -->"
            if start in text:
                before, rest = text.split(start, 1)
                text = before + start + "\n" + table + "\n" + end + rest.split(end, 1)[1]
        doc.write_text(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", help="region names to (re)build")
    parser.add_argument("--tables", action="store_true", help="only re-render the tables")
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    if not args.tables:
        for name, label, group, extract in REGIONS:
            result_file = RESULTS / f"{name}.json"
            if args.only is not None and name not in args.only:
                continue
            if args.only is None and result_file.exists():
                continue
            if not (DATA / f"{extract}.osm.pbf").exists():
                print(f"-- {label}: no extract, skipped")
                continue
            try:
                result = measure(name, label, group, extract)
            except RuntimeError as e:
                print(f"!! {label}: {e}")
                continue
            result_file.write_text(json.dumps(result, indent=2) + "\n")
    render_tables([json.loads(p.read_text()) for p in sorted(RESULTS.glob("*.json"))
                   if not p.name.startswith("admin-") and p.name != "validation.json"])


if __name__ == "__main__":
    main()
