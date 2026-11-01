"""Restore all published primary training bytes without training or rewriting.

Run from the repository root with a standard-library Python installation:
    python -m tools.hcsn.digital_read_before_20261031.restore_training --out /tmp/digital-restored-primary

The output directory must not exist. Original JSON bytes, captured absolute paths
and recorded clocks remain unchanged. A failed restoration may leave a partial
new directory; it is never silently reused. The verification receipt is stdout.
"""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import tarfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("invalid relative archive path")
    posix, windows = PurePosixPath(name), PureWindowsPath(name)
    if (posix.is_absolute() or windows.drive or windows.is_absolute()
            or any(part in ("", ".", "..") for part in name.split("/"))
            or posix.as_posix() != name):
        raise ValueError(f"unsafe relative archive path: {name}")
    return Path(*posix.parts)


def read_record(record):
    relative = safe_name(record["path"])
    path = REPO/relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(REPO):
        raise ValueError("published artifact must be a regular file inside the repository")
    payload = path.read_bytes()
    if len(payload) != record["bytes"] or digest(payload) != record["sha256"]:
        raise IOError(f"published artifact identity mismatch: {relative}")
    return payload


def gunzip_checked(compressed, raw_bytes, raw_sha256):
    if not isinstance(raw_bytes, int) or raw_bytes < 0:
        raise ValueError("invalid declared uncompressed length")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
        raw = stream.read(raw_bytes+1)
        if len(raw) != raw_bytes or stream.read(1):
            raise IOError("uncompressed length mismatch")
    if digest(raw) != raw_sha256:
        raise IOError("uncompressed SHA-256 mismatch")
    return raw


def unpack_stream(record):
    payload = read_record(record)
    if record["encoding"] == "gzip":
        compressed = payload
    elif record["encoding"] == "gzip_chunks":
        index = json.loads(payload)
        if index["schema"] != "digital-gzip-chunks-v1":
            raise ValueError("unknown chunk index schema")
        for field in ("parts", "raw_bytes", "raw_sha256", "gzip_bytes", "gzip_sha256"):
            if index[field] != record[field]:
                raise IOError("chunk index differs from the per-fit declaration")
        paths = [part["path"] for part in index["parts"]]
        if not paths or len(paths) != len(set(paths)):
            raise ValueError("empty or repeated compressed chunks")
        compressed = b"".join(read_record(part) for part in index["parts"])
    else:
        raise ValueError("unsupported archive encoding")
    if len(compressed) != record["gzip_bytes"] or digest(compressed) != record["gzip_sha256"]:
        raise IOError("complete gzip stream identity mismatch")
    return gunzip_checked(compressed, record["raw_bytes"], record["raw_sha256"])


def checked_members(archive, expected):
    declared = {}
    for record in expected:
        path = safe_name(record["path"])
        if record["path"] in declared or not isinstance(record["bytes"], int) or record["bytes"] < 0:
            raise ValueError("duplicate member declaration or invalid size")
        declared[record["path"]] = record
        for parent in path.parents:
            if parent != Path(".") and parent.as_posix() in declared:
                raise ValueError("archive file/directory path conflict")
    for name in declared:
        if any(parent.as_posix() in declared for parent in safe_name(name).parents if parent != Path(".")):
            raise ValueError("archive file/directory path conflict")
    members, seen = archive.getmembers(), set()
    for member in members:
        safe_name(member.name)
        if (member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.pax_headers
                or member.name in seen or member.name not in declared):
            raise ValueError("archive contains a nonregular, repeated or undeclared member")
        if member.size != declared[member.name]["bytes"]:
            raise IOError("archive member length differs from the inventory")
        seen.add(member.name)
    if [m.name for m in members] != [r["path"] for r in expected]:
        raise IOError("archive member inventory/order differs from its declaration")
    return members, declared


def restore_fit(raw_tar, expected, destination):
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode="r:") as archive:
        members, declared = checked_members(archive, expected)
        destination.mkdir(exist_ok=False)
        for member in members:
            target = destination/safe_name(member.name)
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("member would escape its fit directory")
            with archive.extractfile(member) as source:
                payload = source.read(member.size+1)
            record = declared[member.name]
            if len(payload) != record["bytes"] or digest(payload) != record["sha256"]:
                raise IOError(f"archive member content mismatch: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(payload)
            if target.read_bytes() != payload:
                raise IOError(f"restored file readback mismatch: {member.name}")
    return dict(files=len(members), bytes=sum(r["bytes"] for r in expected))


def restore_training(out):
    requested = Path(out).expanduser()
    if requested.exists() or requested.is_symlink():
        raise FileExistsError("restoration requires a fresh output directory; existing paths are never overwritten")
    output = requested.resolve()
    aggregate_path = HERE/"evidence/training/PACKAGING_ALL_PRIMARY.json"
    aggregate_raw, freeze_raw = aggregate_path.read_bytes(), (HERE/"MODEL_FREEZE.json").read_bytes()
    aggregate, freeze = json.loads(aggregate_raw), json.loads(freeze_raw)
    for field in ("models", "training_data_sha256", "source_sha256", "source_commit", "source_freeze_sha256"):
        if aggregate[field] != freeze[field]:
            raise IOError("primary packaging and MODEL_FREEZE disagree: " + field)
    fits = [entry["fit"] for entry in aggregate["fits"]]
    if len(fits) != len(set(fits)) or {str(fit) for fit in fits} != set(freeze["training_data_sha256"]):
        raise ValueError("incomplete or repeated fit inventory")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for entry in aggregate["fits"]:
        fit = entry["fit"]
        if not isinstance(fit, int) or fit < 0:
            raise ValueError("invalid fit identifier")
        index_raw = read_record(entry["index"])
        index = json.loads(index_raw)
        if (index["fit"] != fit or index["stage"] != "primary"
                or index["source_freeze_sha256"] != freeze["source_freeze_sha256"]):
            raise ValueError("per-fit packaging identity mismatch")
        raw_tar = unpack_stream(index["full_fit"])
        folder = output/f"fit_{fit}"
        restored = restore_fit(raw_tar, index["full_fit_members"], folder)
        data_path = folder/"data"/f"fit_{fit}_data.json"
        data_hash = digest(data_path.read_bytes())
        if data_hash != freeze["training_data_sha256"][str(fit)] or data_hash != index["training_data_sha256"]:
            raise IOError("restored training data differs from MODEL_FREEZE")
        models = []
        for model in [m for m in freeze["models"] if m["fit"] == fit]:
            frozen = gunzip_checked(read_record(model), model["raw_bytes"], model["model_sha256"])
            family_path = safe_name(model["family"]+".json")
            restored_model = (folder/"models"/family_path).read_bytes()
            if restored_model != frozen:
                raise IOError("restored model is not byte-identical to MODEL_FREEZE")
            models.append(dict(family=model["family"], bytes=len(frozen), sha256=digest(frozen), byte_identical=True))
        if index["models"] != [m for m in freeze["models"] if m["fit"] == fit]:
            raise IOError("per-fit model inventory differs from MODEL_FREEZE")
        records.append(dict(fit=fit, **restored, index_sha256=digest(index_raw),
                            training_data_sha256=data_hash, tar_sha256=index["full_fit"]["raw_sha256"],
                            tar_bytes=len(raw_tar), gzip_sha256=index["full_fit"]["gzip_sha256"],
                            gzip_bytes=index["full_fit"]["gzip_bytes"], models=models))
    return dict(schema="digital-primary-training-restore-check-v1", status="passed",
                checked_at=datetime.now(timezone.utc).isoformat(), output=str(output),
                fits=records, fit_count=len(records), files=sum(r["files"] for r in records),
                restored_file_bytes=sum(r["bytes"] for r in records),
                frozen_models_verified=sum(len(r["models"]) for r in records),
                aggregate_sha256=digest(aggregate_raw), model_freeze_sha256=digest(freeze_raw),
                restorer_sha256=digest(Path(__file__).read_bytes()), source_commit=freeze["source_commit"],
                archive_checks="Every index/chunk/gzip/tar identity and byte count; every regular member identity; restored file readback; complete training-data and model equality to MODEL_FREEZE.",
                safety="Fresh output only; no absolute paths, traversal, duplicate members, links, special files, PAX metadata or file/directory conflicts; no extractall.",
                preservation="Original file bytes restored unchanged, including captured JSON paths and clocks; no training or experiment was run.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(restore_training(args.out), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
