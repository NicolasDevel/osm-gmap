from roadpack.graph import split_into_segments
from roadpack.osm import Way


def way(*refs):
    return Way(list(refs), road_class=6, speed=25, oneway=0, roundabout=False, link=False, name="")


def refs_of(segments):
    return [seg for seg, _ in segments]


def test_single_way_is_one_segment():
    assert refs_of(split_into_segments([way(1, 2, 3, 4)])) == [[1, 2, 3, 4]]


def test_ways_are_split_at_shared_nodes():
    segs = split_into_segments([way(1, 2, 3, 4, 5), way(10, 3, 11)])
    assert refs_of(segs) == [[1, 2, 3], [3, 4, 5], [10, 3], [3, 11]]


def test_ways_meeting_at_endpoints_are_not_split_further():
    assert refs_of(split_into_segments([way(1, 2, 3), way(3, 4, 5)])) == [[1, 2, 3], [3, 4, 5]]


def test_closed_way_is_split_in_half():
    # A loop hanging from node 1: both halves share the middle node, so the loop can be driven through.
    segs = split_into_segments([way(0, 1), way(1, 2, 3, 4, 1)])
    assert refs_of(segs) == [[0, 1], [1, 2, 3], [3, 4, 1]]


def test_self_intersection_is_a_node():
    # A "lollipop": the way comes back through node 2.
    assert refs_of(split_into_segments([way(1, 2, 3, 4, 2)])) == [[1, 2], [2, 3, 4], [4, 2]]


def test_degenerate_two_point_loop_is_dropped():
    assert refs_of(split_into_segments([way(1, 2), way(2, 2)])) == [[1, 2]]
