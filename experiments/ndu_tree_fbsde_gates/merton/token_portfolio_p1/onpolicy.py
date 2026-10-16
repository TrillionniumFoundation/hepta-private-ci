"""P2 prospective on-policy research executor protocol.

Runs ONLY explicit, injected, separately-authorized Reader adapters. Never accepts
future labels or unexecuted candidates at decision time. This is an offline
qualification harness, NOT a Hepta product ModelWorker or effect authority.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from portfolio import Invalid, canonical, digest, fit, manifest, public_cases, run
from replay import read, write_new

MAX_READER_OUTPUT_BYTES = 16_384


@dataclass(frozen=True)
class Meter:
    input_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    output_tokens: int
    latency_ms: int

    def validate(self, token_ceiling: int, latency_ceiling: int) -> None:
        values = (self.input_tokens, self.cached_input_tokens, self.reasoning_tokens,
                  self.output_tokens, self.latency_ms)
        if any(type(x) is not int or x < 0 or x > 1_000_000 for x in values):
            raise Invalid("nonnegative integer physical meter fields required")
        if self.cached_input_tokens > self.input_tokens:
            raise Invalid("cached tokens exceed input")
        # Baseline input/output is charged in the independently reported full
        # lifecycle. Additional action ceilings apply ONLY to incremental
        # reasoning tokens. No real cost is estimated or fabricated here.
        if self.reasoning_tokens > token_ceiling or self.latency_ms > latency_ceiling:
            raise Invalid("original Reader exceeded admitted action ceiling")


@dataclass(frozen=True)
class Response:
    answer: str
    meter: Meter
    receipt_digest: str

    def validate(self, token_ceiling: int, latency_ceiling: int) -> None:
        if type(self.answer) is not str or not 1 <= len(self.answer) <= 2048:
            raise Invalid("empty or oversized original Reader answer")
        if type(self.receipt_digest) is not str or len(self.receipt_digest) != 64 or any(
            c not in "0123456789abcdef" for c in self.receipt_digest
        ):
            raise Invalid("original Reader receipt identifier required")
        self.meter.validate(token_ceiling, latency_ceiling)


def packet(raw: Any, expected_ids: set[str]) -> dict[str, str]:
    if type(raw) is not dict or set(raw) != {"schema", "prompts"} or raw["schema"] != "hepta.p2.public-prompts.v1":
        raise Invalid("untrusted prompt packet format")
    if type(raw["prompts"]) is not list or len(raw["prompts"]) != len(expected_ids):
        raise Invalid("prompt packet count")
    prompts: dict[str, str] = {}
    for row in raw["prompts"]:
        if type(row) is not dict or set(row) != {"task_id", "prompt"}:
            raise Invalid("untrusted prompt row keys (labels forbidden)")
        tid, value = row["task_id"], row["prompt"]
        if type(tid) is not str or tid in prompts or type(value) is not str or not 1 <= len(value) <= 8192:
            raise Invalid("duplicate/malformed prompt")
        prompts[tid] = value
    if set(prompts) != expected_ids:
        raise Invalid("prompt tasks differ from admission")
    return prompts


def execute(manifest_doc: Any, train_doc: Any, public_doc: Any, prompts_doc: Any,
            execute_reader: Callable[[str, str, str], Response],
            *, policy: str, model_digest: str, adapter_digest: str) -> dict[str, Any]:
    if policy not in ("direct", "fixed_reason", "greedy", "neutral", "fixed_risk", "ndu_discrete", "ordinary_same_profile"):
        raise Invalid("unknown policy")
    if any(type(d) is not str or len(d) != 64 or any(c not in "0123456789abcdef" for c in d)
           for d in (model_digest, adapter_digest)):
        raise Invalid("model/adapter source digests required")
    acts, token_budget, latency_budget, fee = manifest(manifest_doc)
    by_action = {a.name: a for a in acts}
    cases = public_cases(public_doc)
    prompts = packet(prompts_doc, {c.task_id for c in cases})
    # run is label-blind. An outcome/truth argument does not exist in this API.
    sealed_decision = run(manifest_doc, train_doc, public_doc)
    decision = next(p for p in sealed_decision["attempt"]["policies"] if p["policy"] == policy)
    token_total, latency_total = 0, 0
    results = []
    for case in cases:
        action = decision["assignments"][case.task_id]
        profile = by_action[action]
        # This request is the FIRST authorized run for the selected action,
        # not a selection from an already completed full-action matrix.
        out = execute_reader(case.task_id, prompts[case.task_id], action)
        if type(out) is not Response:
            raise Invalid("typed Reader Response required")
        out.validate(profile.token_ceiling, profile.latency_ceiling_ms)
        token_total += out.meter.reasoning_tokens
        latency_total += out.meter.latency_ms
        if token_total > token_budget or latency_total > latency_budget:
            raise Invalid("physical action budget exceeded")
        results.append({
            "task_id": case.task_id, "selected_action": action, "answer": out.answer,
            "meter": vars(out.meter), "reader_receipt_sha256": out.receipt_digest,
        })
    return {
        "schema": "hepta.p2.onpolicy-attempt.v1", "qualifier": "RESEARCH_ONLY_DENY_ALL",
        "model_sha256": model_digest, "adapter_sha256": adapter_digest,
        "policy": policy, "manifest_sha256": digest(manifest_doc),
        "train_sha256": digest(train_doc), "public_sha256": digest(public_doc),
        "prompts_sha256": digest(prompts_doc), "decision_sha256": sealed_decision["seal_sha256"],
        "registered_token_budget": token_budget, "registered_latency_budget_ms": latency_budget,
        "observed_additional_reasoning_tokens": token_total,
        "observed_total_latency_ms": latency_total,
        "records": results,
        "limitations": "MODEL_AND_METER_RECEIPTS_FROM_CALLER_NOT_INDEPENDENTLY_ATTESTED",
    }


def score_postseal(attempt: Any, gold: Any) -> dict[str, Any]:
    if type(attempt) is not dict or attempt.get("schema") != "hepta.p2.onpolicy-attempt.v1":
        raise Invalid("unknown attempt")
    if type(gold) is not dict or set(gold) != {"schema", "answers"} or gold["schema"] != "hepta.p2.gold.v1":
        raise Invalid("gold owner schema")
    if type(gold["answers"]) is not list or len(gold["answers"]) != len(attempt["records"]):
        raise Invalid("gold count")
    labels: dict[str, str] = {}
    for row in gold["answers"]:
        if type(row) is not dict or set(row) != {"task_id", "answer"}:
            raise Invalid("gold keys")
        tid, answer = row["task_id"], row["answer"]
        if type(tid) is not str or tid in labels or type(answer) is not str or not 1 <= len(answer) <= 2048:
            raise Invalid("bad gold row")
        labels[tid] = answer
    if set(labels) != {x["task_id"] for x in attempt["records"]}:
        raise Invalid("unmatched gold task")
    # Exact-match scorer deliberately narrow: no hidden judge, self-scoring
    # language model, or answer normalization selected after seeing results.
    correct = sum(x["answer"] == labels[x["task_id"]] for x in attempt["records"])
    return {
        "schema": "hepta.p2.postseal-score.v1",
        "attempt_sha256": digest(attempt), "gold_sha256": digest(gold),
        "correct": correct, "total": len(labels),
        "additional_reasoning_tokens": attempt["observed_additional_reasoning_tokens"],
        "total_reported_latency_ms": attempt["observed_total_latency_ms"],
        "interpretation": "ON_POLICY_CALLER_METERED_NOT_INDEPENDENT_MODEL_ATTESTATION",
        "qualifier": "RESEARCH_ONLY_DENY_ALL",
    }


def cli() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=("run", "score"))
    p.add_argument("--manifest")
    p.add_argument("--train")
    p.add_argument("--public")
    p.add_argument("--prompts")
    p.add_argument("--policy")
    p.add_argument("--model-sha256")
    p.add_argument("--adapter-sha256")
    p.add_argument("--adapter")
    p.add_argument("--attempt")
    p.add_argument("--gold")
    p.add_argument("--output", required=True)
    args = p.parse_args()
    if args.operation == "score":
        if not args.attempt or not args.gold or any(
            [args.manifest, args.train, args.public, args.prompts, args.adapter, args.policy]
        ):
            p.error("score accepts only an original attempt and postseal gold")
        result = score_postseal(read(args.attempt), read(args.gold))
    else:
        if args.gold or args.attempt:
            p.error("original Reader runner cannot access future gold or previous attempt")
        if not all((args.manifest, args.train, args.public, args.prompts,
                    args.policy, args.adapter, args.model_sha256, args.adapter_sha256)):
            p.error("real Reader inputs and pinned adapter required")
        path = Path(args.adapter).resolve(strict=True)
        b = path.read_bytes()
        if digest_adapter_bytes(b) != args.adapter_sha256:
            raise Invalid("adapter code SHA256 mismatch")
        spec = importlib.util.spec_from_file_location("hepta_p2_reader_adapter", path)
        if spec is None or spec.loader is None:
            raise Invalid("invalid local Reader adapter")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "execute_reader", None)
        if not callable(fn):
            raise Invalid("reader adapter must export execute_reader(task_id,prompt,action)")
        result = execute(read(args.manifest), read(args.train), read(args.public),
                         read(args.prompts), fn, policy=args.policy,
                         model_digest=args.model_sha256, adapter_digest=args.adapter_sha256)
    write_new(args.output, result)
    print(json.dumps({"output": args.output, "sha256": digest(result),
                      "authority": "RESEARCH_ONLY_DENY_ALL"}, sort_keys=True))


def digest_adapter_bytes(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    cli()
