"""Portable, hash-verified split evidence archives; never replace differing bytes."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import resource
import tarfile
import tempfile
import time


CHUNK = 192 * 1024


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def relative(name):
    path = PurePosixPath(name)
    if (not name or not path.parts or path.is_absolute() or path.as_posix() != name or "\\" in name
            or ":" in path.parts[0] or any(p in (".", "..") for p in path.parts)):
        raise ValueError(f"Unsafe archive path: {name!r}")
    return path


def target(root, name):
    parts = relative(name).parts
    result = root.joinpath(*parts)
    for path in (result, *result.parents):
        if path == root.parent:
            break
        if path.is_symlink():
            raise ValueError(f"Symlink destination refused: {path}")
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Destination escaped restore root")
    return result


def metrics(wall, cpu):
    return dict(wall_seconds=time.perf_counter() - wall, cpu_seconds=time.process_time() - cpu,
                process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                scope="archive operation; final receipt serialization excluded", energy_joules=None)


def selected_files(root, includes):
    files = {}
    for include in includes:
        source = target(root, include)
        if not source.exists():
            raise FileNotFoundError(source)
        for path in ([source] if source.is_file() else sorted(source.rglob("*"))):
            if path.is_symlink() or (not path.is_dir() and not path.is_file()):
                raise ValueError(f"Only regular source files allowed: {path}")
            if path.is_file():
                files[path.relative_to(root).as_posix()] = path
    return files


def pack(root, includes, output, name):
    wall, cpu = time.perf_counter(), time.process_time()
    root, output = Path(root).resolve(), Path(output)
    relative(name)
    if "/" in name:
        raise ValueError("Archive name must be a basename")
    files = selected_files(root, includes)
    if not files:
        raise ValueError("Empty evidence selection")
    output.mkdir(parents=True, exist_ok=False)
    members = [dict(path=key, bytes=files[key].stat().st_size, sha256=digest(files[key])) for key in sorted(files)]
    temporary = output / (name + ".working.tar.xz")
    with tarfile.open(temporary, "w:xz", format=tarfile.PAX_FORMAT, preset=6) as archive:
        for member in members:
            info = tarfile.TarInfo(member["path"])
            info.size, info.mode, info.mtime = member["bytes"], 0o644, 0
            with files[member["path"]].open("rb") as stream:
                archive.addfile(info, stream)
    archive_hash, archive_bytes, parts = digest(temporary), temporary.stat().st_size, []
    with temporary.open("rb") as stream:
        while block := stream.read(CHUNK):
            part = output / f"{name}.tar.xz.part{len(parts) + 1:04d}"
            with part.open("xb") as sink:
                sink.write(block)
            parts.append(dict(path=part.name, bytes=len(block), sha256=hashlib.sha256(block).hexdigest()))
    temporary.unlink()
    if set(selected_files(root, includes)) != set(files):
        raise ValueError("Source membership changed during packaging; retained partial evidence")
    for member in members:
        if digest(files[member["path"]]) != member["sha256"]:
            raise ValueError("Source changed during packaging; retained partial evidence")
    manifest = dict(schema="hcsn-evidence-bundle.v3", name=name, format="POSIX tar; xz; ordered binary parts",
                    member_paths_relative_to="experiments/hcsn_causal_execution_v3", members=members, parts=parts,
                    part_max_bytes=CHUNK, archive_sha256=archive_hash, compressed_bytes=archive_bytes,
                    uncompressed_file_bytes=sum(m["bytes"] for m in members), pack_cost=metrics(wall, cpu))
    path = output / (name + ".json")
    with path.open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def restore(manifest_path, destination):
    wall, cpu = time.perf_counter(), time.process_time()
    manifest_path, destination = Path(manifest_path), Path(destination)
    plan = json.loads(manifest_path.read_text())
    if plan["schema"] != "hcsn-evidence-bundle.v3":
        raise ValueError("Unsupported evidence schema")
    expected = {m["path"]: m for m in plan["members"]}
    if len(expected) != len(plan["members"]):
        raise ValueError("Duplicate manifest member")
    for name in expected:
        target(destination, name)
    written = identical = 0
    with tempfile.TemporaryFile() as joined:
        complete = hashlib.sha256()
        seen_parts = set()
        for part in plan["parts"]:
            name = relative(part["path"])
            if len(name.parts) != 1 or part["path"] in seen_parts:
                raise ValueError("Invalid or duplicate part path")
            seen_parts.add(part["path"])
            path = manifest_path.parent / part["path"]
            if path.is_symlink() or path.stat().st_size != part["bytes"] or digest(path) != part["sha256"]:
                raise ValueError("Part hash or size mismatch")
            with path.open("rb") as stream:
                while block := stream.read(1 << 20):
                    complete.update(block)
                    joined.write(block)
        if joined.tell() != plan["compressed_bytes"] or complete.hexdigest() != plan["archive_sha256"]:
            raise ValueError("Complete archive hash or size mismatch")
        joined.seek(0)
        with tarfile.open(fileobj=joined, mode="r:xz") as archive:
            members = archive.getmembers()
            if len(members) != len(expected) or len({m.name for m in members}) != len(members):
                raise ValueError("Archive member count or uniqueness mismatch")
            for member in members:
                path = target(destination, member.name)
                if not member.isfile() or member.linkname or member.name not in expected:
                    raise ValueError("Only declared regular members may be restored")
                record = expected[member.name]
                if member.size != record["bytes"]:
                    raise ValueError("Member size mismatch")
                with archive.extractfile(member) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != record["sha256"]:
                        raise ValueError("Member hash mismatch")
                if path.exists() and (not path.is_file() or digest(path) != record["sha256"]):
                    raise FileExistsError(f"Refuse to replace differing bytes: {path}")
            for member in members:
                path = target(destination, member.name)
                if path.exists():
                    identical += 1
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as stream, path.open("xb") as sink:
                    while block := stream.read(1 << 20):
                        sink.write(block)
                if digest(path) != expected[member.name]["sha256"]:
                    raise ValueError("Restored output hash mismatch")
                written += 1
    return dict(schema="hcsn-evidence-restore.v3", manifest_sha256=digest(manifest_path),
                archive_sha256=plan["archive_sha256"], verified_members=len(expected), written=written,
                identical_existing=identical, all_verified=True, restore_cost=metrics(wall, cpu))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    make = sub.add_parser("pack")
    for argument in ("root", "output"):
        make.add_argument("--" + argument, type=Path, required=True)
    make.add_argument("--name", required=True)
    make.add_argument("--include", nargs="+", required=True)
    unpack = sub.add_parser("restore")
    unpack.add_argument("--manifest", type=Path, required=True)
    unpack.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(pack(args.root, args.include, args.output, args.name) if args.action == "pack"
          else json.dumps(restore(args.manifest, args.destination), indent=2))
