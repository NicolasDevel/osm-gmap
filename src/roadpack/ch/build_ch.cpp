// Builds the contraction hierarchy (CH) of a graph with RoutingKit and writes it reorganized by node number
// (not by rank), so that nodes close on the map stay close on the SD card.
//
// Input  (little-endian): u32 node_count, u32 arc_count, u32 tail[arc_count], u32 head[arc_count],
//                         u32 weight[arc_count]
// Output (little-endian), for each side (forward first, then backward):
//          u32 arc_count, u32 first_out[node_count + 1], arcs[arc_count] of 16 bytes:
//          u32 other (head in forward, tail in backward), u32 weight, u32 a, u32 b
//          Original arc: a = ORIGINAL | id of the input arc, b = 0.
//          Shortcut: a = arc of the backward side, b = arc of the forward side (its two halves).
//
// Usage: build_ch input.bin output.bin

#include <routingkit/contraction_hierarchy.h>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <vector>

using namespace RoutingKit;

static const uint32_t ORIGINAL = 0x80000000u;

static std::vector<uint32_t> readArray(std::ifstream &in, size_t n) {
  std::vector<uint32_t> v(n);
  in.read(reinterpret_cast<char *>(v.data()), n * 4);
  return v;
}

static void writeU32(std::ofstream &out, uint32_t v) { out.write(reinterpret_cast<const char *>(&v), 4); }

// Reorders one side of the CH: from rank-indexed to node-indexed.
// newArc[old] is the new position of each arc, used to rewrite the references inside shortcuts.
static void reorder(const ContractionHierarchy &ch, const ContractionHierarchy::Side &side, std::vector<uint32_t> &firstOut,
                    std::vector<uint32_t> &newArc) {
  const uint32_t n = ch.node_count();
  firstOut.assign(n + 1, 0);
  for (uint32_t node = 0; node < n; node++) {
    uint32_t r = ch.rank[node];
    firstOut[node + 1] = firstOut[node] + (side.first_out[r + 1] - side.first_out[r]);
  }
  newArc.assign(side.head.size(), 0);
  for (uint32_t node = 0; node < n; node++) {
    uint32_t r = ch.rank[node];
    for (uint32_t k = 0; k < side.first_out[r + 1] - side.first_out[r]; k++) newArc[side.first_out[r] + k] = firstOut[node] + k;
  }
}

static void writeSide(std::ofstream &out, const ContractionHierarchy &ch, const ContractionHierarchy::Side &side,
                      const std::vector<uint32_t> &firstOut, const std::vector<uint32_t> &newArc,
                      const std::vector<uint32_t> &newBackward, const std::vector<uint32_t> &newForward) {
  const size_t arcs = side.head.size();
  std::vector<uint32_t> rec(arcs * 4);
  for (size_t old = 0; old < arcs; old++) {
    uint32_t *r = &rec[newArc[old] * 4];
    r[0] = ch.order[side.head[old]];  // rank -> node number
    r[1] = side.weight[old];
    if (side.is_shortcut_an_original_arc.is_set(old)) {
      r[2] = ORIGINAL | side.shortcut_first_arc[old];
      r[3] = 0;
    } else {
      r[2] = newBackward[side.shortcut_first_arc[old]];
      r[3] = newForward[side.shortcut_second_arc[old]];
    }
  }
  writeU32(out, (uint32_t)arcs);
  out.write(reinterpret_cast<const char *>(firstOut.data()), firstOut.size() * 4);
  out.write(reinterpret_cast<const char *>(rec.data()), rec.size() * 4);
}

int main(int argc, char **argv) {
  if (argc != 3) {
    std::cerr << "usage: build_ch input.bin output.bin\n";
    return 2;
  }
  std::ifstream in(argv[1], std::ios::binary);
  uint32_t nodeCount = 0, arcCount = 0;
  in.read(reinterpret_cast<char *>(&nodeCount), 4);
  in.read(reinterpret_cast<char *>(&arcCount), 4);
  std::vector<unsigned> tail = readArray(in, arcCount), head = readArray(in, arcCount), weight = readArray(in, arcCount);
  if (!in) {
    std::cerr << "truncated input\n";
    return 1;
  }

  ContractionHierarchy ch = ContractionHierarchy::build(nodeCount, tail, head, weight,
                                                        [](const std::string &msg) { std::cerr << "  [ch] " << msg << "\n"; });
  check_contraction_hierarchy_for_errors(ch);

  std::vector<uint32_t> fwdFirst, bwdFirst, newForward, newBackward;
  reorder(ch, ch.forward, fwdFirst, newForward);
  reorder(ch, ch.backward, bwdFirst, newBackward);

  std::ofstream out(argv[2], std::ios::binary);
  writeSide(out, ch, ch.forward, fwdFirst, newForward, newBackward, newForward);
  writeSide(out, ch, ch.backward, bwdFirst, newBackward, newBackward, newForward);
  std::cerr << "  [ch] " << ch.forward.head.size() << " forward arcs, " << ch.backward.head.size() << " backward arcs\n";
  return out ? 0 : 1;
}
