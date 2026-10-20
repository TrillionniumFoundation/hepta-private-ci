"""Read-only decision gate for the exact archived 40+72 Qwen research census.

Cryptographic source binding and reproduced benchmark bookkeeping do NOT issue
human source necessity, semantic entailment, statistical independence, or
production acceptance. This tool performs no inference, training or mutation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memory-cell.verified-strong-rag-research-gate.v1"
GENERATION_COMMIT = "c24fad24b65984a6255a8854c6714c141911ff79"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
MODEL_ID = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
PINS = {
    "original": (
        "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b",
        35,
    ),
    "reader": (
        "2d71f40e553e7d28cad9d8e16803f52b7a99e771b5bf54f55c89bc9468702107",
        38,
    ),
    "replay": (
        "fe710be3f987e34ec3cda48be37509e20a01b48db090907c98ce33cfff198225",
        8,
    ),
}
CAL_ARMS = ("k1", "k2", "k3", "k4", "k6")
TEST_ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "single_hop",
    "entity_time",
    "organized",
    "program_support",
    "empty",
)
SCORER_FIELDS = frozenset(
    (
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    )
)


def _unique(pairs):
    data = {}
    for name, value in pairs:
        if name in data:
            raise ValueError("duplicate JSON property")
        data[name] = value
    return data


def strict_json(data: bytes):
    def invalid(value):
        raise ValueError("nonfinite JSON value: " + value)

    return json.loads(
        data.decode("utf-8"), object_pairs_hook=_unique, parse_constant=invalid
    )


def verified_zip(path: Path, *, kind: str):
    """Check an externally pinned complete ZIP and its whole inner file census."""
    if kind not in PINS or path.is_symlink() or not path.is_file():
        raise ValueError("regular registered archive required")
    expected, count = PINS[kind]
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("archive size bound")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("external immutable archive digest changed")
    with zipfile.ZipFile(path) as z:
        items = z.infolist()
        if (
            len(items) != count + 1
            or sum(x.file_size for x in items) > 64 * 1024 * 1024
        ):
            raise ValueError("archive size or file census changed")
        files = {}
        for item in items:
            pos = PurePosixPath(item.filename)
            if (
                pos.is_absolute()
                or ".." in pos.parts
                or "\\" in item.filename
                or item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16)
                or str(pos) in files
            ):
                raise ValueError("unsafe or duplicate ZIP member")
            files[str(pos)] = z.read(item)
    manifest = files.get("SHA256SUMS")
    if manifest is None:
        raise ValueError("missing inner SHA256SUMS")
    declared = {}
    for line in manifest.decode("ascii").splitlines():
        hit = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if hit is None:
            raise ValueError("invalid SHA256SUMS line")
        digest, name = hit.groups()
        if name in declared:
            raise ValueError("duplicate declared inner file")
        declared[name] = digest
    if set(declared) != set(files) - {"SHA256SUMS"}:
        raise ValueError("inner file population mismatch")
    for name, digest in declared.items():
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise ValueError("invalid original inner file: " + name)
    return files


def _rows(files, phase, arms):
    raw = files[f"{phase}/raw-answers.jsonl"]
    if not raw.endswith(b"\n"):
        raise ValueError("uncommitted final JSONL line")
    received = [strict_json(line) for line in raw.splitlines()]
    scored = strict_json(files[f"{phase}/scored-answers.json"])
    if len(received) != 8 * len(arms) or len(scored) != len(received):
        raise ValueError("incomplete fixed question/arm census")
    ids = {row["question_id"] for row in received}
    if len(ids) != 8 or Counter(
        (r["question_id"], r["arm"]) for r in received
    ) != Counter((qid, arm) for qid in ids for arm in arms):
        raise ValueError("missing, duplicated or unrelated generation")
    for row, scored_row in zip(received, scored, strict=True):
        if row["status"] != "succeeded":
            raise ValueError("unqualified original model call")
        if {k: v for k, v in scored_row.items() if k not in SCORER_FIELDS} != row:
            raise ValueError("original answer, ordered source, or reader was rewritten")
        for key in ("strict_task_success", "required_sources_covered"):
            if type(scored_row.get(key)) is not bool:
                raise ValueError("missing strict scorer field")
        if scored_row["receipt"].get("reader_identity") != MODEL_ID:
            raise ValueError("different pretrained reader")
        if type(scored_row["receipt"].get("input_tokens")) is not int:
            raise ValueError("missing measured prompt cost")
    return received, scored, ids


def _arm_stats(rows, arms):
    grouped = {}
    for arm in arms:
        arm_rows = [r for r in rows if r["arm"] == arm]
        grouped[arm] = dict(
            planned=len(arm_rows),
            strict_success=sum(r["strict_task_success"] for r in arm_rows),
            support_covered=sum(r["required_sources_covered"] for r in arm_rows),
            input_tokens=sum(r["receipt"]["input_tokens"] for r in arm_rows),
            generated_tokens=sum(r["receipt"]["generated_tokens"] for r in arm_rows),
        )
    return grouped


def _check_stats(stats, report, *, field):
    published = report[field]
    if set(published) != set(stats):
        raise ValueError("report arm census changed")
    for arm, observed in stats.items():
        for name, value in observed.items():
            key = "output_tokens" if name == "generated_tokens" else name
            if published[arm].get(key) != value:
                raise ValueError(f"{arm} recorded {key} contradicts original results")


def _pairs(rows, left, right):
    lookup = {(r["question_id"], r["arm"]): r for r in rows}
    ids = sorted({r["question_id"] for r in rows})
    outcomes = [
        (
            lookup[(qid, left)]["strict_task_success"],
            lookup[(qid, right)]["strict_task_success"],
        )
        for qid in ids
    ]
    return dict(
        wins=sum(not a and b for a, b in outcomes),
        losses=sum(a and not b for a, b in outcomes),
        ties=sum(a == b for a, b in outcomes),
    )


def assess_reproduced(
    cal, evaluation, *, frozen_k, loo, citation, replay, policy, source
):
    """Assess reported aggregates; only audit() verifies the original sample census."""
    if (
        source != GENERATION_COMMIT
        or type(frozen_k) is not int
        or frozen_k not in (1, 2, 3, 4, 6)
    ):
        raise ValueError("different frozen experiment")
    for stats, arms in ((cal, CAL_ARMS), (evaluation, TEST_ARMS)):
        if set(stats) != set(arms):
            raise ValueError("incomplete or unregistered arm census")
        for row in stats.values():
            if type(row.get("planned")) is not int or row["planned"] != 8:
                raise ValueError("incomplete planned population")
            if (
                type(row.get("strict_success")) is not int
                or not 0 <= row["strict_success"] <= row["planned"]
                or type(row.get("input_tokens")) is not int
                or row["input_tokens"] < 0
            ):
                raise ValueError("invalid reported outcome or token count")
    chosen = min(
        (int(arm[1:]) for arm in cal),
        key=lambda k: (
            -cal[f"k{k}"]["strict_success"],
            cal[f"k{k}"]["input_tokens"],
            k,
        ),
    )
    if chosen != frozen_k:
        raise ValueError("top-k freeze not derived from real calibration outcomes")
    if (
        loo.get("planned_calibration_questions") != 8
        or len(loo.get("folds", [])) != 8
        or type(loo.get("stable_to_one_calibration_case_removal")) is not bool
    ):
        raise ValueError("missing held-out calibration sensitivity")
    if (
        replay.get("generating_commit") != GENERATION_COMMIT
        or replay.get("production_accepted") is not False
    ):
        raise ValueError("independent replay identity/permission mismatch")
    if (
        policy.get("selected_k") != frozen_k
        or policy.get("production_accepted") is not False
    ):
        raise ValueError("unfrozen or promoted calibration policy")
    if citation.get("planned_attempts") != 72 or citation.get("planned_questions") != 8:
        raise ValueError("incomplete citation control census")
    if set(citation.get("by_arm", {})) != set(TEST_ARMS):
        raise ValueError("missing citation-arm review")
    for arm, x in evaluation.items():
        c = citation["by_arm"][arm]
        if (
            c["attempted"] != 8
            or c["strict_task_success"] != x["strict_success"]
            or not 0
            <= c["correct_with_full_program_declared_citations"]
            <= x["strict_success"]
        ):
            raise ValueError("contradictory formal citation output")
    simple, graph = evaluation["entity_time"], evaluation["organized"]
    c_simple = citation["by_arm"]["entity_time"]
    c_graph = citation["by_arm"]["organized"]
    return dict(
        schema=SCHEMA,
        generating_commit=GENERATION_COMMIT,
        frozen_k=frozen_k,
        reported_calibration_attempts=sum(row["planned"] for row in cal.values()),
        reported_evaluation_attempts=sum(row["planned"] for row in evaluation.values()),
        complete_calibration=None,
        complete_evaluation=None,
        census_verified=False,
        independent_readonly_replay_complete=False,
        authored_question_scope_count=None,
        independent_future_source_families=0,
        full_path_task_success=simple["strict_success"],
        organized_task_success=graph["strict_success"],
        incremental_graph_task_success=(
            graph["strict_success"] - simple["strict_success"]
        ),
        full_path_full_declared_source_citation_success=c_simple[
            "correct_with_full_program_declared_citations"
        ],
        organized_full_declared_source_citation_success=c_graph[
            "correct_with_full_program_declared_citations"
        ],
        incremental_graph_complete_citations=(
            c_graph["correct_with_full_program_declared_citations"]
            - c_simple["correct_with_full_program_declared_citations"]
        ),
        organized_input_tokens_saved=(simple["input_tokens"] - graph["input_tokens"]),
        organized_input_tokens_saved_per_question=(
            simple["input_tokens"] - graph["input_tokens"]
        )
        / 8,
        calibration_leave_one_out_stable=loo["stable_to_one_calibration_case_removal"],
        distinct_calibration_loo_choices=loo.get("distinct_choices"),
        mechanical_citation_coverage_not_semantic_entailment=True,
        independent_semantic_citation_precision=None,
        deployed_total_lifecycle_cost=None,
        graph_task_gain_qualified=False,
        parametric_memory_gain_qualified=False,
        population_superiority_established=False,
        candidate_accepted=False,
        production_accepted=False,
        disposition="NO_GO_on_this_authored_census_for_incremental_graph_accuracy",
        next_gate=(
            "preregistered independent real-source families with same-reader "
            "full-path and tuned-RAG controls, complete source-chain "
            "adjudication, and total-lifecycle cost"
        ),
    )


def audit(original: Path, reader: Path, replay: Path):
    src, generated, independent = (
        verified_zip(original, kind="original"),
        verified_zip(reader, kind="reader"),
        verified_zip(replay, kind="replay"),
    )
    if hashlib.sha256(src["plan/plan.json"]).hexdigest() != PLAN_SHA:
        raise ValueError("original frozen plan changed")
    assert_source = generated["tested-commit.txt"].decode().strip()
    if (
        assert_source != GENERATION_COMMIT
        or independent["auditor-source-commit.txt"].decode().strip()
        != GENERATION_COMMIT
    ):
        raise ValueError("different generating versus auditing source")
    c_raw, c_rows, c_ids = _rows(generated, "calibration", CAL_ARMS)
    e_raw, e_rows, e_ids = _rows(generated, "evaluation", TEST_ARMS)
    if c_ids & e_ids:
        raise ValueError("calibration/test scope overlap")
    cal_report = strict_json(generated["calibration/report.json"])
    test_report = strict_json(generated["evaluation/report.json"])
    policy = strict_json(generated["calibration/frozen-policy.json"])
    separate = strict_json(independent["receipt.json"])
    _check_stats(_arm_stats(c_rows, CAL_ARMS), cal_report, field="arms")
    _check_stats(_arm_stats(e_rows, TEST_ARMS), test_report, field="success_by_arm")
    if (
        cal_report["frozen_k"] != policy["selected_k"]
        or test_report["selected_k"] != policy["selected_k"]
    ):
        raise ValueError("original policy applied inconsistently")
    if (
        policy["source_commit"] != GENERATION_COMMIT
        or policy["original_test_plan_sha256"] != PLAN_SHA
    ):
        raise ValueError("wrong original frozen policy")
    if (
        policy["raw_answers_sha256"]
        != hashlib.sha256(generated["calibration/raw-answers.jsonl"]).hexdigest()
    ):
        raise ValueError("calibration answer pin changed")
    if (
        separate["calibration"]["attempts"] != 40
        or separate["evaluation"]["attempts"] != 72
        or separate["model_identity"] != MODEL_ID
        or separate["original_plan_sha256"] != PLAN_SHA
    ):
        raise ValueError("auditor source or reader mismatch")
    for phase, rows in (("calibration", c_rows), ("evaluation", e_rows)):
        arms = CAL_ARMS if phase == "calibration" else TEST_ARMS
        actual = _arm_stats(rows, arms)
        if separate[phase]["strict_success"] != {
            arm: actual[arm]["strict_success"] for arm in arms
        }:
            raise ValueError("separate replay disagrees with original task scores")
    comparisons = {
        "organized_minus_entity_time": ("entity_time", "organized"),
        "entity_time_minus_single_hop": ("single_hop", "entity_time"),
        "selected_minus_hybrid4": ("hybrid_k4", "selected_k"),
    }
    for name, (left, right) in comparisons.items():
        actual = _pairs(e_rows, left, right)
        published = test_report["paired_contrasts"][name]
        if any(actual[k] != published[k] for k in ("wins", "losses", "ties")):
            raise ValueError("paired effect cannot be replayed from original answers")
    if test_report["formal_citation_chain"] != separate["formal_citation_chain"]:
        raise ValueError("independent formal citation replay mismatch")
    if test_report["same_prompt_consistency"] != separate["same_prompt_consistency"]:
        raise ValueError("independent same-input repeatability replay mismatch")
    decision = assess_reproduced(
        _arm_stats(c_rows, CAL_ARMS),
        _arm_stats(e_rows, TEST_ARMS),
        frozen_k=policy["selected_k"],
        loo=cal_report["calibration_sensitivity"],
        citation=test_report["formal_citation_chain"],
        replay=separate,
        policy=policy,
        source=assert_source,
    )
    decision.update(
        complete_calibration=len(c_raw),
        complete_evaluation=len(e_raw),
        census_verified=True,
        independent_readonly_replay_complete=True,
        authored_question_scope_count=len(e_ids),
    )
    decision["original_plan_sha256"] = PLAN_SHA
    decision["model_inventory_digest"] = MODEL_ID
    decision["outer_artifact_sha256"] = {
        name: PINS[name][0] for name in ("original", "reader", "replay")
    }
    decision["inner_manifest_files_verified"] = sum(
        PINS[name][1] for name in ("original", "reader", "replay")
    )
    decision["original_answers_relabelled"] = False
    return decision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("original_zip", "reader_zip", "replay_zip", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    value = audit(args.original_zip, args.reader_zip, args.replay_zip)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(value, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
