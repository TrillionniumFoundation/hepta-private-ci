"""Lossless, hash-verified transport of complete raw research evidence."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(root, part_bytes=524288):
    root = Path(root).resolve()
    destination = root / "evidence/transport"
    destination.mkdir(parents=True, exist_ok=False)
    files = list((root / "evidence/calibration_targets").glob("*.npz"))
    for mode in ("direct", "continuous", "clocked", "first_passage"):
        files += list((root / "evidence").glob(f"calibration_{mode}_*.json"))
    for name in ("contract_exchange_v1", "confirmation_v1", "native_validation01", "native_cost01", "native_reuse_cost01"):
        folder = root / "evidence" / name
        if not (folder / ("summary.json" if name in ("contract_exchange_v1", "confirmation_v1") else "REPORT.json")).exists():
            raise ValueError("raw evidence is not complete: " + name)
        files += [path for path in folder.rglob("*") if path.is_file()]
    files = sorted(set(files))
    inventory = {str(path.relative_to(root)): {"bytes": path.stat().st_size, "sha256": digest(path)}
                 for path in files}
    inventory_bytes = (json.dumps(inventory, sort_keys=True, indent=2) + "\n").encode()
    with tempfile.TemporaryDirectory(prefix="transport_", dir=root) as temporary:
        archive = Path(temporary) / "raw.tar.gz"
        with archive.open("wb") as out, gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                item = tarfile.TarInfo("__inventory__.json")
                item.size, item.mtime, item.mode = len(inventory_bytes), 0, 0o644
                tar.addfile(item, io.BytesIO(inventory_bytes))
                for path in files:
                    relative = str(path.relative_to(root))
                    item = tarfile.TarInfo(relative)
                    item.size, item.mtime, item.mode = path.stat().st_size, 0, 0o644
                    with path.open("rb") as stream:
                        tar.addfile(item, stream)
        parts = []
        with archive.open("rb") as stream:
            index = 0
            while data := stream.read(part_bytes):
                path = destination / f"raw.part{index:04d}"
                path.write_bytes(data)
                parts.append({"path": str(path.relative_to(root)), "bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest(),
                              "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})
                index += 1
        result = {"schema": "hepta.raw-transport.v1", "format": "concatenated gzip tar parts",
                  "archive_sha256": digest(archive), "archive_bytes": archive.stat().st_size,
                  "inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
                  "files": len(files), "original_bytes": sum(value["bytes"] for value in inventory.values()),
                  "parts": parts, "lossless": True,
                  "scope": "All raw calibration targets/traces, fixed-anchor state tables, full confirmation trajectories, native owner journals, real broker files and both cold/reused process cost records."}
    manifest = root / "evidence/RAW_TRANSPORT.json"
    with manifest.open("x", encoding="utf8") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result


def restore(root, *, destination=None):
    root = Path(root).resolve()
    destination = Path(destination).resolve() if destination else root
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "evidence/RAW_TRANSPORT.json").read_text())
    restored = already_present = 0
    with tempfile.TemporaryDirectory(prefix="restore_", dir=destination) as temporary:
        archive = Path(temporary) / "raw.tar.gz"
        with archive.open("wb") as out:
            for part in manifest["parts"]:
                source = (root / part["path"]).resolve()
                if not source.is_relative_to(root) or source.stat().st_size != part["bytes"] or digest(source) != part["sha256"]:
                    raise ValueError("transport part identity failed")
                with source.open("rb") as stream:
                    while data := stream.read(1024 * 1024):
                        out.write(data)
        if archive.stat().st_size != manifest["archive_bytes"] or digest(archive) != manifest["archive_sha256"]:
            raise ValueError("concatenated archive identity failed")
        with tarfile.open(archive, "r:gz") as tar:
            encoded_inventory = tar.extractfile("__inventory__.json").read()
            if hashlib.sha256(encoded_inventory).hexdigest() != manifest["inventory_sha256"]:
                raise ValueError("inventory identity failed")
            inventory = json.loads(encoded_inventory)
            names = {member.name for member in tar.getmembers()}
            if names != set(inventory) | {"__inventory__.json"}:
                raise ValueError("archive member set does not match inventory")
            for relative, expected in inventory.items():
                member = tar.getmember(relative)
                target = (destination / relative).resolve()
                if not member.isfile() or not relative.startswith("evidence/") or not target.is_relative_to(destination):
                    raise ValueError("invalid archive path or member type")
                if target.exists():
                    if target.stat().st_size != expected["bytes"] or digest(target) != expected["sha256"]:
                        raise FileExistsError("refuse to overwrite differing evidence: " + relative)
                    already_present += 1
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                data = tar.extractfile(member).read()
                if len(data) != expected["bytes"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
                    raise ValueError("archive payload identity failed")
                with target.open("xb") as out:
                    out.write(data)
                restored += 1
    return {"restored_files": restored, "already_identical_files": already_present,
            "archive_sha256": manifest["archive_sha256"], "all_payloads_verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("build", "restore"))
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    result = build(args.root) if args.operation == "build" else restore(args.root, destination=args.destination)
    print(json.dumps({key: value for key, value in result.items() if key != "parts"}))
