"""Independent, fail-closed readout for matched frozen-Encoder Cell candidates.

This module *never* trains, loads, authenticates or chooses a model. Its inputs
are SHA256-pinned prediction/ground-truth artifacts, NOT trusted execution or
NDU witnesses. A useful geometric or classification score cannot promote a Cell.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from multimodal_alignment_contract import (
    canonical, load_pinned_document, load_pinned_jsonl, sha, write_new,
)
from multimodal_bridge import ContractError, _digest

PLAN = "hepta.stem-candidate-plan.v1"
RESULT = "hepta.stem-candidate-prediction.v1"
READOUT = "hepta.stem-candidate-independent-readout.v1"
MAX_CANDIDATES = 8
MAX_CASES = 2048


def _fields(value: object, expected: set[str], where: str) -> dict:
    if type(value) is not dict or set(value) != expected:
        raise ContractError(f"noncanonical {where} fields")
    return value


def _positive(value: object, maximum: int, name: str, minimum: int = 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError(f"invalid {name}")
    return value


def _name(value: object, what: str) -> str:
    if type(value) is not str or not 1 <= len(value) <= 96 or any(
        not (c.isascii() and (c.isalnum() or c in "-_.")) for c in value
    ):
        raise ContractError(f"invalid {what}")
    return value


def validate_plan(plan: dict) -> dict:
    _fields(plan, {
        "schema", "scope", "train_sha256", "future_source_sha256",
        "future_targets_sha256", "train_group_sha256s", "train_cutoff",
        "future_start", "future_end", "classes", "train_steps", "head_parameters",
        "seed", "hardware_sha256", "environment_sha256", "candidates",
    }, "plan")
    if plan["schema"] != PLAN:
        raise ContractError("unexpected plan schema")
    scope = _name(plan["scope"], "scope")
    for key in ("train_sha256", "future_source_sha256", "future_targets_sha256",
                "hardware_sha256", "environment_sha256"):
        _digest(plan[key])
    _positive(plan["train_cutoff"], 2**63 - 2, "train cutoff", minimum=0)
    _positive(plan["future_start"], 2**63 - 1, "future start")
    _positive(plan["future_end"], 2**63 - 1, "future end")
    if not plan["train_cutoff"] < plan["future_start"] <= plan["future_end"]:
        raise ContractError("unfrozen or overlapping future interval")
    _positive(plan["classes"], 32, "class count", minimum=2)
    _positive(plan["train_steps"], 10000, "head training steps")
    _positive(plan["head_parameters"], 262144, "matched head parameters")
    _positive(plan["seed"], 2**31 - 1, "random seed", minimum=0)
    groups = plan["train_group_sha256s"]
    if (type(groups) is not list or not 2 <= len(groups) <= MAX_CASES
            or groups != sorted(set(groups))):
        raise ContractError("train groups must be a sorted independent census")
    for digest in groups:
        _digest(digest)
    candidates = plan["candidates"]
    if type(candidates) is not list or not 2 <= len(candidates) <= MAX_CANDIDATES:
        raise ContractError("baseline plus bounded candidate inventory required")
    names = []
    for item in candidates:
        _fields(item, {"name", "profile_sha256", "snapshot_sha256"}, "candidate")
        names.append(_name(item["name"], "candidate name"))
        _digest(item["profile_sha256"])
        _digest(item["snapshot_sha256"])
    if names != sorted(set(names)) or names.count("no_change") != 1:
        raise ContractError("sorted unique candidates and frozen no_change required")
    return plan


def _case_sources(targets: list[dict], plan: dict) -> list[dict]:
    if not 16 <= len(targets) <= MAX_CASES:
        raise ContractError("insufficient or oversized future window")
    ids = []
    sources = []
    for row in targets:
        _fields(row, {"case_id", "group_id", "scope", "observed_at",
                      "input_sha256", "label"}, "future target")
        cid = _name(row["case_id"], "future case")
        _name(row["group_id"], "future group")
        if row["scope"] != plan["scope"]:
            raise ContractError("future scope drift")
        _digest(row["input_sha256"])
        _positive(row["observed_at"], plan["future_end"], "future observation")
        if row["observed_at"] < plan["future_start"]:
            raise ContractError("lookahead or stale future observation")
        _positive(row["label"], plan["classes"] - 1, "target label", minimum=0)
        if sha(row["group_id"].encode()) in plan["train_group_sha256s"]:
            raise ContractError("train/future group leakage")
        ids.append(cid)
        sources.append({k: row[k] for k in
                        ("case_id", "group_id", "scope", "observed_at", "input_sha256")})
    if ids != sorted(set(ids)):
        raise ContractError("future cases require unique canonical ordering")
    if sha(b"".join(canonical(x) for x in sources)) != plan["future_source_sha256"]:
        raise ContractError("future source cohort differs from the frozen plan")
    if sha(b"".join(canonical(x) for x in targets)) != plan["future_targets_sha256"]:
        raise ContractError("future labels do not match the frozen plan")
    return sources


def _probabilities(values: object, classes: int) -> list[float]:
    if (type(values) is not list or len(values) != classes or any(
            type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1
            for p in values) or abs(math.fsum(values) - 1.0) > 1e-6):
        raise ContractError("unsealed, malformed or unnormalized probabilities")
    return [float(p) for p in values]


def evaluate(plan: dict, targets: list[dict], result_files: list[tuple[dict, str]],
             plan_sha256: str) -> dict:
    validate_plan(plan)
    if sha(canonical(plan)) != _digest(plan_sha256):
        raise ContractError("plan changed after freezing")
    sources = _case_sources(targets, plan)
    expected_names = [item["name"] for item in plan["candidates"]]
    if len(result_files) != len(expected_names):
        raise ContractError("all candidate result files are mandatory")
    selected = {}
    for document, file_digest in result_files:
        _digest(file_digest)
        if sha(canonical(document)) != file_digest:
            raise ContractError("candidate result bytes do not match its pin")
        _fields(document, {"schema", "candidate", "plan_sha256", "profile_sha256",
                           "snapshot_sha256", "train_sha256", "future_source_sha256",
                           "hardware_sha256", "environment_sha256", "train_steps",
                           "head_parameters", "seed", "execution", "predictions"}, "candidate result")
        if document["schema"] != RESULT:
            raise ContractError("unknown candidate result schema")
        name = document["candidate"]
        if name not in expected_names or name in selected:
            raise ContractError("unexpected or duplicate candidate result")
        declaration = next(x for x in plan["candidates"] if x["name"] == name)
        for field in ("profile_sha256", "snapshot_sha256"):
            if document[field] != declaration[field]:
                raise ContractError("model identity does not match the frozen plan")
        for field in ("train_sha256", "future_source_sha256", "hardware_sha256",
                      "environment_sha256", "seed"):
            if document[field] != plan[field]:
                raise ContractError("data, machine or seed changed between arms")
        if (document["plan_sha256"] != plan_sha256
                or document["train_steps"] != (0 if name == "no_change" else plan["train_steps"])
                or document["head_parameters"] != (0 if name == "no_change" else plan["head_parameters"])):
            raise ContractError("unmatched or retroactively changed training budget")
        execution = _fields(document["execution"], {
            "physical_forwards", "checkpoint_locally_verified", "resident_bytes",
            "wall_ns", "cpu_ns", "energy_joules", "publisher_authenticated",
        }, "resource witness")
        _positive(execution["physical_forwards"], 2**31-1, "actual forwards")
        for item in ("resident_bytes", "wall_ns", "cpu_ns"):
            _positive(execution[item], 2**63-1, item)
        if type(execution["checkpoint_locally_verified"]) is not bool or not execution["checkpoint_locally_verified"]:
            raise ContractError("checkpoint must be materialized and locally verified")
        if type(execution["publisher_authenticated"]) is not bool:
            raise ContractError("invalid publisher declaration")
        joules = execution["energy_joules"]
        if joules is not None and (type(joules) not in (int, float) or not math.isfinite(joules) or joules <= 0):
            raise ContractError("invalid physical energy declaration")
        preds = document["predictions"]
        if type(preds) is not list or len(preds) != len(sources):
            raise ContractError("candidate skipped or added future cases")
        sequence = []
        for actual, source in zip(preds, sources):
            _fields(actual, set(source) | {"probabilities"}, "source-only prediction")
            if any(actual[k] != source[k] for k in source):
                raise ContractError("candidate prediction cohort or time drift")
            sequence.append(_probabilities(actual["probabilities"], plan["classes"]))
        selected[name] = {"probabilities": sequence, "execution": execution,
                          "result_sha256": file_digest}
    if sorted(selected) != expected_names:
        raise ContractError("missing exact candidate coverage")
    outcomes = [row["label"] for row in targets]
    baseline = selected["no_change"]["probabilities"]
    base_correct = [int(max(range(plan["classes"]), key=lambda i: (p[i], -i)) == y)
                    for p, y in zip(baseline, outcomes)]
    reports = {}
    for name in expected_names:
        rows = selected[name]["probabilities"]
        correct = [int(max(range(plan["classes"]), key=lambda i: (p[i], -i)) == y)
                   for p, y in zip(rows, outcomes)]
        bins = [[] for _ in range(10)]
        for p, y, ok in zip(rows, outcomes, correct):
            bins[min(9, int(10 * max(p)))].append((max(p), ok))
        ece = math.fsum(abs(math.fsum(t[0] for t in bucket) / len(bucket)
                            - math.fsum(t[1] for t in bucket) / len(bucket)) * len(bucket)
                        for bucket in bins if bucket) / len(rows)
        reports[name] = {
            "cases": len(rows), "accuracy": math.fsum(correct) / len(rows),
            "brier": math.fsum(math.fsum((p[i] - (i == y)) ** 2
                                         for i in range(plan["classes"]))
                                for p, y in zip(rows, outcomes)) / len(rows),
            "log_loss": math.fsum(-math.log(max(p[y], 1e-12))
                                   for p, y in zip(rows, outcomes)) / len(rows),
            "ece_10": ece,
            "new_errors_vs_no_change": sum(b and not a for a, b in zip(correct, base_correct)),
            "recovered_errors_vs_no_change": sum(a and not b for a, b in zip(correct, base_correct)),
            "declared_resource_receipt": selected[name]["execution"],
            "candidate_result_sha256": selected[name]["result_sha256"],
        }
    return {"schema": READOUT, "plan_sha256": plan_sha256,
            "future_targets_sha256": plan["future_targets_sha256"],
            "future_source_sha256": plan["future_source_sha256"],
            "candidate_results": reports, "frozen_no_change": "no_change",
            "all_arms_evaluated": True, "independent_ndu_verified": False,
            "resource_receipts_independently_attested": False,
            "pretrained_publisher_authenticated": False,
            "real_model_learning_benefit_qualified": False,
            "winner": None, "production_accepted": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Independent readout; does not select production stem")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--future-targets", type=Path, required=True)
    parser.add_argument("--future-targets-sha256", required=True)
    parser.add_argument("--candidate", type=Path, action="append", required=True)
    parser.add_argument("--candidate-sha256", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if len(args.candidate) != len(args.candidate_sha256):
        parser.error("exact file and SHA256 count must match")
    plan = load_pinned_document(args.plan, args.plan_sha256)
    if args.future_targets_sha256 != plan.get("future_targets_sha256"):
        raise ContractError("future targets hash is not the precommitted plan hash")
    truth, _ = load_pinned_jsonl(args.future_targets, args.future_targets_sha256)
    files = [(load_pinned_document(path, digest), digest)
             for path, digest in zip(args.candidate, args.candidate_sha256)]
    write_new(args.output, evaluate(plan, truth, files, args.plan_sha256))


if __name__ == "__main__":
    main()
