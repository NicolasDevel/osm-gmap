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
| Bogotá | 21 MB | 247,709 | 91,076 (37%) | 207,657 | 15 MB | 170 | 5 s | 1.7 GB |
| Mexico City | 19 MB | 333,405 | 151,909 (46%) | 340,842 | 26 MB | 171 | 4 s | 1.7 GB |
| Lima | 30 MB | 608,003 | 202,055 (33%) | 496,045 | 37 MB | 182 | 5 s | 1.8 GB |
| Buenos Aires | 39 MB | 446,899 | 216,057 (48%) | 574,606 | 46 MB | 211 | 9 s | 1.8 GB |
| Santiago | 41 MB | 540,992 | 182,273 (34%) | 411,222 | 30 MB | 162 | 5 s | 1.8 GB |
| Washington DC | 65 MB | 593,128 | 138,135 (23%) | 313,401 | 23 MB | 163 | 4 s | 1.8 GB |
| Ottawa | 49 MB | 280,353 | 54,696 (20%) | 123,777 | 9.3 MB | 170 | 2 s | 1.8 GB |
| Toronto | 102 MB | 721,280 | 171,604 (24%) | 405,017 | 29 MB | 170 | 6 s | 1.8 GB |
| New York | 153 MB | 1,110,586 | 295,665 (27%) | 673,087 | 50 MB | 169 | 10 s | 1.9 GB |
| Madrid | 77 MB | 631,568 | 160,636 (25%) | 305,890 | 25 MB | 156 | 5 s | 1.8 GB |
| Barcelona | 73 MB | 537,561 | 106,974 (20%) | 195,991 | 16 MB | 154 | 4 s | 1.8 GB |
| Paris | 243 MB | 994,019 | 258,208 (26%) | 510,934 | 39 MB | 152 | 9 s | 1.9 GB |
| London | 200 MB | 1,466,274 | 419,169 (29%) | 877,578 | 62 MB | 149 | 11 s | 1.9 GB |
| Berlin | 183 MB | 687,104 | 199,004 (29%) | 418,802 | 30 MB | 153 | 6 s | 1.8 GB |
| Tokyo | 92 MB | 583,568 | 236,169 (40%) | 578,507 | 42 MB | 180 | 7 s | 1.8 GB |
| Colombia | 314 MB | 9,655,142 | 1,265,660 (13%) | 3,044,885 | 263 MB | 208 | 54 s | 3.5 GB |
| Spain | 1,494 MB | 19,814,884 | 3,405,688 (17%) | 7,392,022 | 603 MB | 177 | 129 s | 6.2 GB |
| Brazil | 2,097 MB | 78,280,125 | 10,194,516 (13%) | 25,272,908 | 2,200 MB | 216 | 457 s | 9.3 GB |
| Canada | 6,519 MB | 18,113,378 | 2,866,165 (16%) | 6,805,976 | 579 MB | 202 | 147 s | 5.5 GB |
| California | 1,333 MB | 14,054,040 | 2,943,103 (21%) | 6,810,753 | 505 MB | 172 | 95 s | 5.0 GB |
| Texas | 726 MB | 15,820,817 | 3,649,807 (23%) | 8,920,565 | 671 MB | 184 | 107 s | 5.9 GB |
| New York State | 498 MB | 6,580,883 | 1,129,095 (17%) | 2,696,036 | 207 MB | 183 | 40 s | 2.5 GB |
<!-- /SIZE -->

## Routing cost

Nodes settled by the contraction hierarchy query, and the data it touches, in 4 KiB pages, with an empty cache:
what a microcontroller reads from the SD card. "With geometry" adds the edges and shape points of the route.
A* on the full graph is shown for comparison (mean over 5 routes).

<!-- ROUTES -->
| Region | Routes | Median length | Nodes settled (median / p95 / max) | KB read, query (median / p95) | KB read with geometry (median) | A* nodes settled (mean) |
|---|---:|---:|---:|---:|---:|---:|
| Bogotá | 199 | 15.2 km | 272 / 385 / 426 | 1,072 / 1,596 | 1,280 | 29,283 |
| Mexico City | 199 | 17.8 km | 365 / 506 / 604 | 1,540 / 2,176 | 1,736 | 50,689 |
| Lima | 194 | 27.8 km | 299 / 424 / 469 | 1,480 / 2,076 | 1,840 | 75,239 |
| Buenos Aires | 198 | 33.7 km | 658 / 981 / 1,229 | 2,552 / 3,708 | 2,888 | 70,274 |
| Santiago | 198 | 22.6 km | 361 / 533 / 580 | 1,592 / 2,264 | 1,804 | 44,638 |
| Washington DC | 190 | 17.5 km | 279 / 409 / 454 | 1,204 / 1,768 | 1,400 | 28,878 |
| Ottawa | 196 | 19.7 km | 167 / 247 / 283 | 664 / 940 | 860 | 17,181 |
| Toronto | 194 | 28.6 km | 298 / 436 / 515 | 1,288 / 1,996 | 1,528 | 50,840 |
| New York | 181 | 36.5 km | 408 / 617 / 713 | 1,992 / 2,868 | 2,380 | 44,535 |
| Madrid | 190 | 30.0 km | 305 / 449 / 534 | 1,348 / 1,912 | 1,584 | 40,671 |
| Barcelona | 194 | 25.8 km | 219 / 337 / 378 | 908 / 1,344 | 1,140 | 9,289 |
| Paris | 190 | 28.1 km | 378 / 596 / 747 | 1,764 / 2,636 | 2,028 | 65,853 |
| London | 188 | 30.6 km | 389 / 585 / 651 | 2,040 / 3,136 | 2,408 | 83,222 |
| Berlin | 196 | 30.0 km | 293 / 407 / 440 | 1,392 / 2,040 | 1,640 | 43,944 |
| Tokyo | 196 | 17.0 km | 462 / 627 / 680 | 2,112 / 2,844 | 2,364 | 81,247 |
| Colombia | 184 | 609.8 km | 294 / 458 / 558 | 2,972 / 4,640 | 4,896 | 438,898 |
| Spain | 180 | 562.9 km | 420 / 698 / 842 | 3,560 / 5,308 | 5,292 | 544,517 |
| Brazil | 194 | 1,673.7 km | 693 / 1,075 / 1,320 | 8,020 / 14,096 | 12,464 | 3,585,063 |
| Canada | 179 | 1,564.9 km | 546 / 973 / 1,159 | 5,572 / 8,668 | 8,336 | 856,566 |
| California | 186 | 407.6 km | 566 / 910 / 1,075 | 4,496 / 6,100 | 5,876 | 1,087,332 |
| Texas | 191 | 460.4 km | 789 / 1,090 / 1,339 | 6,020 / 8,744 | 7,960 | 667,972 |
| New York State | 187 | 314.9 km | 459 / 661 / 795 | 3,408 / 4,984 | 4,504 | 269,416 |
<!-- /ROUTES -->

## Where the bytes go

<!-- SECTIONS -->
| Region | Nodes | Edges | Grid | Geometry | Names | CH forward | CH backward | Copies |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bogotá | 7% | 38% | 4% | 2% | 1% | 24% | 24% | 0% |
| Mexico City | 7% | 37% | 5% | 2% | 2% | 24% | 24% | 0% |
| Lima | 7% | 38% | 5% | 4% | 1% | 23% | 23% | 0% |
| Buenos Aires | 6% | 35% | 5% | 1% | 0% | 26% | 26% | 0% |
| Santiago | 7% | 39% | 5% | 2% | 1% | 23% | 22% | 0% |
| Washington DC | 7% | 39% | 5% | 5% | 1% | 21% | 21% | 0% |
| Ottawa | 7% | 37% | 6% | 6% | 2% | 21% | 21% | 0% |
| Toronto | 7% | 39% | 5% | 6% | 1% | 21% | 21% | 0% |
| New York | 7% | 38% | 5% | 4% | 1% | 23% | 23% | 0% |
| Madrid | 8% | 34% | 6% | 6% | 2% | 22% | 22% | 0% |
| Barcelona | 8% | 33% | 6% | 6% | 2% | 22% | 22% | 0% |
| Paris | 8% | 37% | 5% | 4% | 2% | 22% | 22% | 0% |
| London | 8% | 39% | 5% | 4% | 1% | 21% | 21% | 0% |
| Berlin | 8% | 39% | 6% | 3% | 1% | 22% | 22% | 0% |
| Tokyo | 7% | 38% | 4% | 2% | 0% | 24% | 24% | 0% |
| Colombia | 6% | 32% | 8% | 16% | 0% | 19% | 19% | 0% |
| Spain | 7% | 34% | 7% | 10% | 1% | 21% | 20% | 0% |
| Brazil | 6% | 32% | 10% | 13% | 1% | 19% | 19% | 0% |
| Canada | 6% | 33% | 15% | 11% | 1% | 17% | 17% | 0% |
| California | 7% | 38% | 7% | 8% | 1% | 20% | 20% | 0% |
| Texas | 7% | 37% | 9% | 8% | 1% | 20% | 20% | 0% |
| New York State | 7% | 36% | 8% | 9% | 1% | 20% | 19% | 0% |
<!-- /SECTIONS -->

## Turn restrictions

OSM turn restrictions (`type=restriction`) are applied by splitting the junctions they go through (see
[FORMAT.md](../FORMAT.md#turn-restrictions)). Counted over the whole extract: "outside the network" are those whose
via node is not a junction of drivable roads in the region (or whose ways the vehicle cannot use); "unsupported"
have several from/to members (these tables were built before via ways were supported: then a way as via counted
here too). Time-dependent ones (`restriction:conditional`) are not counted.

<!-- RESTRICTIONS -->
| Region | Restrictions for the vehicle | Applied | Outside the network | Ambiguous | Unsupported | Junction copies | Extra edges | Extra bytes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Bogotá | 2,356 | 2,130 | 22 | 0 | 204 | 2,083 (2.29%) | 3,079 | 0.1 MB (0.8%) |
| Mexico City | 1,028 | 798 | 34 | 0 | 196 | 772 (0.51%) | 974 | 0.0 MB (0.2%) |
| Lima | 1,444 | 934 | 97 | 0 | 413 | 901 (0.45%) | 1,125 | 0.0 MB (0.1%) |
| Buenos Aires | 5,304 | 5,005 | 82 | 0 | 217 | 4,847 (2.24%) | 9,100 | 0.4 MB (0.8%) |
| Santiago | 6,249 | 4,845 | 795 | 0 | 609 | 4,715 (2.59%) | 6,514 | 0.3 MB (0.9%) |
| Washington DC | 4,069 | 2,796 | 364 | 0 | 909 | 2,492 (1.80%) | 4,141 | 0.2 MB (0.7%) |
| Ottawa | 2,919 | 2,203 | 134 | 0 | 582 | 2,076 (3.80%) | 3,093 | 0.1 MB (1.4%) |
| Toronto | 4,238 | 3,159 | 500 | 0 | 579 | 3,040 (1.77%) | 4,719 | 0.2 MB (0.7%) |
| New York | 13,118 | 10,159 | 1,180 | 1 | 1,778 | 9,192 (3.11%) | 15,132 | 0.6 MB (1.2%) |
| Madrid | 7,652 | 7,174 | 396 | 0 | 82 | 6,619 (4.12%) | 8,644 | 0.4 MB (1.5%) |
| Barcelona | 6,598 | 5,982 | 525 | 1 | 90 | 5,600 (5.23%) | 6,999 | 0.3 MB (1.9%) |
| Paris | 6,160 | 5,390 | 554 | 0 | 216 | 5,073 (1.96%) | 6,582 | 0.3 MB (0.7%) |
| London | 5,928 | 4,709 | 504 | 0 | 715 | 4,393 (1.05%) | 6,155 | 0.3 MB (0.4%) |
| Berlin | 2,284 | 1,902 | 247 | 0 | 135 | 1,838 (0.92%) | 2,325 | 0.1 MB (0.3%) |
| Tokyo | 1,401 | 1,058 | 142 | 0 | 201 | 977 (0.41%) | 1,439 | 0.1 MB (0.1%) |
| Colombia | 7,125 | 5,913 | 227 | 0 | 985 | 5,727 (0.45%) | 8,519 | 0.4 MB (0.1%) |
| Spain | 142,236 | 135,495 | 5,561 | 2 | 1,178 | 124,085 (3.64%) | 149,166 | 6.7 MB (1.1%) |
| Brazil | 123,307 | 114,854 | 2,845 | 10 | 5,598 | 107,075 (1.05%) | 127,051 | 5.7 MB (0.3%) |
| Canada | 76,112 | 62,997 | 3,951 | 14 | 9,150 | 57,901 (2.02%) | 88,738 | 3.6 MB (0.6%) |
| California | 87,045 | 63,666 | 6,965 | 8 | 16,406 | 57,792 (1.96%) | 110,384 | 4.2 MB (0.8%) |
| Texas | 23,151 | 15,761 | 2,260 | 6 | 5,124 | 12,603 (0.35%) | 18,882 | 0.8 MB (0.1%) |
| New York State | 24,318 | 18,542 | 2,374 | 5 | 3,397 | 15,946 (1.41%) | 25,601 | 1.0 MB (0.5%) |
<!-- /RESTRICTIONS -->

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
