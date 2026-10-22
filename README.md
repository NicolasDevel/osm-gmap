# roadpack

Compact OpenStreetMap road graphs for microcontrollers.

`roadpack` turns an OpenStreetMap extract (`.osm.pbf`) into a `.gmap`: a binary road graph with a precomputed
**contraction hierarchy**, laid out so a device with a few MB of RAM can route straight from a microSD card
without loading the map. It powers an offline motorcycle navigator on an ESP32-S3, which routes the 977 km
from Bogotá to Cartagena in about 8 seconds.

## Install

```bash
pip install git+https://github.com/NicolasDevel/roadpack.git
```

Building the contraction hierarchy needs `git` and a C++17 compiler: the first build fetches
[RoutingKit](https://github.com/RoutingKit/RoutingKit) and compiles a small helper into `~/.cache/roadpack`.

## Usage

```bash
# An extract from https://download.geofabrik.de, e.g. Colombia: the whole file, or a part of it
roadpack build colombia-latest.osm.pbf -o out/colombia.gmap
roadpack build colombia-latest.osm.pbf --region bogota -o out/bogota.gmap
roadpack build colombia-latest.osm.pbf --bbox 4.45,-74.25,4.84,-73.98 --profile car -o out/bogota-car.gmap

roadpack info out/bogota.gmap
roadpack route out/bogota.gmap --from 4.5981,-74.0760 --to 4.6766,-74.0482 --check --images out/preview
roadpack stats out/bogota.gmap --routes 200
```

`build` writes `out/bogota.gmap` and `out/bogota/`, the same file split into 4 MiB chunks for a FAT SD card.
`route` routes like a device would and prints the maneuvers; `--check` compares against A* on the full graph
and `--images` renders the route and each maneuver screen.

`stats` routes between random pairs of nodes and reports how many nodes the contraction hierarchy settles and
how many KB of the file each route reads, which is what an SD card has to deliver.

## Results

A few of the [benchmarks](benchmarks/README.md) (motorcycle profile, 200 random routes per region):

| Region | Graph nodes | `.gmap` | Build | Median route | Nodes settled (median) | A* settles |
|---|---:|---:|---:|---:|---:|---:|
| Bogotá | 89 k | 15 MB | 2 s | 14 km | 236 | 31 k |
| London | 415 k | 62 MB | 10 s | 31 km | 370 | 84 k |
| Colombia | 1.26 M | 287 MB | 52 s | 617 km | 275 | 458 k |
| Spain | 3.28 M | 620 MB | 126 s | 550 km | 459 | 578 k |
| Brazil | 10.1 M | 2.5 GB | 8 min | 1,690 km | 630 | 3.4 M |

The `.gmap` v2 format addresses up to 4 GiB and about 164° of longitude, so a country like the United States
is built per state.

## Layout

| Module | Layer |
|---|---|
| `roadpack.osm` | Loading: drivable ways of an OSM extract for a vehicle profile (`motorcycle`, `car`) |
| `roadpack.graph` | Graph: segments between intersections, simplified geometry, Morton order, spatial grid |
| `roadpack.ch` | Contraction hierarchy (RoutingKit, `build_ch.cpp`) |
| `roadpack.format` | The `.gmap` format: writer, reader, SD card chunks |
| `roadpack.routing` | Reference routing: CH query, A*, turn-by-turn maneuvers |
| `roadpack.preview` | PNG of a route and of each maneuver on a round 466×466 display |
| `roadpack.cli` | The `roadpack` command |

The binary format is specified in [FORMAT.md](FORMAT.md).

## Tests

```bash
pip install -e '.[test]' && pytest
```

The tests build small synthetic OpenStreetMap files: a hand-made town that exercises every rule (one-ways,
access tags per vehicle, roundabouts, loops, parking aisles, roads crossing the bounding box, geometry
simplification) and random street grids, on which the contraction hierarchy must match Dijkstra on every pair
of nodes.

## Licenses

- This repository's code: [MIT](LICENSE).
- Generated maps are a database derived from OpenStreetMap, © OpenStreetMap contributors, under the
  [ODbL](https://opendatacommons.org/licenses/odbl/): if you distribute them, give that attribution and share
  them under the same license.
- [RoutingKit](https://github.com/RoutingKit/RoutingKit) (BSD 2-Clause) is downloaded and compiled on use; it
  is not included in this repository.
- Python dependencies: [pyosmium](https://github.com/osmcode/pyosmium) (BSD 2-Clause),
  [NumPy](https://numpy.org) (BSD 3-Clause), [Pillow](https://python-pillow.org) (MIT-CMU).
