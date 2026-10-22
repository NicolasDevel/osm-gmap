"""The .gmap file: writer/reader round trip, header, sections, SD card chunks and the spatial grid."""
import math
import random

import pytest

from roadpack.ch import build_graph_ch
from roadpack.format import Gmap, join_chunks, write_chunks, write_gmap
from roadpack.format.spec import HEADER, MAGIC, NONE, SCALE, VERSION
from roadpack.geo import local_xy
from roadpack.graph import build_graph
from roadpack.osm import PROFILES, load_roads

from conftest import TOWN_BBOX


@pytest.fixture(scope="module")
def written(town, tmp_path_factory):
    """The in-memory graph, its hierarchy, and the file written from them."""
    graph = build_graph(load_roads(town.osm, TOWN_BBOX, PROFILES["motorcycle"]))
    ch = build_graph_ch(graph, log=lambda _: None)
    path = tmp_path_factory.mktemp("written") / "town.gmap"
    sections = write_gmap(graph, ch, path)
    return graph, ch, path, sections


def test_round_trip_nodes_and_edges(written):
    graph, _, path, _ = written
    g = Gmap(path)
    assert g.node_count == len(graph.nodes) and g.edge_count == len(graph.edges)
    for n, (lat, lon) in enumerate(graph.nodes):
        assert (g.lat[n], g.lon[n]) == (round(lat * SCALE) / SCALE, round(lon * SCALE) / SCALE)
        assert g.first_edge[n] == graph.first_edge[n]
    assert g.first_edge[-1] == g.edge_count  # sentinel
    for i, e in enumerate(graph.edges):
        seg = graph.segments[e.segment]
        assert (g.source[i], g.target[i]) == (e.source, e.target)
        assert (g.length[i], g.weight[i], g.speed[i], g.flags[i]) == (e.length_m, e.weight, e.speed, e.flags)
        assert g.name(i) == seg.way.name
        interior = g.polyline(i)[1:-1]
        expected = seg.interior if e.source == seg.a else seg.interior[::-1]
        assert interior == pytest.approx(expected, abs=1e-7)
        assert (g.geom[i] == NONE) == (not seg.interior)


def test_header_and_sections(written):
    _, ch, path, sections = written
    data = path.read_bytes()
    g = Gmap(path)
    magic, version, header_size = HEADER.unpack_from(data)[:3]
    assert (magic, version, header_size) == (MAGIC, VERSION, 72)
    assert sections["total"] == len(data)
    sizes = g.section_sizes()
    assert sum(sizes.values()) == len(data)
    assert g.ch_fwd_off % 4 == 0
    assert sizes["nodes"] == 12 * (g.node_count + 1) and sizes["edges"] == 28 * g.edge_count
    assert data[g.ch_fwd_off:g.ch_bwd_off] == ch.forward and data[g.ch_bwd_off:] == ch.backward
    assert g.ch_fwd.arc_count == ch.forward_arcs and g.ch_bwd.arc_count == ch.backward_arcs


def test_names_are_stored_once(written):
    _, _, path, _ = written
    g = Gmap(path)
    blob = g.data[g.names_off:g.ch_fwd_off].rstrip(b"\0").split(b"\0")
    assert len(blob) == len(set(blob))


def test_rejects_truncated_or_foreign_files(written, tmp_path):
    _, _, path, _ = written
    data = path.read_bytes()
    for name, content in (("short", data[:-1]), ("magic", b"XMAP" + data[4:]), ("tiny", b"GMAP")):
        bad = tmp_path / f"{name}.gmap"
        bad.write_bytes(content)
        with pytest.raises(ValueError, match="not a valid"):
            Gmap(bad)


@pytest.mark.parametrize("chunk_size", [1000, 4096, 1 << 22])
def test_chunks_round_trip(written, tmp_path, chunk_size):
    _, _, path, _ = written
    data = path.read_bytes()
    count = write_chunks(path, tmp_path / "chunks", chunk_size)
    files = sorted((tmp_path / "chunks").glob("*.bin"))
    assert count == len(files) == math.ceil(len(data) / chunk_size)
    assert all(f.stat().st_size == chunk_size for f in files[:-1])
    assert join_chunks(tmp_path / "chunks") == data
    assert Gmap(tmp_path / "chunks").data == data


def test_rewriting_chunks_removes_stale_ones(written, tmp_path):
    _, _, path, _ = written
    write_chunks(path, tmp_path / "c", 1000)
    write_chunks(path, tmp_path / "c", 1 << 22)
    assert [f.name for f in (tmp_path / "c").glob("*.bin")] == ["0000.bin"]


def test_every_edge_point_is_indexed(moto_town):
    """Each polyline point lies in a grid cell that lists the edge or its twin (the other direction)."""
    g = moto_town
    for e in range(g.edge_count):
        same_segment = {e} | {t for t in g.out_edges(g.target[e]) if g.target[t] == g.source[e]
                              and g.geom[t] == g.geom[e] and g.length[t] == g.length[e]}
        for lat, lon in g.polyline(e):
            row, col = int((lat - g.min_lat) / g.cell), int((lon - g.min_lon) / g.cell)
            assert same_segment & set(g.edges_in_cell(row, col)), (e, lat, lon)


def test_cells_outside_the_grid_are_empty(moto_town):
    g = moto_town
    assert g.edges_in_cell(-1, 0) == [] and g.edges_in_cell(0, g.cols) == []


def test_nearest_node_matches_brute_force(grid_map):
    g = grid_map
    rng = random.Random(7)
    for _ in range(50):
        lat = rng.uniform(g.min_lat, g.max_lat)
        lon = rng.uniform(g.min_lon, g.max_lon)
        dist = lambda n: math.hypot(*local_xy((lat, lon), g.point(n)))
        assert dist(g.nearest_node(lat, lon)) == pytest.approx(min(dist(n) for n in range(g.node_count)))


def test_nearest_node_far_from_roads(moto_town):
    with pytest.raises(ValueError, match="no roads near"):
        moto_town.nearest_node(moto_town.min_lat - 1, moto_town.min_lon - 1)
