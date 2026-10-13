"""Pinned source ZIP checks and model-stage metadata for disjoint Qwen shards.

This tool NEVER downloads model weights, reads task labels, judges source entailment,
generates text or promotes a memory policy. Historical stage timing cannot be
counted as a new shard's model download cost.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

ORIGINAL_ZIP_SHA = "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b"
HISTORICAL_MODEL_ZIP_SHA = (
    "129351221d56c9668c57e33f8dec79a6443c0252675752085538375b12ca25a8"
)
ORIGINAL_SOURCE_COMMIT = "c9dd3aeff958fbdc4356a98718e96dec47f9b820"
HISTORICAL_MODEL_COMMIT = "02c12b4aff0d589d10e5ed25d22b05d794ca96a0"
CANONICAL_SHA = {
    "stage.json": "1b96ffaa0644f02511d0f8f1cd47f8eb4cf6bce68191220708f3ccbf592b6e2b",
    "inventory.json": "ff0aea3f394f7257e004799e69edd691749d9d98f0949d64f068bb5d71165e9b",
    "publisher.json": "535b5cb5b0ed47db7fce1a9c73cb16fec31984e14909ad621c1d7cf2cbe0e234",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verified_zip(path, expected_zip_sha, *, expected_commit, max_total):
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 16 * 1024 * 1024
    ):
        raise ValueError("bounded regular Actions ZIP required")
    if sha(path.read_bytes()) != expected_zip_sha:
        raise ValueError(
            "downloaded Actions artifact does not match externally pinned ZIP"
        )
    with zipfile.ZipFile(path) as z:
        info = z.infolist()
        if not 1 <= len(info) <= 256 or sum(i.file_size for i in info) > max_total:
            raise ValueError("ZIP content census or expanded size exceeds bound")
        names = set()
        for entry in info:
            name = PurePosixPath(entry.filename)
            if (
                name.is_absolute()
                or ".." in name.parts
                or "\\" in entry.filename
                or entry.is_dir()
                or stat.S_ISLNK(entry.external_attr >> 16)
                or str(name) in names
            ):
                raise ValueError("unsafe, duplicate or nonregular ZIP member")
            names.add(str(name))
        if "SHA256SUMS" not in names or "tested-commit.txt" not in names:
            raise ValueError("missing immutable archive provenance")
        pins = {}
        for line in z.read("SHA256SUMS").decode("utf-8").splitlines():
            found = re.fullmatch(r"([a-f0-9]{64})  (?:\./)?(.+)", line)
            if found is None:
                raise ValueError("invalid SHA256SUMS member")
            value, name = found.groups()
            path_name = PurePosixPath(name)
            if (
                path_name.is_absolute()
                or ".." in path_name.parts
                or name not in names
                or name in pins
            ):
                raise ValueError("unsafe, missing or repeated manifest member")
            pins[name] = value
            if sha(z.read(name)) != value:
                raise ValueError("ZIP member differs from source SHA256SUMS")
        if set(pins) != names - {"SHA256SUMS"}:
            raise ValueError("missing or extra ZIP members")
        if z.read("tested-commit.txt").decode().strip() != expected_commit:
            raise ValueError("unexpected archived generating source")
        return {name: z.read(name) for name in names}


def extract_original(archive, destination):
    files = verified_zip(
        archive,
        ORIGINAL_ZIP_SHA,
        expected_commit=ORIGINAL_SOURCE_COMMIT,
        max_total=32 * 1024 * 1024,
    )
    destination.mkdir()
    for name, payload in files.items():
        out = destination / name
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("xb") as f:
            f.write(payload)
    required = {
        "plan/plan.json": "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897",
        "observations/collection.json": "be47e85e87692fa0c5036ebf1aa6090e040334b70719a9103e880960e6a60da9",
    }
    for name, digest in required.items():
        if sha((destination / name).read_bytes()) != digest:
            raise ValueError("source plan or observation collection is not frozen")
    return len(files)


def extract_model_identity(archive, destination):
    files = verified_zip(
        archive,
        HISTORICAL_MODEL_ZIP_SHA,
        expected_commit=HISTORICAL_MODEL_COMMIT,
        max_total=4 * 1024 * 1024,
    )
    if len(files) != 26:
        raise ValueError("unexpected historical model receipt census")
    destination.mkdir()
    for name, expected in CANONICAL_SHA.items():
        if sha(files[name]) != expected:
            raise ValueError("model identity metadata differs from canonical Qwen")
        with (destination / name).open("xb") as f:
            f.write(files[name])
    (destination / "PROVENANCE.txt").write_text(
        "source_run=38111452963\nsource_artifact=11696974258\n"
        "use=canonical exact Qwen identity only\n"
        "historical_stage_seconds_not_new_shard_cost=true\n",
        encoding="utf-8",
    )
    return CANONICAL_SHA["stage.json"]


def align_model_stage(live, canonical, observation):
    """Align only elapsed-time-bearing stage metadata, never model files."""
    for name in ("inventory.json", "publisher.json"):
        if sha((live / name).read_bytes()) != CANONICAL_SHA[name]:
            raise ValueError(
                "independently staged Qwen model differs from pinned identity"
            )
    staged = json.loads((live / "stage.json").read_text())
    locked = json.loads((canonical / "stage.json").read_text())
    if set(staged) != set(locked) or any(
        staged[key] != locked[key] for key in locked if key != "seconds"
    ):
        raise ValueError("model stage changed beyond observed download duration")
    if (
        type(staged["seconds"]) not in (int, float)
        or not 0 <= staged["seconds"] < 3600
    ):
        raise ValueError("untrusted model staging duration")
    if sha((canonical / "stage.json").read_bytes()) != CANONICAL_SHA["stage.json"]:
        raise ValueError("reused historical stage identity mutated")
    receipt = {
        "schema": "hepta.memory-strong-rag.shard-stage-observation.v1",
        "actual_shard_model_staging_seconds": staged["seconds"],
        "canonical_stage_digest": CANONICAL_SHA["stage.json"],
        "canonical_stage_seconds_are_historical": True,
        "model_weights_changed": False,
        "training_performed": False,
        "production_accepted": False,
    }
    with observation.open("x", encoding="utf-8") as out:
        json.dump(receipt, out, sort_keys=True, allow_nan=False)
        out.write("\n")
    shutil.copyfile(canonical / "stage.json", live / "stage.json")
    return receipt


def check_tree(directory):
    source = directory / "SHA256SUMS"
    if source.is_symlink() or not source.is_file():
        raise ValueError("missing directory manifest")
    listed = set()
    for row in source.read_text().splitlines():
        found = re.fullmatch(r"([a-f0-9]{64})  (?:\./)?(.+)", row)
        if found is None:
            raise ValueError("invalid folder manifest")
        expected, name = found.groups()
        entry = directory / name
        if name in listed or ".." in PurePosixPath(name).parts:
            raise ValueError("duplicate/unsafe manifest")
        listed.add(name)
        if (
            entry.is_symlink()
            or not entry.is_file()
            or sha(entry.read_bytes()) != expected
        ):
            raise ValueError("folder member changed")
    physical = {
        f.relative_to(directory).as_posix()
        for f in directory.rglob("*")
        if f.is_file()
    }
    if physical != listed | {"SHA256SUMS"}:
        raise ValueError("folder census mismatch")
    return len(listed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("original", "identity", "align", "verify"):
        sub.add_parser(action)
    parser.choices["original"].add_argument("archive", type=Path)
    parser.choices["original"].add_argument("output", type=Path)
    parser.choices["identity"].add_argument("archive", type=Path)
    parser.choices["identity"].add_argument("output", type=Path)
    parser.choices["align"].add_argument("live", type=Path)
    parser.choices["align"].add_argument("canonical", type=Path)
    parser.choices["align"].add_argument("receipt", type=Path)
    parser.choices["verify"].add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.action == "original":
        result = extract_original(args.archive, args.output)
    elif args.action == "identity":
        result = extract_model_identity(args.archive, args.output)
    elif args.action == "align":
        result = align_model_stage(args.live, args.canonical, args.receipt)
    else:
        result = check_tree(args.directory)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
