"""Shared fixtures: a hand-made town that exercises every OSM rule, and random street grids."""
from dataclasses import dataclass
from pathlib import Path

import pytest

from roadpack.format import Gmap
from roadpack.osm import PROFILES
from roadpack.pipeline import build

from osm_builder import LAT0, LON0, STEP, OsmBuilder, grid_network

# Generous box around the town; "Far away" lies outside it, "East exit" crosses its border.
TOWN_BBOX = (LAT0 - 0.01, LON0 - 0.01, LAT0 + 0.01, LON0 + 0.01)


@dataclass
class Town:
    osm: Path
    points: dict  # name -> (lat, lon) of the interesting nodes


def make_town(path: Path) -> Town:
    """
    Layout (rows go north, columns east, 100 m apart):

        G ── Only cars (motorcycle=no) ── E ←─ Against (oneway=-1) ── F ─→ Dead end (oneway=yes)
                                                                      │ Private (access=private)
                                          │  ↖ Loop (closed way)      ↑ One way (oneway=yes)
        A ─────────── Main avenue ─────── B ────────────────────────── C ~~curve~~ D ── Route 45 (ref) ── H ── roundabout
        │ footway                                                                  │ parking aisle      exits N, E, S
    """
    o = OsmBuilder()
    pt = {}

    def n(name, row, col):
        pt[name] = (LAT0 + row * STEP, LON0 + col * STEP)
        return o.node(*pt[name])

    A, B, C, D = n("A", 0, 0), n("B", 0, 1), n("C", 0, 2), n("D", 0, 3)
    E, F, G, H = n("E", 1, 1), n("F", 1, 2), n("G", 1, 0), n("H", 0, 4)

    # Main avenue: one way through A, B, C, D, with a bend between C and D and a point exactly on the
    # straight line (Douglas-Peucker must drop it).
    mid_ab = n("mid_ab", 0, 0.5)  # collinear with A and B
    bend = [n("bend1", 0.25, 2.25), n("bend2", 0.3, 2.5), n("bend3", 0.25, 2.75)]
    o.way([A, mid_ab, B, C, *bend, D], highway="primary", name="Main avenue")

    o.way([B, E], highway="residential", name="North street")
    o.way([B, n("unnamed_end", -1, 1)], highway="residential")  # no name and no ref
    o.way([C, F], highway="residential", name="One way", oneway="yes")
    o.way([E, F], highway="residential", name="Against", oneway="-1")
    o.way([F, n("private_end", 2, 2)], highway="residential", name="Private", access="private")
    o.way([E, G], highway="residential", name="Only cars", motorcycle="no")
    o.way([F, n("dead_end", 1, 3)], highway="residential", name="Dead end", oneway="yes")  # no way back
    o.way([D, n("parking_end", -1, 3)], highway="service", service="parking_aisle", name="Parking")
    o.way([A, n("footway_end", -1, 0)], highway="footway", name="Footway")
    plaza = n("plaza1", 2, 0)
    o.way([plaza, n("plaza2", 2, 0.5), n("plaza3", 2.5, 0.5), plaza], highway="service", area="yes", name="Plaza")
    o.way([E, n("loop1", 1.5, 0.8), n("loop2", 1.8, 1.0), n("loop3", 1.5, 1.2), E], highway="residential",
          name="Loop")
    o.way([D, H], highway="trunk", ref="Route 45", maxspeed="80")

    # Roundabout around (0, 5.3), drawn counterclockwise: west, south, east, north, west.
    R1, R2, R3, R4 = n("R1", 0, 5), n("R2", 0.3, 5.3), n("R3", 0, 5.6), n("R4", -0.3, 5.3)
    o.way([H, R1], highway="trunk", ref="Route 45", maxspeed="80")
    o.way([R1, R4, R3, R2, R1], highway="primary", junction="roundabout", name="Roundabout")
    o.way([R2, n("north_exit", 1.3, 5.3)], highway="secondary", name="North exit")
    east = n("east_exit", 0, 6.6)
    o.way([R3, east], highway="secondary", name="East exit")
    o.way([east, n("far_east", 0, 70)], highway="secondary", name="East exit")
    o.way([R4, n("south_exit", -1.3, 5.3)], highway="secondary", name="South exit")

    o.way([o.node(LAT0 + 2, LON0), o.node(LAT0 + 2.001, LON0)], highway="residential", name="Far away")
    o.write(path)
    return Town(path, pt)


@pytest.fixture(scope="session")
def town(tmp_path_factory) -> Town:
    return make_town(tmp_path_factory.mktemp("town") / "town.osm")


def _build(osm, bbox, profile, out_dir):
    out = out_dir / "map.gmap"
    stats = build(osm, bbox, PROFILES[profile], out, chunk_dir=out_dir / "chunks", log=lambda _: None)
    return out, stats


@pytest.fixture(scope="session", params=["motorcycle", "car"])
def town_map(request, town, tmp_path_factory):
    """(Gmap, build stats, .gmap path, profile name) of the town for each vehicle profile."""
    out, stats = _build(town.osm, TOWN_BBOX, request.param, tmp_path_factory.mktemp(f"town-{request.param}"))
    return Gmap(out), stats, out, request.param


@pytest.fixture(scope="session")
def moto_town(town, tmp_path_factory):
    out, stats = _build(town.osm, TOWN_BBOX, "motorcycle", tmp_path_factory.mktemp("moto-town"))
    return Gmap(out)


@pytest.fixture(scope="session", params=[1, 2, 3])
def grid_map(request, tmp_path_factory):
    """A random 8 × 8 street grid (three different seeds)."""
    tmp = tmp_path_factory.mktemp(f"grid{request.param}")
    osm, _ = grid_network(8, seed=request.param)
    path = osm.write(tmp / "grid.osm")
    out, _ = _build(path, (LAT0 - 0.01, LON0 - 0.01, LAT0 + 0.02, LON0 + 0.02), "motorcycle", tmp)
    return Gmap(out)
