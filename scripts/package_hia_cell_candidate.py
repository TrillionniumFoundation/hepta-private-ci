#!/usr/bin/env python3
"""Copy exact joint-candidate bytes with genuine, path-scoped Git custody.

Original candidate/build records remain unchanged. Runtime/device refreezing
and explicitly derived relocated build records are separate operations.
"""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import zlib

COMMIT = "f33d8da316de8fdf27b504371f1a5310997ff548"
PROTECTED = (
    "hepta",
    "docs/HIA_CORE_LOWERING_ABI.json",
    "docs/HIA_CORE_EMITTER_ABI.json",
    "docs/HIA_BYTE_WRAPPER_ABI.json",
    "docs/HIA_MACHINE_OBJECT_ABI.json",
)
PINNED_FILES = (*PROTECTED, "pyproject.toml")
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_FILES = 4096


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON field")
            value[key] = item
        return value

    def constant(value):
        raise ValueError("nonfinite JSON constant: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def encoded(value):
    return (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def relative(value):
    if type(value) is not str:
        raise ValueError("candidate path must be a string")
    path = PurePosixPath(value)
    if (
        not path.parts
        or path.is_absolute()
        or str(path) != value
        or "\\" in value
        or any(
            part in ("..", ".git", ".gitconfig", ".git-credentials")
            for part in path.parts
        )
    ):
        raise ValueError("noncanonical or reserved candidate path")
    return path


def read_file(root, name):
    path = (root / relative(name)).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("candidate source escapes its root or is not a file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("candidate file exceeds bound")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("candidate file grew beyond bound")
    return raw, 0o755 if path.stat().st_mode & 0o111 else 0o644


def git(root, *args, data=None):
    # No user Git config, alternates, replace refs, hooks or credentials travel.
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_NO_LAZY_FETCH="1",
    )
    return subprocess.run(
        ["git", "-C", str(root), *args],
        input=data,
        capture_output=True,
        check=True,
        timeout=30,
        env=env,
    ).stdout


def pinned_objects(root):
    objects = {}

    def obtain(kind, oid):
        if oid not in objects:
            raw = git(root, "cat-file", kind, oid)
            full = kind.encode() + b" " + str(len(raw)).encode() + b"\0" + raw
            if hashlib.sha1(full).hexdigest() != oid:
                raise ValueError("Git object content does not match its real identity")
            objects[oid] = (kind, raw, zlib.compress(full))
        if objects[oid][0] != kind:
            raise ValueError("Git object type differs")
        return objects[oid][1]

    raw_commit = obtain("commit", COMMIT)
    tree_line = raw_commit.split(b"\n", 1)[0]
    if not re.fullmatch(rb"tree [0-9a-f]{40}", tree_line):
        raise ValueError("invalid pinned commit tree")
    tree = tree_line[5:].decode()
    obtain("tree", tree)
    entries = []
    listing = git(root, "ls-tree", "-r", "-t", "-z", COMMIT, "--", *PINNED_FILES)
    for item in listing.split(b"\0"):
        if not item:
            continue
        fields, name = item.split(b"\t", 1)
        mode, kind, oid = (part.decode() for part in fields.split())
        name = str(relative(name.decode()))
        if kind not in ("tree", "blob") or mode not in ("040000", "100644", "100755"):
            raise ValueError("unsupported pinned Git entry")
        raw = obtain(kind, oid)
        if kind == "blob":
            entries.append({"path": name, "mode": mode, "oid": oid, "raw": raw})
    names = {entry["path"] for entry in entries}
    if not set(PINNED_FILES[1:]) <= names or "hepta/__init__.py" not in names:
        raise ValueError("pinned compiler closure is incomplete")
    return objects, entries, tree


def package(candidate, output):
    candidate = candidate.resolve(strict=True)
    output = output.absolute()
    archive = output.with_name(output.name + ".tar.gz")
    archive_record = output.with_name(output.name + ".archive.json")
    if any(
        path.exists() or path.is_symlink() for path in (output, archive, archive_record)
    ):
        raise FileExistsError("bundle, archive and archive record must all be new")
    raw, _ = read_file(candidate.parent, candidate.name)
    if len(raw) > 2**20:
        raise ValueError("candidate manifest exceeds bound")
    value = strict_json(raw)
    if (
        value["schema"] != "hepta.joint-cell-candidate.v1"
        or value["source_bases"]["hia_compiler"] != COMMIT
    ):
        raise ValueError("candidate schema or compiler pin differs")
    origins = {
        "cells": Path(__file__).resolve().parent.parent,
        "hia": Path(value["hia_root"]).resolve(strict=True),
        "artifacts": candidate.parent,
    }
    targets = {"cells": "cells", "hia": "hia", "artifacts": "candidate"}
    staged, records = {}, {}
    total = 0

    def add(name, content, mode=0o644, **origin):
        nonlocal total
        if name in staged or len(staged) >= MAX_FILES or len(content) > MAX_FILE_BYTES:
            raise ValueError(
                "duplicate bundle path or bundle file/count bound exceeded"
            )
        total += len(content)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("bundle bytes exceed bound")
        staged[name] = (content, mode)
        records[name] = {
            "path": name,
            "sha256": digest(content),
            "bytes": len(content),
            "mode": mode,
            **origin,
        }

    observed = set()
    for item in value["files"]:
        group, name = item["root"], str(relative(item["path"]))
        expected = item["sha256"]
        if (
            group not in origins
            or (group, name) in observed
            or not re.fullmatch(r"[0-9a-f]{64}", expected)
        ):
            raise ValueError("invalid or duplicate candidate source record")
        retained = candidate.parent / "executed-source" / group
        saved = retained / name
        source_root = (
            retained.resolve()
            if group != "artifacts" and (saved.exists() or saved.is_symlink())
            else origins[group]
        )
        content, mode = read_file(source_root, name)
        if digest(content) != expected:
            raise ValueError("candidate byte identity changed: " + group + "/" + name)
        target = targets[group] + "/" + name
        add(
            target,
            content,
            mode,
            origin_root=group,
            origin_path=name,
            candidate_record=True,
        )
        observed.add((group, name))
    required = {
        ("cells", "scripts/hepta_cell_joint_worker.py"),
        ("hia", "tools/cell_bridge_native.py"),
        ("hia", "examples/hia_cell_bridge/continuation.hepta"),
        ("artifacts", "native/build.json"),
        ("artifacts", "inputs.json"),
    }
    if not required <= observed:
        raise ValueError("candidate lacks required portable records")
    build = strict_json(staged["candidate/native/build.json"][0])
    native = value["native"]
    if (
        build["compiler_commit"] != COMMIT
        or build["image_sha256"] != native["image_sha256"]
        or build["source_sha256"] != native["source_sha256"]
        or records["hia/examples/hia_cell_bridge/continuation.hepta"]["sha256"]
        != native["source_sha256"]
        or records["candidate/" + str(relative(native["image"]))]["sha256"]
        != native["image_sha256"]
    ):
        raise ValueError("candidate native/build/source binding differs")
    for model in value["models"].values():
        if (
            records["candidate/" + str(relative(model["path"]))]["sha256"]
            != model["sha256"]
        ):
            raise ValueError("candidate model binding differs")
    add(
        "candidate/original_candidate.json",
        raw,
        origin_root="candidate",
        candidate_record=False,
    )

    objects, entries, tree = pinned_objects(origins["hia"])
    supplements = []
    protected_names = {"hia/" + entry["path"] for entry in entries}
    for name in staged:
        if name.startswith("hia/hepta/") and name not in protected_names:
            raise ValueError("candidate compiler file is absent from the pinned commit")
    for entry in entries:
        name, mode = "hia/" + entry["path"], int(entry["mode"], 8) & 0o777
        if name in staged:
            if staged[name] != (entry["raw"], mode):
                raise ValueError(
                    "candidate compiler bytes or mode differ from real pinned Git blob"
                )
            records[name]["git_blob"] = entry["oid"]
        else:
            add(
                name,
                entry["raw"],
                mode,
                origin_root="pinned_git",
                git_blob=entry["oid"],
                candidate_record=False,
            )
            supplements.append(entry["path"])
    for oid, (kind, _, compressed) in sorted(objects.items()):
        add(
            "hia/.git/objects/" + oid[:2] + "/" + oid[2:],
            compressed,
            origin_root="pinned_git",
            git_object=oid,
            git_type=kind,
        )
    add("hia/.git/HEAD", (COMMIT + "\n").encode(), origin_root="derived_git_metadata")
    add(
        "hia/.git/shallow", (COMMIT + "\n").encode(), origin_root="derived_git_metadata"
    )
    add(
        "hia/.git/config",
        b"[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n\tlogallrefupdates = false\n",
        origin_root="derived_git_metadata",
    )
    output.mkdir(parents=True)
    for name, (content, mode) in staged.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
        path.chmod(mode)
    (output / "hia/.git/refs").mkdir()
    index = b"".join(
        (entry["mode"] + " " + entry["oid"] + "\t" + entry["path"]).encode() + b"\0"
        for entry in entries
    )
    git(output / "hia", "update-index", "-z", "--index-info", data=index)
    git(output / "hia", "cat-file", "-e", COMMIT + "^{commit}")
    git(output / "hia", "diff", "--quiet", COMMIT, "--", *PROTECTED)
    index_path = output / "hia/.git/index"
    index_bytes = index_path.read_bytes()
    mutable_index = {
        "path": "hia/.git/index",
        "sha256": digest(index_bytes),
        "bytes": len(index_bytes),
        "mode": stat.S_IMODE(index_path.stat().st_mode),
        "origin_root": "derived_git_metadata",
        "mutability": "Git may refresh stat-cache bytes after relocation; archive hash authenticates the transferred initial index.",
    }
    source_map = {
        "schema": "hepta.portable-joint-source-map.v1",
        "origin_candidate_sha256": digest(raw),
        "packager_sha256": digest(Path(__file__).read_bytes()),
        "compiler_commit": COMMIT,
        "compiler_tree": tree,
        "git_scope": "one genuine shallow commit; only selected path trees/blobs; not a complete repository or history",
        "git_objects": len(objects),
        "compiler_files": len(entries),
        "supplemental_compiler_files": supplements,
        "original_build_record_preserved": True,
        "relocation": "Refreeze device/runtime separately; absolute build paths need an explicitly derived relocated record.",
        "coverage": "All payload file transfer hashes are in files or mutable_git_metadata, except this SOURCE_MAP.json; no user Git config, remotes, hooks, alternates or credentials.",
        "mutable_git_metadata": [mutable_index],
        "files": [records[name] for name in sorted(records)],
    }
    (output / "SOURCE_MAP.json").write_bytes(encoded(source_map))
    return make_archive(output, archive, archive_record, source_map)


def make_archive(output, archive, archive_record, source_map):
    members = []
    with (
        archive.open("xb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
    ):
        with tarfile.open(
            fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
        ) as tar:
            for path in sorted(output.rglob("*")):
                name = str(path.relative_to(output))
                info = tar.gettarinfo(str(path), arcname=output.name + "/" + name)
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                if path.is_dir():
                    # Empty refs/ must survive extraction for a genuine repo.
                    tar.addfile(info)
                    members.append(
                        {"path": name, "type": "directory", "mode": info.mode}
                    )
                else:
                    content = path.read_bytes()
                    with path.open("rb") as stream:
                        tar.addfile(info, stream)
                    members.append(
                        {
                            "path": name,
                            "type": "file",
                            "sha256": digest(content),
                            "bytes": len(content),
                            "mode": info.mode,
                        }
                    )
    result = {
        "schema": "hepta.portable-joint-archive.v1",
        "bundle": str(output),
        "archive": str(archive),
        "archive_sha256": digest(archive.read_bytes()),
        "archive_bytes": archive.stat().st_size,
        "origin_candidate_sha256": source_map["origin_candidate_sha256"],
        "source_map_sha256": digest((output / "SOURCE_MAP.json").read_bytes()),
        "members": members,
    }
    with archive_record.open("xb") as stream:
        stream.write(encoded(result))
    return {key: value for key, value in result.items() if key != "members"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.candidate, args.output), sort_keys=True))


if __name__ == "__main__":
    main()
