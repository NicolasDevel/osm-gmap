"""Serializes a RoadGraph and its contraction hierarchy into a .gmap file (layout in FORMAT.md)."""
from pathlib import Path

import numpy as np

from ..arrays import first_occurrences, ranges
from .reader import EDGE_DTYPE, NODE_DTYPE
from .spec import COPY, HEADER, MAGIC, NONE, SCALE, VERSION


def _fixed(deg):
    return round(deg * SCALE)


def _first_occurrence_order(keys):
    """Distinct keys ordered by where they first appear."""
    uniq, first = first_occurrences(keys)
    return uniq[np.argsort(first, kind="stable")]


def write_gmap(graph, ch, path: Path) -> dict:
    """Write the .gmap and return the size in bytes of each section."""
    # Names: one copy of each, in order of first use by a segment.
    used = _first_occurrence_order(graph.seg_name[graph.seg_name >= 0])
    encoded = [graph.names[i].encode("utf-8") + b"\0" for i in used.tolist()]
    names_blob = b"".join(encoded)
    name_off = np.full(len(graph.names) + 1, NONE, np.uint32)  # the extra slot maps -1 (no name) to NONE
    name_off[used] = np.cumsum([0] + [len(b) for b in encoded[:-1]]) if encoded else []

    # Geometry: count (u16), padding (u16), then lat/lon pairs. A segment's geometry is written the first time an
    # edge uses it, so it follows edge (and node) order on disk.
    counts = np.diff(graph.seg_geom_start)
    with_geom = _first_occurrence_order(graph.segment[counts[graph.segment] > 0])
    words = 1 + 2 * counts[with_geom]  # 32-bit words per geometry record
    rec_off = np.zeros(len(with_geom) + 1, np.int64)
    np.cumsum(words, out=rec_off[1:])
    geom = np.zeros(int(rec_off[-1]), np.uint32)
    geom[rec_off[:-1]] = counts[with_geom]  # count in the low half, padding 0 (little-endian)
    n = counts[with_geom]
    pts = ranges(graph.seg_geom_start[with_geom], n)  # point indices, record after record
    slots = 2 * ranges(np.zeros(len(n), np.int64), n) + np.repeat(rec_off[:-1] + 1, n)
    geom[slots] = graph.geom_lat7[pts].view(np.uint32)
    geom[slots + 1] = graph.geom_lon7[pts].view(np.uint32)
    geom_blob = geom.tobytes()
    seg_geom = np.full(len(counts), NONE, np.uint32)
    seg_geom[with_geom] = rec_off[:-1] * 4

    edges = np.zeros(graph.edge_count, EDGE_DTYPE)
    edges["source"], edges["target"] = graph.source, graph.target
    edges["geom"] = seg_geom[graph.segment]
    edges["name"] = name_off[graph.seg_name[graph.segment]]
    edges["length"], edges["weight"] = graph.length_m, graph.weight
    edges["speed"], edges["flags"] = graph.speed, graph.flags
    edges_blob = edges.tobytes()

    nodes = np.zeros(graph.node_count + 1, NODE_DTYPE)  # the last record is a sentinel: end of the last edges
    nodes["lat"][:-1], nodes["lon"][:-1] = graph.lat7, graph.lon7
    nodes["first_edge"] = graph.first_edge
    nodes_blob = nodes.tobytes()

    g = graph.grid
    grid_blob = b"".join(np.asarray(a, "<u4").tobytes() for a in ([len(g.cell_ids)], g.cell_ids, g.cell_start, g.items))

    nodes_off = HEADER.size
    edges_off = nodes_off + len(nodes_blob)
    grid_off = edges_off + len(edges_blob)
    geom_off = grid_off + len(grid_blob)
    names_off = geom_off + len(geom_blob)
    ch_fwd_off = names_off + len(names_blob)
    ch_fwd_off += -ch_fwd_off % 4  # CH sections aligned to 4 bytes
    ch_bwd_off = ch_fwd_off + len(ch.forward)
    copies = np.zeros((len(graph.copy_nodes), 2), "<u4")
    copies[:, 0], copies[:, 1] = graph.copy_nodes, graph.copy_original
    copies_blob = copies.tobytes()
    assert len(copies_blob) == len(copies) * COPY.size
    copies_off = ch_bwd_off + len(ch.backward)
    file_size = copies_off + len(copies_blob)
    if file_size >= 1 << 32:
        raise ValueError(f"the map is {file_size / 2**30:.1f} GiB; the .gmap format is limited to 4 GiB "
                         "(build a smaller region)")
    if g.cols > 0xFFFF or g.rows > 0xFFFF:
        raise ValueError(f"the region spans {g.cols} × {g.rows} grid cells; the .gmap format allows 65535 "
                         "per side (about 164° at the default cell size)")
    min_lat, min_lon, max_lat, max_lon = graph.bounds
    header = HEADER.pack(
        MAGIC, VERSION, HEADER.size, graph.node_count, graph.edge_count,
        _fixed(min_lat), _fixed(min_lon), _fixed(max_lat), _fixed(max_lon),
        _fixed(g.cell_deg), g.cols, g.rows,
        nodes_off, edges_off, grid_off, geom_off, names_off, ch_fwd_off, ch_bwd_off, file_size,
        copies_off, len(copies),
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        for part in (header, nodes_blob, edges_blob, grid_blob, geom_blob, names_blob):
            f.write(part)
        f.write(b"\0" * (ch_fwd_off - names_off - len(names_blob)))
        f.write(ch.forward)
        f.write(ch.backward)
        f.write(copies_blob)

    return {
        "header": len(header), "nodes": len(nodes_blob), "edges": len(edges_blob), "grid": len(grid_blob),
        "geometry": len(geom_blob), "names": len(names_blob), "ch_forward": len(ch.forward),
        "ch_backward": len(ch.backward), "copies": len(copies_blob), "total": file_size, "unique_names": len(used),
        "grid_cells": len(g.cell_ids),
    }
