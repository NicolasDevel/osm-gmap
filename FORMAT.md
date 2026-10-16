# Formato `.gmap` v2

Grafo vial de una región, pensado para leerse desde la microSD con `fseek` + `fread`, sin parsear texto y
**sin cargarlo completo en memoria**: la placa lee por páginas con una caché pequeña. Incluye una
**jerarquía de contracción (CH)** precalculada para rutear distancias largas visitando pocos nodos.

Todo es **little-endian** (igual que el ESP32-S3). Las coordenadas son enteros en grados × 10⁷ (≈ 1,1 cm).
`0xFFFFFFFF` significa "no hay" en las referencias de 32 bits.

```
┌──────────┬────────────┬───────────┬─────────────────┬────────────┬─────────┬────────────┬─────────────┐
│ cabecera │ nodos      │ aristas   │ índice espacial │ geometría  │ nombres │ CH forward │ CH backward │
│ 72 B     │ 12 B × N+1 │ 28 B × E  │ disperso        │ variable   │ UTF-8   │            │             │
└──────────┴────────────┴───────────┴─────────────────┴────────────┴─────────┴────────────┴─────────────┘
```

Los nodos están ordenados por **curva Z (Morton)** de su celda del índice espacial: lo que está cerca en el
mapa, en cualquier dirección, está cerca en el archivo. Aristas, geometría y CH siguen ese mismo orden. Así
la caché de páginas de la placa acierta casi siempre.

## En la microSD

El archivo se guarda **partido en pedazos de 4 MiB** dentro de una carpeta: `/maps/<región>/0000.bin`,
`0001.bin`, … (los genera `build_graph.py` en `out/<región>/`). Para la placa es un solo archivo continuo.

El motivo: el núcleo de Arduino trae FAT sin *fast seek*, y saltar hacia atrás dentro de un archivo de
cientos de MB recorre toda la cadena de clústeres (medido: ~12 ms por lectura). Con pedazos de 4 MiB el salto
es corto y se abren pocos archivos (cada apertura cuesta ~17 ms en la placa).

## Cabecera (72 bytes)

| Offset | Tipo | Campo | Notas |
|---:|---|---|---|
| 0 | char[4] | magic | `GMAP` |
| 4 | u16 | version | `2` |
| 6 | u16 | header_size | `72` |
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
| 60 | u32 | ch_fwd_off | alineado a 4 bytes |
| 64 | u32 | ch_bwd_off | |
| 68 | u32 | file_size | para validar que el archivo esté completo |

## Nodos (12 bytes, N + 1 registros)

Cada nodo es una **intersección o un extremo de vía**; los puntos intermedios de las calles no son nodos.

| Offset | Tipo | Campo |
|---:|---|---|
| 0 | i32 | lat |
| 4 | i32 | lon |
| 8 | u32 | first_edge |

Las aristas que salen del nodo `n` son `[first_edge(n), first_edge(n+1))` (formato CSR). El registro `N`
es un **centinela** con `first_edge = E`.

## Aristas (28 bytes, E registros)

Aristas **dirigidas**: una vía de doble sentido tiene dos (una por sentido); una de un solo sentido, una.

| Offset | Tipo | Campo | Notas |
|---:|---|---|---|
| 0 | u32 | source | nodo de origen |
| 4 | u32 | target | nodo destino |
| 8 | u32 | geom | offset relativo a `geom_off`, o `0xFFFFFFFF` si el tramo es recto |
| 12 | u32 | name | offset relativo a `names_off`, o `0xFFFFFFFF` |
| 16 | u32 | length_m | longitud real del tramo en metros |
| 20 | u32 | weight_ds | tiempo de recorrido en décimas de segundo (`length_m × 36 / speed_kmh`, mínimo 1): el peso para rutear |
| 24 | u8 | speed_kmh | `maxspeed` de OSM o el valor por defecto de la clase |
| 25 | u8 | flags | ver abajo |
| 26 | u16 | (relleno) | 0 |

**flags**

| Bits | Significado |
|---|---|
| 0-3 | clase: 0 motorway, 1 trunk, 2 primary, 3 secondary, 4 tertiary, 5 unclassified, 6 residential, 7 service/living_street |
| 4 | `GEOM_REVERSED`: la geometría guardada va de destino a origen; recórrela al revés |
| 5 | `ROUNDABOUT`: la arista es parte de una glorieta |
| 6 | `LINK`: rampa o enlace (`*_link`) |

## Índice espacial (disperso)

Cuadrícula de `grid_cols × grid_rows` celdas sobre la extensión de la red; solo se guardan las celdas con
vías (para un país, la cuadrícula completa ocuparía cientos de MB). La celda de un punto es
`row = (lat - min_lat) / cell_size`, `col = (lon - min_lon) / cell_size`, `id = row * grid_cols + col`.

| Tipo | Campo |
|---|---|
| u32 | K: cantidad de celdas no vacías |
| u32 × K | ids de las celdas, **ordenados** (búsqueda binaria) |
| u32 × (K+1) | inicio de cada celda en la lista de aristas |
| u32 × … | aristas: las de la celda `k` van de `start[k]` a `start[k+1]` |

Cada tramo aparece una vez por celda que toca (con una sola de sus dos direcciones). Sirve para encontrar
la vía más cercana a la posición del GPS y las calles alrededor de un cruce.

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

## Jerarquía de contracción

La calcula `tools/ch/build_ch` con [RoutingKit](https://github.com/RoutingKit/RoutingKit) sobre los pesos
`weight_ds`. Cada nodo tiene un rango; la CH agrega **atajos** para que toda ruta óptima se pueda armar
subiendo de rango desde el origen y bajando hasta el destino.

Cada lado (forward y backward) tiene la misma estructura, **indexada por número de nodo**:

| Tipo | Campo |
|---|---|
| u32 | A: cantidad de arcos |
| u32 × (N+1) | first_out: los arcos del nodo `n` van de `first_out[n]` a `first_out[n+1]` |
| 16 B × A | arcos |

| Offset | Tipo | Campo | Notas |
|---:|---|---|---|
| 0 | u32 | other | forward: nodo de **mayor rango** al que lleva el arco. Backward: nodo de mayor rango desde el que llega (en el sentido real de la vía, `other → n`) |
| 4 | u32 | weight_ds | |
| 8 | u32 | a | si el bit 31 está encendido: arco original, `a & 0x7FFFFFFF` es el id de la arista. Si no: primera mitad del atajo (un arco **backward**) |
| 12 | u32 | b | atajo: segunda mitad (un arco **forward**). Arco original: 0 |

**Consulta** (ver `route_ch` en `tools/route.py`):
1. Dijkstra desde el origen sobre los arcos forward y, a la vez, desde el destino sobre los arcos backward.
   Cada lado se detiene cuando su menor distancia pendiente ya no mejora la mejor ruta encontrada.
2. La ruta pasa por el nodo de encuentro con menor suma de distancias.
3. Cada arco se desarma recursivamente: atajo = backward(`a`) seguido de forward(`b`), hasta llegar a las
   aristas originales.

En Bogotá y Cundinamarca la consulta asienta unos **240 nodos por ruta** (máximo ~400), contra miles del A*
sobre el grafo completo, y da exactamente el mismo costo.
