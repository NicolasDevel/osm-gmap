"""Images to review a route on a PC:
  - route.png: the road network around the route, with the route and its maneuvers.
  - screen_NN.png: each maneuver as it would look on a 466×466 round display, Beeline style: the junction
    simplified with the heading up, the arrow, the distance and the street.
"""
import math

from PIL import Image, ImageDraw, ImageFont

from .geo import local_xy
from .routing.maneuvers import arriving_bearing, leaving_bearing, turn_angle

SIZE = 466
CENTER = (SIZE // 2, 205)    # the junction sits a bit above the center; distance and street go below
PX_PER_M = 1.6
BRANCH_M = 70                # length of the roads drawn around the junction
ROUTE_AFTER_M = 80           # how much of the route is drawn past the junction
BLACK, WHITE, GRAY, DIM = (0, 0, 0), (255, 255, 255), (70, 70, 70), (150, 150, 150)


def font(size):
    for name in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
                 "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def format_distance(m):
    """Rounded like a navigation display: 10 m steps, 50 m from 300 m, then km with one decimal."""
    if m < 1000:
        step = 10 if m < 300 else 50
        return f"{int(round(m / step) * step)} m"
    return f"{m / 1000:.1f} km"


def clip(points, max_m):
    """First max_m meters of the polyline."""
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        seg = math.hypot(*local_xy(a, b))
        if seg >= max_m:
            t = max_m / seg if seg else 0
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            return out
        out.append(b)
        max_m -= seg
    return out


def draw_junction(d, gmap, path, m, line):
    """The real junction, simplified: neighbouring roads in gray, the route in white with its arrow."""
    origin = gmap.point(m.node)
    # Every road entering or leaving the junction, in gray.
    for e in list(gmap.out_edges(m.node)):
        line(clip(gmap.polyline(e), BRANCH_M), GRAY, 26)
    for e in gmap.in_edges(m.node):
        line(clip(gmap.polyline(e)[::-1], BRANCH_M), GRAY, 26)

    # The route in white: what comes before the junction and what follows.
    before = clip(gmap.polyline(path[m.edge_index - 1])[::-1], BRANCH_M)[::-1]
    after, left = [origin], ROUTE_AFTER_M
    for e in path[m.edge_index:]:
        pts = clip(gmap.polyline(e), left)
        after += pts[1:]
        left -= gmap.length[e]
        if left <= 0:
            break
    line(before, WHITE, 18)
    px = line(after, WHITE, 18)

    arrow_head(d, px[-2], px[-1])


def arrow_head(d, tip_from, tip_to, size=22):
    (x1, y1), (x2, y2) = tip_from, tip_to
    ang = math.atan2(y2 - y1, x2 - x1)
    tip = (x2 + size * math.cos(ang), y2 + size * math.sin(ang))
    wing = lambda s: (x2 + size * math.cos(ang + s * 2.2), y2 + size * math.sin(ang + s * 2.2))
    d.polygon([tip, wing(1), wing(-1)], fill=WHITE)


def draw_roundabout(d, gmap, path, m, radius=56, stub=50):
    """Roundabout icon: entry at the bottom, counterclockwise, the exit at its real angle."""
    cx, cy = CENTER[0], CENTER[1] - 15
    in_b = arriving_bearing(gmap, path[m.edge_index - 1])

    def on_ring(theta, r):  # theta: degrees from the top, clockwise
        t = math.radians(theta)
        return cx + r * math.sin(t), cy - r * math.cos(t)

    # Exits not taken, in gray.
    k = m.edge_index
    while k < len(path) and gmap.is_roundabout(path[k]):
        node = gmap.target[path[k]]
        for e in gmap.out_edges(node):
            if not gmap.is_roundabout(e) and (k + 1 >= len(path) or e != path[k + 1]):
                theta = turn_angle(in_b, leaving_bearing(gmap, e))
                d.line([on_ring(theta, radius), on_ring(theta, radius + stub)], fill=GRAY, width=22)
        k += 1

    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=GRAY, width=22)

    exit_theta = m.angle
    # Right-hand traffic goes counterclockwise: from the entry (bottom, 180°) round to the exit.
    d.arc((cx - radius, cy - radius, cx + radius, cy + radius), exit_theta - 90, 90, fill=WHITE, width=18)
    d.line([on_ring(180, radius + 38), on_ring(180, radius)], fill=WHITE, width=18)
    start, end = on_ring(exit_theta, radius), on_ring(exit_theta, radius + stub)
    d.line([start, end], fill=WHITE, width=18)
    arrow_head(d, start, end)


def draw_screen(gmap, path, m, distance_m, out_file):
    img = Image.new("RGB", (SIZE, SIZE), BLACK)
    d = ImageDraw.Draw(img)
    origin = gmap.point(m.node)
    heading = math.radians(arriving_bearing(gmap, path[m.edge_index - 1]))

    def to_px(p):
        x, y = local_xy(origin, p)
        # Arrival heading points up.
        rx = x * math.cos(heading) - y * math.sin(heading)
        ry = x * math.sin(heading) + y * math.cos(heading)
        return CENTER[0] + rx * PX_PER_M, CENTER[1] - ry * PX_PER_M

    def line(points, color, width):
        px = [to_px(p) for p in points]
        d.line(px, fill=color, width=width, joint="curve")
        for x, y in (px[0], px[-1]):
            d.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=color)
        return px

    if m.kind == "roundabout":
        draw_roundabout(d, gmap, path, m)
    else:
        draw_junction(d, gmap, path, m, line)

    # Text: big distance, street and roundabout exit in small type.
    d.text((SIZE / 2, 352), format_distance(distance_m), font=font(56), fill=WHITE, anchor="mm")
    sub = m.street or ""
    if m.kind == "roundabout":
        sub = f"exit {m.exit_number}" + (f" · {sub}" if sub else "")
    if sub:
        size = 26
        while size > 14 and d.textlength(sub, font=font(size)) > 280:  # usable width of the circle at that height
            size -= 1
        d.text((SIZE / 2, 400), sub, font=font(size), fill=DIM, anchor="mm")

    # Round screen border.
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    round_img = Image.new("RGB", (SIZE, SIZE), (25, 25, 25))
    round_img.paste(img, (0, 0), mask)
    round_img.save(out_file)


def draw_overview(gmap, path, ms, out_file, width=1100):
    pts = [p for e in path for p in gmap.polyline(e)]
    lat0, lat1 = min(p[0] for p in pts), max(p[0] for p in pts)
    lon0, lon1 = min(p[1] for p in pts), max(p[1] for p in pts)
    pad_lat, pad_lon = (lat1 - lat0) * 0.08 + 0.002, (lon1 - lon0) * 0.08 + 0.002
    lat0, lat1, lon0, lon1 = lat0 - pad_lat, lat1 + pad_lat, lon0 - pad_lon, lon1 + pad_lon
    k = math.cos(math.radians((lat0 + lat1) / 2))
    height = int(width * (lat1 - lat0) / ((lon1 - lon0) * k))
    img = Image.new("RGB", (width, height), BLACK)
    d = ImageDraw.Draw(img)
    to_px = lambda p: ((p[1] - lon0) / (lon1 - lon0) * width, (lat1 - p[0]) / (lat1 - lat0) * height)

    widths = [4, 4, 3, 3, 2, 1, 1, 1]  # per road class
    seen = set()
    for e in gmap.edges_near((lat0 + lat1) / 2, (lon0 + lon1) / 2,
                              int(max(lat1 - lat0, lon1 - lon0) / gmap.cell / 2) + 1):
        if e in seen:
            continue
        seen.add(e)
        d.line([to_px(p) for p in gmap.polyline(e)], fill=(55, 55, 55), width=widths[gmap.road_class(e)])
    d.line([to_px(p) for p in pts], fill=(255, 140, 0), width=5)
    for m in ms:
        x, y = to_px(gmap.point(m.node))
        d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=WHITE)
    img.save(out_file)


def render(gmap, path, ms, out_dir):
    """Write route.png and one screen_NN.png per maneuver into out_dir. Returns the number of files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    draw_overview(gmap, path, ms, out_dir / "route.png")
    for n, (prev, m) in enumerate(zip(ms, ms[1:-1]), start=1):
        draw_screen(gmap, path, m, m.at_m - prev.at_m, out_dir / f"screen_{n:02d}.png")
    return len(ms) - 1
