"""Materialize complete immutable sources, never extracted semantic functions."""
import hashlib
import json
from pathlib import Path
import tarfile
import tomllib

from .common import binding, clean_identity, git, require, sha

BASE = "a2014bc6bfa1c1c9957edb3f14f8ae7d9ddcc095"
CRATE = "codex-rs/utils/string"
CRATE_TREE = "f01ec1e932152ed6ad539dbb19bb7cb9cab419ac"
CATALOG_SHA = "d43112f8dfeea832e674a87885211f6ee9bf0a72b092d6483a38a639bb37279b"
LIB_SHA = "5a48256f2f429170d845803602434bfbdf1fbd130e9fa99375b10074efff86c6"
MODULE_BLOCK = '// BEGIN HIA UUID FIND MODULE\n#[cfg(feature = "hia-native")]\nmod hia_native_uuid;\n#[cfg(feature = "hia-native")]\npub use hia_native_uuid::find_uuids;\n// END HIA UUID FIND MODULE\n'
GUARD_BLOCK = '// BEGIN HIA UUID FIND ORIGINAL GUARD\n#[cfg(not(feature = "hia-native"))]\n// END HIA UUID FIND ORIGINAL GUARD\n'

COMPATIBILITY_TEST_BLOCK = '// BEGIN HIA UUID COMPATIBILITY TESTS\n#[cfg(test)]\n#[path = "uuid_tests.rs"]\nmod uuid_tests;\n// END HIA UUID COMPATIBILITY TESTS\n'


# Exact later additions are removed only to recover the immutable UUID baseline.
# The complete original library hash and byte comparison remain authoritative.
OUTPUT_LINES_ROUTING_BLOCKS = (
    "#[cfg(feature = \"hia-native\")]\nmod hia_native_output_lines;\n",
    "/// Count lines with the same semantics as [`str::lines`].\npub fn count_lines(s: &str) -> usize {\n    #[cfg(feature = \"hia-native\")]\n    {\n        hia_native_output_lines::count_lines(s)\n    }\n    #[cfg(not(feature = \"hia-native\"))]\n    {\n        s.lines().count()\n    }\n}\n\n",
    "#[cfg(test)]\n#[path = \"output_lines_tests.rs\"]\nmod output_lines_tests;\n\n",
)


def catalog():
    path = Path(__file__).with_name("sources.json")
    require(sha(path) == CATALOG_SHA, "the complete immutable source catalog changed")
    result = json.loads(path.read_bytes())
    require(result["commit"] == BASE and result["crate_tree"] == CRATE_TREE
            and len(result["original_files"]) == 15 and len(result["regex_files"]) == 23,
            "whole-source scope changed")
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
            "the whole original utils/string tree differs")
    rows = git(repo, "ls-tree", "-r", "-z", BASE, CRATE).split(b"\0")
    entries = {}
    for row in filter(None, rows):
        meta, path = row.split(b"\t", 1)
        mode, kind, blob = meta.decode().split()
        require(mode == "100644" and kind == "blob", "unsupported immutable source entry")
        name = path.decode().removeprefix(CRATE + "/")
        entries[name] = blob
    require(entries == {name: row["git_blob"] for name, row in cat["original_files"].items()},
            "the full 15-file original inventory differs")
    destination.mkdir()
    for name, blob in entries.items():
        raw = git(repo, "cat-file", "blob", blob)
        require(hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest() == blob,
                "original Git blob hash disagrees with its bytes")
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    verify_tree(destination, cat["original_files"])
    return {"commit": BASE, "crate_tree": CRATE_TREE, "root": str(destination),
            "complete_original_files": cat["original_files"], "full_original_file_count": 15}


def producing_source(producer, original):
    original_manifest = original / "Cargo.toml"
    require((producer / CRATE / "Cargo.toml").read_bytes() == original_manifest.read_bytes(),
            "original dependency/feature declarations changed")
    path = producer / CRATE / "src/lib.rs"
    raw = path.read_bytes()
    routing_blocks = (
        MODULE_BLOCK,
        GUARD_BLOCK,
        '#[cfg(feature = "hia-native")]\nmod hia_native_truncate;\n',
        COMPATIBILITY_TEST_BLOCK,
        *OUTPUT_LINES_ROUTING_BLOCKS,
    )
    for text in routing_blocks:
        block = text.encode()
        require(raw.count(block) == 1, "whole-library routing block missing or duplicated")
        raw = raw.replace(block, b"", 1)
    require(hashlib.sha256(raw).hexdigest() == LIB_SHA and raw == (original / "src/lib.rs").read_bytes(),
            "routing inverse did not recover the entire original library")
    return {"source": binding(path), "restored_original_sha256": LIB_SHA,
            "restored_bytes": len(raw), "exact_blocks_removed": len(routing_blocks)}


def registry_source(producer, package, destination):
    cat = catalog()
    expected = cat["regex_package"]
    lock = tomllib.loads((producer / "codex-rs/Cargo.lock").read_text())
    rows = [row for row in lock["package"] if row["name"] == "regex-lite"]
    require(rows == [expected], "actual locked regex version/source/checksum changed")
    require(package["name"] == expected["name"] and package["version"] == expected["version"]
            and package["source"] == expected["source"], "Cargo selected another regex package")
    current = Path(package["manifest_path"]).resolve(strict=True).parent
    archive = current.parent.parent.parent / "cache" / current.parent.name / "regex-lite-0.1.8.crate"
    require(sha(archive) == expected["checksum"], "actual registry archive differs from Cargo.lock")
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as stream:
        entries = {}
        for member in stream.getmembers():
            require(member.isfile() or member.isdir(), "unsupported locked registry archive member")
            require(member.name.startswith("regex-lite-0.1.8/") and ".." not in Path(member.name).parts,
                    "locked registry archive path escapes its root")
            if not member.isfile():
                continue
            name = member.name.removeprefix("regex-lite-0.1.8/")
            require(name not in entries, "duplicate locked registry archive member")
            raw = stream.extractfile(member).read()
            entries[name] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as output:
                output.write(raw)
            require((current / name).read_bytes() == raw, "actual Cargo regex source differs from complete locked archive")
        require(entries == cat["regex_files"], "the complete 23-file regex inventory differs")
    verify_tree(destination, cat["regex_files"])
    return {"package": expected, "actual_registry_root": str(current), "archive": binding(archive),
            "root": str(destination), "files": cat["regex_files"],
            "actual_source_bindings": [binding(current / name) for name in sorted(entries)]}
