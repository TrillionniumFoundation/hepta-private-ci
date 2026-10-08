"""Frozen native-question coverage and fail-closed shard aggregation.

This is an unsigned experiment collector, not a new learning.eval authority.
A missing job, failed answer, or unresolved annotation never becomes a smaller
successful denominator. LoCoMo folds are source-family held out; LongMemEval is
external test-only and must not fit a reranker on its own gold annotations.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from native import Benchmark, Question, digest

ARMS = ("no_memory", "rag", "rag_lora", "parametric_only")


def partition(benchmark: Benchmark, query: Question, *, fold: int, folds: int) -> str:
    if type(fold) is not int or type(folds) is not int or not 0 <= fold < folds <= 16:
        raise ValueError("fold identity/bound")
    if benchmark.name == "longmemeval":
        if folds != 1:
            raise ValueError("LongMemEval is external test-only, not a train/test resplit")
        return "test"
    if folds == 1:
        return benchmark.partition(query)
    families = sorted(set(benchmark.families.values()), key=digest)
    if not 3 <= folds <= len(families):
        raise ValueError("cross-fit requires at least three root-separated folds")
    bucket = families.index(benchmark.families[query.family]) % folds
    if bucket == fold:
        return "test"
    if bucket == (fold + 1) % folds:
        return "select"
    return "train"


@dataclass(frozen=True)
class CoveragePlan:
    benchmark: str
    source_sha256: str
    native_total: int
    folds: int
    shards: int
    per_fold_limit: int | None
    cases: tuple[tuple[str, str, int, int], ...]  # native question, source family, fold, shard

    def content(self) -> dict:
        return {"schema": "hepta.memory-benchmark.coverage.v1", **asdict(self)}

    def seal(self) -> str:
        return digest(self.content())

    def assigned(self, fold: int, shard: int) -> tuple[str, ...]:
        if not 0 <= fold < self.folds or not 0 <= shard < self.shards:
            raise ValueError("shard outside frozen plan")
        return tuple(identity for identity, _, f, s in self.cases if (f, s) == (fold, shard))


def decode_plan(value: dict) -> CoveragePlan:
    """Validate an externally frozen manifest, never infer the plan from results."""
    required = {"schema", "benchmark", "source_sha256", "native_total", "folds", "shards", "per_fold_limit", "cases"}
    if not isinstance(value, dict) or set(value) != required or value["schema"] != "hepta.memory-benchmark.coverage.v1":
        raise ValueError("unknown coverage manifest")
    if value["benchmark"] not in ("longmemeval", "locomo"):
        raise ValueError("unknown benchmark")
    source = value["source_sha256"]
    if not isinstance(source, str) or len(source) != 64 or any(c not in "0123456789abcdef" for c in source):
        raise ValueError("source digest")
    for key, maximum in (("native_total", 20_000), ("folds", 16), ("shards", 64)):
        if type(value[key]) is not int or not 1 <= value[key] <= maximum:
            raise ValueError("coverage bounds")
    if value["benchmark"] == "longmemeval" and value["folds"] != 1:
        raise ValueError("external-test-only fold")
    limit = value["per_fold_limit"]
    if limit is not None and (type(limit) is not int or not 1 <= limit <= 20_000):
        raise ValueError("coverage limit")
    cases = value["cases"]
    if not isinstance(cases, (list, tuple)) or not 1 <= len(cases) <= value["native_total"]:
        raise ValueError("coverage cases")
    seen = set()
    for row in cases:
        if not isinstance(row, (list, tuple)) or len(row) != 4:
            raise ValueError("case shape")
        qid, family, fold, shard = row
        if any(not isinstance(x, str) or not x or len(x.encode()) > 1024 for x in (qid, family)):
            raise ValueError("case identity")
        if qid in seen or type(fold) is not int or type(shard) is not int or not 0 <= fold < value["folds"] or not 0 <= shard < value["shards"]:
            raise ValueError("duplicate/out-of-bound case")
        seen.add(qid)
    return CoveragePlan(value["benchmark"], source, value["native_total"], value["folds"], value["shards"], limit, tuple(tuple(row) for row in cases))


def plan_coverage(benchmark: Benchmark, *, folds: int, shards: int, per_fold_limit: int | None) -> CoveragePlan:
    if type(shards) is not int or not 1 <= shards <= 64:
        raise ValueError("shard budget")
    if type(folds) is not int or not 1 <= folds <= 16:
        raise ValueError("fold budget")
    if per_fold_limit is not None and (type(per_fold_limit) is not int or not 1 <= per_fold_limit <= 20_000):
        raise ValueError("query limit")
    if not benchmark.questions or len({q.identity for q in benchmark.questions}) != len(benchmark.questions):
        raise ValueError("empty/duplicate native question identity")
    cases = []
    for fold in range(folds):
        queries = sorted((q for q in benchmark.questions if partition(benchmark, q, fold=fold, folds=folds) == "test"), key=lambda q: digest(q.identity))
        if not queries:
            raise ValueError("no held-out source family for fold")
        if per_fold_limit is not None:
            queries = queries[:per_fold_limit]
        for position, query in enumerate(queries):
            cases.append((query.identity, benchmark.families[query.family], fold, position % shards))
    if len({identity for identity, _, _, _ in cases}) != len(cases):
        raise ValueError("one native question appears in multiple evaluation folds")
    return CoveragePlan(benchmark.name, benchmark.source_sha256, len(benchmark.questions), folds, shards, per_fold_limit, tuple(cases))


def aggregate(plan: CoveragePlan, receipts: list[dict], *, execution_binding: dict) -> dict:
    """The trusted caller supplies the pre-run plan and exact code/model/budget tuple.

    This validates completeness and record consistency, not truth, authorization,
    statistical independence, judge correctness or production readiness.
    """
    slots, outcomes = set(), {arm: {} for arm in ARMS}
    retained_bytes = 0
    for receipt in receipts:
        fold, shard = receipt.get("fold"), receipt.get("shard")
        if type(fold) is not int or type(shard) is not int:
            raise ValueError("missing shard identity")
        slot = (fold, shard)
        expected = set(plan.assigned(fold, shard))
        if slot in slots:
            raise ValueError("duplicate shard receipt")
        slots.add(slot)
        if receipt.get("coverage_digest") != plan.seal() or receipt.get("execution_binding") != execution_binding:
            raise ValueError("source/model/code/protocol drift")
        arms = receipt.get("results")
        if not isinstance(arms, dict) or set(arms) != set(ARMS):
            raise ValueError("missing or undeclared experimental arm")
        size = receipt.get("retained_bytes")
        if type(size) is not int or size < 0:
            raise ValueError("missing actual retained storage measurement")
        retained_bytes += size
        for arm in ARMS:
            records = arms[arm]
            if not isinstance(records, list):
                raise ValueError("arm records must be a list")
            seen = set()
            for record in records:
                qid = record.get("question_id")
                if not isinstance(qid, str) or qid in seen or qid not in expected:
                    raise ValueError("duplicate or out-of-scope question result")
                seen.add(qid)
                if record.get("status") not in ("succeeded", "failed"):
                    raise ValueError("unknown or missing terminal observation")
                value = record.get("diagnostic_token_f1")
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
                    raise ValueError("invalid bounded diagnostic score")
                if record["status"] == "failed" and value is not None:
                    raise ValueError("failed work cannot claim a measured score")
                if record["status"] == "succeeded" and not isinstance(record.get("hypothesis"), str):
                    raise ValueError("successful result omitted generated text")
                if qid in outcomes[arm]:
                    raise ValueError("same query counted across shard receipts")
                outcomes[arm][qid] = record
            if seen != expected:
                raise ValueError("incomplete arm: missing questions must have explicit failure records")
    if slots != {(f, s) for f in range(plan.folds) for s in range(plan.shards)}:
        raise ValueError("missing shard; no complete benchmark result")
    expected_all = {identity for identity, _, _, _ in plan.cases}
    result = {}
    for arm, records in outcomes.items():
        if set(records) != expected_all:
            raise ValueError("incomplete experiment arm")
        successful = [r for r in records.values() if r["status"] == "succeeded"]
        scored = [r["diagnostic_token_f1"] for r in successful if r.get("diagnostic_token_f1") is not None]
        result[arm] = {
            "planned": len(records), "succeeded": len(successful),
            "failed": len(records) - len(successful), "diagnostically_scored": len(scored),
            "diagnostic_f1_conditional_mean": sum(scored) / len(scored) if scored else None,
            "diagnostic_f1_zero_for_unscored_lower_summary": sum(scored) / len(records) if records else None,
        }
    return {
        "schema": "hepta.memory-benchmark.coverage-result.v1",
        "coverage_digest": plan.seal(), "execution_binding": execution_binding,
        "complete": True, "coverage_scope": "frozen-plan",
        "all_native_questions_covered": len(plan.cases) == plan.native_total,
        "native_question_total": plan.native_total, "native_cases": len(plan.cases),
        "source_root_groups": len({family for _, family, _, _ in plan.cases}),
        "physically_retained_shard_bytes": retained_bytes, "arms": result,
        "official_benchmark_score": None, "citation_entailment_precision": None,
        "production_accepted": False, "superiority_claim": False,
        "notes": ["Cross-fit/connected source groups are not independent calendar snapshots.",
                  "Conditional diagnostic F1 excludes unscored answers; the full planned denominator is retained.",
                  "Independent signed learning.eval evidence is required for statistical or production qualification."],
    }
