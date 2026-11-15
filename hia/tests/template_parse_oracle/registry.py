"""Verify all 54 original locked source files used by the three real test libraries."""
import hashlib
from pathlib import Path
import tarfile
import tomllib

from .common import binding, git, require, sha, verify
from .original import BASE, catalog


def sources(producer, original_repo, packages, graphs):
    current_lock = producer / "codex-rs/Cargo.lock"
    original_raw = git(original_repo, "show", BASE + ":codex-rs/Cargo.lock")
    original = tomllib.loads(original_raw.decode())["package"]
    current = tomllib.loads(current_lock.read_text())["package"]
    expected = catalog()["registry_packages"]
    used = {unit["package_id"] for graph in graphs.values() for unit in graph["units"]
            if packages[unit["package_id"]]["source"] is not None}
    require(used == set(expected), "actual registry library closure differs from the full original")
    records = {}
    for package_id in sorted(used):
        package, spec = packages[package_id], expected[package_id]
        require(package["source"] == "registry+https://github.com/rust-lang/crates.io-index",
                "unsupported nonregistry dependency source")
        select = lambda rows: [p for p in rows if p["name"] == package["name"] and p["version"] == package["version"]]
        old, new = select(original), select(current)
        require(old == new == [spec["lock"]] and new[0]["source"] == package["source"],
                "an actual test dependency differs from the immutable original/current locks")
        source = Path(package["manifest_path"]).resolve(strict=True).parent
        prefix = package["name"] + "-" + package["version"]
        archive = source.parent.parent.parent / "cache" / source.parent.name / (prefix + ".crate")
        require(sha(archive) == spec["lock"]["checksum"], "actual crate archive differs from both locks")
        files, observed = {}, {}
        with tarfile.open(archive, "r:gz") as stream:
            for member in stream.getmembers():
                require(member.isdir() or member.isfile(), "unsupported locked archive entry")
                require(member.name.startswith(prefix + "/") and ".." not in Path(member.name).parts,
                        "archive source path escapes the complete crate")
                if not member.isfile():
                    continue
                name = member.name.removeprefix(prefix + "/")
                require(name not in files, "duplicate complete registry source entry")
                data = stream.extractfile(member).read()
                item = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                record = binding(source / name)
                require({key: record[key] for key in item} == item,
                        "actual Cargo source differs from its full locked archive")
                files[name], observed[name] = record, item
        require(observed == spec["files"], "complete registry source inventory differs from the original")
        records[package_id] = {"lock": spec["lock"], "archive": binding(archive),
            "actual_manifest": binding(package["manifest_path"]), "files": files}
    require(sum(len(row["files"]) for row in records.values()) == 54, "complete registry file count differs")
    return {"current_lock": binding(current_lock), "original_lock_bytes": len(original_raw),
            "original_lock_sha256": hashlib.sha256(original_raw).hexdigest(), "packages": records,
            "complete_registry_files": 54, "actual_cargo_units": 3}


def verify_sources(record):
    verify(record["current_lock"])
    for package in record["packages"].values():
        for item in (package["archive"], package["actual_manifest"], *package["files"].values()):
            verify(item)
