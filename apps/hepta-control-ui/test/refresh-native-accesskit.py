#!/usr/bin/env python3
"""Verify the exact upstream source, then refresh all native AccessKit provenance.

Reads fixed Git objects only. No network, checkout mutation, source rewriting,
or dependency installation is performed. Default mode checks; --write updates
the diff, source manifest and separate installed dependency-notice manifest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import tomllib

REVISION = "405d578cdfd8496ee79020d24cfaac8c29a8a48f"
REPOSITORY = "https://github.com/AccessKit/accesskit"
ROOTS = ("common", "consumer", "platforms/atspi-common", "platforms/unix")
ROOT_FILES = ("Cargo.toml", "LICENSE-APACHE", "LICENSE-MIT", "LICENSE.chromium", "README.md")
CRATES = {"accesskit": "0.17.1", "accesskit_consumer": "0.26.0",
          "accesskit_atspi_common": "0.10.1", "accesskit_unix": "0.13.1"}
NOTICES = ("LICENSE-APACHE", "LICENSE-MIT", "LICENSE.chromium", "HEPTA_UPSTREAM.json",
           "HEPTA_PATCH.diff", "HEPTA_PATCH.md")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def git(repository, *args):
    result = subprocess.run(["git", "-C", str(repository), *args], stdin=subprocess.DEVNULL,
                            capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("Cannot read the exact upstream Git source: " + result.stderr.decode("utf-8", errors="replace"))
    return result.stdout


def original_files(repository):
    exact = git(repository, "rev-parse", REVISION + "^{commit}").decode().strip()
    if exact != REVISION:
        raise ValueError("Upstream commit identity differs")
    paths = git(repository, "ls-tree", "-r", "--name-only", REVISION, "--", *ROOTS, *ROOT_FILES).decode().splitlines()
    result = {}
    for path in sorted(paths):
        data = git(repository, "show", REVISION + ":" + path)
        data.decode("utf-8")
        result[path] = data
    return result


def current_files(vendor):
    paths = [vendor / name for name in ROOT_FILES]
    for root in ROOTS:
        for path in (vendor / root).rglob("*"):
            if path.is_symlink():
                raise ValueError("Vendored source cannot contain a symlink: " + str(path))
            if path.is_file():
                paths.append(path)
    if len(paths) > 256:
        raise ValueError("Unexpected source count; do not include build outputs in the vendor tree")
    result = {}
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Missing, indirect or unexpectedly large source: " + str(path))
        data = path.read_bytes()
        data.decode("utf-8")
        result[path.relative_to(vendor).as_posix()] = data
    return result


def source_diff(original, current):
    with tempfile.TemporaryDirectory(prefix="hepta-accesskit-diff-") as temporary:
        root = Path(temporary)
        for name, files in (("original", original), ("current", current)):
            for relative, data in files.items():
                path = root / name / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        result = subprocess.run(["git", "-c", "core.autocrlf=false", "diff", "--no-index",
                                 "--no-ext-diff", "--no-color", "--no-renames", "--text", "--unified=3",
                                 "--src-prefix=a/", "--dst-prefix=b/", "original", "current"],
                                cwd=root, stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        if result.returncode not in (0, 1):
            raise ValueError("Cannot produce complete upstream diff")
        lines = []
        for line in result.stdout.splitlines(keepends=True):
            if line.startswith((b"diff --git ", b"--- ", b"+++ ")):
                line = line.replace(b"a/original/", b"a/").replace(b"b/current/", b"b/")
                # Git uses the current-side name in both headers for new files.
                line = line.replace(b"a/current/", b"a/")
            lines.append(line)
        patch = b"".join(lines)
        applied = subprocess.run(["git", "apply", "--no-index", "-"], input=patch,
                                 cwd=root / "original", capture_output=True, timeout=30)
        if applied.returncode:
            raise ValueError("Generated provenance diff cannot reproduce the vendor: "
                             + applied.stderr.decode("utf-8", errors="replace"))
        reproduced = {path.relative_to(root / "original").as_posix(): path.read_bytes()
                      for path in (root / "original").rglob("*") if path.is_file()}
        if reproduced != current:
            raise ValueError("Generated provenance diff omitted or changed source bytes")
        return patch


def refresh(hepta, upstream, write):
    vendor = hepta / "codex-rs/third_party/accesskit-0.17.1"
    metadata_path = vendor / "HEPTA_UPSTREAM.json"
    previous = json.loads(metadata_path.read_bytes())
    if (previous.get("schema") != "hepta.vendored-source.v1" or previous.get("revision") != REVISION
            or previous.get("repository") != REPOSITORY or previous.get("crates") != CRATES):
        raise ValueError("Existing source manifest is not the exact original AccessKit source")
    original = original_files(upstream)
    recorded = {entry["path"]: entry for entry in previous["original_files"]}
    if set(recorded) != set(original) or len(recorded) != len(previous["original_files"]):
        raise ValueError("Original retained source list differs; source removals are not a formatting change")
    original_records = []
    for path, data in original.items():
        entry = {"path": path, "sha256": digest(data), "bytes": len(data)}
        if recorded[path] != entry:
            raise ValueError("Declared upstream bytes differ from exact Git object: " + path)
        original_records.append(entry)
    current = current_files(vendor)
    if not set(original).issubset(current):
        raise ValueError("Original retained files were removed: " + str(sorted(set(original) - set(current))))
    for crate_root in ROOTS:
        package = tomllib.loads(current[crate_root + "/Cargo.toml"].decode())["package"]
        if CRATES.get(package["name"]) != package["version"]:
            raise ValueError("Vendored package identity changed")
    changed = [{"path": path, "sha256": digest(data), "bytes": len(data),
                "upstream_sha256": digest(original[path]) if path in original else None}
               for path, data in current.items() if original.get(path) != data]
    metadata = dict(previous, original_files=original_records, patched_files=changed)
    updates = {metadata_path: encoded(metadata), vendor / "HEPTA_PATCH.diff": source_diff(original, current)}
    notice_entries = []
    for name in NOTICES:
        path = vendor / name
        data = updates[path] if path in updates else path.read_bytes()
        notice_entries.append({"path": "dependency-notices/accesskit/" + name,
                               "bytes": len(data), "sha256": digest(data)})
    notice_path = hepta / "apps/hepta-native/resources/NATIVE-DEPENDENCIES.json"
    updates[notice_path] = encoded({"schema": "hepta.native-dependency-notices.v1",
                                    "upstreamRevision": REVISION, "crates": CRATES, "files": notice_entries})
    stale = [str(path.relative_to(hepta)) for path, data in updates.items() if not path.is_file() or path.read_bytes() != data]
    if write:
        for path, data in updates.items():
            if path.is_file() and path.read_bytes() == data:
                continue
            temporary = path.with_name(path.name + ".refresh-tmp")
            with temporary.open("xb") as stream:
                stream.write(data)
            temporary.replace(path)
    return {"schema": "hepta.accesskit-provenance-refresh.v1", "upstream": REVISION,
            "verified_original_files": len(original), "patched_files": [entry["path"] for entry in changed],
            "updated_files" if write else "stale_files": stale,
            "source_files_rewritten": False, "network_used": False, "passed": write or not stale}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hepta-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--upstream-repo", type=Path, required=True,
                        help="Existing local Git repository containing exact 405d578 objects; HEAD need not move")
    parser.add_argument("--write", action="store_true")
    options = parser.parse_args()
    report = refresh(options.hepta_root.resolve(strict=True), options.upstream_repo.resolve(strict=True), options.write)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
