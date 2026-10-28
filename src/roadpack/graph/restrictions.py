"""Turn restrictions by node splitting: the graph stays node-based, so the contraction hierarchy and the query on
the device do not change.

At a junction v with turn restrictions, each restricted way of arrival gets its own copy of v: the edge arriving
along that way is redirected to the copy, and the copy only has (copies of) the exits that are allowed from it.
Edges arriving along other ways keep going to v, which keeps every exit. Copies are placed right after their
original in node order (same place on the SD card) and are listed in the file, so a reader can tell that they are
the same junction (to describe maneuvers, draw streets once, or snap a position).

Only restrictions with a via node are supported, and only when the from and to ways end at it (as OSM requires): if
a way goes through the via node, which side the restriction means is ambiguous, and it is skipped.
"""
from collections import defaultdict
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

    forbidden = defaultdict(set)  # arriving edge -> exits it may not take
    for k in range(len(restrictions)):
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
            forbidden[e_in].update(e for e in exits if e not in outs)
        else:
            forbidden[e_in].update(outs)
    if not forbidden:
        return replace(graph, stats={**graph.stats, **stats})

    # One copy per junction and set of forbidden exits (arrivals with the same restrictions share it).
    copies = defaultdict(list)  # node -> [frozenset of forbidden exits], in a stable order
    copy_of_edge = {}  # arriving edge -> (node, copy number)
    for e_in in sorted(forbidden):
        v, key = int(graph.target[e_in]), frozenset(forbidden[e_in])
        if key not in copies[v]:
            copies[v].append(key)
        copy_of_edge[e_in] = (v, copies[v].index(key))

    # Copies go right after their original: new number = old number + copies of the nodes before it.
    per_node = np.zeros(n, np.int64)
    for v, keys in copies.items():
        per_node[v] = len(keys)
    shift = np.concatenate([[0], np.cumsum(per_node)[:-1]])
    new_node = np.arange(n) + shift
    total = n + int(per_node.sum())
    copy_nodes = np.array(sorted(new_node[v] + 1 + j for v, keys in copies.items() for j in range(len(keys))),
                          np.int64)
    original = np.repeat(np.arange(n), per_node + 1)  # old original of every new node
    copy_original = new_node[original[copy_nodes]]

    target = new_node[graph.target]
    for e_in, (v, j) in copy_of_edge.items():
        target[e_in] = new_node[v] + 1 + j
    source = new_node[graph.source]

    # Exits of each copy: the allowed ones of the original, going where the original edge goes (to a copy too, if
    # it is itself a restricted arrival at the next junction).
    dup_from, dup_source = [], []
    for v, keys in sorted(copies.items()):
        for j, key in enumerate(keys):
            for e in range(first_edge[v], first_edge[v + 1]):
                if e not in key:
                    dup_from.append(e)
                    dup_source.append(new_node[v] + 1 + j)
    dup_from = np.array(dup_from, np.int64)
    every = np.concatenate([np.arange(m), dup_from])  # old edge each new edge comes from
    all_source = np.concatenate([source, np.array(dup_source, np.int64)])
    all_target = np.concatenate([target, target[dup_from]])
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
