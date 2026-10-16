# Formato `.gmap` v1

Grafo vial de una región, pensado para leerse desde la microSD con `fseek` + `fread`, sin parsear texto.
Todo es **little-endian** (igual que el ESP32-S3). Las coordenadas son enteros en grados × 10⁷ (≈ 1,1 cm).
`0xFFFFFFFF` significa "no hay" en las referencias de 32 bits.

```
┌──────────┬───────────┬───────────┬────────────────────────┬────────────┬─────────┐
│ cabecera │ nodos     │ aristas   │ índice espacial        │ geometría  │ nombres │
│ 64 B     │ 12 B × N+1│ 16 B × E  │ (celdas+1)×4 B + items │ variable   │ UTF-8   │
└──────────┴───────────┴───────────┴────────────────────────┴────────────┴─────────┘
```

## Cabecera (64 bytes)

| Offset | Tipo | Campo | Notas |
|---:|---|---|---|
| 0 | char[4] | magic | `GMAP` |
| 4 | u16 | version | `1` |
| 6 | u16 | header_size | `64` |
| 8 | u32 | node_count | N |
| 12 | u32 | edge_count | E |
| 16 | i32 ×4 | min_lat, min_lon, max_lat, max_lon | extensión de la red; (min_lat, min_lon) es el origen del índice |
| 32 | u32 | cell_size | lado de la celda del índice, en grados × 10⁷ |
| 36 | u16 | grid_cols | |
| 38 | u16 | grid_rows | |
| 40 | u32 | nodes_off | offsets absolutos de cada sección |
| 44 | u32 | edges_off | |
| 48 | u32 | grid_off | |
| 52 | u32 | geom_off | |
| 56 | u32 | names_off | |
| 60 | u32 | file_size | para validar que el archivo esté completo |

## Nodos (12 bytes, N + 1 registros)

Cada nodo es una **intersección o un extremo de vía**; los puntos intermedios de las calles no son nodos.

| Offset | Tipo | Campo |
|---:|---|---|
| 0 | i32 | lat |
| 4 | i32 | lon |
| 8 | u32 | first_edge |

Las aristas que salen del nodo `n` son `[first_edge(n), first_edge(n+1))` (formato CSR).
El registro `N` es un **centinela** con `first_edge = E`, para que la fórmula sirva también con el último nodo.
Los nodos están ordenados por celda del índice: los que están cerca en el mapa están cerca en el archivo.

## Aristas (16 bytes, E registros)

Aristas **dirigidas**: una vía de doble sentido tiene dos (una por sentido); una de un solo sentido, una.

| Offset | Tipo | Campo | Notas |
|---:|---|---|---|
| 0 | u32 | target | nodo destino |
| 4 | u32 | geom | offset relativo a `geom_off`, o `0xFFFFFFFF` si el tramo es recto |
| 8 | u32 | name | offset relativo a `names_off`, o `0xFFFFFFFF` |
| 12 | u16 | length_m | longitud real del tramo en metros |
| 14 | u8 | speed_kmh | `maxspeed` de OSM o el valor por defecto de la clase |
| 15 | u8 | flags | ver abajo |

El nodo de origen no se guarda: es el nodo en cuyo rango CSR está la arista.

**flags**

| Bits | Significado |
|---|---|
| 0-3 | clase: 0 motorway, 1 trunk, 2 primary, 3 secondary, 4 tertiary, 5 unclassified, 6 residential, 7 service/living_street |
| 4 | `GEOM_REVERSED`: la geometría guardada va de destino a origen; recórrela al revés |
| 5 | `ROUNDABOUT`: la arista es parte de una glorieta |
| 6 | `LINK`: rampa o enlace (`*_link`) |

## Índice espacial

Cuadrícula de `grid_cols × grid_rows` celdas sobre la extensión de la red. La celda de un punto es
`row = (lat - min_lat) / cell_size`, `col = (lon - min_lon) / cell_size`, `i = row * grid_cols + col`.

- `grid_off`: `u32 start[celdas + 1]`
- a continuación: `u32 items[start[celdas]]`

Las aristas de la celda `i` son `items[start[i] .. start[i+1])`. Cada tramo aparece una vez por celda que toca
(con una sola de sus dos direcciones). Sirve para encontrar la vía más cercana a la posición del GPS.

## Geometría

Solo los **puntos intermedios** del tramo (sin los nodos de los extremos), simplificados con Douglas-Peucker
a 2 m. Las dos direcciones de una vía comparten la misma geometría.

| Tipo | Campo |
|---|---|
| u16 | count |
| u16 | (relleno, 0) |
| (i32 lat, i32 lon) × count | puntos |

Polilínea completa de una arista = `[origen, ...puntos (al revés si GEOM_REVERSED), destino]`.

## Nombres

Cadenas UTF-8 terminadas en `\0`, sin repetir. Se usa `name` de OSM, o `ref` si no tiene nombre.

## Memoria en la placa (Bogotá)

| Sección | Tamaño | Dónde |
|---|---:|---|
| Nodos + aristas | ≈ 5,0 MB | PSRAM (cabe en los 8 MB) para que A* sea rápido; o leídos de la SD bajo demanda |
| Índice espacial | ≈ 0,9 MB | SD, se lee la celda alrededor de la posición |
| Geometría + nombres | ≈ 0,6 MB | SD, solo los tramos que se dibujan |
