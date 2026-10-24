"""Plan and gate the complete shared-Stem/Cell/System2 research matrix.

The planner records parameter budgets and measurement requirements. It never
turns parameter counts into FLOPs, latency, energy, or task scores. Neural rows
are admitted only with an externally trusted, model-bound Reader gate.
"""

from dataclasses import asdict, dataclass
import hashlib
import itertools
import os
import json
from pathlib import Path
import re
import sys

from reader_review_ledger import audit_case_ledger
from reader_originals_attestation import audit_originals, load_strict_json_file


STEMS = (
    ("small_stem", 150_000_000, "shared", True),
    ("shared_421m", 421_000_000, "shared", False),
    ("shared_421m_plus_head", 421_000_000, "shared", True),
    ("replicated_421m", 421_000_000, "replicated", True),
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
BOUND_FIELDS = ("weights_sha256", "tokenizer_sha256", "prompt_sha256", "dataset_sha256")


@dataclass(frozen=True)
class ReaderGate:
    passed: bool
    reason: str
    cohort_size: int
    human_sufficient_grounded: int
    ordinary_retrieval_grounded: int
    no_evidence_exact_refusal: int
    premise_removed_exact_refusal: int
    model_binding_digest: str | None
    trust_manifest_digest: str | None
    authorized_reviewer_roster_digest: str | None
    original_source_manifest_digest: str | None
    capabilities: dict


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _digest_bytes(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _empty_gate(reason: str) -> ReaderGate:
    return ReaderGate(False, reason, 0, 0, 0, 0, 0, None, None, None, None, {})


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _arm(conditions: dict, name: str, cohort: list[str]) -> tuple[int, int] | None:
    row = conditions.get(name)
    if not isinstance(row, dict) or row.get("item_ids") != cohort:
        return None
    total = row.get("total")
    grounded = row.get("grounded_and_cited")
    refusal = row.get("exact_refusal")
    if (
        type(total) is not int
        or total != len(cohort)
        or any(type(x) is not int or x < 0 or x > total for x in (grounded, refusal))
    ):
        return None
    return grounded, refusal


def evaluate_reader_gate(
    payload: dict | None,
    trust_manifest: dict | None = None,
    *,
    trusted_review_sha256: str | None = None,
    reviewer_roster: dict | None = None,
    trusted_roster_sha256: str | None = None,
    original_sources: dict | None = None,
    trusted_originals_sha256: str | None = None,
) -> ReaderGate:
    """Derive the four-arm admission decision from an external v2 receipt.

    Receipt and manifest cannot attest to their own independence. An
    operator-provided OUT-OF-BAND review-manifest SHA is mandatory. The
    preapproved manifest must also bind every reviewed cohort, arm count,
    model identity and claimed capability. Reviewer ID strings are NOT proof
    of human identity: at least two Ed25519 signatures from separate public
    keys in an independently operator-pinned reviewer roster are required.
    Absent external authorization and actual reviewed results, rows stay blocked.
    """
    if not isinstance(payload, dict) or payload.get("schema") != "hepta.reader-gate.v2":
        return _empty_gate("missing-or-unknown-reader-gate")
    cohort = payload.get("cohort")
    conditions = payload.get("conditions")
    binding = payload.get("model_binding")
    review = payload.get("independent_review")
    capabilities = payload.get("capabilities")
    if (
        type(cohort) is not list
        or not cohort
        or len(cohort) > 10000
        or any(type(item) is not str or not item for item in cohort)
        or len(set(cohort)) != len(cohort)
    ):
        return _empty_gate("invalid-reader-cohort")
    if (
        not isinstance(conditions, dict)
        or not isinstance(binding, dict)
        or not isinstance(review, dict)
    ):
        return _empty_gate("reader-gate-fields-missing")
    if any(not _valid_sha(binding.get(field)) for field in BOUND_FIELDS):
        return _empty_gate("reader-model-binding-incomplete")
    if not isinstance(binding.get("revision"), str) or not binding["revision"]:
        return _empty_gate("reader-revision-missing")
    if (
        type(binding.get("decode_budget")) is not int
        or not 1 <= binding["decode_budget"] <= 65536
    ):
        return _empty_gate("reader-decode-budget-invalid")
    rows = {
        name: _arm(conditions, name, cohort)
        for name in (
            "no_evidence",
            "ordinary_retrieval",
            "human_sufficient",
            "critical_premise_removed",
        )
    }
    if any(value is None for value in rows.values()):
        return _empty_gate("reader-arm-denominator-or-cohort-mismatch")
    if not isinstance(capabilities, dict) or any(
        not isinstance(capabilities.get(key), list)
        or not capabilities[key]
        or any(
            type(value) is not str or value not in allowed
            for value in capabilities[key]
        )
        or len(set(capabilities[key])) != len(capabilities[key])
        for key, allowed in (("modalities", MODALITIES), ("inference", INFERENCE))
    ):
        return _empty_gate("invalid-reader-capabilities")
    if not isinstance(trust_manifest, dict) or not _valid_sha(
        review.get("trust_manifest_sha256")
    ):
        return _empty_gate("external-trust-manifest-required")
    # A self-referential pair of hashes is not an external trust root.
    if not _valid_sha(trusted_review_sha256):
        return _empty_gate("out-of-band-trust-pin-required")
    manifest_digest = _digest_bytes(trust_manifest)
    if (
        manifest_digest != review["trust_manifest_sha256"]
        or trust_manifest.get("schema") != "hepta.reader.trust.v1"
    ):
        return _empty_gate("trust-manifest-digest-or-schema-mismatch")
    if manifest_digest != trusted_review_sha256:
        return _empty_gate("out-of-band-trust-pin-mismatch")
    # Aggregate-only attestations do not establish per-question correctness.
    # Require the complete source-bound review ledger IN the signed content.
    if "reviewed_items" not in payload:
        return _empty_gate("missing-case-level-review-ledger")
    reviewed_content = {
        name: payload[name]
        for name in (
            "schema",
            "cohort",
            "model_binding",
            "conditions",
            "capabilities",
            "reviewed_items",
        )
    }
    if trust_manifest.get("reviewed_gate_content_sha256") != _digest_bytes(
        reviewed_content
    ):
        return _empty_gate("review-not-bound-to-observed-reader-results")
    reviewers = trust_manifest.get("independent_reviewers")
    if (
        not isinstance(reviewers, list)
        or len(reviewers) < 2
        or any(
            not isinstance(item, dict)
            or type(item.get("id")) is not str
            or not item["id"]
            or item.get("revoked") is not False
            for item in reviewers
        )
        or len({item["id"] for item in reviewers}) != len(reviewers)
    ):
        return _empty_gate("no-current-independent-reviewer-in-trust-manifest")
    if not isinstance(reviewer_roster, dict) or not _valid_sha(trusted_roster_sha256):
        return _empty_gate("out-of-band-reviewer-roster-required")
    roster_digest = _digest_bytes(reviewer_roster)
    if (
        roster_digest != trusted_roster_sha256
        or trust_manifest.get("authorized_reviewer_roster_sha256") != roster_digest
    ):
        return _empty_gate("reviewer-roster-pin-mismatch")
    if reviewer_roster.get("schema") != "hepta.reader.authorized-reviewers.v1":
        return _empty_gate("invalid-authorized-reviewer-roster")
    roster = reviewer_roster.get("reviewers")
    if (
        not isinstance(roster, list)
        or len(roster) < 2
        or any(
            not isinstance(item, dict)
            or type(item.get("id")) is not str
            or not item["id"]
            or type(item.get("public_key_hex")) is not str
            or re.fullmatch(r"[0-9a-f]{64}", item["public_key_hex"]) is None
            or item.get("authorized") is not True
            or item.get("independent_of_model_owner") is not True
            or item.get("independent_of_dataset_owner") is not True
            for item in roster
        )
    ):
        return _empty_gate("invalid-authorized-reviewer-roster")
    roster_keys = {entry["id"]: entry["public_key_hex"] for entry in roster}
    if len(roster_keys) != len(roster) or len(set(roster_keys.values())) != len(roster):
        return _empty_gate("duplicated-authorized-reviewer-key")
    if (
        any(
            type(entry.get("signature_hex")) is not str
            or re.fullmatch(r"[0-9a-f]{128}", entry["signature_hex"]) is None
            or entry["id"] not in roster_keys
            for entry in reviewers
        )
        or len({roster_keys[entry["id"]] for entry in reviewers}) < 2
    ):
        return _empty_gate("missing-or-unauthorized-reviewer-signature")
    # Domain-separated signatures bind the exact graded cohort, four-arm
    # answers, model and capabilities, never a reviewer ID alone. The roster
    # and review manifest must be pinned through TWO out-of-band owner inputs.
    signed_message = b"hepta.reader-gate.v2.ed25519\x00" + bytes.fromhex(
        trust_manifest["reviewed_gate_content_sha256"]
    )
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        return _empty_gate("signature-verifier-unavailable")
    try:
        for entry in reviewers:
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(roster_keys[entry["id"]])
            ).verify(bytes.fromhex(entry["signature_hex"]), signed_message)
    except (InvalidSignature, ValueError, TypeError):
        return _empty_gate("reviewer-signature-verification-failed")
    # Cryptographic trust is necessary but insufficient: derive every numeric
    # summary count from one signed, provenance-bound human verdict per item.
    ledger_error = audit_case_ledger(cohort, conditions, payload["reviewed_items"])
    if ledger_error is not None:
        return _empty_gate(ledger_error)
    # A signed case-ledger is not itself evidence the ORIGINAL answer/source
    # bytes existed. Independently pin the original producer's complete
    # question, token-ID, answer and UTF-8 byte-window package, then replay
    # the per-case fingerprints and the model's literal bracket citations.
    if not isinstance(original_sources, dict) or not _valid_sha(
        trusted_originals_sha256
    ):
        return _empty_gate("out-of-band-originals-required")
    original_digest = _digest_bytes(original_sources)
    if (
        original_digest != trusted_originals_sha256
        or trust_manifest.get("originals_sha256") != original_digest
    ):
        return _empty_gate("original-evidence-pin-mismatch")
    originals_error = audit_originals(
        cohort, binding, payload["reviewed_items"], original_sources
    )
    if originals_error is not None:
        return _empty_gate(originals_error)
    human_grounded, _ = rows["human_sufficient"]
    ordinary_grounded, _ = rows["ordinary_retrieval"]
    _, empty_refusal = rows["no_evidence"]
    _, removed_refusal = rows["critical_premise_removed"]
    total = len(cohort)
    passed = (
        human_grounded / total >= 0.75
        and human_grounded > ordinary_grounded
        and empty_refusal / total >= 0.90
        and removed_refusal / total >= 0.90
    )
    reason = "passed" if passed else "reader-adequacy-rate-gate-not-met"
    model_digest = _digest(binding)
    return ReaderGate(
        passed,
        reason,
        total,
        human_grounded,
        ordinary_grounded,
        empty_refusal,
        removed_refusal,
        model_digest,
        manifest_digest,
        roster_digest,
        original_digest,
        capabilities if isinstance(capabilities, dict) else {},
    )


def resource_estimate(
    stem: str, head: str, modality: str, inference: str, structure: str, cells: int
) -> dict:
    stem_row = next(row for row in STEMS if row[0] == stem)
    head_params = next(row[1] for row in HEADS if row[0] == head)
    modality_params = {
        "text": 500_000,
        "image": 8_000_000,
        "audio": 6_000_000,
        "video": 12_000_000,
    }[modality]
    stem_params, sharing, cell_trainable = stem_row[1], stem_row[2], stem_row[3]
    per_cell = head_params if cell_trainable else 0
    if sharing == "replicated":
        unique_params = stem_params * cells + modality_params + per_cell * cells
        incremental = stem_params + per_cell
    else:
        unique_params = stem_params + modality_params + per_cell * cells
        incremental = per_cell
    return {
        "parameter_budget": {
            "unique_parameters": unique_params,
            "shared_stem_parameters": stem_params if sharing == "shared" else 0,
            "replicated_stem_parameters": stem_params * cells
            if sharing == "replicated"
            else 0,
            "modality_adapter_parameters": modality_params,
            "cell_head_parameters": per_cell,
            "incremental_cell_parameters": incremental,
        },
        "weight_bytes_bf16_nominal": unique_params * 2,
        "active_flops": None,
        "peak_memory_bytes": None,
        "energy_joules": None,
        "measurement_requirements": [
            "tokens_or_frames_and_batch_size",
            "actual_route_count_and_active_cells",
            "profiler_or_graph_op_count",
            "peak_allocator_memory_and_device_power",
        ],
    }


def enumerate_matrix(cells: int = 32) -> list[dict]:
    if type(cells) is not int or not 1 <= cells <= 4096:
        raise ValueError("cells must be in [1, 4096]")
    records = []
    for stem_row, head_row, modality, inference, structure in itertools.product(
        STEMS, HEADS, MODALITIES, INFERENCE, STRUCTURES
    ):
        stem, head = stem_row[0], head_row[0]
        config = dict(
            stem=stem,
            head=head,
            modality=modality,
            inference=inference,
            structure=structure,
            cells=cells,
            stem_training_policy="frozen" if not stem_row[3] else "cell_delta",
        )
        records.append(
            {
                "schema": "hepta.full-cell-matrix.record.v2",
                "config_id": _digest(config)[:16],
                "config": config,
                "resource_estimate": resource_estimate(
                    stem, head, modality, inference, structure, cells
                ),
                "metrics": {name: None for name in METRICS},
                "status": "planned",
                "efficacy_claim": False,
            }
        )
    return records


def _capability_allows(gate: ReaderGate, record: dict) -> bool:
    capabilities = gate.capabilities
    modalities = capabilities.get("modalities", [])
    inference = capabilities.get("inference", [])
    return (
        record["config"]["modality"] in modalities
        and record["config"]["inference"] in inference
    )


def plan(
    output: Path,
    *,
    cells: int = 32,
    reader_gate: dict | None = None,
    trust_manifest: dict | None = None,
    trusted_review_sha256: str | None = None,
    reviewer_roster: dict | None = None,
    trusted_roster_sha256: str | None = None,
    original_sources: dict | None = None,
    trusted_originals_sha256: str | None = None,
) -> dict:
    gate = evaluate_reader_gate(
        reader_gate,
        trust_manifest,
        trusted_review_sha256=trusted_review_sha256,
        reviewer_roster=reviewer_roster,
        trusted_roster_sha256=trusted_roster_sha256,
        original_sources=original_sources,
        trusted_originals_sha256=trusted_originals_sha256,
    )
    records = enumerate_matrix(cells)
    for record in records:
        record["reader_gate"] = asdict(gate)
        if not gate.passed:
            record["status"] = "blocked_reader_gate"
        elif not _capability_allows(gate, record):
            record["status"] = "blocked_capability_binding"
        else:
            record["status"] = "planned_neural_execution"
    output.mkdir(parents=True, exist_ok=True)
    with (output / "matrix-plan.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
            )
    summary = {
        "schema": "hepta.full-cell-matrix.summary.v2",
        "planned_records": len(records),
        "recorded_records": len(records),
        "reader_gate": asdict(gate),
        "blocked_reader_records": sum(
            r["status"] == "blocked_reader_gate" for r in records
        ),
        "blocked_capability_records": sum(
            r["status"] == "blocked_capability_binding" for r in records
        ),
        "planned_neural_records": sum(
            r["status"] == "planned_neural_execution" for r in records
        ),
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
    if len(argv) not in (2, 3, 4, 5, 6):
        print(
            "usage: full_cell_matrix.py OUTPUT [READER_GATE_JSON TRUST_MANIFEST_JSON AUTHORIZED_ROSTER_JSON ORIGINAL_SOURCE_MANIFEST_JSON]",
            file=sys.stderr,
        )
        return 2
    gate = load_strict_json_file(Path(argv[2])) if len(argv) >= 3 else None
    trust = load_strict_json_file(Path(argv[3])) if len(argv) >= 4 else None
    roster = load_strict_json_file(Path(argv[4])) if len(argv) >= 5 else None
    originals = (
        load_strict_json_file(
            Path(argv[5]),
            expected_file_sha256=os.environ.get("HEPTA_READER_ORIGINALS_FILE_SHA256")
            or None,
            require_pin=True,
        )
        if len(argv) == 6
        else None
    )
    summary = plan(
        Path(argv[1]),
        reader_gate=gate,
        trust_manifest=trust,
        trusted_review_sha256=os.environ.get("HEPTA_READER_TRUST_SHA256") or None,
        reviewer_roster=roster,
        trusted_roster_sha256=os.environ.get("HEPTA_REVIEWER_ROSTER_SHA256") or None,
        original_sources=originals,
        trusted_originals_sha256=os.environ.get("HEPTA_READER_ORIGINALS_SHA256")
        or None,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
