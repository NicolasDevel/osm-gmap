# Building large regions

The [benchmarks](../benchmarks/README.md) include Spain, Brazil, Canada and three US states, built on a laptop
with 16 GB of RAM. The first version of the builder needed 4.7 GB for Colombia and 8.1 GB for Spain; at that
rate Brazil (78 million road nodes) would need 30 to 40 GB.
This page explains what changed, what did **not** change, and the evidence that the large maps hold the same
graphs the original builder produces, and that every route on them is exact.

**In short:** there is no special mode for large regions. Every map in the tables comes from the same command,
`roadpack build <extract> -o <file>`, with the same parameters. What changed is how the data sits in memory
while the map is built, not which data goes into the file.

## What changed

The original builder (`build_graph.py`, commit `d688ccb`) was written for clarity: one Python object per way,
a dict from OSM node id to a `(lat, lon)` tuple, lists of tuples per edge. A Python tuple of two floats with its
dict entry takes around 200 bytes, so memory grew with every node of the road network, and osmium kept a
location index of every node in the extract (buildings and rivers included) to resolve the ways.

The current builder (commit `46b10b5`) uses four techniques.

### 1. Two passes over the extract, filtered in C++

1. **Ways.** osmium reads only ways that have a `highway` tag (`KeyFilter`, in C++). Python checks each one
   against the vehicle profile and keeps its node ids in a flat `array('q')`.
2. **Nodes.** osmium reads the extract again and passes on only the nodes those ways use (`IdFilter`, also in
   C++). Their coordinates go into flat integer arrays.

This replaces the location index of every node in the file. The id filter is a bitmap over the whole range of
OSM node ids (up to ~13 billion), which costs about 1.5 GB whatever the size of the region. It is the floor
you see in the "Peak RAM" column of the benchmarks: even Bogotá peaks at 1.7 GB.

### 2. Columnar data with numpy

Ways, nodes, segments and edges are numpy arrays (structure of arrays) instead of Python objects: about 4 to
8 bytes per value instead of 30 to 60. Every step that used to loop in Python is a vectorized operation:

| Step | Implementation |
|---|---|
| Splitting ways at intersections | node use counts with `bincount`, cut positions with `flatnonzero` |
| Morton (Z-order) node order | bit interleaving on integer arrays, then `lexsort` |
| Segment lengths | haversine on all point pairs, summed per segment (see below) |
| Bounding boxes | `minimum.reduceat` / `maximum.reduceat` |
| Edges in CSR order | `lexsort` by (source node, segment) |
| Spatial grid | each segment repeated once per cell of its bounding box, then a stable sort by cell |
| Writing the file | numpy structured arrays with the exact record layout of [FORMAT.md](../FORMAT.md) |

Only Douglas-Peucker still runs in Python, one segment at a time and in batches of 50,000 segments, so it
never holds the whole map as Python floats.

Two details keep the output identical:

- **Lengths are summed exactly like Python's `sum()`.** Since Python 3.12, `sum()` of floats uses Neumaier
  compensated summation, and that is what the original builder ran on. numpy's `add.reduce` uses pairwise
  summation, which can differ in the last bit and, once in a while, change a length rounded to whole meters.
  `_sequential_sums` reproduces Neumaier's algorithm, vectorized across segments.
- **`np.unique` is not used on large arrays.** Recent numpy versions can use a hash table for it, which took
  1 GB for 10 million ids here; sorting takes about a third of that.

### 3. The contraction hierarchy did not change

It is still computed by [RoutingKit](https://github.com/RoutingKit/RoutingKit) in C++ with the same helper
(`build_ch.cpp`). The original builder cloned RoutingKit's latest commit; roadpack pins that same commit
(`54d49bb`), and the byte-identical output below confirms both produce the same hierarchy. On every build, RoutingKit's own
`check_contraction_hierarchy_for_errors` verifies the hierarchy before it is written.

### 4. A lighter reader

The Python reader that `route`, `stats` and the validation use kept every column as a Python list. It now
keeps `memoryview`s over numpy arrays: the same fast element access, at 4 to 8 bytes per value instead of
~32. With it, a country map can be loaded to sample routes (Colombia: 0.8 GB).

## What did not change

- **No sampling, no tiling, no merging.** Every region is read whole and written as one graph. No roads are
  dropped beyond the vehicle profile rules, which are the same for all regions.
- **Same parameters everywhere:** 2 m Douglas-Peucker tolerance, 0.0025° grid cells, motorcycle profile.
- **Same file format** (`.gmap` v2), the one the ESP32 firmware reads for Colombia.
- **Measured, not estimated.** Each build runs in its own process and its peak resident memory is read with
  `wait4` (`ru_maxrss`). The largest, Brazil, peaks at 8.0 GB on a 16 GB machine.

## Evidence

### Same output as the original builder

The original builder still fits in 16 GB up to about 20 million road nodes, so it can be run side by side with
the current one on real countries. `benchmarks/compare_reference.sh` checks out the original (commit
`d688ccb`) in a temporary git worktree, builds the same extract with both, measures them, and compares the
files:

| Region | Road nodes | Original builder | Current builder | Result |
|---|---:|---:|---:|---|
| Bogotá | 0.3 M | 23 s, 2.0 GB | 27 s, 2.4 GB | byte-identical |
| Colombia | 9.7 M | 79 s, 4.7 GB | 48 s, 2.8 GB | byte-identical |
| California | 14.1 M | 156 s, 7.6 GB | 79 s, 4.8 GB | byte-identical |
| Spain | 19.8 M | 211 s, 8.1 GB | 110 s, 6.4 GB | same graph, 1 pair of nodes numbered the other way |

SHA-256 of the byte-identical files: Bogotá `2f2403513a1aa83cb309e031c4ef0349fc025e51de8029d8727e49116b0eb814`,
Colombia `737a1f061de8e09382780a0fd600d444353caf452f6b743ca1939b25c3a77bfb`, California
`625e77fff7d6971b80c755c16d0c5d5b4028954e1c1f5dd45c01c7aa9f5840ff`. The Colombia file is also the map on the SD
card of the ESP32 navigator this project was made for. Peak memory varies by a few hundred MB between runs
(Spain, a second time: 7.8 GB and 6.0 GB). On a small region the current builder uses *more* memory than the
original: that is the fixed cost of the id filter.

**Spain.** OpenStreetMap has distinct nodes at exactly the same coordinates. When two of them are graph nodes,
they tie in the Morton sort, and the tie decides which one gets the lower number. The original builder broke ties
by the iteration order of a Python `set` (arbitrary); the current one breaks them by OSM id (reproducible). Spain
has one such pair (42.8175735, −2.8117227, on Erregebidea in Álava), so two node numbers are swapped, 4 edges are
renumbered, and RoutingKit, which sees a different numbering, picks a different but equally valid contraction
order. `benchmarks/compare_maps.py` checks that two such files are the same graph:

```
nodes: 3,281,603 vs 3,281,603, same coordinates in the same order: True; 1 pairs of nodes share exact coordinates
edges: 7,242,856; 4 numbered differently, all touching tied nodes: True; same edges as a multiset: True
routes: 200 random pairs, 0 with a different cost (hierarchies byte-identical: False)
EQUIVALENT
```

Every edge is compared field by field (endpoints by coordinates, length, weight, speed, flags, name, geometry).
California has 13 such pairs and still came out byte-identical: there the set order happened to follow the ids.

To reproduce:

```bash
benchmarks/compare_reference.sh colombia-latest.osm.pbf bogota       # bogota | cundinamarca | colombia
benchmarks/compare_reference.sh california-latest.osm.pbf all        # a whole extract
```

Brazil was not compared: the original builder would need 30 to 40 GB. Neither was Canada: it has fewer road
nodes than Spain, but the original builder keeps a location index for every node of the 6.5 GB extract. Both go
through exactly the same code as the four regions above.

### Tests against the reference algorithms

The test suite (`pytest`, also run by GitHub Actions on Linux and macOS) checks the vectorized code against
the original pure-Python algorithms:

- `split_into_segments` against the original splitting loop on 200 random sets of ways, including loops,
  self-intersections and repeated nodes;
- `_sequential_sums` against Neumaier summation written out in Python;
- a hand-made town covering every OSM rule (one-ways per vehicle, access tags, roundabouts, loops, roads
  crossing the bounding box), checked node by node and edge by edge.

### Routes: contraction hierarchy against A*

On every map, random routes are solved twice: with the contraction hierarchy (what a device runs) and with A*
over every edge of the graph, which does not use the hierarchy at all. The costs must be identical, and the
route unpacked from the hierarchy's shortcuts must add up to that cost edge by edge.
`benchmarks/validate.py`, with a different seed from the benchmark routes:

<!-- VALIDATION -->
| Region | Routes checked | Same cost | Pairs without a route (skipped) | Time |
|---|---:|---:|---:|---:|
| Bogotá | 100 | all | 0 | 3 s |
| Mexico City | 100 | all | 1 | 5 s |
| Lima | 100 | all | 3 | 6 s |
| Buenos Aires | 100 | all | 1 | 6 s |
| Santiago | 100 | all | 4 | 5 s |
| Washington DC | 100 | all | 15 | 3 s |
| Ottawa | 100 | all | 5 | 1 s |
| Toronto | 100 | all | 2 | 3 s |
| New York | 100 | all | 8 | 7 s |
| Madrid | 100 | all | 14 | 3 s |
| Barcelona | 100 | all | 6 | 2 s |
| Paris | 100 | all | 10 | 7 s |
| London | 100 | all | 8 | 12 s |
| Berlin | 100 | all | 6 | 6 s |
| Tokyo | 100 | all | 3 | 9 s |
| Colombia | 100 | all | 4 | 43 s |
| Spain | 100 | all | 10 | 67 s |
| Brazil | 100 | all | 1 | 410 s |
| Canada | 100 | all | 11 | 97 s |
| California | 100 | all | 10 | 99 s |
| Texas | 100 | all | 8 | 81 s |
| New York State | 100 | all | 7 | 35 s |
| **Total** | **2,200** | **all** | | |
<!-- /VALIDATION -->

Pairs without a route (islands, one-way dead ends at the edge of an extract) are skipped: confirming them
with A* would mean exploring the whole connected component in Python.

### Where the time goes

For the largest regions (from the benchmark results):

<!-- TIMING -->
| Region | Road nodes in OSM | Load | Graph | CH | Total | Peak RAM |
|---|---:|---:|---:|---:|---:|---:|
| New York State | 6.6 M | 21 s | 5 s | 8 s | 36 s | 2.5 GB |
| Colombia | 9.7 M | 27 s | 9 s | 21 s | 59 s | 3.1 GB |
| California | 14.1 M | 50 s | 13 s | 19 s | 85 s | 4.8 GB |
| Texas | 15.8 M | 52 s | 15 s | 26 s | 97 s | 6.0 GB |
| Canada | 18.1 M | 72 s | 18 s | 19 s | 112 s | 6.8 GB |
| Spain | 19.8 M | 70 s | 18 s | 40 s | 133 s | 5.4 GB |
| Brazil | 78.3 M | 218 s | 90 s | 118 s | 443 s | 7.4 GB |
<!-- /TIMING -->

"Load" is the two passes over the extract; Brazil has 78 million road nodes, which Python still touches one
by one in the node pass. "Graph" is the numpy work plus Douglas-Peucker; "CH" is RoutingKit.

## Limits

- **Format:** `.gmap` v2 uses 32-bit offsets and a 16-bit grid, so a map must stay under 4 GiB and about 164°
  of longitude. Brazil is 2.5 GB. The whole United States would be about 8 GB and crosses the 180th
  meridian (Alaska), so it is built per state. The writer refuses maps beyond these limits instead of
  producing a corrupt file.
- **Memory:** the fixed ~1.5 GB of the id filter, plus what grows with the road network: 2.8 GB in total for
  Colombia, 5.0 GB for Spain, 6.2 GB for Canada, 8.0 GB for Brazil (78 million road nodes). The whole United
  States would not fit in 16 GB.
- **Spatial grid:** each segment is listed in every cell of its bounding box, which inflates the grid where
  roads are long (36 % of the Canada map). Listing only the cells a segment actually crosses would shrink it
  without changing the format.
