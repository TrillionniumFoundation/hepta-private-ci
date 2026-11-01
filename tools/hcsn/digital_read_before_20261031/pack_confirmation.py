"""Lossless, deterministic delivery of a completed confirmation campaign.

Only a complete SUMMARY admits packaging. Every original regular file, including
the model cache, is retained. The complete run is a USTAR stream with normalized
metadata and gzip mtime=0; large compressed streams and inventories are chunked.
Packaging neither evaluates nor selects a candidate or changes scientific files.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import zlib

from .freeze_artifacts import HERE, REPO, MAX_BYTES, _pack, _read_stable, _write
from .freeze_artifacts import _verify_freeze, canonical, digest

BLOCK = 1024 * 1024


class HashedReader:
    def __init__(self, stream):
        self.stream, self.sha256, self.bytes = stream, hashlib.sha256(), 0

    def read(self, size=-1):
        payload = self.stream.read(size)
        self.sha256.update(payload)
        self.bytes += len(payload)
        return payload


def _file_identity(path):
    with Path(path).open("rb") as stream:
        reader = HashedReader(stream)
        while reader.read(BLOCK):
            pass
    return dict(sha256=reader.sha256.hexdigest(), bytes=reader.bytes)


def _files(root, external_log):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"symlink in confirmation evidence: {path}")
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path
        elif not path.is_dir():
            raise ValueError(f"nonregular confirmation evidence: {path}")
    if external_log.is_symlink() or not external_log.is_file():
        raise ValueError("the complete external confirmation log is required")
    name = "external_logs/" + external_log.name
    if name in files:
        raise ValueError("external log archive path conflicts with run evidence")
    files[name] = external_log
    return dict(sorted(files.items()))


def _stat(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular evidence file: {path}")
    value = path.stat()
    return value.st_size, value.st_mtime_ns


def _make_tar(files, destination):
    members, states = [], {}
    with tarfile.open(destination, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name, path in files.items():
            before = _stat(path)
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = before[0], 0, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as stream:
                reader = HashedReader(stream)
                archive.addfile(info, reader)
                extra = reader.read(1)
            if extra or reader.bytes != before[0] or _stat(path) != before:
                raise RuntimeError(f"source changed while archiving: {path}")
            members.append(dict(path=name, bytes=reader.bytes, sha256=reader.sha256.hexdigest()))
            states[name] = before
    return members, states


def _pack_stream(source, destination, temporary):
    compressed = temporary / "complete_run.tar.gz"
    with source.open("rb") as input_stream, compressed.open("xb") as output_stream:
        reader = HashedReader(input_stream)
        with gzip.GzipFile(filename="", mode="wb", fileobj=output_stream,
                           compresslevel=9, mtime=0) as compressor:
            while True:
                block = reader.read(BLOCK)
                if not block:
                    break
                compressor.write(block)
    zipped = _file_identity(compressed)
    metadata = dict(raw_sha256=reader.sha256.hexdigest(), raw_bytes=reader.bytes,
                    gzip_sha256=zipped["sha256"], gzip_bytes=zipped["bytes"])
    if zipped["bytes"] <= MAX_BYTES:
        return dict(**_write(destination, compressed.read_bytes()), encoding="gzip", **metadata)
    parts = []
    with compressed.open("rb") as stream:
        while True:
            block = stream.read(MAX_BYTES)
            if not block:
                break
            path = destination.with_name(destination.name + f".part{len(parts):04d}")
            parts.append(_write(path, block))
    index = dict(schema="digital-gzip-chunks-v1", parts=parts, **metadata,
                 reconstruction="Concatenate parts in listed order, verify gzip_sha256, then gzip-decompress and verify raw_sha256")
    return dict(**_write(destination.with_name(destination.name + ".index.json"), canonical(index)+b"\n"),
                encoding="gzip_chunks", parts=parts, **metadata)


def _assemble(record, destination):
    if record["encoding"] == "gzip":
        parts = [record]
    elif record["encoding"] == "gzip_chunks":
        encoded = _read_stable(REPO/record["path"])
        if digest(encoded) != record["sha256"]:
            raise IOError("archive chunk index changed")
        index = json.loads(encoded)
        if index["parts"] != record["parts"]:
            raise IOError("archive chunk declarations differ")
        parts = index["parts"]
    else:
        raise ValueError("unsupported archive encoding")
    sha, size = hashlib.sha256(), 0
    with destination.open("xb") as stream:
        for part in parts:
            payload = _read_stable(REPO/part["path"])
            if digest(payload) != part["sha256"] or len(payload) != part["bytes"]:
                raise IOError("archive chunk identity mismatch")
            stream.write(payload)
            sha.update(payload)
            size += len(payload)
    if sha.hexdigest() != record["gzip_sha256"] or size != record["gzip_bytes"]:
        raise IOError("reassembled archive identity mismatch")


def _verify_tar(record, files, members, states, temporary):
    joined = temporary/"reassembled.tar.gz"
    _assemble(record, joined)
    with gzip.open(joined, "rb") as stream:
        reader, seen = HashedReader(stream), []
        with tarfile.open(fileobj=reader, mode="r|") as archive:
            for info in archive:
                if not info.isfile() or len(seen) >= len(members):
                    raise IOError("unexpected archive member")
                expected = members[len(seen)]
                if (info.name != expected["path"] or info.size != expected["bytes"]
                        or info.mtime != 0 or info.mode != 0o644 or info.uid != 0 or info.gid != 0
                        or info.uname or info.gname):
                    raise IOError("archive member metadata mismatch")
                source = files[info.name]
                if _stat(source) != states[info.name]:
                    raise RuntimeError("original changed before archive verification")
                sha, size = hashlib.sha256(), 0
                with source.open("rb") as original, archive.extractfile(info) as recovered:
                    while True:
                        a, b = original.read(BLOCK), recovered.read(BLOCK)
                        if a != b:
                            raise IOError(f"archive does not recover original bytes: {info.name}")
                        if not a:
                            break
                        sha.update(a)
                        size += len(a)
                if (sha.hexdigest() != expected["sha256"] or size != expected["bytes"]
                        or _stat(source) != states[info.name]):
                    raise IOError("verified member identity changed")
                seen.append(info.name)
        # Include trailing USTAR records and padding in the complete data hash.
        while reader.read(BLOCK):
            pass
    if (seen != list(files) or reader.sha256.hexdigest() != record["raw_sha256"]
            or reader.bytes != record["raw_bytes"]):
        raise IOError("complete uncompressed archive identity mismatch")


def _admit(root):
    summary_path = root/"SUMMARY.json"
    if not summary_path.is_file():
        raise FileNotFoundError("SUMMARY.json is absent: confirmation is not complete; packaging has not started")
    summary_raw = _read_stable(summary_path)
    summary, started = json.loads(summary_raw), json.loads(_read_stable(root/"STARTED.json"))
    results_raw = _read_stable(root/"RESULTS.json")
    results = json.loads(results_raw)
    source, source_hash = _verify_freeze()
    model_raw = _read_stable(HERE/"MODEL_FREEZE.json")
    model_freeze, protocol = json.loads(model_raw), json.loads(_read_stable(HERE/"protocol.json"))
    if started["model_freeze_sha256"] != digest(model_raw):
        raise ValueError("confirmation MODEL_FREEZE identity mismatch")
    if (summary["published_model_commit"] != started["published_model_commit"]
            or summary["binary_sha256"] != started["binary_sha256"]
            or model_freeze["source_sha256"] != source["source_sha256"]):
        raise ValueError("confirmation source/model/binary provenance mismatch")
    groups = {f"{fit}_{split}_{family}_{controller}.json.gz"
              for fit in protocol["fits"] for split in ("iid", "ood")
              for family in protocol["families"]+[protocol["reference_family"]]
              for controller in protocol["controllers"]}
    expected_rows = (len(protocol["fits"])*(protocol["iid_worlds"]+protocol["ood_worlds"])
                     *(len(protocol["families"])+1)*len(protocol["controllers"]))
    if (not isinstance(results, list) or len(results) != expected_rows
            or {p.name for p in (root/"raw").iterdir()} != groups
            or summary["cohort_count"] != len(protocol["fits"])*2):
        raise ValueError("confirmation completion inventory is incomplete")
    cache = []
    for model in model_freeze["models"]:
        relative = f"models/{model['fit']}_{model['family']}.json"
        actual = _file_identity(root/relative)
        cache.append(dict(path=relative, **actual, frozen_path=model["path"],
                          frozen_sha256=model["sha256"], frozen_model_sha256=model["model_sha256"],
                          equals_frozen_model=actual["sha256"] == model["model_sha256"], retained_in_full_archive=True))
    return dict(summary_raw=summary_raw, results_raw=results_raw, source=source,
                source_freeze_sha256=source_hash, model_freeze_sha256=digest(model_raw),
                model_cache=cache, rows=len(results), groups=len(groups))


def pack_confirmation(runs, external_log=None):
    root = Path(runs).resolve()
    log = Path(external_log).resolve() if external_log is not None else root.with_name(root.name+".log")
    admitted = _admit(root)  # No artifact is written until SUMMARY admits the run.
    files = _files(root, log)
    destination = HERE/"evidence"/"confirmation"
    with tempfile.TemporaryDirectory(prefix="digital-confirmation-pack-") as scratch:
        temporary = Path(scratch)
        archive_path = temporary/"complete_run.tar"
        members, states = _make_tar(files, archive_path)
        archive = _pack_stream(archive_path, destination/"complete_run.tar.gz", temporary)
        _verify_tar(archive, files, members, states, temporary)
        if _files(root, log) != files or any(_stat(path) != states[name] for name, path in files.items()):
            raise RuntimeError("confirmation inventory changed during packaging")
    # These small entry points avoid decoding the complete campaign for review.
    summary = _write(destination/"SUMMARY.json", admitted["summary_raw"])
    results = _pack(destination/"RESULTS.json.gz", admitted["results_raw"])
    inventory = dict(schema="digital-confirmation-file-inventory-v1", original_root=str(root),
                     external_log=str(log), member_count=len(members), members=members,
                     original_file_bytes=sum(m["bytes"] for m in members))
    inventory_archive = _pack(destination/"ORIGINAL_FILES.json.gz", canonical(inventory)+b"\n")
    record = dict(schema="digital-confirmation-packaging-v1", complete_run=archive,
                  summary=summary, results=results, original_files=inventory_archive,
                  original_root=str(root), original_file_count=len(members),
                  original_file_bytes=inventory["original_file_bytes"],
                  confirmed_rows=admitted["rows"], raw_groups=admitted["groups"],
                  source_commit=admitted["source"]["source_commit"],
                  source_freeze_sha256=admitted["source_freeze_sha256"],
                  model_freeze_sha256=admitted["model_freeze_sha256"],
                  model_cache_deduplicated=False, model_cache=admitted["model_cache"],
                  packer_sources={p.name: digest(p.read_bytes()) for p in
                                  (Path(__file__), HERE/"freeze_artifacts.py")},
                  zlib_version=zlib.ZLIB_RUNTIME_VERSION,
                  deterministic_metadata="Sorted USTAR regular files; uid/gid/mtime=0, mode0644, empty owner names; gzip mtime=0 and empty filename.",
                  verification="Concatenated published chunks were decompressed; every recovered file was compared byte-for-byte with its stable original; complete gzip/tar hashes and every original file hash were checked.",
                  preservation="All original run files retained, including world public/packet/evaluator bytes, raw group JSON.gz, native stdout/stderr/checkpoint/journal/witness, STARTED/RESULTS/SUMMARY, all cached frozen models, and the external log. Injected missing packets remain absent as declared by evaluator records.")
    record["index"] = _write(destination/"PACKAGING_INDEX.json", canonical(record)+b"\n")
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--external-log", type=Path)
    args = parser.parse_args()
    result = pack_confirmation(args.runs, args.external_log)
    print(json.dumps({key: result[key] for key in
                      ("index", "original_file_count", "original_file_bytes", "confirmed_rows", "raw_groups", "complete_run")}, indent=2))


if __name__ == "__main__":
    main()
