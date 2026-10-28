"""The whole pipeline: OSM extract -> drivable ways -> compact graph -> contraction hierarchy -> .gmap file."""
import time
from pathlib import Path

from .ch import build_graph_ch
from .format import CHUNK_SIZE, write_chunks, write_gmap
from .graph import CELL_DEG, SIMPLIFY_TOLERANCE_M, build_graph, split_restricted_nodes
from .osm import Profile, load_roads


def _log(message):
    print(message, flush=True)


def build(pbf: Path, bbox, profile: Profile, out: Path, chunk_dir: Path | None = None, chunk_size=CHUNK_SIZE,
          cell_deg=CELL_DEG, simplify_tolerance_m=SIMPLIFY_TOLERANCE_M, restrictions=True, log=_log) -> dict:
    """Build out (a .gmap) from pbf, and split it into chunk_dir if given. Returns the build statistics."""
    t0 = time.time()
    log(f"Reading {pbf} (bbox {', '.join(f'{v:g}' for v in bbox)}, profile {profile.name}) ...")
    network = load_roads(pbf, bbox, profile, restrictions)
    t_load = time.time() - t0
    log(f"  {network.way_count:,} drivable ways, {network.node_count:,} OSM nodes ({t_load:.0f} s)")

    graph = build_graph(network, cell_deg, simplify_tolerance_m)
    graph = split_restricted_nodes(graph, network.way_ids, network.restrictions)
    del network
    log(f"  graph: {graph.node_count:,} nodes, {graph.edge_count:,} edges ({graph.stats['graph_seconds']:.0f} s); "
        "contracting ...")
    st = graph.stats
    if st["restrictions"]:
        log(f"  turn restrictions: {st['restrictions_applied']:,} of {st['restrictions']:,} applied "
            f"({st['restrictions_not_found']:,} outside the network, {st['restrictions_ambiguous']:,} ambiguous, "
            f"{st['restrictions_unsupported']:,} unsupported); {st['node_copies']:,} junction copies, "
            f"{st['edge_copies']:,} extra edges")

    t_ch = time.time()
    ch = build_graph_ch(graph, log)
    t_ch = time.time() - t_ch
    log(f"  contraction hierarchy: {ch.forward_arcs:,} forward + {ch.backward_arcs:,} backward arcs ({t_ch:.0f} s)")

    sections = write_gmap(graph, ch, out)
    stats = {
        **graph.stats,
        "nodes": graph.node_count,
        "edges": graph.edge_count,
        "ch_forward_arcs": ch.forward_arcs,
        "ch_backward_arcs": ch.backward_arcs,
        "sections": sections,
        "load_seconds": t_load,
        "ch_seconds": t_ch,
    }
    if chunk_dir is not None:
        stats["chunks"] = write_chunks(out, chunk_dir, chunk_size)
    stats["total_seconds"] = time.time() - t0
    return stats
