"""Small geodesy helpers. Flat-earth approximations are fine at the scale of a road segment or a junction."""
import math


def haversine_m(a, b):
    """Great-circle distance in meters between two (lat, lon) points."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def local_xy(origin, point):
    """Meters (east, north) of point relative to origin."""
    k = math.cos(math.radians(origin[0]))
    return (point[1] - origin[1]) * 111_320 * k, (point[0] - origin[0]) * 110_540


def bearing(a, b):
    """Bearing from a to b in degrees: 0 = north, 90 = east."""
    x, y = local_xy(a, b)
    return math.degrees(math.atan2(x, y)) % 360


def simplify_indices(lats, lons, tolerance_m):
    """Douglas-Peucker in meters (local equirectangular projection): indices of the points to keep, in order.
    Always keeps both endpoints."""
    n = len(lats)
    if n <= 2:
        return list(range(n))
    k = math.cos(math.radians(lats[0]))
    xs = [lon * k * 111_320 for lon in lons]
    ys = [lat * 110_540 for lat in lats]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        x1, y1, x2, y2 = xs[i], ys[i], xs[j], ys[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        best, best_d = -1, tolerance_m
        for m in range(i + 1, j):
            d = abs(dy * (xs[m] - x1) - dx * (ys[m] - y1)) / norm
            if d > best_d:
                best, best_d = m, d
        if best >= 0:
            keep[best] = True
            stack += [(i, best), (best, j)]
    return [i for i in range(n) if keep[i]]


def simplify(points, tolerance_m):
    """Douglas-Peucker on [(lat, lon)]; see simplify_indices."""
    return [points[i] for i in simplify_indices([p[0] for p in points], [p[1] for p in points], tolerance_m)]


def morton(row, col):
    """Z-order curve index: interleaves the bits of row and column (16 bits each)."""
    z = 0
    for bit in range(16):
        z |= ((col >> bit) & 1) << (2 * bit) | ((row >> bit) & 1) << (2 * bit + 1)
    return z
