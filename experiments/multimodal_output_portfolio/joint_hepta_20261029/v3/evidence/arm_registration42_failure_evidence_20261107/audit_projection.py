"""Verify the complete declared ARM view and retain only a small diagnostic subset."""

from collections import Counter
import hashlib
import io
import shutil
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
import zipfile
import zlib

HERE = Path(__file__).resolve().parent
HEAD = "8b0fcf80afb95c5199be9b5f131d6454663c1632"
TREE = "8b46b24ccca6bf77227e1b21aa66ec84b0ea5473"
MERGE = "99e81f8e932e805869d57bd8534761b9f3266ed8"
PREFIXES = [
    "preparation/prefetch/cargo-home/",
    "qualification/build/cargo-home/",
    "qualification/build/cold-test/",
    "qualification/build/cold-product/",
]
SUFFIXES = [".json", ".jsonl", ".log", ".stderr", ".stdout", ".txt", ".xml"]
BOUNDS = {
    "max_files": 5000,
    "max_path_bytes": 1024,
    "part_bytes": 134217728,
    "max_parts": 8,
}
EXPECTED = {
    "artifact-13568260268.zip.gz": (
        21253917,
        "11c8ad717e752a2ccbe8a3ff0cc9e9f47ca2e3c7b0385cb93f3a1a098152a2ae",
    ),
    "artifact-13567472872.zip.gz": (
        69734546,
        "a9decf8d808f4f104cd45c5495b4995007718c7d6c5cd220a1c1e64e48f5321d",
    ),
}


def require(value, code):
    if not value:
        raise ValueError(code)


def pairs(rows):
    result = {}
    for key, value in rows:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs)


def ident(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def safe_name(name):
    require(isinstance(name, str) and 0 < len(name.encode()) <= 1024, "PATH_BOUND")
    require(
        not any(ord(c) < 32 or ord(c) == 127 or c in "\\:" for c in name), "UNSAFE_PATH"
    )
    path = PurePosixPath(name)
    require(not path.is_absolute() and path.as_posix() == name, "PATH_SHAPE")
    require(all(p not in {"", ".", ".."} for p in name.split("/")), "PATH_TRAVERSAL")
    return path


def retain(name):
    return (
        name == "CI_RESULT.json"
        or name.endswith(
            (
                "SOURCE_SEAL.json",
                "BUILD_RESULT.json",
                "PREPARATION_RESULT.json",
                "EXECUTION_RESULT.json",
                "process-identity-ledger.json",
            )
        )
        or name
        in {
            "qualification/RESULT.json",
            "qualification/runtime/nextest-store/linux-synapse/junit.xml",
        }
        or name.startswith("qualification/runtime/commands/")
        or name.startswith(
            (
                "qualification/build/commands/000-",
                "qualification/build/commands/001-",
                "qualification/build/commands/024-",
                "qualification/build/commands/026-",
                "qualification/build/commands/027-",
            )
        )
        or (
            name.startswith("qualification/controller-commands/")
            and "-container-final-log." in name
        )
    )


archives, raw_archives, wrappers = {}, {}, {}
for name, (size, digest) in EXPECTED.items():
    file = HERE / name
    receipt_file = HERE / (name.removesuffix(".zip.gz") + ".WRAPPER.json")
    wrapper_receipt = parse(receipt_file.read_bytes())
    wrapped = file.read_bytes()
    require(
        ident(wrapped)
        == {
            key: wrapper_receipt["complete_zip_wrapper"][key]
            for key in ("bytes", "sha256")
        },
        "WRAPPER_IDENTITY",
    )
    decoder = zlib.decompressobj(wbits=31)
    raw = decoder.decompress(wrapped, size + 1)
    require(
        decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail,
        "WRAPPER_SINGLE_MEMBER",
    )
    require(
        ident(raw) == {"bytes": size, "sha256": digest}, "OFFICIAL_ARCHIVE_IDENTITY"
    )
    require(
        wrapper_receipt["source_head"] == HEAD
        and wrapper_receipt["run_id"] == 42353199414,
        "WRAPPER_SOURCE",
    )
    archives[name] = {"bytes": size, "sha256": digest}
    wrappers[name] = {
        **ident(wrapped),
        "original_zip_exact_roundtrip": True,
        "receipt": ident(receipt_file.read_bytes()),
    }
    raw_archives[name] = raw
with zipfile.ZipFile(
    io.BytesIO(raw_archives["artifact-13568260268.zip.gz"])
) as archive:
    require(
        archive.namelist()
        == ["DIAGNOSTICS.json", "PROJECTION.json", "SOURCE_DIRECTORY.json"],
        "MANIFEST_MEMBERS",
    )
    require(archive.testzip() is None, "MANIFEST_CRC")
    metadata = {name: archive.read(name) for name in archive.namelist()}
diagnostics, projection, catalogue = [
    parse(metadata[n])
    for n in ["DIAGNOSTICS.json", "PROJECTION.json", "SOURCE_DIRECTORY.json"]
]
require(
    projection["source_commit"] == HEAD
    and projection["complete_projection"] is True
    and diagnostics["complete"] is True,
    "COMPLETE_SOURCE_VIEW",
)
require(
    all(
        projection[k] is True
        for k in [
            "collector_called",
            "source_catalogue_complete",
            "original_selected_files_unchanged",
        ]
    ),
    "VIEW_COMPLETION",
)
require(
    projection["whole_original_artifact_restorable"] is False
    and projection["qualification_or_promotion"] is False
    and diagnostics["qualification_or_promotion"] is False,
    "SCOPE_FLAGS",
)
require(diagnostics["original_artifact_unchanged"] is True, "ORIGINAL_UNCHANGED")
require(
    projection["original_collector_sha256"]
    == "47867b1e884c29993524558020b4dcf3800910ae33dc00feb11b435081be0761",
    "COLLECTOR_IDENTITY",
)
require(projection["bounds"] == diagnostics["bounds"] == BOUNDS, "ORIGINAL_BOUNDS")
require(
    projection["selection"] == {"suffixes": SUFFIXES, "excluded_prefixes": PREFIXES},
    "VIEW_SELECTION",
)
require(
    diagnostics["selection"] == {"recursive_suffixes": SUFFIXES}, "COLLECTOR_SELECTION"
)
require(
    projection["diagnostics"] == ident(metadata["DIAGNOSTICS.json"])
    and projection["source_catalogue"] == ident(metadata["SOURCE_DIRECTORY.json"]),
    "METADATA_IDENTITIES",
)
require(
    diagnostics["workflow"]
    == {"GITHUB_RUN_ID": "42353199414", "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": MERGE},
    "WORKFLOW_IDENTITY",
)
require(
    isinstance(catalogue, list)
    and len(catalogue) <= 200000
    and len(metadata["SOURCE_DIRECTORY.json"]) <= 67108864,
    "CATALOGUE_BOUND",
)
seen, selected = set(), set()
excluded = {p: {"entries": 0, "lstat_bytes": 0, "suffix_files": 0} for p in PREFIXES}
for row in catalogue:
    require(set(row) == {"path", "lstat_bytes", "mode", "category"}, "CATALOGUE_FIELDS")
    name = row["path"]
    path = safe_name(name)
    require(
        name not in seen
        and type(row["lstat_bytes"]) is int
        and row["lstat_bytes"] >= 0
        and type(row["mode"]) is int,
        "CATALOGUE_ENTRY",
    )
    seen.add(name)
    category = next(
        (p for p in PREFIXES if name.startswith(p)),
        "selected" if path.suffix in SUFFIXES else "other-suffix",
    )
    require(row["category"] == category, "CATALOGUE_CLASSIFICATION")
    if category in excluded:
        excluded[category]["entries"] += 1
        excluded[category]["lstat_bytes"] += row["lstat_bytes"]
        excluded[category]["suffix_files"] += int(path.suffix in SUFFIXES)
    if category == "selected":
        require(
            stat.S_ISREG(row["mode"])
            and row["lstat_bytes"] == projection["files"][name]["bytes"],
            "SELECTED_METADATA",
        )
        selected.add(name)
require(excluded == projection["excluded_inventory"], "EXCLUSION_INVENTORY")
require(
    selected == set(projection["files"]) == set(diagnostics["files"]),
    "COMPLETE_SELECTED_SET",
)
require(
    len(selected) == diagnostics["file_count"] == 1474 <= BOUNDS["max_files"],
    "SELECTED_COUNT",
)
for name in selected:
    parts = safe_name(name).parts
    require(
        not any("/".join(parts[:n]) in selected for n in range(1, len(parts))),
        "PATH_PREFIX_CONFLICT",
    )
require(len(diagnostics["parts"]) == 1, "PART_COUNT")
part = diagnostics["parts"][0]
require(
    part["file"] == "part-01.tar.part" and part["bytes"] <= BOUNDS["part_bytes"],
    "PART_BOUND",
)
verified, selected_bytes, retained = set(), 0, {}
with zipfile.ZipFile(
    io.BytesIO(raw_archives["artifact-13567472872.zip.gz"])
) as archive:
    require(
        archive.namelist() == [part["file"]] and archive.testzip() is None,
        "PART_MEMBERS_AND_CRC",
    )
    with archive.open(part["file"]) as stream:
        tar_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    require(
        archive.getinfo(part["file"]).file_size == part["bytes"]
        and tar_sha == part["sha256"] == diagnostics["tar_sha256"],
        "COMPLETE_TAR_IDENTITY",
    )
    with (
        archive.open(part["file"]) as stream,
        tarfile.open(fileobj=stream, mode="r|") as tar,
    ):
        for member in tar:
            name = member.name
            safe_name(name)
            require(
                member.isfile()
                and member.mode == 0o600
                and name in selected
                and name not in verified,
                "TAR_MEMBER",
            )
            raw = tar.extractfile(member).read()
            require(
                member.size == len(raw) and ident(raw) == diagnostics["files"][name],
                "MEMBER_IDENTITY",
            )
            require(
                {**ident(raw), "crc32": f"{zlib.crc32(raw) & 0xFFFFFFFF:08x}"}
                == projection["files"][name],
                "MEMBER_CRC",
            )
            if retain(name):
                retained[name] = raw
            verified.add(name)
            selected_bytes += len(raw)
require(
    verified == selected
    and selected_bytes == diagnostics["selected_bytes"] == 68665776,
    "WHOLE_DECLARED_VIEW",
)
retained_total = sum(map(len, retained.values()))
require(retained_total <= 16 * 1024 * 1024, "RETAINED_SUBSET_BOUND")
require(
    shutil.disk_usage(HERE).free >= retained_total + 4 * 1024 * 1024,
    "RETAINED_SUBSET_SPACE",
)
destination = HERE / "reviewed-diagnostics"
destination.mkdir(exist_ok=False)
for name, raw in retained.items():
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)
    target.chmod(0o600)
    require(target.read_bytes() == raw, "RETAINED_BYTES")
receipt = {
    "source_head": HEAD,
    "source_tree": TREE,
    "workflow_merge": MERGE,
    "run_id": 42353199414,
    "job_id": 128346079305,
    "attempt": 1,
    "archives": archives,
    "whole_zip_lossless_wrappers": wrappers,
    "raw_zips_written_to_disk": False,
    "all_four_zip_members_crc_verified": True,
    "declared_selected_files": len(verified),
    "selected_bytes": selected_bytes,
    "all_member_sizes_sha256_crc32_verified": True,
    "source_catalogue_entries": len(catalogue),
    "all_catalogue_classifications_recomputed": True,
    "categories": dict(Counter(r["category"] for r in catalogue)),
    "original_bounds": BOUNDS,
    "tar_mode": "0600",
    "retained_mode": "0600",
    "retained_files": len(retained),
    "retained_bytes": sum(map(len, retained.values())),
    "retained_files_identities": {n: ident(b) for n, b in retained.items()},
    "complete_full_artifact_downloaded_or_restorable": False,
    "qualification_or_promotion": False,
    "scope": "Every selected payload was verified before retaining the small diagnostic subset. Excluded original entries have catalogue metadata only. Source tree/API binding and business timing interpretation are separate receipts; this does not claim business success.",
}
with (HERE / "PROJECTION_PAYLOAD_VALIDATION.json").open("x") as stream:
    stream.write(json.dumps(receipt, indent=2) + "\n")
print(
    json.dumps(
        {
            k: receipt[k]
            for k in [
                "declared_selected_files",
                "selected_bytes",
                "source_catalogue_entries",
                "retained_files",
                "retained_bytes",
            ]
        }
    )
)
