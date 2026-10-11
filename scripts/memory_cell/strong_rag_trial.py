"""Actual-reader strong RAG top-k calibration and matched development evaluation.

Calibration answers are committed before calibration labels are opened. The
calibrator is given ONLY calibration scopes and their targets, never the final
plan or its target file. Evaluation runs in a new process with the frozen choice,
opens final labels only after all generated answers are fsynced, and counts every
attempt. These are previously exposed AUTHORED development tasks, not independent
future windows, a human sufficiency certificate or model improvement proof.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import time

from event_memory_trial import LIMIT, read, strict_identifier
from native import Document, Question, digest

SCHEMA = "hepta.memory-strong-rag.v1"
KS = (1, 2, 3, 4, 6)
EVAL_ARMS = (
    "selected_k",
    "hybrid_k4",
    "hybrid_k6",
    "hybrid_k4_reversed",
    "organized",
    "program_support",
    "empty",
)
HISTORIC_PLAN_SHA = "9840a25487af444914dca24c818d98ff798ebc1610ea8dfdd827187c31ad1897"
HISTORIC_COLLECTION_SHA = (
    "be47e85e87692fa0c5036ebf1aa6090e040334b70719a9103e880960e6a60da9"
)


def file_sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular pinned file required")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, obj):
    """No overwrite of a sealed artifact, and no nonfinite measurements."""
    with path.open("x", encoding="utf-8") as target:
        json.dump(obj, target, ensure_ascii=False, indent=2, allow_nan=False)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())


def commit_source():
    value = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("exact generating source commit required")
    return value


def documents(data):
    docs = tuple(Document(**(d | {"assets": tuple(d["assets"])})) for d in data)
    if len(docs) != len({d.identity for d in docs}):
        raise ValueError("duplicate original source identity")
    return {d.identity: d for d in docs}


def chosen_prefix(ids, k):
    if k not in KS or not isinstance(ids, (list, tuple)):
        raise ValueError("unregistered top-k candidate")
    if len(ids) != len(set(ids)) or not 1 <= len(ids) <= 32:
        raise ValueError("invalid frozen candidate ranking")
    return tuple(ids[:k])


def eval_selections(case, chosen_k):
    """Top-k arms see ONLY the fixed retrieved order, never oracle/support labels."""
    candidates = case["candidate_ids"]
    if digest(tuple(candidates)) != case["candidate_digest"]:
        raise ValueError("candidate pool drift")
    if chosen_k not in KS or not 4 <= len(candidates) <= 32:
        raise ValueError("invalid evaluator policy or candidate census")
    controls = case["controls"]
    if not {"organized", "program_support", "empty", "hybrid"}.issubset(controls):
        raise ValueError("existing controlled baseline required")
    if tuple(controls["hybrid"]["selected"]) != chosen_prefix(candidates, 4):
        raise ValueError("hybrid baseline no longer matches fixed retrieval")
    return {
        "selected_k": chosen_prefix(candidates, chosen_k),
        "hybrid_k4": chosen_prefix(candidates, 4),
        "hybrid_k6": chosen_prefix(candidates, 6),
        "hybrid_k4_reversed": tuple(reversed(chosen_prefix(candidates, 4))),
        "organized": tuple(controls["organized"]["selected"]),
        "program_support": tuple(controls["program_support"]["selected"]),
        "empty": (),
    }


def assert_calibration_publication(cases, sources, index_hashes):
    """Fail closed if an evaluation scope is exposed to the k calibrator."""
    calib_scopes = {case["query"]["scope"] for case in cases}
    if (
        len(cases) != 8
        or len(calib_scopes) != 8
        or calib_scopes != set(index_hashes)
        or calib_scopes != {d["scope"] for d in sources}
        or any(case["query"]["identity"] != case["query"]["scope"] for case in cases)
    ):
        raise ValueError("calibration artifact exposed a held-out scope or index")


def prepare(inputs, plan_dir, encoder_dir, output, *, plan_sha):
    """Read pinned source/index; export ONLY calibration scopes to calibrator."""
    from event_experience import question
    from event_projection import EventProjection
    from index import PersistentIndex, RetrievalPolicy
    from pretrained import Encoder

    commit = commit_source()
    if plan_sha != HISTORIC_PLAN_SHA:
        raise ValueError("frozen historic plan differs")
    locked = read(plan_dir / "plan.json", plan_sha)
    collection = read(inputs / "collection.json", HISTORIC_COLLECTION_SHA)
    if (
        locked["schema"] != "hepta.event-organization.plan.v1"
        or len(locked["cases"]) != 8
        or locked["token_limit"] != LIMIT
        or locked["frozen"]["collection_sha"] != HISTORIC_COLLECTION_SHA
        or locked["extraction"] != collection
    ):
        raise ValueError("original frozen event input required")
    encoder_pin = locked["frozen"]["encoder_sha"]
    encoder_info = read(encoder_dir / "inventory.json", encoder_pin)
    encoder = Encoder(encoder_dir / "encoder")
    if encoder.identity != encoder_info["digest"]:
        raise ValueError("encoder bytes/profile differ from fixed index")
    originals = documents(
        read(plan_dir / "source-view.json", locked["source_view_sha"])
    )
    specs = read(inputs / "questions.json", collection["files"]["questions.json"])
    labels = read(inputs / "labels.json", collection["files"]["labels.json"])
    if (
        len(specs) != 16
        or len(labels) != 16
        or len({s["id"] for s in specs}) != 16
        or len({l["id"] for l in labels}) != 16
        or {s["id"] for s in specs} != {l["id"] for l in labels}
        or sum(s["phase"] == "calibration" for s in specs) != 8
        or sum(s["phase"] == "test" for s in specs) != 8
    ):
        raise ValueError("incomplete fixed 8+8 development census")
    test_by_id = {c["query"]["identity"]: c for c in locked["cases"]}
    if {s["id"] for s in specs if s["phase"] == "test"} != set(test_by_id):
        raise ValueError("test question census drift")
    observed_at = locked["cases"][0]["query"]["observed_at"]
    weight = locked["selected_weight"]
    if type(weight) not in (float, int) or not 0 <= weight <= 1:
        raise ValueError("unregistered hybrid calibration weight")
    policy = RetrievalPolicy(top_k=32, channel_k=32, lexical_weight=weight)
    sources, cases, index_hashes = [], [], {}
    labels_by_id = {l["id"]: l for l in labels}
    calibration_ids = {s["id"] for s in specs if s["phase"] == "calibration"}
    for spec in specs:
        q, _ = question(spec, observed_at)
        scoped = tuple(d for d in originals.values() if d.scope == q.scope)
        projection = EventProjection(scoped)
        info = locked["frozen"]["costs"][q.scope]
        if not scoped or len(scoped) > 32:
            raise ValueError("unexpected scope documents")
        index = PersistentIndex(
            plan_dir / (q.scope + ".sqlite"),
            projection.frontier,
            set(),
            expected_file_digest=info["index_digest"],
            expected_encoder=encoder.identity,
        )
        try:
            selected, receipt = index.query(
                q,
                encoder.encode([q.content])[0],
                policy,
                current_cut=projection.frontier,
                revoked=set(),
            )
        finally:
            index.close()
        candidate_ids = tuple(d.identity for d in selected)
        if spec["phase"] == "test":
            # No test label is consulted; replay must reproduce exactly the
            # historical calibrated hybrid pool and its query/prompt bytes.
            older = test_by_id[q.identity]
            if (
                asdict(q) != older["query"]
                or list(candidate_ids) != older["candidate_ids"]
                or projection.frontier != older["frontier"]
                or digest(candidate_ids) != older["candidate_digest"]
            ):
                raise ValueError("cannot reproduce historical test retrieval")
            continue
        if q.identity not in calibration_ids or len(candidate_ids) < 4:
            raise ValueError("calibration isolation/candidate count")
        # Only calibration-scope indices may be published to the calibrator.
        index_hashes[q.scope] = info["index_digest"]
        sources.extend(asdict(d) for d in scoped)
        cases.append(
            dict(
                query=asdict(q),
                kind=spec["kind"],
                frontier=projection.frontier,
                candidate_ids=candidate_ids,
                candidate_digest=digest(candidate_ids),
                index_digest=info["index_digest"],
                retrieval=receipt,
            )
        )
    if len(cases) != 8 or len({d["identity"] for d in sources}) != len(sources):
        raise ValueError("incomplete/overlapping calibration sources")
    assert_calibration_publication(cases, sources, index_hashes)
    calibration_labels = [labels_by_id[c["query"]["identity"]] for c in cases]
    output.mkdir()
    dump(output / "calibration-sources.json", sources)
    dump(output / "calibration-labels.json", calibration_labels)
    dump(
        output / "calibration-plan.json",
        dict(
            schema=SCHEMA,
            source_commit=commit,
            historical_plan_sha256=plan_sha,
            historical_collection_sha256=HISTORIC_COLLECTION_SHA,
            encoder_inventory_sha256=encoder_pin,
            reader_profile="hepta.controlled-event.schema-expansion.v1",
            selected_prior_lexical_weight=weight,
            ks=KS,
            token_limit=LIMIT,
            cases=cases,
            calibration_only=True,
            test_cases_materialized=False,
            calibration_labels_sha256=file_sha(output / "calibration-labels.json"),
            calibration_sources_sha256=file_sha(output / "calibration-sources.json"),
            frozen_indices=index_hashes,
            human_sufficient_context_census=0,
            independent_sources=False,
            production_accepted=False,
        ),
    )
    return dict(
        cases=len(cases),
        encoder_sha256=encoder_pin,
        plan_sha256=file_sha(output / "calibration-plan.json"),
        calibration_only=True,
    )


def _bundle(query, selected, originals, *, frontier, arm):
    from evidence_bundle import EvidenceBundle, EvidenceSpan

    spans = []
    for key in selected:
        doc = originals[key]
        spans.append(
            EvidenceSpan(
                doc.identity,
                doc.root,
                doc.scope,
                doc.session,
                doc.observed_at,
                0,
                len(doc.content.encode()),
                doc.content,
                digest(doc.content),
            )
        )
    return EvidenceBundle(digest(asdict(query)), frontier, tuple(spans), arm)


def _journal_answers(reader, cases, originals, arms, selections, journal, *, seed):
    from native_citation import capture_native

    rows = []
    with journal.open("x", encoding="utf-8") as target:
        for case in cases:
            query = Question(**case["query"])
            for arm in arms:
                picked = selections(case, arm)
                row = dict(
                    question_id=query.identity,
                    kind=case["kind"],
                    arm=arm,
                    selected=list(picked),
                    candidate_digest=case["candidate_digest"],
                )
                try:
                    answer, receipt = reader.answer(
                        query,
                        _bundle(
                            query, picked, originals, frontier=case["frontier"], arm=arm
                        ),
                        originals,
                        frontier=case["frontier"],
                        revoked=set(),
                        token_limit=LIMIT,
                    )
                    audit = capture_native(
                        query,
                        answer,
                        dict(
                            input_ids_sha256=receipt["input_ids_digest"],
                            delivered_evidence=receipt["delivered_evidence"],
                        ),
                        experiment_digest=digest((seed, arm)),
                        family_digest=digest(query.family),
                    )
                    row.update(
                        status="succeeded",
                        answer=answer,
                        receipt=receipt,
                        citation_audit=audit,
                    )
                except Exception as error:
                    row.update(
                        status="failed",
                        error_type=type(error).__name__,
                        error=str(error)[:1024],
                    )
                target.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                target.flush()
                os.fsync(target.fileno())
                rows.append(row)
    reader.verify_frozen()
    return rows


def _score(rows, labels, *, expected, arms):
    """Score after journal fsync; keep all missing/failed attempts in denominator."""
    from event_experience import call_worker

    labels_by_id = {l["id"]: l for l in labels}
    if (
        len(expected) != len(set(expected))
        or set(expected) != set(labels_by_id)
        or {(r["question_id"], r["arm"]) for r in rows}
        != {(qid, arm) for qid in expected for arm in arms}
        or len(rows) != len(expected) * len(arms)
        or any(r["status"] not in ("succeeded", "failed") for r in rows)
    ):
        raise ValueError("incomplete scored task/arm census")
    for row in rows:
        if row["status"] == "failed":
            continue
        truth = labels_by_id[row["question_id"]]
        parsed = strict_identifier(row["answer"])
        row["parsed_identifier"] = parsed
        row["strict_task_success"] = parsed == truth["expected"]
        row["required_sources_covered"] = set(truth["support"]).issubset(
            row["selected"]
        )
        if truth["kind"] != row["kind"]:
            raise ValueError("task kind drift")
        if truth["kind"] == "procedure":
            verified = call_worker(
                dict(
                    operation="execute",
                    recipe=truth["procedure"],
                    supplied=parsed or "invalid_response",
                )
            )
            row["procedure_verification"] = verified
            row["strict_task_success"] = verified["exit_code"] == 0
    return rows


def _stats(rows, arms, expected):
    group = {}
    for row in rows:
        group.setdefault(row["question_id"], {})[row["arm"]] = row
    if set(group) != set(expected) or any(set(g) != set(arms) for g in group.values()):
        raise ValueError("missing paired group")
    stats = {}
    for arm in arms:
        records = [group[qid][arm] for qid in expected]
        observed = [r for r in records if r["status"] == "succeeded"]
        stats[arm] = dict(
            planned=len(records),
            succeeded=len(observed),
            failed=len(records) - len(observed),
            strict_success=sum(r["strict_task_success"] for r in observed),
            support_covered=sum(r["required_sources_covered"] for r in observed),
            input_tokens=sum(r["receipt"]["input_tokens"] for r in observed),
            output_tokens=sum(r["receipt"]["generated_tokens"] for r in observed),
            inference_seconds=sum(r["receipt"]["seconds"] for r in observed),
            per_kind={
                kind: dict(
                    planned=sum(r["kind"] == kind for r in records),
                    succeeded=sum(
                        r["kind"] == kind and r["status"] == "succeeded"
                        for r in records
                    ),
                    task_success=sum(
                        r["kind"] == kind and r.get("strict_task_success") is True
                        for r in records
                    ),
                )
                for kind in sorted({r["kind"] for r in records})
            },
        )
    return stats, group


def choose_k(rows, labels, expected):
    scored = _score(rows, labels, expected=expected, arms=tuple(f"k{k}" for k in KS))
    stats, _ = _stats(scored, tuple(f"k{k}" for k in KS), expected)
    if any(info["failed"] for info in stats.values()):
        return None, stats  # never silently choose on incomplete observations
    chosen = max(
        KS,
        key=lambda k: (
            stats[f"k{k}"]["strict_success"],
            -stats[f"k{k}"]["input_tokens"],
            -k,
        ),
    )
    return chosen, stats


def _reader(model_dir, stage_sha):
    from event_reader_view import EventPresentationReader

    staged = read(model_dir / "stage.json", stage_sha)
    inventory = read(model_dir / "inventory.json", staged["inventory_sha256"])
    if staged["tier"] != "qwen-3b":
        raise ValueError("only separately pinned stronger Qwen reference reader")
    return (
        EventPresentationReader(
            model_dir / "reader", expected_inventory=inventory["inventory_digest"]
        ),
        staged,
        inventory,
    )


def calibrate(prep, model_dir, output, *, prep_sha, stage_sha):
    commit = commit_source()
    locked = read(prep / "calibration-plan.json", prep_sha)
    if (
        locked["schema"] != SCHEMA
        or locked["historical_plan_sha256"] != HISTORIC_PLAN_SHA
        or tuple(locked["ks"]) != KS
        or len(locked["cases"]) != 8
        or not locked["calibration_only"]
        or locked["test_cases_materialized"]
        or locked["token_limit"] != LIMIT
    ):
        raise ValueError("must use frozen calibration-only manifest")
    originals = documents(
        read(prep / "calibration-sources.json", locked["calibration_sources_sha256"])
    )
    if not all(
        q["query"]["identity"] in {d.scope for d in originals.values()}
        for q in locked["cases"]
    ):
        raise ValueError("missing original calibration scope")
    reader, stage, inventory = _reader(model_dir, stage_sha)
    output.mkdir()
    dump(
        output / "run.json",
        dict(
            schema=SCHEMA,
            stage="calibration",
            source_commit=commit,
            calibration_sha256=prep_sha,
            model_stage_sha256=stage_sha,
            model=inventory,
            optimizer_executed=False,
            test_tasks_opened=False,
            human_reviewed=False,
            production_accepted=False,
        ),
    )
    started = time.perf_counter()
    arms = tuple(f"k{k}" for k in KS)
    rows = _journal_answers(
        reader,
        locked["cases"],
        originals,
        arms,
        lambda case, arm: chosen_prefix(case["candidate_ids"], int(arm[1:])),
        output / "raw-answers.jsonl",
        seed=prep_sha,
    )
    # Exactly here, AFTER every original answer was synced, open CALIBRATION-only labels.
    labels = read(prep / "calibration-labels.json", locked["calibration_labels_sha256"])
    expected = [case["query"]["identity"] for case in locked["cases"]]
    choice, statistics = choose_k(rows, labels, expected)
    dump(output / "scored-answers.json", rows)
    elapsed = time.perf_counter() - started
    report = dict(
        schema=SCHEMA,
        source_commit=commit,
        phase="calibration",
        planned_attempts=len(rows),
        frozen_k=choice,
        ks=KS,
        selection_objective="actual strict task success, then fewer observed input tokens, then smaller k",
        arms=statistics,
        total_elapsed_seconds=elapsed,
        reader_identity=inventory["inventory_digest"],
        model_stage_sha256=stage_sha,
        raw_answers_sha256=file_sha(output / "raw-answers.jsonl"),
        original_cases_are_exposed_development=True,
        statistical_superiority=False,
        independent_semantic_review=False,
        production_accepted=False,
    )
    dump(output / "report.json", report)
    if choice is None:
        raise ValueError(
            "incomplete calibration observations; no frozen selected baseline"
        )
    dump(
        output / "frozen-policy.json",
        dict(
            schema=SCHEMA,
            selected_k=choice,
            ks=KS,
            source_commit=commit,
            calibration_plan_sha256=prep_sha,
            original_test_plan_sha256=HISTORIC_PLAN_SHA,
            stage_sha256=stage_sha,
            reader_identity=inventory["inventory_digest"],
            raw_answers_sha256=report["raw_answers_sha256"],
            scored_answers_sha256=file_sha(output / "scored-answers.json"),
            selection_objective=report["selection_objective"],
            calibration_task_count=8,
            evaluation_task_count=8,
            frozen_before_evaluation=True,
            independent_source_families=0,
            candidate_accepted=False,
            production_accepted=False,
        ),
    )
    return report


def paired(group, left, right):
    wins = losses = ties = unknown = 0
    for rows in group.values():
        first, second = rows[left], rows[right]
        if first["status"] != "succeeded" or second["status"] != "succeeded":
            unknown += 1
        else:
            difference = int(second["strict_task_success"]) - int(
                first["strict_task_success"]
            )
            wins += difference > 0
            losses += difference < 0
            ties += difference == 0
    n = len(group)
    return dict(
        wins=wins,
        losses=losses,
        ties=ties,
        unknown_pairs=unknown,
        planned_delta_lower=(wins - losses - unknown) / n,
        planned_delta_upper=(wins - losses + unknown) / n,
        # These are missing-outcome bounds, NOT confidence intervals.
        interval_is_statistical=False,
    )


def evaluate(
    plan_dir,
    inputs,
    model_dir,
    calibration_dir,
    output,
    *,
    plan_sha,
    stage_sha,
    policy_sha,
):
    from event_reader_experiment import preflight

    commit = commit_source()
    locked_policy = read(calibration_dir / "frozen-policy.json", policy_sha)
    if (
        locked_policy["schema"] != SCHEMA
        or locked_policy["selected_k"] not in KS
        or locked_policy["original_test_plan_sha256"] != HISTORIC_PLAN_SHA
        or locked_policy["stage_sha256"] != stage_sha
        or plan_sha != HISTORIC_PLAN_SHA
        or not locked_policy["frozen_before_evaluation"]
        or locked_policy["candidate_accepted"]
    ):
        raise ValueError("policy not frozen or not bound to original test source")
    locked, originals = preflight(plan_dir, inputs, plan_sha)
    reader, stage, inventory = _reader(model_dir, stage_sha)
    if inventory["inventory_digest"] != locked_policy["reader_identity"]:
        raise ValueError("different reader between calibration and evaluation")
    output.mkdir()
    dump(
        output / "run.json",
        dict(
            schema=SCHEMA,
            phase="evaluation",
            source_commit=commit,
            policy_sha256=policy_sha,
            policy=locked_policy,
            test_plan_sha256=plan_sha,
            stage_sha256=stage_sha,
            model=inventory,
            original_case_census=len(locked["cases"]),
            training_during_query=False,
            new_future_sources=False,
            human_verified_sufficiency=False,
            production_accepted=False,
        ),
    )
    selections = {
        case["query"]["identity"]: eval_selections(case, locked_policy["selected_k"])
        for case in locked["cases"]
    }
    if len(selections) != len(locked["cases"]):
        raise ValueError("duplicate evaluation task")
    started = time.perf_counter()
    rows = _journal_answers(
        reader,
        locked["cases"],
        originals,
        EVAL_ARMS,
        lambda case, arm: selections[case["query"]["identity"]][arm],
        output / "raw-answers.jsonl",
        seed=digest((plan_sha, policy_sha)),
    )
    # Never open the original test answer labels until the full output is durable.
    labels = read(inputs / "labels.json", locked["labels_sha"])
    expected = [case["query"]["identity"] for case in locked["cases"]]
    test_labels = [row for row in labels if row["id"] in set(expected)]
    rows = _score(rows, test_labels, expected=expected, arms=EVAL_ARMS)
    dump(output / "scored-answers.json", rows)
    stats, group = _stats(rows, EVAL_ARMS, expected)
    pairs = {
        "selected_minus_hybrid4": paired(group, "hybrid_k4", "selected_k"),
        "organized_minus_selected": paired(group, "selected_k", "organized"),
        "organized_minus_hybrid4": paired(group, "hybrid_k4", "organized"),
        "reversed_minus_hybrid4": paired(group, "hybrid_k4", "hybrid_k4_reversed"),
        "hybrid6_minus_hybrid4": paired(group, "hybrid_k4", "hybrid_k6"),
    }
    report = dict(
        schema=SCHEMA,
        phase="evaluation",
        source_commit=commit,
        selected_k=locked_policy["selected_k"],
        test_task_count=len(expected),
        total_attempts=len(rows),
        success_by_arm=stats,
        paired_contrasts=pairs,
        source_and_index_costs=locked["frozen"]["costs"],
        extraction_costs=locked["extraction"],
        retained_original_source_bytes=sum(
            len(d.content.encode()) for d in originals.values()
        ),
        calibration_training_optimizer_seconds=0.0,
        reader_optimizer_seconds=0.0,
        wall_seconds=time.perf_counter() - started,
        raw_answers_sha256=file_sha(output / "raw-answers.jsonl"),
        citation_entailment_accuracy=None,
        missing_costs=["deployed retention", "revocation", "real recovery"],
        total_lifecycle_cost=None,
        prior_public_authored_exposed_development=True,
        independent_source_family_count=0,
        statistical_superiority=False,
        reader_capacity_gain_is_memory_gain=False,
        model_or_policy_accepted=False,
        production_accepted=False,
    )
    dump(output / "report.json", report)
    if any(row["status"] != "succeeded" for row in rows):
        raise ValueError(
            "failed model attempts preserved; complete evaluation not established"
        )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("prepare")
    for name in ("inputs", "plan", "encoder", "output"):
        pr.add_argument(name, type=Path)
    pr.add_argument("--plan-sha", required=True)
    ca = sub.add_parser("calibrate")
    for name in ("prep", "model", "output"):
        ca.add_argument(name, type=Path)
    ca.add_argument("--prep-sha", required=True)
    ca.add_argument("--stage-sha", required=True)
    ev = sub.add_parser("evaluate")
    for name in ("plan", "inputs", "model", "calibration", "output"):
        ev.add_argument(name, type=Path)
    ev.add_argument("--plan-sha", required=True)
    ev.add_argument("--stage-sha", required=True)
    ev.add_argument("--policy-sha", required=True)
    args = p.parse_args()
    if args.cmd == "prepare":
        result = prepare(
            args.inputs, args.plan, args.encoder, args.output, plan_sha=args.plan_sha
        )
    elif args.cmd == "calibrate":
        result = calibrate(
            args.prep,
            args.model,
            args.output,
            prep_sha=args.prep_sha,
            stage_sha=args.stage_sha,
        )
    else:
        result = evaluate(
            args.plan,
            args.inputs,
            args.model,
            args.calibration,
            args.output,
            plan_sha=args.plan_sha,
            stage_sha=args.stage_sha,
            policy_sha=args.policy_sha,
        )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
