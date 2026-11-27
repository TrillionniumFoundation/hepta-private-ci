"""Strict prelabel producer and postseal reviewer for NDU token allocation.

A SHA256 seal is tamper evidence only; it is not independent custody or a timestamp.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from portfolio import Invalid, canonical, digest, keys, manifest, public_cases, run


def read(path: str) -> Any:
    with open(path, "rb") as f:
        b = f.read(2_000_001)
    if len(b) > 2_000_000:
        raise Invalid("input too large")
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in items:
            if k in out:
                raise Invalid("duplicate JSON key")
            out[k] = v
        return out
    try:
        return json.loads(b, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(Invalid("nonfinite number")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Invalid("invalid JSON") from exc


def review(manifest_doc: Any, train_doc: Any, public_doc: Any, sealed: Any, truth: Any) -> dict[str, Any]:
    keys(sealed, {"attempt", "seal_sha256"}, "seal")
    if type(sealed["seal_sha256"]) is not str or len(sealed["seal_sha256"]) != 64 or digest(sealed["attempt"]) != sealed["seal_sha256"]:
        raise Invalid("invalid attempt SHA256 seal")
    expected = run(manifest_doc, train_doc, public_doc)
    if canonical(expected) != canonical(sealed):
        raise Invalid("attempt/source/policy drift from sealed original")
    acts, token_budget, latency_budget, fee = manifest(manifest_doc)
    cases = public_cases(public_doc)
    keys(truth, {"schema", "cases"}, "truth")
    if truth["schema"] != "hepta.p1.postseal-truth.v1" or type(truth["cases"]) is not list or len(truth["cases"]) != len(cases):
        raise Invalid("invalid truth inventory")
    valid = {a.name: a for a in acts}
    original: dict[str, dict[str, tuple[int, int, int]]] = {}
    for row in truth["cases"]:
        keys(row, {"task_id", "actions"}, "truth case")
        task = row["task_id"]
        if type(task) is not str or task in original or type(row["actions"]) is not list:
            raise Invalid("duplicate/invalid truth task")
        actions: dict[str, tuple[int, int, int]] = {}
        for outcome in row["actions"]:
            keys(outcome, {"action", "success", "actual_incremental_tokens", "actual_latency_ms"}, "outcome")
            name = outcome["action"]
            if type(name) is not str or name in actions or name not in valid:
                raise Invalid("missing/duplicate/unknown truth action")
            a = valid[name]
            success = outcome["success"]
            tokens = outcome["actual_incremental_tokens"]
            duration = outcome["actual_latency_ms"]
            if type(success) is not int or success not in (0, 1) or type(tokens) is not int or type(duration) is not int:
                raise Invalid("invalid independently scored outcome or meter")
            if not 0 <= tokens <= a.token_ceiling or not 0 <= duration <= a.latency_ceiling_ms:
                raise Invalid("original physical cost exceeds registered ceiling")
            actions[name] = (success, tokens, duration)
        if set(actions) != set(valid):
            raise Invalid("incomplete outcome action panel")
        original[task] = actions
    if set(original) != {c.task_id for c in cases}:
        raise Invalid("original outcome task mismatch")
    whole_trace_tokens = sum(v[1] for t in original.values() for v in t.values())
    whole_trace_latency = sum(v[2] for t in original.values() for v in t.values())
    report = []
    for policy in sealed["attempt"]["policies"]:
        allocations = policy["assignments"]
        if set(allocations) != set(original):
            raise Invalid("allocation task mismatch")
        completed = sum(original[tid][action][0] for tid, action in allocations.items())
        charged_tokens = sum(original[tid][action][1] for tid, action in allocations.items())
        charged_latency = sum(original[tid][action][2] for tid, action in allocations.items())
        if charged_tokens > token_budget or charged_latency > latency_budget:
            raise Invalid("physical cost budget violated")
        report.append({
            "policy": policy["policy"], "correct_tasks": completed, "of_tasks": len(cases),
            "counterfactual_selected_tokens": charged_tokens,
            "counterfactual_selected_latency_ms": charged_latency,
            "realized_task_minus_token_fee": str(completed - fee*charged_tokens),
        })
    return {
        "schema": "hepta.p1.postseal-review.v1", "attempt_sha256": sealed["seal_sha256"],
        "truth_sha256": digest(truth), "policy_scores": report,
        "full_precomputed_trace_reported_tokens": whole_trace_tokens,
        "full_precomputed_trace_reported_latency_ms": whole_trace_latency,
        "interpretation": "RETROSPECTIVE_FULL_TRACE_PAID_NO_ON_POLICY_PHYSICAL_SAVINGS",
        "authority": "RESEARCH_ONLY_DENY_ALL",
    }


def write_new(path: str, obj: Any) -> None:
    with open(path, "xb") as f:
        f.write(canonical(obj) + b"\n")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("producer", "review"))
    p.add_argument("--manifest", required=True)
    p.add_argument("--train", required=True)
    p.add_argument("--public", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--sealed")
    p.add_argument("--truth")
    a = p.parse_args()
    if a.command == "producer" and (a.sealed or a.truth):
        p.error("producer must not receive truth or review material")
    if a.command == "review" and (not a.sealed or not a.truth):
        p.error("review requires both sealed attempt and separately held truth")
    docs = [read(a.manifest), read(a.train), read(a.public)]
    if a.command == "producer":
        result = run(*docs)
    else:
        result = review(*docs, read(a.sealed), read(a.truth))
    write_new(a.output, result)
    print(json.dumps({"output": str(Path(a.output)), "sha256": digest(result), "authority": "DENY_ALL"}, sort_keys=True))


if __name__ == "__main__":
    main()
