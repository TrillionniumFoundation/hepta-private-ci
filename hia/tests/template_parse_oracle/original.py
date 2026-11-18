"""Recover the complete immutable four-file crate, including parse and render."""
import hashlib
import json
from pathlib import Path

from .common import binding, clean_identity, git, require, sha

BASE = "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095"
CRATE = "codex-rs/utils/template"
CRATE_TREE = "239023ac5b71e7cd40b23bff31cbf3e36c59a8c5"
CATALOG_SHA = "c5fd2255ec086eee74b9af10763360d836a893e1b7eac308600a6864141a8e17"
LIB_SHA = "f930640a38e4ed882274397f6f2ac2105c3aac7891269b7b1edf39393b5d80cf"
FEATURE_BLOCK = '[features]\nhia-native = []\n\n'
BUILD_SOURCE = 'include!("../../../hia/cargo_build.rs");\n\nfn main() {\n    link_native("template_parse");\n    link_native("template_render");\n    link_native("template_index");\n}\n'


def catalog():
    path = Path(__file__).with_name("sources.json")
    require(sha(path) == CATALOG_SHA, "the complete immutable source catalog changed")
    result = json.loads(path.read_bytes())
    require(result["commit"] == BASE and result["crate_tree"] == CRATE_TREE
            and len(result["original_files"]) == 4 and len(result["original_tests"]) == 14
            and len(result["routing_blocks"]) == 15 and len(result["registry_packages"]) == 3
            and sum(len(item["files"]) for item in result["registry_packages"].values()) == 54,
            "the whole-source scope differs")
    return result


def verify_tree(root, records):
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    require(actual == set(records), "the complete immutable source inventory changed")
    for name, record in records.items():
        path = root / name
        require(not path.is_symlink() and path.stat().st_size == record["bytes"]
                and sha(path) == record["sha256"], "complete source bytes differ: " + name)


def snapshot(repo, destination):
    cat = catalog()
    require(clean_identity(repo)["head"] == BASE, "original checkout must be the clean immutable a201 revision")
    require(git(repo, "rev-parse", f"{BASE}:{CRATE}").decode().strip() == CRATE_TREE,
            "the whole original template tree differs")
    entries = {}
    for row in filter(None, git(repo, "ls-tree", "-r", "-z", BASE, CRATE).split(b"\0")):
        meta, path = row.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        require(mode == "100644" and kind == "blob", "unsupported immutable source entry")
        name = path.decode().removeprefix(CRATE + "/")
        require(name not in entries, "duplicate immutable source entry")
        entries[name] = blob
    require(entries == {name: row["git_blob"] for name, row in cat["original_files"].items()},
            "the entire four-file original inventory differs")
    destination.mkdir()
    for name, blob in entries.items():
        raw = git(repo, "cat-file", "blob", blob)
        require(hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == blob,
                "original Git blob identity differs from its bytes")
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    verify_tree(destination, cat["original_files"])
    return {"commit": BASE, "crate_tree": CRATE_TREE, "root": str(destination),
            "complete_original_files": cat["original_files"], "full_original_file_count": 4}


def producing_source(producer, original):
    cat = catalog()
    manifest = producer / CRATE / "Cargo.toml"
    raw_manifest = manifest.read_bytes()
    feature = FEATURE_BLOCK.encode()
    require(raw_manifest.count(feature) == 1 and raw_manifest.replace(feature, b"", 1)
            == (original / "Cargo.toml").read_bytes(), "exact manifest inverse failed")
    build = producer / CRATE / "build.rs"
    require(build.read_text() == BUILD_SOURCE, "the real template build entry changed")
    path = producer / CRATE / "src/lib.rs"
    raw = path.read_bytes()
    for row in cat["routing_blocks"]:
        block = row["text"].encode()
        require(hashlib.sha256(block).hexdigest() == row["sha256"] and raw.count(block) == 1,
                "whole-library routing block missing, changed or duplicated")
        raw = raw.replace(block, b"", 1)
    require(hashlib.sha256(raw).hexdigest() == LIB_SHA and raw == (original / "src/lib.rs").read_bytes(),
            "routing inverse did not recover the entire original library")
    return {"source": binding(path), "manifest": binding(manifest), "build_entry": binding(build),
            "restored_original_sha256": LIB_SHA, "restored_bytes": len(raw),
            "exact_library_blocks_removed": 15, "exact_manifest_blocks_removed": 1,
            "complete_original_render_and_tests_restored": True}
