# Benchmarks

Every region is built from a public OpenStreetMap extract with the default motorcycle profile, then 200 random
pairs of nodes are routed the way a device would do it. To regenerate: `benchmarks/download.sh`, then
`python benchmarks/run.py`. How the large countries fit in a laptop, and the evidence that they are complete
and exact maps, is in [docs/SCALING.md](../docs/SCALING.md).

<!-- META -->
Measured on arm64 Darwin, 10 cores; OSM data from 2026-05-09 to 2026-10-20.
<!-- /META -->

## Size

"Road nodes in OSM" are the nodes of the drivable ways; only intersections and dead ends become graph nodes.

<!-- SIZE -->
| Region | OSM extract | Road nodes in OSM | Graph nodes | Edges | `.gmap` | Bytes / node | Build | Peak RAM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bogotá | 21 MB | 247,709 | 88,993 (36%) | 204,578 | 15 MB | 170 | 2 s | 1.7 GB |
| Mexico City | 19 MB | 333,405 | 151,137 (45%) | 339,868 | 26 MB | 172 | 4 s | 1.7 GB |
| Lima | 30 MB | 608,003 | 201,154 (33%) | 494,920 | 37 MB | 184 | 5 s | 1.8 GB |
| Buenos Aires | 39 MB | 446,899 | 211,210 (47%) | 565,506 | 45 MB | 212 | 9 s | 1.8 GB |
| Santiago | 41 MB | 540,992 | 177,558 (33%) | 404,708 | 29 MB | 163 | 5 s | 1.8 GB |
| Washington DC | 65 MB | 593,128 | 135,643 (23%) | 309,260 | 22 MB | 164 | 5 s | 1.8 GB |
| Ottawa | 49 MB | 280,353 | 52,620 (19%) | 120,684 | 9.1 MB | 173 | 2 s | 1.8 GB |
| Toronto | 102 MB | 721,280 | 168,564 (23%) | 400,298 | 29 MB | 171 | 5 s | 1.8 GB |
| New York | 153 MB | 1,110,586 | 286,473 (26%) | 657,955 | 49 MB | 170 | 9 s | 1.9 GB |
| Madrid | 77 MB | 631,568 | 154,017 (24%) | 297,246 | 25 MB | 160 | 5 s | 1.8 GB |
| Barcelona | 73 MB | 537,561 | 101,374 (19%) | 188,992 | 16 MB | 157 | 4 s | 1.8 GB |
| Paris | 243 MB | 994,019 | 253,135 (25%) | 504,352 | 39 MB | 153 | 8 s | 1.9 GB |
| London | 200 MB | 1,466,274 | 414,776 (28%) | 871,423 | 62 MB | 149 | 10 s | 1.9 GB |
| Berlin | 183 MB | 687,104 | 197,166 (29%) | 416,477 | 30 MB | 154 | 6 s | 1.8 GB |
| Tokyo | 92 MB | 583,568 | 235,192 (40%) | 577,068 | 42 MB | 180 | 7 s | 1.8 GB |
| Colombia | 314 MB | 9,655,142 | 1,259,933 (13%) | 3,036,366 | 287 MB | 228 | 52 s | 2.8 GB |
| Spain | 1,494 MB | 19,814,884 | 3,281,603 (17%) | 7,242,856 | 620 MB | 189 | 126 s | 5.0 GB |
| Brazil | 2,097 MB | 78,280,125 | 10,087,441 (13%) | 25,145,857 | 2,487 MB | 247 | 457 s | 8.0 GB |
| Canada | 6,519 MB | 18,113,378 | 2,808,264 (16%) | 6,717,238 | 760 MB | 271 | 103 s | 6.2 GB |
| California | 1,333 MB | 14,054,040 | 2,885,311 (21%) | 6,700,369 | 513 MB | 178 | 80 s | 4.7 GB |
| Texas | 726 MB | 15,820,817 | 3,637,204 (23%) | 8,901,683 | 698 MB | 192 | 96 s | 5.7 GB |
| New York State | 498 MB | 6,580,883 | 1,113,149 (17%) | 2,670,435 | 212 MB | 191 | 34 s | 2.4 GB |
<!-- /SIZE -->

## Routing cost

Nodes settled by the contraction hierarchy query, and the data it touches, in 4 KiB pages, with an empty cache:
what a microcontroller reads from the SD card. "With geometry" adds the edges and shape points of the route.
A* on the full graph is shown for comparison (mean over 5 routes).

<!-- ROUTES -->
| Region | Routes | Median length | Nodes settled (median / p95 / max) | KB read, query (median / p95) | KB read with geometry (median) | A* nodes settled (mean) |
|---|---:|---:|---:|---:|---:|---:|
| Bogotá | 198 | 14.2 km | 236 / 338 / 380 | 972 / 1,384 | 1,144 | 31,011 |
| Mexico City | 197 | 18.1 km | 345 / 522 / 554 | 1,508 / 2,228 | 1,728 | 52,646 |
| Lima | 195 | 28.1 km | 304 / 408 / 503 | 1,480 / 1,952 | 1,820 | 71,961 |
| Buenos Aires | 194 | 33.3 km | 604 / 861 / 952 | 2,324 / 3,396 | 2,588 | 61,456 |
| Santiago | 193 | 21.8 km | 343 / 506 / 565 | 1,492 / 2,196 | 1,688 | 41,830 |
| Washington DC | 192 | 19.2 km | 255 / 402 / 483 | 1,116 / 1,716 | 1,336 | 44,991 |
| Ottawa | 194 | 19.4 km | 145 / 211 / 259 | 620 / 860 | 804 | 13,896 |
| Toronto | 183 | 28.6 km | 282 / 436 / 505 | 1,256 / 1,884 | 1,480 | 41,233 |
| New York | 186 | 33.9 km | 363 / 571 / 671 | 1,836 / 2,604 | 2,176 | 56,859 |
| Madrid | 196 | 31.5 km | 293 / 398 / 436 | 1,284 / 1,748 | 1,516 | 52,383 |
| Barcelona | 190 | 27.5 km | 194 / 268 / 322 | 824 / 1,208 | 1,044 | 35,981 |
| Paris | 183 | 26.3 km | 354 / 568 / 669 | 1,660 / 2,580 | 1,908 | 57,517 |
| London | 191 | 30.6 km | 370 / 538 / 631 | 1,976 / 2,980 | 2,284 | 83,576 |
| Berlin | 195 | 31.5 km | 301 / 404 / 451 | 1,388 / 2,052 | 1,640 | 60,056 |
| Tokyo | 198 | 17.2 km | 438 / 598 / 684 | 1,936 / 2,640 | 2,188 | 82,162 |
| Colombia | 192 | 617.3 km | 275 / 435 / 555 | 2,980 / 4,472 | 4,988 | 457,588 |
| Spain | 187 | 549.9 km | 459 / 707 / 837 | 3,664 / 5,644 | 5,176 | 577,899 |
| Brazil | 193 | 1,690.4 km | 630 / 934 / 1,234 | 7,684 / 13,504 | 11,956 | 3,432,140 |
| Canada | 175 | 1,638.1 km | 526 / 806 / 1,150 | 5,312 / 8,352 | 8,168 | 510,409 |
| California | 184 | 521.8 km | 523 / 769 / 965 | 4,296 / 6,320 | 5,988 | 614,117 |
| Texas | 194 | 438.2 km | 707 / 1,151 / 1,411 | 5,672 / 8,556 | 7,524 | 445,549 |
| New York State | 192 | 303.0 km | 424 / 648 / 818 | 3,144 / 5,024 | 4,352 | 214,120 |
<!-- /ROUTES -->

## Where the bytes go

<!-- SECTIONS -->
| Region | Nodes | Edges | Grid | Geometry | Names | CH forward | CH backward |
|---|---:|---:|---:|---:|---:|---:|---:|
| Bogotá | 7% | 38% | 5% | 2% | 1% | 24% | 24% |
| Mexico City | 7% | 37% | 5% | 2% | 2% | 24% | 24% |
| Lima | 7% | 37% | 5% | 4% | 1% | 23% | 23% |
| Buenos Aires | 6% | 35% | 6% | 1% | 0% | 26% | 26% |
| Santiago | 7% | 39% | 5% | 2% | 1% | 22% | 22% |
| Washington DC | 7% | 39% | 5% | 5% | 1% | 21% | 21% |
| Ottawa | 7% | 37% | 8% | 6% | 2% | 20% | 20% |
| Toronto | 7% | 39% | 6% | 6% | 1% | 21% | 21% |
| New York | 7% | 38% | 5% | 4% | 1% | 23% | 23% |
| Madrid | 8% | 34% | 7% | 6% | 2% | 22% | 22% |
| Barcelona | 8% | 33% | 6% | 7% | 2% | 22% | 22% |
| Paris | 8% | 36% | 6% | 4% | 2% | 22% | 22% |
| London | 8% | 39% | 5% | 4% | 1% | 21% | 21% |
| Berlin | 8% | 38% | 7% | 3% | 1% | 22% | 22% |
| Tokyo | 7% | 38% | 4% | 2% | 0% | 24% | 24% |
| Colombia | 5% | 30% | 16% | 15% | 0% | 17% | 17% |
| Spain | 6% | 33% | 12% | 9% | 1% | 19% | 19% |
| Brazil | 5% | 28% | 21% | 11% | 1% | 17% | 17% |
| Canada | 4% | 25% | 36% | 8% | 1% | 13% | 13% |
| California | 7% | 37% | 10% | 8% | 1% | 19% | 19% |
| Texas | 6% | 36% | 13% | 7% | 1% | 19% | 19% |
| New York State | 6% | 35% | 12% | 9% | 1% | 19% | 19% |
<!-- /SECTIONS -->

## Colombia by department

Graph nodes inside each department (`admin_level=4` boundaries of the same extract) and the size a map of just
that department would have at Colombia's bytes per node. Regenerate with `python benchmarks/admin.py colombia`.

<!-- ADMIN-colombia -->
| Area | Graph nodes | Share | Edges | Map of just this area (est.) |
|---|---:|---:|---:|---:|
| Antioquia | 139,825 | 11.1% | 309,209 | ~31.8 MB |
| Cundinamarca | 119,641 | 9.5% | 268,498 | ~27.2 MB |
| Valle del Cauca | 108,530 | 8.6% | 254,606 | ~24.7 MB |
| Bogotá, Distrito Capital | 88,881 | 7.1% | 204,814 | ~20.2 MB |
| Santander | 66,332 | 5.3% | 152,511 | ~15.1 MB |
| Bolívar | 56,167 | 4.5% | 145,362 | ~12.8 MB |
| Boyacá | 55,463 | 4.4% | 131,416 | ~12.6 MB |
| Tolima | 49,888 | 4.0% | 117,970 | ~11.4 MB |
| Atlántico | 49,553 | 3.9% | 132,116 | ~11.3 MB |
| Norte de Santander | 48,736 | 3.9% | 118,029 | ~11.1 MB |
| Meta | 45,577 | 3.6% | 112,598 | ~10.4 MB |
| Cauca | 43,913 | 3.5% | 102,614 | ~10.0 MB |
| Córdoba | 42,994 | 3.4% | 113,804 | ~9.8 MB |
| Huila | 41,786 | 3.3% | 104,492 | ~9.5 MB |
| Magdalena | 37,254 | 3.0% | 102,649 | ~8.5 MB |
| Cesar | 34,069 | 2.7% | 95,502 | ~7.8 MB |
| Nariño | 32,219 | 2.6% | 75,844 | ~7.3 MB |
| Caldas | 27,158 | 2.2% | 62,479 | ~6.2 MB |
| La Guajira | 25,820 | 2.0% | 72,245 | ~5.9 MB |
| Sucre | 25,807 | 2.0% | 69,134 | ~5.9 MB |
| Risaralda | 24,637 | 2.0% | 53,422 | ~5.6 MB |
| Casanare | 20,881 | 1.7% | 54,594 | ~4.8 MB |
| Quindío | 16,650 | 1.3% | 35,820 | ~3.8 MB |
| Caquetá | 13,030 | 1.0% | 33,250 | ~3.0 MB |
| Arauca | 11,059 | 0.9% | 29,410 | ~2.5 MB |
| Putumayo | 9,694 | 0.8% | 23,950 | ~2.2 MB |
| Chocó | 7,405 | 0.6% | 17,545 | ~1.7 MB |
| Guaviare | 3,523 | 0.3% | 9,097 | ~0.8 MB |
| Vichada | 2,095 | 0.2% | 5,713 | ~0.5 MB |
| Archipiélago de San Andrés, Providencia y Santa Catalina | 1,319 | 0.1% | 2,936 | ~0.3 MB |
| Amazonas | 954 | 0.1% | 2,252 | ~0.2 MB |
| Guainía | 862 | 0.1% | 2,245 | ~0.2 MB |
| Vaupés | 333 | 0.0% | 805 | ~0.1 MB |
<!-- /ADMIN-colombia -->
