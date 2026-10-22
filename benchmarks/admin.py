#!/usr/bin/env python3
"""Graph size per administrative area (departments, states, provinces) of a country map.

    python benchmarks/admin.py colombia            # admin_level 4 of data/countries/colombia.osm.pbf

Reads the boundaries (boundary=administrative, admin_level=4 by default) from the same extract the map was built
from, counts the graph nodes and edges inside each one and estimates the size of a map of just that area (at
the country's bytes per node). Writes benchmarks/results/admin-<name>.json; run.py renders the table.
Needs shapely (pip install shapely).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import osmium
import shapely
from shapely import wkb

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run import DATA, REGIONS, RESULTS  # noqa: E402

from roadpack.format import Gmap  # noqa: E402


def boundaries(pbf, admin_level):
    """{name: shapely geometry} of the administrative areas of that level."""
    factory = osmium.geom.WKBFactory()
    areas = {}
    processor = osmium.FileProcessor(str(pbf)).with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
    for obj in processor:
        if not obj.is_area() or obj.tags.get("admin_level") != str(admin_level):
            continue
        name = obj.tags.get("name") or obj.tags.get("name:en") or f"#{obj.orig_id()}"
        try:
            geom = wkb.loads(factory.create_multipolygon(obj), hex=True)
        except RuntimeError:
            continue  # broken ring in OSM
        areas[name] = shapely.union(areas[name], geom) if name in areas else geom
    return areas


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("region", help="a country of benchmarks/run.py whose map is already built")
    parser.add_argument("--admin-level", type=int, default=4)
    args = parser.parse_args()
    name, label, _, extract = next(r for r in REGIONS if r[0] == args.region)

    g = Gmap(DATA / "out" / f"{name}.gmap")
    lat, lon = np.asarray(g.lat)[:-1], np.asarray(g.lon)[:-1]
    source = np.asarray(g.source)
    bytes_per_node = len(g.data) / g.node_count
    areas = boundaries(DATA / f"{extract}.osm.pbf", args.admin_level)
    print(f"{len(areas)} areas of admin_level {args.admin_level}")

    rows, assigned = [], np.zeros(g.node_count, bool)
    for area, geom in sorted(areas.items()):
        shapely.prepare(geom)
        inside = shapely.contains_xy(geom, lon, lat)
        assigned |= inside
        nodes = int(inside.sum())
        rows.append({"name": area, "nodes": nodes, "edges": int(inside[source].sum()),
                     "estimated_mb": nodes * bytes_per_node / 1e6})
    rows = sorted((r for r in rows if r["nodes"]), key=lambda r: -r["nodes"])  # OSM has some mistagged areas
    result = {"region": name, "label": label, "admin_level": args.admin_level, "areas": rows,
              "nodes_outside": int((~assigned).sum()), "bytes_per_node": bytes_per_node}
    (RESULTS / f"admin-{name}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for r in rows:
        print(f"  {r['name']:<40} {r['nodes']:>10,} nodes  ~{r['estimated_mb']:,.1f} MB")


if __name__ == "__main__":
    main()
