"""Bounded CPU Qwen experiment shards; original answers are never relabeled.

The 8x5 calibration and 8x9 evaluation populations are unchanged. Every arm
really executes the frozen reader. Splitting does not create independent tasks,
change weights/decoder, or authorize a production/semantic quality claim.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import time

import strong_rag_trial as trial
from event_memory_trial import read
from native import Question, digest
from strong_rag_stability import KS, leave_one_out

SCHEMA = "hepta.memory-strong-rag.shards.v1"
# Disjoint, preregistered groups. Worst arm groups each receive their own host.
CAL_GROUPS = (("k1", "k3", "k6"), ("k2", "k4"))
EVAL_GROUPS = (
    ("selected_k", "hybrid_k4", "single_hop", "organized", "empty"),
    ("hybrid_k6", "hybrid_k4_reversed", "entity_time", "program_support"),
)
SHARD_MAX_SECONDS = 5400.0  # real CPU calls can take >180s, 90m remains bounded


def groups(phase):
    if phase == "calibration":
        result, expected = CAL_GROUPS, tuple(f"k{k}" for k in KS)
    elif phase == "evaluation":
        result, expected = EVAL_GROUPS, trial.EVAL_ARMS
    else:
        raise ValueError("only frozen calibration/evaluation phases")
    flat = tuple(item for group in result for item in group)
    if len(flat) != len(set(flat)) or set(flat) != set(expected):
        raise ValueError("sharded arms differ from preregistered reader controls")
    return result


def name(phase, index, half):
    if type(index) is not int or not 0 <= index < 8 or half not in (0, 1):
        raise ValueError("registered 8 by 2 shard identifier required")
    if phase not in ("calibration", "evaluation"):
        raise ValueError("invalid frozen phase")
    return f"memory-{phase}-{index}-{half}"


def _copy(source, destination):
    if source.is_symlink() or not source.is_file():
        raise ValueError("pinned regular source artifact required")
    shutil.copyfile(source, destination)


def _seal(output, extras):
    """Bind each shard to frozen source commit/model and original answer bytes."""
    digest_fields = {file: trial.file_sha(output / file) for file in extras}
    trial.dump(output / "sha-pins.json", digest_fields)


def _read_local_record(path):
    """Reopen one bounded, unexternally-pinned artifact without disabling read().

    These records are checked against other source pins and exact journal
    receipts by their callers. A self-hash is NOT independent authentication.
    """
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("bounded regular local record required")
    return read(path, trial.file_sha(path))


def _read_rows(path, count):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError("bounded immutable original journal required")
    body = path.read_bytes()
    if not body.endswith(b"\n") or len(body.splitlines()) != count:
        raise ValueError("missing, partial or extra model attempt")

    def unique_pairs(pairs):
        value = {}
        for key, obj in pairs:
            if key in value:
                raise ValueError("duplicate raw model answer JSON key")
            value[key] = obj
        return value

    def reject_nonfinite(value):
        raise ValueError("nonfinite raw model result")

    return [
        json.loads(
            line.decode("utf-8", "strict"),
            object_pairs_hook=unique_pairs,
            parse_constant=reject_nonfinite,
        )
        for line in body.splitlines()
    ]


def _stage(model_dir, stage_sha):
    metadata = read(model_dir / "stage.json", stage_sha)
    inventory = read(model_dir / "inventory.json", metadata["inventory_sha256"])
    if (
        metadata["tier"] != "qwen-3b"
        or metadata["revision"] != "82f42baa094a9600e39ccd80d34058aeeb3abbc1"
        or inventory["inventory_digest"]
        != "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
    ):
        raise ValueError("reader changed from separately pinned research-only Qwen")
    return metadata, inventory


def _journal_shard(reader, case, originals, arms, selection, path, *, seed):
    """Use the original generator verbatim; change only the CPU time gate.

    Every answer is fsynced by strong_rag_trial before this diagnostic bound is
    checked. The temporary substitution is process-local to one source shard;
    prompts, weights, attribution, decoding and citation capture stay original.
    """
    from unittest.mock import patch

    original_guard = trial.fail_if_unviable_reader

    def bounded(row):
        return original_guard(row, max_seconds=SHARD_MAX_SECONDS)

    with patch.object(trial, "fail_if_unviable_reader", bounded):
        return trial._journal_answers(
            reader, [case], originals, arms, selection, path, seed=seed
        )


def generate(
    phase,
    prep,
    plan_dir,
    inputs,
    model_dir,
    calibration_dir,
    output,
    *,
    case_index,
    part,
    prep_sha=None,
    plan_sha=None,
    stage_sha,
    policy_sha=None,
):
    """Generate one full original-answer journal without opening target labels."""
    from strong_rag_trial import _reader, documents
    from runtime_preflight import capture_runtime
    import torch

    commit = trial.commit_source()
    scheduled = groups(phase)[part]
    if phase == "calibration":
        manifest = read(prep / "calibration-plan.json", prep_sha)
        if (
            manifest["schema"] != trial.SCHEMA
            or manifest["source_commit"] != commit
            or len(manifest["cases"]) != 8
        ):
            raise ValueError("wrong calibration-only source commit/census")
        if (
            manifest["calibration_only"] is not True
            or manifest["test_cases_materialized"] is not False
        ):
            raise ValueError("evaluation data accessible through calibration plan")
        cases = manifest["cases"]
        originals = documents(
            read(
                prep / "calibration-sources.json",
                manifest["calibration_sources_sha256"],
            )
        )
        case = cases[case_index]
        selected = lambda row, arm: trial.chosen_prefix(
            row["candidate_ids"], int(arm[1:])
        )
        seed = prep_sha
        policy_digest = None
        single_hop = None
    else:
        from event_reader_experiment import preflight

        frozen = read(calibration_dir / "frozen-policy.json", policy_sha)
        if (
            plan_sha != trial.HISTORIC_PLAN_SHA
            or frozen["source_commit"] != commit
            or frozen["selected_k"] not in KS
            or frozen["original_test_plan_sha256"] != plan_sha
            or frozen["candidate_accepted"] is not False
            or frozen["frozen_before_evaluation"] is not True
        ):
            raise ValueError("unfrozen evaluation or reader source")
        manifest, originals = preflight(plan_dir, inputs, plan_sha)
        cases, single_hop = trial.freeze_single_hop(
            manifest["cases"], inputs, originals
        )
        case = cases[case_index]
        selection = trial.eval_selections(case, frozen["selected_k"])
        selected = lambda row, arm: selection[arm]
        seed = digest((plan_sha, policy_sha))
        policy_digest = policy_sha
    stage, inv = _stage(model_dir, stage_sha)
    if phase == "evaluation" and inv["inventory_digest"] != frozen["reader_identity"]:
        raise ValueError("different model between calibration and evaluation")
    reader, _, actual_inventory = _reader(model_dir, stage_sha)
    if actual_inventory["inventory_digest"] != inv["inventory_digest"]:
        raise ValueError("model inventory changed during initialization")
    output.mkdir()
    trial.dump(output / "runtime-preflight.json", capture_runtime(torch, bounded=False))
    if single_hop is not None:
        trial.dump(output / "single-hop-control.json", single_hop)
    _copy(model_dir / "stage.json", output / "stage.json")
    _copy(model_dir / "inventory.json", output / "inventory.json")
    _copy(model_dir / "publisher.json", output / "publisher.json")
    start = time.perf_counter()
    rows = _journal_shard(
        reader,
        case,
        originals,
        scheduled,
        selected,
        output / "raw-answers.jsonl",
        seed=seed,
    )
    trial.dump(
        output / "run.json",
        dict(
            schema=SCHEMA,
            phase=phase,
            source_commit=commit,
            case_index=case_index,
            part=part,
            case_id=case["query"]["identity"],
            arms=list(scheduled),
            model_stage_sha256=stage_sha,
            reader_identity=inv["inventory_digest"],
            calibration_plan_sha256=prep_sha if phase == "calibration" else None,
            test_plan_sha256=plan_sha if phase == "evaluation" else None,
            policy_sha256=policy_digest,
            generated=len(rows),
            raw_answers_sha256=trial.file_sha(output / "raw-answers.jsonl"),
            single_hop_control_sha256=(
                trial.file_sha(output / "single-hop-control.json")
                if single_hop is not None
                else None
            ),
            runtime_preflight_sha256=trial.file_sha(output / "runtime-preflight.json"),
            seconds=time.perf_counter() - start,
            model_weight_training=False,
            allowed_to_train=False,
            production_accepted=False,
        ),
    )
    sealed = [
        "runtime-preflight.json",
        "stage.json",
        "inventory.json",
        "publisher.json",
        "raw-answers.jsonl",
        "run.json",
    ]
    if single_hop is not None:
        sealed.append("single-hop-control.json")
    _seal(output, sealed)
    if any(r["status"] != "succeeded" for r in rows):
        raise ValueError("failed model attempt retained, not accepted")
    return len(rows)


def _merge_shards(
    phase,
    shard_root,
    cases,
    *,
    commit,
    prep_sha=None,
    plan_sha=None,
    policy_sha=None,
    reader_identity=None,
):
    """Fail closed on all 16 immutable per-source shard journals and pins."""
    result, records, model_pins, hop_pin = {}, [], None, None
    for idx, case in enumerate(cases):
        for part, scheduled in enumerate(groups(phase)):
            folder = shard_root / name(phase, idx, part)
            manifest = _read_local_record(folder / "sha-pins.json")
            expected_files = {
                "runtime-preflight.json",
                "stage.json",
                "inventory.json",
                "publisher.json",
                "raw-answers.jsonl",
                "run.json",
            }
            if phase == "evaluation":
                expected_files.add("single-hop-control.json")
            if set(manifest) != expected_files:
                raise ValueError("shard file census incomplete")
            if folder.is_symlink() or {
                entry.name for entry in folder.iterdir()
            } != expected_files | {"sha-pins.json"}:
                raise ValueError("unsealed or extra source-shard file")
            for filename, digest_pin in manifest.items():
                if trial.file_sha(folder / filename) != digest_pin:
                    raise ValueError("source-shard artifact mutated")
            run = read(folder / "run.json", manifest["run.json"])
            identity = read(folder / "inventory.json", manifest["inventory.json"])[
                "inventory_digest"
            ]
            stage = read(folder / "stage.json", manifest["stage.json"])
            if (
                run["schema"] != SCHEMA
                or run["phase"] != phase
                or run["source_commit"] != commit
                or run["case_index"] != idx
                or run["part"] != part
                or run["case_id"] != case["query"]["identity"]
                or run["arms"] != list(scheduled)
                or run["generated"] != len(scheduled)
                or run["reader_identity"] != identity
                or run["model_stage_sha256"] != manifest["stage.json"]
                or stage["inventory_sha256"] != manifest["inventory.json"]
                or stage.get("publisher_sha256") != manifest["publisher.json"]
                or run["runtime_preflight_sha256"] != manifest["runtime-preflight.json"]
                or run["raw_answers_sha256"] != manifest["raw-answers.jsonl"]
                or run.get("single_hop_control_sha256")
                != (
                    manifest["single-hop-control.json"]
                    if phase == "evaluation"
                    else None
                )
                or run["calibration_plan_sha256"]
                != (prep_sha if phase == "calibration" else None)
                or run["test_plan_sha256"]
                != (plan_sha if phase == "evaluation" else None)
                or run["policy_sha256"]
                != (policy_sha if phase == "evaluation" else None)
                or run["production_accepted"] is not False
                or identity
                != "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
                or (reader_identity is not None and reader_identity != identity)
            ):
                raise ValueError("cross-shard source/model/phase drift")
            rows = _read_rows(folder / "raw-answers.jsonl", len(scheduled))
            if [r["arm"] for r in rows] != list(scheduled) or any(
                row["question_id"] != case["query"]["identity"]
                or row["status"] != "succeeded"
                or row["candidate_digest"] != case["candidate_digest"]
                for row in rows
            ):
                raise ValueError("missing, moved or failed original model answer")
            # Each shard can be internally hash-consistent while a different
            # model stage, inventory or publisher slips into a paired census.
            shard_model_pins = tuple(
                manifest[key]
                for key in ("stage.json", "inventory.json", "publisher.json")
            )
            if model_pins is None:
                model_pins = shard_model_pins
            elif shard_model_pins != model_pins:
                raise ValueError("mixed frozen reader model files across shards")
            if phase == "evaluation":
                this_hop = manifest["single-hop-control.json"]
                if hop_pin is None:
                    hop_pin = this_hop
                elif this_hop != hop_pin:
                    raise ValueError("mixed original single-hop evidence across shards")
            result[name(phase, idx, part)] = dict(
                raw_answers_sha256=manifest["raw-answers.jsonl"],
                run_sha256=manifest["run.json"],
                stage_sha256=manifest["stage.json"],
                runtime_preflight_sha256=manifest["runtime-preflight.json"],
                single_hop_control_sha256=(
                    manifest["single-hop-control.json"]
                    if phase == "evaluation"
                    else None
                ),
                seconds=run["seconds"],
            )
            records.extend(rows)
    if len(result) != 16 or len(records) != 8 * len(
        tuple(a for grp in groups(phase) for a in grp)
    ):
        raise ValueError("incomplete frozen 8 by 2 generation census")
    # Original registered row order; split groups can interleave registered arms.
    by_key = {(r["question_id"], r["arm"]): r for r in records}
    if len(by_key) != len(records):
        raise ValueError("duplicate original model answer")
    return [
        by_key[(case["query"]["identity"], arm)]
        for case in cases
        for arm in (
            tuple(f"k{k}" for k in KS) if phase == "calibration" else trial.EVAL_ARMS
        )
    ], result


def _write_journal(path, rows):
    with path.open("x", encoding="utf-8") as dest:
        for row in rows:
            dest.write(json.dumps(row, allow_nan=False, ensure_ascii=False) + "\n")
        dest.flush()
        os.fsync(dest.fileno())


def _first_metadata(shard_root, phase, dest, *, canonical=False):
    shard = shard_root / name(phase, 0, 0)
    for filename in (
        "runtime-preflight.json",
        "stage.json",
        "inventory.json",
        "publisher.json",
    ):
        _copy(shard / filename, dest / filename)
    return trial.file_sha(dest / "stage.json")


def collect_calibration(prep, shard_root, output, *, prep_sha):
    commit = trial.commit_source()
    locked = read(prep / "calibration-plan.json", prep_sha)
    if (
        locked["schema"] != trial.SCHEMA
        or locked["source_commit"] != commit
        or len(locked["cases"]) != 8
    ):
        raise ValueError("wrong pre-committed calibration population")
    cases = locked["cases"]
    rows, receipts = _merge_shards(
        "calibration", shard_root, cases, commit=commit, prep_sha=prep_sha
    )
    output.mkdir()
    stage_sha = _first_metadata(shard_root, "calibration", output)
    inv = read(
        output / "inventory.json",
        read(output / "stage.json", stage_sha)["inventory_sha256"],
    )
    _write_journal(output / "raw-answers.jsonl", rows)
    labels = read(prep / "calibration-labels.json", locked["calibration_labels_sha256"])
    expected = [c["query"]["identity"] for c in cases]
    choice, stats = trial.choose_k(rows, labels, expected)
    sensitivity = leave_one_out(rows, expected)
    trial.dump(output / "scored-answers.json", rows)
    trial.dump(
        output / "run.json",
        dict(
            schema=trial.SCHEMA,
            stage="calibration",
            source_commit=commit,
            runtime_preflight_sha256=trial.file_sha(output / "runtime-preflight.json"),
            calibration_sha256=prep_sha,
            model_stage_sha256=stage_sha,
            model=inv,
            optimizer_executed=False,
            test_tasks_opened=False,
            human_reviewed=False,
            execution_mode="sharded",
            production_accepted=False,
        ),
    )
    trial.dump(
        output / "report.json",
        dict(
            schema=trial.SCHEMA,
            source_commit=commit,
            phase="calibration",
            planned_attempts=len(rows),
            frozen_k=choice,
            ks=KS,
            selection_objective="actual strict task success, then fewer observed input tokens, then smaller k",
            arms=stats,
            calibration_sensitivity=sensitivity,
            total_elapsed_seconds=sum(r["seconds"] for r in receipts.values()),
            reader_identity=inv["inventory_digest"],
            model_stage_sha256=stage_sha,
            raw_answers_sha256=trial.file_sha(output / "raw-answers.jsonl"),
            original_cases_are_exposed_development=True,
            statistical_superiority=False,
            independent_semantic_review=False,
            production_accepted=False,
            execution_mode="sharded",
            elapsed_is_sum_not_wall=True,
        ),
    )
    if choice is None:
        raise ValueError("cannot freeze k with missing/failed calibration attempts")
    trial.dump(
        output / "frozen-policy.json",
        dict(
            schema=trial.SCHEMA,
            selected_k=choice,
            ks=KS,
            source_commit=commit,
            calibration_plan_sha256=prep_sha,
            original_test_plan_sha256=trial.HISTORIC_PLAN_SHA,
            stage_sha256=stage_sha,
            reader_identity=inv["inventory_digest"],
            raw_answers_sha256=trial.file_sha(output / "raw-answers.jsonl"),
            scored_answers_sha256=trial.file_sha(output / "scored-answers.json"),
            calibration_sensitivity_digest=digest(sensitivity),
            selection_objective="actual strict task success, then fewer observed input tokens, then smaller k",
            calibration_task_count=8,
            evaluation_task_count=8,
            frozen_before_evaluation=True,
            independent_source_families=0,
            candidate_accepted=False,
            production_accepted=False,
            execution_mode="sharded",
        ),
    )
    trial.dump(
        output / "shard-census.json",
        dict(
            schema=SCHEMA,
            phase="calibration",
            receipts=receipts,
            canonical_stage_sha256=stage_sha,
            raw_sha256=trial.file_sha(output / "raw-answers.jsonl"),
            source_commit=commit,
            production_accepted=False,
        ),
    )
    return choice


def collect_evaluation(
    plan_dir, inputs, prep, calibration_dir, shard_root, output, *, plan_sha, policy_sha
):
    from event_reader_experiment import preflight
    from strong_rag_repeatability import audit_repeats
    from historical_event_citation_chain import audit_evaluation

    commit = trial.commit_source()
    locked_policy = read(calibration_dir / "frozen-policy.json", policy_sha)
    if (
        locked_policy["source_commit"] != commit
        or locked_policy["schema"] != trial.SCHEMA
        or locked_policy["candidate_accepted"] is not False
    ):
        raise ValueError("unqualified frozen source policy")
    locked, originals = preflight(plan_dir, inputs, plan_sha)
    active, hop = trial.freeze_single_hop(locked["cases"], inputs, originals)
    rows, receipts = _merge_shards(
        "evaluation",
        shard_root,
        active,
        commit=commit,
        plan_sha=plan_sha,
        policy_sha=policy_sha,
        reader_identity=locked_policy["reader_identity"],
    )
    output.mkdir()
    _first_metadata(shard_root, "evaluation", output)
    _write_journal(output / "raw-answers.jsonl", rows)
    trial.dump(output / "single-hop-control.json", hop)
    expected_hop_sha = trial.file_sha(output / "single-hop-control.json")
    if any(
        receipt["single_hop_control_sha256"] != expected_hop_sha
        for receipt in receipts.values()
    ):
        raise ValueError("evaluation shards disagree with frozen single-hop evidence")
    expected = [c["query"]["identity"] for c in active]
    labels = read(inputs / "labels.json", locked["labels_sha"])
    targets = [l for l in labels if l["id"] in set(expected)]
    trial._score(rows, targets, expected=expected, arms=trial.EVAL_ARMS)
    trial.dump(output / "scored-answers.json", rows)
    public_questions = read(
        inputs / "questions.json", locked["extraction"]["files"]["questions.json"]
    )
    citations = audit_evaluation(
        rows,
        public_questions,
        targets,
        originals,
        expected_qids=expected,
        arms=trial.EVAL_ARMS,
    )
    stats, group = trial._stats(rows, trial.EVAL_ARMS, expected)
    repeats = audit_repeats(rows, expected, trial.EVAL_ARMS)
    pairs = {
        "selected_minus_hybrid4": trial.paired(group, "hybrid_k4", "selected_k"),
        "organized_minus_selected": trial.paired(group, "selected_k", "organized"),
        "single_hop_minus_hybrid4": trial.paired(group, "hybrid_k4", "single_hop"),
        "entity_time_minus_single_hop": trial.paired(
            group, "single_hop", "entity_time"
        ),
        "entity_time_minus_hybrid4": trial.paired(group, "hybrid_k4", "entity_time"),
        "organized_minus_entity_time": trial.paired(group, "entity_time", "organized"),
        "organized_minus_hybrid4": trial.paired(group, "hybrid_k4", "organized"),
        "reversed_minus_hybrid4": trial.paired(
            group, "hybrid_k4", "hybrid_k4_reversed"
        ),
        "hybrid6_minus_hybrid4": trial.paired(group, "hybrid_k4", "hybrid_k6"),
    }
    stage_sha = locked_policy["stage_sha256"]
    if (
        _read_local_record(calibration_dir / "run.json")["model_stage_sha256"]
        != stage_sha
    ):
        raise ValueError("canonical staged reader drift")
    inv = read(
        output / "inventory.json",
        _read_local_record(output / "stage.json")["inventory_sha256"],
    )
    trial.dump(
        output / "run.json",
        dict(
            schema=trial.SCHEMA,
            phase="evaluation",
            source_commit=commit,
            execution_mode="sharded",
            runtime_preflight_sha256=trial.file_sha(output / "runtime-preflight.json"),
            policy_sha256=policy_sha,
            policy=locked_policy,
            test_plan_sha256=plan_sha,
            stage_sha256=stage_sha,
            model=inv,
            original_case_census=len(active),
            training_during_query=False,
            new_future_sources=False,
            human_verified_sufficiency=False,
            production_accepted=False,
        ),
    )
    trial.dump(
        output / "report.json",
        dict(
            schema=trial.SCHEMA,
            phase="evaluation",
            source_commit=commit,
            selected_k=locked_policy["selected_k"],
            test_task_count=len(expected),
            total_attempts=len(rows),
            success_by_arm=stats,
            paired_contrasts=pairs,
            same_prompt_consistency=repeats,
            formal_citation_chain=citations,
            single_hop_control_sha256=trial.file_sha(
                output / "single-hop-control.json"
            ),
            source_and_index_costs=locked["frozen"]["costs"],
            extraction_costs=locked["extraction"],
            retained_original_source_bytes=sum(
                len(d.content.encode()) for d in originals.values()
            ),
            calibration_training_optimizer_seconds=0.0,
            reader_optimizer_seconds=0.0,
            wall_seconds=sum(x["seconds"] for x in receipts.values()),
            raw_answers_sha256=trial.file_sha(output / "raw-answers.jsonl"),
            citation_entailment_accuracy=None,
            missing_costs=["deployed retention", "revocation", "real recovery"],
            total_lifecycle_cost=None,
            prior_public_authored_exposed_development=True,
            independent_source_family_count=0,
            statistical_superiority=False,
            reader_capacity_gain_is_memory_gain=False,
            model_or_policy_accepted=False,
            production_accepted=False,
            execution_mode="sharded",
            elapsed_is_sum_not_wall=True,
        ),
    )
    trial.dump(
        output / "shard-census.json",
        dict(
            schema=SCHEMA,
            phase="evaluation",
            receipts=receipts,
            canonical_stage_sha256=stage_sha,
            raw_sha256=trial.file_sha(output / "raw-answers.jsonl"),
            source_commit=commit,
            production_accepted=False,
        ),
    )
    return stats


def verify_release(archive, original):
    """Independent of model generation, reassemble every unmodified shard."""
    from event_reader_experiment import preflight

    commit = trial.commit_source()
    manifest = _read_local_record(archive / "prep/calibration-plan.json")
    prep_sha = trial.file_sha(archive / "prep/calibration-plan.json")
    frozen = _read_local_record(archive / "calibration/frozen-policy.json")
    policy_sha = trial.file_sha(archive / "calibration/frozen-policy.json")
    if (
        frozen["source_commit"] != commit
        or frozen["calibration_plan_sha256"] != prep_sha
    ):
        raise ValueError("frozen k detached from exact shard source")
    original_cal, cal_provenance = _merge_shards(
        "calibration",
        archive / "shards/calibration",
        manifest["cases"],
        commit=commit,
        prep_sha=prep_sha,
    )
    original_plan, original_sources = preflight(
        original / "plan", original / "observations", trial.HISTORIC_PLAN_SHA
    )
    active, expected_hop = trial.freeze_single_hop(
        original_plan["cases"], original / "observations", original_sources
    )
    original_eval, eval_provenance = _merge_shards(
        "evaluation",
        archive / "shards/evaluation",
        active,
        commit=commit,
        plan_sha=trial.HISTORIC_PLAN_SHA,
        policy_sha=policy_sha,
        reader_identity=frozen["reader_identity"],
    )
    published_hop = _read_local_record(archive / "evaluation/single-hop-control.json")
    if published_hop != expected_hop or any(
        row["single_hop_control_sha256"]
        != trial.file_sha(archive / "evaluation/single-hop-control.json")
        for row in eval_provenance.values()
    ):
        raise ValueError("single-hop evidence differs from original public sources")
    for phase, rows, receipts in (
        ("calibration", original_cal, cal_provenance),
        ("evaluation", original_eval, eval_provenance),
    ):
        saved = _read_rows(archive / phase / "raw-answers.jsonl", len(rows))
        if rows != saved:
            raise ValueError(
                "published answer journal differs from generated shard rows"
            )
        summary = _read_local_record(archive / phase / "shard-census.json")
        if (
            summary["schema"] != SCHEMA
            or summary["phase"] != phase
            or summary["source_commit"] != commit
            or summary["receipts"] != receipts
            or summary["raw_sha256"]
            != trial.file_sha(archive / phase / "raw-answers.jsonl")
            or (
                phase == "calibration"
                and summary["canonical_stage_sha256"] != frozen["stage_sha256"]
            )
        ):
            raise ValueError("shard source claims differ from audited original rows")
    return dict(
        schema=SCHEMA,
        source_commit=commit,
        calibration_rows=len(original_cal),
        evaluation_rows=len(original_eval),
        shard_census=32,
        source_byte_replay=True,
        independent_semantic_judgement=False,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("calibration-shard", "evaluation-shard"):
        p = sub.add_parser(command)
        p.add_argument("prep", type=Path)
        p.add_argument("plan", type=Path)
        p.add_argument("inputs", type=Path)
        p.add_argument("model", type=Path)
        p.add_argument("calibration", type=Path)
        p.add_argument("output", type=Path)
        p.add_argument("--case", type=int, required=True)
        p.add_argument("--part", type=int, required=True)
        p.add_argument("--prep-sha")
        p.add_argument("--plan-sha")
        p.add_argument("--stage-sha", required=True)
        p.add_argument("--policy-sha")
    for command in ("calibration-collect", "evaluation-collect"):
        p = sub.add_parser(command)
        for field in ("prep", "plan", "inputs", "calibration", "shards", "output"):
            p.add_argument(field, type=Path)
        p.add_argument("--prep-sha")
        p.add_argument("--plan-sha")
        p.add_argument("--policy-sha")
    v = sub.add_parser("verify-release")
    v.add_argument("archive", type=Path)
    v.add_argument("original", type=Path)
    args = parser.parse_args()
    if args.command == "verify-release":
        print(json.dumps(verify_release(args.archive, args.original), allow_nan=False))
    elif args.command.endswith("-shard"):
        print(
            generate(
                args.command.split("-")[0],
                args.prep,
                args.plan,
                args.inputs,
                args.model,
                args.calibration,
                args.output,
                case_index=args.case,
                part=args.part,
                prep_sha=args.prep_sha,
                plan_sha=args.plan_sha,
                stage_sha=args.stage_sha,
                policy_sha=args.policy_sha,
            )
        )
    elif args.command == "calibration-collect":
        print(
            collect_calibration(
                args.prep, args.shards, args.output, prep_sha=args.prep_sha
            )
        )
    else:
        print(
            json.dumps(
                collect_evaluation(
                    args.plan,
                    args.inputs,
                    args.prep,
                    args.calibration,
                    args.shards,
                    args.output,
                    plan_sha=args.plan_sha,
                    policy_sha=args.policy_sha,
                ),
                allow_nan=False,
            )
        )


if __name__ == "__main__":
    main()
