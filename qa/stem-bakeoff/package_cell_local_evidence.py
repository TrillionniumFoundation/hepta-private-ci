"""Lossless content-addressed local-phase data package, with independent restore.

Source code stays in its immutable Git commits. Model checkpoints and executable
environments are reacquired from their pinned receipts, never bundled as evidence.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

from package_cell_evidence import (MAX_OBJECT_BYTES, REPOSITORY, _tar_member,
                                  canonical, collect_files, safe_name, sha_file)

SCHEMA = "hepta.cell-local-next-evidence.v1"
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_FILES = 65536


def code_pin(repo, commit):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("full immutable implementation commit required")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args])
    tree = git("rev-parse", commit + "^{tree}").decode().strip()
    names = git("ls-tree", "-r", "--name-only", commit, "qa/stem-bakeoff").decode().splitlines()
    names = [name for name in names if Path(name).parent.as_posix() == "qa/stem-bakeoff"
             and name.endswith((".py", ".md", ".txt", ".json"))]
    hashes = {name: hashlib.sha256(git("show", commit + ":" + name)).hexdigest() for name in names}
    if hashes.get("qa/stem-bakeoff/" + Path(__file__).name) != sha_file(__file__):
        raise ValueError("running packager differs from immutable implementation")
    return {"repository": REPOSITORY, "commit": commit, "tree": tree, "code_sha256": hashes}


def build(entries, output, provenance):
    output = Path(output)
    index_path = output.with_name(output.name + ".index.json")
    if not 1 <= len(entries) <= MAX_FILES or output.exists() or index_path.exists():
        raise ValueError("bounded nonempty data and fresh archive/index destinations required")
    files, objects = [], {}
    for name, path in sorted(entries.items()):
        safe_name(name)
        path = Path(path)
        if path.is_symlink() or not path.is_file() or not 0 <= path.stat().st_size <= MAX_OBJECT_BYTES:
            raise ValueError("bounded ordinary evidence files required")
        digest, size = sha_file(path), path.stat().st_size
        files.append({"path": name, "sha256": digest, "bytes": size})
        objects.setdefault(digest, (path, size))
    manifest = {"schema": SCHEMA, "provenance": provenance, "files": files,
                "file_count": len(files), "object_count": len(objects),
                "logical_bytes": sum(row["bytes"] for row in files),
                "unique_bytes": sum(size for _, size in objects.values())}
    encoded = canonical(manifest)
    instructions = ("# Local phase evidence\n\n"
        "Verify and restore with package_cell_local_evidence.py from the pinned Git commit.\n"
        "Commands: verify --archive FILE --index INDEX; restore --archive FILE --index INDEX --output NEW.\n"
        "The manifest maps original experiment roots to archive-relative paths. Original receipt paths remain unchanged.\n"
        "Preparation and evaluation seals, row order, checkpoint/feature identities, model weights and predictions are retained.\n"
        "Experiment-private small heads are data; shared public checkpoints, runtime installations and Hepta source stay outside.\n"
        "Use run_calibrated_cells.py on restored dataset/features with a NEW output directory for another run.\n"
        "Recorded observed holdouts remain repeated-use data; restoration does not create an independent test set.\n"
        "Public source Git objects and original execution logs are retained where listed; installing dependencies or executing source is never automatic.\n"
        "All restored files are independent ordinary files, not executable links. No original receipt is rewritten.\n").encode()
    try:
        with output.open("xb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.USTAR_FORMAT) as tar:
                _tar_member(tar, "manifest.json", encoded)
                _tar_member(tar, "REPRODUCE.md", instructions)
                for digest, (path, size) in sorted(objects.items()):
                    data = path.read_bytes()
                    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError("source changed during packaging")
                    _tar_member(tar, "objects/" + digest, data)
        if output.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("local phase archive exceeds one GB compressed bound")
        if any(sha_file(entries[row["path"]]) != row["sha256"] for row in files):
            raise ValueError("source changed before package completion")
        index = {"schema": SCHEMA, "archive_sha256": sha_file(output), "archive_bytes": output.stat().st_size,
                 "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
                 "instructions_sha256": hashlib.sha256(instructions).hexdigest(),
                 "file_count": len(files), "object_count": len(objects), "provenance": provenance}
        with index_path.open("xb") as stream:
            stream.write(canonical(index))
    except Exception:
        output.unlink(missing_ok=True)
        index_path.unlink(missing_ok=True)
        raise
    return index


def check(archive, index_path, output=None):
    archive, index_path = Path(archive), Path(index_path)
    if index_path.stat().st_size > 4 * 1024**2:
        raise ValueError("oversized archive index")
    index = json.loads(index_path.read_bytes())
    if (index.get("schema") != SCHEMA or not 0 < archive.stat().st_size <= MAX_ARCHIVE_BYTES
            or archive.stat().st_size != index["archive_bytes"] or sha_file(archive) != index["archive_sha256"]):
        raise ValueError("archive differs from independent hash index")
    root = None if output is None else Path(output)
    if root is not None:
        root.mkdir(parents=True, exist_ok=False)
    expected, seen, logical = {}, set(), set()
    manifest = None
    with tarfile.open(archive, mode="r|gz") as tar:
        for position, member in enumerate(tar):
            if not member.isfile() or not 0 <= member.size <= MAX_OBJECT_BYTES or member.name in seen:
                raise ValueError("unexpected archive member type, size or duplicate")
            seen.add(member.name)
            content = tar.extractfile(member).read()
            digest = hashlib.sha256(content).hexdigest()
            if position == 0:
                if member.name != "manifest.json" or digest != index["manifest_sha256"]:
                    raise ValueError("manifest differs from independent index")
                manifest = json.loads(content)
                if (manifest.get("schema") != SCHEMA or manifest["provenance"] != index["provenance"]
                        or not 1 <= len(manifest["files"]) <= MAX_FILES
                        or len(manifest["files"]) != index["file_count"]):
                    raise ValueError("invalid bound manifest")
                for row in manifest["files"]:
                    safe_name(row["path"])
                    if (row["path"] in logical or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                            or type(row["bytes"]) is not int or not 0 <= row["bytes"] <= MAX_OBJECT_BYTES):
                        raise ValueError("duplicate or invalid logical file")
                    logical.add(row["path"])
                    value = expected.setdefault("objects/" + row["sha256"], {"bytes": row["bytes"], "paths": []})
                    if value["bytes"] != row["bytes"]:
                        raise ValueError("one object has conflicting sizes")
                    value["paths"].append(row["path"])
            elif position == 1:
                if member.name != "REPRODUCE.md" or digest != index["instructions_sha256"]:
                    raise ValueError("reproduction instructions differ")
            else:
                if member.name not in expected or member.name != "objects/" + digest or len(content) != expected[member.name]["bytes"]:
                    raise ValueError("object absent from manifest or content hash differs")
                if root is not None:
                    for name in expected[member.name]["paths"]:
                        path = root / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        with path.open("xb") as stream:
                            stream.write(content)
    if (manifest is None or seen != {"manifest.json", "REPRODUCE.md", *expected}
            or len(expected) != index["object_count"] or manifest["object_count"] != len(expected)
            or manifest["file_count"] != len(logical)):
        raise ValueError("archive is incomplete or manifest counts differ")
    if root is not None:
        for row in manifest["files"]:
            if sha_file(root / row["path"]) != row["sha256"]:
                raise ValueError("restored logical file differs")
    return {"verified": True, "file_count": len(logical), "object_count": len(expected),
            "archive_sha256": index["archive_sha256"], "restored": root is not None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("build")
    for name in ("repo", "commit", "roots", "output"):
        create.add_argument("--" + name, required=True)
    for command in ("verify", "restore"):
        sub = subparsers.add_parser(command)
        for name in ("archive", "index"):
            sub.add_argument("--" + name, required=True)
        if command == "restore":
            sub.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "build":
        roots = json.loads(Path(args.roots).read_bytes())
        pin = code_pin(args.repo, args.commit)
        result = build(collect_files(args.repo, roots), args.output, {"git": pin, "roots": roots})
    else:
        result = check(args.archive, args.index, getattr(args, "output", None))
    print(json.dumps(result))
