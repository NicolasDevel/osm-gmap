"""Turn restrictions by node splitting: the graph stays node-based, so the contraction hierarchy and the query on
the device do not change.

At a junction v with turn restrictions, each restricted way of arrival gets its own copy of v: the edge arriving
along that way is redirected to the copy, and the copy only has (copies of) the exits that are allowed from it.
Edges arriving along other ways keep going to v, which keeps every exit. Copies are placed right after their
original in node order (same place on the SD card) and are listed in the file, so a reader can tell that they are
the same junction (to describe maneuvers, draw streets once, or snap a position).

A restriction with via ways (usually the short segment across a median: no U-turn onto the other carriageway) is
a sequence of edges: the arrival, then the edges along the via ways. Then a copy stands for "arrived along this
sequence": the arrival leads to a copy of the first junction, whose exit along the via way leads to a copy of the
next one, and so on until the last, which lacks the forbidden exits. In general the copies are the states of an
automaton over the edges driven (Aho-Corasick over all the sequences, so restrictions that share junctions combine),
and equivalent states at the same junction share a copy. Inside a via way the vehicle may not turn back along it:
otherwise a route would cross the median, turn around in the gap and cross again, no longer "arriving along the
from way", and the restriction would never apply. With only via-node restrictions this gives one copy per
junction and set of forbidden exits.

A via node is supported when the from and to ways end at it (as OSM requires): if a way goes through the via node,
which side the restriction means is ambiguous, and it is skipped. Via ways are supported when they make a single
path of edges from the end of the from way to the to way.
"""
from collections import defaultdict, deque
from dataclasses import replace

import numpy as np


def split_restricted_nodes(graph, way_ids, restrictions):
    """New RoadGraph with the restrictions applied (or the same graph if there are none)."""
    stats = {"restrictions": len(restrictions) + restrictions.skipped, "restrictions_applied": 0,
             "restrictions_not_found": 0, "restrictions_ambiguous": 0, "restrictions_unsupported": restrictions.skipped,
             "node_copies": 0, "edge_copies": 0}
    n, m = graph.node_count, graph.edge_count
    edge_way = way_ids[graph.seg_way[graph.segment]]  # OSM way id of each edge
    first_edge = graph.first_edge
    in_order = np.argsort(graph.target, kind="stable")
    in_first = np.searchsorted(graph.target[in_order], np.arange(n + 1))
    by_osm = np.argsort(graph.osm_ids, kind="stable")
    sorted_osm = graph.osm_ids[by_osm]

    rules = defaultdict(set)  # sequence of edges -> exits forbidden at its end
    for k in range(len(restrictions.via)):
        i = np.searchsorted(sorted_osm, restrictions.via[k])
        if i == len(sorted_osm) or sorted_osm[i] != restrictions.via[k]:
            stats["restrictions_not_found"] += 1  # outside the region, or not a junction of drivable roads
            continue
        v = int(by_osm[i])
        exits = range(first_edge[v], first_edge[v + 1])
        ins = [int(e) for e in in_order[in_first[v]:in_first[v + 1]] if edge_way[e] == restrictions.from_way[k]]
        outs = [e for e in exits if edge_way[e] == restrictions.to_way[k]]
        if restrictions.from_way[k] == restrictions.to_way[k]:
            # Back along the same way (no_u_turn): only the reverse of the arrival, not the way going on past the
            # junction. A U-turn onto the other carriageway has a different to way and is like any other turn.
            outs = [e for e in outs for a in ins if graph.segment[e] == graph.segment[a]]
        if not ins or not outs:
            stats["restrictions_not_found"] += 1  # a way the vehicle cannot use, or not touching the via node
            continue
        if len(ins) > 1 or len(outs) > 1:
            stats["restrictions_ambiguous"] += 1
            continue
        stats["restrictions_applied"] += 1
        e_in = ins[0]
        if restrictions.only[k]:
            rules[(e_in,)].update(e for e in exits if e not in outs)
        else:
            rules[(e_in,)].update(outs)

    for rule in _locate_via_ways(graph, edge_way, in_order, in_first, restrictions.via_ways, stats):
        rules[rule[0]].update(rule[1])
    if not rules:
        return replace(graph, stats={**graph.stats, **stats})

    def reverse(e):
        """The edge back along the same segment, or -1."""
        u, v = graph.source[e], graph.target[e]
        return next((f for f in range(first_edge[v], first_edge[v + 1])
                     if graph.target[f] == u and graph.segment[f] == graph.segment[e]), -1)

    states, banned, delta = _automaton(rules, reverse)
    copies, class_of = _merge_states(graph, states, banned, delta)

    # Copies go right after their original: new number = old number + copies of the nodes before it.
    per_node = np.zeros(n, np.int64)
    for v, classes in copies.items():
        per_node[v] = len(classes)
    shift = np.concatenate([[0], np.cumsum(per_node)[:-1]])
    new_node = np.arange(n) + shift
    total = n + int(per_node.sum())
    copy_nodes = np.array(sorted(new_node[v] + 1 + j for v, classes in copies.items() for j in range(len(classes))),
                          np.int64)
    original = np.repeat(np.arange(n), per_node + 1)  # old original of every new node
    copy_original = new_node[original[copy_nodes]]

    copy_id = {}  # state class -> new node number of its copy
    for v, classes in copies.items():
        for j, c in enumerate(classes):
            copy_id[c] = int(new_node[v]) + 1 + j

    def node_after(state, e):
        """New node reached along old edge e into an automaton state (0: nothing pending, the original junction)."""
        return int(new_node[graph.target[e]]) if state == 0 else copy_id[class_of[state]]

    target = new_node[graph.target]
    for (e,), state in ((p, st) for p, st in states.items() if len(p) == 1):
        target[e] = node_after(state, e)
    source = new_node[graph.source]

    # Exits of each copy: the allowed ones of the original, going to the state one edge further (a copy, if a
    # restriction is pending there, or the original junction).
    dup_from, dup_source, dup_target = [], [], []
    for v, classes in sorted(copies.items()):
        for j, c in enumerate(classes):
            state = c[0]  # any state of the class: they behave the same
            for e in range(first_edge[v], first_edge[v + 1]):
                if e not in banned[state]:
                    dup_from.append(e)
                    dup_source.append(new_node[v] + 1 + j)
                    dup_target.append(node_after(delta(state, e), e))
    dup_from = np.array(dup_from, np.int64)
    every = np.concatenate([np.arange(m), dup_from])  # old edge each new edge comes from
    all_source = np.concatenate([source, np.array(dup_source, np.int64)])
    all_target = np.concatenate([target, np.array(dup_target, np.int64)])
    order = np.lexsort((graph.segment[every], all_source))  # stable: original edges keep their order
    every, all_source, all_target = every[order], all_source[order], all_target[order]
    new_edge = np.empty(m, np.int64)
    is_original = order < m
    new_edge[order[is_original]] = np.flatnonzero(is_original)

    grid = replace(graph.grid, items=new_edge[graph.grid.items])
    stats["node_copies"] = len(copy_nodes)
    stats["edge_copies"] = len(dup_from)
    return replace(
        graph,
        lat7=graph.lat7[original], lon7=graph.lon7[original], osm_ids=graph.osm_ids[original],
        seg_a=new_node[graph.seg_a], seg_b=new_node[graph.seg_b],
        source=all_source, target=all_target, segment=graph.segment[every], length_m=graph.length_m[every],
        weight=graph.weight[every], speed=graph.speed[every], flags=graph.flags[every],
        first_edge=np.searchsorted(all_source, np.arange(total + 1)).astype(np.int64),
        grid=grid, copy_nodes=copy_nodes, copy_original=copy_original, stats={**graph.stats, **stats},
    )


def _locate_via_ways(graph, edge_way, in_order, in_first, via_ways, stats):
    """Restrictions with via ways as (sequence of edges, exits forbidden at its end): the arrival along the from
    way, then the shortest path along the via ways to a junction with an exit along the to way."""
    if not via_ways:
        return []
    first_edge, source, target = graph.first_edge, graph.source, graph.target
    wanted = np.array(sorted({w for f, vias, t, _ in via_ways for w in (f, t, *vias)}), np.int64)
    edges_of = defaultdict(list)
    for e in np.flatnonzero(np.isin(edge_way, wanted)):
        edges_of[int(edge_way[e])].append(int(e))

    rules = []
    for from_way, vias, to_way, only in via_ways:
        if not edges_of[from_way] or not edges_of[to_way] or not all(edges_of[w] for w in vias):
            stats["restrictions_not_found"] += 1  # outside the region, or a way the vehicle cannot use
            continue
        via_set = set(vias)
        starts = sorted({int(target[e]) for e in edges_of[from_way]} &
                        {int(source[e]) for w in vias for e in edges_of[w]})
        found = []
        for a in starts:
            reached_by = {a: None}  # node -> edge it was reached by
            queue = deque([a])
            while queue:
                u = queue.popleft()
                if u != a and any(edge_way[e] == to_way for e in range(first_edge[u], first_edge[u + 1])):
                    path = []
                    while u != a:
                        path.append(reached_by[u])
                        u = int(source[reached_by[u]])
                    found.append((a, path[::-1]))
                    break
                for e in range(first_edge[u], first_edge[u + 1]):
                    if int(edge_way[e]) in via_set and int(target[e]) not in reached_by:
                        reached_by[int(target[e])] = e
                        queue.append(int(target[e]))
        if not found:
            stats["restrictions_not_found"] += 1
            continue
        if len(found) > 1:
            stats["restrictions_ambiguous"] += 1
            continue
        a, path = found[0]
        b = int(target[path[-1]])
        ins = [int(e) for e in in_order[in_first[a]:in_first[a + 1]] if edge_way[e] == from_way]
        exits = range(first_edge[b], first_edge[b + 1])
        outs = [e for e in exits if edge_way[e] == to_way]
        if len(ins) > 1 or len(outs) > 1:
            stats["restrictions_ambiguous"] += 1  # the from or to way goes through the junction
            continue
        stats["restrictions_applied"] += 1
        rules.append(((ins[0], *path), [e for e in exits if e not in outs] if only else outs))
    return rules


def _automaton(rules, reverse):
    """Aho-Corasick over the edge sequences of the rules. States are the prefixes of the sequences (0 is the empty
    one: nothing pending); `banned[s]` are the exits forbidden in state s (by every rule that ends there, also as a
    suffix, and turning back along a via way), and `delta(s, e)` is the state after driving edge e from state s:
    the longest suffix of the sequence so far that is a state."""
    states = {(): 0}
    for seq in sorted(rules):
        for i in range(1, len(seq) + 1):
            states.setdefault(seq[:i], len(states))
    seq_of = sorted(states, key=states.get)
    banned = [set().union(*(rules.get(p[i:], ()) for i in range(len(p)))) for p in seq_of]
    for p, b in zip(seq_of, banned):
        if len(p) >= 2:  # the last edge is along a via way (via-node sequences have only the arrival)
            b.add(reverse(p[-1]))

    def delta(state, e):
        p = seq_of[state] + (e,)
        for i in range(len(p)):
            if p[i:] in states:
                return states[p[i:]]
        return 0

    return states, banned, delta


def _merge_states(graph, states, banned, delta):
    """Group the pending states (all but 0) that behave the same at the same junction: same forbidden exits, and
    each exit leading to equivalent states (partition refinement). Returns node -> [classes in copy order] and
    state -> class; a class is the sorted tuple of its states, and classes are ordered by their first sequence."""
    first_edge, target = graph.first_edge, graph.target
    pending = [st for p, st in states.items() if p]
    node = {st: int(target[p[-1]]) for p, st in states.items() if p}
    exits = {st: [e for e in range(first_edge[node[st]], first_edge[node[st] + 1]) if e not in banned[st]]
             for st in pending}
    succ = {st: [delta(st, e) for e in exits[st]] for st in pending}
    label = {st: (node[st], tuple(sorted(banned[st]))) for st in pending}
    while True:
        ids = {key: i for i, key in enumerate(sorted(set(label.values())))}
        group = {st: ids[label[st]] for st in pending}
        label = {st: (group[st], tuple(group.get(t, -1) for t in succ[st])) for st in pending}
        if len(set(label.values())) == len(ids):
            break
    members = defaultdict(list)
    for st in pending:
        members[group[st]].append(st)
    seq_of = {st: p for p, st in states.items()}
    copies, class_of = defaultdict(list), {}
    for c in sorted((tuple(sorted(ms, key=seq_of.get)) for ms in members.values()), key=lambda c: seq_of[c[0]]):
        copies[node[c[0]]].append(c)
        for st in c:
            class_of[st] = c
    return copies, class_of
