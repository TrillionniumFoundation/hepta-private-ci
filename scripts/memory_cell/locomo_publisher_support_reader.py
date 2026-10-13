"""Publisher-support-only frozen Qwen intervention on the ORIGINAL LoCoMo 16.

This is a PRIVILEGED diagnostic, NOT retrieval: publisher support labels choose
evidence before generation. Reference answers never enter model inputs. No
independent human sufficiency, memory-learning or promotion claim is possible.
"""
import argparse
import json
import os
from pathlib import Path
import re

from locomo_frozen_reader_pair import (
    LIMIT, bundle_for, frozen_qwen_cpu_threads, metric, original_document,
    source_plan, write_once,
)
from locomo_ninearm_source_replay import ZIPS, canonical, read_zip, sha, strict_json
from locomo_sufficiency_worklist import pinned_zip, verify_inputs

SCHEMA = "hepta.locomo.publisher-support-reader.v1"
PLANNED = 16
MODES = ("publisher_support", "unanswerable_empty", "support_unavailable")
BASE_ARMS = ("lexical_k4", "lexical_k8")
ORIGINAL_READER_SHA = "7160ede72114b04135e544fb687a804dc0c4852834cf1695440a75b85214bf48"


def proposed(cases, documents, targets):
    """Build an answer-text-free plan from LABEL-PRIVILEGED support IDs."""
    if (len(cases) != PLANNED or len({c["question_id"] for c in cases}) != PLANNED
            or len({c["family_proxy_digest"] for c in cases}) != 2
            or set(targets) != {c["question_id"] for c in cases}):
        raise ValueError("original fixed LoCoMo population required")
    rows = []
    for case in cases:
        target = targets[case["question_id"]]
        support, unresolved = target.get("support"), target.get("unresolved_support")
        if (type(target.get("unanswerable")) is not bool
                or not isinstance(support, list) or not isinstance(unresolved, list)
                or any(type(s) is not str or not s for s in support + unresolved)
                or len(set(support + unresolved)) != len(support + unresolved)
                or not set(support + unresolved) <= set(case["source_ids"])):
            raise ValueError("bad publisher source membership or answerability")
        if target["unanswerable"]:
            if support or unresolved:
                raise ValueError("unanswerable example has publisher support")
            mode, selected = "unanswerable_empty", []
        elif not support or unresolved or len(support) > 8:
            # Missing/partial/too-large support must not become no-evidence truth.
            mode, selected = "support_unavailable", []
        else:
            mode = "publisher_support"
            selected = [sid for sid in case["source_ids"] if sid in set(support)]
        if len(selected) != len(support) and mode == "publisher_support":
            raise ValueError("lost original support identity")
        if any(documents[sid]["scope"] != case["scope"] for sid in selected):
            raise ValueError("publisher support crosses original source scope")
        rows.append(dict(
            question_id=case["question_id"],
            family_proxy_digest=case["family_proxy_digest"],
            source_census_sha256=case["source_census_sha256"],
            mode=mode, selected=selected,
            support_count=len(support),
            unresolved_count=len(unresolved),
        ))
    return rows


def plan(public_dir, target_dir, output):
    cases, documents, _ = source_plan(public_dir)
    raw_targets = read_zip(target_dir, "evaluation")["targets.json"]
    targets = strict_json(raw_targets)
    rows = proposed(cases, documents, targets)
    # Export only IDs, never the actual gold answer, reviewer text or scoring.
    payload = dict(
        schema=SCHEMA + ".plan.v1", cases=rows,
        original_public_zip_sha256=ZIPS["public"][1],
        original_decisions_zip_sha256=ZIPS["decisions"][1],
        publisher_target_zip_sha256=ZIPS["evaluation"][1],
        publisher_targets_sha256=sha(raw_targets),
        publisher_support_selection_is_privileged=True,
        retrieval_policy_comparator=False,
        model_receives_answer_text=False,
        independent_source_review=False,
        production_accepted=False,
    )
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "plan.json", canonical(payload) + b"\n")
    print(json.dumps(dict(planned=len(rows), modes={
        m: sum(r["mode"] == m for r in rows) for m in MODES
    }), sort_keys=True))
    return payload


def validate_plan(payload, cases, documents):
    if (payload.get("schema") != SCHEMA + ".plan.v1"
            or payload.get("original_public_zip_sha256") != ZIPS["public"][1]
            or payload.get("original_decisions_zip_sha256") != ZIPS["decisions"][1]
            or payload.get("publisher_target_zip_sha256") != ZIPS["evaluation"][1]
            or payload.get("publisher_support_selection_is_privileged") is not True
            or payload.get("retrieval_policy_comparator") is not False
            or payload.get("model_receives_answer_text") is not False
            or payload.get("independent_source_review") is not False
            or payload.get("production_accepted") is not False):
        raise ValueError("missing privileged-source admission boundary")
    if set(payload) != {
        "schema", "cases", "original_public_zip_sha256",
        "original_decisions_zip_sha256", "publisher_target_zip_sha256",
        "publisher_targets_sha256", "publisher_support_selection_is_privileged",
        "retrieval_policy_comparator", "model_receives_answer_text",
        "independent_source_review", "production_accepted",
    } or not re.fullmatch(r"[a-f0-9]{64}", payload["publisher_targets_sha256"]):
        raise ValueError("plan cannot contain answer labels or extra metadata")
    rows = payload["cases"]
    if not isinstance(rows, list) or len(rows) != PLANNED or len(cases) != PLANNED:
        raise ValueError("wrong publisher-support plan census")
    for case, row in zip(cases, rows, strict=True):
        if not isinstance(row, dict) or set(row) != {
            "question_id", "family_proxy_digest", "source_census_sha256",
            "mode", "selected", "support_count", "unresolved_count",
        }:
            raise ValueError("unexpected privileged plan field")
        if any(row[k] != case[k] for k in (
            "question_id", "family_proxy_digest", "source_census_sha256"
        )):
            raise ValueError("original question identity changed")
        selected = row["selected"]
        if (row["mode"] not in MODES or not isinstance(selected, list)
                or len(selected) > 8 or len(set(selected)) != len(selected)
                or any(type(s) is not str or s not in case["source_ids"] for s in selected)
                or any(documents[s]["scope"] != case["scope"] for s in selected)
                or type(row["support_count"]) is not int
                or type(row["unresolved_count"]) is not int
                or not 0 <= row["support_count"] <= len(case["source_ids"])
                or not 0 <= row["unresolved_count"] <= len(case["source_ids"])
                or (row["mode"] == "publisher_support" and
                    (not selected or row["support_count"] != len(selected) or row["unresolved_count"]))
                or (row["mode"] != "publisher_support" and selected)
                or (row["mode"] == "unanswerable_empty" and
                    (row["support_count"] or row["unresolved_count"]))):
            raise ValueError("source-only selection or unknown/empty distinction drift")
    return rows


def generate(public_dir, model_dir, plan_dir, output):
    from event_memory_trial import read
    from reader_reference import MODELS, ReferenceReader
    import torch

    cases, documents, _ = source_plan(public_dir)
    plan_bytes = (plan_dir / "plan.json").read_bytes()
    selection = strict_json(plan_bytes)
    rows = validate_plan(selection, cases, documents)
    stage_bytes = (model_dir / "stage.json").read_bytes()
    stage = strict_json(stage_bytes)
    if (stage["tier"] != "qwen-3b"
            or (stage["repository"], stage["revision"]) != MODELS["qwen-3b"]
            or stage["production_accepted"] is not False):
        raise ValueError("not the original frozen research Qwen")
    inventory = read(model_dir / "inventory.json", stage["inventory_sha256"])
    frozen_qwen_cpu_threads(torch)
    reader = ReferenceReader(
        model_dir / "reader", expected_inventory=inventory["inventory_digest"]
    )
    reader.verify_frozen()
    originals = {k: original_document(v) for k, v in documents.items()}
    output.mkdir(parents=True, exist_ok=False)
    original_rows = []
    with (output / "raw-answers.jsonl").open("xb") as stream:
        for case, selected in zip(cases, rows, strict=True):
            item = dict(
                question_id=case["question_id"], mode=selected["mode"],
                selected=selected["selected"],
                family_proxy_digest=case["family_proxy_digest"],
                source_census_sha256=case["source_census_sha256"],
            )
            if selected["mode"] == "support_unavailable":
                item.update(status="unavailable", reason="incomplete_publisher_support")
            else:
                try:
                    q, bundle = bundle_for(
                        case, "publisher_support", originals, selected["selected"]
                    )
                    answer, receipt = reader.answer(
                        q, bundle,
                        {k: originals[k] for k in selected["selected"]},
                        frontier=case["source_census_sha256"],
                        revoked=set(), token_limit=LIMIT,
                    )
                    item.update(status="succeeded", answer=answer, receipt=receipt)
                except Exception as exc:
                    item.update(status="failed", error_type=type(exc).__name__,
                                error_detail=str(exc)[:384])
            stream.write(canonical(item) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
            original_rows.append(item)
    reader.verify_frozen()
    commit = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[a-f0-9]{40}", commit):
        raise ValueError("exact source commit required")
    raw = (output / "raw-answers.jsonl").read_bytes()
    ready = dict(
        schema=SCHEMA, generating_commit=commit,
        reader_identity=reader.identity, reader_profile=reader.profile,
        reader_stage_sha256=sha(stage_bytes),
        original_public_zip_sha256=ZIPS["public"][1],
        original_decisions_zip_sha256=ZIPS["decisions"][1],
        privileged_plan_sha256=sha(plan_bytes),
        original_gold_answers_accessible_to_generator=False,
        publisher_support_retrieval_privileged=True,
        weight_updates=0, unmodified_frozen_reader=True,
        raw_sha256=sha(raw), planned=PLANNED,
        succeeded=sum(x["status"] == "succeeded" for x in original_rows),
        failed=sum(x["status"] == "failed" for x in original_rows),
        unavailable=sum(x["status"] == "unavailable" for x in original_rows),
        semantic_citation_precision=None, production_accepted=False,
    )
    write_once(output / "READY.json", canonical(ready) + b"\n")
    print(json.dumps({k:v for k,v in ready.items() if "identity" not in k}))
    return ready


def paired_deltas(cases, rows, original, targets):
    """Bound all missing outcomes; scores are diagnostic token F1, never entailment."""
    if len(rows) != PLANNED or len(original) != PLANNED * 2:
        raise ValueError("incomplete original Reader census")
    old = {(r["question_id"], r["arm"]): r for r in original}
    if len(old) != PLANNED * 2:
        raise ValueError("duplicate original Reader result")
    result = {}
    categories = ("all", "answerable", "unanswerable", "support_seen_by_k4",
                  "support_missing_by_k4")
    for comparator in BASE_ARMS:
        result[comparator] = {}
        for cohort in categories:
            paired = complete = missing = wins = losses = ties = 0
            old_sum = new_sum = 0.
            for case, row in zip(cases, rows, strict=True):
                target = targets[case["question_id"]]
                annotated = set(target["support"])
                k4 = old[case["question_id"], "lexical_k4"]["selected"]
                want = (
                    cohort == "all"
                    or cohort == "answerable" and not target["unanswerable"]
                    or cohort == "unanswerable" and target["unanswerable"]
                    or cohort == "support_seen_by_k4" and not target["unanswerable"]
                       and bool(annotated) and annotated <= set(k4)
                    or cohort == "support_missing_by_k4" and not target["unanswerable"]
                       and bool(annotated) and not annotated <= set(k4)
                )
                if not want:
                    continue
                paired += 1
                reference = old[case["question_id"], comparator]
                if row["status"] != "succeeded" or reference["status"] != "succeeded":
                    missing += 1
                    continue
                a, b = metric(reference["answer"], target), metric(row["answer"], target)
                if not a["eligible"] or not b["eligible"]:
                    missing += 1
                    continue
                complete += 1
                old_sum += a["f1"]
                new_sum += b["f1"]
                diff = b["f1"] - a["f1"]
                wins += diff > 0
                losses += diff < 0
                ties += diff == 0
            result[comparator][cohort] = dict(
                planned=paired, complete=complete, missing_or_unscored=missing,
                source_free_reader_success_baseline_f1=old_sum/complete if complete else None,
                privileged_support_reader_f1=new_sum/complete if complete else None,
                wins=wins, losses=losses, ties=ties,
                all_planned_delta_bounds=[
                    (new_sum-old_sum-missing)/paired,
                    (new_sum-old_sum+missing)/paired
                ] if paired else None,
                missing_bounds_are_not_confidence_intervals=True,
            )
    return result


def score(public_dir, target_dir, plan_dir, generation_dir, original_zip, output,
          *, expected_commit):
    cases, documents, decisions = source_plan(public_dir)
    plan_bytes = (plan_dir / "plan.json").read_bytes()
    plan_data = strict_json(plan_bytes)
    admitted = validate_plan(plan_data, cases, documents)
    source = strict_json((generation_dir / "READY.json").read_bytes())
    raw = (generation_dir / "raw-answers.jsonl").read_bytes()
    rows = [strict_json(x) for x in raw.splitlines()]
    if (source["schema"] != SCHEMA
            or source["generating_commit"] != expected_commit
            or source["privileged_plan_sha256"] != sha(plan_bytes)
            or source["raw_sha256"] != sha(raw)
            or source["original_public_zip_sha256"] != ZIPS["public"][1]
            or source["original_decisions_zip_sha256"] != ZIPS["decisions"][1]
            or source["weight_updates"] != 0
            or source["original_gold_answers_accessible_to_generator"] is not False
            or source["production_accepted"] is not False
            or len(raw) > 2 * 1024 * 1024
            or len(rows) != PLANNED
            or len({r["question_id"] for r in rows}) != PLANNED):
        raise ValueError("missing original publisher-support generation")
    originals = {k: original_document(v) for k, v in documents.items()}
    for case, expected, row in zip(cases, admitted, rows, strict=True):
        if any(row.get(k) != v for k, v in dict(
            question_id=case["question_id"], mode=expected["mode"],
            selected=expected["selected"],
            family_proxy_digest=case["family_proxy_digest"],
            source_census_sha256=case["source_census_sha256"],
        ).items()):
            raise ValueError("model row changed selection or family")
        if row["status"] == "succeeded":
            _, bundle = bundle_for(case, "publisher_support", originals, expected["selected"])
            r = row["receipt"]
            if (r["reader_identity"] != source["reader_identity"]
                    or r["reader_profile"] != source["reader_profile"]
                    or r["token_limit"] != LIMIT
                    or r["trainable_parameters"] != 0
                    or r["answer_postprocessed"] is not False
                    or r["delivered_evidence"] != bundle.delivered()
                    or type(row.get("answer")) is not str or not row["answer"].strip()):
                raise ValueError("actual frozen-reader response or bytes drift")
        elif row["status"] == "unavailable":
            if expected["mode"] != "support_unavailable" or "answer" in row:
                raise ValueError("unavailable source became an answer")
        elif row["status"] == "failed":
            if "answer" in row or "receipt" in row:
                raise ValueError("failed source intervention has invented answer")
        else:
            raise ValueError("unknown original execution status")
    if sum(r["status"] == "succeeded" for r in rows) != source["succeeded"] or (
        sum(r["status"] == "failed" for r in rows) != source["failed"]
    ) or sum(r["status"] == "unavailable" for r in rows) != source["unavailable"]:
        raise ValueError("original result status census differs from committed manifest")
    public = pinned_zip(public_dir / ZIPS["public"][0], "public")
    decisions_bytes = pinned_zip(public_dir / ZIPS["decisions"][0], "decisions")
    old_archive = pinned_zip(original_zip, "reader")
    _, _, _, original_rows, original_ready = verify_inputs(
        public, decisions_bytes, old_archive
    )
    if (source["reader_identity"] != original_ready["model_identity"]
            or source["reader_profile"] != original_ready["model_profile"]):
        raise ValueError("frozen Qwen changed across reader interventions")
    gold_bytes = read_zip(target_dir, "evaluation")["targets.json"]
    targets = strict_json(gold_bytes)
    if (sha(gold_bytes) != plan_data["publisher_targets_sha256"]
            or proposed(cases, documents, targets) != admitted):
        raise ValueError("publisher selection was changed after original generation")
    contrasts = paired_deltas(cases, rows, original_rows, targets)
    report = dict(
        schema=SCHEMA + ".diagnostic.v1",
        generating_commit=expected_commit,
        original_reader_commit=original_ready["generating_commit"],
        original_32_answers_sha256=original_ready["raw_journal_sha256"],
        privileged_16_answers_sha256=sha(raw),
        original_publisher_target_sha256=sha(gold_bytes),
        reader_identity=source["reader_identity"],
        model_calls_executed=source["succeeded"] + source["failed"],
        privileged_source_selection=True,
        publisher_support_not_independent_sufficiency=True,
        lexical_baselines_unchanged=True,
        contrasts=contrasts,
        independent_family_n=0,
        semantic_citation_precision=None,
        parameter_memory_gain=None,
        production_accepted=False,
    )
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "report.json", canonical(report) + b"\n")
    print(json.dumps(report))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    actions = ap.add_subparsers(dest="command", required=True)
    p = actions.add_parser("plan")
    p.add_argument("public", type=Path)
    p.add_argument("evaluation", type=Path)
    p.add_argument("output", type=Path)
    g = actions.add_parser("generate")
    g.add_argument("public", type=Path)
    g.add_argument("model", type=Path)
    g.add_argument("plan", type=Path)
    g.add_argument("output", type=Path)
    s = actions.add_parser("score")
    for item in ("public", "evaluation", "plan", "generation", "original", "output"):
        s.add_argument(item, type=Path)
    s.add_argument("--expected-commit", required=True)
    args = ap.parse_args()
    if args.command == "plan":
        plan(args.public, args.evaluation, args.output)
    elif args.command == "generate":
        generate(args.public, args.model, args.plan, args.output)
    else:
        score(args.public, args.evaluation, args.plan, args.generation,
              args.original, args.output, expected_commit=args.expected_commit)


if __name__ == "__main__":
    main()
