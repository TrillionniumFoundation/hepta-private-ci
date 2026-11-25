"""Verify and restore exact evidence bytes without changing a research result."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zlib

FORMAT = "hcsn-evidence-transport-v2"
PART_FORMAT = "hcsn-gzip-byte-parts-v2"
MAX_PART_BYTES = 480000
RAW_PART_BYTES = 479000


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git_blob_digest(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ValueError("invalid relative evidence path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in (".", "..") for p in path.parts) or path.as_posix() != value:
        raise ValueError("noncanonical relative evidence path: " + value)
    return path


def contained_file(root, value):
    relative = relative_path(value)
    root = root.resolve()
    path = root.joinpath(*relative.parts)
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("symlink is not an evidence part: " + value)
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError("missing or escaping evidence file: " + value)
    return path


def manifest_objects(repo_root, index_path):
    index_bytes = Path(index_path).read_bytes()
    index = json.loads(index_bytes)
    if (index.get("format") != FORMAT or index.get("part_limit_bytes") != MAX_PART_BYTES
            or index.get("decoded_part_limit_bytes") != RAW_PART_BYTES):
        raise ValueError("unsupported transport index")
    objects, logical_paths, used_parts = [], set(), set()
    for entry in index["objects"]:
        raw = contained_file(repo_root, entry["manifest"]).read_bytes()
        if len(raw) != entry["manifest_bytes"] or digest(raw) != entry["manifest_sha256"]:
            raise ValueError("part manifest identity mismatch")
        obj = json.loads(raw)
        logical = obj["logical_path"]
        relative_path(logical)
        if (obj.get("format") != PART_FORMAT or obj["source_commit"] != index["source_commit"]
                or logical != entry["logical_path"] or logical in logical_paths
                or type(obj["bytes"]) is not int or obj["bytes"] <= 0):
            raise ValueError("invalid or duplicate logical object")
        logical_paths.add(logical)
        offset = 0
        for number, part in enumerate(obj["parts"]):
            relative_path(part["path"])
            if (part["index"] != number or part["offset"] != offset
                    or part.get("encoding") != "gzip-single-member"
                    or not part["path"].endswith(".bin.gz")
                    or type(part["encoded_bytes"]) is not int
                    or not 0 < part["encoded_bytes"] <= MAX_PART_BYTES
                    or type(part["decoded_bytes"]) is not int
                    or not 0 < part["decoded_bytes"] <= RAW_PART_BYTES
                    or part["path"] in used_parts):
                raise ValueError("unordered, duplicate, or oversized evidence part")
            used_parts.add(part["path"])
            offset += part["decoded_bytes"]
        if not obj["parts"] or offset != obj["bytes"]:
            raise ValueError("part sizes do not cover the exact original object")
        objects.append(obj)
    if not objects or len(objects) != index["object_count"]:
        raise ValueError("incomplete transport inventory")
    return index, index_bytes, objects


def verified_bytes(repo_root, obj):
    sha256 = hashlib.sha256()
    git_sha = hashlib.sha1(b"blob " + str(obj["bytes"]).encode() + b"\0")
    for part in obj["parts"]:
        with contained_file(repo_root, part["path"]).open("rb") as handle:
            encoded = handle.read(MAX_PART_BYTES + 1)
        if (len(encoded) != part["encoded_bytes"] or digest(encoded) != part["encoded_sha256"]
                or git_blob_digest(encoded) != part["git_blob_sha1"]):
            raise ValueError("evidence part identity mismatch: " + part["path"])
        decoder = zlib.decompressobj(wbits=31)
        try:
            raw = decoder.decompress(encoded, part["decoded_bytes"] + 1)
        except zlib.error as error:
            raise ValueError("invalid gzip evidence part: " + part["path"]) from error
        if (not decoder.eof or decoder.unused_data or decoder.unconsumed_tail
                or len(raw) != part["decoded_bytes"] or digest(raw) != part["decoded_sha256"]):
            raise ValueError("gzip decoded identity or single-member boundary mismatch: " + part["path"])
        sha256.update(raw)
        git_sha.update(raw)
        yield raw
    if sha256.hexdigest() != obj["sha256"] or git_sha.hexdigest() != obj["source_git_blob_sha1"]:
        raise ValueError("reassembled original identity mismatch: " + obj["logical_path"])


def verify_or_restore(repo_root, index_path, output_root=None):
    repo_root = Path(repo_root)
    index, index_bytes, objects = manifest_objects(repo_root, index_path)
    # Every part and complete original is verified before creating any output.
    for obj in objects:
        for _ in verified_bytes(repo_root, obj):
            pass
    if output_root is not None:
        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=False)
        for obj in objects:
            target = output_root.joinpath(*relative_path(obj["logical_path"]).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as handle:
                for raw in verified_bytes(repo_root, obj):
                    handle.write(raw)
    receipt = {"format": FORMAT, "status": "verified", "source_commit": index["source_commit"],
               "index_sha256": digest(index_bytes), "object_count": len(objects),
               "part_count": sum(len(o["parts"]) for o in objects),
               "original_bytes": sum(o["bytes"] for o in objects),
               "maximum_part_bytes": max(p["encoded_bytes"] for o in objects for p in o["parts"]),
               "encoded_bytes": sum(p["encoded_bytes"] for o in objects for p in o["parts"]),
               "maximum_decoded_part_bytes": max(p["decoded_bytes"] for o in objects for p in o["parts"]),
               "restored": output_root is not None,
               "objects": [{k: o[k] for k in ("logical_path", "bytes", "sha256", "source_git_blob_sha1")}
                           for o in objects],
               "scope": "Exact byte transport only; no metric, threshold, source model, or experiment change."}
    if output_root is not None:
        with (output_root / "TRANSPORT_RESTORE_RECEIPT.json").open("x") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--index", type=Path, default=Path(__file__).with_name("INDEX.json"))
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_or_restore(args.repo_root, args.index, args.output_root), indent=2, sort_keys=True))
