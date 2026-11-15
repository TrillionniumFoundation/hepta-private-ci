"""Bind every actual registry library source to both original and producer locks."""
import hashlib
from pathlib import Path
import tarfile
import tomllib

from .common import binding, git, require, sha, verify
from .original import BASE


def sources(producer, original_repo, packages, graphs):
    current_lock = producer / "codex-rs/Cargo.lock"
    original_raw = git(original_repo, "show", BASE + ":codex-rs/Cargo.lock")
    original = tomllib.loads(original_raw.decode())["package"]
    current = tomllib.loads(current_lock.read_text())["package"]
    used = {unit["package_id"] for graph in graphs.values() for unit in graph["units"]}
    records = {}
    for package_id in sorted(used):
        package = packages[package_id]
        if package["source"] is None:
            continue
        require(package["source"] == "registry+https://github.com/rust-lang/crates.io-index",
                "unsupported nonregistry dependency source")
        select = lambda rows: [p for p in rows if p["name"] == package["name"] and p["version"] == package["version"]]
        old, new = select(original), select(current)
        require(len(old) == len(new) == 1 and old == new and new[0]["source"] == package["source"],
                "an actual registry dependency differs from the whole original lock")
        source = Path(package["manifest_path"]).resolve(strict=True).parent
        prefix = package["name"] + "-" + package["version"]
        archive = source.parent.parent.parent / "cache" / source.parent.name / (prefix + ".crate")
        require(sha(archive) == new[0]["checksum"], "actual dependency archive differs from Cargo.lock")
        files = {}
        with tarfile.open(archive, "r:gz") as stream:
            for member in stream.getmembers():
                require(member.isdir() or member.isfile(), "unsupported registry archive entry")
                require(member.name.startswith(prefix + "/") and ".." not in Path(member.name).parts,
                        "registry source path escapes the complete crate")
                if not member.isfile():
                    continue
                name = member.name.removeprefix(prefix + "/")
                require(name not in files, "duplicate complete registry source entry")
                data = stream.extractfile(member).read()
                record = binding(source / name)
                require(record["bytes"] == len(data) and record["sha256"] == hashlib.sha256(data).hexdigest(),
                        "actual registry source differs from its complete locked archive")
                files[name] = record
        records[package_id] = {"lock": new[0], "archive": binding(archive),
                               "actual_manifest": binding(package["manifest_path"]), "files": files}
    return {"current_lock": binding(current_lock), "original_lock_bytes": len(original_raw),
            "original_lock_sha256": hashlib.sha256(original_raw).hexdigest(), "packages": records}


def verify_sources(record):
    verify(record["current_lock"])
    for package in record["packages"].values():
        for item in (package["archive"], package["actual_manifest"], *package["files"].values()):
            verify(item)
