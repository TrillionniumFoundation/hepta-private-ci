"""Separate, pinned external-Git metadata Memory diagnostic: 40 + 72 calls.

Original Memory source pins and scorers remain untouched. This adapter reuses
the original frozen reader, lossless event view, retrieval primitives, evidence
selection and observed-call journal. Its procedure scorer checks a fixed Git
object-type predicate. Every projection is explicitly derived from original
captured bytes; no result is an independent semantic or production certificate.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time

from event_experience import question
from event_memory_trial import LIMIT, read, strict_identifier
from event_projection import EventProjection, Lookup
from external_git_projection import PRECOMMIT_SHA, SCHEMA as COLLECTION_SCHEMA, load_receipt, verify_admission
from capture_git_objects import object_sha, sha256
from measured_strong_rag import CallObserver
from native import Question, digest
from strong_rag_trial import (
    EVAL_ARMS, KS, MAX_READER_CALL_SECONDS, _bundle, _journal_answers, _reader,
    _stats, chosen_prefix, documents, dump, eval_selections, file_sha, paired,
)

SCHEMA = "hepta.external-git-event-trial.v1"
ORIGINAL_COMMIT = "2f8c5678d19713ed4d532768f245a4810b139377"
MODEL_REVISION = "82f42baa094a9600e39ccd80d34058aeeb3abbc1"
STAGE_SHA = "ceae3536947e7c84e5d55a8c93491654aa388c91961d504ccede6d5650785ba9"
ENCODER_SHA = "4159d748e05f31f8c2c9bfd145d54591e79e8ba2995e9f846bd95d50ff9697a8"


def utc():
    return datetime.now(timezone.utc).isoformat()


def source_identity():
    import strong_rag_trial
    root = Path(strong_rag_trial.__file__).resolve().parents[2]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if head != ORIGINAL_COMMIT:
        raise ValueError("inherited reader checkout commit changed")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "scripts/memory_cell"],
                   cwd=root, check=True, stdout=subprocess.DEVNULL)
    return dict(inherited_source_commit=head,
                adapter_files={p.name: file_sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
                inherited_modules={p.name: file_sha(p) for p in sorted(
                    (root / "scripts/memory_cell").glob("*.py"))})


def collection(inputs, expected_sha):
    manifest = read(inputs / "collection.json", expected_sha)
    if (manifest["schema"] != COLLECTION_SCHEMA or manifest["precommit_sha256"] != PRECOMMIT_SHA
            or manifest["task_count"] != 8 or manifest["production_accepted"]):
        raise ValueError("external prospective collection contract changed")
    proof = read(inputs / "projection-proof.json", manifest["files"]["projection-proof.json"])
    if len(proof["cases"]) != 8:
        raise ValueError("projection source proof census changed")
    for case in proof["cases"]:
        receipt, _, _, _, receipt_sha = load_receipt(Path(case["source_receipt_path"]))
        if receipt_sha != case["source_receipt_sha256"] or receipt["entry"]["repo"] != case["repository"]:
            raise ValueError("original source receipt detached from projection")
    if manifest["phase"] == "evaluation":
        for name in ("selection-admission.json", "selected-pairs.json", "calibration-source-boundary.json"):
            read(inputs / name, manifest["files"][name])
        verified = verify_admission(inputs / "selection-admission.json", inputs / "selected-pairs.json",
            inputs / "calibration-source-boundary.json", [Path(c["source_receipt_path"]) for c in proof["cases"]])
        if manifest["selection_proof"] != verified:
            raise ValueError("selector proof detached from the actual evaluation collection")
    return manifest


def prepare(inputs, encoder_dir, output, *, collection_sha, calibration_plan=None, calibration_plan_sha=None):
    """Read source/support only. Actual expected-answer labels remain unopened."""
    from index import PersistentIndex, RetrievalPolicy
    from pretrained import Encoder
    from runtime_preflight import configure_torch
    import torch

    configure_torch(torch, bounded=False)
    started = time.perf_counter()
    manifest = collection(inputs, collection_sha)
    phase = manifest["phase"]
    catalogue = read(encoder_dir / "inventory.json", ENCODER_SHA)
    original_list = read(inputs / "sources.json", manifest["files"]["sources.json"])
    originals = documents(original_list)
    public = read(inputs / "questions.json", manifest["files"]["questions.json"])
    support = read(inputs / "program-support.json", manifest["files"]["program-support.json"])
    if len(public) != 8 or {s["id"] for s in public} != {d.scope for d in originals.values()}:
        raise ValueError("exact eight scopes required")
    if set(support) != {s["id"] for s in public}:
        raise ValueError("privileged support census changed")
    if phase == "evaluation":
        old = read(calibration_plan / "plan.json", calibration_plan_sha)
        if old["phase"] != "calibration" or old["schema"] != SCHEMA:
            raise ValueError("frozen calibration retrieval policy required")
        if set(manifest["source_repositories"]) & set(old["source_collection"]["source_repositories"]):
            raise ValueError("repository family crossed calibration/evaluation")
        if set(manifest["exact_source_object_ids"]) & set(old["source_collection"]["exact_source_object_ids"]):
            raise ValueError("exact original source object crossed phases")
    elif phase != "calibration" or calibration_plan is not None:
        raise ValueError("unregistered phase")
    output.mkdir()
    dump(output / "source-view.json", original_list)
    encoder = Encoder(encoder_dir / "encoder")
    if encoder.identity != catalogue["digest"]:
        raise ValueError("encoder inventory drift")
    projections, indices, costs = {}, {}, {}
    try:
        for scope in sorted({d.scope for d in originals.values()}):
            before = time.perf_counter()
            scoped = tuple(d for d in originals.values() if d.scope == scope)
            proj = EventProjection(scoped)
            projected = time.perf_counter()
            vectors = encoder.encode([d.content for d in scoped])
            encoded = time.perf_counter()
            index_path = output / (scope + ".sqlite")
            identity = PersistentIndex.build(index_path, scoped, vectors, encoder.identity, proj.frontier)
            indices[scope] = PersistentIndex(index_path, proj.frontier, set(),
                                             expected_file_digest=identity, expected_encoder=encoder.identity)
            projections[scope] = proj
            costs[scope] = dict(projection_seconds=projected-before, encoding_seconds=encoded-projected,
                                index_seconds=time.perf_counter()-encoded, index_bytes=index_path.stat().st_size,
                                index_digest=identity, derived_event_source_bytes=proj.source_bytes)
        queries = {s["id"]: question(s, utc()) for s in public}
        before = time.perf_counter()
        vectors = {qid: encoder.encode([q.content])[0] for qid, (q, _) in queries.items()}
        encoding_seconds = time.perf_counter()-before
        tuning = []
        if phase == "calibration":
            for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
                recalls = []
                for qid, (query, _) in queries.items():
                    found, _ = indices[qid].query(query, vectors[qid],
                        RetrievalPolicy(top_k=4, channel_k=32, lexical_weight=weight),
                        current_cut=projections[qid].frontier, revoked=set())
                    required = set(support[qid])
                    if not required or not required.issubset(projections[qid].facts):
                        raise ValueError("invalid calibration support")
                    recalls.append(len(required & {d.identity for d in found}) / len(required))
                tuning.append(dict(weight=weight, mean_support_recall=sum(recalls)/8))
            chosen_weight = max(tuning, key=lambda r: (r["mean_support_recall"], -abs(r["weight"]-0.5)))["weight"]
        else:
            chosen_weight = old["selected_lexical_weight"]
        cases = []
        for spec in public:
            qid = spec["id"]
            query, lookup = queries[qid]
            proj = projections[qid]
            found, retrieval = indices[qid].query(query, vectors[qid],
                RetrievalPolicy(top_k=32, channel_k=32, lexical_weight=chosen_weight),
                current_cut=proj.frontier, revoked=set())
            candidates = tuple(d.identity for d in found)
            controls = {}
            for mode in ("hybrid", "entity_time", "organized"):
                selected, info = proj.select(lookup, candidates, mode=mode, revoked=set())
                controls[mode] = dict(selected=selected, selection=info)
            first, first_info = proj.select(Lookup(lookup.entity, (lookup.path[0],), lookup.revision),
                                            candidates, mode="entity_time", revoked=set())
            controls["single_hop"] = dict(selected=first, selection=first_info)
            required = tuple(support[qid])
            if not 1 <= len(required) <= 4 or not set(required).issubset(proj.facts):
                raise ValueError("invalid explicitly privileged program support")
            controls.update(program_support=dict(selected=required), empty=dict(selected=[]))
            cases.append(dict(query=asdict(query), kind=spec["kind"], candidate_ids=candidates,
                              candidate_digest=digest(candidates), frontier=proj.frontier,
                              retrieval=retrieval, controls=controls))
        dump(output / "plan.json", dict(
            schema=SCHEMA, phase=phase, precommit_sha256=PRECOMMIT_SHA,
            source_collection_sha256=collection_sha, source_collection=manifest,
            source_view_sha256=file_sha(output / "source-view.json"),
            cases=cases, ks=KS, evaluation_arms=EVAL_ARMS, token_limit=LIMIT,
            labels_sha256=manifest["files"]["labels.json"], questions_sha256=manifest["files"]["questions.json"],
            selected_lexical_weight=chosen_weight, calibration_retrieval_tuning=tuning,
            inherited_calibration_plan_sha256=calibration_plan_sha,
            encoder_inventory_sha256=ENCODER_SHA, measured_source_index_costs=costs,
            query_encoding_seconds=encoding_seconds, planning_seconds=time.perf_counter()-started,
            source_identity=source_identity(), expected_answer_labels_opened=False,
            support_oracle_is_privileged=True, projection_is_external_original=False,
            production_accepted=False,
        ))
    finally:
        for index in indices.values():
            index.close()


def verify_procedure(procedure, parsed):
    if parsed not in procedure["modes"]:
        return dict(executed=False, predicate_success=False, reason="unregistered model identifier")
    identifier = procedure["modes"][parsed]
    if not re.fullmatch(r"[0-9a-f]{40}", identifier) or procedure["required_stdout"] != "tree\n":
        raise ValueError("fixed procedure object or predicate changed")
    receipt_path = Path(procedure["source_receipt_path"])
    receipt, _, _, _, receipt_sha = load_receipt(receipt_path)
    if (receipt_sha != procedure["source_receipt_sha256"]
            or Path(procedure["bare_git_dir"]).resolve() != (receipt_path.parent / "objects.git").resolve()):
        raise ValueError("scoring object store detached from original capture")
    matches = [info for info in receipt["original_objects"] if info["git_sha1"] == identifier]
    if len(matches) != 1 or matches[0]["kind"] not in ("tree", "commit"):
        raise ValueError("scoring object missing from original publisher-bound receipt")
    expected_object = matches[0]
    argv = ["git", "-c", "core.hooksPath=/dev/null", "--git-dir", procedure["bare_git_dir"],
            "cat-file", "-t", identifier]
    isolated_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    isolated_env.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1",
                        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
    started = time.perf_counter()
    completed = subprocess.run(argv, capture_output=True, timeout=10, env=isolated_env)
    raw_argv = argv[:-3] + ["cat-file", expected_object["kind"], identifier]
    raw = subprocess.run(raw_argv, capture_output=True, timeout=10, env=isolated_env)
    if (completed.returncode != 0 or completed.stdout != (expected_object["kind"] + "\n").encode()
            or raw.returncode != 0 or sha256(raw.stdout) != expected_object["sha256"]
            or object_sha(expected_object["kind"], raw.stdout) != identifier):
        raise ValueError("actual scoring Git object bytes/type drifted after capture")
    return dict(executed=True, argv=argv, exit_code=completed.returncode,
                stdout_base64=base64.b64encode(completed.stdout).decode(),
                stderr_base64=base64.b64encode(completed.stderr).decode(),
                measured_seconds=time.perf_counter()-started,
                raw_object_argv=raw_argv, raw_object_sha256=sha256(raw.stdout),
                raw_object_git_sha1=identifier, raw_object_bytes=len(raw.stdout),
                raw_object_stdout_base64=base64.b64encode(raw.stdout).decode(),
                raw_object_stderr_base64=base64.b64encode(raw.stderr).decode(),
                source_receipt_sha256=receipt_sha, git_replace_objects_disabled=True,
                inherited_git_environment_removed=True, global_system_git_configuration_disabled=True,
                predicate_success=completed.returncode == 0 and completed.stdout == b"tree\n",
                process_exit_zero_alone_is_success=False)


def score(rows, labels, expected, arms):
    truth = {label["id"]: label for label in labels}
    if (set(truth) != set(expected) or len(truth) != len(labels)
            or len(rows) != len(expected)*len(arms)
            or {(r["question_id"], r["arm"]) for r in rows} != {(q, a) for q in expected for a in arms}):
        raise ValueError("complete paired task/arm census required")
    for row in rows:
        if row["status"] == "failed":
            continue
        if row["status"] != "succeeded":
            raise ValueError("unregistered model attempt status")
        label = truth[row["question_id"]]
        if label["kind"] != row["kind"]:
            raise ValueError("kind drift")
        parsed = strict_identifier(row["answer"])
        row.update(parsed_identifier=parsed, strict_task_success=parsed == label["expected"],
                   required_sources_covered=set(label["support"]).issubset(row["selected"]))
        if row["kind"] == "procedure":
            verification = verify_procedure(label["procedure"], parsed)
            row["procedure_verification"] = verification
            row["strict_task_success"] &= verification["predicate_success"]
    return rows


def prompt_preflight(plan, originals, model, output, chosen_k):
    from transformers import AutoTokenizer
    from event_reader_view import event_prompt
    tokenizer = AutoTokenizer.from_pretrained(model / "reader", local_files_only=True, trust_remote_code=False)
    checks = []
    for case in plan["cases"]:
        query = Question(**case["query"])
        selections = ({f"k{k}": chosen_prefix(case["candidate_ids"], k) for k in KS}
                      if plan["phase"] == "calibration" else eval_selections(case, chosen_k))
        for arm, picked in selections.items():
            ids, receipt = event_prompt(tokenizer, query,
                _bundle(query, picked, originals, frontier=case["frontier"], arm=arm),
                originals, frontier=case["frontier"], revoked=set(), token_limit=LIMIT)
            checks.append(dict(question_id=query.identity, arm=arm, input_tokens=len(ids),
                               input_ids_digest=receipt["input_ids_digest"]))
    dump(output / "prompt-budget-preflight.json", dict(
        token_limit=LIMIT, planned_calls=len(checks), checks=checks,
        model_called=False, all_selected_event_json_delivered_losslessly=True))


def run(plan_dir, inputs, model, output, *, plan_sha, calibration=None, policy_sha=None):
    identity = source_identity()
    plan = read(plan_dir / "plan.json", plan_sha)
    phase = plan["phase"]
    if (plan["schema"] != SCHEMA or plan["precommit_sha256"] != PRECOMMIT_SHA
            or len(plan["cases"]) != 8 or tuple(plan["ks"]) != KS
            or tuple(plan["evaluation_arms"]) != EVAL_ARMS or plan["token_limit"] != LIMIT):
        raise ValueError("new external profile plan drift")
    if plan["source_identity"] != identity:
        raise ValueError("adapter or inherited source changed after plan freeze")
    manifest = collection(inputs, plan["source_collection_sha256"])
    if manifest != plan["source_collection"]:
        raise ValueError("collection detached from plan")
    originals = documents(read(plan_dir / "source-view.json", plan["source_view_sha256"]))
    chosen_k = None
    if phase == "evaluation":
        policy = read(calibration / "frozen-policy.json", policy_sha)
        if (policy["schema"] != SCHEMA or policy["selected_k"] not in KS
                or policy["calibration_plan_sha256"] != plan["inherited_calibration_plan_sha256"]
                or policy["stage_sha256"] != STAGE_SHA or not policy["frozen_before_evaluation"]
                or policy["adapter_source_digest"] != digest(identity)):
            raise ValueError("separate frozen calibration policy required")
        chosen_k = policy["selected_k"]
    elif phase != "calibration" or calibration is not None:
        raise ValueError("phase/policy contract changed")
    output.mkdir()
    prompt_preflight(plan, originals, model, output, chosen_k)
    dump(output / "run.json", dict(
        schema=SCHEMA, phase=phase, started_at=utc(), source_identity=identity,
        plan_sha256=plan_sha, stage_sha256=STAGE_SHA, model_revision=MODEL_REVISION,
        policy_sha256=policy_sha, prompt_preflight_sha256=file_sha(output / "prompt-budget-preflight.json"),
        hostname=platform.node(), temporary_execution_container=True,
        dedicated_project_host_attested=False, expected_labels_opened=False,
        original_memory112_pins_unchanged=True, per_call_stop_seconds=MAX_READER_CALL_SECONDS,
        mode="SHADOW_ONLY", authority="DENY_ALL", release="NO_GO", production_accepted=False,
    ))
    with (output / "calls.jsonl").open("x", encoding="utf-8") as journal:
        observer = CallObserver(journal)
        started = time.perf_counter()
        try:
            reader, staged, inventory = _reader(model, STAGE_SHA)
            observer.attach(reader)
            import torch
            from runtime_preflight import capture_runtime
            dump(output / "runtime-preflight.json", capture_runtime(torch, bounded=False))
            load_seconds = time.perf_counter()-started
            arms = tuple(f"k{k}" for k in KS) if phase == "calibration" else EVAL_ARMS
            selection = (lambda case, arm: chosen_prefix(case["candidate_ids"], int(arm[1:]))) if phase == "calibration" else (
                lambda case, arm: eval_selections(case, chosen_k)[arm])
            rows = _journal_answers(reader, plan["cases"], originals, arms, selection,
                                    output / "raw-answers.jsonl", seed=digest((plan_sha, policy_sha)))
            # Only after all planned answers have been fsynced, open phase labels.
            labels = read(inputs / "labels.json", plan["labels_sha256"])
            expected = [case["query"]["identity"] for case in plan["cases"]]
            score(rows, labels, expected, arms)
            dump(output / "scored-answers.json", rows)
            stats, groups = _stats(rows, arms, expected)
            if phase == "calibration":
                chosen_k = (None if any(s["failed"] for s in stats.values()) else
                    max(KS, key=lambda k: (stats[f"k{k}"]["strict_success"],
                                         -stats[f"k{k}"]["input_tokens"], -k)))
            from historical_event_citation_chain import audit_evaluation
            public = read(inputs / "questions.json", plan["questions_sha256"])
            try:
                formal = audit_evaluation(rows, public, labels, originals, expected_qids=expected, arms=arms)
            except ValueError as error:
                # Invalid model citations are retained as audit failure; they
                # do not get repaired or silently removed from the task census.
                formal = dict(status="audit_failed", error_type=type(error).__name__,
                              error=str(error), measured_citation_success=None,
                              independent_semantic_adjudication=False)
            report = dict(
                schema=SCHEMA, phase=phase, selected_k=chosen_k, task_count=8, total_calls=len(rows),
                success_by_arm=stats, formal_projection_citation_chain=formal,
                source_family_proxy_count=8, independent_family_certification=False,
                raw_answers_sha256=file_sha(output / "raw-answers.jsonl"),
                observed_calls_sha256=file_sha(output / "calls.jsonl"),
                model_load_seconds=load_seconds, wall_seconds=time.perf_counter()-started,
                plan_sha256=plan_sha, reader_identity=inventory["inventory_digest"],
                source_and_index_costs=plan["measured_source_index_costs"],
                optimizer_executed=False, optimizer_seconds=0.0, physical_flops=None, energy_joules=None,
                billed_cost=None, total_lifecycle_cost=None,
                independently_reviewed_semantic_entailment=None, independent_semantic_review=False,
                evidence_is_projected_git_metadata=True, natural_language_understanding_claim=False,
                statistical_superiority=False, mode="SHADOW_ONLY", authority="DENY_ALL",
                release="NO_GO", production_accepted=False,
            )
            if phase == "evaluation":
                report["paired_contrasts"] = {
                    "selected_minus_hybrid4": paired(groups, "hybrid_k4", "selected_k"),
                    "organized_minus_selected": paired(groups, "selected_k", "organized"),
                    "single_hop_minus_hybrid4": paired(groups, "hybrid_k4", "single_hop"),
                    "entity_time_minus_single_hop": paired(groups, "single_hop", "entity_time"),
                    "organized_minus_entity_time": paired(groups, "entity_time", "organized"),
                    "organized_minus_hybrid4": paired(groups, "hybrid_k4", "organized"),
                }
            dump(output / "report.json", report)
            if any(r["status"] != "succeeded" for r in rows):
                raise ValueError("failed model attempts retained; complete phase not established")
            if phase == "calibration":
                dump(output / "frozen-policy.json", dict(
                    schema=SCHEMA, selected_k=chosen_k, ks=KS, calibration_plan_sha256=plan_sha,
                    stage_sha256=STAGE_SHA, reader_identity=inventory["inventory_digest"],
                    adapter_source_digest=digest(identity),
                    raw_answers_sha256=report["raw_answers_sha256"],
                    scored_answers_sha256=file_sha(output / "scored-answers.json"),
                    selection_objective="exact recorded mapped identifier, fewer actual input tokens, smaller k",
                    frozen_at=utc(), frozen_before_evaluation=True, production_accepted=False,
                ))
            print(json.dumps({"phase": phase, "completed_calls": len(rows), "selected_k": chosen_k}), flush=True)
        finally:
            dump(output / "completion.json", dict(
                completed_at=utc(), observed_calls=observer.ordinal,
                call_journal_sha256=file_sha(output / "calls.jsonl"),
                phase_success_requires_report=True, production_accepted=False,
            ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    for name in ("inputs", "encoder", "output"):
        prepare_parser.add_argument(name, type=Path)
    prepare_parser.add_argument("--collection-sha", required=True)
    prepare_parser.add_argument("--calibration-plan", type=Path)
    prepare_parser.add_argument("--calibration-plan-sha")
    run_parser = commands.add_parser("run")
    for name in ("plan", "inputs", "model", "output"):
        run_parser.add_argument(name, type=Path)
    run_parser.add_argument("--plan-sha", required=True)
    run_parser.add_argument("--calibration", type=Path)
    run_parser.add_argument("--policy-sha")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.inputs, args.encoder, args.output, collection_sha=args.collection_sha,
                calibration_plan=args.calibration_plan, calibration_plan_sha=args.calibration_plan_sha)
    else:
        run(args.plan, args.inputs, args.model, args.output, plan_sha=args.plan_sha,
            calibration=args.calibration, policy_sha=args.policy_sha)


if __name__ == "__main__":
    main()
