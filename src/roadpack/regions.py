"""Named bounding boxes for --region: (min_lat, min_lon, max_lat, max_lon)."""

REGIONS = {
    "bogota": (4.45, -74.25, 4.84, -73.98),
    "cundinamarca": (3.70, -74.95, 5.90, -73.00),  # includes Bogotá
    "colombia": (-4.5, -82.0, 13.6, -66.8),  # includes San Andrés and Providencia
}


def parse_bbox(text):
    """"min_lat,min_lon,max_lat,max_lon" -> tuple of floats."""
    values = tuple(float(v) for v in text.split(","))
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("expected min_lat,min_lon,max_lat,max_lon")
    return values
