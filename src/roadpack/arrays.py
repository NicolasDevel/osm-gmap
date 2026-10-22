"""numpy helpers. np.unique is avoided on large arrays: recent numpy versions may use a hash table that takes
several times the memory of sorting (1 GB for 10 million ids)."""
import numpy as np


def unique(a):
    """Sorted distinct values of a."""
    s = np.sort(a)
    return s[np.concatenate(([True], s[1:] != s[:-1]))] if len(s) else s


def unique_inverse(a):
    """(distinct values, index of each element of a among them)."""
    u = unique(a)
    return u, np.searchsorted(u, a)


def first_occurrences(keys):
    """(distinct keys, position of the first occurrence of each), sorted by key."""
    order = np.argsort(keys, kind="stable")
    s = keys[order]
    group = np.concatenate(([True], s[1:] != s[:-1])) if len(s) else np.zeros(0, bool)
    return s[group], order[group]


def ranges(starts, counts):
    """Concatenation of arange(starts[k], starts[k] + counts[k]) for every k."""
    counts = np.asarray(counts, np.int64)
    offsets = np.repeat(np.cumsum(counts) - counts, counts)
    return np.repeat(np.asarray(starts, np.int64), counts) + (np.arange(int(counts.sum())) - offsets)
