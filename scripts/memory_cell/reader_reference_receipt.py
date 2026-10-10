"""Re-read complete frozen-reader records; never generate, repair or judge text.

The full eight-case census remains authoritative. A matched reviewed subset is
an explicitly auxiliary view selected by the original availability mask, never
by model scores. Repeated reference runs are not independent observations.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

from bundle_trial import decode_bundle, write
from native import Document, Question, digest
from native_citation import capture_native
from reader_reference import GENERATION, MODELS, PINS, PRECISION, SYSTEM, summarize
from reviewed_diagnostic import capability_plan, outcome
from selector_answer_metrics import answer_scores
from tensor_contract import strict_json

SOURCE = "1879c0c52748e29739a12e4d4217a17dd7ac24c6"
BOUND = 64 * 1024 * 1024
ANNOTATIONS = {"f1", "exact_match", "target_unanswerable"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def archive(path, expected, *, inner=True):
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError("regular archive required")
    with path.open("rb") as stream:
        raw = stream.read(BOUND + 1)
    if len(raw) > BOUND or sha(raw) != expected:
        raise ValueError("external archive pin/size mismatch")
    files, size = {}, 0
    with zipfile.ZipFile(path) as source:
        if len(source.infolist()) > 512:
            raise ValueError("archive member bound")
        for entry in source.infolist():
            name = entry.filename
            parts = PurePosixPath(name).parts
            if (
                not name
                or "\\" in name
                or name.startswith("/")
                or ".." in parts
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError("unsafe archive member")
            if entry.is_dir():
                continue
            if name in files or entry.file_size < 0:
                raise ValueError("duplicate archive member")
            size += entry.file_size
            if size > BOUND:
                raise ValueError("expanded archive byte bound")
            files[name] = source.read(entry)
    if inner:
        inventory = {}
        for line in files["SHA256SUMS"].decode("utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                raise ValueError("invalid inner inventory")
            name = match[2].removeprefix("./")
            if name in inventory or name not in files or name == "SHA256SUMS":
                raise ValueError("duplicate or missing inventory member")
            inventory[name] = match[1]
        if set(inventory) != set(files) - {"SHA256SUMS"} or any(
            sha(files[k]) != v for k, v in inventory.items()
        ):
            raise ValueError("incomplete or mismatched inner inventory")
    return files


def object_at(files, name):
    return strict_json(files[name].decode("utf-8"))


def align_records(raw, scored, expected):
    keys = [(r["question_id"], r["arm"]) for r in raw]
    if (
        not expected
        or len(keys) != len(set(keys))
        or set(keys) != set(expected)
        or len(scored) != len(raw)
    ):
        raise ValueError("incomplete or duplicate answer census")
    result = {}
    for original, evaluated in zip(raw, scored, strict=True):
        if (
            ANNOTATIONS.intersection(original)
            or set(evaluated) != set(original) | ANNOTATIONS
            or any(evaluated[k] != v for k, v in original.items())
            or original["status"] not in ("succeeded", "failed", "unavailable")
        ):
            raise ValueError("raw answer or execution metadata was altered")
        result[(original["question_id"], original["arm"])] = evaluated
    return result


def replay(inputs, files):
    if files["tested-commit.txt"].decode().strip() != SOURCE:
        raise ValueError("wrong actual generating source")
    for name, value in PINS.items():
        if sha(inputs[name + ".json"]) != value:
            raise ValueError("original input pin mismatch")
    original = object_at(inputs, "plan.json")
    package = object_at(inputs, "reviews.json")
    withdrawn = set(object_at(inputs, "withdrawals.json"))
    plan = capability_plan(original, package, withdrawn)
    saved_plan = "run/diagnostic/reviewed-plan.json"
    if object_at(files, saved_plan) != plan:
        raise ValueError("reconstructed original conditions differ")
    plan_sha = sha(files[saved_plan])
    inventory = object_at(files, "inventory.json")
    tier = inventory["tier"]
    if (inventory["repository"], inventory["revision"]) != MODELS[tier]:
        raise ValueError("model family/revision drift")
    reader_id = digest(inventory["inventory"])
    if reader_id != inventory["inventory_digest"]:
        raise ValueError("model inventory identity mismatch")
    pins = PINS | {"inventory": sha(files["inventory.json"])}
    preregistered = object_at(files, "run/preregistered.json")
    if any(
        preregistered[k] != v
        for k, v in dict(
            source_commit=SOURCE,
            input_pins=pins,
            tier=tier,
            generation=GENERATION,
            system=SYSTEM,
            dtype=PRECISION,
            attention="eager",
            protocol="reader-reference-v1",
            optimization_permitted=False,
            production_accepted=False,
        ).items()
    ):
        raise ValueError("registered reader protocol changed")
    execution = object_at(files, "run/diagnostic/execution/execution.json")
    if any(
        execution[k] != v
        for k, v in dict(
            tested_commit=SOURCE,
            plan_sha256=plan_sha,
            labels_sha256=PINS["labels"],
            reader_identity=reader_id,
            reader_training=False,
        ).items()
    ):
        raise ValueError("execution detached from reader or inputs")
    expected = {
        (c["question"]["identity"], a): (c, condition)
        for c in plan["cases"]
        for a, condition in c["conditions"].items()
    }
    raw = [
        strict_json(line)
        for line in files["run/diagnostic/execution/raw-answers.jsonl"]
        .decode("utf-8")
        .splitlines()
    ]
    scored = object_at(files, "run/diagnostic/execution/scored-answers.json")
    by_key = align_records(raw, scored, expected)
    labels = object_at(inputs, "labels.json")
    requests, spans = 0, 0
    for key, row in by_key.items():
        case, condition = expected[key]
        query = Question(**case["question"])
        if row["family"] != case["family"] or row["phase"] != case["phase"]:
            raise ValueError("query family/phase drift")
        if condition.get("status") == "unavailable":
            if row["status"] != "unavailable" or row["reason"] != condition["reason"]:
                raise ValueError("missing review was silently repaired")
        if row["status"] == "succeeded":
            bundle = decode_bundle(condition)
            originals = {
                d["identity"]: Document(**(d | {"assets": tuple(d["assets"])}))
                for d in case["originals"]
            }
            bundle.validate(query, originals, frontier=case["frontier"], revoked=withdrawn)
            receipt = row["receipt"]
            if any(
                receipt[k] != v
                for k, v in dict(
                    delivered_evidence=bundle.delivered(),
                    bundle_digest=bundle.seal(),
                    query_digest=digest(asdict(query)),
                    reader_identity=reader_id,
                    token_limit=condition["token_limit"],
                    omitted_evidence_bytes=0,
                    trainable_parameters=0,
                    answer_postprocessed=False,
                    production_accepted=False,
                ).items()
            ):
                raise ValueError("actual evidence or generation receipt drift")
            if not 0 < receipt["input_tokens"] <= condition["token_limit"] or not (
                0 < receipt["generated_tokens"] <= GENERATION["max_new_tokens"]
            ):
                raise ValueError("actual decoder budget exceeded")
            request = capture_native(
                query,
                row["answer"],
                dict(
                    input_ids_sha256=receipt["input_ids_digest"],
                    delivered_evidence=receipt["delivered_evidence"],
                ),
                experiment_digest=digest((plan_sha, reader_id, key[1])),
                family_digest=digest(case["family"]),
            )
            if request != row["citation_audit"]:
                raise ValueError("original unsigned citation queue differs")
            requests += 1
            spans += len(bundle.selected)
        target = labels[key[0]]
        answers = (target["answer"],) if target["answer"] is not None else None
        null = target["unanswerable"] if answers is not None else None
        expected_score = (
            answer_scores(row["answer"], answers, null)
            if row["status"] == "succeeded"
            else dict(f1=None, exact_match=None)
        )
        if row["target_unanswerable"] != null or any(
            row[k] != v for k, v in expected_score.items()
        ):
            raise ValueError("QA diagnostics do not reproduce")
    metrics = summarize(scored)
    reference = object_at(files, "run/reference-report.json")
    if reference["source_commit"] != SOURCE or reference["summaries"] != metrics:
        raise ValueError("original reference report differs")
    gate = outcome(plan, package, scored)
    saved_gate = object_at(files, "run/diagnostic/reviewed-diagnostic.json")
    if any(saved_gate[k] != v for k, v in gate.items()):
        raise ValueError("original capability screen differs")
    return plan, by_key, dict(
        tier=tier,
        generated_source=SOURCE,
        rebuilt_citation_requests=requests,
        verified_delivered_spans=spans,
        complete_census=len(raw),
        summaries=metrics,
        original_capability_screen=gate,
        stage_seconds=reference["stage_seconds"],
        model_file_bytes=reference["model_file_bytes"],
        upstream_extraction_index_cost=None,
        training_seconds=0,
        new_model_execution=False,
        independent_semantic_judgement=False,
        production_accepted=False,
    )


def matched_view(plan, models):
    qids = [
        c["question"]["identity"]
        for c in plan["cases"]
        if c["conditions"]["reviewed_minimal"].get("status") != "unavailable"
    ]
    result = {}
    for tier, records in models.items():
        groups = {}
        for arm in ("reviewed_minimal", "reviewed_reversed", "retrieved2", "empty"):
            rows = [records[(q, arm)] for q in qids]
            groups[arm] = summarize(rows)[arm] if rows else None
        result[tier] = groups
    return dict(
        original_case_count=len(plan["cases"]),
        auxiliary_case_ids=qids,
        selection="original review availability, never model scores",
        replaces_full_census=False,
        per_reader=result,
        independently_reviewed=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "smol", "qwen", "output"):
        parser.add_argument(name, type=Path)
    for name in ("inputs", "smol", "qwen"):
        parser.add_argument("--" + name + "-sha", required=True)
    args = parser.parse_args()
    inputs = archive(args.inputs, args.inputs_sha, inner=False)
    models, reports, common = {}, {}, None
    for path, pin in ((args.smol, args.smol_sha), (args.qwen, args.qwen_sha)):
        plan, records, result = replay(inputs, archive(path, pin))
        if common is not None and common != plan:
            raise ValueError("reference models used different evidence plans")
        common = plan
        if result["tier"] in models:
            raise ValueError("duplicate reference reader")
        models[result["tier"]], reports[result["tier"]] = records, result
    if set(models) != set(MODELS):
        raise ValueError("incomplete two-reader comparison")
    for key, row in models["smol-1.7b"].items():
        other = models["qwen-3b"][key]
        if row["status"] == other["status"] == "succeeded" and (
            row["receipt"]["delivered_evidence"]
            != other["receipt"]["delivered_evidence"]
        ):
            raise ValueError("cross-reader actual evidence mismatch")
    result = dict(
        readers=reports,
        matched_auxiliary=matched_view(common, models),
        production_accepted=False,
        semantic_citation_precision=None,
        memory_gain_claim=False,
    )
    write(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    for case in common["cases"]:
        qid = case["question"]["identity"]
        for arm in ("reviewed_minimal", "retrieved2", "empty"):
            for tier, records in models.items():
                row = records[(qid, arm)]
                print(json.dumps(dict(
                    question_id=qid, question=case["question"]["content"],
                    tier=tier, arm=arm, status=row["status"],
                    answer=row.get("answer"), diagnostic_f1=row.get("f1"),
                    semantic_verdict=None,
                ), ensure_ascii=False))
