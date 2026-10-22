import pytest

from roadpack.osm import PROFILES
from roadpack.osm.profiles import parse_speed

MOTO, CAR = PROFILES["motorcycle"], PROFILES["car"]


@pytest.mark.parametrize("tags, moto, car", [
    ({}, True, True),
    ({"access": "private"}, False, False),
    ({"access": "no", "motor_vehicle": "yes"}, True, True),  # the more specific tag wins
    ({"motorcycle": "no"}, False, True),
    ({"motorcar": "no"}, True, False),
    ({"vehicle": "agricultural"}, False, False),
    ({"access": "destination"}, True, True),
])
def test_access(tags, moto, car):
    assert MOTO.allows(tags) is moto
    assert CAR.allows(tags) is car


@pytest.mark.parametrize("tags, highway, expected", [
    ({}, "residential", 0),
    ({"oneway": "yes"}, "residential", 1),
    ({"oneway": "1"}, "residential", 1),
    ({"oneway": "-1"}, "residential", -1),
    ({"oneway": "no"}, "motorway", 0),
    ({}, "motorway", 1),
    ({}, "motorway_link", 1),
    ({"junction": "roundabout"}, "primary", 1),
    ({"junction": "circular"}, "primary", 1),
    ({"oneway": "yes", "oneway:motorcycle": "no"}, "residential", 0),
])
def test_oneway_motorcycle(tags, highway, expected):
    assert MOTO.oneway(tags, highway) == expected


def test_vehicle_specific_oneway_only_applies_to_its_vehicle():
    tags = {"oneway": "yes", "oneway:motorcycle": "no"}
    assert MOTO.oneway(tags, "residential") == 0
    assert CAR.oneway(tags, "residential") == 1


@pytest.mark.parametrize("value, expected", [
    (None, 30), ("", 30), ("50", 50), ("30 mph", 48), ("60;80", 60), ("signals", 30),
    ("2", 5), ("300", 120), ("RU:urban", 30),
])
def test_parse_speed(value, expected):
    assert parse_speed(value, 30) == expected
