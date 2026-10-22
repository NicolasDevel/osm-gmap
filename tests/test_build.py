"""The whole pipeline on the hand-made town: which roads survive, in which direction, with what attributes."""
import math

import pytest

from roadpack.format.spec import CLASS_MASK, FLAG_GEOM_REVERSED, ROAD_CLASSES, travel_time_ds
from roadpack.geo import haversine_m


def names(g):
    return {g.name(e) for e in range(g.edge_count)}


def node_at(g, point):
    """Graph node at exactly this position (to 1e-7°), or None."""
    for n in range(g.node_count):
        if abs(g.lat[n] - point[0]) < 1e-7 and abs(g.lon[n] - point[1]) < 1e-7:
            return n
    return None


def edges_between(g, a, b):
    return [e for e in g.out_edges(a) if g.target[e] == b]


def test_kept_and_dropped_roads(town_map):
    g, _, _, profile = town_map
    kept = names(g)
    assert {"Main avenue", "North street", "One way", "Against", "Loop", "Route 45", "Roundabout",
            "North exit", "East exit", "South exit"} <= kept
    assert not {"Private", "Parking", "Footway", "Plaza", "Far away"} & kept
    assert ("Only cars" in kept) == (profile == "car")
    assert "" in kept  # the unnamed street


def test_interior_points_are_not_nodes(town, moto_town):
    g = moto_town
    for name in ("mid_ab", "bend1", "bend2", "bend3", "loop1", "loop3", "private_end", "parking_end"):
        assert node_at(g, town.points[name]) is None, name
    for name in ("A", "B", "C", "D", "E", "F", "H", "R1", "R2", "R3", "R4", "loop2"):
        assert node_at(g, town.points[name]) is not None, name


def test_way_crossing_the_bbox_is_kept_whole(town, moto_town):
    assert node_at(moto_town, town.points["far_east"]) is not None


def test_oneways(town, moto_town):
    g = moto_town
    C, F, E = (node_at(g, town.points[k]) for k in "CFE")
    assert edges_between(g, C, F) and not edges_between(g, F, C)  # oneway=yes
    assert edges_between(g, F, E) and not edges_between(g, E, F)  # oneway=-1


def test_roundabout_is_oneway_counterclockwise(town, moto_town):
    g = moto_town
    R1, R2, R3, R4 = (node_at(g, town.points[k]) for k in ("R1", "R2", "R3", "R4"))
    for a, b in ((R1, R4), (R4, R3), (R3, R2), (R2, R1)):
        (e,) = edges_between(g, a, b)
        assert g.is_roundabout(e)
        assert not edges_between(g, b, a)


def test_edge_attributes(town, moto_town):
    g = moto_town
    D, H, B, E = (node_at(g, town.points[k]) for k in "DHBE")
    (route45,) = edges_between(g, D, H)
    assert g.name(route45) == "Route 45"  # ref, the way has no name
    assert g.speed[route45] == 80
    assert ROAD_CLASSES[g.flags[route45] & CLASS_MASK] == "trunk"
    (north,) = edges_between(g, B, E)
    assert g.speed[north] == 25  # residential default
    for e in range(g.edge_count):
        assert g.weight[e] == travel_time_ds(g.length[e], g.speed[e])


def test_lengths_follow_the_original_geometry(town, moto_town):
    g, p = moto_town, town.points
    C, D = node_at(g, p["C"]), node_at(g, p["D"])
    (e,) = edges_between(g, C, D)
    curve = [p["C"], p["bend1"], p["bend2"], p["bend3"], p["D"]]
    expected = sum(haversine_m(a, b) for a, b in zip(curve, curve[1:]))
    assert g.length[e] == round(expected)
    assert g.length[e] > haversine_m(p["C"], p["D"]) + 10  # the bend is longer than the chord


def test_geometry_is_simplified_and_shared_by_both_directions(town, moto_town):
    g, p = moto_town, town.points
    A, B, C, D = (node_at(g, p[k]) for k in "ABCD")
    (ab,) = edges_between(g, A, B)
    assert g.polyline(ab) == [g.point(A), g.point(B)]  # the collinear point was dropped
    (cd,), (dc,) = edges_between(g, C, D), edges_between(g, D, C)
    forward = g.polyline(cd)
    assert len(forward) == 5
    assert g.polyline(dc) == forward[::-1]
    assert g.geom[cd] == g.geom[dc]  # one copy on disk
    assert bool(g.flags[cd] & FLAG_GEOM_REVERSED) != bool(g.flags[dc] & FLAG_GEOM_REVERSED)
    for got, want in zip(forward[1:-1], (p["bend1"], p["bend2"], p["bend3"])):
        assert got == pytest.approx(want, abs=1e-7)


def test_loop_is_drivable(town, moto_town):
    g = moto_town
    E, mid = node_at(g, town.points["E"]), node_at(g, town.points["loop2"])
    assert len([e for e in g.out_edges(E) if g.name(e) == "Loop"]) == 2  # both halves leave E
    assert len([e for e in g.out_edges(mid) if g.name(e) == "Loop"]) == 2


def test_nodes_are_in_morton_order(moto_town):
    from roadpack.geo import morton
    g = moto_town
    codes = [morton(int((g.lat[n] - g.min_lat) / g.cell), int((g.lon[n] - g.min_lon) / g.cell))
             for n in range(g.node_count)]
    assert codes == sorted(codes)


def test_build_stats(town_map):
    g, stats, _, _ = town_map
    assert stats["nodes"] == g.node_count and stats["edges"] == g.edge_count
    assert stats["osm_nodes"] > stats["nodes"]
    assert stats["shape_points_kept"] < stats["shape_points"]
    assert stats["sections"]["total"] == len(g.data)
    assert stats["chunks"] == 1


def test_build_is_deterministic(town, tmp_path):
    from roadpack.osm import PROFILES
    from roadpack.pipeline import build
    from conftest import TOWN_BBOX
    outs = [tmp_path / "a.gmap", tmp_path / "b.gmap"]
    for out in outs:
        build(town.osm, TOWN_BBOX, PROFILES["motorcycle"], out, log=lambda _: None)
    assert outs[0].read_bytes() == outs[1].read_bytes()


def test_empty_area_is_an_error(town, tmp_path):
    from roadpack.osm import PROFILES
    from roadpack.pipeline import build
    with pytest.raises(ValueError, match="no drivable roads"):
        build(town.osm, (-1.0, -1.0, -0.9, -0.9), PROFILES["motorcycle"], tmp_path / "x.gmap", log=lambda _: None)


def test_total_road_length(town, moto_town):
    # Sanity check on the scale: the town has a few km of roads plus the 6 km "East exit".
    km = sum(moto_town.length) / 1000
    assert 10 < km < 25 and not math.isnan(km)
