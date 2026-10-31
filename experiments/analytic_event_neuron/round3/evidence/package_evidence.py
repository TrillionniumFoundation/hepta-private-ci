"""Create deterministic, member-verified evidence bundles with bounded blob sizes."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            value.update(block)
    return value.hexdigest()


def descriptor(path, repo):
    return {"path": str(path.relative_to(repo)), "bytes": path.stat().st_size, "sha256": sha(path)}


def package(root, relative_paths, repo, destination, name, restore_root="run"):
    root, repo, destination = Path(root).resolve(), Path(repo).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (name + ".tar.gz")
    if archive.exists() or list(destination.glob(name + ".tar.gz.part*")):
        raise FileExistsError("Refusing to replace a previously packaged bundle")
    chosen = []
    for relative in relative_paths:
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Selection escapes source root")
        chosen.extend(path.rglob("*") if path.is_dir() else [path])
    files = sorted({p for p in chosen if p.is_file() and "__pycache__" not in p.parts})
    if not files or any(p.is_symlink() for p in files):
        raise ValueError("Evidence must comprise ordinary files")
    hashes = {str(p.relative_to(root)): sha(p) for p in files}
    manifest = "_bundle_manifests/" + name + ".json"
    payload = (json.dumps(hashes, sort_keys=True, indent=2) + "\n").encode()
    with archive.open("xb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as tar:
            for path in files:
                info = tar.gettarinfo(str(path), arcname=str(path.relative_to(root)))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                with path.open("rb") as source:
                    tar.addfile(info, source)
            info = tarfile.TarInfo(manifest)
            info.size, info.mode, info.mtime = len(payload), 0o644, 0
            tar.addfile(info, io.BytesIO(payload))
    with tarfile.open(archive, "r:gz") as tar:
        actual = {member.name: hashlib.sha256(tar.extractfile(member).read()).hexdigest()
                  for member in tar if member.isfile() and member.name != manifest}
    if actual != hashes:
        raise ValueError("Evidence member set or bytes changed")
    value = {"name": name, **descriptor(archive, repo), "restore_root": restore_root,
             "member_manifest": manifest, "data_members": len(files),
             "all_member_hashes_verified": True, "scientific_data_regenerated": False}
    if archive.stat().st_size > 8 * 1024 * 1024:
        parts = []
        with archive.open("rb") as source:
            while block := source.read(8 * 1024 * 1024):
                target = Path(str(archive) + f".part{len(parts):03d}")
                with target.open("xb") as stream:
                    stream.write(block)
                parts.append(descriptor(target, repo))
        check = hashlib.sha256()
        for part in parts:
            with (repo / part["path"]).open("rb") as stream:
                for block in iter(lambda: stream.read(1048576), b""):
                    check.update(block)
        if check.hexdigest() != value["sha256"]:
            raise ValueError("Reassembled byte parts differ")
        value["parts"] = parts
        value.pop("path")
        archive.unlink()
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for key in ("root", "repo", "destination", "name", "output"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("--path", action="append", required=True)
    parser.add_argument("--restore-root", default="run")
    args = parser.parse_args()
    result = package(args.root, args.path, args.repo, args.destination, args.name, args.restore_root)
    with Path(args.output).open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({"name": result["name"], "bytes": result["bytes"], "data_members": result["data_members"]}))
