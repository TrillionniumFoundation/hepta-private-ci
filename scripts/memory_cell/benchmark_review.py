"""Read-only census of a complete frozen benchmark, without a model or judge.

The investigator and generator identities stay distinct. Old outputs are never
relabelled as fresh executions. Historical records without a bound citation
request stay unavailable rather than receiving a post-hoc generator signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

from benchmark_coverage import ARMS, aggregate, decode_plan
from citation_audit import request_payload, sha
from native import digest
from native_citation import capture_native

MAX_REPORT = 64 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024


def read_json(path: Path, limit: int) -> tuple[dict, str, int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular immutable input required")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("review input byte bound")

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def invalid_number(value):
        raise ValueError(f"nonfinite JSON number: {value}")

    return (
        json.loads(raw, object_pairs_hook=object_pairs, parse_constant=invalid_number),
        sha(raw),
        len(raw),
    )


def load_complete(plan_path: Path, receipts_root: Path):
    declared, plan_hash, size = read_json(plan_path, MAX_REPORT)
    if (
        set(declared) != {"schema", "coverage", "execution_binding"}
        or declared["schema"] != "hepta.memory-benchmark.preregistered.v1"
    ):
        raise ValueError("unknown pre-run manifest")
    plan = decode_plan(declared["coverage"])
    if len(plan.cases) != plan.native_total or plan.per_fold_limit is not None:
        raise ValueError("review requires every native question, not a pilot")
    paths = sorted(receipts_root.rglob("report.json"))
    if len(paths) != plan.folds * plan.shards:
        raise ValueError("missing or surplus shard reports")
    records, inputs = [], []
    for path in paths:
        if any(p.is_symlink() for p in path.parents):
            raise ValueError("symlink in report path")
        report, hashed, used = read_json(path, MAX_REPORT)
        size += used
        if size > MAX_TOTAL:
            raise ValueError("review total byte bound")
        records.append(report)
        inputs.append(
            {
                "relative_path": str(path.relative_to(receipts_root)),
                "sha256": hashed,
                "bytes": used,
            }
        )
    coverage = aggregate(plan, records, execution_binding=declared["execution_binding"])
    return plan, declared["execution_binding"], records, coverage, plan_hash, inputs


def paired_diagnostics(plan, reports):
    """Exploratory equal-family differences with worst-case unmeasured outcomes.

    [0,1] is an identification interval for a missing score, NOT an invented
    measurement. The simultaneous Hoeffding bounds additionally assume independent
    families; neither source independence nor train-fold independence is proved.
    """
    outcomes = {arm: {} for arm in ARMS}
    for report in reports:
        for arm in ARMS:
            outcomes[arm].update((r["question_id"], r) for r in report["results"][arm])
    families = {}
    for qid, family, _, _ in plan.cases:
        families.setdefault(family, []).append(qid)
    comparisons = []
    for arm in ("no_memory", "rag_lora", "parametric_only"):
        bounds, unmeasured = [], 0
        for members in families.values():
            lower, upper = 0.0, 0.0
            for qid in members:
                a = outcomes[arm][qid].get("diagnostic_token_f1")
                b = outcomes["rag"][qid].get("diagnostic_token_f1")
                unmeasured += a is None or b is None
                lower += (a if a is not None else 0.0) - (b if b is not None else 1.0)
                upper += (a if a is not None else 1.0) - (b if b is not None else 0.0)
            bounds.append((lower / len(members), upper / len(members)))
        lo = sum(v[0] for v in bounds) / len(bounds)
        hi = sum(v[1] for v in bounds) / len(bounds)
        radius = math.sqrt(2.0 * math.log(2.0 * 3 / 0.05) / len(bounds))
        comparisons.append(
            {
                "candidate": arm,
                "baseline": "rag",
                "family_groups": len(bounds),
                "paired_questions": len(plan.cases),
                "unmeasured_pairs": unmeasured,
                "identified_family_mean_difference": [lo, hi],
                "conditional_simultaneous_95_interval": [
                    max(-1.0, lo - radius),
                    min(1.0, hi + radius),
                ],
            }
        )
    return {
        "metric": "diagnostic-token-f1-not-official-judge-score",
        "analysis": "retrospective-exploratory-not-preregistered-qualification",
        "independence_verified": False,
        "comparisons": comparisons,
        "statistical_superiority_established": False,
    }


def audit_entry(plan, binding, arm, row, family, question=None):
    """Bind a review item to original bytes; never fill missing prompt material."""
    qid = row["question_id"]
    alias = digest(("hepta.memory-benchmark.blind-review.v1", plan.seal(), arm, qid))
    item = {
        "schema": "hepta.memory-benchmark.review-item.v1",
        "review_id": alias,
        "status": "unavailable",
        "generator_signature": None,
        "evaluator_signature": None,
        "judgement": None,
        "semantic_precision": None,
        "production_accepted": False,
    }
    index = {
        "review_id": alias,
        "arm": arm,
        "question_id": qid,
        "family": family,
        "original_record_sha256": digest(row),
    }
    if question is not None:
        item.update(
            question=question.content,
            question_time=question.observed_at,
            question_origin="pinned-benchmark-not-generator-attestation",
        )
    if row["status"] == "failed":
        item.update(
            status="execution_failed", reason=row.get("stage", "model-execution")
        )
        return item, index
    if not row["hypothesis"].strip():
        raise ValueError("successful result has no generated answer")
    queue, receipt = row.get("citation_audit"), row.get("receipt")
    if not isinstance(receipt, dict):
        item["reason"] = "missing-original-model-receipt"
        return item, index
    # Historical native outputs have raw root strings. Preserve their exact
    # delivered material for investigation; do not rebuild a signed request.
    item["answer"] = row["hypothesis"]
    item["original_prompt_sha256"] = receipt.get("input_ids_sha256")
    item["delivered_evidence"] = receipt.get("delivered_evidence")
    if not isinstance(queue, dict) or "request" not in queue:
        item["reason"] = "no-original-bound-citation-request"
        return item, index
    request = queue["request"]
    encoded = request_payload(request)
    if question is not None and (
        request["scope"] != question.scope
        or request["question"] != question.content
        or request["question_time"] != question.observed_at
    ):
        raise ValueError("citation question differs from pinned native input")
    if (
        queue.get("request_sha256") != sha(encoded)
        or request["query_id"] != qid
        or request["family_digest"] != digest(family)
        or request["experiment_digest"] != digest((plan.seal(), binding, arm))
        or request["answer"] != row["hypothesis"]
        or request["prompt_digest"] != receipt.get("input_ids_sha256")
    ):
        raise ValueError("citation request detached from original result")
    if queue.get("schema") == "hepta.memory-citation.native-queue.v1":
        from native import Question

        q = Question(
            qid, family, request["scope"], request["question"], request["question_time"]
        )
        expected = capture_native(
            q,
            row["hypothesis"],
            receipt,
            experiment_digest=request["experiment_digest"],
            family_digest=request["family_digest"],
        )
        if queue != expected:
            raise ValueError("native root mapping or unsigned queue drift")
    elif queue.get("schema") == "hepta.memory-citation.queue.v1":
        delivered = [
            {k: source[k] for k in ("id", "root", "label", "excerpt")}
            for source in receipt.get("delivered_evidence", [])
        ]
        if request["sources"] != delivered:
            raise ValueError("citation source is not actually delivered")
        if any(
            queue.get(k) is not None
            for k in (
                "judgement",
                "generator_signature",
                "evaluator_signature",
                "semantic_precision",
            )
        ):
            raise ValueError("adjudications require the separate signed owner ingress")
    else:
        raise ValueError("unknown citation queue schema")
    item.update(
        status="awaiting_independent_judgement",
        request=request,
        request_sha256=sha(encoded),
        reason="unsigned-generator-and-evaluator",
    )
    return item, index


def review(
    plan_path: Path,
    receipts_root: Path,
    output: Path,
    *,
    validator_commit: str,
    benchmark_path: Path | None = None,
):
    if len(validator_commit) != 40 or any(
        c not in "0123456789abcdef" for c in validator_commit
    ):
        raise ValueError("exact validator commit required")
    plan, binding, reports, coverage, plan_hash, inputs = load_complete(
        plan_path, receipts_root
    )
    family_by_query = {q: f for q, f, _, _ in plan.cases}
    questions = {}
    if benchmark_path is not None:
        from native import load

        benchmark = load(
            benchmark_path,
            plan.benchmark,
            plan.source_sha256,
            allow_unresolved_evidence=True,
            session_conflicts="retain-versioned",
            invalid_history="quarantine-question",
        )
        questions = {q.identity: q for q in benchmark.questions}
        if set(questions) != set(family_by_query) or any(
            benchmark.families[q.family] != family_by_query[q.identity]
            for q in benchmark.questions
        ):
            raise ValueError("pinned source-family or native question census drift")
    by_arm = {a: {} for a in ARMS}
    for report in reports:
        for arm in ARMS:
            by_arm[arm].update((r["question_id"], r) for r in report["results"][arm])
    # Validate every item before publishing any report. Limit to the already
    # bounded native question census, not a sampling chosen after seeing scores.
    items = []
    counts = {a: {} for a in ARMS}
    for arm in ARMS:
        for qid in sorted(by_arm[arm]):
            item, index = audit_entry(
                plan,
                binding,
                arm,
                by_arm[arm][qid],
                family_by_query[qid],
                questions.get(qid),
            )
            items.append((item, index))
            status = item["status"]
            counts[arm][status] = counts[arm].get(status, 0) + 1
    output.mkdir()
    with (
        (output / "review.jsonl").open("x") as work,
        (output / "review-index.jsonl").open("x") as index,
    ):
        for item, key in sorted(items, key=lambda pair: pair[0]["review_id"]):
            work.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
            index.write(json.dumps(key, ensure_ascii=False, allow_nan=False) + "\n")
    summary = {
        "schema": "hepta.memory-benchmark.review-result.v1",
        "validator_commit": validator_commit,
        "plan_file_sha256": plan_hash,
        "execution_source_commit": binding.get("source_commit"),
        "original_reports": inputs,
        "coverage": coverage,
        "paired_diagnostics": paired_diagnostics(plan, reports),
        "citation_census": counts,
        "all_attempts_exported": len(items),
        "signed_semantic_citation_precision": None,
        "prospective_calendar_windows": 0,
        "independent_acceptance": None,
        "production_accepted": False,
        "superiority_claim": False,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n"
    )
    with (output / "SHA256SUMS").open("x") as manifest:
        for path in sorted(output.iterdir()):
            if path.name != "SHA256SUMS":
                manifest.write(
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    + "  "
                    + path.name
                    + "\n"
                )
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("receipts", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--validator-commit", required=True)
    parser.add_argument("--benchmark-json", type=Path)
    args = parser.parse_args()
    result = review(
        args.plan,
        args.receipts,
        args.output,
        validator_commit=args.validator_commit,
        benchmark_path=args.benchmark_json,
    )
    print(
        json.dumps(
            {
                "native_cases": result["coverage"]["native_cases"],
                "exported_attempts": result["all_attempts_exported"],
                "production_accepted": False,
            }
        )
    )
    if any(a["failed"] for a in result["coverage"]["arms"].values()):
        raise SystemExit("complete census contains failed executions; no qualification")
