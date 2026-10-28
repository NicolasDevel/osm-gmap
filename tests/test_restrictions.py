"""Turn restrictions: junctions are split so the hierarchy never routes through a forbidden turn, and routes stay
optimal among the allowed ones (checked against a turn-aware Dijkstra on the map built without them)."""
import heapq
import math
import random

import pytest

from roadpack.format import Gmap
from roadpack.osm import PROFILES
from roadpack.pipeline import build
from roadpack.routing import maneuvers, route_astar, route_ch

from osm_builder import LAT0, LON0, STEP, OsmBuilder, grid_network


def _build(osm_builder, tmp_path, name, restrictions=True, profile="motorcycle"):
    osm = osm_builder.write(tmp_path / f"{name}.osm")
    out = tmp_path / f"{name}.gmap"
    stats = build(osm, (LAT0 - 0.01, LON0 - 0.01, LAT0 + 0.02, LON0 + 0.02), PROFILES[profile], out,
                  restrictions=restrictions, log=lambda _: None)
    return Gmap(out), stats


def _node_at(g, lat, lon):
    """The original node at a position."""
    found = [n for n in range(g.node_count) if not g.is_copy(n) and
             g.point(n) == pytest.approx((lat, lon), abs=1e-7)]
    assert len(found) == 1
    return found[0]


def _turns(g, path):
    """Junctions of a route as (from point, via point, to point)."""
    return [(g.point(g.source[a]), g.point(g.target[a]), g.point(g.target[b])) for a, b in zip(path, path[1:])]


@pytest.fixture
def cross():
    """A + junction at C with arms N, S, E, W (100 m, two-way residential), plus a block around the north-east
    corner so that a forbidden left turn has a detour:

        N ── NE
        │    │
    W ─ C ── E
        │
        S
    """
    o = OsmBuilder()
    p = {"C": (0, 0), "N": (1, 0), "S": (-1, 0), "E": (0, 1), "W": (0, -1), "NE": (1, 1)}
    ids = {k: o.node(LAT0 + r * STEP, LON0 + c * STEP) for k, (r, c) in p.items()}
    ways = {k: o.way([ids["C"], ids[k]], highway="residential", name=f"{k} street") for k in ("N", "S", "E", "W")}
    o.way([ids["N"], ids["NE"], ids["E"]], highway="residential", name="Back street")
    pts = {k: o.nodes[i] for k, i in ids.items()}  # as written to the file (7 decimals)
    return o, ids, ways, pts


def test_no_left_turn_takes_the_detour(cross, tmp_path):
    o, ids, ways, pts = cross
    o.restriction("no_left_turn", ways["S"], ids["C"], ways["W"])  # coming from the south, no left onto W
    o.restriction("no_right_turn", ways["S"], ids["C"], ways["E"])
    g, stats = _build(o, tmp_path, "cross")
    assert stats["restrictions_applied"] == 2 and stats["node_copies"] == 1
    s, w, e, n = (_node_at(g, *pts[k]) for k in ("S", "W", "E", "N"))
    path, _ = route_ch(g, s, w)
    assert (pts["S"], pts["C"], pts["W"]) not in _turns(g, path)
    path, _ = route_ch(g, s, e)  # no right turn: straight on, then around
    assert [g.point(g.target[x]) for x in path[:2]] == [pts["C"], pts["N"]]
    assert (pts["S"], pts["C"], pts["E"]) not in _turns(g, path)
    # Other arrivals keep every exit; straight on from the south is still allowed.
    assert len(route_ch(g, e, w)[0]) == 2 and len(route_ch(g, s, n)[0]) == 2


def test_only_straight_on(cross, tmp_path):
    o, ids, ways, pts = cross
    o.restriction("only_straight_on", ways["S"], ids["C"], ways["N"])
    g, _ = _build(o, tmp_path, "only")
    s, e = _node_at(g, *pts["S"]), _node_at(g, *pts["E"])
    path, _ = route_ch(g, s, e)
    assert g.point(g.target[path[1]]) == pts["N"]
    # A U-turn at the junction is not allowed either: back to the south it has to go around (C, N, NE, E, C, S).
    assert len(route_ch(g, s, _node_at(g, *pts["W"]))[0]) > 2


def test_no_u_turn(tmp_path):
    o = OsmBuilder()
    a, b, c = (o.node(LAT0, LON0 + k * STEP) for k in range(3))
    ab = o.way([a, b], highway="residential")
    o.way([b, c], highway="residential")
    o.restriction("no_u_turn", ab, b, ab)
    g, stats = _build(o, tmp_path, "uturn")
    assert stats["restrictions_applied"] == 1
    a_n, b_n = _node_at(g, LAT0, LON0), _node_at(g, LAT0, LON0 + STEP)
    arrive = next(e for e in g.out_edges(a_n) if g.original(g.target[e]) == b_n)
    copy = g.target[arrive]
    assert g.copies_of(b_n) == [copy] and g.original(copy) == b_n
    assert [g.original(g.target[e]) for e in g.out_edges(copy)] == [_node_at(g, LAT0, LON0 + 2 * STEP)]
    assert sorted(g.original(g.target[e]) for e in g.out_edges(b_n)) == sorted([a_n, g.original(g.target[g.out_edges(copy)[0]])])


def test_u_turn_onto_the_other_carriageway(tmp_path):
    o = OsmBuilder()
    a, b, c = (o.node(LAT0, LON0 + k * STEP) for k in range(3))
    there = o.way([a, b], highway="primary", oneway="yes", name="Avenue")
    back = o.way([b, a], highway="primary", oneway="yes", name="Avenue")
    o.way([b, c], highway="residential")
    o.restriction("no_u_turn", there, b, back)
    g, stats = _build(o, tmp_path, "carriageways")
    assert stats["restrictions_applied"] == 1
    a_n, b_n, c_n = (_node_at(g, LAT0, LON0 + k * STEP) for k in range(3))
    copy = g.target[next(iter(g.out_edges(a_n)))]
    assert g.original(copy) == b_n and copy != b_n
    assert [g.original(g.target[e]) for e in g.out_edges(copy)] == [c_n]


def test_profile_rules(cross, tmp_path):
    o, ids, ways, pts = cross
    o.restriction("no_left_turn", ways["S"], ids["C"], ways["W"], except_="motorcycle")
    o.restriction("no_right_turn", ways["S"], ids["C"], ways["E"], restriction__conditional="no_right_turn @ (Su)",
                  restriction=None)
    o.restriction("no_straight_on", ways["W"], ids["C"], ways["E"], restriction__motorcar="no_straight_on",
                  restriction=None)
    _, moto = _build(o, tmp_path, "moto")
    _, car = _build(o, tmp_path, "car", profile="car")
    assert moto["restrictions"] == 0  # except motorcycle; conditional only; car only
    assert car["restrictions_applied"] == 2  # the left turn and the motorcar one


def test_ambiguous_and_unsupported_are_skipped(tmp_path):
    o = OsmBuilder()
    w, c, e = (o.node(LAT0, LON0 + k * STEP) for k in range(3))
    n = o.node(LAT0 + STEP, LON0 + STEP)
    through = o.way([w, c, e], highway="residential")  # passes through the junction: which side is "from"?
    north = o.way([c, n], highway="residential")
    o.restriction("no_left_turn", through, c, north)
    o.restriction("no_left_turn", north, through, north, via_type="way")
    o.restriction("no_left_turn", north, 999999, through)  # via node not in the network
    _, stats = _build(o, tmp_path, "skip")
    assert stats["restrictions"] == 3
    assert (stats["restrictions_ambiguous"], stats["restrictions_unsupported"], stats["restrictions_not_found"]) == (1, 1, 1)
    assert stats["restrictions_applied"] == 0 and stats["node_copies"] == 0


def test_maneuvers_see_the_whole_junction(cross, tmp_path):
    """Through a copy, the forbidden exit is still a street: going straight is not an instruction, and a turn is
    described against all the exits."""
    o, ids, ways, pts = cross
    o.restriction("no_left_turn", ways["S"], ids["C"], ways["W"])
    g, _ = _build(o, tmp_path, "man")
    path, _ = route_ch(g, _node_at(g, *pts["S"]), _node_at(g, *pts["E"]))
    ms = maneuvers(g, path)
    assert [(m.kind, m.side) for m in ms] == [("depart", ""), ("turn", "right"), ("arrive", "")]
    assert not g.is_copy(ms[1].node) and g.point(ms[1].node) == pts["C"]
    # Straight on through the copy: the exit taken is a copied edge, not a rival fork ("keep left").
    path, _ = route_ch(g, _node_at(g, *pts["S"]), _node_at(g, *pts["N"]))
    assert g.is_copy(g.target[path[0]])
    assert [m.kind for m in maneuvers(g, path)] == ["depart", "arrive"]


def _turn_dijkstra(g, start, forbidden):
    """Ground truth on the map built without restrictions: Dijkstra over edges, skipping forbidden turns given as
    (from point, via point, to point). Returns the best cost to reach each point."""
    best = {}
    dist = {}
    heap = []
    for e in g.out_edges(start):
        dist[e] = g.weight[e]
        heapq.heappush(heap, (g.weight[e], e))
    while heap:
        d, e = heapq.heappop(heap)
        if d > dist[e]:
            continue
        v = g.target[e]
        best[g.point(v)] = min(best.get(g.point(v), math.inf), d)
        turn_from = g.point(g.source[e])
        for f in g.out_edges(v):
            if (turn_from, g.point(v), g.point(g.target[f])) in forbidden:
                continue
            nd = d + g.weight[f]
            if nd < dist.get(f, math.inf):
                dist[f] = nd
                heapq.heappush(heap, (nd, f))
    return best


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
def test_random_grids_match_a_turn_aware_dijkstra(seed, tmp_path):
    osm, ids = grid_network(7, seed=seed)
    size = len(ids)
    way_of = {frozenset(refs): wid for wid, refs, _ in osm.ways}
    point = {osm_id: ll for osm_id, ll in osm.nodes.items()}
    rng = random.Random(seed)
    forbidden_osm = set()  # (from node, via, to node): turns the vehicle may not make
    oneway = {frozenset(refs): (refs, tags.get("oneway")) for _, refs, tags in osm.ways}

    def can_go(x, y):
        refs, ow = oneway[frozenset((x, y))]
        return ow is None or (ow == "yes") == (refs[0] == x)

    for _ in range(40):
        r, c = rng.randrange(1, size - 1), rng.randrange(1, size - 1)
        v = ids[r][c]
        arms = [ids[r - 1][c], ids[r + 1][c], ids[r][c - 1], ids[r][c + 1]]
        u = rng.choice(arms)
        if not can_go(u, v):
            continue
        fw = way_of[frozenset((u, v))]
        kind = rng.choice(["no", "no", "no", "only", "uturn"])
        if kind == "uturn":
            if not can_go(v, u):
                continue
            osm.restriction("no_u_turn", fw, v, fw)
            forbidden_osm.add((u, v, u))
        else:
            w = rng.choice([a for a in arms if a != u])
            if not can_go(v, w):
                continue
            osm.restriction(f"{kind}_x_turn", fw, v, way_of[frozenset((v, w))])
            forbidden_osm.update((u, v, a) for a in arms if (a == w) == (kind == "no"))
    g, stats = _build(osm, tmp_path, "grid")
    plain, _ = _build(osm, tmp_path, "plain", restrictions=False)
    assert stats["node_copies"] > 0 and plain.copy_count == 0
    forbidden = {(point[a], point[b], point[c]) for a, b, c in forbidden_osm}
    originals = [n for n in range(g.node_count) if not g.is_copy(n)]
    by_point = {g.point(n): n for n in originals}
    for s in originals:
        truth = _turn_dijkstra(plain, by_point_plain(plain, g.point(s)), forbidden)
        for t in originals:
            if t == s:
                continue
            path, cost = route_ch(g, s, t)
            expected = truth.get(g.point(t), math.inf)
            assert cost == expected, (seed, g.point(s), g.point(t))
            if path:
                assert g.original(g.source[path[0]]) == s and g.original(g.target[path[-1]]) == t
                assert not forbidden & set(_turns(g, path))
                assert route_astar(g, s, t)[1] == cost
    assert by_point  # the split map has the same junctions as the plain one
    assert len(by_point) == plain.node_count


def by_point_plain(g, pt):
    return next(n for n in range(g.node_count) if g.point(n) == pt)
