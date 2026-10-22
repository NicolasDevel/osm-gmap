"""Routing: the contraction hierarchy must give exactly the optimal routes, and maneuvers must make sense."""
import heapq
import math

import pytest

from roadpack.routing import maneuvers, route, route_astar, route_ch


def dijkstra(g, start):
    """Plain Dijkstra on the full graph: the ground truth, independent of the code under test."""
    dist = {start: 0}
    heap = [(0, start)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for e in g.out_edges(u):
            v, nd = g.target[e], d + g.weight[e]
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                heapq.heappush(heap, (nd, v))
    return dist


def check_path(g, path, start, goal, cost):
    """The edges chain from start to goal and add up to the cost."""
    assert g.source[path[0]] == start and g.target[path[-1]] == goal
    for a, b in zip(path, path[1:]):
        assert g.target[a] == g.source[b]
    assert sum(g.weight[e] for e in path) == cost


def all_pairs(g, routing):
    for start in range(g.node_count):
        truth = dijkstra(g, start)
        for goal in range(g.node_count):
            if goal == start:
                continue
            path, cost = routing(g, start, goal)
            if goal not in truth:
                assert path is None and cost == math.inf, (start, goal)
                continue
            assert cost == truth[goal], (start, goal)
            check_path(g, path, start, goal, cost)


def test_ch_is_exact_on_random_grids(grid_map):
    all_pairs(grid_map, route_ch)


def test_ch_is_exact_on_the_town(town_map):
    all_pairs(town_map[0], route_ch)


def test_astar_is_exact(grid_map):
    all_pairs(grid_map, route_astar)


def test_some_pairs_are_unreachable_in_the_town(moto_town):
    # The town has dead-end one-ways, so the "no route" branch above is really exercised.
    g = moto_town
    assert any(len(dijkstra(g, s)) < g.node_count for s in range(g.node_count))


def test_route_to_itself(moto_town):
    assert route_ch(moto_town, 0, 0) == ([], 0)


def test_ch_settles_fewer_nodes_than_astar(grid_map):
    g = grid_map
    ch_total = astar_total = 0
    for start, goal in ((0, g.node_count - 1), (g.node_count - 1, 0), (5, g.node_count // 2)):
        ch_stats, astar_stats = {}, {}
        route_ch(g, start, goal, ch_stats)
        route_astar(g, start, goal, astar_stats)
        ch_total += ch_stats["settled"]
        astar_total += astar_stats["settled"]
    assert ch_total < astar_total


def node_at(g, point):
    return min(range(g.node_count), key=lambda n: abs(g.lat[n] - point[0]) + abs(g.lon[n] - point[1]))


@pytest.mark.parametrize("exit_name, number", [("south_exit", 1), ("east_exit", 2), ("north_exit", 3)])
def test_roundabout_exit_numbers(town, moto_town, exit_name, number):
    g = moto_town
    path = route(g, node_at(g, town.points["D"]), node_at(g, town.points[exit_name]))
    ms = maneuvers(g, path)
    (rb,) = [m for m in ms if m.kind == "roundabout"]
    assert rb.exit_number == number
    assert f"{['1st', '2nd', '3rd'][number - 1]} exit" in rb.text()
    assert rb.street == g.name(path[rb.edge_index + number])  # the edge after `number` roundabout edges


def test_turns(town, moto_town):
    g, p = moto_town, town.points
    # A -> E: along the avenue, then left at B into North street.
    ms = maneuvers(g, route(g, node_at(g, p["A"]), node_at(g, p["E"])))
    assert [m.kind for m in ms] == ["depart", "turn", "arrive"]
    assert ms[1].side == "left" and ms[1].street == "North street"
    assert ms[0].text() == "Head out onto Main avenue"
    assert ms[1].text() == "Turn left onto North street"
    assert ms[-1].at_m == pytest.approx(sum(g.length[e] for e in route(g, node_at(g, p["A"]), node_at(g, p["E"]))))


def test_straight_through_a_junction_has_no_maneuver(town, moto_town):
    g, p = moto_town, town.points
    # A -> C goes straight through B, where North street leaves to the left.
    ms = maneuvers(g, route(g, node_at(g, p["A"]), node_at(g, p["C"])))
    assert [m.kind for m in ms] == ["depart", "arrive"]


def test_bend_at_a_junction_says_which_way_to_keep(town, moto_town):
    # At C the avenue bends ~40° to the left (One way leaves to the north): worth an instruction.
    g, p = moto_town, town.points
    ms = maneuvers(g, route(g, node_at(g, p["A"]), node_at(g, p["D"])))
    assert [(m.kind, m.side) for m in ms] == [("depart", ""), ("slight", "left"), ("arrive", "")]
