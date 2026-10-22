"""The roadpack command, end to end."""
import json

import pytest

from roadpack.cli import main

from conftest import TOWN_BBOX

BBOX = ",".join(str(v) for v in TOWN_BBOX)


@pytest.fixture(scope="module")
def built(town, tmp_path_factory):
    out = tmp_path_factory.mktemp("cli") / "town.gmap"
    main(["build", str(town.osm), "--bbox", BBOX, "-o", str(out), "--stats-json", str(out.with_suffix(".json"))])
    return out


def test_build_writes_the_map_chunks_and_stats(built):
    assert built.exists()
    assert sorted(p.name for p in built.with_suffix("").glob("*.bin")) == ["0000.bin"]
    stats = json.loads(built.with_suffix(".json").read_text())
    assert stats["sections"]["total"] == built.stat().st_size


def test_build_summary(town, tmp_path, capsys):
    main(["build", str(town.osm), "--bbox", BBOX, "-o", str(tmp_path / "m.gmap"), "--no-chunks",
          "--profile", "car"])
    out = capsys.readouterr().out
    assert "profile car" in out and "directed edges" in out and "ch_forward" in out
    assert not (tmp_path / "m").exists()


def test_info_json(built, capsys):
    main(["info", str(built), "--json"])
    info = json.loads(capsys.readouterr().out)
    assert info["size"] == built.stat().st_size
    assert sum(info["sections"].values()) == info["size"]
    assert set(info["edges_by_class"]) <= {"trunk", "primary", "secondary", "residential"}


def test_info_reads_a_chunk_directory(built, capsys):
    main(["info", str(built.with_suffix(""))])
    assert "nodes" in capsys.readouterr().out


def test_route_check_and_images(town, built, tmp_path, capsys):
    a, d = town.points["A"], town.points["north_exit"]
    main(["route", str(built), "--from", f"{a[0]},{a[1]}", "--to", f"{d[0]},{d[1]}", "--check",
          "--images", str(tmp_path / "img")])
    out = capsys.readouterr().out
    assert "same cost" in out and "3rd exit" in out and "You have arrived" in out
    assert (tmp_path / "img" / "route.png").exists()
    assert len(list((tmp_path / "img").glob("screen_*.png"))) >= 2


@pytest.mark.parametrize("argv, message", [
    (["info", "missing.gmap"], "roadpack: "),
    (["route", "{map}", "--from", "0,0", "--to", "4.6,-74.1"], "no roads near"),
])
def test_errors_are_short_messages(built, argv, message):
    with pytest.raises(SystemExit) as exc:
        main([a.replace("{map}", str(built)) for a in argv])
    assert message in str(exc.value)


def test_empty_area(town, tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["build", str(town.osm), "--bbox", "-1,-1,-0.9,-0.9", "-o", str(tmp_path / "x.gmap")])
    assert "no drivable roads" in str(exc.value)


def test_southern_and_western_coordinates_parse(tmp_path):
    # Values starting with "-" must not be taken for options (Lima, Santiago, Buenos Aires...).
    with pytest.raises(SystemExit) as exc:
        main(["route", str(tmp_path / "none.gmap"), "--from", "-12.05,-77.04", "--to", "-12.1,-77.0"])
    assert "roadpack: " in str(exc.value)  # got as far as opening the file


@pytest.mark.parametrize("argv", [
    ["build", "x.pbf", "-o", "x.gmap"],                                  # no area
    ["build", "x.pbf", "-o", "x.gmap", "--bbox", "1,2,3"],               # bad bbox
    ["build", "x.pbf", "-o", "x.gmap", "--bbox", "5,0,4,1"],             # min > max
    ["build", "x.pbf", "-o", "x.gmap", "--region", "bogota", "--bbox", "0,0,1,1"],
    ["route", "x.gmap", "--from", "4.6", "--to", "4.6,-74"],
])
def test_bad_arguments(argv):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2


def test_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("roadpack ")
