"""Turn-by-turn maneuvers of a route (arrow + distance, Beeline style): only at junctions where the rider has
to decide something.
"""
import math
from dataclasses import dataclass

from ..format.reader import Gmap
from ..format.spec import FLAG_LINK
from ..geo import bearing, local_xy

# Turn thresholds in degrees (positive = right).
STRAIGHT_DEG = 20
SLIGHT_DEG = 45
TURN_DEG = 135
SHARP_DEG = 170
BEARING_SAMPLE_M = 15  # how far from a junction the incoming and outgoing bearings are measured


def _walk(points, distance):
    """Point `distance` meters along the polyline (or its last point if it is shorter)."""
    for a, b in zip(points, points[1:]):
        seg = math.hypot(*local_xy(a, b))
        if seg >= distance:
            t = distance / seg if seg else 0
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        distance -= seg
    return points[-1]


def leaving_bearing(gmap, e):
    pts = gmap.polyline(e)
    return bearing(pts[0], _walk(pts, BEARING_SAMPLE_M))


def arriving_bearing(gmap, e):
    pts = gmap.polyline(e)[::-1]
    return bearing(_walk(pts, BEARING_SAMPLE_M), pts[0])


def turn_angle(in_bearing, out_bearing):
    """Turn in degrees in (-180, 180]: positive to the right, negative to the left."""
    a = (out_bearing - in_bearing + 180) % 360 - 180
    return 180.0 if a == -180 else a


@dataclass
class Maneuver:
    kind: str          # depart, straight, slight, turn, sharp, uturn, roundabout, arrive
    side: str          # left, right or "" (straight, depart, arrive)
    angle: float       # turn in degrees (positive = right)
    node: int          # junction where the maneuver happens
    edge_index: int    # position in the route of the edge leaving the junction
    at_m: float        # distance from the start of the route
    street: str        # road being turned into
    exit_number: int = 0  # roundabouts: exit to take

    def text(self):
        street = f" onto {self.street}" if self.street else ""
        if self.kind == "depart":
            return f"Head out{street}"
        if self.kind == "arrive":
            return "You have arrived"
        if self.kind == "roundabout":
            n = self.exit_number
            suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
            return f"At the roundabout, take the {n}{suffix} exit{street}"
        if self.kind == "uturn":
            return f"Make a U-turn{street}"
        verb = {"straight": "Continue straight", "slight": "Keep", "turn": "Turn", "sharp": "Turn sharp"}[self.kind]
        return f"{verb} {self.side}{street}".replace("  ", " ")


def _classify(angle):
    side = "right" if angle > 0 else "left"
    a = abs(angle)
    if a < STRAIGHT_DEG:
        return "straight", ""
    if a < SLIGHT_DEG:
        return "slight", side
    if a < TURN_DEG:
        return "turn", side
    if a < SHARP_DEG:
        return "sharp", side
    return "uturn", side


def _same_road(gmap, a, b):
    """The same exit of a junction: an edge and its copy (turn restrictions) share geometry, length and ends."""
    o = gmap.original
    return a == b or (gmap.geom[a] == gmap.geom[b] and gmap.length[a] == gmap.length[b]
                      and o(gmap.target[a]) == o(gmap.target[b]) and o(gmap.source[a]) == o(gmap.source[b]))


def maneuvers(gmap: Gmap, path):
    """Maneuvers of a route given as a list of edges, from "depart" to "arrive"."""
    result = [Maneuver("depart", "", 0, gmap.original(gmap.source[path[0]]), 0, 0, gmap.name(path[0]))]
    at = 0.0
    i = 0
    while i < len(path) - 1:
        e_in, e_out = path[i], path[i + 1]
        at += gmap.length[e_in]
        node = gmap.original(gmap.target[e_in])
        came_from = gmap.original(gmap.source[e_in])
        # Exits of the junction itself, not of the copy the route goes through (turn restrictions): a forbidden
        # exit is still a street the rider sees.
        options = [e for e in gmap.out_edges(node) if gmap.original(gmap.target[e]) != came_from]
        in_b = arriving_bearing(gmap, e_in)

        # Entering a roundabout: a single instruction with the exit number.
        if gmap.is_roundabout(e_out) and not gmap.is_roundabout(e_in):
            exits, j = 0, i + 1
            while j < len(path) - 1 and gmap.is_roundabout(path[j]):
                n = gmap.original(gmap.target[path[j]])
                if any(not gmap.is_roundabout(e) for e in gmap.out_edges(n)):
                    exits += 1
                j += 1
            exit_edge = path[min(j, len(path) - 1)]
            angle = turn_angle(in_b, leaving_bearing(gmap, exit_edge))
            result.append(Maneuver("roundabout", "", angle, node, i + 1, at, gmap.name(exit_edge), max(exits, 1)))
            for k in range(i + 1, j):
                at += gmap.length[path[k]]
            i = j
            continue

        if len(options) > 1:
            angle = turn_angle(in_b, leaving_bearing(gmap, e_out))
            kind, side = _classify(angle)
            same_road = gmap.name(e_out) == gmap.name(e_in) and not gmap.flags[e_out] & FLAG_LINK
            if kind == "straight" and not same_road:
                # A fork: if another exit also goes almost straight, say which side to keep.
                # Going straight along the same road (even with side carriageways leaving) needs no instruction.
                rivals = [turn_angle(in_b, leaving_bearing(gmap, e)) for e in options if not _same_road(gmap, e, e_out)]
                close = [r for r in rivals if abs(r) < SLIGHT_DEG]
                if close:
                    kind, side = "slight", "right" if angle > min(close, key=abs) else "left"
            if kind != "straight":
                result.append(Maneuver(kind, side, angle, node, i + 1, at, gmap.name(e_out)))
        i += 1

    at += gmap.length[path[-1]]
    result.append(Maneuver("arrive", "", 0, gmap.original(gmap.target[path[-1]]), len(path), at, ""))
    return result
