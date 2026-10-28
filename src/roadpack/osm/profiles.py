"""Vehicle profiles: which OSM ways a vehicle may use, in which direction and at what speed."""
from dataclasses import dataclass

# highway -> (road class stored in the edge flags, km/h when the way has no maxspeed)
HIGHWAYS = {
    "motorway": (0, 80), "motorway_link": (0, 50),
    "trunk": (1, 60), "trunk_link": (1, 40),
    "primary": (2, 50), "primary_link": (2, 40),
    "secondary": (3, 40), "secondary_link": (3, 30),
    "tertiary": (4, 30), "tertiary_link": (4, 30),
    "unclassified": (5, 30),
    "residential": (6, 25),
    "living_street": (7, 10),
    "service": (7, 15),
}
EXCLUDED_SERVICE = {"parking_aisle", "driveway", "drive-through", "emergency_access"}
DENIED_ACCESS = {"no", "private", "agricultural", "forestry", "emergency"}


@dataclass(frozen=True)
class Profile:
    name: str
    access_keys: tuple  # OSM access tags to check, from the most specific to the most general
    oneway_key: str     # vehicle-specific oneway tag, checked before `oneway`

    def allows(self, tags) -> bool:
        """Whether the vehicle may use a way with these tags (only the access restrictions)."""
        for key in self.access_keys:
            value = tags.get(key)
            if value is not None:
                return value not in DENIED_ACCESS
        return True

    def restriction(self, tags):
        """Turn restriction that applies to the vehicle ("no_left_turn", "only_straight_on", ...), or None.

        A vehicle-specific `restriction:<vehicle>` wins over `restriction`, which does not apply when `except`
        names the vehicle. Time-dependent `restriction:conditional` is ignored.
        """
        vehicles = [k for k in self.access_keys if k != "access"]
        for v in vehicles:
            value = tags.get(f"restriction:{v}")
            if value:
                return value if value.startswith(("no_", "only_")) else None
        value = tags.get("restriction")
        if not value or not value.startswith(("no_", "only_")):
            return None
        if set(tags.get("except", "").split(";")) & set(vehicles):
            return None
        return value

    def oneway(self, tags, highway) -> int:
        """1 = only along the way's drawing direction, -1 = only against it, 0 = both directions."""
        value = tags.get(self.oneway_key) or tags.get("oneway")
        if value in ("yes", "1", "true"):
            return 1
        if value == "-1":
            return -1
        if value == "no":
            return 0
        if tags.get("junction") in ("roundabout", "circular") or highway in ("motorway", "motorway_link"):
            return 1
        return 0


PROFILES = {
    "motorcycle": Profile("motorcycle", ("motorcycle", "motor_vehicle", "vehicle", "access"), "oneway:motorcycle"),
    "car": Profile("car", ("motorcar", "motor_vehicle", "vehicle", "access"), "oneway:motorcar"),
}


def parse_speed(value, default):
    """km/h from an OSM maxspeed value ("50", "30 mph", "60;80"), clamped to 5–120; default if unusable."""
    if not value:
        return default
    digits = "".join(c for c in value.split(";")[0] if c.isdigit())
    if not digits:
        return default
    speed = int(digits)
    if "mph" in value:
        speed = round(speed * 1.609)
    # Some ways in OSM carry impossible speeds.
    return max(5, min(speed, 120))
