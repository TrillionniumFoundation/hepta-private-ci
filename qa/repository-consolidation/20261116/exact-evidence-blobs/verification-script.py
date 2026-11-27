#!/usr/bin/env python3
"""Inspect retained evidence bytes without extracting or executing their contents."""

import ast
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import tarfile
import zipfile


ROOT = Path(__file__).parent
SOURCES = ROOT / "custody-source"
RECORDS = json.loads((ROOT / "blob-policy-records.json").read_text())


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def source_record(path):
    data = (SOURCES / path).read_bytes()
    return {
        "path": path,
        "git_blob": git_blob(data),
        "sha256": sha256(data),
        "bytes": len(data),
        "document": json.loads(data),
    }


def archive_members(data, mode, expected):
    actual = []
    with tarfile.open(fileobj=io.BytesIO(data), mode=mode) as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("non-regular archive member: " + member.name)
            name = member.name
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("unexpected archive member path: " + name)
            content = archive.extractfile(member).read()
            actual.append({"path": name, "bytes": len(content), "sha256": sha256(content)})
    if len(actual) != len({r["path"] for r in actual}):
        raise ValueError("duplicate archive member")
    if sorted(actual, key=lambda r: r["path"]) != sorted(expected, key=lambda r: r["path"]):
        raise ValueError("archive members differ from original manifest")
    return actual


def npz_structure(data):
    arrays = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if archive.testzip() is not None:
            raise ValueError("NPZ CRC failure")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate NPZ member")
        for info in archive.infolist():
            if not info.filename.endswith(".npy"):
                raise ValueError("unexpected NPZ member: " + info.filename)
            if Path(info.filename).is_absolute() or ".." in Path(info.filename).parts:
                raise ValueError("unexpected NPZ path")
            with archive.open(info) as member:
                if member.read(6) != b"\x93NUMPY":
                    raise ValueError("invalid NPY magic")
                version = tuple(member.read(2))
                if version not in {(1, 0), (2, 0), (3, 0)}:
                    raise ValueError("unsupported NPY header")
                width = 2 if version[0] == 1 else 4
                length = struct.unpack("<H" if width == 2 else "<I", member.read(width))[0]
                header = ast.literal_eval(
                    member.read(length).decode("utf-8" if version[0] == 3 else "latin1")
                )
                if set(header) != {"descr", "fortran_order", "shape"}:
                    raise ValueError("unexpected NPY header fields")
                dtype = re.fullmatch(r"[<>=|]([biufcUS])(\d+)", header["descr"])
                if dtype is None:
                    raise ValueError("object or unsupported dtype; no pickle loading permitted")
                itemsize = int(dtype[2]) * (4 if dtype[1] == "U" else 1)
                shape = header["shape"]
                if not isinstance(shape, tuple) or any(type(n) is not int or n < 0 for n in shape):
                    raise ValueError("invalid NPY shape")
                expected_size = 8 + width + length + math.prod(shape) * itemsize
                if info.file_size != expected_size:
                    raise ValueError("NPY shape/dtype byte count mismatch")
                arrays.append({
                    "name": info.filename,
                    "npy_version": list(version),
                    "dtype": header["descr"],
                    "shape": list(shape),
                    "fortran_order": header["fortran_order"],
                    "bytes": info.file_size,
                })
    return {"kind": "npz", "crc_checked": True, "pickle_loaded": False, "arrays": arrays}


groups = {
    "cell-p0-common-validation-20261111-c2fc": "qualification/cell-p0-common-validation-20261111-c2fc/SUMMARY.json",
    "hcsn_dense_sweep": "qualification/hcsn_dense_sweep/evidence/cost-attempt002-audit/outputs/SUMMARY.json",
    "hcsn_finite_review": "qualification/hcsn_finite_review/evidence/actual-v2-finite-attempt002/SUMMARY.json",
    "hcsn_graded": "qualification/hcsn_graded/evidence/actual-migrated-continuation-attempt002/SUMMARY.json",
    "hcsn_joint_dde": "qualification/hcsn_joint_dde/evidence/all-visits-attempt002/SUMMARY.json",
    "hcsn_secondcycle": "qualification/hcsn_secondcycle/evidence/references-attempt001/SUMMARY.json",
}
statuses = {}
for group, path in groups.items():
    record = source_record(path)
    document = record.pop("document")
    statuses[group] = {
        **record,
        "status": document["status"],
        "qualification_flags": {
            k: v for k, v in document.items()
            if k in {"all_closed", "finite_domain_qualified", "rare_phase_relative_precision_qualified"}
        },
    }

raw_manifest = source_record("qualification/cell-p0-common-validation-20261111-c2fc/RAW_MANIFEST.json")
review_manifest = source_record("qualification/hcsn_secondcycle/evidence/independent-git-review/MANIFEST.json")
review_document = review_manifest["document"]
part_shas = [
    "0d13389b4531487c372b9843ad645600ea314b0d",
    "816fe75003d8d8cb1bda02593fd78c0d8e7983ea",
    "fdf74727f9bf4cbfae11ade7931e51bfbf407958",
]
parts = [(ROOT / "blobs" / sha).read_bytes() for sha in part_shas]
for sha, data, expected in zip(part_shas, parts, review_document["payloads"]):
    if git_blob(data) != sha or len(data) != expected["bytes"] or sha256(data) != expected["sha256"]:
        raise ValueError("split archive part differs from original manifest")
review_archive = b"".join(parts)
if len(review_archive) != review_document["archive_bytes"] or sha256(review_archive) != review_document["archive_sha256"]:
    raise ValueError("split archive aggregate differs from original manifest")
review_members = archive_members(review_archive, "r:gz", [
    {"path": r["name"], "bytes": r["bytes"], "sha256": r["sha256"]}
    for r in review_document["members"]
])
with tarfile.open(fileobj=io.BytesIO(review_archive), mode="r:gz") as archive:
    review_status = json.loads(archive.extractfile("REVIEW.json").read())
review_flags = {
    k: v for k, v in review_status.items()
    if re.search(r"status|closed|decision|verdict|qualified|adopt|production", k)
}

verified = []
for record in RECORDS:
    data = (ROOT / "blobs" / record["sha"]).read_bytes()
    if len(data) != record["size"] or git_blob(data) != record["sha"]:
        raise ValueError("original blob identity mismatch: " + record["path"])
    path = record["path"]
    if path.endswith(".npz"):
        structure = npz_structure(data)
    elif path.endswith(".tar.xz"):
        manifest = raw_manifest["document"]
        members = archive_members(data, "r:xz", manifest["files"])
        if len(members) != manifest["raw_files"] or sum(r["bytes"] for r in members) != manifest["raw_bytes"]:
            raise ValueError("raw archive manifest totals mismatch")
        original_summary = json.loads((SOURCES / groups["cell-p0-common-validation-20261111-c2fc"]).read_bytes())
        if sha256(data) != original_summary["raw_archive"]["sha256"]:
            raise ValueError("raw archive summary digest mismatch")
        structure = {"kind": "tar.xz", "regular_members": len(members), "uncompressed_bytes": sum(r["bytes"] for r in members), "all_member_hashes_match": True, "manifest": {k: v for k, v in raw_manifest.items() if k != "document"}}
    elif ".tar.gz.part" in path:
        structure = {"kind": "split-tar.gz", "all_three_parts_verified": True, "aggregate_sha256": sha256(review_archive), "aggregate_bytes": len(review_archive), "regular_members": len(review_members), "all_member_hashes_match": True, "original_review_flags": review_flags, "manifest": {k: v for k, v in review_manifest.items() if k != "document"}}
    elif path.endswith(".json"):
        value = json.loads(data)
        structure = {"kind": "json", "root_type": type(value).__name__, "entries": len(value)}
        if isinstance(value, dict):
            structure["keys"] = sorted(value)
            structure["array_lengths"] = {k: len(v) for k, v in value.items() if isinstance(v, list)}
    else:
        raise ValueError("unreviewed evidence type")
    group = next(key for key in groups if f"/{key}/" in path)
    status_source = statuses[group]["path"]
    historical_status = statuses[group]["status"]
    extra_status = {}
    if structure["kind"] == "split-tar.gz":
        status_source = review_manifest["path"]
        historical_status = review_flags["status"]
        extra_status = {
            "historical_status_archive_member": next(
                member for member in review_members if member["path"] == "REVIEW.json"
            ),
            "historical_scientific_status": review_flags["scientific_status"],
            "historical_all_closed": review_flags["all_closed"],
        }
    verified.append({
        "path": path,
        "git_blob": record["sha"],
        "bytes": len(data),
        "sha256": sha256(data),
        "structure": structure,
        "historical_status_source": status_source,
        "historical_status": historical_status,
        **extra_status,
    })

result = {
    "schema": "hepta.exact-historical-evidence-blob-custody.v1",
    "observed_source_commit": "ca1ae598efb77b552df3897b8debc0441bc7bd90",
    "blocking_job": 133149163164,
    "blocking_run": 43822682848,
    "unchanged_size_limit_bytes": 512000,
    "verified_blobs": len(verified),
    "verified_original_bytes": sum(r["bytes"] for r in verified),
    "status_sources": statuses,
    "files": verified,
    "boundaries": [
        "Retention-only exact-byte exceptions; all original status and failure records remain unchanged.",
        "NPZ contents were CRC checked and their safe NPY headers/byte counts inspected; no pickle deserialization.",
        "Archive members were read and hashed in memory, without extraction or execution.",
        "No model, candidate, integral, expm, optimizer or scientific qualification was executed or adopted.",
        "Changed bytes and other paths retain the existing size limit; no threshold or generic path exemption changes.",
    ],
}
(ROOT / "blob-custody-receipt.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
lines = [
    "",
    "# Exact historical evidence retained from ca1ae598efb77b552df3897b8debc0441bc7bd90.",
    "# Custody, sizes, archive members and unchanged HOLD statuses are recorded in",
    "# qa/repository-consolidation/20261116/exact-evidence-blobs/custody-receipt.json.",
    "# Only these original bytes are exempt; changed content regains the 512000-byte limit.",
]
lines.extend(f"sha256:{r['sha256']} {r['path']}" for r in verified)
(ROOT / "blob-allowlist-append.txt").write_text("\n".join(lines) + "\n")
print(json.dumps({"verified_blobs": len(verified), "verified_original_bytes": result["verified_original_bytes"], "raw_members": raw_manifest["document"]["raw_files"], "review_members": len(review_members), "original_review_flags": review_flags}, indent=2))
