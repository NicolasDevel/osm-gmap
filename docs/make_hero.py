#!/usr/bin/env python3
"""Renders docs/img/hero.png: a country's whole road graph with a long route, and three maneuver screens.

    python docs/make_hero.py out/colombia --from 4.6097,-74.0817 --to 10.3910,-75.4794 --device-seconds 3.4

--device-seconds is the time measured on the device for this route (it cannot be computed here).
"""
import argparse
import math
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from roadpack.format import Gmap
from roadpack.preview import draw_screen, font, format_distance
from roadpack.routing import maneuvers, route_ch

OUT = Path(__file__).resolve().parent / "img" / "hero.png"
W, H = 1600, 900
SCALE = 2  # drawn at 2x and downsampled, for antialiasing
BG, ROAD, ROUTE, TEXT, DIM = (11, 12, 14), (78, 84, 94), (255, 145, 30), (235, 235, 235), (140, 140, 145)


def point(text):
    lat, lon = (float(v) for v in text.split(","))
    return lat, lon


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gmap", type=Path)
    parser.add_argument("--from", dest="origin", type=point, required=True)
    parser.add_argument("--to", dest="dest", type=point, required=True)
    parser.add_argument("--device-seconds", type=float, required=True,
                        help="time to route it on the ESP32-S3, as measured there")
    args = parser.parse_args()

    g = Gmap(args.gmap)
    start, goal = g.nearest_node(*args.origin), g.nearest_node(*args.dest)
    stats = {}
    path, _ = route_ch(g, start, goal, stats)
    ms = maneuvers(g, path)
    km = sum(g.length[e] for e in path) / 1000

    img = Image.new("RGB", (W * SCALE, H * SCALE), BG)
    d = ImageDraw.Draw(img)

    # Map panel: the whole graph, fitted to the left part of the banner.
    pad = 20 * SCALE
    panel_w, panel_h = 680 * SCALE, H * SCALE - 2 * pad
    k = math.cos(math.radians((g.min_lat + g.max_lat) / 2))
    span_x, span_y = (g.max_lon - g.min_lon) * k, g.max_lat - g.min_lat
    s = min(panel_w / span_x, panel_h / span_y)
    ox = pad + (panel_w - span_x * s) / 2
    oy = pad + (panel_h - span_y * s) / 2
    to_px = lambda p: (ox + (p[1] - g.min_lon) * k * s, oy + (g.max_lat - p[0]) * s)

    widths = [4, 4, 3, 2, 2, 1, 1, 1]
    for e in range(g.edge_count):
        if g.source[e] < g.target[e] or not any(g.target[t] == g.source[e] for t in g.out_edges(g.target[e])):
            d.line([to_px(p) for p in g.polyline(e)], fill=ROAD, width=widths[g.flags[e] & 0x0F])
    d.line([to_px(p) for e in path for p in g.polyline(e)], fill=ROUTE, width=5 * SCALE, joint="curve")
    for p in (g.point(start), g.point(goal)):
        x, y = to_px(p)
        r = 9 * SCALE
        d.ellipse((x - r, y - r, x + r, y + r), fill=ROUTE, outline=BG, width=3 * SCALE)

    # Text.
    x0 = 720 * SCALE
    d.text((x0, 70 * SCALE), "roadpack", font=font(64 * SCALE), fill=TEXT)
    d.text((x0, 150 * SCALE), "OpenStreetMap road graphs for microcontrollers", font=font(30 * SCALE), fill=DIM)
    facts = [
        f"Bogotá → Cartagena, {km:,.0f} km",
        f"{g.node_count / 1e6:.2f} M nodes, whole country: {len(g.data) / 1e6:,.0f} MB on a microSD",
        f"contraction hierarchy: {stats['settled']} nodes settled for the route",
        f"routed on an ESP32-S3 in {args.device_seconds:g} s, offline",
    ]
    for i, line in enumerate(facts):
        d.text((x0, (225 + 44 * i) * SCALE), line, font=font(26 * SCALE), fill=TEXT if i == 0 else DIM)

    # Three maneuver screens, as the round display shows them.
    picks = []
    for kind in ("roundabout", "turn", "slight"):
        picks += [i for i, m in enumerate(ms) if m.kind == kind and 0 < len(m.street) <= 20][:1]
    with tempfile.TemporaryDirectory() as tmp:
        size = 260 * SCALE
        for n, i in enumerate(sorted(picks)[:3]):
            f = Path(tmp) / f"{n}.png"
            draw_screen(g, path, ms[i], ms[i].at_m - ms[i - 1].at_m, f)
            screen = Image.open(f).convert("RGB").resize((size, size), Image.LANCZOS)
            mask = Image.new("L", (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
            x = x0 + n * (size + 30 * SCALE)
            img.paste(screen, (x, 470 * SCALE), mask)
            d.text((x + size / 2, 470 * SCALE + size + 32 * SCALE), f"at km {ms[i].at_m / 1000:,.0f}",
                   font=font(20 * SCALE), fill=DIM, anchor="mm")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    print(f"{OUT} ({OUT.stat().st_size / 1024:.0f} KB); route {format_distance(km * 1000)}")


if __name__ == "__main__":
    main()
