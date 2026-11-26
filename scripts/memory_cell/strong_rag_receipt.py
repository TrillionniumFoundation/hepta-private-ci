"""Read-only, exact-answer audit of the sealed strong-RAG experiment.

Run in a separate process after generation. Re-score raw answers and re-run
bounded procedure verification; DO NOT generate text, train, sign semantic
judgments, or replace the original evidence. Full source/archive pins are
checked. The original authored task population is NOT prospective evidence.
"""

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import stat

from event_memory_trial import LIMIT, read
from native import Question, digest
from strong_rag_trial import (
    EVAL_ARMS,
    HISTORIC_COLLECTION_SHA,
    HISTORIC_PLAN_SHA,
    KS,
    SCHEMA,
    _score,
    _stats,
    choose_k,
    chosen_prefix,
    eval_selections,
    file_sha,
    paired,
)

MAX_RESEARCH_BYTES = 128 * 1024 * 1024
VIEW = "hepta.controlled-event.schema-expansion.v1"
SCORER_ONLY = frozenset(
    ("parsed_identifier", "strict_task_success", "required_sources_covered", "procedure_verification")
)


def strict_json(payload):
    def unique(pairs):
        result = {}
        for k, value in pairs:
            if k in result:
                raise ValueError("duplicate JSON field")
            result[k] = value
        return result

    def reject_constant(value):
        raise ValueError(f"nonfinite JSON number: {value}")

    return json.loads(payload, object_pairs_hook=unique, parse_constant=reject_constant)


def verify_manifest(root):
    """Validate the complete archive file census, not just a chosen report."""
    root = root.resolve(strict=True)
    manifest = root / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("missing artifact manifest")
    physical = {}
    size = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("artifact symlink")
        if path.is_dir():
            continue
        if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
            raise ValueError("non-regular artifact")
        rel = path.relative_to(root).as_posix()
        physical[rel] = path
        size += path.stat().st_size
        if size > MAX_RESEARCH_BYTES or len(physical) > 1024:
            raise ValueError("artifact size or count bound")
    pins = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if match is None:
            raise ValueError("invalid sha256 manifest record")
        sha, name = match.groups()
        parts = Path(name)
        if parts.is_absolute() or any(x in ("..", ".") for x in parts.parts):
            raise ValueError("untrusted manifest path")
        if name in pins:
            raise ValueError("duplicate manifest path")
        pins[name] = sha
    if set(pins) != set(physical) - {"SHA256SUMS"} or not pins:
        raise ValueError("artifact manifest missing or extra file")
    for name, pinned in pins.items():
        if file_sha(physical[name]) != pinned:
            raise ValueError(f"artifact changed: {name}")
    return len(pins)


def _json_file(path, *, bound=8 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > bound:
        raise ValueError("invalid bounded artifact")
    return strict_json(path.read_text(encoding="utf-8"))


def _raw_lines(path, *, expected):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("invalid answer journal")
    raw = path.read_text(encoding="utf-8")
    if not raw.endswith("\n"):
        raise ValueError("incomplete fsynced JSONL journal")
    lines = raw.splitlines()
    if len(lines) != expected:
        raise ValueError("raw answer census differs from registered plan")
    rows = [strict_json(line) for line in lines]
    if any(type(row) is not dict for row in rows):
        raise ValueError("answer rows must be objects")
    return rows


def _doc_scope(documents, scope):
    return {row["identity"]: row for row in documents if row["scope"] == scope}


def _check_row(row, case, selected, originals, reader_identity, *, profiles):
    query = case["query"]
    if (
        row["question_id"] != query["identity"]
        or row["kind"] != case["kind"]
        or row["candidate_digest"] != case["candidate_digest"]
        or tuple(row["selected"]) != selected
        or row["status"] not in ("succeeded", "failed")
    ):
        raise ValueError("answer not bound to frozen source/condition")
    if row["status"] == "failed":
        if "answer" in row or "receipt" in row or "citation_audit" in row:
            raise ValueError("failed attempt contains forged generation")
        return
    receipt = row["receipt"]
    if (
        type(row.get("answer")) is not str
        or not row["answer"].strip()
        or receipt["reader_identity"] != reader_identity
        or receipt["view_profile"] != VIEW
        or receipt["query_digest"] != digest(query)
        or receipt["token_limit"] != LIMIT
        or type(receipt["input_tokens"]) is not int
        or not 1 <= receipt["input_tokens"] <= LIMIT
        or type(receipt["generated_tokens"]) is not int
        or not 1 <= receipt["generated_tokens"] <= 64
        or type(receipt["trainable_parameters"]) is not int
        or receipt["trainable_parameters"] != 0
        or receipt["answer_postprocessed"] is not False
        or receipt["production_accepted"] is not False
        or not math.isfinite(receipt["seconds"])
        or not 0 <= receipt["seconds"] <= 21600
        or not re.fullmatch(r"[0-9a-f]{64}", receipt["input_ids_digest"])
        or not re.fullmatch(r"[0-9a-f]{64}", receipt["reader_profile"])
    ):
        raise ValueError("reader/input identity, budget or immutable-base evidence drift")
    profiles.add(receipt["reader_profile"])
    delivered = receipt["delivered_evidence"]
    expanded = receipt["derived_evidence"]
    if len(delivered) != len(selected) or len(expanded) != len(selected):
        raise ValueError("delivered/derived evidence not the selected full originals")
    if digest(expanded) != receipt["derived_view_digest"]:
        raise ValueError("derived source view hash mismatch")
    for i, key in enumerate(selected, 1):
        original = originals[key]
        source, expansion = delivered[i - 1], expanded[i - 1]
        if (
            source["original_id"] != key
            or source["root"] != original["root"]
            or source["scope"] != query["scope"]
            or source["observed_at"] != original["observed_at"]
            or source["source_start"] != 0
            or source["source_end"] != len(original["content"].encode())
            or source["excerpt"] != original["content"]
            or source["source_digest"] != digest(original["content"])
            or source["label"] != f"E{i}"
            or expansion["label"] != f"E{i}"
            or expansion["original_id"] != key
            or expansion["original_digest"] != digest(original["content"])
            or expansion["derivation_profile"] != VIEW
        ):
            raise ValueError("reader received altered, fabricated or shifted source")
        event = strict_json(original["content"])
        prior = ", ".join(event["supersedes"]) or "none explicitly named"
        expected_text = (
            f"Event {event['id']}: at logical revision {event['revision']}, "
            f"entity {event['entity']} has attribute {event['attribute']} "
            f"with value {event['value']}. Superseded event IDs: {prior}. "
            "This is a logical state revision, not a calendar date."
        )
        if expansion["text"] != expected_text:
            raise ValueError("schema expansion is not source-preserving")
    audit = row["citation_audit"]
    request = audit["request"]
    if (
        request["query_id"] != query["identity"]
        or request["scope"] != query["scope"]
        or request["question"] != query["content"]
        or request["question_time"] != query["observed_at"]
        or request["answer"] != row["answer"]
        or request["prompt_digest"] != receipt["input_ids_digest"]
        or audit["judgement"] is not None
        or audit["production_accepted"] is not False
    ):
        raise ValueError("native citation capture detached from original generation")


def _check_scored(raw, scored, labels, expected, arms):
    if len(scored) != len(raw):
        raise ValueError("removed raw attempt")
    for original, row in zip(raw, scored, strict=True):
        if {k: v for k, v in row.items() if k not in SCORER_ONLY} != original:
            raise ValueError("scorer changed original answer, evidence or receipt")
    new = _score(deepcopy(raw), labels, expected=expected, arms=arms)
    for fresh, recorded in zip(new, scored, strict=True):
        base = {k: v for k, v in fresh.items() if k != "procedure_verification"}
        archive = {k: v for k, v in recorded.items() if k != "procedure_verification"}
        if base != archive:
            raise ValueError("published score differs from independent raw-answer replay")
        if "procedure_verification" in recorded:
            a, b = fresh["procedure_verification"], recorded["procedure_verification"]
            for key in ("request", "stdout", "stderr", "exit_code"):
                if a[key] != b[key]:
                    raise ValueError("procedural task output changed under replay")
    return new


def audit(archive, original, *, expected_commit):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_commit):
        raise ValueError("generating source SHA required")
    files = verify_manifest(archive)
    if (archive / "tested-commit.txt").read_text().strip() != expected_commit:
        raise ValueError("archived source does not match generating commit")
    plan = read(original / "plan/plan.json", HISTORIC_PLAN_SHA)
    collection = read(original / "observations/collection.json", HISTORIC_COLLECTION_SHA)
    originals = read(original / "plan/source-view.json", plan["source_view_sha"])
    labels = read(original / "observations/labels.json", collection["files"]["labels.json"])
    documents = {row["identity"]: row for row in originals}
    if len(documents) != len(originals) or len(originals) != 108:
        raise ValueError("original event source changed")
    original_labels = {row["id"]: row for row in labels}
    if len(original_labels) != 16:
        raise ValueError("original fixed labels changed")
    run_cal = _json_file(archive / "calibration/run.json")
    run_eval = _json_file(archive / "evaluation/run.json")
    frozen = _json_file(archive / "calibration/frozen-policy.json")
    cal_plan_path = archive / "prep/calibration-plan.json"
    cal_plan = _json_file(cal_plan_path)
    calib_sources = _json_file(archive / "prep/calibration-sources.json")
    calib_labels = _json_file(archive / "prep/calibration-labels.json")
    inv = _json_file(archive / "inventory.json")
    if (
        cal_plan["schema"] != SCHEMA
        or cal_plan["source_commit"] != expected_commit
        or cal_plan["historical_plan_sha256"] != HISTORIC_PLAN_SHA
        or cal_plan["historical_collection_sha256"] != HISTORIC_COLLECTION_SHA
        or cal_plan["calibration_only"] is not True
        or cal_plan["test_cases_materialized"] is not False
        or tuple(cal_plan["ks"]) != KS
        or tuple(frozen["ks"]) != KS
        or frozen["source_commit"] != expected_commit
        or frozen["calibration_plan_sha256"] != file_sha(cal_plan_path)
        or frozen["original_test_plan_sha256"] != HISTORIC_PLAN_SHA
        or frozen["stage_sha256"] != run_cal["model_stage_sha256"]
        or run_eval["stage_sha256"] != frozen["stage_sha256"]
        or run_eval["policy_sha256"] != file_sha(archive / "calibration/frozen-policy.json")
        or run_cal["source_commit"] != expected_commit
        or run_eval["source_commit"] != expected_commit
        or frozen["reader_identity"] != inv["inventory_digest"]
        or frozen["frozen_before_evaluation"] is not True
        or frozen["candidate_accepted"] is not False
        or frozen["production_accepted"] is not False
        or run_cal["stage"] != "calibration"
        or run_eval["phase"] != "evaluation"
        or run_cal["test_tasks_opened"] is not False
        or run_eval["training_during_query"] is not False
    ):
        raise ValueError("calibration/evaluation lineage, reader or source drift")
    calib_cases = cal_plan["cases"]
    test_cases = plan["cases"]
    calib_ids = [row["query"]["identity"] for row in calib_cases]
    test_ids = [row["query"]["identity"] for row in test_cases]
    if (
        len(calib_ids) != 8 or len(test_ids) != 8
        or len(set(calib_ids) | set(test_ids)) != 16
        or len({row["identity"] for row in calib_sources}) != len(calib_sources)
        or set(x["scope"] for x in calib_sources) != set(calib_ids)
        or set(cal_plan["frozen_indices"]) != set(calib_ids)
        or any(row not in originals for row in calib_sources)
        or set(x["id"] for x in calib_labels) != set(calib_ids)
        or any(x != original_labels[x["id"]] for x in calib_labels)
        or not cal_plan["calibration_only"]
    ):
        raise ValueError("calibrator had a held-out scope or mismatched labels")
    calib_docs = {row["identity"]: row for row in calib_sources}
    phases = (
        ("calibration", calib_cases, calib_docs, calib_labels, tuple(f"k{k}" for k in KS)),
        ("evaluation", test_cases, documents, [original_labels[q] for q in test_ids], EVAL_ARMS),
    )
    result = {}
    profiles = set()
    from native_citation import capture_native

    for stage, cases, source_pool, target, arms in phases:
        path = archive / stage
        questions = [case["query"]["identity"] for case in cases]
        raw = _raw_lines(path / "raw-answers.jsonl", expected=len(cases) * len(arms))
        scored = _json_file(path / "scored-answers.json")
        if (
            len(scored) != len(raw)
            or {(r["question_id"], r["arm"]) for r in raw}
            != {(qid, arm) for qid in questions for arm in arms}
        ):
            raise ValueError("missing, duplicate or changed raw attempts")
        for case in cases:
            qid = case["query"]["identity"]
            selected = (
                {f"k{k}": chosen_prefix(case["candidate_ids"], k) for k in KS}
                if stage == "calibration" else eval_selections(case, frozen["selected_k"])
            )
            scope_docs = _doc_scope(list(source_pool.values()), case["query"]["scope"])
            for row in (r for r in raw if r["question_id"] == qid):
                _check_row(
                    row, case, selected[row["arm"]], scope_docs,
                    inv["inventory_digest"], profiles=profiles,
                )
                if row["status"] == "succeeded":
                    seed = (
                        file_sha(cal_plan_path)
                        if stage == "calibration"
                        else digest((HISTORIC_PLAN_SHA, file_sha(archive / "calibration/frozen-policy.json")))
                    )
                    canonical = capture_native(
                        Question(**case["query"]), row["answer"],
                        dict(
                            input_ids_sha256=row["receipt"]["input_ids_digest"],
                            delivered_evidence=row["receipt"]["delivered_evidence"],
                        ),
                        experiment_digest=digest((seed, row["arm"])),
                        family_digest=digest(case["query"]["family"]),
                    )
                    if canonical != row["citation_audit"]:
                        raise ValueError("citation queue does not match original answer and evidence")
        replay = _check_scored(raw, scored, target, questions, arms)
        summary, groups = _stats(replay, arms, questions)
        if stage == "calibration":
            choice, derived = choose_k(deepcopy(raw), target, questions)
            if (
                choice is None or choice != frozen["selected_k"]
                or summary != derived
                or file_sha(path / "raw-answers.jsonl") != frozen["raw_answers_sha256"]
                or file_sha(path / "scored-answers.json") != frozen["scored_answers_sha256"]
                or _json_file(path / "report.json")["arms"] != summary
            ):
                raise ValueError("frozen k is not derived from original calibration answers")
        else:
            paired_results = {
                "selected_minus_hybrid4": paired(groups, "hybrid_k4", "selected_k"),
                "organized_minus_selected": paired(groups, "selected_k", "organized"),
                "organized_minus_hybrid4": paired(groups, "hybrid_k4", "organized"),
                "reversed_minus_hybrid4": paired(groups, "hybrid_k4", "hybrid_k4_reversed"),
                "hybrid6_minus_hybrid4": paired(groups, "hybrid_k4", "hybrid_k6"),
            }
            report = _json_file(path / "report.json")
            if (
                report["success_by_arm"] != summary
                or report["paired_contrasts"] != paired_results
                or report["selected_k"] != frozen["selected_k"]
                or report["raw_answers_sha256"] != file_sha(path / "raw-answers.jsonl")
                or report["production_accepted"] is not False
            ):
                raise ValueError("test effects are not reproducible from original outputs")
            # Same original evidence and question -> same deterministic prompt IDs.
            for answers in groups.values():
                baseline = answers["hybrid_k4"]
                for arm in ("selected_k", "hybrid_k6", "hybrid_k4_reversed", "organized", "program_support"):
                    other = answers[arm]
                    if (
                        other["selected"] == baseline["selected"]
                        and other["status"] == baseline["status"] == "succeeded"
                        and other["receipt"]["input_ids_digest"] != baseline["receipt"]["input_ids_digest"]
                    ):
                        raise ValueError("identical control sources produced different prompt token IDs")
            result["paired_contrasts"] = paired_results
        result[stage] = dict(
            attempts=len(raw), all_model_calls_succeeded=all(r["status"] == "succeeded" for r in raw),
            strict_success={arm: summary[arm]["strict_success"] for arm in arms},
            original_raw_sha256=file_sha(path / "raw-answers.jsonl"),
        )
    if len(profiles) != 1:
        raise ValueError("model prompt/profile differs across calibration and evaluation")
    return dict(
        schema="hepta.memory-strong-rag-independent-replay.v1",
        generating_commit=expected_commit,
        original_plan_sha256=HISTORIC_PLAN_SHA,
        original_collection_sha256=HISTORIC_COLLECTION_SHA,
        model_identity=inv["inventory_digest"],
        model_profile=next(iter(profiles)),
        verified_artifact_files=files,
        verification="read-only procedure reexecution, source/prompt lineage and exact raw-score/contrast replay",
        independent_semantic_judge=False,
        independent_source_families=0,
        longitudinal_observations=0,
        statistical_superiority=False,
        production_accepted=False,
        **result,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("original_inputs", type=Path)
    parser.add_argument("--generating-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = audit(
        args.archive, args.original_inputs, expected_commit=args.generating_commit
    )
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(receipt, target, indent=2, ensure_ascii=False, allow_nan=False)
        target.write("\n")
    print(json.dumps(receipt, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
