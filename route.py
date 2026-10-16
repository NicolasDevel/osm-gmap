"""
Ruteo A* sobre el grafo y cálculo de maniobras (flecha + distancia, al estilo Beeline).
Es la referencia del algoritmo que correrá en la placa.
"""
import bisect
import heapq
import math
from dataclasses import dataclass

from gmap import Graph, bearing, local_xy
from gmap_format import CH_ORIGINAL, FLAG_LINK

MAX_SPEED_KMH = 120  # para la heurística de A*: nunca sobreestima el tiempo restante

# Umbrales de giro (grados, positivo = derecha).
STRAIGHT_DEG = 20
SLIGHT_DEG = 45
TURN_DEG = 135
SHARP_DEG = 170
BEARING_SAMPLE_M = 15  # distancia a la que se mide el rumbo de entrada y de salida de un cruce


def route_astar(graph: Graph, start: int, goal: int):
    """Ruta más rápida con A* sobre el grafo completo. Se conserva como referencia para validar la CH."""
    goal_pt = graph.point(goal)

    def h(n):  # décimas de segundo a la velocidad máxima
        return math.hypot(*local_xy(graph.point(n), goal_pt)) * 36 / MAX_SPEED_KMH

    best = {start: 0}
    came_from = {}
    open_heap = [(h(start), 0, start)]
    while open_heap:
        _, cost, node = heapq.heappop(open_heap)
        if node == goal:
            path = []
            while node != start:
                e = came_from[node]
                path.append(e)
                node = graph.source[e]
            return path[::-1], cost
        if cost > best.get(node, math.inf):
            continue
        for e in graph.out_edges(node):
            nxt = graph.target[e]
            c = cost + graph.weight[e]
            if c < best.get(nxt, math.inf):
                best[nxt] = c
                came_from[nxt] = e
                heapq.heappush(open_heap, (c + h(nxt), c, nxt))
    return None, math.inf


def _unpack(graph, side, arc, out):
    """Desarma un arco de la CH en las aristas originales (en orden). Atajo = backward(a) + forward(b)."""
    stack = [(side, arc)]
    while stack:
        sd, a = stack.pop()
        ch = graph.ch_fwd if sd == "f" else graph.ch_bwd
        if ch.a[a] & CH_ORIGINAL:
            out.append(ch.a[a] & ~CH_ORIGINAL)
        else:
            stack.append(("f", ch.b[a]))  # se apila primero la segunda mitad para procesarla después
            stack.append(("b", ch.a[a]))


def route_ch(graph: Graph, start: int, goal: int, stats=None):
    """Ruta más rápida con la jerarquía de contracción: Dijkstra bidireccional solo hacia arriba."""
    dist = ({start: 0}, {goal: 0})
    pred = ({}, {})  # nodo -> arco por el que se llegó
    heaps = ([(0, start)], [(0, goal)])
    sides = (graph.ch_fwd, graph.ch_bwd)
    best, meet = math.inf, None
    settled = 0
    while heaps[0] or heaps[1]:
        # Se avanza por el lado con la clave más baja; cada lado se detiene cuando ya no puede mejorar.
        k = 0 if heaps[0] and (not heaps[1] or heaps[0][0][0] <= heaps[1][0][0]) else 1
        d, u = heapq.heappop(heaps[k])
        if d >= best:
            heaps[k].clear()
            continue
        if d > dist[k].get(u, math.inf):
            continue
        settled += 1
        if u in dist[1 - k] and d + dist[1 - k][u] < best:
            best, meet = d + dist[1 - k][u], u
        ch = sides[k]
        for a in range(ch.first[u], ch.first[u + 1]):
            v, nd = ch.other[a], d + ch.weight[a]
            if nd < dist[k].get(v, math.inf):
                dist[k][v] = nd
                pred[k][v] = a
                heapq.heappush(heaps[k], (nd, v))
    if stats is not None:
        stats["settled"] = settled
    if meet is None:
        return None, math.inf

    # Subida desde el inicio (arcos forward) y bajada hacia el destino (arcos backward).
    up = []
    n = meet
    while n != start:
        a = pred[0][n]
        up.append(a)
        n = _arc_tail_forward(graph, a)
    path = []
    for a in reversed(up):
        _unpack(graph, "f", a, path)
    n = meet
    while n != goal:
        a = pred[1][n]
        _unpack(graph, "b", a, path)
        n = _arc_head_backward(graph, a)
    return path, best


def _arc_tail_forward(graph, a):
    """Nodo donde está guardado un arco forward (su cola)."""
    return bisect.bisect_right(graph.ch_fwd.first, a) - 1


def _arc_head_backward(graph, a):
    """Nodo donde está guardado un arco backward (en el sentido original, su cabeza)."""
    return bisect.bisect_right(graph.ch_bwd.first, a) - 1


def route(graph: Graph, start: int, goal: int):
    """Ruta más rápida como lista de aristas (usa la CH). None si no hay camino."""
    return route_ch(graph, start, goal)[0]


def _walk(points, distance):
    """Punto a `distance` metros a lo largo de la polilínea (o el último si es más corta)."""
    for a, b in zip(points, points[1:]):
        seg = math.hypot(*local_xy(a, b))
        if seg >= distance:
            t = distance / seg if seg else 0
            return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
        distance -= seg
    return points[-1]


def leaving_bearing(graph, e):
    pts = graph.polyline(e)
    return bearing(pts[0], _walk(pts, BEARING_SAMPLE_M))


def arriving_bearing(graph, e):
    pts = graph.polyline(e)[::-1]
    return bearing(_walk(pts, BEARING_SAMPLE_M), pts[0])


def turn_angle(in_bearing, out_bearing):
    """Giro en grados en (-180, 180]: positivo a la derecha, negativo a la izquierda."""
    a = (out_bearing - in_bearing + 180) % 360 - 180
    return 180.0 if a == -180 else a


@dataclass
class Maneuver:
    kind: str          # depart, straight, slight, turn, sharp, uturn, roundabout, arrive
    side: str          # left, right o "" (recto, salida, llegada)
    angle: float       # giro en grados (positivo = derecha)
    node: int          # cruce donde ocurre la maniobra
    edge_index: int    # posición en la ruta de la arista que sale del cruce
    at_m: float        # distancia desde el inicio de la ruta
    street: str        # vía hacia la que se gira
    exit_number: int = 0  # glorietas: número de salida

    def text(self):
        side = {"left": "a la izquierda", "right": "a la derecha"}.get(self.side, "")
        street = f" por {self.street}" if self.street else ""
        if self.kind == "depart":
            return f"Sal{street}"
        if self.kind == "arrive":
            return "Llegaste a tu destino"
        if self.kind == "roundabout":
            return f"En la glorieta, toma la {self.exit_number}.ª salida{street}"
        if self.kind == "uturn":
            return f"Da la vuelta en U{street}"
        verb = {"straight": "Sigue derecho", "slight": "Mantente", "turn": "Gira", "sharp": "Gira cerrado"}[self.kind]
        return f"{verb} {side}{street}".replace("  ", " ")


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


def maneuvers(graph: Graph, path):
    """Maniobras de la ruta: solo en los cruces donde hay que decidir algo."""
    result = [Maneuver("depart", "", 0, graph.source[path[0]], 0, 0, graph.name(path[0]))]
    at = 0.0
    i = 0
    while i < len(path) - 1:
        e_in, e_out = path[i], path[i + 1]
        at += graph.length[e_in]
        node = graph.target[e_in]
        came_from = graph.source[e_in]
        options = [e for e in graph.out_edges(node) if graph.target[e] != came_from]
        in_b = arriving_bearing(graph, e_in)

        # Entrada a glorieta: una sola instrucción con el número de salida.
        if graph.is_roundabout(e_out) and not graph.is_roundabout(e_in):
            exits, j = 0, i + 1
            while j < len(path) - 1 and graph.is_roundabout(path[j]):
                n = graph.target[path[j]]
                if any(not graph.is_roundabout(e) for e in graph.out_edges(n)):
                    exits += 1
                j += 1
            exit_edge = path[min(j, len(path) - 1)]
            angle = turn_angle(in_b, leaving_bearing(graph, exit_edge))
            result.append(Maneuver("roundabout", "", angle, node, i + 1, at, graph.name(exit_edge), max(exits, 1)))
            for k in range(i + 1, j):
                at += graph.length[path[k]]
            i = j
            continue

        if len(options) > 1:
            angle = turn_angle(in_b, leaving_bearing(graph, e_out))
            kind, side = _classify(angle)
            same_road = graph.name(e_out) == graph.name(e_in) and not graph.flags[e_out] & FLAG_LINK
            if kind == "straight" and not same_road:
                # Bifurcación: si otra salida también va casi derecho, hay que avisar hacia qué lado mantenerse.
                # Seguir derecho por la misma vía (aunque salgan calzadas laterales) no lleva aviso.
                rivals = [turn_angle(in_b, leaving_bearing(graph, e)) for e in options if e != e_out]
                close = [r for r in rivals if abs(r) < SLIGHT_DEG]
                if close:
                    kind, side = "slight", "right" if angle > min(close, key=abs) else "left"
            if kind != "straight":
                result.append(Maneuver(kind, side, angle, node, i + 1, at, graph.name(e_out)))
        i += 1

    at += graph.length[path[-1]]
    result.append(Maneuver("arrive", "", 0, graph.target[path[-1]], len(path), at, ""))
    return result
