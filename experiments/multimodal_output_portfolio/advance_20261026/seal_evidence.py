"""Seal closed advance evidence, including protocols outside the repository.

This extends the previous immutable sealer only to name explicitly allowed
raw-directory protocols. Every archived member is read and verified after close.
Frozen external runtime inputs are inventoried, not called a portable runtime.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import time

from ..closure_20261025.package_evidence import file_sha, package


def write_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def seal(definition, archive, receipt, workspace, repository):
    """Explicit tree inclusion; protocol pins outside those trees are inventoried.

    Large manifests remain inside the complete archive and beside it locally.
    The compact receipt and definition can be committed without expanding Git
    by one JSON row for every small generated media file.
    """
    definition, archive, receipt = map(Path, (definition, archive, receipt))
    workspace, repository = Path(workspace).resolve(), Path(repository).resolve()
    manifest_path = archive.with_suffix(archive.suffix + ".manifest.json")
    expanded_path = archive.with_suffix(archive.suffix + ".inputs.json")
    if any(path.exists() for path in (archive, receipt, manifest_path, expanded_path)):
        raise FileExistsError("Never replace a completed evidence package")
    spec = json.loads(definition.read_text())
    roots = [workspace]
    for source_root in spec.get("additional_source_roots", []):
        root = Path(source_root).resolve()
        if root == Path("/tmp") or not (root.is_relative_to("/tmp") or root.is_relative_to(workspace)):
            raise ValueError("Extra evidence roots must name a study path in /tmp or the workspace")
        if not root.exists():
            raise ValueError("Missing additional evidence root")
        roots.append(root)

    def allowed(path):
        return any(path.is_relative_to(root) for root in roots)

    files, source_names = {}, {}

    def add(path, name):
        path = Path(path)
        if path.is_symlink():
            raise ValueError("Symlink is not an evidence source: " + str(path))
        path = path.resolve()
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts or name == "MANIFEST.json":
            raise ValueError("Unsafe or reserved member name")
        if not path.is_file() or not allowed(path):
            raise ValueError("Evidence must belong to an explicit study source root: " + str(path))
        if name in files and files[name] != path:
            raise ValueError("Two source files have one archive name")
        if path in source_names and source_names[path] != name:
            return  # One immutable copy per source file is sufficient.
        files[name], source_names[path] = path, name

    for root in spec["trees"]:
        path = Path(root["path"]).resolve()
        if not path.is_dir() or not allowed(path):
            raise ValueError("Missing declared evidence tree")
        for child in sorted(path.rglob("*")):
            if child.is_file() and "__pycache__" not in child.parts:
                add(child, root["prefix"].rstrip("/") + "/" + child.relative_to(path).as_posix())
    for entry in spec.get("files", []):
        if "sha256" in entry and file_sha(Path(entry["path"])) != entry["sha256"]:
            raise ValueError("Explicit evidence input identity changed: " + entry["path"])
        add(entry["path"], entry["name"])
    for path in (definition, Path(__file__).resolve(),
                 Path(__file__).resolve().parents[1] / "closure_20261025/package_evidence.py"):
        add(path, "repository/" + path.resolve().relative_to(repository).as_posix())

    external, protocols, historical = {}, {}, []
    snapshots = {(str(Path(row["protocol"]).resolve()), row["historical_path"]):
                 Path(row["exact_executed_snapshot"]).resolve()
                 for row in spec.get("historical_exact_source_snapshots", [])}
    for path in map(Path, spec.get("protocols", [])):
        record = json.loads(path.read_text())
        protocols[str(path.resolve())] = file_sha(path)
        resolved = path.resolve()
        protocol_member = ("repository/" + resolved.relative_to(repository).as_posix()
                           if resolved.is_relative_to(repository)
                           else "protocols/" + file_sha(path) + "/" + path.name)
        add(path, protocol_member)
        for source, expected in record["frozen_candidate_sha256"].items():
            item = Path(source).resolve()
            if file_sha(item) != expected:
                snapshot = snapshots.get((str(path.resolve()), source))
                if snapshot is None or file_sha(snapshot) != expected:
                    raise ValueError("Frozen source or model changed without its exact historical snapshot: " + source)
                historical.append({"protocol": str(path.resolve()), "historical_path": source,
                                   "exact_executed_snapshot": str(snapshot), "sha256": expected})
                add(snapshot, "historical-executed-source/" + expected + "/" + snapshot.name)
                continue
            if item.is_relative_to(repository):
                add(item, "repository/" + item.relative_to(repository).as_posix())
            elif item not in source_names:
                external[str(item)] = {"sha256": expected, "bytes": item.stat().st_size}
    custody = []
    for entry in spec.get("external_archives", []):
        path = Path(entry["path"])
        if file_sha(path) != entry["sha256"]:
            raise ValueError("Linked complete archive changed")
        for key in ("manifest", "receipt"):
            if key in entry and key + "_sha256" in entry:
                if file_sha(Path(entry[key])) != entry[key + "_sha256"]:
                    raise ValueError("Linked archive custody changed: " + entry[key])
        custody.append({**entry, "bytes": path.stat().st_size, "verified": True})
    expanded = {"study": spec["study"], "description": spec["description"],
                "definition_sha256": file_sha(definition),
                "files": [{"path": str(path), "name": name, "sha256": file_sha(path)}
                          for name, path in sorted(files.items())]}
    write_new(expanded_path, expanded)
    package(expanded_path, archive)
    verified = set()
    with tarfile.open(archive, "r:gz") as packed:
        manifest_bytes = packed.extractfile("MANIFEST.json").read()
        manifest = json.loads(manifest_bytes)
        expected = {row["member"]: row for row in manifest["files"]}
        if len(expected) != len(files):
            raise ValueError("Manifest omitted or duplicated a source file")
        for member in packed.getmembers():
            if member.name == "MANIFEST.json":
                continue
            if not member.isfile() or member.name not in expected or member.name in verified:
                raise ValueError("Unexpected, repeated or non-file archive member")
            digest = hashlib.sha256()
            with packed.extractfile(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if (member.size != expected[member.name]["bytes"]
                    or digest.hexdigest() != expected[member.name]["sha256"]):
                raise ValueError("Archived bytes differ from original: " + member.name)
            verified.add(member.name)
    if verified != set(expected):
        raise ValueError("Archive is incomplete")
    manifest_path.write_bytes(manifest_bytes)
    prior = json.loads(archive.with_suffix(archive.suffix + ".receipt.json").read_text())
    if (file_sha(archive) != prior["archive_sha256"]
            or hashlib.sha256(manifest_bytes).hexdigest() != prior["manifest_sha256"]):
        raise ValueError("Archive identity or internal manifest changed")
    result = {**prior, "schema": "hepta.advance.closed-evidence.v1", "status": "passed",
              "definition_sha256": file_sha(definition), "protocols_verified": protocols,
              "allowed_source_roots": list(map(str, roots)),
              "historical_exact_source_snapshots_verified": historical,
              "member_manifest": str(manifest_path), "expanded_inputs": str(expanded_path),
              "external_frozen_inputs": external, "linked_complete_archives": custody,
              "external_scope": spec.get("external_scope", "See explicitly linked archives and frozen input identities"),
              "all_member_bytes_rehashed_after_archive_close": True,
              "verified_members_including_manifest": len(verified) + 1,
              "original_files_retained": True, "upload_performed": False,
              "completed_unix_ns": time.time_ns()}
    write_new(receipt, result)
    print(json.dumps({key: result[key] for key in
                     ("status", "archive", "archive_bytes", "archive_sha256", "verified_members_including_manifest")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("definition", "archive", "receipt", "workspace", "repository"):
        parser.add_argument("--" + name, type=Path, required=True)
    seal(**vars(parser.parse_args()))
