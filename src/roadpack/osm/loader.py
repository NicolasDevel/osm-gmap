"""Loading layer: reads an OSM extract and keeps only the ways the vehicle can drive on.

Passes over the file, so memory grows with the road network and not with the whole extract:
  1. ways with a `highway` tag (filtered in C++ by osmium), checked against the vehicle profile;
  2. only the nodes those ways use (an id filter, also in C++), for their coordinates;
  3. turn restrictions (relations tagged type=restriction) that apply to the vehicle.
Everything is kept in flat numpy arrays: a few dozen bytes per road node instead of Python objects.
"""
import array
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import osmium

from ..arrays import unique, unique_inverse
from .profiles import EXCLUDED_SERVICE, HIGHWAYS, Profile, parse_speed

COORD_SCALE = 10_000_000  # osmium stores coordinates as degrees × 1e7 integers, like the .gmap format


@dataclass
class Restrictions:
    """Turn restrictions through a node, by OSM ids: arriving along from_way at via, the vehicle may not continue
    onto to_way (`only` False) or may only continue onto to_way (`only` True)."""
    from_way: np.ndarray  # int64 OSM way ids
    via: np.ndarray       # int64 OSM node ids
    to_way: np.ndarray
    only: np.ndarray      # bool
    skipped: int = 0      # restrictions for the vehicle that this format cannot express (a way as via, several
                          # from/to members)

    @staticmethod
    def empty():
        z = np.zeros(0, np.int64)
        return Restrictions(z, z, z, np.zeros(0, bool))

    def __len__(self):
        return len(self.via)


@dataclass
class RoadNetwork:
    """Drivable ways that touch the bounding box, as flat arrays.

    The nodes of way w are node indices refs[way_start[w]:way_start[w + 1]], in drawing order.
    """
    way_start: np.ndarray   # int64, W + 1
    refs: np.ndarray        # int64 indices into the node arrays
    road_class: np.ndarray  # uint8 per way
    speed: np.ndarray       # uint8 per way, km/h
    oneway: np.ndarray      # int8 per way: 1, -1 or 0 (see Profile.oneway)
    roundabout: np.ndarray  # bool per way
    link: np.ndarray        # bool per way
    name_id: np.ndarray     # int32 per way, index into names or -1
    names: list             # distinct way names
    node_ids: np.ndarray    # int64 OSM id per node, sorted
    lat7: np.ndarray        # int32 degrees × 1e7 per node
    lon7: np.ndarray
    way_ids: np.ndarray = None     # int64 OSM id per way
    restrictions: Restrictions = None

    @property
    def way_count(self):
        return len(self.way_start) - 1

    @property
    def node_count(self):
        return len(self.node_ids)

    def lat(self):
        return self.lat7 / COORD_SCALE

    def lon(self):
        return self.lon7 / COORD_SCALE


def _read_ways(path, profile: Profile):
    """Pass 1: candidate ways (attributes and OSM node ids), before knowing where they are."""
    refs = array.array("q")
    lengths, way_ids = array.array("q"), array.array("q")
    road_class, speed, oneway, flags = array.array("B"), array.array("B"), array.array("b"), array.array("B")
    name_ids, names, name_index = array.array("i"), [], {}
    ways = osmium.FileProcessor(str(path), osmium.osm.WAY).with_filter(osmium.filter.KeyFilter("highway"))
    for w in ways:
        tags = w.tags
        highway = tags.get("highway")
        if highway not in HIGHWAYS:
            continue
        if highway == "service" and tags.get("service") in EXCLUDED_SERVICE:
            continue
        if tags.get("area") == "yes" or not profile.allows(tags):
            continue
        nodes = [n.ref for n in w.nodes]
        if len(nodes) < 2:
            continue
        refs.extend(nodes)
        lengths.append(len(nodes))
        way_ids.append(w.id)
        cls, default_speed = HIGHWAYS[highway]
        road_class.append(cls)
        speed.append(parse_speed(tags.get("maxspeed"), default_speed))
        oneway.append(profile.oneway(tags, highway))
        flags.append((tags.get("junction") in ("roundabout", "circular")) | highway.endswith("_link") << 1)
        name = tags.get("name") or tags.get("ref") or ""
        if not name:
            name_ids.append(-1)
        else:
            if name not in name_index:
                name_index[name] = len(names)
                names.append(name)
            name_ids.append(name_index[name])
    as_np = lambda a, t: np.frombuffer(a, dtype=t) if len(a) else np.zeros(0, t)
    return (as_np(refs, np.int64), as_np(lengths, np.int64), as_np(road_class, np.uint8), as_np(speed, np.uint8),
            as_np(oneway, np.int8), as_np(flags, np.uint8), as_np(name_ids, np.int32), names, as_np(way_ids, np.int64))


def _read_nodes(path, ids):
    """Pass 2: coordinates of the given (sorted, unique) node ids that exist in the file."""
    found, xs, ys = array.array("q"), array.array("i"), array.array("i")
    nodes = osmium.FileProcessor(str(path), osmium.osm.NODE).with_filter(osmium.filter.IdFilter(ids))
    for n in nodes:
        loc = n.location
        if loc.valid():
            found.append(n.id)
            xs.append(loc.x)
            ys.append(loc.y)
    node_ids = np.frombuffer(found, dtype=np.int64) if found else np.zeros(0, np.int64)
    order = np.argsort(node_ids, kind="stable")  # extracts are sorted by id, but do not rely on it
    lon7 = np.frombuffer(xs, dtype=np.int32) if xs else np.zeros(0, np.int32)
    lat7 = np.frombuffer(ys, dtype=np.int32) if ys else np.zeros(0, np.int32)
    return node_ids[order], lat7[order], lon7[order]


def _read_restrictions(path, profile: Profile) -> Restrictions:
    """Pass 3: turn restrictions for the vehicle with a single from way, via node and to way."""
    rows, skipped = [], 0
    relations = osmium.FileProcessor(str(path), osmium.osm.RELATION).with_filter(
        osmium.filter.TagFilter(("type", "restriction")))
    for r in relations:
        value = profile.restriction(r.tags)
        if value is None:
            continue
        members = {"from": [], "via": [], "to": []}
        for m in r.members:
            if m.role in members:
                members[m.role].append((m.type, m.ref))
        f, v, t = members["from"], members["via"], members["to"]
        if not (len(f) == len(v) == len(t) == 1 and f[0][0] == "w" and v[0][0] == "n" and t[0][0] == "w"):
            skipped += 1
            continue
        rows.append((f[0][1], v[0][1], t[0][1], value.startswith("only_")))
    if not rows:
        empty = Restrictions.empty()
        empty.skipped = skipped
        return empty
    cols = list(zip(*rows))
    return Restrictions(np.array(cols[0], np.int64), np.array(cols[1], np.int64), np.array(cols[2], np.int64),
                        np.array(cols[3], bool), skipped)


def load_roads(path: Path, bbox, profile: Profile, restrictions=True) -> RoadNetwork:
    """Drivable ways of an .osm.pbf (or .osm/.osm.bz2) that have at least one node inside bbox.

    bbox is (min_lat, min_lon, max_lat, max_lon). Ways that cross the border are kept whole, so routes
    leaving the region do not end abruptly at its edge. Nodes missing from the extract are skipped.
    """
    osm_refs, lengths, road_class, speed, oneway, flags, name_id, names, way_ids = _read_ways(path, profile)
    node_ids, lat7, lon7 = _read_nodes(path, unique(osm_refs))

    # Resolve OSM ids to node indices; drop references to nodes the extract does not have.
    way_of = np.repeat(np.arange(len(lengths)), lengths)
    idx = np.searchsorted(node_ids, osm_refs)
    present = idx < len(node_ids)
    present[present] = node_ids[idx[present]] == osm_refs[present]
    idx, way_of = idx[present], way_of[present]
    lengths = np.bincount(way_of, minlength=len(lengths))

    # Keep the ways with at least two nodes and one of them inside the box.
    min_lat, min_lon, max_lat, max_lon = bbox
    lat, lon = lat7[idx] / COORD_SCALE, lon7[idx] / COORD_SCALE
    inside = (min_lat <= lat) & (lat <= max_lat) & (min_lon <= lon) & (lon <= max_lon)
    keep_way = (np.bincount(way_of, weights=inside, minlength=len(lengths)) > 0) & (lengths >= 2)
    keep_ref = keep_way[way_of]
    idx = idx[keep_ref]

    # Only the nodes the kept ways use.
    used, refs = unique_inverse(idx)
    lengths = lengths[keep_way]
    way_start = np.zeros(len(lengths) + 1, np.int64)
    np.cumsum(lengths, out=way_start[1:])
    flags = flags[keep_way]
    return RoadNetwork(
        way_start=way_start, refs=refs.astype(np.int64), road_class=road_class[keep_way], speed=speed[keep_way],
        oneway=oneway[keep_way], roundabout=(flags & 1).astype(bool), link=(flags & 2).astype(bool),
        name_id=name_id[keep_way], names=names, node_ids=node_ids[used], lat7=lat7[used], lon7=lon7[used],
        way_ids=way_ids[keep_way],
        restrictions=_read_restrictions(path, profile) if restrictions else Restrictions.empty(),
    )
