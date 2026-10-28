"""Builds small synthetic OpenStreetMap files (.osm XML) for the tests."""
import random
from xml.sax.saxutils import quoteattr

# Around Bogotá: one degree of latitude ≈ 110.5 km, so 0.0009° ≈ 100 m.
LAT0, LON0 = 4.60, -74.10
STEP = 0.0009


class OsmBuilder:
    def __init__(self):
        self.nodes = {}  # id -> (lat, lon)
        self.ways = []   # (id, node ids, tags)
        self.relations = []  # (id, [(type, ref, role)], tags)

    def node(self, lat, lon):
        nid = len(self.nodes) + 1
        self.nodes[nid] = (round(lat, 7), round(lon, 7))
        return nid

    def way(self, refs, **tags):
        """Add a way; tag names with a colon are written with a double underscore (oneway__motorcycle)."""
        wid = len(self.ways) + 1
        self.ways.append((wid, list(refs), {k.replace("__", ":"): str(v) for k, v in tags.items()}))
        return wid

    def restriction(self, kind, from_way, via, to_way, via_type="node", **tags):
        """A turn restriction relation: from way, via node (or way), to way."""
        rid = len(self.relations) + 1
        members = [("way", from_way, "from"), (via_type, via, "via"), ("way", to_way, "to")]
        tags = {"type": "restriction", "restriction": kind, **{k.rstrip("_").replace("__", ":"): str(v) for k, v in tags.items()}}
        self.relations.append((rid, members, {k: v for k, v in tags.items() if v != "None"}))
        return rid

    def write(self, path):
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6" generator="roadpack-tests">']
        for nid, (lat, lon) in self.nodes.items():
            lines.append(f'  <node id="{nid}" version="1" lat="{lat}" lon="{lon}"/>')
        for wid, refs, tags in self.ways:
            lines.append(f'  <way id="{wid}" version="1">')
            lines += [f'    <nd ref="{r}"/>' for r in refs]
            lines += [f'    <tag k={quoteattr(k)} v={quoteattr(v)}/>' for k, v in tags.items()]
            lines.append("  </way>")
        for rid, members, tags in self.relations:
            lines.append(f'  <relation id="{rid}" version="1">')
            lines += [f'    <member type="{t}" ref="{r}" role="{role}"/>' for t, r, role in members]
            lines += [f'    <tag k={quoteattr(k)} v={quoteattr(v)}/>' for k, v in tags.items()]
            lines.append("  </relation>")
        lines.append("</osm>")
        path.write_text("\n".join(lines) + "\n")
        return path


def grid_network(size=6, seed=1):
    """A size × size grid of streets (100 m blocks) with random one-ways, speeds and road classes.
    The outer ring stays two-way; one-ways on inner streets may leave some pairs without a route."""
    rng = random.Random(seed)
    osm = OsmBuilder()
    ids = [[osm.node(LAT0 + r * STEP, LON0 + c * STEP) for c in range(size)] for r in range(size)]
    highways = ["primary", "secondary", "tertiary", "residential", "residential", "unclassified"]

    def street(refs, name, outer):
        tags = {"highway": rng.choice(highways), "name": name}
        if rng.random() < 0.5:
            tags["maxspeed"] = str(rng.choice([20, 30, 40, 60]))
        if not outer and rng.random() < 0.4:
            tags["oneway"] = rng.choice(["yes", "-1"])
        osm.way(refs, **tags)

    for r in range(size):  # each row and column is split into one way per block
        for c in range(size - 1):
            street([ids[r][c], ids[r][c + 1]], f"Calle {r}", r in (0, size - 1))
            street([ids[c][r], ids[c + 1][r]], f"Carrera {r}", r in (0, size - 1))
    return osm, ids
