"""Plan and gate the complete shared-Stem/Cell/System2 research matrix.

This module deliberately separates resource accounting from neural efficacy.  It
never manufactures task scores.  A reader-gate receipt from an independent
diagnostic is required before a neural matrix can be admitted.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
from pathlib import Path
import sys


STEMS = (
    ("small_stem", 150_000_000, "shared"),
    ("shared_421m", 421_000_000, "shared"),
    ("shared_421m_plus_head", 421_000_000, "shared"),
    ("replicated_421m", 421_000_000, "replicated"),
)
HEADS = (
    ("linear", 1_000_000),
    ("gated", 2_000_000),
    ("lora", 4_000_000),
    ("sparse_expert", 8_000_000),
)
MODALITIES = ("text", "image", "audio", "video")
INFERENCE = ("no_recurrent", "recurrent", "system2", "system2_ndu")
STRUCTURES = ("no_split", "offline_split", "split_merge")
METRICS = (
    "task_score",
    "evidence_precision",
    "unsupported_claim_rate",
    "ece",
    "brier",
    "p95_latency_ms",
    "active_flops",
    "peak_memory_bytes",
    "energy_joules",
    "incremental_cell_params",
)


@dataclass(frozen=True)
class ReaderGate:
    passed: bool
    reason: str
    independent_adjudication: bool
    human_sufficient_grounded: int
    ordinary_retrieval_grounded: int
    no_evidence_exact_refusal: int
    premise_removed_exact_refusal: int


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _count(condition: dict, *names: str) -> int:
    for name in names:
        value = condition.get(name)
        if type(value) is int and value >= 0:
            return value
    return 0


def evaluate_reader_gate(payload: dict | None) -> ReaderGate:
    """Apply the predeclared four-arm reader admission rule.

    The receipt is intentionally stricter than a model-generated status field:
    it must say that independent adjudication happened and must provide counts
    for sufficient evidence, ordinary retrieval, and both negative controls.
    """
    if not isinstance(payload, dict) or payload.get("schema") != "hepta.reader-gate.v1":
        return ReaderGate(False, "missing-or-unknown-reader-gate", False, 0, 0, 0, 0)
    conditions = payload.get("conditions")
    if not isinstance(conditions, dict):
        return ReaderGate(False, "reader-gate-conditions-missing", False, 0, 0, 0, 0)
    human = conditions.get("human_sufficient", {})
    ordinary = conditions.get("ordinary_retrieval", {})
    empty = conditions.get("no_evidence", {})
    removed = conditions.get("critical_premise_removed", {})
    human_grounded = _count(human, "grounded", "grounded_and_cited")
    ordinary_grounded = _count(ordinary, "grounded", "grounded_and_cited")
    empty_refusal = _count(empty, "exact_refusal", "exact_refusals")
    removed_refusal = _count(removed, "exact_refusal", "exact_refusals")
    independent = payload.get("independent_adjudication") is True
    declared = payload.get("reader_adequacy_established") is True
    passed = (
        independent
        and declared
        and human_grounded >= 15
        and human_grounded > ordinary_grounded
        and empty_refusal >= 18
        and removed_refusal >= 18
    )
    reason = "passed" if passed else "reader-adequacy-gate-not-met"
    return ReaderGate(
        passed,
        reason,
        independent,
        human_grounded,
        ordinary_grounded,
        empty_refusal,
        removed_refusal,
    )


def resource_estimate(stem: str, head: str, modality: str, inference: str,
                      structure: str, cells: int) -> dict:
    stem_row = next(row for row in STEMS if row[0] == stem)
    head_params = next(row[1] for row in HEADS if row[0] == head)
    modality_params = {"text": 500_000, "image": 8_000_000,
                       "audio": 6_000_000, "video": 12_000_000}[modality]
    stem_params, sharing = stem_row[1], stem_row[2]
    shared_params = stem_params + modality_params
    if sharing == "replicated":
        unique_params = stem_params * cells + head_params * cells + modality_params
        active_flops = stem_params * cells
    else:
        unique_params = shared_params + head_params * cells
        active_flops = stem_params + head_params * cells
    if inference == "recurrent":
        active_flops = int(active_flops * 1.25)
    elif inference == "system2":
        active_flops = int(active_flops * 1.8)
    elif inference == "system2_ndu":
        active_flops = int(active_flops * 2.1)
    if structure == "offline_split":
        unique_params = int(unique_params * 1.05)
    elif structure == "split_merge":
        unique_params = int(unique_params * 1.1)
    return {
        "unique_params": unique_params,
        "weight_bytes_bf16": unique_params * 2,
        "active_flops": active_flops,
        "peak_memory_bytes_lower_bound": unique_params * 2,
        "incremental_cell_params": head_params + (modality_params if cells == 1 else 0),
    }


def enumerate_matrix(cells: int = 32) -> list[dict]:
    if type(cells) is not int or not 1 <= cells <= 4096:
        raise ValueError("cells must be in [1, 4096]")
    records = []
    axes = (STEMS, HEADS, MODALITIES, INFERENCE, STRUCTURES)
    for stem_row, head_row, modality, inference, structure in itertools.product(*axes):
        stem, head = stem_row[0], head_row[0]
        config = dict(stem=stem, head=head, modality=modality,
                      inference=inference, structure=structure, cells=cells)
        resource = resource_estimate(stem, head, modality, inference, structure, cells)
        records.append({
            "schema": "hepta.full-cell-matrix.record.v1",
            "config_id": _digest(config)[:16],
            "config": config,
            "resource_estimate": resource,
            "metrics": {name: None for name in METRICS},
            "status": "planned",
            "efficacy_claim": False,
        })
    return records


def plan(output: Path, *, cells: int = 32, reader_gate: dict | None = None) -> dict:
    gate = evaluate_reader_gate(reader_gate)
    records = enumerate_matrix(cells)
    for record in records:
        record["reader_gate"] = asdict(gate)
        record["status"] = "ready_for_neural_execution" if gate.passed else "blocked_reader_gate"
    output.mkdir(parents=True, exist_ok=True)
    with (output / "matrix-plan.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    summary = {
        "schema": "hepta.full-cell-matrix.summary.v1",
        "planned_records": len(records),
        "recorded_records": len(records),
        "reader_gate": asdict(gate),
        "blocked_records": sum(r["status"] == "blocked_reader_gate" for r in records),
        "ready_records": sum(r["status"] == "ready_for_neural_execution" for r in records),
        "metrics_are_unpopulated": True,
        "neural_calls": 0,
        "production_accepted": False,
        "native_reasoning_superiority": False,
    }
    (output / "run-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print("usage: full_cell_matrix.py OUTPUT [READER_GATE_JSON]", file=sys.stderr)
        return 2
    output = Path(argv[1])
    gate = None
    if len(argv) == 3:
        gate = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    summary = plan(output, reader_gate=gate)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
