"""Read-only cross-run audit of three exact frozen-reader Qwen research runs.

This checks original output identity and empirical *inter-run* variability,
not statistical independence, semantic citation entailment or production fitness.
Never merge raw answers from different source commits into a synthetic trial.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memory-strong-rag.cross-run-replication.v1"
PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
COLLECTION_SHA = "be47e85e87692fa0c5036ebf1aa6090e040334b70719a9103e880960e6a60da9"
SOURCE_PINS = {
    "A": {
        "run_id": 38148514657,
        "commit": "8250698244417eb14994518af05fa6f79e783066",
        "full_sha256": (
            "7c991f0996fc24c650efb28f6266da51ed1655b78585e11b78dbc424707b7b7f"
        ),
        "replay_sha256": (
            "7e390bddfb1c59e0bb82999b01747a180eb1ec1f84d9f863a536dd036ec483f1"
        ),
        "full_members": 267,
        "replay_members": 1,
        "replay_file": "shard-replay.json",
        "whole_workflow_success": True,
    },
    "B": {
        "run_id": 38146546731,
        "commit": "eba9af092cca1c2875552ffaea2219678143a73c",
        "full_sha256": (
            "b4cf1346ce4c5b1625cdc57845bcca33fcf82f84340433b602d76258c10c1138"
        ),
        "replay_sha256": (
            "4c64e9c01bef56d0f311e633af53c7a246102e7083a272122286fb7ff66085a3"
        ),
        "full_members": 267,
        "replay_members": 1,
        "replay_file": "shard-replay.json",
        "whole_workflow_success": True,
    },
    "C": {
        "run_id": 38114667490,
        "commit": "c24fad24b65984a6255a8854c6714c141911ff79",
        "full_sha256": (
            "2d71f40e553e7d28cad9d8e16803f52b7a99e771b5bf54f55c89bc9468702107"
        ),
        "replay_sha256": (
            "fe710be3f987e34ec3cda48be37509e20a01b48db090907c98ce33cfff198225"
        ),
        "full_members": 38,
        "replay_members": 8,
        "replay_file": "receipt.json",
        "whole_workflow_success": False,
    },
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
SCORED_ONLY = frozenset(
    (
        "parsed_identifier",
        "strict_task_success",
        "required_sources_covered",
        "procedure_verification",
    )
)


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def strict_json(data: bytes):
    def unique(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    def reject(number):
        raise ValueError("nonfinite JSON number")

    def finite(number):
        value = float(number)
        if not math.isfinite(value):
            raise ValueError("nonfinite JSON float")
        return value

    return json.loads(
        data, object_pairs_hook=unique, parse_constant=reject, parse_float=finite
    )


def _safe_member(name: str) -> None:
    path = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or name != path.as_posix()
        or "\\" in name
        or path.is_absolute()
        or path.parts[0] == "."
        or any(part in ("..", "") for part in path.parts)
    ):
        raise ValueError("noncanonical ZIP member path")


def open_sealed(path: Path, expected_sha: str, *, manifest: bool):
    if not path.is_file() or path.is_symlink():
        raise ValueError("missing or linked archive")
    if (
        path.stat().st_size > 16 * 1024 * 1024
        or digest(path.read_bytes()) != expected_sha
    ):
        raise ValueError("outer archive SHA256 does not match selected run")
    with zipfile.ZipFile(path) as z:
        entries = z.infolist()
        if (
            not entries
            or len(entries) > 400
            or sum(x.file_size for x in entries) > 12 * 1024 * 1024
        ):
            raise ValueError("archive has invalid file census or size")
        names = set()
        for item in entries:
            _safe_member(item.filename)
            if (
                item.filename in names
                or item.is_dir()
                or stat.S_ISLNK(item.external_attr >> 16)
            ):
                raise ValueError("archive has duplicate, directory or symlink member")
            names.add(item.filename)
        files = {item.filename: z.read(item) for item in entries}
    if manifest:
        if "SHA256SUMS" not in files:
            raise ValueError("missing original artifact SHA256SUMS")
        checks = {}
        for line in files["SHA256SUMS"].decode("utf-8").splitlines():
            found = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
            if not found:
                raise ValueError("invalid manifest entry")
            sha, name = found.groups()
            _safe_member(name)
            if name in checks:
                raise ValueError("duplicate manifest entry")
            checks[name] = sha
        if set(checks) != names - {"SHA256SUMS"}:
            raise ValueError("incomplete or extra manifest entries")
        for name, expected in checks.items():
            if digest(files[name]) != expected:
                raise ValueError("changed original archive member")
    elif set(files) != {"shard-replay.json"}:
        raise ValueError("unexpected independent replay ZIP census")
    return files


def load_stage(files, stage, replay, commit, model_identity, arms, count):
    raw_bytes = files[f"{stage}/raw-answers.jsonl"]
    raw = [strict_json(line) for line in raw_bytes.splitlines() if line.strip()]
    scored = strict_json(files[f"{stage}/scored-answers.json"])
    report = strict_json(files[f"{stage}/report.json"])
    run = strict_json(files[f"{stage}/run.json"])
    if len(raw) != count or len(scored) != count or run["source_commit"] != commit:
        raise ValueError("incomplete original generation or changed emitting commit")
    if report["source_commit"] != commit or report["raw_answers_sha256"] != digest(
        raw_bytes
    ):
        raise ValueError("run report detached from raw generation journal")
    if (
        replay[stage]["attempts"] != count
        or replay[stage]["all_model_calls_succeeded"] is not True
    ):
        raise ValueError("independent replay did not verify every original model call")
    if replay[stage]["original_raw_sha256"] != digest(raw_bytes):
        raise ValueError("independent replay raw-answer hash mismatch")
    ids = set()
    successes = Counter()
    for original, verified in zip(raw, scored, strict=True):
        key = (original["question_id"], original["arm"])
        if key in ids or key[1] not in arms:
            raise ValueError("duplicate or unexpected original question/arm")
        ids.add(key)
        if original["status"] != "succeeded" or verified["status"] != "succeeded":
            raise ValueError("failed model call in complete-trial claim")
        if any(k in original for k in SCORED_ONLY):
            raise ValueError("raw journal opened scored/gold values before generation")
        if {k: v for k, v in verified.items() if k not in SCORED_ONLY} != original:
            raise ValueError("scorer changed original answer or model receipt")
        if type(verified.get("strict_task_success")) is not bool:
            raise ValueError("missing strict task result")
        receipt = original["receipt"]
        if (
            receipt["reader_identity"] != model_identity
            or not re.fullmatch(r"[0-9a-f]{64}", receipt["input_ids_digest"])
            or not re.fullmatch(r"[0-9a-f]{64}", receipt["generated_ids_digest"])
            or type(receipt["input_tokens"]) is not int
            or not 0 < receipt["input_tokens"] <= 2048
            or type(receipt["generated_tokens"]) is not int
            or not 0 <= receipt["generated_tokens"] <= 64
            or [s["original_id"] for s in receipt["delivered_evidence"]]
            != original["selected"]
            or original["citation_audit"]["request"]["answer"] != original["answer"]
        ):
            raise ValueError(
                "original delivered source, reader or prompt does not match"
            )
        successes[original["arm"]] += verified["strict_task_success"]
    if len({q for q, _ in ids}) != 8 or {arm for _, arm in ids} != set(arms):
        raise ValueError("incorrect original question/arm census")
    if {q: {arm for qid, arm in ids if qid == q} for q, _ in ids} != {
        q: set(arms) for q, _ in ids
    }:
        raise ValueError("original question lacks a matched experimental arm")
    if dict(successes) != replay[stage]["strict_success"]:
        raise ValueError("independent replay scored success differs from journal")
    totals = report["arms"] if stage == "calibration" else report["success_by_arm"]
    if any(totals[a]["strict_success"] != successes[a] for a in arms):
        raise ValueError(
            "reported strict success differs from independently replayed journal"
        )
    return {
        "raw": {(r["question_id"], r["arm"]): r for r in raw},
        "scored": {(r["question_id"], r["arm"]): r for r in scored},
        "report": report,
        "strict_success": dict(successes),
        "raw_sha256": digest(raw_bytes),
    }


def inspect(full_path: Path, replay_path: Path, pin: dict):
    files = open_sealed(full_path, pin["full_sha256"], manifest=True)
    independent = open_sealed(
        replay_path,
        pin["replay_sha256"],
        manifest=pin["replay_file"] == "receipt.json",
    )
    if len(files) - 1 != pin["full_members"]:
        raise ValueError("incorrect pinned original model file census")
    if len(independent) - ("SHA256SUMS" in independent) != pin["replay_members"]:
        raise ValueError("incorrect pinned read-only replay file census")
    replay = strict_json(independent[pin["replay_file"]])
    source = files["tested-commit.txt"].decode("utf-8").strip()
    inventory = strict_json(files["inventory.json"])
    model = inventory["inventory_digest"]
    if (
        source != pin["commit"]
        or replay["generating_commit"] != source
        or replay["original_plan_sha256"] != PLAN_SHA
        or replay["original_collection_sha256"] != COLLECTION_SHA
        or replay["model_identity"] != model
        or replay["verified_artifact_files"] != len(files) - 1
        or replay["production_accepted"] is not False
        or replay["independent_semantic_judge"] is not False
    ):
        raise ValueError("incorrect frozen plan, model identity or independent replay")
    policy = strict_json(files["calibration/frozen-policy.json"])
    if policy["source_commit"] != source or policy["reader_identity"] != model:
        raise ValueError("frozen calibration policy moved")
    cal = load_stage(files, "calibration", replay, source, model, CAL_ARMS, 40)
    ev = load_stage(files, "evaluation", replay, source, model, TEST_ARMS, 72)
    if (
        policy["selected_k"] != cal["report"]["frozen_k"]
        or ev["report"]["selected_k"] != policy["selected_k"]
    ):
        raise ValueError("evaluation selection changed after original calibration")
    if ev["report"]["formal_citation_chain"] != replay["formal_citation_chain"]:
        raise ValueError(
            "published formal citation result differs from read-only replay"
        )
    if ev["report"]["paired_contrasts"] != replay["paired_contrasts"]:
        raise ValueError("published paired contrasts differ from replay")
    return {
        "commit": source,
        "model_identity": model,
        "replay": replay,
        "calibration": cal,
        "evaluation": ev,
    }


def compare(a: dict, b: dict):
    if a["model_identity"] != b["model_identity"]:
        raise ValueError("different reader/model weights across runs")
    differences = {"calibration": [], "evaluation": []}
    for stage in ("calibration", "evaluation"):
        left = a[stage]["raw"]
        right = b[stage]["raw"]
        if set(left) != set(right):
            raise ValueError("different question/arm populations between runs")
        for (qid, arm), x in left.items():
            y = right[(qid, arm)]
            xr, yr = x["receipt"], y["receipt"]
            for label, val_a, val_b in (
                ("candidate", x["candidate_digest"], y["candidate_digest"]),
                ("selected", x["selected"], y["selected"]),
                ("reader_profile", xr["reader_profile"], yr["reader_profile"]),
                ("input_ids_digest", xr["input_ids_digest"], yr["input_ids_digest"]),
                ("input_tokens", xr["input_tokens"], yr["input_tokens"]),
                (
                    "delivered_evidence",
                    xr["delivered_evidence"],
                    yr["delivered_evidence"],
                ),
            ):
                if val_a != val_b:
                    raise ValueError(
                        f"inter-run source/prompt mismatch: {stage} {qid} {arm} {label}"
                    )
            if (
                x["answer"] != y["answer"]
                or xr["generated_ids_digest"] != yr["generated_ids_digest"]
            ):
                differences[stage].append(
                    {
                        "question_id": qid,
                        "arm": arm,
                        "answer_a": x["answer"],
                        "answer_b": y["answer"],
                        "generated_ids_digest_a": xr["generated_ids_digest"],
                        "generated_ids_digest_b": yr["generated_ids_digest"],
                        "strict_success_a": a[stage]["scored"][(qid, arm)][
                            "strict_task_success"
                        ],
                        "strict_success_b": b[stage]["scored"][(qid, arm)][
                            "strict_task_success"
                        ],
                    }
                )
    return differences


def generate(paths: dict, pins=None):
    pins = SOURCE_PINS if pins is None else pins
    names = ("A", "B", "C")
    sources = {
        key: inspect(Path(paths[key][0]), Path(paths[key][1]), pins[key])
        for key in names
    }
    model_ids = {source["model_identity"] for source in sources.values()}
    choices = {
        label: source["calibration"]["report"]["frozen_k"]
        for label, source in sources.items()
    }
    if len(model_ids) != 1 or len(set(choices.values())) != 1:
        raise ValueError("different frozen reader or calibrated k across runs")

    pairwise_differences = {}
    for left, right in (("A", "B"), ("A", "C"), ("B", "C")):
        pairwise_differences[left + "_versus_" + right] = compare(
            sources[left], sources[right]
        )
    unstable_cases = {"calibration": [], "evaluation": []}
    for stage in unstable_cases:
        original = sources["A"][stage]["raw"]
        for key in sorted(original):
            all_rows = [sources[label][stage]["raw"][key] for label in names]
            all_scored = [sources[label][stage]["scored"][key] for label in names]
            answers = [row["answer"] for row in all_rows]
            generated = [row["receipt"]["generated_ids_digest"] for row in all_rows]
            if len(set(answers)) != 1 or len(set(generated)) != 1:
                unstable_cases[stage].append(
                    {
                        "question_id": key[0],
                        "arm": key[1],
                        "answers": dict(zip(names, answers, strict=True)),
                        "strict_success": {
                            label: row["strict_task_success"]
                            for label, row in zip(names, all_scored, strict=True)
                        },
                        "strict_task_outcome_changed": len(
                            {row["strict_task_success"] for row in all_scored}
                        )
                        > 1,
                        "same_exact_original_prompt_in_all_runs": True,
                    }
                )

    arms = {}
    for arm in TEST_ARMS:
        by_run = {}
        for label in names:
            report = sources[label]["evaluation"]["report"]
            stats = report["success_by_arm"][arm]
            chain = report["formal_citation_chain"]["by_arm"][arm]
            by_run[label] = {
                "correct": stats["strict_success"],
                "correct_with_full_program_declared_citations": chain[
                    "correct_with_full_program_declared_citations"
                ],
                "input_tokens": stats["input_tokens"],
            }
        arms[arm] = by_run
    for source in sources.values():
        report = source["evaluation"]["report"]
        if report["total_attempts"] != 72:
            raise ValueError("incomplete original nine-arm evaluation")
        if report["same_prompt_consistency"]["answer_disagreements"]:
            raise ValueError("original experiment reports same-prompt instability")

    return {
        "schema": SCHEMA,
        "input": {
            label: {
                "github_actions_run": pins[label]["run_id"],
                "source_commit": pins[label]["commit"],
                "full_archive_sha256": pins[label]["full_sha256"],
                "independent_replay_sha256": pins[label]["replay_sha256"],
                "verified_manifest_entries": pins[label]["full_members"],
                "independent_replay_manifest_entries": pins[label]["replay_members"],
                "whole_workflow_success": pins[label]["whole_workflow_success"],
                "original_calibration_journal_sha256": source["calibration"][
                    "raw_sha256"
                ],
                "original_evaluation_journal_sha256": source["evaluation"][
                    "raw_sha256"
                ],
            }
            for label, source in sources.items()
        },
        "frozen_model_identity": next(iter(model_ids)),
        "frozen_plan_sha256": PLAN_SHA,
        "runs": len(names),
        "original_calibration_generations_per_run": 40,
        "original_evaluation_generations_per_run": 72,
        "total_actual_model_generations": len(names) * (40 + 72),
        "identical_original_prompts_across_all_runs": {
            "calibration": 40,
            "evaluation": 72,
        },
        "pairwise_output_differences": pairwise_differences,
        "distinct_inputs_with_output_variability": {
            stage: len(cases) for stage, cases in unstable_cases.items()
        },
        "unstable_original_prompt_cases": unstable_cases,
        "calibrated_k_by_run": choices,
        "strict_success_and_citation_by_arm": arms,
        "all_runs_exact_output_equivalent": not any(unstable_cases.values()),
        "independent_new_source_families": 0,
        "independent_semantic_citation_adjudication": False,
        "parametric_training_performed": False,
        "organization_extra_task_success_over_entity_time": {
            label: source["evaluation"]["report"]["success_by_arm"]["organized"][
                "strict_success"
            ]
            - source["evaluation"]["report"]["success_by_arm"]["entity_time"][
                "strict_success"
            ]
            for label, source in sources.items()
        },
        "production_accepted": False,
        "statistical_superiority": False,
        "disposition": (
            "NO-GO: no incremental organizer task/citation-chain gain over "
            "full-path filtering on exposed authored tasks"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for label in ("a_full", "a_replay", "b_full", "b_replay", "c_full", "c_replay"):
        parser.add_argument(label, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = generate(
        {
            "A": (args.a_full, args.a_replay),
            "B": (args.b_full, args.b_replay),
            "C": (args.c_full, args.c_replay),
        }
    )
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(report, target, indent=2, ensure_ascii=False, allow_nan=False)
        target.write("\n")
    print(
        json.dumps(
            {
                "schema": report["schema"],
                "distinct_inputs_with_output_variability": report[
                    "distinct_inputs_with_output_variability"
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
