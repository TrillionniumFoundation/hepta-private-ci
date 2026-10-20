"""Five immutable real-model ZIPs -> four-stage fail-closed research decision.

No model inference, training, approval signatures or deployment. Reuses the
existing original-answer validator and independent 40+72 RAG archive validator.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from historical_reader_failure_modes import (
    ARMS,
    GENERATING_SOURCE,
    MODELS,
    PLAN_SHA,
    SOURCE_SHA,
    diagnose,
    sealed_zip,
)
from reader_admission_gate import audit as audit_strong_rag

STRICT = re.compile(r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*")


def ensure(test, reason):
    if not test:
        raise ValueError(reason)


def pairs(groups, left, right):
    wins = sum(v[right] and not v[left] for v in groups.values())
    losses = sum(v[left] and not v[right] for v in groups.values())
    return dict(
        wins=wins,
        losses=losses,
        ties=len(groups) - wins - losses,
        delta=(wins - losses) / len(groups),
    )


def analyze(source_zip, smol_zip, qwen_zip, strong_zip, replay_zip):
    failure = diagnose(source_zip, qwen_zip, smol_zip)
    rag = audit_strong_rag(source_zip, strong_zip, replay_zip)
    src = sealed_zip(source_zip, SOURCE_SHA)
    ensure(
        hashlib.sha256(src["plan/plan.json"]).hexdigest() == PLAN_SHA,
        "source plan changed",
    )
    labels = {
        r["id"]: r
        for r in json.loads(src["observations/labels.json"])
        if r["phase"] == "test"
    }
    ensure(len(labels) == 8, "development question population changed")
    docs = {r["identity"]: r for r in json.loads(src["plan/source-view.json"])}
    ensure(len(docs) == 108, "original experience corpus changed")
    outputs, models = {}, {}
    reexecuted = 0
    with tempfile.TemporaryDirectory() as temporary:
        worker = Path(temporary) / "event_probe.py"
        worker.write_bytes(src["source/event_probe.py"])
        for name, path in (("smol-1.7b", smol_zip), ("qwen-3b", qwen_zip)):
            zipped = sealed_zip(path, MODELS[name])
            ensure(
                zipped["tested-commit.txt"].decode().strip() == GENERATING_SOURCE,
                "real Reader generation SHA changed",
            )
            inv = json.loads(zipped["inventory.json"])
            ensure(inv["tier"] == name, "Reader tier drift")
            records = json.loads(zipped["run/scored-answers.json"])
            ensure(len(records) == 48, "incomplete model census")
            matched = {}
            by_case = defaultdict(dict)
            cost = {
                a: dict(
                    success=0,
                    planned=8,
                    input_tokens=0,
                    output_tokens=0,
                    measured_seconds=0.0,
                )
                for a in ARMS
            }
            for row in records:
                key = (row["question_id"], row["arm"])
                ensure(
                    key not in matched
                    and key[0] in labels
                    and key[1] in ARMS
                    and row["status"] == "succeeded",
                    "invalid real answer row",
                )
                receipt = row["receipt"]
                ensure(
                    receipt["reader_identity"] == inv["inventory_digest"]
                    and receipt["trainable_parameters"] == 0
                    and receipt["answer_postprocessed"] is False
                    and receipt["token_limit"] == 2048,
                    "Reader weights or token ceiling differ",
                )
                second = receipt["seconds"]
                ensure(
                    type(second) in (int, float)
                    and math.isfinite(second)
                    and second >= 0
                    and type(receipt["input_tokens"]) is int
                    and 0 <= receipt["input_tokens"] <= 2048
                    and type(receipt["generated_tokens"]) is int
                    and 0 <= receipt["generated_tokens"] <= 64,
                    "unmeasured or unbounded model inference cost",
                )
                delivered = receipt["delivered_evidence"]
                ensure(
                    [v["original_id"] for v in delivered] == row["selected"],
                    "source selection changed",
                )
                for item in delivered:
                    original = docs[item["original_id"]]
                    ensure(
                        item["excerpt"] == original["content"]
                        and item["root"] == original["root"]
                        and item["scope"] == original["scope"],
                        "delivered evidence not original",
                    )
                parsed = STRICT.fullmatch(row["answer"])
                identifier = parsed.group(1) if parsed else None
                ensure(
                    identifier == row["parsed_identifier"],
                    "original model answer repaired",
                )
                success = identifier == labels[key[0]]["expected"]
                if row["kind"] == "procedure":
                    request = dict(
                        operation="execute",
                        recipe=labels[key[0]]["procedure"],
                        supplied=identifier or "invalid_response",
                    )
                    result = subprocess.run(
                        [sys.executable, "-I", "-S", str(worker)],
                        input=json.dumps(request, sort_keys=True),
                        text=True,
                        capture_output=True,
                        timeout=10,
                        check=False,
                    )
                    receipt_program = row["procedure_verification"]
                    ensure(
                        receipt_program["request"] == request
                        and receipt_program["exit_code"] == result.returncode
                        and receipt_program["stdout"] == result.stdout
                        and receipt_program["stderr"] == result.stderr,
                        "real program task execution cannot be replayed",
                    )
                    success = result.returncode == 0
                    reexecuted += 1
                ensure(
                    row["strict_task_success"] is success,
                    "scorer changed actual task result",
                )
                v = cost[key[1]]
                v["success"] += int(success)
                v["input_tokens"] += receipt["input_tokens"]
                v["output_tokens"] += receipt["generated_tokens"]
                v["measured_seconds"] += second
                matched[key] = row
                by_case[key[0]][key[1]] = success
            ensure(len(matched) == 48, "not a full 48-answer Reader run")
            models[name] = dict(
                arms=cost,
                frozen_model_file_bytes=sum(
                    x["bytes"] for x in inv["inventory"].values()
                ),
                matched_observed_effects=dict(
                    entity_time_vs_hybrid=pairs(by_case, "hybrid", "entity_time"),
                    organized_vs_entity_time=pairs(by_case, "entity_time", "organized"),
                ),
            )
            outputs[name] = matched
    for key, a in outputs["smol-1.7b"].items():
        b = outputs["qwen-3b"][key]
        ensure(
            a["selected"] == b["selected"]
            and a["candidate_digest"] == b["candidate_digest"]
            and a["receipt"]["query_digest"] == b["receipt"]["query_digest"]
            and a["receipt"]["bundle_digest"] == b["receipt"]["bundle_digest"]
            and a["receipt"]["token_limit"] == b["receipt"]["token_limit"]
            and a["receipt"]["delivered_evidence"]
            == b["receipt"]["delivered_evidence"],
            "Reader capacity comparison received unmatched evidence",
        )
    literal_still_visible = 0
    for qid, item in labels.items():
        remaining = outputs["qwen-3b"][qid, "without_prerequisite"]["receipt"][
            "delivered_evidence"
        ]
        original = " ".join(source["excerpt"] for source in remaining)
        literal_still_visible += bool(
            re.search(
                rf"(?<![A-Za-z0-9_-]){re.escape(item['expected'])}(?![A-Za-z0-9_-])",
                original,
            )
        )
    ensure(literal_still_visible == 4, "frozen lesion cohort changed")
    ensure(
        rag["complete_calibration"] == 40 and rag["complete_evaluation"] == 72,
        "real 40+72 census incomplete",
    )
    return dict(
        schema="hepta.memory.real-four-stage-source-verified.v1",
        actual_inference_records=48 + 48 + 40 + 72,
        original_reader_pairs=48,
        independent_program_worker_reexecutions=reexecuted,
        exact_zip_sha256=dict(
            source=SOURCE_SHA, **MODELS, strong_rag=rag["outer_artifact_sha256"]
        ),
        actual_model_costs=models,
        stage1=dict(
            model_capacity_not_memory_learning=True,
            smol_organized_success=models["smol-1.7b"]["arms"]["organized"]["success"],
            qwen_organized_success=models["qwen-3b"]["arms"]["organized"]["success"],
            human_verified_sufficiency=False,
            necessary_premise_proven=False,
            ablation_answer_visible=literal_still_visible,
            ablation_answer_removed=8 - literal_still_visible,
            independent_sources_certified=False,
        ),
        stage2=dict(
            qwen_hybrid_success=models["qwen-3b"]["arms"]["hybrid"]["success"],
            qwen_entity_time_success=models["qwen-3b"]["arms"]["entity_time"][
                "success"
            ],
            organized_extra_correct_over_entity_time=rag[
                "incremental_graph_task_success"
            ],
            organized_input_tokens_saved=rag["organized_input_tokens_saved"],
            independent_generalization_qualified=False,
        ),
        stage3=dict(
            matched_learned_policy_extra_gain=None,
            matched_knowledge_module_extra_gain=None,
            original_body_free_compression_fidelity=None,
            prospective_training_freeze_authenticated=False,
            parametric_candidate_accepted=False,
        ),
        stage4=dict(
            raw_evidence_bytes_retained=sum(
                len(v["content"].encode()) for v in docs.values()
            ),
            extraction_index_and_serving_costs_fully_paid=False,
            actual_prospective_calendar_windows=0,
            maintenance_revocation_recovery_usd=None,
            complete_lifecycle_cost_usd=None,
            production_qualified=False,
        ),
        original_failures_are_not_rewritten=failure["new_model_generations"] == 0,
        historical_rag_no_go=not rag["candidate_accepted"],
        primary_scores_are_not_semantic_judge_scores=True,
        independent_source_families_authenticated=0,
        new_model_calls=0,
        training_steps=0,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "smol", "qwen", "strong", "replay", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("refuse to overwrite original real audit")
    result = analyze(args.source, args.smol, args.qwen, args.strong, args.replay)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )


if __name__ == "__main__":
    main()
