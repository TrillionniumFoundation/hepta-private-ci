"""Lossless per-fit evidence archives with independent read-back byte hashes."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

from ..unified_cell_r12_20261031.fit import atomic_json


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pack(run, destination, stage):
    run, destination = Path(run), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    manifest = dict(schema="hcsn-r14-lossless-evidence-v1", stage=stage, archives=[])
    for directory in sorted(p for p in run.iterdir() if p.is_dir() and p.name.isdigit()):
        files = [p for p in sorted(directory.iterdir()) if p.is_file()
                 and (p.name.startswith("confirmation_") == (stage == "confirmation"))]
        if not files:
            continue
        archive = destination / (stage + "_" + directory.name + ".zip")
        members = []
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
            for file in files:
                data, name = file.read_bytes(), file.relative_to(run).as_posix()
                info = zipfile.ZipInfo(name, date_time=(2026, 11, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                zipped.writestr(info, data)
                members.append(dict(path=name, size=len(data), sha256=sha(data)))
        # Independent bytes read from the finished ZIP must match every original.
        with zipfile.ZipFile(archive) as zipped:
            if set(zipped.namelist()) != {m["path"] for m in members}:
                raise AssertionError("Archive membership changed")
            for member in members:
                data = zipped.read(member["path"])
                if len(data) != member["size"] or sha(data) != member["sha256"]:
                    raise AssertionError("Archive read-back differs from executed artifact")
        manifest["archives"].append(dict(file=archive.name, size=archive.stat().st_size,
                                         sha256=sha(archive.read_bytes()), members=members))
    atomic_json(destination / (stage.upper() + "_ARCHIVES.json"), manifest)
    return manifest


def restore(index, destination):
    index, destination = Path(index), Path(destination)
    manifest = json.loads(index.read_text())
    count = 0
    for archive in manifest["archives"]:
        archive_path = index.parent / archive["file"]
        if PurePosixPath(archive["file"]).name != archive["file"] or sha(archive_path.read_bytes()) != archive["sha256"]:
            raise ValueError("Invalid archive path or byte identity")
        with zipfile.ZipFile(archive_path) as zipped:
            if set(zipped.namelist()) != {m["path"] for m in archive["members"]}:
                raise ValueError("Archive has unexpected members")
            for member in archive["members"]:
                name = PurePosixPath(member["path"])
                if name.is_absolute() or ".." in name.parts or "\\" in member["path"]:
                    raise ValueError("Unsafe archive member")
                data = zipped.read(member["path"])
                if len(data) != member["size"] or sha(data) != member["sha256"]:
                    raise ValueError("Evidence hash differs")
                target = destination.joinpath(*name.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and target.read_bytes() != data:
                    raise FileExistsError("Refuse to overwrite different existing evidence")
                target.write_bytes(data)
                count += 1
    return dict(restored_files=count, byte_identities_verified=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("pack", "restore"))
    parser.add_argument("--run", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--stage", choices=("training", "confirmation"))
    parser.add_argument("--index", type=Path)
    args = parser.parse_args()
    result = pack(args.run, args.destination, args.stage) if args.operation == "pack" else restore(args.index, args.destination)
    print(json.dumps(result if args.operation == "restore" else
                     dict(stage=args.stage, archives=len(result["archives"]), bytes=sum(a["size"] for a in result["archives"]))))


if __name__ == "__main__":
    main()
