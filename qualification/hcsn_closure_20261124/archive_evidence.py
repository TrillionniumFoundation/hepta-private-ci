"""Snapshot explicit terminal experiment directories into verified raw archives.

This transports evidence only. It never runs a model, changes a result or
interprets a successful process exit as scientific qualification. Use the
separate gzip-parts transport for repository-size bounded publication.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
import time


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical(name):
    path = PurePosixPath(name)
    if (not name or "\\" in name or "\0" in name or path.is_absolute()
            or path.as_posix() != name or any(p in (".", "..") for p in path.parts)):
        raise ValueError("invalid evidence path")
    return path


def inventory(root):
    rows = []
    for p in sorted(root.rglob("*")):
        relative = p.relative_to(root)
        if "__pycache__" in relative.parts or p.suffix == ".pyc":
            continue
        info = p.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("evidence contains a symlink: "+str(relative))
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("evidence contains a nonregular file: "+str(relative))
        name = relative.as_posix()
        canonical(name)
        rows.append({"path": name, "bytes": info.st_size,
                     "sha256": digest_file(p), "mode": stat.S_IMODE(info.st_mode)})
    if not rows:
        raise ValueError("empty evidence directory")
    return rows


def snapshot(base, spec, output, logical_prefix):
    name = spec["name"]
    if len(canonical(name).parts) != 1:
        raise ValueError("source must be one explicitly listed directory")
    source = base/name
    if source.is_symlink() or not source.is_dir():
        raise ValueError("invalid source directory")
    terminal = spec.get("terminal_receipts", [])
    if spec.get("kind") != "immutable_source" and not terminal:
        raise ValueError("experiment snapshot requires a terminal receipt")
    for receipt in terminal:
        canonical(receipt)
        p = source/receipt
        if p.is_symlink() or not p.is_file():
            raise ValueError("missing terminal receipt: "+str(p))
        json.loads(p.read_text())
    rows = inventory(source)
    member_manifest = {"schema": "hcsn-exact-archive-members-v1", "source_name": name,
        "kind": spec["kind"], "terminal_receipts": terminal, "files": rows,
        "excluded": ["__pycache__ directories", "*.pyc derived interpreter caches"]}
    manifest_raw = (json.dumps(member_manifest, sort_keys=True, indent=2)+"\n").encode()
    logical = logical_prefix+"/"+name+".tar.gz"
    canonical(logical)
    target = output/logical
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as outer:
        with gzip.GzipFile(filename="", mode="wb", fileobj=outer, mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for row in rows:
                    data = (source/row["path"]).read_bytes()
                    if len(data) != row["bytes"] or sha(data) != row["sha256"]:
                        raise ValueError("source changed while archiving")
                    info = tarfile.TarInfo(name+"/"+row["path"])
                    info.size, info.mode, info.mtime = len(data), row["mode"], 0
                    tar.addfile(info, io.BytesIO(data))
                info = tarfile.TarInfo("ARCHIVE_MEMBERS.json")
                info.size, info.mode, info.mtime = len(manifest_raw), 0o644, 0
                tar.addfile(info, io.BytesIO(manifest_raw))
    if inventory(source) != rows:
        raise ValueError("source roster or bytes changed before snapshot completed")
    expected = {name+"/"+row["path"]: row for row in rows}
    observed = set()
    with tarfile.open(target, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or member.name in observed:
                raise ValueError("nonregular or duplicate archive member")
            observed.add(member.name)
            data = tar.extractfile(member).read()
            if member.name == "ARCHIVE_MEMBERS.json":
                if data != manifest_raw:
                    raise ValueError("archive member inventory changed")
            elif (member.name not in expected or sha(data) != expected[member.name]["sha256"]
                  or len(data) != expected[member.name]["bytes"]):
                raise ValueError("archive member identity mismatch")
    if observed != set(expected)|{"ARCHIVE_MEMBERS.json"}:
        raise ValueError("incomplete archive")
    size = target.stat().st_size
    git = hashlib.sha1(b"blob "+str(size).encode()+b"\0")
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024*1024), b""):
            git.update(chunk)
    return {"logical_path": logical, "bytes": size, "sha256": digest_file(target),
            "source_git_blob_sha1": git.hexdigest(), "source_name": name,
            "member_count": len(observed), "original_member_bytes": sum(row["bytes"] for row in rows),
            "member_manifest_sha256": sha(manifest_raw), "terminal_receipts": terminal}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text())
    if not spec or len({s["name"] for s in spec}) != len(spec):
        raise ValueError("empty or duplicate archive roster")
    args.out.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter(), time.process_time()
    objects = []
    for entry in spec:
        row = snapshot(args.base, entry, args.out, args.prefix)
        objects.append(row)
        print(json.dumps({"verified_archive": row["source_name"], "bytes": row["bytes"],
                          "members": row["member_count"]}), flush=True)
    receipt = {"schema": "hcsn-exact-archive-roster-v1", "objects": objects,
               "wall_seconds": time.perf_counter()-start,
               "cpu_seconds": time.process_time()-cpu, "energy_joules_process": None}
    with (args.out/"ARCHIVES.json").open("x") as handle:
        json.dump(receipt, handle, sort_keys=True, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
