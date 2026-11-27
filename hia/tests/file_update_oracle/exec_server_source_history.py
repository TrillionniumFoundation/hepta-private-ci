"""Exact exec-server platform source history before the existing Wine-only leg."""
import hashlib
import json
from pathlib import Path

from .dependencies import _read

DEPENDENCY = "codex-rs/exec-server"
CURRENT_TREE = "4ded82432f79ba4191223cb2f88448dd560a31d0"
PREVIOUS_TREE = "040d2b09f7f1ed6dcf930c0c6032868e32b52764"
ORIGINAL_TREE = "6e7fb23cad63c4d9cd0c7ae24faae16c16def394"
LOCAL_FILE = DEPENDENCY + "/src/local_file_system.rs"
LOCAL_ORIGINAL_SHA = "f5210cc12b474ebb1983737ed8ee141cc10a033cc457bc22fe869fb1e967c061"
LOCAL_CURRENT_SHA = "a4b3d87823a0858c0495d34c1c066e6c67b773762ce561807e552fb295ee6538"
LEAVES = {
    "src/local_file_system.rs": (
        "0a1be1295388173a8aebc3e81980e3edecb9f12a",
        "ccfc1f65fb1c2cb9aa0e7acb632265de34b34f16"),
    "src/local_file_system_authorized_read_tests.rs": (
        "8d16d6e8ab4bb17d63ed850d92af8f86c4e5c588",
        "c1223c43044977c694bafba42815740140401c5e"),
    "src/local_file_system_macos.rs": (
        None, "587f1b55bba4754c66b31b3b0bb677ba525e3927"),
}
LOCAL_INVERSE = json.loads("[{\"before\":\"\",\"after\":\"#[cfg(target_os = \\\"macos\\\")]\\n#[path = \\\"local_file_system_macos.rs\\\"]\\nmod macos;\\n\"},{\"before\":\"    let denied_by_pattern = ReadDenyMatcher::new(&policy, cwd.as_path())\\n        .is_some_and(|matcher| matcher.is_read_denied(final_path));\\n    if denied_by_pattern || !policy.can_read_path_with_cwd(final_path, cwd.as_path()) {\\n\",\"after\":\"    #[cfg(target_os = \\\"linux\\\")]\\n    let path_candidates = [final_path];\\n    #[cfg(target_os = \\\"macos\\\")]\\n    let path_candidates = macos::authorized_read_path_candidates(final_path);\\n    let denied = ReadDenyMatcher::new(&policy, cwd.as_path()).is_some_and(|matcher| {\\n        path_candidates\\n            .iter()\\n            .any(|path| matcher.is_read_denied(path))\\n    });\\n    let allowed = path_candidates\\n        .iter()\\n        .any(|path| policy.can_read_path_with_cwd(path, cwd.as_path()));\\n    if denied || !allowed {\\n\"}]")


def _blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def reverse_local_file_source(producer, original):
    current, captured = _read(Path(producer) / LOCAL_FILE)
    if hashlib.sha256(original).hexdigest() != LOCAL_ORIGINAL_SHA:
        raise RuntimeError("the original complete local filesystem source changed")
    if captured["sha256"] != LOCAL_CURRENT_SHA:
        raise RuntimeError("unreviewed current local filesystem source")
    restored = current
    for block in LOCAL_INVERSE:
        new, old = block["after"].encode(), block["before"].encode()
        if restored.count(new) != 1:
            raise RuntimeError("local filesystem platform inverse is not unique")
        restored = restored.replace(new, old, 1)
    if restored != original or _blob(restored) != LEAVES["src/local_file_system.rs"][0]:
        raise RuntimeError("platform inverse did not restore the complete original source")
    _, helper = _read(Path(__file__))
    return {"schema": "codex.hia.local-filesystem-source-inverse.v1",
            "actual_file": captured, "helper": helper,
            "actual_git_blob": _blob(current), "restored_git_blob": _blob(restored),
            "restored_sha256": hashlib.sha256(restored).hexdigest(),
            "exact_blocks_removed_or_replaced": 2,
            "scope": "Source history only. Current filesystem dependency artifacts and original "
                     "owner behavior must still be captured and executed."}


def reverse_platform_tree(producer, relative, expected, actual, listing):
    from . import identity

    if (relative, expected, actual) != (DEPENDENCY, ORIGINAL_TREE, CURRENT_TREE):
        raise RuntimeError("unreviewed platform dependency source projection")
    if not listing.endswith(b"\0"):
        raise RuntimeError("platform dependency listing is incomplete")
    entries = {}
    for row in listing[:-1].split(b"\0"):
        header, path = row.split(b"\t", 1)
        mode, kind, blob = header.decode("ascii").split(" ")
        name = path.decode("utf-8")
        if (kind != "blob" or mode not in {"100644", "100755"} or len(blob) != 40
                or any(c not in "0123456789abcdef" for c in blob) or name in entries
                or any(part in {"", ".", ".."} for part in name.split("/"))
                or any(c in name for c in "\t\r\n\\")):
            raise RuntimeError("invalid or duplicate platform dependency leaf")
        entries[name] = (mode, blob)
    if len(entries) != 144 or identity._dependency_tree_digest(entries) != CURRENT_TREE:
        raise RuntimeError("the complete current platform dependency tree changed")
    projected, captured = dict(entries), {}
    for name, (before, after) in LEAVES.items():
        if entries.get(name) != ("100644", after):
            raise RuntimeError("a reviewed platform leaf differs: " + name)
        data, binding = _read(Path(producer) / DEPENDENCY / name)
        if _blob(data) != after:
            raise RuntimeError("physical platform source differs from its Git leaf: " + name)
        captured[name] = binding
        if before is None:
            del projected[name]
        else:
            projected[name] = ("100644", before)
    if len(projected) != 143 or identity._dependency_tree_digest(projected) != PREVIOUS_TREE:
        raise RuntimeError("platform inverse did not recover the complete preceding tree")
    previous_listing = b"".join(
        mode.encode() + b" blob " + blob.encode() + b"\t" + name.encode() + b"\0"
        for name, (mode, blob) in sorted(projected.items()))
    previous = identity._exec_server_test_projection(
        relative, expected, PREVIOUS_TREE, previous_listing)
    _, helper = _read(Path(__file__))
    return {"schema": "codex.hia.path-dependency-platform-projection.v1",
            "dependency": relative, "actual_tree": actual, "actual_leaf_count": len(entries),
            "intermediate_tree": PREVIOUS_TREE, "original_tree": expected,
            "actual_changed_files": captured, "helper": helper,
            "changed_source_leaves": len(LEAVES), "previous_projection": previous,
            "platform_behavior_equivalence_claimed": False}
