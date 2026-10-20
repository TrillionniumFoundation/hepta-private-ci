"""Read-only audit of real, complete 135M four-condition development shards.

No model execution, semantic sufficiency certificate, training, or production use.
Unknown external reviews remain in the full planned denominator.
"""

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re

from reader_reference import MODELS, PINS
from stage1_reader_pair import (
    strict_json,
    verify_frozen_shard_attempts,
    verify_inventory,
)
from stage1_reader_score import answer_scores

SOURCE = "e32546207ecca603c6f93c9a20388a83d440cc49"
ARMS = ("empty", "retrieved1", "reviewed_minimal", "reviewed_without_premise1")


def demand(ok, message):
    if not ok:
        raise ValueError(message)


def read_bytes(path):
    path = Path(path)
    demand(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 64 << 20,
        "missing, linked or oversized experiment file",
    )
    return path.read_bytes()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    return strict_json(read_bytes(path))


def audit(directory, labels_file, *, source=SOURCE):
    root = Path(directory)
    freeze = root / "freeze"
    frozen_files = verify_inventory(freeze)
    registration = load(freeze / "registration.json")
    full = load(freeze / "full.json")
    labels_bytes = read_bytes(labels_file)
    demand(
        source == SOURCE
        and registration.get("source") == source
        and registration.get("original_pins") == PINS
        and registration.get("conditions") == list(ARMS)
        and registration.get("tiers", {}).get("smol-135m") == list(MODELS["smol-135m"])
        and registration.get("training") == 0
        and registration.get("production_accepted") is False
        and len(registration.get("slices", [])) == 4
        and len(full.get("cases", [])) == 8
        and registration["original_projected_sha256"]
        == sha(read_bytes(freeze / "full.json"))
        and sha(labels_bytes) == PINS["labels"],
        "original pinned source, label or registered plan changed",
    )
    labels = strict_json(labels_bytes)
    ids = [case["question"]["identity"] for case in full["cases"]]
    demand(
        len(set(ids)) == len(ids) == 8 and set(labels) == set(ids),
        "question, root or answer population drift",
    )
    profile = set()
    scores = {}
    by_arm = defaultdict(list)
    resource = defaultdict(
        lambda: dict(seconds=0.0, input_tokens=0, generated_tokens=0)
    )
    shard_receipts = []
    for i in range(4):
        folder = root / f"shard-{i}"
        original_manifest = verify_inventory(folder)
        spec = registration["slices"][i]
        frozen_bytes = read_bytes(freeze / f"shard-{i}.json")
        plan_bytes = read_bytes(folder / "plan.json")
        plan = strict_json(plan_bytes)
        owner = load(folder / "identity.json")
        execution = load(folder / "execution/execution.json")
        journal_bytes = read_bytes(folder / "execution/raw-answers.jsonl")
        demand(journal_bytes.endswith(b"\n"), "interrupted original JSONL journal")
        raw = [strict_json(line) for line in journal_bytes.splitlines()]
        scored = load(folder / "execution/scored-answers.json")
        demand(
            spec["shard"] == i
            and spec["sha256"] == sha(frozen_bytes)
            and frozen_bytes == plan_bytes
            and len(plan["cases"]) == 2
            and [c["question"]["identity"] for c in plan["cases"]]
            == spec["ids"]
            == ids[2 * i : 2 * i + 2]
            and owner["head"] == source
            and owner["tier"] == "smol-135m"
            and owner["shard"] == i
            and owner["revision"] == MODELS["smol-135m"][1]
            and owner["training"] == 0
            and owner["production_accepted"] is False
            and owner["registration_sha256"]
            == sha(read_bytes(freeze / "registration.json"))
            and owner["original_plan_sha256"] == sha(plan_bytes)
            and execution["tested_commit"] == source
            and execution["reader_training"] is False
            and execution["labels_sha256"] == PINS["labels"]
            and execution["reader_identity"] == owner["model_digest"]
            and execution["plan_sha256"] == sha(plan_bytes)
            and read_bytes(folder / "tested-head.txt").decode().strip() == source,
            "original worker/model/plan/labels identity changed",
        )
        receipt = verify_frozen_shard_attempts(plan, list(ARMS), owner, raw, scored)
        profile.add(owner["model_digest"])
        for j, row in enumerate(scored):
            case = plan["cases"][j // 4]
            arm = ARMS[j % 4]
            qid = case["question"]["identity"]
            demand((qid, arm) not in scores, "duplicate question/condition")
            if row["status"] == "succeeded":
                target = labels[qid]
                reference = answer_scores(
                    row["answer"],
                    ((target["answer"],) if target["answer"] is not None else None),
                    target["unanswerable"],
                )
                demand(
                    row["f1"] == reference["f1"]
                    and row["exact_match"] == reference["exact_match"],
                    "original answer was edited or posthoc mis-scored",
                )
                original_cost = row["receipt"]
                profile.add(original_cost["reader_identity"])
                resource[arm]["seconds"] += original_cost["seconds"]
                resource[arm]["input_tokens"] += original_cost["input_tokens"]
                resource[arm]["generated_tokens"] += original_cost["generated_tokens"]
            by_arm[arm].append(row)
            scores[(qid, arm)] = row
        shard_receipts.append(
            {
                "shard": i,
                "attempts": receipt,
                "original_journal_sha256": sha(journal_bytes),
                "verified_artifact_files": len(original_manifest),
            }
        )
    demand(len(profile) == 1 and len(scores) == 32, "mixed model or incomplete census")
    arms = {}
    for arm in ARMS:
        items = by_arm[arm]
        successful = [row for row in items if row["status"] == "succeeded"]
        unknown = 8 - len(successful)
        value = sum(row["f1"] for row in successful)
        arms[arm] = {
            "planned": 8,
            "succeeded": len(successful),
            "unavailable": sum(row["status"] == "unavailable" for row in items),
            "failed": sum(row["status"] == "failed" for row in items),
            "all_planned_diagnostic_f1_bounds": [value / 8, (value + unknown) / 8],
            "conditional_diagnostic_f1": (
                value / len(successful) if successful else None
            ),
            "literal_citations": sum(
                len(re.findall(r"\[E[1-9][0-9]*\]", row["answer"]))
                for row in successful
            ),
            "measured_inference": resource[arm],
        }
    paired = {}
    for left, right in (
        ("empty", "retrieved1"),
        ("retrieved1", "reviewed_minimal"),
        ("reviewed_minimal", "reviewed_without_premise1"),
    ):
        all_pairs = [(scores[(qid, left)], scores[(qid, right)]) for qid in ids]
        observed = [
            (a, b) for a, b in all_pairs if a["status"] == b["status"] == "succeeded"
        ]
        delta = [b["f1"] - a["f1"] for a, b in observed]
        unknown = len(all_pairs) - len(observed)
        paired[f"{right}_minus_{left}"] = {
            "planned": 8,
            "compared": len(observed),
            "unknown": unknown,
            "wins": sum(v > 1e-12 for v in delta),
            "losses": sum(v < -1e-12 for v in delta),
            "ties": sum(abs(v) <= 1e-12 for v in delta),
            "observed_diagnostic_delta": (sum(delta) / len(delta) if delta else None),
            "planned_delta_bounds": [
                (sum(delta) - unknown) / 8,
                (sum(delta) + unknown) / 8,
            ],
            "bounds_are_not_statistical_intervals": True,
        }
    return {
        "schema": "hepta.memory.stage1.sharded135m.readonly.v1",
        "original_generating_source": source,
        "original_workflow_run": 39022071419,
        "original_plan_sha256": registration["original_projected_sha256"],
        "model_revision": MODELS["smol-135m"][1],
        "model_digests": sorted(profile),
        "planned_attempts": 32,
        "successful_model_calls": sum(x["succeeded"] for x in arms.values()),
        "missing_or_unavailable": sum(
            x["unavailable"] + x["failed"] for x in arms.values()
        ),
        "declared_source_families": len({case["family"] for case in full["cases"]}),
        "independent_source_families_authenticated": False,
        "arms": arms,
        "paired_evidence_diagnostics": paired,
        "original_shards": shard_receipts,
        "verified_frozen_files": len(frozen_files),
        "independent_semantic_sufficiency_certified": False,
        "citation_entailment_precision": None,
        "training_during_queries": False,
        "additional_reader_capacity_test_complete": False,
        "economic_lifecycle_cost_complete": False,
        "production_accepted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--source", default=SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.root, args.labels, source=args.source)
    demand(not args.output.exists(), "refuse to rewrite original audit")
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    main()
