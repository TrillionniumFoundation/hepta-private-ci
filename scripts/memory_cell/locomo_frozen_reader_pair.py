"""Actual matched frozen-reader LoCoMo k4/k8 experiment; no learning claim.

Generation accepts ONLY the two sealed public source ZIPs. The evaluation answer
ZIP is opened exclusively by the separate offline scorer after raw model output
and the model/input receipt have been committed. Publisher source support is not
human-certified sufficient context and neither diagnostic F1 nor citation-label
presence is independent entailment.
"""

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import string

from evidence_bundle import EvidenceBundle, EvidenceSpan
from locomo_ninearm_source_replay import (
    ZIPS,
    canonical,
    check_roles,
    compute,
    load_public,
    read_zip,
    sha,
    strict_json,
    verify_original_six,
)
from native import Document, Question, digest
from locomo_reader_paired_cost import (
    audit_matched_costs,
    verify_immutable_generation_record,
)

ARMS = ("lexical_k4", "lexical_k8")
LIMIT = 2048
PLANNED = 16
REFUSAL = "I do not have enough evidence."
SCHEMA = "hepta.memorycell.locomo-frozen-reader-pair.v1"
CITE = re.compile(r"\[E[1-9][0-9]*\]")


def source_plan(root):
    check_roles(root)
    population, documents = load_public(root)
    decision_rows = compute(population, documents)
    if verify_original_six(root, decision_rows) != 480:
        raise ValueError("published decisions were not reproduced")
    decisions = {
        (row["question_id"], row["arm"]): row for row in decision_rows
    }
    cases = population["splits"]["evaluation"]
    if len(cases) != PLANNED or len({c["question_id"] for c in cases}) != PLANNED:
        raise ValueError("original evaluation census drift")
    if len({c["family_proxy_digest"] for c in cases}) != 2:
        raise ValueError("original evaluation families drift")
    for case in cases:
        small = decisions[(case["question_id"], ARMS[0])]["selected"]
        large = decisions[(case["question_id"], ARMS[1])]["selected"]
        if len(small) != 4 or len(large) != 8 or small != large[:4]:
            raise ValueError("frozen lexical selections or order drift")
        for arm in ARMS:
            selected = decisions[(case["question_id"], arm)]
            if (selected["source_census_sha256"] != case["source_census_sha256"]
                    or selected["family_proxy_digest"] != case["family_proxy_digest"]
                    or any(k not in documents for k in selected["selected"])):
                raise ValueError("frozen source identities drift")
    return cases, documents, decisions


def query_for(case):
    return Question(
        case["question_id"],
        case["family_proxy_digest"],
        case["scope"],
        case["question"],
        case["observation_time"],
    )


def original_document(value):
    return Document(**(value | {"assets": tuple(value["assets"])}))


def bundle_for(case, arm, original, selected):
    query = query_for(case)
    spans = []
    for key in selected:
        doc = original[key]
        if doc.scope != query.scope:
            raise ValueError("cross-scope evidence was selected")
        raw = doc.content.encode("utf-8", "strict")
        spans.append(
            EvidenceSpan(
                doc.identity, doc.root, doc.scope, doc.session, doc.observed_at,
                0, len(raw), doc.content, digest(doc.content),
            )
        )
    bundle = EvidenceBundle(
        digest(asdict(query)), case["source_census_sha256"], tuple(spans), arm
    )
    bundle.validate(
        query, {key: original[key] for key in selected},
        frontier=case["source_census_sha256"], revoked=set(),
    )
    return query, bundle


def unique_rows(rows, cases, decisions):
    expected = [
        (case["question_id"], arm) for case in cases for arm in ARMS
    ]
    if len(rows) != len(expected) or [
        (r["question_id"], r["arm"]) for r in rows
    ] != expected:
        raise ValueError("missing, reordered or duplicate model execution")
    profiles = set()
    for row in rows:
        key = (row["question_id"], row["arm"])
        decision = decisions[key]
        if (
            row["selected"] != decision["selected"]
            or row["source_census_sha256"] != decision["source_census_sha256"]
            or row["family_proxy_digest"] != decision["family_proxy_digest"]
            or row["status"] not in ("succeeded", "failed")
        ):
            raise ValueError("post-generation original retrieval drift")
        if row["status"] == "succeeded":
            if not isinstance(row.get("answer"), str) or not row["answer"].strip():
                raise ValueError("empty actual model answer")
            receipt = row["receipt"]
            profiles.add((receipt["reader_identity"], receipt["reader_profile"]))
            if (
                receipt["token_limit"] != LIMIT
                or type(receipt["input_tokens"]) is not int
                or receipt["input_tokens"] > LIMIT
                or type(receipt["generated_tokens"]) is not int
                or receipt["generated_tokens"] > 64
                or receipt["trainable_parameters"] != 0
                or receipt["answer_postprocessed"] is not False
            ):
                raise ValueError("reader, decoder or budget drift")
            delivered = receipt["delivered_evidence"]
            if len(delivered) != len(row["selected"]) or [
                d["original_id"] for d in delivered
            ] != row["selected"]:
                raise ValueError("actual source presentation drift")
        elif ("answer" in row or "receipt" in row):
            raise ValueError("failed run smuggled a successful response")
    if len(profiles) > 1:
        raise ValueError("different frozen reader profiles between arms")
    return profiles


def write_once(path, raw):
    if path.exists() or path.is_symlink():
        raise ValueError("immutable output already exists")
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def generate(public_root, model_root, output):
    from reader_reference import MODELS, ReferenceReader
    from event_memory_trial import read

    cases, documents, decisions = source_plan(public_root)
    stage_raw = (model_root / "stage.json").read_bytes()
    stage = strict_json(stage_raw)
    if (
        stage["tier"] != "qwen-3b"
        or (stage["repository"], stage["revision"]) != MODELS["qwen-3b"]
        or stage["production_accepted"] is not False
    ):
        raise ValueError("not the pinned research-only Qwen reference")
    inventory = read(
        model_root / "inventory.json", stage["inventory_sha256"]
    )
    reader = ReferenceReader(
        model_root / "reader",
        expected_inventory=inventory["inventory_digest"],
    )
    reader.verify_frozen()
    original = {k: original_document(v) for k, v in documents.items()}
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    with (output / "raw-answers.jsonl").open("xb") as journal:
        for case in cases:
            for arm in ARMS:
                decision = decisions[(case["question_id"], arm)]
                selected = decision["selected"]
                row = dict(
                    question_id=case["question_id"], arm=arm,
                    family_proxy_digest=case["family_proxy_digest"],
                    source_census_sha256=case["source_census_sha256"],
                    selected=selected,
                )
                try:
                    query, bundle = bundle_for(case, arm, original, selected)
                    answer, receipt = reader.answer(
                        query, bundle,
                        {key: original[key] for key in selected},
                        frontier=case["source_census_sha256"],
                        revoked=set(), token_limit=LIMIT,
                    )
                    row.update(status="succeeded", answer=answer, receipt=receipt)
                except Exception as error:
                    row.update(
                        status="failed", error_type=type(error).__name__,
                        error_detail=str(error)[:384],
                    )
                journal.write(canonical(row) + b"\n")
                journal.flush()
                os.fsync(journal.fileno())
                rows.append(row)
    reader.verify_frozen()
    unique_rows(rows, cases, decisions)
    raw = (output / "raw-answers.jsonl").read_bytes()
    head = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ValueError("exact generating commit required")
    manifest = dict(
        schema=SCHEMA, generating_commit=head,
        original_source_sha256=ZIPS["public"][1],
        original_six_decisions_sha256=ZIPS["decisions"][1],
        model_stage_sha256=sha(stage_raw),
        model_identity=reader.identity, model_profile=reader.profile,
        planned_questions=PLANNED, planned_arms=list(ARMS),
        planned_model_calls=PLANNED * len(ARMS), actual_model_calls=len(rows),
        succeeded=sum(r["status"] == "succeeded" for r in rows),
        failed=sum(r["status"] == "failed" for r in rows),
        input_token_ceiling=LIMIT, generated_token_ceiling=64,
        labels_seen_during_generation=False,
        weight_updates=0, original_answers_rewritten=False,
        raw_journal_sha256=sha(raw),
        independent_source_authentication=False,
        semantic_citation_precision=None, production_accepted=False,
    )
    verify_immutable_generation_record(
        manifest, raw, rows,
        expected_commit=head,
        public_zip_sha256=ZIPS["public"][1],
        decisions_zip_sha256=ZIPS["decisions"][1],
    )
    write_once(output / "READY.json", canonical(manifest) + b"\n")
    print(json.dumps({k: v for k, v in manifest.items()
                      if k not in ("model_identity", "model_profile")}))
    return manifest


def normalized(value):
    without_cites = CITE.sub("", value).lower()
    without_punctuation = "".join(
        c for c in without_cites if c not in string.punctuation
    )
    return " ".join(re.sub(r"\b(a|an|the)\b", " ", without_punctuation).split())


def metric(answer, target):
    if target["unanswerable"]:
        v = float(answer.strip() == REFUSAL)
        return dict(em=v, f1=v, eligible=True)
    gold = target.get("answer")
    if not isinstance(gold, str) or not gold.strip():
        return dict(em=None, f1=None, eligible=False)
    a, b = normalized(answer).split(), normalized(gold).split()
    common = sum((Counter(a) & Counter(b)).values())
    f1 = 2 * common / (len(a) + len(b)) if a and b else float(a == b)
    return dict(em=float(a == b), f1=f1, eligible=True)


def summarize(rows, cases, decisions, targets):
    unique_rows(rows, cases, decisions)
    if set(targets) != {q["question_id"] for q in cases}:
        raise ValueError("missing, duplicate or substituted evaluation labels")
    output, pairs = {}, {}
    for arm in ARMS:
        subset = [r for r in rows if r["arm"] == arm]
        successes = [r for r in subset if r["status"] == "succeeded"]
        valid = [r for r in successes if metric(r["answer"], targets[r["question_id"]])["eligible"]]
        f1s = [metric(r["answer"], targets[r["question_id"]])["f1"] for r in valid]
        cites = [CITE.findall(r["answer"]) for r in successes]
        undelivered = sum(
            any(mark[1:-1] not in {
                d["label"] for d in r["receipt"]["delivered_evidence"]
            } for mark in marks)
            for r, marks in zip(successes, cites, strict=True)
        )
        output[arm] = dict(
            planned=len(cases), succeeded=len(successes),
            failed=len(cases) - len(successes), diagnostic_scored=len(valid),
            diagnostic_unscored=len(successes) - len(valid),
            diagnostic_f1=sum(f1s) / len(f1s) if f1s else None,
            all_planned_f1_bounds=[
                sum(f1s) / len(cases),
                (sum(f1s) + len(cases) - len(valid)) / len(cases),
            ],
            emitted_citation_markers=sum(map(len, cites)),
            answers_with_undelivered_marker=undelivered,
            actual_input_tokens=sum(r["receipt"]["input_tokens"] for r in successes),
            actual_generated_tokens=sum(r["receipt"]["generated_tokens"] for r in successes),
            observed_inference_seconds=sum(r["receipt"]["seconds"] for r in successes),
            actual_source_bytes=sum(
                sum(len(d["excerpt"].encode("utf-8")) for d in r["receipt"]["delivered_evidence"])
                for r in successes
            ),
            independent_citation_entailment_precision=None,
        )
    mapped = {(r["question_id"], r["arm"]): r for r in rows}
    win = loss = tie = unknown = 0
    deltas = []
    for q in cases:
        x, y = (mapped[(q["question_id"], arm)] for arm in ARMS)
        if x["status"] != y["status"] or x["status"] == "failed":
            unknown += 1
            continue
        a, b = metric(x["answer"], targets[q["question_id"]]), metric(y["answer"], targets[q["question_id"]])
        if not a["eligible"] or not b["eligible"]:
            unknown += 1
            continue
        d = b["f1"] - a["f1"]
        deltas.append(d)
        win += d > 0
        loss += d < 0
        tie += d == 0
    pairs = dict(
        planned=len(cases), complete_scored=len(deltas), wins=win, losses=loss,
        ties=tie, missing_or_unscored=unknown,
        observed_mean_f1_delta=sum(deltas) / len(deltas) if deltas else None,
        all_planned_delta_bounds=[
            (sum(deltas) - unknown) / len(cases),
            (sum(deltas) + unknown) / len(cases),
        ],
        family_proxies=2, independent_family_significance_established=False,
    )
    return dict(
        schema=SCHEMA + ".diagnostic.v1", arms=output, paired=pairs,
        known_exposed_public_development_data=True,
        source_id_support_not_semantic_sufficiency=True,
        same_frozen_reader_no_parameter_training=True,
        independently_adjudicated_citation_precision=None,
        production_accepted=False,
    )


def score(public_root, evaluation_root, read_root, output, *, expected_commit):
    cases, documents, decisions = source_plan(public_root)
    manifest = strict_json((read_root / "READY.json").read_bytes())
    raw = (read_root / "raw-answers.jsonl").read_bytes()
    if (
        manifest["schema"] != SCHEMA
        or manifest["labels_seen_during_generation"] is not False
        or manifest["weight_updates"] != 0
        or manifest["planned_questions"] != PLANNED
        or manifest["planned_arms"] != list(ARMS)
        or manifest["raw_journal_sha256"] != sha(raw)
        or manifest["original_source_sha256"] != ZIPS["public"][1]
        or manifest["original_six_decisions_sha256"] != ZIPS["decisions"][1]
        or manifest["production_accepted"] is not False
        or not re.fullmatch(r"[0-9a-f]{40}", manifest["generating_commit"])
        or len(raw) > 4 * 1024 * 1024
    ):
        raise ValueError("not a complete immutable original model record")
    rows = [strict_json(line) for line in raw.splitlines()]
    # Source provenance and all 32 raw outcomes must be authenticated before
    # even opening the separately staged answer/label ZIP.
    verified = verify_immutable_generation_record(
        manifest, raw, rows,
        expected_commit=expected_commit,
        public_zip_sha256=ZIPS["public"][1],
        decisions_zip_sha256=ZIPS["decisions"][1],
    )
    unique_rows(rows, cases, decisions)
    by_question = {case["question_id"]: case for case in cases}
    originals = {k: original_document(v) for k, v in documents.items()}
    for row in rows:
        if row["status"] != "succeeded":
            continue
        if row["question_id"] not in by_question:
            raise ValueError("unknown original question")
        _, bundle = bundle_for(
            by_question[row["question_id"]], row["arm"],
            originals, row["selected"],
        )
        receipt = row["receipt"]
        if (
            receipt["delivered_evidence"] != bundle.delivered()
            or receipt["reader_identity"] != manifest["model_identity"]
            or receipt["reader_profile"] != manifest["model_profile"]
        ):
            raise ValueError("original evidence or pinned reader drift")
    evaluation_raw = read_zip(evaluation_root, "evaluation")["targets.json"]
    targets = strict_json(evaluation_raw)
    report = summarize(rows, cases, decisions, targets)
    report["actual_paired_prompt_and_generation_cost"] = audit_matched_costs(
        cases, rows
    )
    report["immutable_original_generation_verified"] = verified
    report.update(
        generating_commit=manifest["generating_commit"],
        original_raw_answers_sha256=sha(raw),
        reference_model_inventory_identity=manifest["model_identity"],
        evaluation_targets_sha256=sha(evaluation_raw),
    )
    output.mkdir(parents=True, exist_ok=False)
    write_once(output / "report.json", canonical(report) + b"\n")
    print(json.dumps(report, ensure_ascii=False))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    gen = modes.add_parser("generate")
    gen.add_argument("public_zips", type=Path)
    gen.add_argument("model", type=Path)
    gen.add_argument("output", type=Path)
    score_parser = modes.add_parser("score")
    score_parser.add_argument("public_zips", type=Path)
    score_parser.add_argument("evaluation_zips", type=Path)
    score_parser.add_argument("raw_answers", type=Path)
    score_parser.add_argument("output", type=Path)
    score_parser.add_argument(
        "--expected-commit", required=True,
        help="Externally known exact Git generating commit; never infer from READY",
    )
    args = parser.parse_args()
    if args.mode == "generate":
        generate(args.public_zips, args.model, args.output)
    else:
        score(
            args.public_zips, args.evaluation_zips, args.raw_answers, args.output,
            expected_commit=args.expected_commit,
        )


if __name__ == "__main__":
    main()
