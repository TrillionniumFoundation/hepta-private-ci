"""Stable Qwen stage identity across CPU shards, with real timing preserved.

Only the per-host staging seconds are detached from the exact metadata hash.
Reader weights, publisher inventory, revision and original staging measurements
are never inferred or overwritten by a synthetic success record.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

SCHEMA = "hepta.memory-strong-rag.stage-observation.v1"
IDENTITY = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
REVISION = "82f42baa094a9600e39ccd80d34058aeeb3abbc1"
FIELDS = {
    "tier",
    "repository",
    "revision",
    "inventory_sha256",
    "publisher_sha256",
    "seconds",
    "model_file_bytes",
    "research_only",
    "production_accepted",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def plain(path):
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 4 * 1024 * 1024
    ):
        raise ValueError("bounded original model metadata required")
    return path.read_bytes()


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate model metadata key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite model metadata")

    return json.loads(
        raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant
    )


def encode(value):
    return (
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()


def save_new(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def normalize(directory):
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("ordinary model directory required")
    stage_path = root / "stage.json"
    original_bytes = plain(stage_path)
    stage = decode(original_bytes)
    if not isinstance(stage, dict) or set(stage) != FIELDS:
        raise ValueError("unregistered original Qwen stage")
    seconds = stage.pop("seconds")
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("invalid observed model download cost")
    if (
        stage["tier"] != "qwen-3b"
        or stage["repository"] != "Qwen/Qwen2.5-3B-Instruct"
        or stage["revision"] != REVISION
        or stage["research_only"] is not True
        or stage["production_accepted"] is not False
        or type(stage["model_file_bytes"]) is not int
        or stage["model_file_bytes"] <= 0
        or sha(plain(root / "inventory.json")) != stage["inventory_sha256"]
        or sha(plain(root / "publisher.json")) != stage["publisher_sha256"]
        or decode(plain(root / "inventory.json"))["inventory_digest"] != IDENTITY
    ):
        raise ValueError("pinned model inventory/publisher changed")
    canonical = encode(stage)
    observation = {
        "schema": SCHEMA,
        "original_stage_sha256": sha(original_bytes),
        "canonical_stage_sha256": sha(canonical),
        "staging_seconds": seconds,
        "reader_identity": IDENTITY,
        "inventory_sha256": stage["inventory_sha256"],
        "publisher_sha256": stage["publisher_sha256"],
        "measured": True,
        "production_accepted": False,
    }
    temporary = root / ".canonical-stage.pending"
    save_new(temporary, canonical)
    save_new(root / "stage-observation.json", encode(observation))
    os.replace(temporary, stage_path)
    if sha(plain(stage_path)) != observation["canonical_stage_sha256"]:
        raise ValueError("atomic canonical stage replacement failed")
    return observation


def verify(archive):
    root = Path(archive)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("ordinary model-answer archive required")
    canonical_sha = None
    totals = {}
    receipts = {}
    for phase in ("calibration", "evaluation"):
        measured = []
        for case in range(8):
            for part in range(2):
                key = f"memory-{phase}-{case}-{part}"
                folder = root / "shards" / phase / key
                canonical_bytes = plain(folder / "stage.json")
                stage = decode(canonical_bytes)
                if set(stage) != FIELDS - {"seconds"}:
                    raise ValueError("noncanonical sharded model stage")
                current_sha = sha(canonical_bytes)
                observation_bytes = plain(folder / "stage-observation.json")
                observation = decode(observation_bytes)
                if set(observation) != {
                    "schema",
                    "original_stage_sha256",
                    "canonical_stage_sha256",
                    "staging_seconds",
                    "reader_identity",
                    "inventory_sha256",
                    "publisher_sha256",
                    "measured",
                    "production_accepted",
                }:
                    raise ValueError("incomplete model staging cost census")
                seconds = observation["staging_seconds"]
                if (
                    type(seconds) not in (float, int)
                    or not math.isfinite(seconds)
                    or seconds < 0
                ):
                    raise ValueError("invalid original staging time")
                if (
                    observation["schema"] != SCHEMA
                    or observation["canonical_stage_sha256"] != current_sha
                    or observation["reader_identity"] != IDENTITY
                    or observation["inventory_sha256"] != stage["inventory_sha256"]
                    or observation["publisher_sha256"] != stage["publisher_sha256"]
                    or observation["measured"] is not True
                    or observation["production_accepted"] is not False
                ):
                    raise ValueError("model staging cost detached from fixed reader")
                timed = {}
                for field, value in stage.items():
                    timed[field] = value
                    if field == "publisher_sha256":
                        timed["seconds"] = seconds
                pins = decode(plain(folder / "sha-pins.json"))
                if (
                    sha(encode(timed)) != observation["original_stage_sha256"]
                    or pins.get("stage.json") != current_sha
                ):
                    raise ValueError(
                        "source stage timing does not reproduce measured bytes"
                    )
                if canonical_sha is None:
                    canonical_sha = current_sha
                elif canonical_sha != current_sha:
                    raise ValueError("independent CPU shards used different models")
                receipts[key] = sha(observation_bytes)
                measured.append(seconds)
        totals[phase] = {"hosts": len(measured), "staging_seconds_sum": sum(measured)}
    frozen = decode(plain(root / "calibration" / "frozen-policy.json"))
    if frozen.get("stage_sha256") != canonical_sha:
        raise ValueError("staging model differs from pre-evaluation frozen policy")
    return {
        "schema": "hepta.memory-strong-rag.stage-cost-census.v1",
        "canonical_stage_sha256": canonical_sha,
        "phases": totals,
        "all_staging_seconds_sum": sum(
            x["staging_seconds_sum"] for x in totals.values()
        ),
        "staging_observation_sha256": receipts,
        "not_concurrent_wall_time": True,
        "independent_semantic_review": False,
        "production_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    n = sub.add_parser("normalize")
    n.add_argument("model_dir", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("archive", type=Path)
    v.add_argument("--output", type=Path)
    v.add_argument("--expected", type=Path)
    args = parser.parse_args()
    if args.mode == "normalize":
        result = normalize(args.model_dir)
    else:
        result = verify(args.archive)
        if args.output is not None and args.expected is not None:
            raise ValueError("read-only replay must never overwrite original census")
        if args.expected is not None and decode(plain(args.expected)) != result:
            raise ValueError("independent staging cost replay differs")
        if args.output is not None:
            save_new(args.output, encode(result))
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
