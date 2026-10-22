import math

import pytest

from roadpack.geo import bearing, haversine_m, local_xy, morton, simplify


def test_haversine_one_degree_of_latitude():
    assert haversine_m((0, 0), (1, 0)) == pytest.approx(111_195, rel=1e-3)


def test_local_xy_matches_haversine_at_city_scale():
    a, b = (4.60, -74.10), (4.61, -74.09)
    assert math.hypot(*local_xy(a, b)) == pytest.approx(haversine_m(a, b), rel=5e-3)


@pytest.mark.parametrize("dlat, dlon, expected", [(1, 0, 0), (0, 1, 90), (-1, 0, 180), (0, -1, 270)])
def test_bearing(dlat, dlon, expected):
    assert bearing((4.6, -74.1), (4.6 + dlat * 1e-3, -74.1 + dlon * 1e-3)) == pytest.approx(expected)


def test_simplify_keeps_endpoints_and_drops_collinear_points():
    line = [(4.6, -74.1 + i * 1e-4) for i in range(10)]
    assert simplify(line, 2.0) == [line[0], line[-1]]


def test_simplify_keeps_points_that_deviate_more_than_the_tolerance():
    bump = (4.6 + 5e-5, -74.0995)  # ~5.5 m off the line
    line = [(4.6, -74.1), bump, (4.6, -74.099)]
    assert simplify(line, 2.0) == line
    assert simplify(line, 10.0) == [line[0], line[-1]]


def test_simplify_short_lines_untouched():
    assert simplify([(1, 2)], 2.0) == [(1, 2)]
    assert simplify([(1, 2), (3, 4)], 2.0) == [(1, 2), (3, 4)]


def test_morton_interleaves_bits():
    assert [morton(0, c) for c in range(4)] == [0, 1, 4, 5]
    assert [morton(r, 0) for r in range(4)] == [0, 2, 8, 10]
    assert morton(1, 1) == 3


def test_morton_is_injective_on_a_block():
    codes = {morton(r, c) for r in range(64) for c in range(64)}
    assert len(codes) == 64 * 64 and max(codes) == 64 * 64 - 1
