#!/usr/bin/env python3
"""
Calcula una ruta en el .gmap y genera imágenes para revisarla en el PC:
  - ruta.png: la red vial alrededor de la ruta, con la ruta y las maniobras.
  - pantalla_NN.png: cómo se vería cada maniobra en la pantalla redonda (466×466), al estilo Beeline:
    el cruce simplificado con el rumbo hacia arriba, la flecha, la distancia y la vía.

Uso:
  python preview.py out/bogota.gmap --from 4.5981,-74.0760 --to 4.6766,-74.0482 --out out/preview
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from gmap import Graph, local_xy
from route import arriving_bearing, leaving_bearing, maneuvers, route, turn_angle

SIZE = 466
CENTER = (SIZE // 2, 205)    # el cruce va un poco arriba del centro; abajo quedan la distancia y la vía
PX_PER_M = 1.6
BRANCH_M = 70                # largo de las vías que se dibujan alrededor del cruce
ROUTE_AFTER_M = 80           # cuánto se dibuja de la ruta después del cruce
BLACK, WHITE, GRAY, DIM = (0, 0, 0), (255, 255, 255), (70, 70, 70), (150, 150, 150)


def font(size):
    for name in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def format_distance(m):
    if m < 1000:
        step = 10 if m < 300 else 50
        return f"{int(round(m / step) * step)} m"
    return f"{m / 1000:.1f} km".replace(".", ",")


def clip(points, max_m):
    """Primeros max_m metros de la polilínea."""
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


def draw_junction(d, graph, path, m, line):
    """Cruce real simplificado: vías vecinas en gris y la ruta en blanco con su flecha."""
    origin = graph.point(m.node)
    # Todas las vías que llegan o salen del cruce, en gris.
    for e in list(graph.out_edges(m.node)):
        line(clip(graph.polyline(e), BRANCH_M), GRAY, 26)
    for e in graph.in_edges(m.node):
        line(clip(graph.polyline(e)[::-1], BRANCH_M), GRAY, 26)

    # La ruta en blanco: lo que viene antes del cruce y lo que sigue después.
    before = clip(graph.polyline(path[m.edge_index - 1])[::-1], BRANCH_M)[::-1]
    after, left = [origin], ROUTE_AFTER_M
    for e in path[m.edge_index:]:
        pts = clip(graph.polyline(e), left)
        after += pts[1:]
        left -= graph.length[e]
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


def draw_roundabout(d, graph, path, m, radius=56, stub=50):
    """Ícono de glorieta: entrada abajo, sentido antihorario y la salida en su ángulo real."""
    cx, cy = CENTER[0], CENTER[1] - 15
    in_b = arriving_bearing(graph, path[m.edge_index - 1])

    def on_ring(theta, r):  # theta: grados desde arriba, sentido horario
        t = math.radians(theta)
        return cx + r * math.sin(t), cy - r * math.cos(t)

    # Salidas que no se toman, en gris.
    k = m.edge_index
    while k < len(path) and graph.is_roundabout(path[k]):
        node = graph.target[path[k]]
        for e in graph.out_edges(node):
            if not graph.is_roundabout(e) and (k + 1 >= len(path) or e != path[k + 1]):
                theta = turn_angle(in_b, leaving_bearing(graph, e))
                d.line([on_ring(theta, radius), on_ring(theta, radius + stub)], fill=GRAY, width=22)
        k += 1

    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=GRAY, width=22)

    exit_theta = m.angle
    # En Colombia se gira en sentido antihorario: de la entrada (abajo, 180°) bajando hasta la salida.
    d.arc((cx - radius, cy - radius, cx + radius, cy + radius), exit_theta - 90, 90, fill=WHITE, width=18)
    d.line([on_ring(180, radius + 38), on_ring(180, radius)], fill=WHITE, width=18)
    start, end = on_ring(exit_theta, radius), on_ring(exit_theta, radius + stub)
    d.line([start, end], fill=WHITE, width=18)
    arrow_head(d, start, end)


def draw_screen(graph, path, m, distance_m, out_file):
    img = Image.new("RGB", (SIZE, SIZE), BLACK)
    d = ImageDraw.Draw(img)
    origin = graph.point(m.node)
    heading = math.radians(arriving_bearing(graph, path[m.edge_index - 1]))

    def to_px(p):
        x, y = local_xy(origin, p)
        # Rumbo de llegada hacia arriba.
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
        draw_roundabout(d, graph, path, m)
    else:
        draw_junction(d, graph, path, m, line)

    # Textos: distancia grande, vía y salida de glorieta en pequeño.
    d.text((SIZE / 2, 352), format_distance(distance_m), font=font(56), fill=WHITE, anchor="mm")
    sub = m.street or ""
    if m.kind == "roundabout":
        sub = f"{m.exit_number}.ª salida" + (f" · {sub}" if sub else "")
    if sub:
        size = 26
        while size > 14 and d.textlength(sub, font=font(size)) > 280:  # ancho útil del círculo a esa altura
            size -= 1
        d.text((SIZE / 2, 400), sub, font=font(size), fill=DIM, anchor="mm")

    # Borde redondo de la pantalla.
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE - 1, SIZE - 1), fill=255)
    round_img = Image.new("RGB", (SIZE, SIZE), (25, 25, 25))
    round_img.paste(img, (0, 0), mask)
    round_img.save(out_file)


def draw_overview(graph, path, ms, out_file, width=1100):
    pts = [p for e in path for p in graph.polyline(e)]
    lat0, lat1 = min(p[0] for p in pts), max(p[0] for p in pts)
    lon0, lon1 = min(p[1] for p in pts), max(p[1] for p in pts)
    pad_lat, pad_lon = (lat1 - lat0) * 0.08 + 0.002, (lon1 - lon0) * 0.08 + 0.002
    lat0, lat1, lon0, lon1 = lat0 - pad_lat, lat1 + pad_lat, lon0 - pad_lon, lon1 + pad_lon
    k = math.cos(math.radians((lat0 + lat1) / 2))
    height = int(width * (lat1 - lat0) / ((lon1 - lon0) * k))
    img = Image.new("RGB", (width, height), BLACK)
    d = ImageDraw.Draw(img)
    to_px = lambda p: ((p[1] - lon0) / (lon1 - lon0) * width, (lat1 - p[0]) / (lat1 - lat0) * height)

    widths = [4, 4, 3, 3, 2, 1, 1, 1]  # por clase de vía
    seen = set()
    for e in graph.edges_near((lat0 + lat1) / 2, (lon0 + lon1) / 2,
                              int(max(lat1 - lat0, lon1 - lon0) / graph.cell / 2) + 1):
        if e in seen:
            continue
        seen.add(e)
        d.line([to_px(p) for p in graph.polyline(e)], fill=(55, 55, 55), width=widths[graph.road_class(e)])
    d.line([to_px(p) for p in pts], fill=(255, 140, 0), width=5)
    for m in ms:
        x, y = to_px(graph.point(m.node))
        d.ellipse((x - 6, y - 6, x + 6, y + 6), fill=WHITE)
    img.save(out_file)


def parse_point(text):
    lat, lon = (float(v) for v in text.split(","))
    return lat, lon


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("gmap", type=Path)
    parser.add_argument("--from", dest="origin", required=True, type=parse_point, help="lat,lon")
    parser.add_argument("--to", dest="dest", required=True, type=parse_point, help="lat,lon")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    graph = Graph(args.gmap)
    start, goal = graph.nearest_node(*args.origin), graph.nearest_node(*args.dest)
    path = route(graph, start, goal)
    if path is None:
        raise SystemExit("No hay ruta entre esos dos puntos.")
    ms = maneuvers(graph, path)

    total_m = sum(graph.length[e] for e in path)
    total_s = sum(graph.length[e] / (graph.speed[e] / 3.6) for e in path)
    print(f"Ruta: {format_distance(total_m)}, ~{total_s / 60:.0f} min, {len(path)} tramos, {len(ms)} maniobras\n")
    for prev, m in zip([None, *ms], ms):
        gap = m.at_m - prev.at_m if prev else 0
        print(f"  {m.at_m / 1000:6.2f} km  (+{format_distance(gap):>7})  {m.text()}")

    args.out.mkdir(parents=True, exist_ok=True)
    draw_overview(graph, path, ms, args.out / "ruta.png")
    for n, (prev, m) in enumerate(zip(ms, ms[1:-1]), start=1):
        draw_screen(graph, path, m, m.at_m - prev.at_m, args.out / f"pantalla_{n:02d}.png")
    print(f"\nImágenes en {args.out}/")
