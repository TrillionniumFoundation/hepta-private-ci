"""Read-only independent disposition of a fully generated, pinned strong-RAG trial.

No model calls or training. All metrics are derived from immutable archives and
strict original raw vs scored records, not from a generated outcome summary.
Program worker execution and source-chain semantics were separately replayed in
the original read-only GitHub job; this tool verifies their persisted results.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from itertools import combinations
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

EXPECTED = {
    "original": "23e9d44b8d2dbe756c7c33031e18853c83326458a37925d4d368881145bf142b",
    "model": "7a99db30fb5b1202fcd43073d22589b84315046dd34044277cc46351f1cbece8",
    "replay": "2445895a7d51e3173837471aa462cebede29eb3ec89653af3bd17e73b6114071",
}
SOURCE_COMMIT = "6304b451268c73f3d1a605985226b102df841bbf"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
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
KS = (1, 2, 3, 4, 6)
SCORER_FIELDS = frozenset(
    {
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    }
)
IDENTIFIER = re.compile(
    r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*"
)
CITATIONS = re.compile(r"\[E[1-9][0-9]*\]")


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def bad(value):
        raise ValueError("nonfinite JSON constant " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=bad)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode()
    ).hexdigest()


def open_verified(path, *, expected_sha):
    """Reject mutated, extra, absent, path-traversing or unlisted archive data."""
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size > 32 * 1024 * 1024
    ):
        raise ValueError("archive must be a bounded regular file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError("outer archive SHA256 differs")
    z = zipfile.ZipFile(path)
    try:
        entries = z.infolist()
        names = [x.filename for x in entries]
        if (
            not 1 <= len(names) <= 256
            or len(set(names)) != len(names)
            or "SHA256SUMS" not in names
        ):
            raise ValueError("invalid archive census")
        if sum(x.file_size for x in entries) > 24 * 1024 * 1024:
            raise ValueError("archive uncompressed budget exceeded")
        for entry in entries:
            parts = PurePosixPath(entry.filename)
            if (
                entry.is_dir()
                or parts.is_absolute()
                or ".." in parts.parts
                or "\\" in entry.filename
            ):
                raise ValueError("untrusted archive path")
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("archive symlink")
        declared = {}
        for line in z.read("SHA256SUMS").decode().splitlines():
            matched = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if not matched:
                raise ValueError("malformed hash manifest")
            sha, name = matched.groups()
            if name in declared:
                raise ValueError("duplicate hash entry")
            declared[name] = sha
        if set(declared) != set(names) - {"SHA256SUMS"}:
            raise ValueError("unlisted or missing archive member")
        for name, sha in declared.items():
            if hashlib.sha256(z.read(name)).hexdigest() != sha:
                raise ValueError("inner archive member differs: " + name)
        return z, {"zip_sha256": expected_sha, "verified_members": len(declared)}
    except BaseException:
        z.close()
        raise


def get_json(z, name):
    return strict_json(z.read(name).decode())


def raw_rows(z, phase):
    raw = z.read(phase + "/raw-answers.jsonl").decode().splitlines()
    return [strict_json(line) for line in raw]


def validate_answers(phase, cases, source_rows, raw, scored, labels, arms, selection):
    """Reconstruct strict score, delivered source identities and full cited support."""
    expected = {(case["query"]["identity"], arm) for case in cases for arm in arms}
    keys = [(x["question_id"], x["arm"]) for x in raw]
    if (
        len(raw) != len(expected)
        or len(set(keys)) != len(keys)
        or set(keys) != expected
    ):
        raise ValueError("incomplete or duplicate raw model attempts")
    if len(scored) != len(raw):
        raise ValueError("scorer dropped answers")
    by_case = {x["query"]["identity"]: x for x in cases}
    if len(by_case) != len(cases):
        raise ValueError("duplicate original task")
    by_source = {x["identity"]: x for x in source_rows}
    if len(by_source) != len(source_rows):
        raise ValueError("duplicate original source")
    by_label = {x["id"]: x for x in labels}
    if set(by_label) != set(by_case):
        raise ValueError("misaligned held-out labels")
    counts = defaultdict(
        lambda: dict(
            success=0,
            full_citation=0,
            prompt_tokens=0,
            generated_tokens=0,
            seconds=0.0,
            full_support_delivered=0,
        )
    )
    group = defaultdict(dict)
    for original, row in zip(raw, scored, strict=True):
        if {k: v for k, v in row.items() if k not in SCORER_FIELDS} != original:
            raise ValueError("scorer altered original answer or receipt")
        qid, arm = row["question_id"], row["arm"]
        case, truth = by_case[qid], by_label[qid]
        expected_selection = selection(case, arm)
        if row["status"] != "succeeded" or tuple(row["selected"]) != tuple(
            expected_selection
        ):
            raise ValueError("failed model call or changed evidence selection")
        if (
            row["candidate_digest"] != case["candidate_digest"]
            or digest(tuple(case["candidate_ids"])) != case["candidate_digest"]
        ):
            raise ValueError("candidate ranking drift")
        receipt = row["receipt"]
        delivered = receipt["delivered_evidence"]
        if [r["original_id"] for r in delivered] != row["selected"]:
            raise ValueError("original delivered evidence differs")
        for i, source in enumerate(delivered):
            doc = by_source[source["original_id"]]
            if (
                source["label"] != f"E{i + 1}"
                or source["root"] != doc["root"]
                or source["scope"] != doc["scope"]
                or source["excerpt"] != doc["content"]
                or source["source_start"] != 0
                or source["source_end"] != len(doc["content"].encode())
                or source["source_digest"] != digest(doc["content"])
            ):
                raise ValueError("original evidence text or byte offsets differ")
        citation_request = row["citation_audit"]["request"]
        if (
            citation_request["answer"] != row["answer"]
            or citation_request["prompt_digest"] != receipt["input_ids_digest"]
            or citation_request["query_id"] != qid
            or citation_request["question"] != case["query"]["content"]
            or len(citation_request["sources"]) != len(delivered)
        ):
            raise ValueError("citation request detached from generated answer")
        for a, b in zip(citation_request["sources"], delivered, strict=True):
            if (
                a["label"] != b["label"]
                or a["id"] != b["id"]
                or a["excerpt"] != b["excerpt"]
            ):
                raise ValueError("citation request altered source identity")
        parsed = IDENTIFIER.fullmatch(row["answer"])
        value = parsed.group(1) if parsed else None
        if value != row["parsed_identifier"]:
            raise ValueError("strict response parser drift")
        correct = value == truth["expected"]
        if truth["kind"] == "procedure":
            verification = row["procedure_verification"]
            if verification["request"] != dict(
                operation="execute",
                recipe=truth["procedure"],
                supplied=value or "invalid_response",
            ):
                raise ValueError("procedure worker input drift")
            correct = verification["exit_code"] == 0
        if bool(row["strict_task_success"]) is not correct:
            raise ValueError("task success changed after generation")
        covered = set(truth["support"]).issubset(row["selected"])
        if bool(row["required_sources_covered"]) is not covered:
            raise ValueError("source coverage mismatch")
        markers = CITATIONS.findall(row["answer"])
        cited = {
            delivered[int(label[2:-1]) - 1]["original_id"]
            for label in markers
            if int(label[2:-1]) <= len(delivered)
        }
        if any(int(label[2:-1]) > len(delivered) for label in markers):
            raise ValueError("invented citation label")
        stats = counts[arm]
        stats["success"] += correct
        stats["full_citation"] += correct and set(truth["support"]).issubset(cited)
        stats["full_support_delivered"] += covered
        for col, field in [
            ("prompt_tokens", "input_tokens"),
            ("generated_tokens", "generated_tokens"),
            ("seconds", "seconds"),
        ]:
            val = receipt[field]
            if (
                isinstance(val, bool)
                or not isinstance(val, (int, float))
                or not math.isfinite(val)
                or val < 0
            ):
                raise ValueError("invalid reader resource cost")
            stats[col] += val
        if (
            receipt["trainable_parameters"] != 0
            or receipt["production_accepted"] is not False
        ):
            raise ValueError("reader was not declared frozen and research-only")
        group[qid][arm] = row
    return dict(counts), group


def evaluate(original_path, model_path, replay_path):
    handles = []
    try:
        files = {}
        for key, path in (
            ("original", original_path),
            ("model", model_path),
            ("replay", replay_path),
        ):
            z, facts = open_verified(path, expected_sha=EXPECTED[key])
            handles.append(z)
            files[key] = (z, facts)
        original, model, replay = (files[k][0] for k in ("original", "model", "replay"))
        if model.read("tested-commit.txt").decode().strip() != SOURCE_COMMIT:
            raise ValueError("model result belongs to a different commit")
        if replay.read("auditor-source-commit.txt").decode().strip() != SOURCE_COMMIT:
            raise ValueError("replayer source revision differs")
        oracle = get_json(original, "observations/labels.json")
        frozen = get_json(original, "plan/plan.json")
        if hashlib.sha256(original.read("plan/plan.json")).hexdigest() != PLAN_SHA:
            raise ValueError("original frozen test plan changed")
        final_cases = frozen["cases"]
        calibration_plan = get_json(model, "prep/calibration-plan.json")
        calibration_cases = calibration_plan["cases"]
        if not (
            len(final_cases) == len(calibration_cases) == 8
            and not {x["query"]["identity"] for x in final_cases}
            & {x["query"]["identity"] for x in calibration_cases}
        ):
            raise ValueError("calibration/evaluation partitions overlap")
        original_sources = get_json(original, "plan/source-view.json")
        calib_sources = get_json(model, "prep/calibration-sources.json")
        if not set(x["scope"] for x in calib_sources).isdisjoint(
            {x["query"]["scope"] for x in final_cases}
        ):
            raise ValueError("test source exposed to calibrator")
        raw_cal, scored_cal = (
            raw_rows(model, "calibration"),
            get_json(model, "calibration/scored-answers.json"),
        )
        raw_eval, scored_eval = (
            raw_rows(model, "evaluation"),
            get_json(model, "evaluation/scored-answers.json"),
        )
        label_map = {l["id"]: l for l in oracle}
        frozen_policy = get_json(model, "calibration/frozen-policy.json")
        selected_k = frozen_policy["selected_k"]
        if selected_k not in KS or frozen_policy["source_commit"] != SOURCE_COMMIT:
            raise ValueError("frozen calibration policy source mismatch")
        single_hop = get_json(model, "evaluation/single-hop-control.json")
        first_hops = {
            x["question_id"]: x["first_hop"] for x in single_hop["test_cases"]
        }
        if (
            len(first_hops) != 8
            or single_hop["source_selection_used_test_labels"] is not False
        ):
            raise ValueError("single-hop selection not frozen independently")

        def calibration_selection(case, arm):
            return case["candidate_ids"][: int(arm[1:])]

        def final_selection(case, arm):
            ids = case["candidate_ids"]
            return {
                "selected_k": ids[:selected_k],
                "hybrid_k4": ids[:4],
                "hybrid_k6": ids[:6],
                "hybrid_k4_reversed": list(reversed(ids[:4])),
                "single_hop": first_hops[case["query"]["identity"]],
                "entity_time": case["controls"]["entity_time"]["selected"],
                "organized": case["controls"]["organized"]["selected"],
                "program_support": case["controls"]["program_support"]["selected"],
                "empty": [],
            }[arm]

        stats_cal, _ = validate_answers(
            "calibration",
            calibration_cases,
            calib_sources,
            raw_cal,
            scored_cal,
            [label_map[x["query"]["identity"]] for x in calibration_cases],
            tuple("k" + str(k) for k in KS),
            calibration_selection,
        )
        stats_test, groups = validate_answers(
            "evaluation",
            final_cases,
            original_sources,
            raw_eval,
            scored_eval,
            [label_map[x["query"]["identity"]] for x in final_cases],
            ARMS,
            final_selection,
        )
        calibration_report = get_json(model, "calibration/report.json")
        evaluation_report = get_json(model, "evaluation/report.json")
        winner = max(
            KS,
            key=lambda k: (
                stats_cal[f"k{k}"]["success"],
                -stats_cal[f"k{k}"]["prompt_tokens"],
                -k,
            ),
        )
        if selected_k != winner or winner != calibration_report["frozen_k"]:
            raise ValueError("chosen top-k was not calibrated from original answers")
        for label, got, published in [
            ("calibration", stats_cal, calibration_report["arms"]),
            ("evaluation", stats_test, evaluation_report["success_by_arm"]),
        ]:
            for arm, v in got.items():
                o = published[arm]
                if (
                    v["success"] != o["strict_success"]
                    or v["full_support_delivered"] != o["support_covered"]
                    or v["prompt_tokens"] != o["input_tokens"]
                    or v["generated_tokens"] != o["output_tokens"]
                    or not math.isclose(
                        v["seconds"], o["inference_seconds"], abs_tol=1e-6
                    )
                ):
                    raise ValueError(label + " published statistics differ: " + arm)
        formal = evaluation_report["formal_citation_chain"]["by_arm"]
        for arm, got in stats_test.items():
            if (
                formal[arm]["strict_task_success"] != got["success"]
                or formal[arm]["correct_with_full_program_declared_citations"]
                != got["full_citation"]
            ):
                raise ValueError("citation result differs from original cited evidence")
        replay_report = get_json(replay, "receipt.json")
        if (
            replay_report["generating_commit"] != SOURCE_COMMIT
            or replay_report["evaluation"]["attempts"] != 72
            or replay_report["calibration"]["attempts"] != 40
            or replay_report["production_accepted"] is not False
            or replay_report["independent_semantic_judge"] is not False
        ):
            raise ValueError("independent read-only receipt does not match source")
        pairs = {}
        for title, left, right in (
            ("selected_minus_hybrid4", "hybrid_k4", "selected_k"),
            ("entity_time_minus_single_hop", "single_hop", "entity_time"),
            ("organized_minus_entity_time", "entity_time", "organized"),
            ("organized_minus_selected", "selected_k", "organized"),
        ):
            wins = sum(
                not gs[left]["strict_task_success"] and gs[right]["strict_task_success"]
                for gs in groups.values()
            )
            losses = sum(
                gs[left]["strict_task_success"] and not gs[right]["strict_task_success"]
                for gs in groups.values()
            )
            observed = evaluation_report["paired_contrasts"][title]
            if (wins, losses) != (observed["wins"], observed["losses"]):
                raise ValueError("paired effect mismatch: " + title)
            pairs[title] = dict(
                wins=wins,
                losses=losses,
                ties=8 - wins - losses,
                observed_delta=(wins - losses) / 8,
            )
        same_prompt_pairs = 0
        for rows in groups.values():
            for a, b in combinations(rows.values(), 2):
                if a["selected"] == b["selected"]:
                    same_prompt_pairs += 1
                    for key in ("input_ids_digest", "generated_ids_digest"):
                        if a["receipt"][key] != b["receipt"][key]:
                            raise ValueError(
                                "identical input generated inconsistent output"
                            )
        if (
            same_prompt_pairs
            != evaluation_report["same_prompt_consistency"][
                "observed_identical_prompt_pairs"
            ]
        ):
            raise ValueError("repeatability census changed")
        chosen_calibration_by_fold = calibration_report["calibration_sensitivity"][
            "chosen_k_counts"
        ]
        if (
            calibration_report["calibration_sensitivity"][
                "stable_to_one_calibration_case_removal"
            ]
            is not False
        ):
            raise ValueError("prematurely accepted unstable k")
        return {
            "schema": "hepta.memorycell.strong-rag.actual-disposition.v1",
            "source_commit": SOURCE_COMMIT,
            "workflow_run": 38224780900,
            "source_archive": dict(files["original"][1], artifact_id=11669174727),
            "model_archive": dict(files["model"][1], artifact_id=11743043427),
            "independent_replay_archive": dict(
                files["replay"][1], artifact_id=11748040166
            ),
            "completed_real_calls": dict(
                calibration=len(raw_cal),
                evaluation=len(raw_eval),
                total=len(raw_cal) + len(raw_eval),
            ),
            "calibration": dict(
                frozen_k=selected_k,
                by_k={
                    k: dict(
                        strict_success=v["success"], prompt_tokens=v["prompt_tokens"]
                    )
                    for k, v in stats_cal.items()
                },
                leave_one_out_counts=chosen_calibration_by_fold,
                stable_to_one_case_removal=False,
            ),
            "evaluation": {
                arm: dict(
                    strict_correct=v["success"],
                    correct_with_full_program_declared_citation=v["full_citation"],
                    input_tokens=v["prompt_tokens"],
                    output_tokens=v["generated_tokens"],
                    reader_seconds=round(v["seconds"], 3),
                    support_delivered=v["full_support_delivered"],
                )
                for arm, v in stats_test.items()
            },
            "paired_effects": pairs,
            "identical_prompt_pairs": same_prompt_pairs,
            "original_source_families_independently_sampled": 0,
            "independent_semantic_citation_adjudication": False,
            "longitudinal_evidence": False,
            "graph_incremental_task_advantage_over_full_path_filter": False,
            "learned_parameter_advantage_established": False,
            "lifecycle_cost_qualified": False,
            "decision": "NO_GO_PARAMETRIC_OR_PRODUCTION; retain simple full-path filter and fixed reader as next independent baseline",
            "production_accepted": False,
        }
    finally:
        for z in handles:
            z.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("original", type=Path)
    p.add_argument("model", type=Path)
    p.add_argument("independent_replay", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    report = evaluate(args.original, args.model, args.independent_replay)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
    print(
        json.dumps(
            {
                "source": report["source_commit"],
                "model_calls": report["completed_real_calls"],
                "decision": report["decision"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
