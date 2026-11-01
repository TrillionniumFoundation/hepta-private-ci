"""Wrap exact archive fragments in genuine gzip containers; stdlib bootstrap."""

import argparse
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import tempfile
import time

LIMIT, RAW = 480000, 479800
FROZEN = Path(__file__).resolve().parents[1] / "evidence.py"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def leaf(name):
    if not name or "\\" in name or PurePosixPath(name).parts != (name,) or name in (".", ".."):
        raise ValueError("Expected an adjacent normalized filename")
    return name


def checked(folder, record):
    path = folder / leaf(record["path"])
    if path.is_symlink() or not path.is_file():
        raise ValueError("Only adjacent regular files are permitted")
    data = path.read_bytes()
    if len(data) != record["bytes"] or sha(data) != record["sha256"]:
        raise ValueError("Transport file identity mismatch: " + record["path"])
    return data


def decoded(folder, record, maximum=RAW):
    if not 0 < record["raw_bytes"] <= maximum or record["bytes"] > LIMIT:
        raise ValueError("Container size outside the declared bounded transport")
    with gzip.GzipFile(fileobj=io.BytesIO(checked(folder, record))) as stream:
        data = stream.read(record["raw_bytes"] + 1)
    if len(data) != record["raw_bytes"] or sha(data) != record["raw_sha256"]:
        raise ValueError("Decoded fragment identity mismatch")
    return data


def container(folder, name, raw):
    blob = gzip.compress(raw, compresslevel=6, mtime=0)
    if len(blob) > LIMIT:
        raise ValueError("Container exceeds the publication limit")
    with (folder / leaf(name)).open("xb") as stream:
        stream.write(blob)
    return dict(path=name, bytes=len(blob), sha256=sha(blob), raw_bytes=len(raw), raw_sha256=sha(raw))


def wrap(index):
    if index.is_symlink() or not index.is_file() or (index.parent / "CONTAINERS.json").exists():
        raise ValueError("Regular legacy index and a fresh wrapping namespace required")
    original = index.read_bytes()
    record = json.loads(original)
    compact = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if record["schema"] != "hcsn.r13.evidence.v1" or len(compact) > 512000:
        raise ValueError("Unsupported or oversized compatible archive index")
    containers, combined = [], hashlib.sha256()
    with tempfile.TemporaryFile() as stream:
        for part in record["chunks"]:
            data = checked(index.parent, part)
            stream.write(data)
            combined.update(data)
        if stream.tell() != record["compressed_bytes"] or combined.hexdigest() != record["compressed_sha256"]:
            raise ValueError("Original combined archive identity mismatch")
        stream.seek(0)
        while data := stream.read(RAW):
            containers.append(container(index.parent, f"stream.part{len(containers):04d}.gz", data))
    legacy = container(index.parent, "legacy-index.json.gz", original)
    manifest = dict(schema="hcsn.r13.gzip-transport.v1", containers=containers, legacy_index=legacy,
        index=dict(path=index.name, bytes=len(compact), sha256=sha(compact)),
        compressed_bytes=record["compressed_bytes"], compressed_sha256=record["compressed_sha256"],
        frozen_restore_sha256=sha(FROZEN.read_bytes()), raw_fragment_limit=RAW, container_limit=LIMIT)
    temporary = index.with_name(index.name + ".compact-new")
    with temporary.open("xb") as stream:
        stream.write(compact)
    temporary.replace(index)
    with (index.parent / "CONTAINERS.json").open("x") as stream:
        json.dump(manifest, stream, sort_keys=True, separators=(",", ":"))
        stream.write("\n")
    return dict(containers=len(containers), outer_bytes=sum(c["bytes"] for c in containers),
        largest_container=max(c["bytes"] for c in containers), original_index_sha256=sha(original),
        compact_index_sha256=sha(compact), compressed_sha256=combined.hexdigest(), original_chunks_retained=True)


def restore(manifest_path, destination):
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Expected a regular transport manifest")
    manifest = json.loads(manifest_path.read_bytes())
    if manifest["schema"] != "hcsn.r13.gzip-transport.v1" or FROZEN.is_symlink():
        raise ValueError("Unsupported transport or symlinked restore source")
    if sha(FROZEN.read_bytes()) != manifest["frozen_restore_sha256"]:
        raise ValueError("Frozen restore implementation changed")
    index_bytes = checked(manifest_path.parent, manifest["index"])
    record = json.loads(index_bytes)
    if record != json.loads(decoded(manifest_path.parent, manifest["legacy_index"], 1000000)):
        raise ValueError("Compact index changes the original index semantics")
    with tempfile.TemporaryDirectory(prefix="hcsn-publication-") as temporary, tempfile.TemporaryFile() as stream:
        combined = hashlib.sha256()
        for part in manifest["containers"]:
            data = decoded(manifest_path.parent, part)
            stream.write(data)
            combined.update(data)
        if stream.tell() != record["compressed_bytes"] or stream.tell() != manifest["compressed_bytes"]:
            raise ValueError("Reassembled compressed byte count changed")
        if combined.hexdigest() != record["compressed_sha256"] or combined.hexdigest() != manifest["compressed_sha256"]:
            raise ValueError("Reassembled original compressed SHA256 changed")
        stream.seek(0)
        for part in record["chunks"]:
            data = stream.read(part["bytes"])
            if len(data) != part["bytes"] or sha(data) != part["sha256"]:
                raise ValueError("Reconstructed legacy inner chunk changed")
            (Path(temporary) / leaf(part["path"])).write_bytes(data)
        if stream.read(1):
            raise ValueError("Legacy index omits compressed bytes")
        temporary_index = Path(temporary) / "INDEX.json"
        temporary_index.write_bytes(index_bytes)
        spec = importlib.util.spec_from_file_location("hcsn_frozen_evidence", FROZEN)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.restore(temporary_index, destination)
    return dict(**result, containers=len(manifest["containers"]), original_chunks=len(record["chunks"]),
                compressed_sha256=combined.hexdigest(), frozen_restore_sha256=manifest["frozen_restore_sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("wrap", "restore"))
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.action == "restore" and args.destination is None:
        parser.error("restore requires --destination")
    cpu, wall = time.process_time(), time.perf_counter()
    result = wrap(args.index) if args.action == "wrap" else restore(args.index, args.destination)
    print(json.dumps(dict(**result, cpu_body_seconds=time.process_time()-cpu,
                         wall_body_seconds=time.perf_counter()-wall), sort_keys=True))
