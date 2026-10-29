# The `.gmap` v3 format

The road graph of a region, designed to be read from a microSD card with `seek` + `read`: no text parsing and
**no need to load it in memory**. A device reads it in pages through a small cache. It carries a precomputed
**contraction hierarchy (CH)** so long routes settle only a few hundred nodes.

Everything is **little-endian** (like the ESP32 and most ARM MCUs). Coordinates are integers in degrees × 10⁷
(≈ 1.1 cm). `0xFFFFFFFF` means "none" in 32-bit references.

```
┌────────┬────────────┬──────────┬──────────────┬──────────┬───────┬────────────┬─────────────┬──────────┐
│ header │ nodes      │ edges    │ spatial grid │ geometry │ names │ CH forward │ CH backward │ copies   │
│ 80 B   │ 12 B × N+1 │ 28 B × E │ sparse       │ variable │ UTF-8 │            │             │ 8 B × K  │
└────────┴────────────┴──────────┴──────────────┴──────────┴───────┴────────────┴─────────────┴──────────┘
```

**v3** adds OSM turn restrictions as junction copies (see [Turn restrictions](#turn-restrictions)): two header
fields at the end and a table at the end of the file. Everything else is where v2 had it, so a v3 reader also
reads v2 files (version 2, 72-byte header, no copies).

Nodes are sorted along a **Z-order (Morton) curve** of their spatial grid cell: what is close on the map, in
any direction, is close in the file. Edges, geometry and the CH follow the same order, so a device's page
cache almost always hits.

## On the SD card

The file is stored **split into 4 MiB chunks** inside a directory: `/maps/<region>/0000.bin`, `0001.bin`, …
(`roadpack build` writes them next to the `.gmap`). To the device they are one continuous file.

Why: the Arduino ESP32 core ships FAT without *fast seek*, and seeking backwards inside a file of hundreds of
MB walks the whole cluster chain (measured: ~12 ms per read). With 4 MiB chunks the seeks are short and few
files are opened (each open costs ~17 ms on the device).

## Header (80 bytes)

| Offset | Type | Field | Notes |
|---:|---|---|---|
| 0 | char[4] | magic | `GMAP` |
| 4 | u16 | version | `3` |
| 6 | u16 | header_size | `80` |
| 8 | u32 | node_count | N |
| 12 | u32 | edge_count | E |
| 16 | i32 ×4 | min_lat, min_lon, max_lat, max_lon | extent of the network; (min_lat, min_lon) is the grid origin |
| 32 | u32 | cell_size | side of a grid cell, in degrees × 10⁷ |
| 36 | u16 | grid_cols | |
| 38 | u16 | grid_rows | |
| 40 | u32 | nodes_off | absolute offset of each section |
| 44 | u32 | edges_off | |
| 48 | u32 | grid_off | |
| 52 | u32 | geom_off | |
| 56 | u32 | names_off | |
| 60 | u32 | ch_fwd_off | 4-byte aligned |
| 64 | u32 | ch_bwd_off | |
| 68 | u32 | file_size | to check the file is complete |
| 72 | u32 | copies_off | junction copies (v3; in v2 there are none) |
| 76 | u32 | copy_count | K |

## Nodes (12 bytes, N + 1 records)

Each node is an **intersection or the end of a way**, or a **copy** of an intersection (turn restrictions); the
points along a street are not nodes.

| Offset | Type | Field |
|---:|---|---|
| 0 | i32 | lat |
| 4 | i32 | lon |
| 8 | u32 | first_edge |

The edges leaving node `n` are `[first_edge(n), first_edge(n+1))` (CSR layout). Record `N` is a **sentinel**
with `first_edge = E`.

## Edges (28 bytes, E records)

**Directed** edges: a two-way road has two (one per direction), a one-way road has one.

| Offset | Type | Field | Notes |
|---:|---|---|---|
| 0 | u32 | source | source node |
| 4 | u32 | target | target node |
| 8 | u32 | geom | offset relative to `geom_off`, or `0xFFFFFFFF` if the segment is straight |
| 12 | u32 | name | offset relative to `names_off`, or `0xFFFFFFFF` |
| 16 | u32 | length_m | real length of the segment in meters |
| 20 | u32 | weight_ds | travel time in tenths of a second (`length_m × 36 / speed_kmh`, at least 1): the routing weight |
| 24 | u8 | speed_kmh | OSM `maxspeed`, or the default of the road class |
| 25 | u8 | flags | see below |
| 26 | u16 | (padding) | 0 |

**flags**

| Bits | Meaning |
|---|---|
| 0-3 | class: 0 motorway, 1 trunk, 2 primary, 3 secondary, 4 tertiary, 5 unclassified, 6 residential, 7 service/living_street |
| 4 | `GEOM_REVERSED`: the stored geometry runs from target to source; walk it backwards |
| 5 | `ROUNDABOUT`: the edge is part of a roundabout |
| 6 | `LINK`: ramp or link road (`*_link`) |

## Spatial grid (sparse)

A grid of `grid_cols × grid_rows` cells over the extent of the network; only cells with roads are stored (for a
country, the full grid would take hundreds of MB). The cell of a point is
`row = (lat - min_lat) / cell_size`, `col = (lon - min_lon) / cell_size`, `id = row * grid_cols + col`.

| Type | Field |
|---|---|
| u32 | K: number of non-empty cells |
| u32 × K | cell ids, **sorted** (binary search) |
| u32 × (K+1) | start of each cell in the edge list |
| u32 × … | edges: those of cell `k` go from `start[k]` to `start[k+1]` |

Each segment appears once per cell it touches (with only one of its two directions). It is used to snap a GPS
position to the nearest road and to find the streets around a junction.

## Geometry

Only the **interior points** of a segment (without the end nodes), simplified with Douglas-Peucker at 2 m.
Both directions of a road share the same geometry.

| Type | Field |
|---|---|
| u16 | count |
| u16 | (padding, 0) |
| (i32 lat, i32 lon) × count | points |

Full polyline of an edge = `[source, ...points (reversed if GEOM_REVERSED), target]`.

## Names

UTF-8 strings terminated by `\0`, without repeats. OSM `name`, or `ref` when the way has no name.

## Contraction hierarchy

Computed with [RoutingKit](https://github.com/RoutingKit/RoutingKit) on the `weight_ds` weights. Every node
has a rank; the CH adds **shortcuts** so that every optimal route can be built going up in rank from the start
and down to the goal.

Both sides (forward and backward) share the same structure, **indexed by node number** (not by rank, so the
CH keeps the Morton locality of the nodes):

| Type | Field |
|---|---|
| u32 | A: number of arcs |
| u32 × (N+1) | first_out: arcs of node `n` go from `first_out[n]` to `first_out[n+1]` |
| 16 B × A | arcs |

| Offset | Type | Field | Notes |
|---:|---|---|---|
| 0 | u32 | other | forward: the **higher-ranked** node the arc leads to. Backward: the higher-ranked node it comes from (in the real direction of the road, `other → n`) |
| 4 | u32 | weight_ds | |
| 8 | u32 | a | if bit 31 is set: original arc, `a & 0x7FFFFFFF` is the edge id. Otherwise: first half of the shortcut (a **backward** arc) |
| 12 | u32 | b | shortcut: second half (a **forward** arc). Original arc: 0 |

**Query** (see `route_ch` in `src/roadpack/routing/search.py`):
1. Dijkstra from the start over the forward arcs and, interleaved, from the goal over the backward arcs. Each
   side stops when its smallest pending distance can no longer improve the best route found.
2. The route goes through the meeting node with the smallest sum of distances.
3. Each arc is unpacked recursively: shortcut = backward(`a`) followed by forward(`b`), down to the original
   edges.

In Bogotá and Cundinamarca a query settles about **240 nodes per route** (at most ~400), against thousands for
A* on the full graph, with exactly the same cost.

## Turn restrictions

OSM turn restrictions (`type=restriction` relations with a via node or via ways: `no_left_turn`,
`only_straight_on`, `no_u_turn`, …) are applied by **splitting junctions**, so the graph stays node-based and the hierarchy and its
query do not change:

- At a junction with restrictions, an edge arriving along a restricted way is redirected to a **copy** of the
  junction: same coordinates, and only the exits allowed from that way (copies of the original edges, with their
  own records in the edge table). Arrivals with the same restrictions share a copy; other arrivals keep going to
  the junction itself, which keeps every exit.
- A restriction with **via ways** (usually the short segment across a median: no U-turn onto the other
  carriageway) becomes a chain of copies: the arrival along the from way leads to a copy of the first junction,
  whose exit along the via way leads to a copy of the next one, and so on; the last copy lacks the forbidden exits.
  Inside the via ways no copy has the exit that turns back along them (otherwise a route could cross the median,
  turn around in the gap and cross again, no longer arriving along the from way). In general the copies are the
  states of an automaton over the edges driven, so restrictions that share junctions combine; a reader needs nothing
  of this: a copy is just a node with its own exits.
- Copies come **right after their original** in node order (same page of the SD card), and their edges right after
  the original's. The spatial grid lists only original edges.

The copies table lists each copy and its original, sorted by copy:

| Offset | Type | Field |
|---:|---|---|
| 0 | u32 | copy |
| 4 | u32 | original |

What a reader has to do with copies:

- **Goal:** a route may arrive at the goal junction through any of its copies (arriving along a restricted way is
  allowed: no turn is made). The backward search starts at the goal and at its copies (those are the nodes right
  after the goal whose original is the goal).
- **Maneuvers:** the streets of a junction are the exits of the **original**; a forbidden exit is still a street
  the rider sees. Compare junctions by their original.
- **Snapping a position to a node:** use the original.

Not supported (left out when building, and counted): restrictions with several from/to members, or a node and ways
mixed as via, and time-dependent ones (`restriction:conditional`). If a from or to way goes through the via node
instead of ending there, which side is meant is ambiguous, and the restriction is skipped; so are via ways that do
not make a single path of edges from the end of the from way to the to way. `except=*` and
`restriction:<vehicle>` follow the vehicle profile.
