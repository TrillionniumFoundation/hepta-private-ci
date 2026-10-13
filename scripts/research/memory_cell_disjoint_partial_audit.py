#!/usr/bin/env python3
"""Independent read-only verification of ORIGINAL BF16 Qwen calibration shard ZIPs.

Not a model inference, truth oracle, new training result, or production promotion.
The 8x5 registered calibration matrix is sealed only after every shard exists.
"""

import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import re
import stat
import zipfile

SOURCE = "bc76ac57ba972bf105c71ddd997cd215cec5df2e"
HISTORIC_PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
MODEL_ID = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
STAGE_SHA = "1b96ffaa0644f02511d0f8f1cd47f8eb4cf6bce68191220708f3ccbf592b6e2b"
ORIG_ZIP_SHA = "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b"
ARM_PART = {0: ("k1", "k3", "k6"), 1: ("k2", "k4")}
ALL = tuple((case, part) for case in range(8) for part in (0, 1))
SHA = re.compile(r"[0-9a-f]{64}")
PREP_ZIP_SHA = "5f4e13b23893ab64666296f565ed9884a4328f451859c0e1b10cfb4b64b19732"
# Original Actions artifact IDs and outer ZIP SHA256, registered before any new replays.
PINNED_SHARDS = {
    "0-0": (
        11827974042,
        "ad10d1d87aa3671fd347d4ca3bbe66c671a82055a58b4e9896f266ba3125fe93",
    ),
    "0-1": (
        11828136602,
        "32b873bf342811ff2a40399f2502877b03174d06fec5ed017caad17602e11545",
    ),
    "1-0": (
        11828627869,
        "ec13c6fc5d4dd00ba321a4f9088ca3245ddeaedd1bee8080ed0429380c540ac8",
    ),
    "1-1": (
        11828351185,
        "d07af975b34f7c6d43a5c32b451af7b80478fc2942482a0dad36262c25207889",
    ),
    "2-0": (
        11828274151,
        "1b57d31a6679df7cddb5aa6b6e53fe63b6066895bc0f3b102e197a213a0d4345",
    ),
    "2-1": (
        11830211593,
        "72a734682ae0811e77c070d0204297c4fb01da966af7118171e7e5997b01855f",
    ),
    "3-0": (
        11829732241,
        "5619331cdfa8e22f97fb680461ece6d9f78c1b1ec18622184a5fa1bdecbad058",
    ),
    "3-1": (
        11827058630,
        "8f758438131e7c262cadbedd33930ed89e024a08400a5088b2d4bc17613c8c6f",
    ),
    "4-0": (
        11828171663,
        "525bd94bcee18f8eb5808c4ae52aa7df06185c4fc0a9a443ac70d136e2a3a338",
    ),
    "4-1": (
        11829240794,
        "25345aafd52af90035fca11dfa6f6e6b93340e47dac127362bf54aa8998fbf11",
    ),
    "5-0": (
        11829879932,
        "5fb4fb42d984f340ebb285d9795ea3dac02d427e9d52c03851214eaa03702441",
    ),
    "5-1": (
        11828771883,
        "3961cd0fd9a50180cd915a016210e612fc0ca583c1ad2ad3fe4d3691276c7998",
    ),
    "6-1": (
        11829716282,
        "824d15c5405e5dca004aea55b71cab8a597b9c8afe1461f72890b605c0ef6aff",
    ),
    "7-0": (
        11831118634,
        "101486f19014f3ee428f3acb360289d78d7a65ee42c84017916efff9d5b9d2d3",
    ),
    "7-1": (
        11829925940,
        "c9bbaca2423694ed18f1f47e7282538a2cc92f4bb80a44c603f76daf6aa97bb7",
    ),
}


def hash_bytes(b):
    return hashlib.sha256(b).hexdigest()


def digest(data):
    return hash_bytes(
        json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    )


def strict_json(payload):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicated JSON key " + k)
            out[k] = v
        return out

    def bad(s):
        raise ValueError("nonfinite JSON " + s)

    return json.loads(payload, object_pairs_hook=unique, parse_constant=bad)


def openzip(path):
    if not path.is_file() or path.is_symlink():
        raise ValueError("regular ZIP required " + str(path))
    sha = hash_bytes(path.read_bytes())
    with zipfile.ZipFile(path) as z:
        names = set()
        files = {}
        for item in z.infolist():
            name = item.filename
            if (
                item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16)
                or name.startswith("/")
                or ".." in Path(name).parts
                or "\\" in name
                or name in names
            ):
                raise ValueError("unsafe ZIP entry " + name)
            names.add(name)
            if item.file_size > 4_000_000:
                raise ValueError("entry size bound " + name)
            files[name] = z.read(name)
    return sha, files


def verify_pins(files):
    pins = strict_json(files["sha-pins.json"])
    if set(pins) != set(files) - {"sha-pins.json"}:
        raise ValueError("shard manifest census mismatch")
    for name, sha in pins.items():
        if not SHA.fullmatch(sha) or hash_bytes(files[name]) != sha:
            raise ValueError("modified shard member " + name)
    return pins


def verify_sum(files):
    lines = files["SHA256SUMS"].decode().splitlines()
    seen = set()
    for line in lines:
        m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if not m:
            raise ValueError("invalid source SHA256SUMS")
        sha, name = m.groups()
        if name in seen or name not in files or sha != hash_bytes(files[name]):
            raise ValueError("invalid source member " + name)
        seen.add(name)
    if seen != set(files) - {"SHA256SUMS"}:
        raise ValueError("incomplete source SHA256SUMS")


def audit(root):
    origsha, orig = openzip(root / "event-inputs-20261010.zip")
    if origsha != ORIG_ZIP_SHA:
        raise ValueError("original source ZIP mismatch")
    verify_sum(orig)
    psha, pfiles = openzip(root / "rag-sharded-prep-20261013.zip")
    verify_sum(pfiles)
    if psha != PREP_ZIP_SHA:
        raise ValueError("externally pinned calibration-only preparation ZIP differs")
    if pfiles["tested-commit.txt"].decode().strip() != SOURCE:
        raise ValueError("prep source commit changed")
    plan = strict_json(pfiles["prep/calibration-plan.json"])
    if (
        plan["source_commit"] != SOURCE
        or plan["historical_plan_sha256"] != HISTORIC_PLAN_SHA
        or plan["calibration_only"] is not True
        or plan["test_cases_materialized"] is not False
        or len(plan["cases"]) != 8
    ):
        raise ValueError("wrong frozen calibration population")
    if (
        hash_bytes(pfiles["prep/calibration-sources.json"])
        != plan["calibration_sources_sha256"]
    ):
        raise ValueError("calibration source bytes changed")
    originals = {
        x["identity"]: x for x in strict_json(pfiles["prep/calibration-sources.json"])
    }
    if len(originals) != 54 or len(plan["cases"]) != 8:
        raise ValueError("calibration input size drift")
    expected_missing = []
    artifacts = []
    keys = set()
    total_inputs = total_outputs = 0
    read_seconds = 0.0
    tested = 0
    types = Counter()
    arm_counts = Counter()
    successes = Counter()
    for case, part in ALL:
        file = root / f"rag-cal-{case}-{part}-20261013.zip"
        if not file.is_file():
            expected_missing.append([case, part])
            continue
        outer, files = openzip(file)
        shard_key = f"{case}-{part}"
        if shard_key not in PINNED_SHARDS or outer != PINNED_SHARDS[shard_key][1]:
            raise ValueError("original Actions artifact ZIP pin mismatch " + shard_key)
        if set(files) != {
            "inventory.json",
            "raw-answers.jsonl",
            "publisher.json",
            "run.json",
            "runtime-preflight.json",
            "sha-pins.json",
            "stage.json",
        }:
            raise ValueError("unexpected shard ZIP census")
        verify_pins(files)
        run = strict_json(files["run.json"])
        query = plan["cases"][case]["query"]
        candidates = plan["cases"][case]["candidate_ids"]
        if (
            run["schema"] != "hepta.memory-strong-rag.shards.v1"
            or run["phase"] != "calibration"
            or run["source_commit"] != SOURCE
            or run["case_index"] != case
            or run["part"] != part
            or run["case_id"] != query["identity"]
            or run["arms"] != list(ARM_PART[part])
            or run["model_stage_sha256"] != STAGE_SHA
            or run["reader_identity"] != MODEL_ID
            or run["calibration_plan_sha256"]
            != hash_bytes(pfiles["prep/calibration-plan.json"])
            or run["model_weight_training"] is not False
            or run["allowed_to_train"] is not False
            or run["production_accepted"] is not False
        ):
            raise ValueError("shard source/model/arm or training drift")
        if hash_bytes(files["raw-answers.jsonl"]) != run["raw_answers_sha256"]:
            raise ValueError("raw answer lineage mismatch")
        if hash_bytes(files["stage.json"]) != STAGE_SHA:
            raise ValueError("model stage byte mismatch")
        data = files["raw-answers.jsonl"]
        lines = data.splitlines()
        if (
            not data.endswith(b"\n")
            or len(lines) != len(ARM_PART[part])
            or run["generated"] != len(lines)
        ):
            raise ValueError("incomplete output census")
        for raw in lines:
            row = strict_json(raw)
            arm = row["arm"]
            k = int(arm[1:])
            sel = candidates[:k]
            if (
                row["question_id"] != query["identity"]
                or row["kind"] != plan["cases"][case]["kind"]
                or arm not in ARM_PART[part]
                or row["selected"] != sel
                or row["candidate_digest"] != digest(candidates)
                or row["status"] not in ("succeeded", "failed")
            ):
                raise ValueError("row source/selection/arm drift")
            key = (row["question_id"], arm)
            if key in keys:
                raise ValueError("duplicated raw model call")
            keys.add(key)
            if row["status"] != "succeeded":
                raise ValueError(
                    "preserve failed raw outcome and reject complete generation"
                )
            receipt = row["receipt"]
            request = row["citation_audit"]["request"]
            if (
                receipt["reader_identity"] != MODEL_ID
                or receipt["token_limit"] != 2048
                or receipt["trainable_parameters"] != 0
                or receipt["answer_postprocessed"] is not False
                or receipt["production_accepted"] is not False
                or request["answer"] != row["answer"]
                or request["query_id"] != query["identity"]
                or request["question"] != query["content"]
                or request["prompt_digest"] != receipt["input_ids_digest"]
            ):
                raise ValueError("reader/prompt/citation identity drift")
            if len(receipt["delivered_evidence"]) != len(sel):
                raise ValueError("changed delivered evidence census")
            for ix, (sourceid, evidence) in enumerate(
                zip(sel, receipt["delivered_evidence"]), 1
            ):
                original = originals[sourceid]
                if (
                    evidence["original_id"] != sourceid
                    or evidence["label"] != "E" + str(ix)
                    or evidence["root"] != original["root"]
                    or evidence["excerpt"] != original["content"]
                    or evidence["source_digest"] != digest(original["content"])
                    or evidence["scope"] != original["scope"]
                ):
                    raise ValueError("source excerpt/citation changed")
            if not (
                type(receipt["input_tokens"]) is int
                and receipt["input_tokens"] > 0
                and type(receipt["generated_tokens"]) is int
                and receipt["generated_tokens"] > 0
                and math.isfinite(receipt["seconds"])
                and receipt["seconds"] >= 0
            ):
                raise ValueError("invalid measured tokens/time")
            total_inputs += receipt["input_tokens"]
            total_outputs += receipt["generated_tokens"]
            read_seconds += receipt["seconds"]
            tested += 1
            arm_counts[arm] += 1
            successes[row["kind"]] += 1
        artifacts.append(
            {
                "case": case,
                "part": part,
                "github_artifact_id": PINNED_SHARDS[shard_key][0],
                "zip_sha256": outer,
                "rows": len(lines),
                "source_commit": SOURCE,
                "model_id": MODEL_ID,
                "original_answers_sha256": hash_bytes(data),
            }
        )
    expected_keys = {
        (plan["cases"][i]["query"]["identity"], f"k{k}")
        for i in range(8)
        for k in (1, 2, 3, 4, 6)
    }
    missing_keys = sorted(expected_keys - keys)
    if tested + len(missing_keys) != 40:
        raise ValueError("unexpected calibration partition")
    if len(artifacts) != 15 or expected_missing != [[6, 0]]:
        raise ValueError(
            "this receipt is pinned to exactly 15 original approved shards"
        )
    return {
        "schema": "hepta.memory-cell.independent-disjoint-partial-review.v1",
        "run_id": 38423223376,
        "source_commit": SOURCE,
        "original_zip_sha256": origsha,
        "prep_zip_sha256": psha,
        "calibration_plan_sha256": hash_bytes(pfiles["prep/calibration-plan.json"]),
        "qwen_model_identity": MODEL_ID,
        "stage_sha256": STAGE_SHA,
        "verified_artifacts": len(artifacts),
        "verified_raw_new_model_calls": tested,
        "expected_calibration_calls": 40,
        "missing_cases_parts": expected_missing,
        "missing_raw_question_arm_pairs": missing_keys,
        "observed_arm_census": dict(sorted(arm_counts.items())),
        "observed_kind_census": dict(sorted(successes.items())),
        "observed_input_tokens": total_inputs,
        "observed_output_tokens": total_outputs,
        "sum_reader_seconds_not_parallel_wall_seconds": round(read_seconds, 3),
        "all_collected_rows_are_original_successful_model_calls": True,
        "calibration_frozen": not missing_keys,
        "evaluation_attempts": 0,
        "full_40_plus_72_experiment_completed": False,
        "reviewer_independent_semantic_judge": False,
        "statistical_superiority_established": False,
        "human_source_sufficiency_qualified": False,
        "parametric_memory_training_qualified": False,
        "production_accepted": False,
        "artifacts": sorted(artifacts, key=lambda x: (x["case"], x["part"])),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    j = audit(a.directory)
    a.output.write_text(
        json.dumps(j, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )
    print(json.dumps({k: v for k, v in j.items() if k != "artifacts"}, indent=2))
