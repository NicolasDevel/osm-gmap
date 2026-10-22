import numpy as np

from roadpack.arrays import first_occurrences, ranges, unique, unique_inverse
from roadpack.graph import split_into_segments


def split(*ways):
    """Segments of these ways (lists of node indices), as lists of node indices."""
    refs = np.array([r for w in ways for r in w], np.int64)
    way_start = np.cumsum([0] + [len(w) for w in ways])
    starts, ends = split_into_segments(way_start, refs)
    return [refs[s:e + 1].tolist() for s, e in zip(starts, ends)]


def test_single_way_is_one_segment():
    assert split([1, 2, 3, 4]) == [[1, 2, 3, 4]]


def test_ways_are_split_at_shared_nodes():
    assert split([1, 2, 3, 4, 5], [10, 3, 11]) == [[1, 2, 3], [3, 4, 5], [10, 3], [3, 11]]


def test_ways_meeting_at_endpoints_are_not_split_further():
    assert split([1, 2, 3], [3, 4, 5]) == [[1, 2, 3], [3, 4, 5]]


def test_closed_way_is_split_in_half():
    # A loop hanging from node 1: both halves share the middle node, so the loop can be driven through.
    assert split([0, 1], [1, 2, 3, 4, 1]) == [[0, 1], [1, 2, 3], [3, 4, 1]]


def test_self_intersection_is_a_node():
    # A "lollipop": the way comes back through node 2.
    assert split([1, 2, 3, 4, 2]) == [[1, 2], [2, 3, 4], [4, 2]]


def test_degenerate_two_point_loop_is_dropped():
    assert split([1, 2], [2, 2]) == [[1, 2]]


def test_no_ways():
    assert split() == []


def test_array_helpers():
    a = np.array([5, 3, 5, 1, 3, 9])
    assert unique(a).tolist() == [1, 3, 5, 9]
    u, inv = unique_inverse(a)
    assert u[inv].tolist() == a.tolist()
    keys, first = first_occurrences(a)
    assert keys.tolist() == [1, 3, 5, 9] and first.tolist() == [3, 1, 0, 5]
    assert ranges([10, 20, 30], [2, 0, 3]).tolist() == [10, 11, 30, 31, 32]
    assert unique(np.zeros(0, np.int64)).tolist() == []


def reference_split(ways):
    """The original pure-Python algorithm, kept as the specification of split_into_segments."""
    from collections import Counter
    usage = Counter()
    for refs in ways:
        usage.update(refs)
        usage[refs[0]] += 1
        usage[refs[-1]] += 1
    out = []
    for refs in ways:
        start = 0
        for i in range(1, len(refs)):
            if usage[refs[i]] < 2:
                continue
            seg = refs[start:i + 1]
            start = i
            if seg[0] == seg[-1]:
                if len(seg) >= 3:
                    mid = len(seg) // 2
                    out += [seg[:mid + 1], seg[mid:]]
            else:
                out.append(seg)
    return out


def test_split_matches_the_reference_on_random_ways():
    rng = np.random.default_rng(3)
    for _ in range(200):
        ways = [rng.integers(0, 30, rng.integers(2, 12)).tolist() for _ in range(rng.integers(1, 15))]
        assert split(*ways) == reference_split(ways)


def neumaier(xs):
    """Python 3.12's sum() of floats, written out so the test does not depend on the Python version."""
    f = c = 0.0
    for x in xs:
        t = f + x
        c += (f - t) + x if abs(f) >= abs(x) else (x - t) + f
        f = t
    return f + c


def test_lengths_are_summed_like_python():
    from roadpack.graph.build import _sequential_sums
    rng = np.random.default_rng(5)
    values = rng.random(5000) * 10 ** rng.uniform(-3, 4, 5000)
    offsets = np.concatenate(([0], np.cumsum(rng.integers(1, 60, 200))))
    offsets = offsets[offsets <= len(values)]
    sums = _sequential_sums(values, offsets)
    assert sums.tolist() == [neumaier(values[a:b].tolist()) for a, b in zip(offsets, offsets[1:])]
