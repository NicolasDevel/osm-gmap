"""Serializes a RoadGraph and its contraction hierarchy into a .gmap file (layout in FORMAT.md)."""
import struct
from pathlib import Path

from .spec import EDGE, GEOM_HEADER, HEADER, MAGIC, NODE, NONE, POINT, SCALE, VERSION


def _fixed(deg):
    return round(deg * SCALE)


def write_gmap(graph, ch, path: Path) -> dict:
    """Write the .gmap and return the size in bytes of each section."""
    # Names: one copy of each, in segment order.
    names_blob, name_off = bytearray(), {}
    seg_name = []
    for seg in graph.segments:
        name = seg.way.name
        if not name:
            seg_name.append(NONE)
            continue
        if name not in name_off:
            name_off[name] = len(names_blob)
            names_blob += name.encode("utf-8") + b"\0"
        seg_name.append(name_off[name])

    # Geometry is written the first time an edge uses it, so it follows edge (and node) order on disk.
    geom_blob, seg_geom = bytearray(), {}
    edges_blob = bytearray()
    for e in graph.edges:
        s = e.segment
        if s not in seg_geom:
            interior = graph.segments[s].interior
            if interior:
                seg_geom[s] = len(geom_blob)
                geom_blob += GEOM_HEADER.pack(len(interior), 0)
                for lat, lon in interior:
                    geom_blob += POINT.pack(_fixed(lat), _fixed(lon))
            else:
                seg_geom[s] = NONE
        edges_blob += EDGE.pack(e.source, e.target, seg_geom[s], seg_name[s], e.length_m, e.weight, e.speed, e.flags, 0)

    nodes_blob = bytearray()
    for (lat, lon), first in zip(graph.nodes, graph.first_edge):
        nodes_blob += NODE.pack(_fixed(lat), _fixed(lon), first)
    nodes_blob += NODE.pack(0, 0, graph.first_edge[-1])  # sentinel: end of the last node's edges

    cells = graph.grid.cells
    cell_ids = sorted(cells)
    starts, total = [], 0
    for cid in cell_ids:
        starts.append(total)
        total += len(cells[cid])
    starts.append(total)
    grid_blob = bytearray(struct.pack("<I", len(cell_ids)))
    grid_blob += struct.pack(f"<{len(cell_ids)}I", *cell_ids)
    grid_blob += struct.pack(f"<{len(starts)}I", *starts)
    for cid in cell_ids:
        grid_blob += struct.pack(f"<{len(cells[cid])}I", *cells[cid])

    nodes_off = HEADER.size
    edges_off = nodes_off + len(nodes_blob)
    grid_off = edges_off + len(edges_blob)
    geom_off = grid_off + len(grid_blob)
    names_off = geom_off + len(geom_blob)
    ch_fwd_off = names_off + len(names_blob)
    ch_fwd_off += -ch_fwd_off % 4  # CH sections aligned to 4 bytes
    ch_bwd_off = ch_fwd_off + len(ch.forward)
    file_size = ch_bwd_off + len(ch.backward)
    min_lat, min_lon, max_lat, max_lon = graph.bounds
    header = HEADER.pack(
        MAGIC, VERSION, HEADER.size, len(graph.nodes), len(graph.edges),
        _fixed(min_lat), _fixed(min_lon), _fixed(max_lat), _fixed(max_lon),
        _fixed(graph.grid.cell_deg), graph.grid.cols, graph.grid.rows,
        nodes_off, edges_off, grid_off, geom_off, names_off, ch_fwd_off, ch_bwd_off, file_size,
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        for part in (header, nodes_blob, edges_blob, grid_blob, geom_blob, names_blob):
            f.write(part)
        f.write(b"\0" * (ch_fwd_off - names_off - len(names_blob)))
        f.write(ch.forward)
        f.write(ch.backward)

    return {
        "header": len(header), "nodes": len(nodes_blob), "edges": len(edges_blob), "grid": len(grid_blob),
        "geometry": len(geom_blob), "names": len(names_blob), "ch_forward": len(ch.forward),
        "ch_backward": len(ch.backward), "total": file_size, "unique_names": len(name_off),
        "grid_cells": len(cell_ids),
    }
