"""Loading layer: reads an OSM extract and keeps only the ways the vehicle can drive on."""
from dataclasses import dataclass, field
from pathlib import Path

import osmium

from .profiles import EXCLUDED_SERVICE, HIGHWAYS, Profile, parse_speed


@dataclass
class Way:
    refs: list          # OSM node ids, in drawing order
    road_class: int
    speed: int          # km/h
    oneway: int         # 1, -1 or 0 (see Profile.oneway)
    roundabout: bool
    link: bool
    name: str


@dataclass
class RoadNetwork:
    """Drivable ways that touch the bounding box, with the coordinates of every node they use."""
    ways: list = field(default_factory=list)
    coords: dict = field(default_factory=dict)  # OSM node id -> (lat, lon)


class _Collector(osmium.SimpleHandler):
    def __init__(self, bbox, profile: Profile):
        super().__init__()
        self.profile = profile
        self.min_lat, self.min_lon, self.max_lat, self.max_lon = bbox
        self.network = RoadNetwork()

    def way(self, w):
        tags = w.tags
        highway = tags.get("highway")
        if highway not in HIGHWAYS:
            return
        if highway == "service" and tags.get("service") in EXCLUDED_SERVICE:
            return
        if tags.get("area") == "yes" or not self.profile.allows(tags):
            return

        refs, points, inside = [], [], False
        for n in w.nodes:
            loc = n.location
            if not loc.valid():
                continue
            lat, lon = loc.lat, loc.lon
            if not inside and self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon:
                inside = True
            refs.append(n.ref)
            points.append((lat, lon))
        if not inside or len(refs) < 2:
            return

        self.network.coords.update(zip(refs, points))
        road_class, default_speed = HIGHWAYS[highway]
        self.network.ways.append(Way(
            refs=refs,
            road_class=road_class,
            speed=parse_speed(tags.get("maxspeed"), default_speed),
            oneway=self.profile.oneway(tags, highway),
            roundabout=tags.get("junction") in ("roundabout", "circular"),
            link=highway.endswith("_link"),
            name=tags.get("name") or tags.get("ref") or "",
        ))


def load_roads(path: Path, bbox, profile: Profile) -> RoadNetwork:
    """Drivable ways of an .osm.pbf (or .osm/.osm.bz2) that have at least one node inside bbox.

    bbox is (min_lat, min_lon, max_lat, max_lon). Ways that cross the border are kept whole, so routes
    leaving the region do not end abruptly at its edge.
    """
    collector = _Collector(bbox, profile)
    collector.apply_file(str(path), locations=True, idx="flex_mem")
    return collector.network
