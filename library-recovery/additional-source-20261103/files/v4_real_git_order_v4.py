"""Original-source pinned Reader rank-order counterfactual, research only.

No new source families or learned memory. Same evidence bytes and source markers,
forward lexical order vs reversed order; both Reader tiers use immutable weights.
Original journal and source verification are separate from scoring. No semantic
review, new parameter-learning win or production approval can be issued here.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
import os
import re
from pathlib import Path

from real_source_reader_probe import (
    EVALUATION, FROZEN_PLAN_SHA256 as V3_PIN, MARKER, SOURCE_CUT,
    SOURCE_SHA, REOPEN_SHA, TIERS, canonical, declarations, digest,
    expected_reader_delivery, hepta_json_digest, plan_from_archives,
    real_source, require, strict_json, write_once,
)

SCHEMA = "hepta.memory.real-git-order-counterfactual.v1"
ARMS = ("lexical_order", "reverse_order")
# This externally published plan digest must match the exact original-archive
# source-derived byte serialization. Never replace a frozen pin in place.
ORDER_PLAN_SHA256 = "a7e0b324e93e32059ab8d85166caa0f102fa787e54a81a37f802c7667ccafa77"


def build_order_plan(v3: dict) -> dict:
    require(v3.get("schema") == "hepta.memory.real-git-reader-function-probe.v3"
            and digest(canonical(v3) + b"\n") == V3_PIN,
            "source-derived v3 plan must be immutable before order test")
    cases = []
    for old in v3["cases"]:
        evidence = old["conditions"]["hybrid_k4"]
        require(2 <= len(evidence) <= 4, "bounded original lexical ranking required")
        # No target marker, mechanical oracle source or gold answer is exported
        # in the public Reader input for this rank-order stress test.
        cases.append(dict(
            id=old["id"], root=old["root"], question=old["question"],
            symbol=old["symbol"], source_identity_digest=old["source_identity_digest"],
            conditions={"lexical_order": evidence, "reverse_order": list(reversed(evidence))},
        ))
    require(len(cases) == 9 and len({x["id"] for x in cases}) == 9,
            "nine original mechanical tasks required")
    return dict(
        schema=SCHEMA, v3_source_plan_sha256=V3_PIN, source_zip_sha256=SOURCE_SHA,
        independent_reopen_zip_sha256=REOPEN_SHA,
        source_cut=SOURCE_CUT, families=list(EVALUATION),
        reader_tiers=list(TIERS), arms=list(ARMS), cases=cases,
        token_limit=1024, max_new_tokens=64, tools_allowed=False,
        evidence_bytes_order_only_permutation=True,
        oracle_or_target_in_reader_plan=False, observed_real_model_calls=0,
        independent_human_semantic_review=False, trained_memory_compared=False,
        production_qualified=False,
    )


def plan_from_sources(source_zip: Path, reopen_zip: Path) -> dict:
    return build_order_plan(plan_from_archives(source_zip, reopen_zip))


def locked_order_plan(path: Path, pinned: str) -> dict:
    require(path.is_file() and not path.is_symlink() and
            path.stat().st_size <= 2_000_000 and
            pinned == ORDER_PLAN_SHA256 == digest(path.read_bytes()),
            "original rank-order precommitted plan SHA mismatch")
    result = strict_json(path.read_bytes())
    require(result.get("schema") == SCHEMA and result.get("arms") == list(ARMS)
            and result.get("reader_tiers") == list(TIERS)
            and result.get("v3_source_plan_sha256") == V3_PIN
            and result.get("token_limit") == 1024
            and result.get("max_new_tokens") == 64
            and result.get("production_qualified") is False,
            "new rank-order plan is not the declared research profile")
    require(len(result.get("cases", [])) == 9, "complete nine-case plan required")
    for row in result["cases"]:
        require(set(row["conditions"]) == set(ARMS) and
                row["conditions"]["reverse_order"] == list(reversed(row["conditions"]["lexical_order"]))
                and 2 <= len(row["conditions"]["lexical_order"]) <= 4,
                "only source-order perturbations permitted")
    return result


def request_objects(case: dict, arm: str):
    from evidence_bundle import EvidenceBundle, EvidenceSpan
    from native import Document, Question, digest as native_digest
    q = Question(case["id"], case["root"], case["id"], case["question"],
                 "2026-10-15T00:00:00Z")
    frontier = native_digest((case["root"], case["source_identity_digest"]))
    original, spans = {}, []
    for e in case["conditions"][arm]:
        content = e["text"]
        doc = Document(native_digest((case["id"], e["marker"], content)),
                       case["root"] + ":" + e["blob_sha"],
                       case["id"], "real-git-blob", SOURCE_CUT, content)
        require(doc.identity not in original, "duplicate rank source")
        original[doc.identity] = doc
        spans.append(EvidenceSpan(doc.identity, doc.root, doc.scope,
                                  doc.session, doc.observed_at, 0,
                                  len(content.encode()), content, native_digest(content)))
    return q, frontier, original, EvidenceBundle(native_digest(asdict(q)), frontier,
                                                  tuple(spans), arm)


def generate(plan: dict, tier: str, stage: Path, stage_sha: str, output: Path) -> dict:
    """Real frozen model execution, all attempts journaled before scoring."""
    from reader_reference import ReferenceReader, MODELS, verify_files
    from reviewed_bundle import strict_read
    require(tier in TIERS and stage.is_dir() and not output.exists(),
            "registered Reader tier and new output required")
    receipt = strict_read(stage / "stage.json", stage_sha, 1024 * 1024)
    require(receipt.get("tier") == tier and
            (receipt.get("repository"), receipt.get("revision")) == MODELS[tier],
            "staged original publisher tier differs")
    publisher = strict_read(stage / "publisher.json", receipt["publisher_sha256"], 1024 * 1024)
    verify_files(stage / "reader", publisher["files"])
    inventory = strict_read(stage / "inventory.json", receipt["inventory_sha256"], 1024 * 1024)
    reader = ReferenceReader(stage / "reader", expected_inventory=inventory["inventory_digest"])
    output.mkdir(parents=False)
    target = output / "original-generation.jsonl"
    with target.open("x", encoding="utf-8") as handle:
        for case in plan["cases"]:
            for arm in ARMS:
                q, frontier, originals, bundle = request_objects(case, arm)
                row = dict(case_id=case["id"], arm=arm, tier=tier,
                           question_sha256=digest(case["question"].encode()),
                           evidence_sha256=digest(canonical(case["conditions"][arm])),
                           reader_identity=reader.identity, reader_profile=reader.profile,
                           status="failed", answer=None, receipt=None)
                try:
                    answer, usage = reader.answer(q, bundle, originals,
                                                  frontier=frontier, revoked=set(),
                                                  token_limit=plan["token_limit"])
                    row.update(status="succeeded", answer=answer, receipt=usage)
                except Exception as exc:
                    row["error"] = type(exc).__name__ + ": " + str(exc)[:512]
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                        allow_nan=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
    reader.verify_frozen()
    rows = [strict_json(line) for line in target.read_bytes().splitlines()]
    require(len(rows) == len(plan["cases"]) * len(ARMS),
            "incomplete frozen Reader attempt census")
    return dict(tier=tier, planned=len(rows), successful=sum(x["status"] == "succeeded" for x in rows),
                original_journal_sha256=digest(target.read_bytes()),
                reader_identity=reader.identity, reader_profile=reader.profile,
                production_qualified=False)


def pinned_journal(path: Path, original_sha: str) -> list:
    require(path.is_file() and not path.is_symlink() and
            0 < path.stat().st_size <= 4_000_000 and
            len(original_sha) == 64 and digest(path.read_bytes()) == original_sha,
            "independently pinned original Reader journal required")
    data = path.read_bytes()
    require(data.endswith(b"\n") and len(data.splitlines()) == 18,
            "complete 18-attempt original Reader journal required")
    rows = [strict_json(line) for line in data.splitlines()]
    require(all(isinstance(row, dict) for row in rows), "original output row objects required")
    return rows


def score(plan: dict, source_archive: tuple, journals: dict) -> dict:
    """Source-first mechanical adjudication; rank controls and Reader paired per case."""
    from real_source_rank_null import rank_only_audit
    from real_source_reader_probe import build_plan as v3_build
    files, blobs = source_archive
    v3 = v3_build(files, blobs)
    require(canonical(plan) == canonical(build_order_plan(v3))
            and digest(canonical(plan) + b"\n") == ORDER_PLAN_SHA256,
            "post-run ranking not original source/frozen plan")
    require(set(journals) == set(TIERS), "both frozen tier original journals required")
    rank3 = rank_only_audit(v3, source_archive)
    original_target_by_case = {}
    for case in plan["cases"]:
        matching = []
        for entry in files:
            if (entry["repo"] != case["root"] or entry["partition"] != "evaluation"
                    or not entry["path"].endswith((".py", ".rs"))):
                continue
            try:
                decoded = blobs[(case["root"], entry["path"])].decode("utf-8")
            except UnicodeDecodeError:
                continue
            if case["symbol"] in [name for name, _ in declarations(decoded)]:
                matching.append(entry["path"])
        require(len(matching) == 1, "original Git declaration ambiguous")
        original_target_by_case[case["id"]] = matching[0]
    summaries = {}
    for tier in TIERS:
        original = journals[tier]
        require(isinstance(original, list) and len(original) == 18,
                "complete original model attempt array required")
        by_case = {}
        identity_set = set()
        for row in original:
            require(isinstance(row, dict) and row.get("tier") == tier and
                    row.get("arm") in ARMS and
                    row.get("case_id") in original_target_by_case,
                    "unexpected model answer or tier")
            key = (row["case_id"], row["arm"])
            require(key not in by_case, "duplicate original Reader attempt")
            by_case[key] = row
            case = next(c for c in plan["cases"] if c["id"] == row["case_id"])
            require(row.get("question_sha256") == digest(case["question"].encode())
                    and row.get("evidence_sha256") == digest(canonical(case["conditions"][row["arm"]])),
                    "original question/evidence changed after generation")
            require(row.get("status") in ("succeeded", "failed"), "original inference status")
            if row["status"] == "succeeded":
                require(isinstance(row.get("answer"), str) and
                        isinstance(row.get("receipt"), dict),
                        "original answer and token receipts required")
                bound = expected_reader_delivery(case, row["arm"])
                receipt = row["receipt"]
                require(all(receipt.get(k) == v for k, v in bound.items()) and
                        receipt.get("reader_identity") == row.get("reader_identity") and
                        receipt.get("reader_profile") == row.get("reader_profile") and
                        type(receipt.get("input_tokens")) is int and
                        0 < receipt["input_tokens"] <= plan["token_limit"] and
                        type(receipt.get("generated_tokens")) is int and
                        0 < receipt["generated_tokens"] <= plan["max_new_tokens"] and
                        type(receipt.get("seconds")) in (int, float) and
                        0 <= receipt["seconds"] < 7200 and
                        receipt.get("trainable_parameters") == 0 and
                        receipt.get("answer_postprocessed") is False and
                        receipt.get("production_accepted") is False and
                        len(receipt.get("input_ids_digest", "")) == 64 and
                        len(receipt.get("generated_ids_digest", "")) == 64,
                        "delivered source/model/token/frozen receipt drift")
                identity_set.add((row["reader_identity"], row["reader_profile"]))
            else:
                require(row.get("answer") is None and row.get("receipt") is None,
                        "failed execution may not have a scored answer")
        require(set(by_case) == {(c["id"], a) for c in plan["cases"] for a in ARMS},
                "incomplete Reader arm/case census")
        require(len(identity_set) == 1, "mixed or missing real frozen Reader identities")
        per_arm = {}
        for arm in ARMS:
            per_root, rows, successes = defaultdict(list), [], 0
            for case in plan["cases"]:
                row = by_case[(case["id"], arm)]
                evidence = case["conditions"][arm]
                target = original_target_by_case[case["id"]]
                expected = next((e["marker"] for e in evidence if e["path"] == target), None)
                require(expected is not None, "target source missing in original lexical pool")
                idx = next(i for i,e in enumerate(evidence,1) if e["path"] == target)
                guess = evidence[0]["marker"]
                answer = row["answer"] if row["status"] == "succeeded" else ""
                matched = MARKER.fullmatch(answer)
                correct = bool(matched and matched.group(1) == expected)
                citations = set(int(v) for v in re.findall(r"\[E([1-9][0-9]*)\]", answer))
                exact_cited = correct and citations == {idx}
                null_correct = guess == expected
                successes += int(row["status"] == "succeeded")
                item = dict(id=case["id"], root=case["root"], reader_correct=correct,
                            null_rank_one_correct=null_correct, correct_with_exact_citation=exact_cited,
                            inference_succeeded=row["status"] == "succeeded",
                            original_answer_sha256=digest(answer.encode()) if answer else None)
                per_root[case["root"]].append(item)
                rows.append(item)
            wins = sum(x["reader_correct"] and not x["null_rank_one_correct"] for x in rows)
            losses = sum(x["null_rank_one_correct"] and not x["reader_correct"] for x in rows)
            roots = {k:(sum(x["reader_correct"] - x["null_rank_one_correct"] for x in v)/len(v))
                     for k,v in per_root.items()}
            per_arm[arm] = dict(attempts=len(rows),successful_calls=successes,
                                reader_correct=sum(x["reader_correct"] for x in rows),
                                exact_target_citation=sum(x["correct_with_exact_citation"] for x in rows),
                                first_rank_null_correct=sum(x["null_rank_one_correct"] for x in rows),
                                reader_wins=wins,reader_losses=losses, ties=len(rows)-wins-losses,
                                family_effects=roots,independent_ci=None,cases=rows)
        a = {x["id"]:x for x in per_arm[ARMS[0]]["cases"]}
        b = {x["id"]:x for x in per_arm[ARMS[1]]["cases"]}
        per_arm["source_order_sensitivity"] = dict(
            lexical_only_wins=sum(a[k]["reader_correct"] and not b[k]["reader_correct"] for k in a),
            reverse_only_wins=sum(b[k]["reader_correct"] and not a[k]["reader_correct"] for k in a),
            equal_outcomes=sum(a[k]["reader_correct"] == b[k]["reader_correct"] for k in a),
            same_evidence_bytes=True,only_order_changes=True,
            oracle_independent_semantics=False,
        )
        summaries[tier] = per_arm
    # A distinct tier must really have a distinct Reader weight inventory.
    # A mere tier label cannot manufacture a stronger reference model.
    require(len({next(iter({(r["reader_identity"], r["reader_profile"])
                   for r in journals[tier] if r["status"] == "succeeded"}))[0]
                 for tier in TIERS}) == len(TIERS),
            "frozen reference tier must have a distinct model identity")
    require(summaries[TIERS[0]]["lexical_order"]["first_rank_null_correct"] == 7 and
            summaries[TIERS[0]]["reverse_order"]["first_rank_null_correct"] == 1,
            "incorrect frozen order baseline")
    return dict(schema="hepta.memory.real-git-order-counterfactual-postrun.v1",
                plan_sha256=ORDER_PLAN_SHA256,v3_sha256=V3_PIN,
                source_zip_sha256=SOURCE_SHA,reopen_zip_sha256=REOPEN_SHA,
                reader_executions_total=sum(summaries[t][a]["successful_calls"]
                                            for t in TIERS for a in ARMS),
                attempted_reader_calls=36,
                mechanical_null_rank1_original=7,mechanical_null_rank1_reversed=1,
                result=summaries,
                no_new_model_calls_during_scoring=True,
                independent_model_authentication=False,
                independent_semantic_judgement=False,
                newly_independent_source_families=False,
                learned_parameter_gain_established=False,
                causal_code_comprehension_certified=False,
                lifecycle_tco=None,production_qualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    p=parser.add_subparsers(dest="command",required=True)
    prepare=p.add_parser("prepare")
    prepare.add_argument("--source-zip",type=Path,required=True)
    prepare.add_argument("--reopen-zip",type=Path,required=True)
    prepare.add_argument("--plan",type=Path,required=True)
    run=p.add_parser("run")
    run.add_argument("--plan",type=Path,required=True)
    run.add_argument("--plan-sha256",required=True)
    run.add_argument("--tier",choices=TIERS,required=True)
    run.add_argument("--model",type=Path,required=True)
    run.add_argument("--stage-sha256",required=True)
    run.add_argument("--output",type=Path,required=True)
    post=p.add_parser("score")
    post.add_argument("--plan",type=Path,required=True)
    post.add_argument("--plan-sha256",required=True)
    post.add_argument("--source-zip",type=Path,required=True)
    post.add_argument("--reopen-zip",type=Path,required=True)
    for tier in TIERS:
        post.add_argument("--"+tier,type=Path,required=True)
        post.add_argument("--"+tier+"-sha256",required=True)
    post.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    if args.command=="prepare":
        result=plan_from_sources(args.source_zip,args.reopen_zip)
        write_once(args.plan,canonical(result)+b"\n")
        print(json.dumps({"plan_sha256":digest(args.plan.read_bytes()),"cases":9,
                          "zero_model_calls":True},sort_keys=True))
    elif args.command=="run":
        result=generate(locked_order_plan(args.plan,args.plan_sha256),args.tier,
                        args.model,args.stage_sha256,args.output)
        write_once(args.output/"generation-report.json",canonical(result)+b"\n")
        print(json.dumps(result,sort_keys=True))
    else:
        plan=locked_order_plan(args.plan,args.plan_sha256)
        original={tier:pinned_journal(getattr(args,tier.replace("-","_")),
                                      getattr(args,tier.replace("-","_")+"_sha256"))
                  for tier in TIERS}
        value=score(plan,real_source(args.source_zip,args.reopen_zip),original)
        write_once(args.output,canonical(value)+b"\n")
        print(json.dumps({"attempts":36,"successful":value["reader_executions_total"],
                          "production_qualified":False},sort_keys=True))


if __name__=="__main__":
    main()
