"""Exact testing-binary fixture transition before the unchanged platform history."""
import hashlib
from pathlib import Path

from .dependencies import _read
from . import exec_server_source_history as previous

DEPENDENCY = previous.DEPENDENCY
ORIGINAL_TREE = previous.ORIGINAL_TREE
PREVIOUS_TREE = "4ded82432f79ba4191223cb2f88448dd560a31d0"
CURRENT_TREE = "2c20219dcf707f8e04d458fd399d6bec8ae20215"
LEAF_COUNT = 144
LEAVES = {
    "testing/BUILD.bazel": (
        "93cb4ceab9127c9792e349e1138632da760f6d05",
        "f6b40d6aebb5b58a5df9e438f1e263b4803c79bb"),
    "testing/exec_server.rs": (
        "36c7685ceb0eb411b8ff2a98f7f97a6a0e30cdf8",
        "6bf59c6726bed58ab0529ab73bc47c2214b9dc86"),
}


def _blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def reverse_fixture_tree(producer, relative, expected, actual, listing):
    from . import identity

    if (relative, expected, actual) != (DEPENDENCY, ORIGINAL_TREE, CURRENT_TREE):
        raise RuntimeError("unreviewed testing fixture dependency projection")
    if previous.CURRENT_TREE != PREVIOUS_TREE:
        raise RuntimeError("the preceding platform source pin changed")
    if not listing.endswith(b"\0"):
        raise RuntimeError("testing fixture dependency listing is incomplete")
    entries = {}
    for row in listing[:-1].split(b"\0"):
        try:
            header, path = row.split(b"\t", 1)
            mode, kind, blob = header.decode("ascii").split(" ")
            name = path.decode("utf-8")
        except (UnicodeError, ValueError) as error:
            raise RuntimeError("invalid testing fixture dependency leaf") from error
        if (kind != "blob" or mode not in {"100644", "100755"} or len(blob) != 40
                or any(c not in "0123456789abcdef" for c in blob) or name in entries
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or any(c in name for c in "\t\r\n\\")):
            raise RuntimeError("invalid or duplicate testing fixture dependency leaf")
        entries[name] = (mode, blob)
    if len(entries) != LEAF_COUNT or identity._dependency_tree_digest(entries) != CURRENT_TREE:
        raise RuntimeError("the complete current testing fixture dependency tree changed")
    projected, captured = dict(entries), {}
    for name, (before, after) in LEAVES.items():
        if entries.get(name) != ("100644", after):
            raise RuntimeError("a reviewed testing fixture leaf differs: " + name)
        data, binding = _read(Path(producer) / DEPENDENCY / name)
        if _blob(data) != after:
            raise RuntimeError("physical testing fixture source differs from its Git leaf: " + name)
        captured[name] = binding
        projected[name] = ("100644", before)
    if len(projected) != LEAF_COUNT or identity._dependency_tree_digest(projected) != PREVIOUS_TREE:
        raise RuntimeError("testing fixture inverse did not recover the complete preceding tree")
    previous_listing = b"".join(
        mode.encode() + b" blob " + blob.encode() + b"\t" + name.encode() + b"\0"
        for name, (mode, blob) in sorted(projected.items()))
    previous_proof = previous.reverse_platform_tree(
        producer, relative, expected, PREVIOUS_TREE, previous_listing)
    _, helper = _read(Path(__file__))
    return {"schema": "codex.hia.path-dependency-testing-fixture-projection.v1",
            "dependency": relative, "actual_tree": actual, "actual_leaf_count": len(entries),
            "intermediate_tree": PREVIOUS_TREE, "original_tree": expected,
            "actual_changed_files": captured, "helper": helper,
            "changed_source_leaves": len(LEAVES), "previous_projection": previous_proof,
            "platform_behavior_equivalence_claimed": False}
