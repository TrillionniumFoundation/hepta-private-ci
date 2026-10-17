"""Exact source-pinned negative admission for actual 32-call LoCoMo Reader study.

Validates original sanitized reports and the published original run/protocol
code blobs, never re-generates logits or promotes any learned memory Cell.
"""

import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = {
    "trial": (
        "frozen_source/locomo_reader_four_regimes.py.source",
        "72ec79ef98f3916c86390db8d8f9725446301ff1",
    ),
    "replay": (
        "frozen_source/locomo_reader_replay.py.source",
        "4da31dfac6f2eb806c252548e719a5107193121a",
    ),
    "report": (
        "data/locomo-eight-root-real-smol135-20261016.json",
        "daea9baf005f489720f4181cc7073d950bf3afaa",
    ),
    "audit": (
        "data/locomo-eight-root-source-replay-20261016.json",
        "1b0dfafe8f4f2fe446cf93c5dac5b66585645b8d",
    ),
}
ARMS = ("empty", "bm25_top3", "annotated_witness", "witness_lesion")
COUNTS = {
    "empty": (497, 153, 0.16666666666666666),
    "bm25_top3": (1720, 192, 0.1),
    "annotated_witness": (1809, 189, 0.1),
    "witness_lesion": (1281, 192, 0.1),
}
RAW_SHA = "1e36a1dcfefabf8d8912b81e215a9e7383bc4eb08a63e2dc592a0b46ce65aab3"
REPORT_SHA = "82aeed889a72597667e6cf613eac48d778f4347a24ca812ee3ff7c2f769d52c6"


def deny(ok, reason):
    if not ok:
        raise ValueError(reason)


def verify_sources(root=HERE):
    for name, (path, blob) in SOURCES.items():
        target = Path(root) / path
        deny(
            target.is_file()
            and not target.is_symlink()
            and 0 < target.stat().st_size < 100000,
            "bounded original Git file required",
        )
        raw = target.read_bytes()
        digest = hashlib.sha1(
            b"blob " + str(len(raw)).encode() + b"\0" + raw
        ).hexdigest()
        deny(digest == blob, "committed source/result bytes changed: " + name)
    return json.loads((Path(root) / SOURCES["report"][0]).read_text()), json.loads(
        (Path(root) / SOURCES["audit"][0]).read_text()
    )


def disposition(original, replay):
    deny(
        original.get("schema") == "hepta.memory.locomo-eight-family-physical-smol135.v1"
        and original.get("real_neural_model_attempts") == 32
        and original.get("successful_neural_model_attempts") == 32
        and original.get("original_raw_journal_sha256") == RAW_SHA
        and original.get("source_json_sha256")
        == "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
        and original.get("original_model_zip_sha256")
        == "07b357cbb3362f4afa4dc1872ab7e28e8a46daaf338f2636fed8d40fbcee76af"
        and original.get("actual_reader_source_git_blob")
        == "c9567b43e5d15ca428baeb3a972b70435bcc7ed7",
        "original physical model or input census relabelled",
    )
    arms = original.get("by_arm")
    deny(
        isinstance(arms, dict) and set(arms) == set(ARMS),
        "four real Reader arms missing",
    )
    for name, (tokens, output, f1_total) in COUNTS.items():
        row = arms[name]
        deny(
            all(
                type(row.get(k)) is int
                for k in (
                    "planned",
                    "model_succeeded",
                    "strict_correct",
                    "structurally_valid_citation",
                    "input_tokens",
                    "output_tokens",
                )
            ),
            "unbounded or invalid experimental metric",
        )
        deny(
            (
                row["planned"],
                row["model_succeeded"],
                row["strict_correct"],
                row["structurally_valid_citation"],
                row["input_tokens"],
                row["output_tokens"],
            )
            == (8, 8, 0, 0, tokens, output),
            "reader task/citation/consumption changed",
        )
        deny(
            type(row.get("token_f1_sum")) in (float, int)
            and math.isclose(row["token_f1_sum"], f1_total, abs_tol=1e-12)
            and math.isclose(
                row["mean_diagnostic_token_f1"], f1_total / 8, abs_tol=1e-12
            ),
            "original diagnostic F1 tampered",
        )
        deny(
            type(row.get("model_wall_seconds")) in (float, int)
            and math.isfinite(row["model_wall_seconds"])
            and row["model_wall_seconds"] > 0,
            "original physical Reader time unbound",
        )
    deny(
        original.get("independent_source_roots_not_authenticated") == 8
        and original.get("original_published_benchmark_preexposed") is True
        and original.get("original_reader_frozen") is True
        and original.get("trained_parameter_memory") is False
        and original.get("reference_stronger_reader_executed") is False
        and original.get("human_semantic_evidence_review") is False
        and original.get("program_execution_tasks") == 0
        and original.get("independent_future_windows") == 0
        and original.get("complete_lifecycle_cost_usd") is None
        and original.get("production_accepted") is False,
        "reader provenance, lifetime or qualification inflated",
    )
    deny(
        replay.get("schema")
        == "hepta.memory.locomo-eight-root-original-independent-replay.v1"
        and replay.get("original_report_sha256") == REPORT_SHA
        and replay.get("raw_journal_sha256") == RAW_SHA
        and replay.get("model_calls_source_replayed") == 32
        and replay.get("original_answer_scores_independently_recomputed") == 32
        and replay.get("original_dialogue_bytes_rechecked") == 32
        and replay.get("new_model_forward_calls") == 0
        and replay.get("original_model_forwards_independently_attested") is False
        and replay.get("prospective_future_source_families") == 0
        and replay.get("independent_sufficiency_judgments") == 0
        and replay.get("real_repository_program_tasks") == 0
        and replay.get("semantic_citation_precision") is None
        and replay.get("complete_lifecycle_cost") is None
        and replay.get("production_accepted") is False
        and replay.get("decision") == "DENY_ALL",
        "source-only independent replay misrepresented as neural/production authority",
    )
    return dict(
        schema="hepta.memory.locomo-actual-32-negative-source-gate.v1",
        executed_physical_reader_calls=32,
        passed_source_only_consistency=True,
        eight_public_preexposed_roots=True,
        task_success_in_all_conditions=0,
        emitted_valid_source_citations_in_all_conditions=0,
        new_neural_calls_in_this_gate=0,
        future_independent_sources=0,
        human_semantic_precision=None,
        parametric_memory_superiority=False,
        qualified_total_cost_usd=None,
        production_accepted=False,
        decision="DENY_ALL",
    )


if __name__ == "__main__":
    print(json.dumps(disposition(*verify_sources()), indent=2, sort_keys=True))
