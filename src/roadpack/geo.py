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


def simplify(points, tolerance_m):
    """Douglas-Peucker in meters (local equirectangular projection). Always keeps both endpoints."""
    if len(points) <= 2:
        return points
    k = math.cos(math.radians(points[0][0]))
    xy = [(lon * k * 111_320, lat * 110_540) for lat, lon in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-9
        best, best_d = -1, tolerance_m
        for m in range(i + 1, j):
            d = abs(dy * (xy[m][0] - x1) - dx * (xy[m][1] - y1)) / norm
            if d > best_d:
                best, best_d = m, d
        if best >= 0:
            keep[best] = True
            stack += [(i, best), (best, j)]
    return [p for p, k_ in zip(points, keep) if k_]


def morton(row, col):
    """Z-order curve index: interleaves the bits of row and column (16 bits each)."""
    z = 0
    for bit in range(16):
        z |= ((col >> bit) & 1) << (2 * bit) | ((row >> bit) & 1) << (2 * bit + 1)
    return z
