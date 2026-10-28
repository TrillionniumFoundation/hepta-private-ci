"""Small sequential archives of immutable natural evidence; never delete raw data."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

from .data_sources import digest, save


def plan(assets, output):
    output.mkdir(parents=True, exist_ok=True)
    destination = output / "PACK_PLAN.json"
    if destination.exists():
        raise FileExistsError("Preserve the previous archive plan")
    paths = []
    for role in ("generator_train", "observer_train", "development"):
        paths.extend(sorted((assets / "prepared" / role).glob("*/*")))
    names = ("SOURCE_PROTOCOL.json", "PARENT_SOURCE_PROTOCOL.json", "FEATURE_PROTOCOL.json",
             "PARENT_FEATURE_PROTOCOL.json", "ACTIVATION.json", "PREPARATION_TRAIN_ONLY.log")
    paths += [assets / name for name in names]
    paths += sorted(assets.glob("*.zip")) + sorted(assets.glob("PREPARATION_*.json"))
    records = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Only immutable regular owned files belong to this archive")
        records.append({"path": str(path), "archive_name": str(path.relative_to(assets.parent)),
                        "bytes": path.stat().st_size, "sha256": digest(path.read_bytes())})
    groups, current, size = [], [], 0
    for record in records:
        if current and size + record["bytes"] > 45_000_000:
            groups.append(current)
            current, size = [], 0
        current.append(record)
        size += record["bytes"]
    if current:
        groups.append(current)
    result = {"schema": "hepta.closure.immutable-natural-pack-plan.v1", "assets": str(assets),
        "source_protocol_file_sha256": digest((assets / "SOURCE_PROTOCOL.json").read_bytes()),
        "roles": ["generator_train", "observer_train", "development"],
        "active_observer_calibration_included": False, "raw_files_removed": False,
        "raw_bytes": sum(record["bytes"] for record in records), "parts": groups}
    save(destination, result)
    return result


def pack(plan_path, part):
    specification = json.loads(plan_path.read_text())
    if not 1 <= part <= len(specification["parts"]):
        raise ValueError("Unknown immutable part number")
    records = specification["parts"][part - 1]
    destination = plan_path.parent / f"natural-v3-training-part{part:02d}.tar.gz"
    if destination.exists():
        raise FileExistsError("Preserve the materialized archive")
    internal = json.dumps({"schema": specification["schema"], "plan_sha256": digest(plan_path.read_bytes()),
                          "part": part, "files": records}, indent=2, sort_keys=True).encode()
    with tarfile.open(destination, "w:gz", compresslevel=1, dereference=True) as archive:
        header = tarfile.TarInfo("PART_MANIFEST.json")
        header.size = len(internal)
        archive.addfile(header, io.BytesIO(internal))
        for record in records:
            path = Path(record["path"])
            if path.stat().st_size != record["bytes"] or digest(path.read_bytes()) != record["sha256"]:
                raise ValueError("An immutable source file changed before packing")
            archive.add(path, arcname=record["archive_name"], recursive=False)
    verified = 0
    with tarfile.open(destination, "r:gz") as archive:
        for record in records:
            with archive.extractfile(record["archive_name"]) as stream:
                hasher = hashlib.sha256()
                count = 0
                for chunk in iter(lambda: stream.read(1024*1024), b""):
                    hasher.update(chunk)
                    count += len(chunk)
            if count != record["bytes"] or hasher.hexdigest() != record["sha256"]:
                raise ValueError("Archived member bytes differ from the immutable manifest")
            verified += 1
    receipt = {"schema": "hepta.closure.verified-local-natural-archive.v1", "part": part,
        "archive_path": str(destination), "archive_bytes": destination.stat().st_size,
        "archive_sha256": digest(destination.read_bytes()), "member_files_verified": verified,
        "plan_sha256": digest(plan_path.read_bytes()), "durable_save_confirmed": False, "raw_files_removed": False}
    save(destination.with_suffix(".receipt.json"), receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--part", type=int)
    args = parser.parse_args()
    if args.part:
        print(json.dumps(pack(args.output / "PACK_PLAN.json", args.part)))
    else:
        result = plan(args.assets, args.output)
        print(json.dumps({"parts": len(result["parts"]), "raw_bytes": result["raw_bytes"]}))
