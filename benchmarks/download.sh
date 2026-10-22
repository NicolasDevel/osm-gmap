#!/bin/bash
# Downloads the extracts of the benchmark tables into data/ (~15 GB, not in git). Resumable.
cd "$(dirname "$0")/../data" && mkdir -p cities countries
for c in Bogota MexicoCity Lima BuenosAires Santiago WashingtonDC Ottawa Toronto NewYork Madrid Barcelona Paris London Berlin Tokyo; do
  curl -sfL -C - -o cities/$c.osm.pbf https://download.bbbike.org/osm/bbbike/$c/$c.osm.pbf && echo "ok $c"
done
for r in europe/spain south-america/brazil north-america/us/california north-america/us/texas north-america/us/new-york north-america/canada; do
  n=$(basename $r)
  curl -sfL -C - -o countries/$n.osm.pbf https://download.geofabrik.de/$r-latest.osm.pbf && echo "ok $n"
done
echo done
