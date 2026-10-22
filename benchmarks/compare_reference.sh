#!/bin/bash
# Builds the same region with the original pure-Python builder (build_graph.py, commit d688ccb, which keeps
# everything in Python dicts and lists) and with the current columnar one, and compares the files byte by byte.
#
#   benchmarks/compare_reference.sh colombia-latest.osm.pbf bogota       # bogota | cundinamarca | colombia
#   benchmarks/compare_reference.sh california-latest.osm.pbf all        # the whole extract
#
# If the files are not byte-identical, compare_maps.py checks whether they hold the same graph (see there).
# The reference builder needs about 500 bytes of RAM per road node (4.7 GB for Colombia). The current roadpack
# must be installed (it is the `roadpack` and `python` on the PATH).
set -euo pipefail
pbf=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
region=$2
repo=$(cd "$(dirname "$0")/.." && pwd)
work=$(mktemp -d)
trap 'git -C "$repo" worktree remove --force "$work/reference" >/dev/null 2>&1; rm -rf "$work"' EXIT

if [ "$(uname)" = Darwin ]; then timer=(/usr/bin/time -l); else timer=(/usr/bin/time -v); fi
measure() {  # runs a command, prints its wall time and peak memory
    local start=$SECONDS
    "${timer[@]}" "$@" > /dev/null 2> "$work/time.txt" || { cat "$work/time.txt"; exit 1; }
    local rss
    rss=$(awk '/maximum resident set size/ {print $1} /Maximum resident set size/ {print $6 * 1024}' "$work/time.txt")
    printf '  %d s, %.1f GB peak\n' $((SECONDS - start)) "$(echo "$rss / 1073741824" | bc -l)"
}

git -C "$repo" worktree add -q --detach "$work/reference" d688ccb
current=(--region "$region")
if [ "$region" = all ]; then
    # The reference only knows three named boxes: give it one that covers the world.
    sed -i.bak 's/^REGIONS = {/REGIONS = {\n    "all": (-90.0, -180.0, 90.0, 180.0),/' "$work/reference/build_graph.py"
    current=()
fi

echo "Reference (d688ccb, pure Python):"
(cd "$work/reference" && measure python build_graph.py --pbf "$pbf" --region "$region" --out "$work/reference.gmap")
echo "Current roadpack:"
measure roadpack build "$pbf" ${current[@]+"${current[@]}"} -o "$work/current.gmap" --no-chunks

shasum -a 256 "$work/reference.gmap" "$work/current.gmap" | sed "s|$work/||"
if cmp -s "$work/reference.gmap" "$work/current.gmap"; then
    echo "IDENTICAL"
else
    echo "Not byte-identical; comparing the graphs:"
    python "$repo/benchmarks/compare_maps.py" "$work/reference.gmap" "$work/current.gmap"
fi
