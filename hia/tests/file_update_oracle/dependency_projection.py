"""Exact inverse for the reviewed Darwin authorization addition to exec-server.

The historical owner still links its own actual original Cargo graph. On Linux,
the reviewed current authorization branch has exactly one candidate, final_path,
and rejects D || !A as before. The new Darwin alias module is cfg-excluded there.
Every changed leaf, the unchanged remaining tree, and the original complete
source bytes stay bound; this is not admission of arbitrary dependency drift.
"""
import hashlib

from . import identity

DEPENDENCY = "codex-rs/exec-server"
ORIGINAL_TREE = "6e7fb23cad63c4d9cd0c7ae24faae16c16def394"
INTERMEDIATE_TREE = "040d2b09f7f1ed6dcf930c0c6032868e32b52764"
ACTUAL_TREE = "4ded82432f79ba4191223cb2f88448dd560a31d0"
SOURCE = "src/local_file_system.rs"
LEAVES = {
    SOURCE: ("0a1be1295388173a8aebc3e81980e3edecb9f12a",
             "ccfc1f65fb1c2cb9aa0e7acb632265de34b34f16"),
    "src/local_file_system_authorized_read_tests.rs": (
        "8d16d6e8ab4bb17d63ed850d92af8f86c4e5c588",
        "c1223c43044977c694bafba42815740140401c5e"),
    "src/local_file_system_macos.rs": (
        None, "587f1b55bba4754c66b31b3b0bb677ba525e3927"),
}
MODULE = (b'#[cfg(target_os = "macos")]\n'
          b'#[path = "local_file_system_macos.rs"]\nmod macos;\n')
ORIGINAL_READ = b'''    let denied_by_pattern = ReadDenyMatcher::new(&policy, cwd.as_path())
        .is_some_and(|matcher| matcher.is_read_denied(final_path));
    if denied_by_pattern || !policy.can_read_path_with_cwd(final_path, cwd.as_path()) {
'''
ACTUAL_READ = b'''    #[cfg(target_os = "linux")]
    let path_candidates = [final_path];
    #[cfg(target_os = "macos")]
    let path_candidates = macos::authorized_read_path_candidates(final_path);
    let denied = ReadDenyMatcher::new(&policy, cwd.as_path()).is_some_and(|matcher| {
        path_candidates
            .iter()
            .any(|path| matcher.is_read_denied(path))
    });
    let allowed = path_candidates
        .iter()
        .any(|path| policy.can_read_path_with_cwd(path, cwd.as_path()));
    if denied || !allowed {
'''


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def blob(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def source(actual, original):
    expected_original, expected_actual = LEAVES[SOURCE]
    require(blob(actual) == expected_actual and blob(original) == expected_original,
            "unreviewed exec-server Darwin source or original bytes")
    require(actual.count(MODULE) == 1 and actual.count(ACTUAL_READ) == 1,
            "reviewed exec-server Darwin source splice changed")
    restored = actual.replace(MODULE, b"", 1).replace(ACTUAL_READ, ORIGINAL_READ, 1)
    require(restored == original, "Darwin source inverse did not recover the complete original")
    return {"path": DEPENDENCY + "/" + SOURCE, "actual_blob": expected_actual,
            "original_blob": expected_original, "actual_sha256": hashlib.sha256(actual).hexdigest(),
            "original_sha256": hashlib.sha256(original).hexdigest(), "exact_splices": 2,
            "linux_candidates": ["final_path"], "linux_denial_predicate": "D || !A"}


def _darwin_tree(relative, expected, actual, listing):
    require((relative, expected, actual) == (DEPENDENCY, ORIGINAL_TREE, ACTUAL_TREE),
            "unreviewed exec-server Darwin dependency projection")
    inverse = listing
    projected = []
    for path, (old, new) in LEAVES.items():
        new_record = f"100644 blob {new}\t{path}\0".encode()
        require(inverse.count(new_record) == 1, "reviewed Darwin dependency leaf changed: " + path)
        old_record = f"100644 blob {old}\t{path}\0".encode() if old else b""
        inverse = inverse.replace(new_record, old_record, 1)
        projected.append({"path": path, "mode": "100644", "actual_blob": new,
                          "original_blob": old})
    wine = identity._exec_server_test_projection(relative, expected, INTERMEDIATE_TREE, inverse)
    # The strict original parser above admits every unchanged record and rejects
    # collisions/duplicates. These exact three records are its only inverse delta.
    entries = {}
    for row in listing[:-1].split(b"\0"):
        header, name = row.split(b"\t", 1)
        mode, kind, digest = header.decode().split(" ")
        require(kind == "blob", "invalid reviewed dependency object")
        entries[name.decode()] = (mode, digest)
    require(len(entries) == 144 and identity._dependency_tree_digest(entries) == ACTUAL_TREE,
            "complete actual Darwin dependency tree changed")
    return {"schema": "codex.hia.path-dependency-darwin-projection.v1",
            "dependency": relative, "actual_tree": actual, "original_tree": expected,
            "leaf_count": 144, "intermediate_tree": INTERMEDIATE_TREE,
            "projected_original_tree": wine["projected_original_tree"],
            "projection": projected, "original_wine_projection": wine}

# The Windows test runfiles successor changes only this Bazel declaration.
# Neither Rust source, Cargo declarations nor the independently built original
# Cargo graph is replaced. The prior full Darwin and Wine inverses remain exact.
BAZEL_TREE = "6a1d154613ad129ed7720947930efc33bcee5f22"
BAZEL_OLD_BLOB = "edd3380811608c669440f20c0083b01fe60874a7"
BAZEL_NEW_BLOB = "29e18f0eff6d45536d58c8a17c94f161d1215b2e"


def tree(relative, expected, actual, listing):
    if actual != BAZEL_TREE:
        return _darwin_tree(relative, expected, actual, listing)
    require((relative, expected, actual) == (DEPENDENCY, ORIGINAL_TREE, BAZEL_TREE),
            "unreviewed exec-server Bazel test dependency projection")
    require(type(listing) is bytes and listing.endswith(b"\0"),
            "complete Bazel dependency listing is required")
    before = f"100644 blob {BAZEL_OLD_BLOB}\tBUILD.bazel\0".encode()
    after = f"100644 blob {BAZEL_NEW_BLOB}\tBUILD.bazel\0".encode()
    require(listing.count(after) == 1 and before not in listing,
            "reviewed Bazel test declaration changed")
    inverse = listing.replace(after, before, 1)
    prior = _darwin_tree(relative, expected, ACTUAL_TREE, inverse)
    require(inverse.replace(before, after, 1) == listing,
            "Bazel test declaration forward replay differs")
    entries = {}
    for row in listing[:-1].split(b"\0"):
        header, name = row.split(b"\t", 1)
        mode, kind, digest = header.decode().split(" ")
        require(kind == "blob" and name.decode() not in entries,
                "invalid or duplicate Bazel dependency leaf")
        entries[name.decode()] = (mode, digest)
    require(len(entries) == prior["leaf_count"]
            and identity._dependency_tree_digest(entries) == BAZEL_TREE,
            "complete Bazel test dependency tree changed")
    return {"schema": "codex.hia.path-dependency-bazel-test-projection.v1",
            "dependency": relative, "actual_tree": actual, "original_tree": expected,
            "leaf_count": len(entries), "intermediate_tree": ACTUAL_TREE,
            "projected_original_tree": prior["projected_original_tree"],
            "projection": {"path": "BUILD.bazel", "mode": "100644",
                           "actual_blob": BAZEL_NEW_BLOB, "original_blob": BAZEL_OLD_BLOB},
            "runtime_source_and_cargo_unchanged": True,
            "original_darwin_projection": prior}
