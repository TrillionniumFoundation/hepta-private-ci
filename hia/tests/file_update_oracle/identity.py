"""Immutable whole-crate source and actual native build admission."""
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib

BASE = "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095"
CRATE = "codex-rs/apply-patch"
CRATE_TREE = "f3e0f3637151b2fe823d25e643cb69b21b6295b3"
OWNER_BLOB = "b95270b799b31149bd19bf5825e4f68b1d97e954"
OWNER_SHA256 = "6f45aabc6d1bb103875df8c8529558a49587db103b1a26aa633b8ea7ada570f2"
RUSTC_SHA256 = "4a84e05991ad6f2a84c1361c29b52b38c390365bd1fc269b1936c88d482a8928"
RUSTC_COMMIT = "31fca3adb283cc9dfd56b49cdee9a96eb9c96ffd"
REQUIRED = frozenset(("anyhow", "codex_exec_server", "codex_utils_absolute_path",
    "codex_utils_path_uri", "similar", "thiserror", "tokio", "tree_sitter",
    "tree_sitter_bash", "assert_cmd", "assert_matches", "codex_utils_cargo_bin",
    "pretty_assertions", "tempfile"))
EXTRA = (
    "codex-rs/Cargo.toml", "codex-rs/Cargo.lock", "codex-rs/rust-toolchain.toml",
    "justfile", "scripts/run-nextest.py", "scripts/just-shell.py", "hia/cargo_build.rs",
    "codex-rs/exec-server/Cargo.toml", "codex-rs/exec-server/src/lib.rs",
    "codex-rs/exec-server/src/local_file_system.rs", "codex-rs/file-system/Cargo.toml",
    "codex-rs/file-system/src/lib.rs", "codex-rs/utils/path-uri/Cargo.toml",
    "codex-rs/utils/path-uri/src/lib.rs", "codex-rs/utils/absolute-path/Cargo.toml",
    "codex-rs/utils/absolute-path/src/lib.rs", "codex-rs/utils/cargo-bin/Cargo.toml",
)
TYPE_SOURCES = (
    "codex-rs/exec-server/src/lib.rs", "codex-rs/exec-server/src/local_file_system.rs",
    "codex-rs/file-system/src/lib.rs", "codex-rs/utils/path-uri/src/lib.rs",
    "codex-rs/utils/absolute-path/src/lib.rs",
)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def clean_identity(repo):
    head = git(repo, "rev-parse", "HEAD").decode().strip()
    if git(repo, "status", "--porcelain", "--untracked-files=all").strip():
        raise RuntimeError("actual owner qualification requires a clean producing checkout")
    return {"commit": head, "tree": git(repo, "rev-parse", "HEAD^{tree}").decode().strip()}


def outside(path, roots):
    path = Path(path).resolve()
    if any(path == root or path.is_relative_to(root) for root in roots):
        raise RuntimeError("generated oracle output must be outside all source checkouts")
    return path


def snapshot(repo, destination, *, require_checkout=True):
    if require_checkout and clean_identity(repo)["commit"] != BASE:
        raise RuntimeError("the complete original checkout must be exactly the pinned a201 commit")
    tree = git(repo, "rev-parse", f"{BASE}:{CRATE}").decode().strip()
    if tree != CRATE_TREE:
        raise RuntimeError("the complete original crate directory identity changed")
    entries = git(repo, "ls-tree", "-r", "-z", BASE, CRATE).split(b"\0")
    records = {}
    for entry in filter(None, entries):
        info, name = entry.split(b"\t", 1)
        mode, kind, blob = info.decode().split()
        path = name.decode()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise RuntimeError("unsupported original source entry")
        records[path] = {"blob": blob, "mode": mode}
    if len(records) != 104:
        raise RuntimeError("the whole original crate file inventory changed")
    for path in EXTRA:
        records[path] = {"blob": git(repo, "rev-parse", f"{BASE}:{path}").decode().strip(),
                         "mode": "100644"}
    if len(records) != 121:
        raise RuntimeError("the complete source/type/build input set changed")
    destination.mkdir(parents=True, exist_ok=False)
    for path, record in sorted(records.items()):
        data = git(repo, "show", f"{BASE}:{path}")
        computed = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
        if computed != record["blob"]:
            raise RuntimeError(f"original Git blob bytes differ: {path}")
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        record.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    owner = records[CRATE + "/src/file_update.rs"]
    if (owner["blob"], owner["sha256"], owner["bytes"]) != (OWNER_BLOB, OWNER_SHA256, 12365):
        raise RuntimeError("the complete original file_update.rs changed")
    original_manifest = tomllib.loads((destination / CRATE / "Cargo.toml").read_text())
    names = {name.replace("-", "_") for section in ("dependencies", "dev-dependencies")
             for name in original_manifest[section]}
    if names != REQUIRED:
        raise RuntimeError("the complete original dependency inventory changed")
    workspace = tomllib.loads((destination / "codex-rs/Cargo.toml").read_text())["workspace"]
    path_trees = {}
    for section in ("dependencies", "dev-dependencies"):
        for name, spec in original_manifest[section].items():
            resolved = workspace["dependencies"][name] if spec.get("workspace") else spec
            if isinstance(resolved, dict) and "path" in resolved:
                relative = "codex-rs/" + resolved["path"]
                path_trees[relative] = git(repo, "rev-parse", f"{BASE}:{relative}").decode().strip()
    result = {"commit": BASE, "tree": git(repo, "rev-parse", f"{BASE}^{{tree}}").decode().strip(),
              "crate_tree": tree, "crate_files": 104, "files": records,
              "path_dependency_trees": path_trees,
              "complete_checkout_validated": require_checkout}
    return result


def verify_sources(snapshot_root, manifest):
    actual = {str(path.relative_to(snapshot_root)) for path in snapshot_root.rglob("*") if path.is_file()}
    if actual != set(manifest["files"]):
        raise RuntimeError("the complete original source file inventory changed")
    for path, record in manifest["files"].items():
        file = snapshot_root / path
        if file.stat().st_size != record["bytes"] or sha(file) != record["sha256"]:
            raise RuntimeError(f"an original source input changed: {path}")

ROUTING_BLOCKS = {
    "file_update_seek_import": "// BEGIN HIA_NATIVE file_update_seek_import\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA_NATIVE file_update_seek_import\n",
    "file_update_replacement_import": "// BEGIN HIA_NATIVE file_update_replacement_import\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA_NATIVE file_update_replacement_import\n",
    "file_update_source_file_import": "// BEGIN HIA_NATIVE file_update_source_file_import\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA_NATIVE file_update_source_file_import\n",
    "file_update_legacy_contents": "    // BEGIN HIA_NATIVE file_update_legacy_contents\n    #[cfg(not(feature = \"hia-native\"))]\n    // END HIA_NATIVE file_update_legacy_contents\n",
    "file_update_native_contents": "    // BEGIN HIA_NATIVE file_update_native_contents\n    #[cfg(feature = \"hia-native\")]\n    let new_contents = crate::hia_native_file_update::new_contents(\n        &original_contents,\n        &path_text,\n        chunks,\n        update_file_mode,\n    )?;\n    // END HIA_NATIVE file_update_native_contents\n",
    "file_update_legacy_plan": "// BEGIN HIA_NATIVE file_update_legacy_plan\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA_NATIVE file_update_legacy_plan\n",
    "file_update_legacy_apply": "// BEGIN HIA_NATIVE file_update_legacy_apply\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA_NATIVE file_update_legacy_apply\n",
    "unified_diff_import": "// BEGIN HIA_NATIVE unified_diff_import\n#[cfg(not(feature = \"hia-native\"))]\n// END HIA_NATIVE unified_diff_import\n",
    "unified_diff_text": "    // BEGIN HIA_NATIVE unified_diff_text\n    #[cfg(not(feature = \"hia-native\"))]\n    // END HIA_NATIVE unified_diff_text\n",
    "unified_diff_render": "    // BEGIN HIA_NATIVE unified_diff_render\n    #[cfg(not(feature = \"hia-native\"))]\n    // END HIA_NATIVE unified_diff_render\n",
    "unified_diff_native": "    // BEGIN HIA_NATIVE unified_diff_native\n    #[cfg(feature = \"hia-native\")]\n    let unified_diff = crate::hia_native_unified_diff::unified_diff(\n        &original_contents,\n        &new_contents,\n        context,\n        crate::hia_native_unified_diff_policy::ARITHMETIC_POLICY,\n    );\n    // END HIA_NATIVE unified_diff_native\n"
}


def recover_owner(producer):
    path = producer / CRATE / "src/file_update.rs"
    original = path.read_bytes()
    restored = original
    for name, value in ROUTING_BLOCKS.items():
        encoded = value.encode()
        if restored.count(encoded) != 1:
            raise RuntimeError(f"exact native routing block changed or duplicated: {name}")
        restored = restored.replace(encoded, b"", 1)
    if b"HIA_NATIVE" in restored:
        raise RuntimeError("an unreviewed native routing block remains")
    blob = hashlib.sha1(f"blob {len(restored)}\0".encode() + restored).hexdigest()
    digest = hashlib.sha256(restored).hexdigest()
    if (len(restored), blob, digest) != (12365, OWNER_BLOB, OWNER_SHA256):
        raise RuntimeError("inverse routing does not recover the complete pinned original owner")
    return {"actual_owner_sha256": hashlib.sha256(original).hexdigest(),
            "exact_blocks_removed": len(ROUTING_BLOCKS), "restored_bytes": len(restored),
            "restored_git_blob": blob, "restored_sha256": digest}


# One reviewed Bazel-only fixture delta; the Linux Cargo library inputs are unchanged.
# Keep the original a201 tree and every other path dependency strictly pinned.
_EXEC_SERVER_TEST_PROJECTION = {
    "dependency": "codex-rs/exec-server",
    "original_tree": "6e7fb23cad63c4d9cd0c7ae24faae16c16def394",
    "actual_tree": "040d2b09f7f1ed6dcf930c0c6032868e32b52764",
    "path": "testing/wine_remote_test_runner.rs",
    "mode": "100644",
    "original_blob": "6e73e68e9b6c7237181beca458741045b3dfe972",
    "actual_blob": "41cd6bfc1531c414b135936480ae6c37985de772",
    "leaf_count": 143,
}


def _dependency_tree_digest(entries):
    root = {}
    for path, entry in entries.items():
        parts = path.split("/")
        node = root
        for part in parts[:-1]:
            child = node.setdefault(part, {})
            if not isinstance(child, dict):
                raise RuntimeError("path dependency has a file/directory collision")
            node = child
        if parts[-1] in node:
            raise RuntimeError("path dependency has a file/directory collision")
        node[parts[-1]] = entry

    def digest(node):
        chunks = []
        ordered = sorted(node.items(), key=lambda item: item[0].encode("utf-8") +
                         (b"/" if isinstance(item[1], dict) else b""))
        for name, entry in ordered:
            mode, blob = ("40000", digest(entry)) if isinstance(entry, dict) else entry
            chunks.append(mode.encode("ascii") + b" " + name.encode("utf-8") +
                          b"\0" + bytes.fromhex(blob))
        payload = b"".join(chunks)
        return hashlib.sha1(f"tree {len(payload)}\0".encode() + payload).hexdigest()

    return digest(root)


def _exec_server_test_projection(relative, expected, actual, listing):
    pin = _EXEC_SERVER_TEST_PROJECTION
    if (relative, expected, actual) != (
            pin["dependency"], pin["original_tree"], pin["actual_tree"]):
        raise RuntimeError("unreviewed path dependency projection")
    if not listing.endswith(b"\0"):
        raise RuntimeError("path dependency leaf listing is incomplete")
    entries = {}
    for record in listing[:-1].split(b"\0"):
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, kind, blob = header.decode("ascii").split(" ")
            path = raw_path.decode("utf-8")
        except (UnicodeError, ValueError) as error:
            raise RuntimeError("invalid path dependency leaf record") from error
        if (kind != "blob" or mode not in {"100644", "100755"} or len(blob) != 40
                or any(char not in "0123456789abcdef" for char in blob)
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or any(char in path for char in "\t\r\n\\") or path in entries):
            raise RuntimeError("invalid or duplicate path dependency leaf")
        entries[path] = (mode, blob)
    if len(entries) != pin["leaf_count"]:
        raise RuntimeError("the complete path dependency leaf count changed")
    if entries.get(pin["path"]) != (pin["mode"], pin["actual_blob"]):
        raise RuntimeError("the exact reviewed test-only leaf changed")
    if _dependency_tree_digest(entries) != actual:
        raise RuntimeError("the complete actual path dependency tree changed")
    projected = dict(entries)
    projected[pin["path"]] = (pin["mode"], pin["original_blob"])
    inverse = _dependency_tree_digest(projected)
    if inverse != expected:
        raise RuntimeError("test-only inverse did not recover the complete original tree")
    return {
        "schema": "codex.hia.path-dependency-test-projection.v1",
        "dependency": relative, "actual_tree": actual, "original_tree": expected,
        "leaf_count": len(entries), "projected_original_tree": inverse,
        "projection": {
            "path": pin["path"], "mode": pin["mode"],
            "actual_blob": pin["actual_blob"], "original_blob": pin["original_blob"],
        },
    }



# Exact candidate admission, supported by the independent cross-lock campaign.
# This is not a wildcard dependency exception or a claim of formal qualification.
_REVIEWED_4280 = {
    "commit": "4280cfe7e4ab7fca7371e499482b6adff7ac31de",
    "tree": "55c3c10cce3580fba1a7c0191bde4d9e5540c8d9",
    "identity_blob": "2843182cf7c2b88a4ef0fc53c902f813f8d58046",
    "cross_lock_ledger_sha256": "0e3eedc18d5a4e92bcfde5fffa3af7c47be5f1f1ae0f1352912ea8560383e14e",
    "file_observations_sha256": "2e0dc35e48acf012100503722ee994b47540cfa8b0b151359016941f339a9655",
    "effects_observations_sha256": "258c518712fd18c0a34f6e4853b31c69b0e42991fae6bde922851c32dcf5a534",
}
_REVIEWED_4280_FILES = {
    "codex-rs/Cargo.toml": (
        "344073ad2f842700540b6b76a412740dbca7453c9303c94cc1ab60979665e1b7",
        "98060794c2dca51858d03c5392147e3ab45df9009c9c8083514948d53ac92a3e"),
    "codex-rs/Cargo.lock": (
        "70e7aaa26f47946700fd8d2bc8dfdcbd9458fbf56891826a32b168cd24fbc955",
        "a15c40f90ec29252277f2803f0cf4f01d660d6ce9a571feca9ecd8ba78d379fa"),
    "codex-rs/exec-server/src/local_file_system.rs": (
        "f5210cc12b474ebb1983737ed8ee141cc10a033cc457bc22fe869fb1e967c061",
        "a4b3d87823a0858c0495d34c1c066e6c67b773762ce561807e552fb295ee6538"),
}
_REVIEWED_4280_EXEC_TREE = "4ded82432f79ba4191223cb2f88448dd560a31d0"
_REVIEWED_4280_EXEC_LEAVES = {
    "src/local_file_system.rs": (
        "ccfc1f65fb1c2cb9aa0e7acb632265de34b34f16",
        "0a1be1295388173a8aebc3e81980e3edecb9f12a"),
    "src/local_file_system_authorized_read_tests.rs": (
        "c1223c43044977c694bafba42815740140401c5e",
        "8d16d6e8ab4bb17d63ed850d92af8f86c4e5c588"),
    "src/local_file_system_macos.rs": (
        "587f1b55bba4754c66b31b3b0bb677ba525e3927", None),
}


def _project_tree(repo, tree, changes):
    """Inverse-project only named, exact leaves; bind every untouched sibling."""
    listing = git(repo, "ls-tree", "-z", tree)
    if not listing.endswith(b"\0"):
        raise RuntimeError("incomplete candidate tree listing")
    entries = {}
    for record in listing[:-1].split(b"\0"):
        header, name = record.split(b"\t", 1)
        mode, kind, blob = header.split(b" ")
        if (not name or name in {b".", b".."} or b"/" in name or name in entries
                or len(blob) != 40 or any(c not in b"0123456789abcdef" for c in blob)
                or (mode, kind) not in {
                    (b"040000", b"tree"), (b"100644", b"blob"),
                    (b"100755", b"blob"), (b"120000", b"blob"),
                    (b"160000", b"commit")}):
            raise RuntimeError("invalid candidate tree entry")
        entries[name] = (mode, kind, blob)

    def digest(items):
        payload = b"".join(
            mode.lstrip(b"0") + b" " + name + b"\0" + bytes.fromhex(blob.decode("ascii"))
            for name, (mode, kind, blob) in sorted(
                items.items(), key=lambda item: item[0] +
                (b"/" if item[1][1] == b"tree" else b"")))
        return hashlib.sha1(f"tree {len(payload)}\0".encode() + payload).hexdigest()

    if digest(entries) != tree:
        raise RuntimeError("candidate tree bytes do not match Git identity")
    by_child = {}
    for path, value in changes.items():
        head, _, tail = path.partition("/")
        by_child.setdefault(head.encode(), {})[tail] = value
    for name, group in by_child.items():
        if name not in entries:
            raise RuntimeError("reviewed projection leaf absent")
        mode, kind, actual = entries[name]
        if "" in group:
            before, after = group[""]
            if len(group) != 1 or (mode, kind, actual) != (
                    b"100644", b"blob", before.encode()):
                raise RuntimeError("reviewed projection leaf differs")
            if after is None:
                del entries[name]
            else:
                entries[name] = (mode, kind, after.encode())
        else:
            if kind != b"tree":
                raise RuntimeError("reviewed projection parent is not a tree")
            entries[name] = (mode, kind, _project_tree(
                repo, actual.decode(), group).encode())
    return digest(entries)


def _reviewed_4280_root(producer, current):
    path = "hia/tests/file_update_oracle/identity.py"
    code = (producer / path).read_bytes()
    blob = hashlib.sha1(f"blob {len(code)}\0".encode() + code).hexdigest()
    inverse = _project_tree(producer, current["tree"], {
        path: (blob, _REVIEWED_4280["identity_blob"]),
    })
    if inverse != _REVIEWED_4280["tree"]:
        raise RuntimeError("unreviewed producing tree; exact 4280 inverse required")
    return inverse


def _reviewed_4280_exec_projection(producer, relative, expected, actual):
    pin = _EXEC_SERVER_TEST_PROJECTION
    if (relative, expected, actual) != (
            pin["dependency"], pin["original_tree"], _REVIEWED_4280_EXEC_TREE):
        raise RuntimeError("unreviewed path dependency projection")
    listing = git(producer, "ls-tree", "-r", "-z", actual)
    if not listing.endswith(b"\0") or len(listing[:-1].split(b"\0")) != 144:
        raise RuntimeError("complete reviewed exec-server leaf inventory differs")
    wine_tree = _project_tree(producer, actual, _REVIEWED_4280_EXEC_LEAVES)
    if wine_tree != pin["actual_tree"]:
        raise RuntimeError("macOS inverse does not recover the reviewed Wine tree")
    inverse = _project_tree(producer, actual, {
        **_REVIEWED_4280_EXEC_LEAVES,
        pin["path"]: (pin["actual_blob"], pin["original_blob"]),
    })
    if inverse != expected:
        raise RuntimeError("complete inverse does not recover the original dependency")
    return {"schema": "codex.hia.path-dependency-reviewed-projection.v2",
            "dependency": relative, "actual_tree": actual,
            "original_tree": expected, "leaf_count": 144,
            "projected_wine_tree": wine_tree, "projected_original_tree": inverse,
            "macos_leaves": {path: list(pair) for path, pair in _REVIEWED_4280_EXEC_LEAVES.items()},
            "wine_projection": pin}


def producer_inputs(producer, original_root, original_manifest):
    current = clean_identity(producer)
    # Equality to immutable originals rejects manifest/default-feature changes even
    # if an attacker updates a self-reported manifest SHA to match that change.
    matched = {}
    reviewed = {}
    paths = ("codex-rs/Cargo.toml", "codex-rs/Cargo.lock", CRATE + "/Cargo.toml", *TYPE_SOURCES)
    differences = {path: (sha(original_root / path), sha(producer / path))
                   for path in paths if sha(producer / path) != sha(original_root / path)}
    if differences:
        if (differences != _REVIEWED_4280_FILES or
                original_manifest["commit"] != BASE or
                original_manifest["crate_tree"] != CRATE_TREE):
            raise RuntimeError("unreviewed original dependency/type declaration change")
        reviewed = {**_REVIEWED_4280,
                    "projected_tree": _reviewed_4280_root(producer, current),
                    "reviewed_files": {path: list(pair) for path, pair in differences.items()}}
    for path in paths:
        if path not in differences:
            matched[path] = sha(producer / path)
    # The producing Actions checkout may be shallow. Baseline trees came from
    # the separate immutable original checkout, never from assumed local history.
    path_trees = {}
    projections = {}
    for relative, expected in original_manifest["path_dependency_trees"].items():
        actual = git(producer, "rev-parse", f"HEAD:{relative}").decode().strip()
        if actual != expected and reviewed:
            projections[relative] = _reviewed_4280_exec_projection(
                producer, relative, expected, actual)
        elif actual != expected:
            pin = _EXEC_SERVER_TEST_PROJECTION
            if (relative, expected, actual) != (
                    pin["dependency"], pin["original_tree"], pin["actual_tree"]):
                raise RuntimeError(f"real path dependency differs from its pinned original: {relative}")
            projections[relative] = _exec_server_test_projection(
                relative, expected, actual, git(producer, "ls-tree", "-r", "-z", actual))
        path_trees[relative] = actual
    result = {**current, "matched_original_files": matched, "path_dependency_trees": path_trees,
              "original_source_manifest": original_manifest["crate_tree"],
              "exact_routing_inverse": recover_owner(producer)}
    if projections:
        result["path_dependency_projections"] = projections
    if reviewed:
        result["reviewed_candidate"] = reviewed
    return result


def native_inputs(producer, library_dir):
    report_path = library_dir / "build.json"
    build = json.loads(report_path.read_text())
    if build.get("status") != "built" or build.get("compiler_fixed_point") is not True:
        raise RuntimeError("a real fixed-point native build is required")
    modules = {}
    for name in ("file_update", "seek_sequence", "source_file"):
        record = build["modules"][name]
        archive = library_dir / f"libcodex_hia_{name}.a"
        source = producer / "hia" / f"{name}.hepta"
        abi = record["codex_link_abi"]
        if record["source_sha256"] != sha(source) or abi["archive_sha256"] != sha(archive):
            raise RuntimeError(f"stale source/archive binding: {name}")
        if abi["symbol"] != f"codex_hia_{name}":
            raise RuntimeError(f"wrong actual native symbol: {name}")
        modules[name] = {"source_sha256": sha(source), "archive_sha256": sha(archive),
                         "symbol": abi["symbol"]}
    return {"build_report_sha256": sha(report_path), "modules": modules,
            "compiler_sha256": build["compiler_sha256"]}
