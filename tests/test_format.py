"""The .gmap file: writer/reader round trip, header, sections, SD card chunks and the spatial grid."""
import math
import random

import pytest

from roadpack.ch import build_graph_ch
from roadpack.format import Gmap, join_chunks, write_chunks, write_gmap
from roadpack.format.spec import HEADER, HEADER_V2, MAGIC, NONE, SCALE, VERSION
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
    assert g.node_count == graph.node_count and g.edge_count == graph.edge_count
    assert g.lat.tolist()[:-1] == (graph.lat7 / SCALE).tolist()  # the reader includes the sentinel
    assert g.lon.tolist()[:-1] == (graph.lon7 / SCALE).tolist()
    assert g.first_edge.tolist() == graph.first_edge.tolist() and g.first_edge[-1] == g.edge_count
    for column, expected in ((g.source, graph.source), (g.target, graph.target), (g.length, graph.length_m),
                             (g.weight, graph.weight), (g.speed, graph.speed), (g.flags, graph.flags)):
        assert column.tolist() == expected.tolist()
    for i, s in enumerate(graph.segment.tolist()):
        n = graph.seg_name[s]
        assert g.name(i) == (graph.names[n] if n >= 0 else "")
        interior = graph.interior(s)
        expected = interior if graph.source[i] == graph.seg_a[s] else interior[::-1]
        flat = [c for point in g.polyline(i)[1:-1] for c in point]  # approx() rejects nested sequences (pytest 9.2)
        assert flat == pytest.approx([c for point in expected for c in point], abs=1e-7)
        assert (g.geom[i] == NONE) == (not interior)


def test_osm_ids_follow_the_nodes(town, written):
    graph = written[0]
    # The OSM builder numbers nodes in creation order; "A" is the first node of the town.
    a = next(i for i, (lat, lon) in enumerate(zip(graph.lat7, graph.lon7))
             if (lat / SCALE, lon / SCALE) == pytest.approx(town.points["A"], abs=1e-7))
    assert graph.osm_ids[a] == 1


def test_header_and_sections(written):
    _, ch, path, sections = written
    data = path.read_bytes()
    g = Gmap(path)
    magic, version, header_size = HEADER.unpack_from(data)[:3]
    assert (magic, version, header_size) == (MAGIC, VERSION, 80)
    assert sections["total"] == len(data)
    sizes = g.section_sizes()
    assert sum(sizes.values()) == len(data)
    assert g.ch_fwd_off % 4 == 0
    assert sizes["nodes"] == 12 * (g.node_count + 1) and sizes["edges"] == 28 * g.edge_count
    assert data[g.ch_fwd_off:g.ch_bwd_off] == ch.forward and data[g.ch_bwd_off:g.copies_off] == ch.backward
    assert g.copy_count == 0 and g.copies_off == len(data)  # no turn restrictions in this file
    assert g.ch_fwd.arc_count == ch.forward_arcs and g.ch_bwd.arc_count == ch.backward_arcs


def test_reads_version_2(written, tmp_path):
    """A v2 file is a v3 one without the two trailing header fields (and without junction copies)."""
    _, _, path, _ = written
    data = path.read_bytes()
    fields = list(HEADER.unpack_from(data))
    assert fields[-1] == 0  # no copies
    v2 = fields[:20]
    v2[1], v2[2] = 2, HEADER_V2.size
    v2[12:20] = [off - (HEADER.size - HEADER_V2.size) for off in v2[12:20]]  # section offsets and file size
    old = tmp_path / "v2.gmap"
    old.write_bytes(HEADER_V2.pack(*v2) + data[HEADER.size:])
    g, g3 = Gmap(old), Gmap(path)
    assert g.version == 2 and g.copy_count == 0 and g.node_count == g3.node_count
    assert g.polyline(5) == g3.polyline(5) and g.ch_bwd.arc_count == g3.ch_bwd.arc_count
    assert [g.original(n) for n in range(g.node_count)] == list(range(g.node_count))


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


def _grid_xy(g, lat, lon):
    return (lon - g.min_lon) / g.cell, (lat - g.min_lat) / g.cell


@pytest.fixture(scope="module")
def diagonal_map(tmp_path_factory):
    """Long diagonal and curved roads: their bounding boxes cover many cells they never touch."""
    from osm_builder import LAT0, LON0, OsmBuilder
    from roadpack.pipeline import build
    o = OsmBuilder()
    o.way([o.node(LAT0, LON0), o.node(LAT0 + 0.012, LON0 + 0.009)], highway="primary", name="Diagonal")
    arc = [o.node(LAT0 + 0.006 * math.sin(a / 10), LON0 - 0.006 * math.cos(a / 10)) for a in range(32)]
    o.way(arc, highway="secondary", name="Curve")
    tmp = tmp_path_factory.mktemp("diagonal")
    out = tmp / "diagonal.gmap"
    build(o.write(tmp / "diagonal.osm"), (LAT0 - 0.02, LON0 - 0.02, LAT0 + 0.02, LON0 + 0.02), PROFILES["motorcycle"],
          out, log=lambda _: None)
    return Gmap(out)


@pytest.mark.parametrize("which", ["town", "grid", "diagonal"])
def test_grid_lists_the_cells_a_segment_crosses_and_no_more(which, moto_town, grid_map, diagonal_map):
    """Every cell the geometry passes through lists the segment (away from cell borders: the stored geometry is
    simplified by up to 2 m), and every listed cell is within a third of a cell of it (not its whole bounding box)."""
    g = {"town": moto_town, "grid": grid_map, "diagonal": diagonal_map}[which]
    margin = 3 / (g.cell * 111_000)  # 3 m in cells
    listed = {}
    for cid in g.cell_ids.tolist():
        for e in g.edges_in_cell(cid // g.cols, cid % g.cols):
            listed.setdefault(e, set()).add(cid)
    for e, cells in listed.items():
        pts = [_grid_xy(g, lat, lon) for lat, lon in g.polyline(e)]
        samples = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 0.01))
            samples += [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n + 1)]
        for x, y in samples:
            near_border = min(x % 1, 1 - x % 1, y % 1, 1 - y % 1) < margin
            assert near_border or int(y) * g.cols + int(x) in cells, (e, x, y)
        for cid in cells:
            r, c = divmod(cid, g.cols)
            gap = min(math.hypot(max(c - x, 0, x - c - 1), max(r - y, 0, y - r - 1)) for x, y in samples)
            assert gap < 1 / 3, (e, cid, gap)


def test_grid_built_in_batches_is_identical(town, tmp_path, monkeypatch):
    """The grid is computed in batches of segments to bound memory: tiny batches give the same file byte by byte."""
    from roadpack.graph import build as graph_build
    from roadpack.pipeline import build
    out = {}
    for batch in (graph_build.GRID_BATCH, 3):
        monkeypatch.setattr(graph_build, "GRID_BATCH", batch)
        out[batch] = tmp_path / f"town-{batch}.gmap"
        build(town.osm, TOWN_BBOX, PROFILES["motorcycle"], out[batch], log=lambda _: None)
    assert out[3].read_bytes() == out[graph_build.GRID_BATCH].read_bytes()


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
