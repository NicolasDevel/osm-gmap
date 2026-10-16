# gps-moto-maps

Genera mapas de ruteo offline para motos a partir de OpenStreetMap, pensados para microcontroladores con
poca memoria (un ESP32-S3 con microSD).

Convierte un extracto `.osm.pbf` en un archivo `.gmap`: un grafo vial binario con solo las vías aptas para
moto, geometría simplificada, nombres, un índice espacial y una **jerarquía de contracción** precalculada.
Con ella, una ruta de 1.000 km se calcula visitando unos cientos de nodos, leyendo poco de la tarjeta.

## Uso

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# Extracto de OpenStreetMap, por ejemplo https://download.geofabrik.de/south-america/colombia.html
.venv/bin/python build_graph.py --pbf colombia-latest.osm.pbf --region colombia --out out/colombia.gmap
```

Genera `out/colombia.gmap` y `out/colombia/`, el mismo mapa partido en pedazos de 4 MB para la microSD.
Regiones incluidas: `bogota`, `cundinamarca`, `colombia` (se agregan en `REGIONS` de `build_graph.py`).

La primera vez descarga y compila [RoutingKit](https://github.com/RoutingKit/RoutingKit) para la jerarquía
de contracción: hace falta `git` y `clang++`.

| Región | Nodos | Archivo | Generación |
|---|---:|---:|---:|
| Bogotá | 108 mil | 17 MB | ~20 s |
| Colombia | 1,26 millones | 273 MB | ~80 s, ~4 GB de RAM |

## Probar una ruta

```bash
.venv/bin/python preview.py out/colombia.gmap --from 4.5981,-74.0760 --to 4.6766,-74.0482 --out out/preview
```

Imprime las maniobras y genera imágenes de la ruta y de cada maniobra. `route.py` tiene el ruteo con la
jerarquía de contracción y un A* de referencia (dan el mismo resultado).

## Archivos

| Archivo | Qué hace |
|---|---|
| `build_graph.py` | OSM → `.gmap` |
| `gmap_format.py` | Constantes del formato |
| `gmap.py` | Lector |
| `route.py` | Ruteo y maniobras |
| `preview.py` | Imágenes de una ruta |
| `ch/build_ch.cpp` | Jerarquía de contracción con RoutingKit |
| `FORMAT.md` | Especificación del formato `.gmap` v2 |

## Licencias

- El código de este repositorio: [MIT](LICENSE).
- Los mapas generados son una base de datos derivada de OpenStreetMap, © colaboradores de OpenStreetMap,
  bajo la [ODbL](https://opendatacommons.org/licenses/odbl/): si se distribuyen, hay que dar esa atribución
  y compartirlos bajo la misma licencia.
- [RoutingKit](https://github.com/RoutingKit/RoutingKit) (BSD 2-Clause) se descarga y compila al usarlo; no
  se incluye en este repositorio.
- Dependencias de Python: [pyosmium](https://github.com/osmcode/pyosmium) (BSD 2-Clause),
  [NumPy](https://numpy.org) (BSD 3-Clause), [Pillow](https://python-pillow.org) (MIT-CMU).
