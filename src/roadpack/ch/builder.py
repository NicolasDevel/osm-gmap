"""Contraction hierarchy layer: precomputes shortcuts with RoutingKit so a device can route long distances
settling a few hundred nodes.

The C++ helper (build_ch.cpp, next to this file) is compiled on first use into a cache directory, together
with a pinned RoutingKit checkout. Requires git and a C++17 compiler.
"""
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..format.spec import CH_ARC

ROUTINGKIT_URL = "https://github.com/RoutingKit/RoutingKit.git"
ROUTINGKIT_COMMIT = "54d49bb0cdea56dde182357522e4e86a03c57852"
ROUTINGKIT_SOURCES = ("contraction_hierarchy.cpp", "bit_vector.cpp", "timer.cpp", "vector_io.cpp", "graph_util.cpp")
SOURCE = Path(__file__).with_name("build_ch.cpp")


@dataclass
class ContractionHierarchy:
    """Forward and backward sections, already serialized as FORMAT.md describes."""
    forward: bytes
    backward: bytes

    @property
    def forward_arcs(self):
        return struct.unpack_from("<I", self.forward)[0]

    @property
    def backward_arcs(self):
        return struct.unpack_from("<I", self.backward)[0]


def cache_dir() -> Path:
    """Where RoutingKit and the compiled helper live: $ROADPACK_CACHE, or ~/.cache/roadpack."""
    if os.environ.get("ROADPACK_CACHE"):
        return Path(os.environ["ROADPACK_CACHE"])
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "roadpack"


def ensure_tool(log=print) -> Path:
    """Path to the compiled build_ch helper, building it (and fetching RoutingKit) if needed."""
    root = cache_dir()
    # Named after the RoutingKit commit and the helper's source, so any change rebuilds it.
    source_hash = hashlib.sha1(SOURCE.read_bytes()).hexdigest()[:8]
    tool = root / f"build_ch-{ROUTINGKIT_COMMIT[:8]}-{source_hash}"
    if tool.exists():
        return tool
    routingkit = root / "RoutingKit"
    if not (routingkit / "src").exists():
        log(f"Fetching RoutingKit into {routingkit} ...")
        root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", ROUTINGKIT_URL, str(routingkit)], check=True)
    subprocess.run(["git", "-C", str(routingkit), "checkout", "-q", ROUTINGKIT_COMMIT], check=True)

    compiler = os.environ.get("CXX") or shutil.which("clang++") or shutil.which("g++")
    if not compiler:
        raise RuntimeError("a C++17 compiler is needed to build the contraction hierarchy (set CXX)")
    log(f"Compiling the contraction hierarchy helper with {Path(compiler).name} ...")
    src = routingkit / "src"
    subprocess.run([compiler, "-std=c++17", "-O3", "-DNDEBUG", f"-I{routingkit / 'include'}", "-o", str(tool),
                    str(SOURCE), *(str(src / f) for f in ROUTINGKIT_SOURCES)], check=True)
    return tool


def build_ch(node_count, tails, heads, weights, log=print) -> ContractionHierarchy:
    """Contraction hierarchy of a directed graph given as parallel arc arrays (weights in tenths of a second)."""
    tool = ensure_tool(log)
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "graph.bin", Path(tmp) / "ch.bin"
        with open(src, "wb") as f:
            f.write(struct.pack("<II", node_count, len(tails)))
            for arr in (tails, heads, weights):
                f.write(struct.pack(f"<{len(arr)}I", *arr))
        subprocess.run([str(tool), str(src), str(dst)], check=True, stderr=subprocess.DEVNULL)
        data = dst.read_bytes()
    fwd_arcs = struct.unpack_from("<I", data, 0)[0]
    fwd_size = 4 + (node_count + 1) * 4 + fwd_arcs * CH_ARC.size
    return ContractionHierarchy(data[:fwd_size], data[fwd_size:])


def build_graph_ch(graph, log=print) -> ContractionHierarchy:
    """Contraction hierarchy of a RoadGraph, on its travel-time weights."""
    edges = graph.edges
    return build_ch(len(graph.nodes), [e.source for e in edges], [e.target for e in edges],
                    [e.weight for e in edges], log)
