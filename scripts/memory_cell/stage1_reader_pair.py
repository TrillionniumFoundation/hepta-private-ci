"""Read-only paired audit of original real Reader outputs, including unavailable cases.

This verifier never runs inference, repairs answers, selects a model or authorizes
memory training. Model staging and independent semantic judgement are separate.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from reader_reference import MODELS, PINS

TIERS = ("smol-135m", "smol-1.7b")
ALLOWED_SCORING = frozenset({"f1", "exact_match", "target_unanswerable"})
MAX_FILE = 64 * 1024 * 1024


def insist(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(raw):
    """Reject ambiguous JSON everywhere, including per-answer journal lines."""

    def distinct(pairs):
        result = {}
        for key, value in pairs:
            insist(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("nonfinite JSON value " + value)

    return json.loads(raw, object_pairs_hook=distinct, parse_constant=nonfinite)


def read_json(path):
    path = Path(path)
    insist(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FILE,
        "bounded original JSON file required",
    )
    return strict_json(path.read_bytes())


def verify_inventory(root):
    root = Path(root)
    insist(root.is_dir() and not root.is_symlink(), "missing original artifact")
    sha_file = root / "SHA256SUMS"
    insist(
        sha_file.is_file() and not sha_file.is_symlink(),
        "missing artifact hash inventory",
    )
    declared = {}
    for line in sha_file.read_text().splitlines():
        entry = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        insist(entry is not None, "invalid SHA256SUMS line")
        hashed, name = entry.groups()
        parts = Path(name).parts
        insist(
            name not in declared
            and parts
            and not any(part in (".", "..", "") for part in parts)
            and not Path(name).is_absolute(),
            "duplicated or unsafe artifact path",
        )
        declared[name] = hashed
    all_files = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() or item.is_symlink()
    }
    insist(
        all_files - {"SHA256SUMS"} == set(declared),
        "missing/extra original artifact bytes",
    )
    for name, hashed in declared.items():
        file = root / name
        insist(
            file.is_file()
            and not file.is_symlink()
            and file.resolve().is_relative_to(root.resolve())
            and file.stat().st_size <= MAX_FILE,
            "unsafe original artifact file",
        )
        insist(digest(file.read_bytes()) == hashed, "original artifact hash mismatch")
    return declared


def verify_frozen_shard_attempts(plan, conditions, identity, original_rows, scored):
    """Reject reordered, rewritten, or false-success original Reader attempts.

    This is a pre-label structural gate. Independent semantic judgment and real
    model attestation remain unavailable, even when every original byte agrees.
    """
    insist(
        isinstance(plan, dict)
        and isinstance(plan.get("cases"), list)
        and len(plan["cases"]) == 2
        and isinstance(conditions, list)
        and len(conditions) == 4
        and len(set(conditions)) == 4,
        "bounded preregistered shard required",
    )
    insist(
        isinstance(original_rows, list)
        and isinstance(scored, list)
        and len(original_rows) == len(scored) == 8,
        "incomplete original shard population",
    )
    expected = [
        (case["question"]["identity"], arm)
        for case in plan["cases"]
        for arm in conditions
    ]
    insist(len(set(expected)) == len(expected), "repeated question/condition slot")
    for index, (original, row) in enumerate(zip(original_rows, scored, strict=True)):
        insist(
            isinstance(original, dict)
            and isinstance(row, dict)
            and (row.get("question_id"), row.get("arm")) == expected[index]
            and (original.get("question_id"), original.get("arm")) == expected[index]
            and {key: value for key, value in row.items() if key not in ALLOWED_SCORING}
            == original,
            "raw/scored answer or frozen slot order changed",
        )
        case = plan["cases"][index // len(conditions)]
        condition = case["conditions"][expected[index][1]]
        insist(
            row.get("family") == case["family"]
            and row.get("phase") == case["phase"]
            and row.get("status") in ("succeeded", "failed", "unavailable"),
            "task family, phase or original status drift",
        )
        if condition.get("status") == "unavailable":
            insist(row["status"] == "unavailable", "unavailable oracle fabricated")
        if row["status"] == "succeeded":
            receipt = row.get("receipt")
            insist(isinstance(receipt, dict), "successful call without receipt")
            answer = row.get("answer")
            insist(
                isinstance(answer, str)
                and bool(answer.strip())
                and type(row.get("f1")) in (int, float)
                and math.isfinite(row["f1"])
                and 0 <= row["f1"] <= 1
                and row.get("exact_match") in (0, 0.0, 1, 1.0),
                "successful call with missing original answer or score",
            )
            insist(
                receipt.get("reader_identity") == identity["model_digest"]
                and receipt.get("trainable_parameters") == 0
                and receipt.get("answer_postprocessed") is False
                and receipt.get("delivered_evidence")
                == condition["delivered_evidence"],
                "reader weights, output or actual delivered source mismatch",
            )
            insist(
                type(receipt.get("input_tokens")) is int
                and 0 < receipt["input_tokens"] <= condition["token_limit"]
                and type(receipt.get("generated_tokens")) is int
                and 0 < receipt["generated_tokens"] <= 64
                and type(receipt.get("seconds")) in (int, float)
                and math.isfinite(receipt["seconds"])
                and 0 < receipt["seconds"] < 86400,
                "unbounded, negative or nonfinite Reader resource receipt",
            )
            for name in ("input_ids_digest", "generated_ids_digest"):
                value = receipt.get(name)
                insist(
                    isinstance(value, str)
                    and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
                    "missing original model prompt/output token digest",
                )
        else:
            insist(
                "answer" not in row
                and "receipt" not in row
                and row.get("f1") is None
                and row.get("exact_match") is None,
                "failed or unavailable generation supplied a fabricated answer",
            )
    return {
        "planned": len(expected),
        "succeeded": sum(row["status"] == "succeeded" for row in scored),
        "failed": sum(row["status"] == "failed" for row in scored),
        "unavailable": sum(row["status"] == "unavailable" for row in scored),
        "semantic_sufficiency_certified": False,
        "production_accepted": False,
    }


def records_from_run(root, *, tier, expected_source):
    inventory = verify_inventory(root)
    insist(
        (root / "tested-commit.txt").read_text().strip() == expected_source,
        "source head drift",
    )
    stage = read_json(root / "stage.json")
    model = read_json(root / "inventory.json")
    registration = read_json(root / "run/preregistered.json")
    execution = read_json(root / "run/diagnostic/execution/execution.json")
    plan = read_json(root / "run/diagnostic/reviewed-plan.json")
    reference_report = read_json(root / "run/reference-report.json")
    insist(
        (stage["repository"], stage["revision"]) == MODELS[tier]
        and stage["tier"] == tier
        and (model["repository"], model["revision"], model["tier"])
        == (MODELS[tier][0], MODELS[tier][1], tier),
        "different model revision or tier",
    )
    insist(
        stage["inventory_sha256"] == digest((root / "inventory.json").read_bytes())
        and stage["publisher_sha256"] == digest((root / "publisher.json").read_bytes()),
        "model publisher/staging pin drift",
    )
    insist(
        registration["source_commit"] == expected_source
        and registration["tier"] == tier
        and registration["stage_sha256"] == digest((root / "stage.json").read_bytes())
        and registration["input_pins"]
        == PINS | {"inventory": stage["inventory_sha256"]}
        and registration["optimization_permitted"] is False
        and registration["production_accepted"] is False
        and execution["tested_commit"] == expected_source
        and execution["labels_sha256"] == PINS["labels"]
        and execution["reader_identity"] == model["inventory_digest"],
        "model run or original inputs not properly frozen",
    )
    insist(
        reference_report["source_commit"] == expected_source
        and reference_report["tier"] == tier
        and reference_report["production_accepted"] is False,
        "incorrect original reference report",
    )
    raw = root / "run/diagnostic/execution/raw-answers.jsonl"
    raw_bytes = raw.read_bytes()
    insist(
        raw_bytes.endswith(b"\n") and len(raw_bytes) <= MAX_FILE,
        "truncated original answer journal",
    )
    entries = [strict_json(line) for line in raw_bytes.splitlines()]
    scored = read_json(root / "run/diagnostic/execution/scored-answers.json")
    insist(
        isinstance(scored, list) and len(scored) == len(entries),
        "missing scored attempts",
    )
    by_key = {}
    for original, row in zip(entries, scored, strict=True):
        key = (row["question_id"], row["arm"])
        insist(
            key not in by_key
            and row["status"] in ("succeeded", "failed", "unavailable")
            and {k: v for k, v in row.items() if k not in ALLOWED_SCORING} == original,
            "duplicate, changed, or missing original generated answer",
        )
        if row["status"] == "succeeded":
            insist(
                isinstance(row.get("answer"), str)
                and row["answer"]
                and row["receipt"]["reader_identity"] == model["inventory_digest"]
                and row["receipt"]["reader_profile"]
                and type(row.get("f1")) in (int, float)
                and math.isfinite(row["f1"])
                and 0 <= row["f1"] <= 1,
                "missing actual inference/profile/score",
            )
        else:
            insist(row.get("f1") is None, "unexecuted answer scored as successful")
        by_key[key] = row
    expected = {
        (case["question"]["identity"], arm)
        for case in plan["cases"]
        for arm in case["conditions"]
    }
    insist(
        len(plan["cases"]) == 8 and set(by_key) == expected,
        "incomplete frozen eight-question condition matrix",
    )
    return (
        by_key,
        {
            "revision": stage["revision"],
            "inventory_digest": model["inventory_digest"],
            "stage_file_bytes": stage["model_file_bytes"],
            "stage_seconds": stage["seconds"],
            "planned": len(entries),
            "successful": sum(r["status"] == "succeeded" for r in scored),
            "unavailable": sum(r["status"] == "unavailable" for r in scored),
            "failed": sum(r["status"] == "failed" for r in scored),
            "original_answer_journal_sha256": digest(raw_bytes),
            "manifest_files_verified": len(inventory),
        },
        plan,
    )


def pair(root, source):
    insist(
        re.fullmatch(r"[0-9a-f]{40}", source) is not None,
        "exact generating head required",
    )
    data, meta, plan_identity = {}, {}, None
    for tier in TIERS:
        rows, info, plan = records_from_run(
            Path(root) / ("memory-stage1-real-" + tier),
            tier=tier,
            expected_source=source,
        )
        data[tier], meta[tier] = rows, info
        # The two model tokenizers can encode the same complete source differently,
        # but must receive the same registered case/control identity and source.
        plan_identity_current = [
            (case["question"]["identity"], case["family"], case["phase"])
            for case in plan["cases"]
        ]
        if plan_identity is not None:
            insist(
                plan_identity == plan_identity_current, "question/source-family drift"
            )
        plan_identity = plan_identity_current
    left, right = (data[tier] for tier in TIERS)
    insist(set(left) == set(right), "incomplete or different paired population")
    insist(
        meta[TIERS[0]]["inventory_digest"] != meta[TIERS[1]]["inventory_digest"],
        "reader revision reused",
    )
    comparisons = []
    known_delta = 0.0
    paired = 0
    unavailable = 0
    for key in sorted(left):
        a, b = left[key], right[key]
        insist(
            (a["question_id"], a["arm"], a["family"], a["phase"])
            == (b["question_id"], b["arm"], b["family"], b["phase"]),
            "changed question family/phase/arm",
        )
        comparison = dict(
            question_id=key[0],
            arm=key[1],
            first_status=a["status"],
            second_status=b["status"],
            frozen_f1=a.get("f1"),
            reference_f1=b.get("f1"),
            delta=None,
            delivered_source_equal=None,
        )
        if a["status"] == b["status"] == "succeeded":
            aa, bb = a["receipt"], b["receipt"]
            insist(
                aa["delivered_evidence"] == bb["delivered_evidence"],
                "reader changed originally delivered evidence",
            )
            comparison["delivered_source_equal"] = True
            comparison["evidence_sha256"] = digest(
                json.dumps(
                    aa["delivered_evidence"], ensure_ascii=False, sort_keys=True
                ).encode()
            )
            comparison["frozen_answer_sha256"] = digest(a["answer"].encode())
            comparison["reference_answer_sha256"] = digest(b["answer"].encode())
            comparison["delta"] = b["f1"] - a["f1"]
            known_delta += comparison["delta"]
            paired += 1
        else:
            unavailable += 1
        comparisons.append(comparison)
    insist(paired > 0, "no jointly executed original reader calls")
    population = len(comparisons)
    return dict(
        schema="hepta.memory.stage1.paired-original-readers.v2",
        tested_commit=source,
        models=meta,
        planned=population,
        matched_succeeded=paired,
        unpaired_or_unavailable=unavailable,
        complete_compatible_execution=unavailable == 0,
        matched_only_mean_f1_delta=known_delta / paired,
        planned_population_delta_lower_bound=(known_delta - unavailable) / population,
        planned_population_delta_upper_bound=(known_delta + unavailable) / population,
        bounds_are_not_statistical_confidence_intervals=True,
        independence_certified=False,
        semantic_sufficiency_certified=False,
        reader_capacity_is_memory_gain=False,
        production_accepted=False,
        rows=comparisons,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = pair(args.root, args.source)
    insist(not args.output.exists(), "refuse to overwrite original paired report")
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    main()
