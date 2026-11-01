"""Content-addressed source/model publication contracts and portable archives."""
import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

from .run_study import digest, read_json, source_hashes, write_json
from .training import candidates


def make_model_freeze(training, protocol, source_commit):
    expected_sources = source_hashes()
    result = dict(schema="digital-mechanism-model-freeze-v1", utc=datetime.now(timezone.utc).isoformat(),
                  source_sha256=expected_sources, source_commit=source_commit,
                  protocol=protocol, fits=protocol["fits"], models_sha256={},
                  training_data_sha256={}, training_receipts_sha256={}, training_finished_sha256={},
                  training_process_sha256={}, confirmation_generated=False)
    for fit in protocol["fits"]:
        folder = training / f"fit_{fit}"
        finish = read_json(folder / "FINISHED.json")
        if finish["fit"] != fit or finish["development"] or finish["source_sha256"] != expected_sources:
            raise ValueError("formal fit was not executed with frozen sources")
        actual = {p.stem for p in (folder / "models").glob("*.json")}
        if actual != {c["id"] for c in candidates()}:
            raise ValueError("incomplete or extra formal model set")
        result["training_data_sha256"][str(fit)] = digest(folder / "extended_data.json.gz")
        result["training_finished_sha256"][str(fit)] = digest(folder / "FINISHED.json")
        process = training / "process_receipts" / f"fit_{fit}.json"
        if read_json(process)["returncode"] != 0:
            raise ValueError("failed formal process cannot qualify as complete")
        result["training_process_sha256"][str(fit)] = digest(process)
        for identifier in actual:
            model_digest = digest(folder / "models" / (identifier + ".json"))
            if model_digest != finish["models"][identifier]["sha256"]:
                raise ValueError("model changed after fit completion")
            result["models_sha256"][f"{fit}/{identifier}"] = model_digest
            result["training_receipts_sha256"][f"{fit}/{identifier}"] = digest(folder / "training" / (identifier + ".json.gz"))
    return result


def pack_directory(source, destination, basename, include=None):
    """Deterministic small text volumes; manifest preserves every original byte."""
    source, destination = Path(source), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    paths = sorted(p for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts
                   and (include is None or include(p.relative_to(source))))
    archive_buffer, entries = io.BytesIO(), []
    with tarfile.open(fileobj=archive_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for path in paths:
            raw = path.read_bytes()
            name = str(path.relative_to(source))
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(raw), 0, 0o644
            archive.addfile(info, io.BytesIO(raw))
            entries.append(dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    packed = gzip.compress(archive_buffer.getvalue(), compresslevel=6, mtime=0)
    encoded = base64.b64encode(packed)
    parts = []
    for i, offset in enumerate(range(0, len(encoded), 450000)):
        path = destination / f"{basename}.part{i:04d}.b64"
        raw = encoded[offset:offset + 450000] + b"\n"
        with path.open("xb") as stream:
            stream.write(raw)
        parts.append(dict(name=path.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    manifest = dict(schema="digital-mechanism-archive-v1", archive_sha256=hashlib.sha256(packed).hexdigest(),
                    archive_bytes=len(packed), parts=parts, files=entries,
                    timestamps="not preserved; chronological claims use original explicit receipt UTC only")
    write_json(destination / f"{basename}.manifest.json", manifest)
    return manifest


def restore_archive(manifest_path, destination):
    manifest_path, destination = Path(manifest_path), Path(destination)
    manifest = read_json(manifest_path)
    chunks = []
    for part in manifest["parts"]:
        raw = (manifest_path.parent / part["name"]).read_bytes()
        if len(raw) != part["bytes"] or hashlib.sha256(raw).hexdigest() != part["sha256"]:
            raise ValueError("archive volume mismatch")
        chunks.append(raw.strip())
    packed = base64.b64decode(b"".join(chunks), validate=True)
    if hashlib.sha256(packed).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("archive hash mismatch")
    expected = {e["path"]: e for e in manifest["files"]}
    destination.mkdir(parents=True, exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(packed))) as archive:
        members = archive.getmembers()
        if len(members) != len(expected) or {m.name for m in members} != set(expected):
            raise ValueError("archive member mismatch")
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or not member.isfile():
                raise ValueError("unsafe archive member")
            raw = archive.extractfile(member).read()
            entry = expected[member.name]
            if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("restored content mismatch")
            out = destination / path
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("xb") as stream:
                stream.write(raw)
    return len(expected)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("freeze", "pack", "restore"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--basename", default="evidence")
    args = parser.parse_args()
    if args.stage == "freeze":
        write_json(args.destination, make_model_freeze(args.source, read_json(args.protocol), args.source_commit))
    elif args.stage == "pack":
        result = pack_directory(args.source, args.destination, args.basename)
        print(json.dumps(dict(files=len(result["files"]), parts=len(result["parts"]), bytes=result["archive_bytes"])))
    else:
        print(json.dumps(dict(restored=restore_archive(args.source, args.destination))))


if __name__ == "__main__":
    main()
