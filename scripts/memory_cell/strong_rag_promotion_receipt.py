"""Read-only research disposition for one COMPLETED strong-RAG execution.

This module does not run a model, judge semantic entailment, or authorize a
parameter-memory/production switch. The published source ZIPs and exact commit
are pinned independently of report claims. It consumes the successful separate
replay receipt as a reproducibility check, not as an independent human judge.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memory-cell.strong-rag-completed-disposition.v1"
MODEL_ARTIFACT_ID = 11743043427
REPLAY_ARTIFACT_ID = 11748040166
MODEL_ZIP_SHA256 = "7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8"
REPLAY_ZIP_SHA256 = "2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071"
GENERATING_COMMIT = "6304b451268c73f3d1a605985226b102df841bbf"
ARMS = (
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
K = (1, 2, 3, 4, 6)
SCORER_FIELDS = frozenset(
    (
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    )
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(raw):
    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                raise ValueError("duplicate JSON object key")
            out[key] = value
        return out

    def bad(value):
        raise ValueError("nonfinite JSON token: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def checked_archive(path, expected_sha):
    """Validate outer pin, complete inner SHA256SUMS and safe ZIP census."""
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 16 * 1024 * 1024
    ):
        raise ValueError("missing, symlinked or oversized artifact")
    raw = path.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError("artifact ZIP hash differs from externally pinned evidence")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if (
            len(members) < 2
            or len(members) > 96
            or sum(m.file_size for m in members) > 16 * 1024 * 1024
        ):
            raise ValueError("unbounded ZIP entries")
        blobs = {}
        for member in members:
            name = member.filename
            p = PurePosixPath(name)
            if (
                member.is_dir()
                or p.is_absolute()
                or ".." in p.parts
                or "\\" in name
                or str(p) != name
                or name in blobs
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise ValueError("invalid, duplicate or linked artifact member")
            blobs[name] = archive.read(member)
    if "SHA256SUMS" not in blobs:
        raise ValueError("missing complete artifact SHA256SUMS")
    declared = {}
    for line in blobs["SHA256SUMS"].decode("utf-8").splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if not m:
            raise ValueError("malformed artifact SHA256SUMS")
        h, name = m.groups()
        if name in declared:
            raise ValueError("duplicate archive manifest member")
        declared[name] = h
    if set(declared) != set(blobs) - {"SHA256SUMS"}:
        raise ValueError("artifact file census differs from manifest")
    if any(sha(blobs[name]) != h for name, h in declared.items()):
        raise ValueError("artifact member has been replaced")
    return blobs


def load(files, name):
    if name not in files:
        raise ValueError("missing pinned research file " + name)
    return strict_json(files[name].decode("utf-8"))


def rows(files, phase, arms, expected_queries=8):
    prefix = phase + "/"
    raw = [
        strict_json(s)
        for s in files[prefix + "raw-answers.jsonl"].decode().splitlines()
        if s.strip()
    ]
    scored = load(files, prefix + "scored-answers.json")
    if len(raw) != len(scored) or len(raw) != expected_queries * len(arms):
        raise ValueError("incomplete calibration or evaluation census")
    seen, questions = set(), set()
    for before, after in zip(raw, scored, strict=True):
        key = (before.get("question_id"), before.get("arm"))
        if (
            key in seen
            or key[1] not in arms
            or before.get("status") != "succeeded"
            or type(after.get("strict_task_success")) is not bool
            or before != {k: v for k, v in after.items() if k not in SCORER_FIELDS}
        ):
            raise ValueError("raw answer/scored record disagreement")
        seen.add(key)
        questions.add(key[0])
        receipt = before.get("receipt")
        if (
            not isinstance(receipt, dict)
            or type(receipt.get("input_tokens")) is not int
            or receipt["input_tokens"] < 1
        ):
            raise ValueError("missing actual prompt-token measurement")
    if len(questions) != expected_queries or seen != {
        (q, a) for q in questions for a in arms
    }:
        raise ValueError("missing or duplicated source question × arm")
    return scored, questions


def per_arm(scored, arms, citation=None):
    accum = {
        arm: dict(
            planned=0,
            correct=0,
            prompt_tokens=0,
            output_tokens=0,
            seconds=0.0,
            correct_with_complete_declared_citations=0,
            correct_with_event_path=0,
        )
        for arm in arms
    }
    for row in scored:
        v = accum[row["arm"]]
        v["planned"] += 1
        v["correct"] += int(row["strict_task_success"])
        v["prompt_tokens"] += row["receipt"]["input_tokens"]
        v["output_tokens"] += row["receipt"]["generated_tokens"]
        v["seconds"] += row["receipt"]["seconds"]
    if citation is not None:
        if set(citation["by_arm"]) != set(arms) or citation["planned_attempts"] != len(
            scored
        ):
            raise ValueError("incomplete formal citation arm census")
        for arm in arms:
            row = citation["by_arm"][arm]
            v = accum[arm]
            if (
                row["attempted"] != v["planned"]
                or row["strict_task_success"] != v["correct"]
                or row["generations_succeeded"] != v["planned"]
                or row["generations_failed"] != 0
            ):
                raise ValueError(
                    "citation provenance not paired to all original answers"
                )
            c = row["correct_with_full_program_declared_citations"]
            p = row["correct_with_public_event_chain_connected"]
            if any(type(x) is not int or not 0 <= x <= v["correct"] for x in (c, p)):
                raise ValueError("invalid original citation counters")
            v["correct_with_complete_declared_citations"] = c
            v["correct_with_event_path"] = p
    for v in accum.values():
        v["seconds"] = round(v["seconds"], 3)
    return accum


def paired_delta(scored, left, right):
    groups = defaultdict(dict)
    for row in scored:
        if row["arm"] in (left, right):
            groups[row["question_id"]][row["arm"]] = row["strict_task_success"]
    if len(groups) != 8 or any(set(r) != {left, right} for r in groups.values()):
        raise ValueError("incomplete planned paired contrast")
    wins = sum(int(r[right]) > int(r[left]) for r in groups.values())
    losses = sum(int(r[right]) < int(r[left]) for r in groups.values())
    return {
        "wins": wins,
        "losses": losses,
        "ties": 8 - wins - losses,
        "difference_eighths": wins - losses,
    }


def replay_leave_one_out(scored, archived, frozen_choice):
    """Recompute each held-out calibration fold without new reader calls."""
    cases = defaultdict(dict)
    for row in scored:
        cases[row["question_id"]][row["arm"]] = row
    if len(cases) != 8 or any(
        set(r) != {"k" + str(k) for k in K} for r in cases.values()
    ):
        raise ValueError("invalid calibration fold universe")
    chosen_counts = Counter()
    outcomes = Counter()
    archived_folds = {x["omitted_calibration_question"]: x for x in archived["folds"]}
    if set(archived_folds) != set(cases) or len(archived["folds"]) != len(cases):
        raise ValueError("missing or duplicate calibration leave-one-out fold")
    for heldout, fold in cases.items():
        remaining = [r for name, r in cases.items() if name != heldout]

        def rank(k):
            rows = [r["k" + str(k)] for r in remaining]
            return (
                sum(x["strict_task_success"] for x in rows),
                -sum(x["receipt"]["input_tokens"] for x in rows),
                -k,
            )

        choice = max(K, key=rank)
        chosen_counts[str(choice)] += 1
        comparison = int(fold["k" + str(choice)]["strict_task_success"]) - int(
            fold["k4"]["strict_task_success"]
        )
        title = (
            "selected_wins"
            if comparison > 0
            else "selected_losses"
            if comparison < 0
            else "selected_ties"
        )
        outcomes[title] += 1
        declared = archived_folds[heldout]
        if declared["chosen_k_without_that_question"] != choice or declared[
            "heldout_comparison"
        ] != (
            "selected_wins"
            if comparison > 0
            else "selected_loses"
            if comparison < 0
            else "tie"
        ):
            raise ValueError("calibration leave-one-out outcome was revised")
    expected_counts = {str(k): chosen_counts[str(k)] for k in K}
    stable = set(chosen_counts) == {str(frozen_choice)}
    if (
        archived["chosen_k_counts"] != expected_counts
        or archived["stable_to_one_calibration_case_removal"] is not stable
        or archived["selected_wins_over_fixed_k4"] != outcomes["selected_wins"]
        or archived["selected_losses_to_fixed_k4"] != outcomes["selected_losses"]
        or archived["selected_ties_with_fixed_k4"] != outcomes["selected_ties"]
    ):
        raise ValueError("calibration instability not reproducible from real answers")
    return not stable


def qualifying_receipt(model_files, replay_files):
    """Emit a negative/conditional RESEARCH disposition; never promote."""
    if model_files["tested-commit.txt"].decode().strip() != GENERATING_COMMIT:
        raise ValueError("wrong generating source commit")
    if replay_files["auditor-source-commit.txt"].decode().strip() != GENERATING_COMMIT:
        raise ValueError("replay from another source commit")
    report = load(model_files, "evaluation/report.json")
    calibration = load(model_files, "calibration/report.json")
    policy = load(model_files, "calibration/frozen-policy.json")
    replay = load(replay_files, "receipt.json")
    if (
        report["source_commit"] != GENERATING_COMMIT
        or calibration["source_commit"] != GENERATING_COMMIT
        or replay["generating_commit"] != GENERATING_COMMIT
        or policy["source_commit"] != GENERATING_COMMIT
        or policy["frozen_before_evaluation"] is not True
        or replay["verified_artifact_files"] != len(model_files) - 1
        or replay["independent_semantic_judge"] is not False
        or replay["production_accepted"] is not False
        or report["production_accepted"] is not False
        or calibration["production_accepted"] is not False
        or report["independent_source_family_count"] != 0
        or report["statistical_superiority"] is not False
    ):
        raise ValueError("source, reader replay, or research-only boundary differs")
    ev, _ = rows(model_files, "evaluation", ARMS)
    cal, _ = rows(model_files, "calibration", tuple("k" + str(k) for k in K))
    # Freeze decision is recomputed from actual answers rather than the summary.
    cal_stats = per_arm(cal, tuple("k" + str(k) for k in K))
    winner = max(
        K,
        key=lambda k: (
            cal_stats["k" + str(k)]["correct"],
            -cal_stats["k" + str(k)]["prompt_tokens"],
            -k,
        ),
    )
    if (
        winner != policy["selected_k"]
        or winner != report["selected_k"]
        or winner != calibration["frozen_k"]
    ):
        raise ValueError("frozen k not reproducible from actual calibration outputs")
    unstable = replay_leave_one_out(cal, calibration["calibration_sensitivity"], winner)
    citation = report["formal_citation_chain"]
    if citation != replay["formal_citation_chain"]:
        raise ValueError("the separate replay disagrees on formal citation records")
    arms = per_arm(ev, ARMS, citation)
    for arm, measured in arms.items():
        archived = report["success_by_arm"][arm]
        if any(
            (
                archived["planned"] != measured["planned"],
                archived["strict_success"] != measured["correct"],
                archived["input_tokens"] != measured["prompt_tokens"],
                archived["output_tokens"] != measured["output_tokens"],
            )
        ):
            raise ValueError("original report and raw outcomes differ")
        if replay["evaluation"]["strict_success"][arm] != measured["correct"]:
            raise ValueError("replayed task outcome differs")
    if (
        replay["calibration"]["strict_success"]
        != {a: v["correct"] for a, v in cal_stats.items()}
        or replay["calibration"]["attempts"] != 40
        or replay["evaluation"]["attempts"] != 72
        or replay["calibration"]["all_model_calls_succeeded"] is not True
        or replay["evaluation"]["all_model_calls_succeeded"] is not True
    ):
        raise ValueError("replayed calibration/evaluation completion differs")
    if (
        report["raw_answers_sha256"] != sha(model_files["evaluation/raw-answers.jsonl"])
        or calibration["raw_answers_sha256"]
        != sha(model_files["calibration/raw-answers.jsonl"])
        or replay["evaluation"]["original_raw_sha256"] != report["raw_answers_sha256"]
        or replay["calibration"]["original_raw_sha256"]
        != calibration["raw_answers_sha256"]
    ):
        raise ValueError("raw journal identity mismatch")
    effects = {
        "complete_path_vs_single_hop": paired_delta(ev, "single_hop", "entity_time"),
        "organized_vs_complete_path": paired_delta(ev, "entity_time", "organized"),
        "calibrated_topk_vs_fixed_four": paired_delta(ev, "hybrid_k4", "selected_k"),
        "organized_vs_calibrated_topk": paired_delta(ev, "selected_k", "organized"),
    }
    for name, report_key in (
        ("complete_path_vs_single_hop", "entity_time_minus_single_hop"),
        ("organized_vs_complete_path", "organized_minus_entity_time"),
        ("calibrated_topk_vs_fixed_four", "selected_minus_hybrid4"),
        ("organized_vs_calibrated_topk", "organized_minus_selected"),
    ):
        rec = report["paired_contrasts"][report_key]
        for k in ("wins", "losses", "ties"):
            if rec[k] != effects[name][k]:
                raise ValueError("paired contrast not reproduced from actual questions")
    graph_extra_accuracy = effects["organized_vs_complete_path"]["difference_eighths"]
    full_chain = arms["organized"]["correct_with_event_path"]
    return {
        "schema": SCHEMA,
        "research_source_run_id": 38224780900,
        "generating_commit": GENERATING_COMMIT,
        "model_artifact_id": MODEL_ARTIFACT_ID,
        "model_zip_sha256": MODEL_ZIP_SHA256,
        "separate_replay_artifact_id": REPLAY_ARTIFACT_ID,
        "separate_replay_zip_sha256": REPLAY_ZIP_SHA256,
        "planned_real_model_calls": 112,
        "actual_calibration_calls": len(cal),
        "actual_evaluation_calls": len(ev),
        "frozen_calibrated_k": winner,
        "calibration_leave_one_question_out_unstable": unstable,
        "model_identity": replay["model_identity"],
        "all_actual_generations_and_replay_complete": True,
        "by_arm": arms,
        "paired_effects": effects,
        "organized_saved_input_tokens_vs_complete_path": arms["entity_time"][
            "prompt_tokens"
        ]
        - arms["organized"]["prompt_tokens"],
        "organized_extra_correct_over_complete_path": graph_extra_accuracy,
        "organized_correct_with_full_public_path": full_chain,
        "graph_task_accuracy_superiority_on_this_development_set": graph_extra_accuracy
        > 0,
        "calibrated_k_stable_under_loo": not unstable,
        "human_certified_citation_semantics": False,
        "independent_future_source_families": 0,
        "parametric_memory_training_qualified": False,
        "statistical_superiority_established": False,
        "production_accepted": False,
        "research_next_action": "Evaluate frozen-reader evidence selection and complete citation paths on independent source-family tasks; retest k calibration stability before considering parameter-memory learning.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_zip", type=Path)
    parser.add_argument("replay_zip", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    model = checked_archive(args.model_zip, MODEL_ZIP_SHA256)
    replay = checked_archive(args.replay_zip, REPLAY_ZIP_SHA256)
    receipt = qualifying_receipt(model, replay)
    with args.out.open("x", encoding="utf-8") as f:
        json.dump(
            receipt, f, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
        )
        f.write("\n")
    print(
        json.dumps(
            {k: v for k, v in receipt.items() if k not in ("by_arm", "paired_effects")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
