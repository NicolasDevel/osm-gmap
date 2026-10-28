"""Route queries on a .gmap: the contraction hierarchy query (what a device runs) and a plain A* on the
full graph, kept as the reference to validate the hierarchy against.
"""
import bisect
import heapq
import math

from ..format.reader import Gmap
from ..format.spec import CH_ARC, CH_ORIGINAL
from ..geo import local_xy

MAX_SPEED_KMH = 120  # for the A* heuristic: never overestimates the remaining time


def route_astar(gmap: Gmap, start: int, goal: int, stats=None):
    """Fastest route with A* on the full graph. Returns (edges, cost in tenths of a second).
    The route may end at a copy of the goal (arriving along a way with turn restrictions there)."""
    goal_pt = gmap.point(goal)
    goals = {goal, *gmap.copies_of(goal)}

    def h(n):  # tenths of a second at top speed
        return math.hypot(*local_xy(gmap.point(n), goal_pt)) * 36 / MAX_SPEED_KMH

    best = {start: 0}
    came_from = {}
    open_heap = [(h(start), 0, start)]
    settled = 0
    while open_heap:
        _, cost, node = heapq.heappop(open_heap)
        if cost > best.get(node, math.inf):
            continue
        settled += 1
        if node in goals:
            if stats is not None:
                stats["settled"] = settled
            path = []
            while node != start:
                e = came_from[node]
                path.append(e)
                node = gmap.source[e]
            return path[::-1], cost
        for e in gmap.out_edges(node):
            nxt = gmap.target[e]
            c = cost + gmap.weight[e]
            if c < best.get(nxt, math.inf):
                best[nxt] = c
                came_from[nxt] = e
                heapq.heappush(open_heap, (c + h(nxt), c, nxt))
    if stats is not None:
        stats["settled"] = settled
    return None, math.inf


def _unpack(gmap, side, arc, out, reads=None):
    """Expand a hierarchy arc into its original edges, in order. Shortcut = backward(a) + forward(b)."""
    stack = [(side, arc)]
    while stack:
        sd, a = stack.pop()
        ch = gmap.ch_fwd if sd == "f" else gmap.ch_bwd
        if reads is not None:
            reads.append((ch.arcs_off + a * CH_ARC.size, CH_ARC.size))
        if ch.a[a] & CH_ORIGINAL:
            out.append(ch.a[a] & ~CH_ORIGINAL)
        else:
            stack.append(("f", ch.b[a]))  # pushed first so the second half is expanded later
            stack.append(("b", ch.a[a]))


def route_ch(gmap: Gmap, start: int, goal: int, stats=None, reads=None):
    """Fastest route with the contraction hierarchy: bidirectional Dijkstra going only upwards.
    Returns (edges, cost in tenths of a second); ([], 0) if start == goal, (None, inf) if unreachable.
    The backward search starts at the goal and at its copies (turn restrictions): the route may arrive at any.
    If `reads` is a list, the (file offset, size) of every hierarchy record the query touches is appended."""
    goals = [goal, *gmap.copies_of(goal)]
    dist = ({start: 0}, {g: 0 for g in goals})
    pred = ({}, {})  # node -> arc it was reached through
    heaps = ([(0, start)], [(0, g) for g in goals])
    sides = (gmap.ch_fwd, gmap.ch_bwd)
    best, meet = math.inf, None
    settled = 0
    while heaps[0] or heaps[1]:
        # Advance the side with the lowest key; each side stops once it cannot improve the best route.
        k = 0 if heaps[0] and (not heaps[1] or heaps[0][0][0] <= heaps[1][0][0]) else 1
        d, u = heapq.heappop(heaps[k])
        if d >= best:
            heaps[k].clear()
            continue
        if d > dist[k].get(u, math.inf):
            continue
        settled += 1
        if u in dist[1 - k] and d + dist[1 - k][u] < best:
            best, meet = d + dist[1 - k][u], u
        ch = sides[k]
        if reads is not None:
            reads.append((ch.first_off + u * 4, 8))
            reads.append((ch.arcs_off + ch.first[u] * CH_ARC.size, (ch.first[u + 1] - ch.first[u]) * CH_ARC.size))
        for a in range(ch.first[u], ch.first[u + 1]):
            v, nd = ch.other[a], d + ch.weight[a]
            if nd < dist[k].get(v, math.inf):
                dist[k][v] = nd
                pred[k][v] = a
                heapq.heappush(heaps[k], (nd, v))
    if stats is not None:
        stats["settled"] = settled
    if meet is None:
        return None, math.inf

    # Up from the start (forward arcs), then down to the goal (backward arcs).
    up = []
    n = meet
    while n != start:
        a = pred[0][n]
        up.append(a)
        n = bisect.bisect_right(gmap.ch_fwd.first, a) - 1  # node that stores the forward arc (its tail)
    path = []
    for a in reversed(up):
        _unpack(gmap, "f", a, path, reads)
    n = meet
    while n not in goals:
        a = pred[1][n]
        _unpack(gmap, "b", a, path, reads)
        n = bisect.bisect_right(gmap.ch_bwd.first, a) - 1  # node that stores the backward arc (its head)
    return path, best


def route(gmap: Gmap, start: int, goal: int):
    """Fastest route as a list of edges (uses the hierarchy), or None if there is no path."""
    return route_ch(gmap, start, goal)[0]
