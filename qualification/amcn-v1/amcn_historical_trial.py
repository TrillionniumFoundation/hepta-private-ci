"""Run real archived-Encoder SemanticMemoryCell on original LoCoMo evidence rows.

Research-only, previously published corpus. Support labels are PUBLISHER ANNOTATIONS,
not independently verified entailment. "Future_a/b" are group-heldout protocol
labels, NOT future dates. No new independent model or production evidence.

Three explicit subprocess phases: prepare (may read all publisher labels),
train (receives TRAIN labels and unlabeled heldout source ONLY), score (opens
withheld targets only after immutable output/prediction files exist).
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

from amcn_core import Evidence, bm25, canonical, digest, require, shadow_disposition
from amcn_native import run_train_once
from amcn_fission_match import matched_fission
from amcn_learning import FeatureMatrix, train_semantic
from experiments.shared_stem_cell.execution import LocalEncoder, parameters, tensor_digest


SCOPE = "amcn.historical.locomo.shadow"
CORPUS = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
GENERATION = "locomo-archive-" + CORPUS[:12]
PROFILE = "hepta.amcn.actual-archived-encoder-evidence.v1"
MAX_SOURCE_BYTES = 1200


def write_once(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(record) + b"\n")
        stream.flush()
        import os
        os.fsync(stream.fileno())


def read_bounded(path, maximum=40 * 1024 * 1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink()
            and path.stat().st_size <= maximum, "missing/linked/oversize material")
    from experiments.shared_stem_cell.execution import decode
    return decode(path.read_bytes())


def stage_from_historical_artifact(archive, output):
    """Only real original external artifact, no benchmark downloads or substitute."""
    from five_native_historical_smoke import (
        ARCHIVE_SHA256, ENCODER_INVENTORY, LOCOMO_SHA256, prepare_materials, snapshot
    )
    from native import load
    archive, output = Path(archive), Path(output)
    require(not output.exists(), "stage output must not exist")
    output.mkdir(parents=True, exist_ok=False)
    original, clean, staging = prepare_materials(archive, output / "staged")
    model = snapshot(clean / "encoder", "encoder", ENCODER_INVENTORY)
    data = [p for p in original.rglob("*.json")
            if p.stat().st_size > 50000 and sha256(p.read_bytes()).hexdigest() == LOCOMO_SHA256]
    require(len(data) == 1, "pinned original LoCoMo bytes missing/ambiguous")
    benchmark = load(data[0], "locomo", expected_sha256=LOCOMO_SHA256,
                     allow_unresolved_evidence=True)
    families = sorted(set(benchmark.families.values()), key=digest)
    require(len(families) >= 8, "not enough disjoint original conversation families")
    # Every source lineage maps to exactly one split. Historical grouping
    # is NOT future-time evidence; old-task retention uses separate questions
    # from TRAIN groups and does not count as a new independent family.
    n = len(families)
    train_end = max(4, n * 6 // 10)
    select_end = min(n - 2, max(train_end + 1, n * 8 // 10))
    require(0 < train_end < select_end < n, "unavailable disjoint groups")
    assignments = {f: ("train" if i < train_end
                       else "select" if i < select_end
                       else "future_a" if i == select_end
                       else "future_b")
                   for i, f in enumerate(families)}
    from amcn_source_first import lexical_shortlist

    query_groups = {}
    for q in benchmark.questions:
        query_groups.setdefault(benchmark.families[q.family], []).append(q)

    train_labels, blind_scores, public, excluded = {}, {}, [], []
    source_first_plans, support_by_question = {}, {}
    seen_row_ids = set()

    def eligible_inventory(question):
        # Admission is fixed from the source alone, before any question targets.
        history = benchmark.history(question)
        items = []
        for doc in history:
            raw = doc.content.encode("utf-8")
            if not 1 <= len(raw) <= MAX_SOURCE_BYTES:
                continue
            items.append(Evidence(
                evidence_id=doc.identity, source_root=doc.root, scope=SCOPE,
                revision=1, text=doc.content,
                content_sha256=sha256(raw).hexdigest(),
                generation=GENERATION, revoked=False))
        require(len(items) <= 8192, "too many eligible source records")
        return items

    def append_row(question, family, split, evidence, label=None):
        rid = digest([question.identity, evidence.evidence_id, split])
        require(rid not in seen_row_ids, "duplicate candidate identity")
        seen_row_ids.add(rid)
        public.append({
            "row_id": rid, "question_id": question.identity,
            "question": question.content, "family": family, "split": split,
            "evidence": asdict(evidence),
        })
        if split == "train":
            require(type(label) is int and label in (0, 1), "TRAIN-only support label")
            train_labels[rid] = label
        else:
            require(label is None, "no heldout labels in public row")

    def freeze_query(question, family, split, inventory):
        # Deterministic across source permutations; no target/evidence-label
        # is supplied to the shortlist constructor.
        plan = lexical_shortlist(
            question.content, inventory, scope=SCOPE,
            generation=GENERATION, top_k=16)
        require(question.identity not in source_first_plans, "duplicate heldout question")
        source_first_plans[question.identity] = plan
        index = {ev.evidence_id: ev for ev in inventory}
        for sid in plan["ranked_source_ids"]:
            append_row(question, family, split, index[sid])

    for family in families:
        queries = sorted(query_groups.get(family, ()),
                         key=lambda q: digest(q.identity))
        available = []
        for question in queries:
            # The query and source admission are independent of publisher gold.
            if len(question.content.encode("utf-8")) > 512:
                continue
            inventory = eligible_inventory(question)
            if not inventory:
                continue
            available.append((question, inventory))
        if not available:
            excluded.append({"family_sha256":digest(family),
                             "reason":"no_admitted_question_or_source"})
            continue
        split = assignments[family]
        if split != "train":
            question, inventory = available[0]
            freeze_query(question, family, split, inventory)
            # Reveal reference IDs only to a separately persisted *withheld*
            # label/score payload, never to Encoder/Head Candidate inputs.
            target = benchmark.targets[question.identity]
            support_by_question[question.identity] = sorted(set(target.evidence))
            continue

        # TRAIN is the only partition allowed to use publisher weak support
        # annotations to construct supervised positive/negative examples.
        training_choice = None
        for question, inventory in available:
            support = set(benchmark.targets[question.identity].evidence)
            positive = [x for x in inventory if x.evidence_id in support]
            negative = [x for x in inventory if x.evidence_id not in support]
            if positive and negative:
                training_choice = (question, positive[0], negative[0])
                break
        if training_choice is None:
            excluded.append({"family_sha256":digest(family),
                             "reason":"no_train_weak_positive_and_negative"})
            continue
        training_question, positive, negative = training_choice
        append_row(training_question, family, "train", positive, 1)
        append_row(training_question, family, "train", negative, 0)
        # Old-task retention shares the TRAIN family by design, but is a
        # different question, selected *without* looking at its annotation.
        retention = next(((q, items) for q, items in available
                          if q.identity != training_question.identity), None)
        if retention is not None:
            freeze_query(retention[0], family, "retention", retention[1])
            support_by_question[retention[0].identity] = sorted(
                set(benchmark.targets[retention[0].identity].evidence))
        else:
            excluded.append({"family_sha256":digest(family),
                             "reason":"no_distinct_old_question_for_retention"})

    require(len(train_labels) >= 8 and {x for x in train_labels.values()} == {0, 1},
            "insufficient original supervised training examples")
    require(source_first_plans and all(sum(
        x["split"] == split for x in public) > 0
        for split in ("select", "future_a", "future_b", "retention")),
        "missing full fixed source-first evaluation split")
    require(all(x["split"] != "train" for x in public if x["row_id"] in blind_scores),
            "heldout truth leaked into TRAIN")
    for record in public:
        if record["split"] == "train":
            continue
        weak_support = set(support_by_question[record["question_id"]])
        blind_scores[record["row_id"]] = int(
            record["evidence"]["evidence_id"] in weak_support)

    inputs = {
        "schema": PROFILE + ".public.v2",
        "scope": SCOPE, "generation": GENERATION,
        "rows": public, "model_manifest": model,
        "family_plan": assignments,
        "source_first_shortlists": source_first_plans,
        "archive_sha256": ARCHIVE_SHA256,
        "dataset_sha256": CORPUS,
        "independent_future_observation": False,
    }
    withheld = {
        "schema": PROFILE + ".withheld.v2",
        "row_labels": blind_scores,
        "publisher_support": support_by_question,
        "source_first_plan_sha256": digest(source_first_plans),
    }
    write_once(output / "public-input.json", inputs)
    write_once(output / "train-labels.json", train_labels)
    # The TRAIN-only process cannot see this separate score-only file.
    write_once(output / "withheld-labels.json", withheld)
    write_once(output / "preparation-receipt.json", shadow_disposition(
        phase="prepare_source_first_v2",
        cohort_sha256=digest(public),
        shortlist_sha256=digest(source_first_plans),
        originally_published_question_families=len(families),
        excluded_families=excluded,
        counts_by_split={split:sum(x["split"] == split for x in public)
                         for split in ("train","select","future_a",
                                       "future_b","retention")},
        labels_are_publisher_weak_support=True,
        heldout_candidate_selection_reads_labels=False,
        source_groups_not_independently_reviewer_qualified=True,
        real_future_windows=0,
        material_staging_sha256=digest(staging),
        physical_pretrained_encoder_execution=False))
    return {
        "public_rows": len(public),
        "train_labels": len(train_labels),
        "withheld_labels": len(blind_scores),
        "heldout_queries": len(source_first_plans),
        "families": len(families),
        "excluded_families": len(excluded),
        "label_blind_candidates": True,
    }


def train_from_only_public_and_train_labels(root, public_path, labels_path, output):
    """Separate process receives no withheld-label argument or evaluator API."""
    info = read_bounded(public_path)
    require(info.get("schema") == PROFILE + ".public.v2", "unreviewed public input shape")
    observed = info["rows"]
    require(isinstance(observed, list) and 4 <= len(observed) <= 1024, "research row budget")
    labels = read_bounded(labels_path)
    records = []
    for r in observed:
        require(set(r) == {"row_id", "question_id", "question", "family", "split", "evidence"},
                "source and question fields only")
        records.append({"row_id":r["row_id"], "question":r["question"],
                        "family":r["family"], "split":r["split"],
                        "evidence":Evidence(**r["evidence"])})
    work = Path(output)
    receipt = run_train_once(
        Path(root) / "staged" / "clean" / "encoder", info["model_manifest"],
        records, labels, scope=SCOPE, generation=GENERATION,
        steps=32, output_dir=work)
    # Additional matched split/no-split training and predictions are separate.
    # No actual future score is opened in this process; avoid duplicate model
    # loading by reading the sealed, exactly verified frozen feature artifact
    # only after the production-compatible worker path is qualified.
    return receipt


def score_only_after_seal(public_path, withheld_path, sealed_dir, output):
    """Score EVERY label-blind heldout shortlist, including zero-positive cases.

    This still measures only publisher-weak source selection; no independent
    semantic judgment or language Reader correctness can be derived.
    """
    from math import isfinite
    from amcn_native import build_inputs
    from amcn_source_first import source_first_weak_score, PROFILE as SOURCE_FIRST

    info = read_bounded(public_path)
    require(info.get("schema") == PROFILE + ".public.v2",
            "source-first public experiment profile required")
    withheld = read_bounded(withheld_path)
    require(set(withheld) == {"schema", "row_labels", "publisher_support",
                              "source_first_plan_sha256"}
            and withheld["schema"] == PROFILE + ".withheld.v2",
            "exact source-first withheld label profile required")
    source_plans = info["source_first_shortlists"]
    require(withheld["source_first_plan_sha256"] == digest(source_plans),
            "shortlist edited after original source-first freeze")

    original = info["rows"]
    require(isinstance(original, list) and 4 <= len(original) <= 1024,
            "bounded original input rows required")
    require(len({r["row_id"] for r in original}) == len(original),
            "duplicate source-first rows")
    records = [{"row_id": r["row_id"], "question": r["question"],
                "family": r["family"], "split": r["split"],
                "evidence": Evidence(**r["evidence"])} for r in original]
    prepared, cases = build_inputs(records, scope=SCOPE, generation=GENERATION)
    expected = {r["row_id"]: (r, case.input_digest) for r, case in zip(original, cases)}
    require(set(withheld["row_labels"]) ==
            {r["row_id"] for r in original if r["split"] != "train"},
            "withheld row denominator drift")

    folder = Path(sealed_dir)
    predictions = read_bounded(folder / "sealed-predictions.json")
    receipt = read_bounded(folder / "candidate-receipt.json")
    model_path = folder / "semantic-head.safetensors"
    require(model_path.is_file() and not model_path.is_symlink()
            and model_path.stat().st_size <= 64 * 1024 * 1024,
            "original head artifact missing/unsafe")
    require(receipt.get("schema") == "hepta.amcn.real-head-candidate.v1"
            and receipt["prediction_digest"] == digest(predictions)
            and receipt["head_tensor_sha256"] ==
                sha256(model_path.read_bytes()).hexdigest()
            and receipt["production_accepted"] is False,
            "model identity/selected-artifact integrity failed")
    require(receipt["source_manifest_sha256"] == digest([
        (row["row_id"], row["evidence"]["content_sha256"],
         row["evidence"]["source_root"]) for row in original]),
        "original source manifest mismatch")
    from amcn_head_integrity import validate_sealed_semantic_head
    verified_head = validate_sealed_semantic_head(model_path, receipt)
    pred = {}
    require(isinstance(predictions, list) and len(predictions) == len(expected),
            "incomplete real pretrained model prediction census")
    for row in predictions:
        require(isinstance(row, dict) and set(row) == {
            "row_id", "split", "family", "input_sha256",
            "frozen_relevance", "trained_relevance"},
            "candidate prediction fields")
        row_id = row["row_id"]
        require(row_id in expected and row_id not in pred,
                "duplicate/unregistered prediction")
        source, digest_input = expected[row_id]
        require(row["family"] == source["family"] and
                row["split"] == source["split"] and
                row["input_sha256"] == digest_input,
                "original question/source/feature bytes changed")
        for kind in ("frozen_relevance", "trained_relevance"):
            value = row[kind]
            require(type(value) in (float, int) and isfinite(value)
                    and 0 <= value <= 1, "invalid model relevance score")
        pred[row_id] = row

    groups = {}
    for row in original:
        if row["split"] != "train":
            groups.setdefault(row["question_id"], []).append(row)
    require(set(groups) == set(source_plans) ==
            set(withheld["publisher_support"]), "unmatched zero-hit questions")
    outcomes = []
    for qid, rows in sorted(groups.items()):
        plan = source_plans[qid]
        require(plan.get("schema") == SOURCE_FIRST
                and plan["labels_accessed"] is False
                and plan["source_scope"] == SCOPE
                and plan["source_generation"] == GENERATION,
                "retrieval candidate not source-first")
        require(all(x["question"] == rows[0]["question"] and
                    x["family"] == rows[0]["family"] and
                    x["split"] == rows[0]["split"] for x in rows),
                "cross-question source mixing")
        require(plan["question_sha256"] == digest(rows[0]["question"]),
                "question frontiers changed")
        evidence_ids = [x["evidence"]["evidence_id"] for x in rows]
        require(evidence_ids == plan["ranked_source_ids"],
                "original source-first candidates changed or reordered")
        refs = withheld["publisher_support"][qid]
        weak = source_first_weak_score(plan, refs)
        supported = set(refs)
        for r in rows:
            weak_label = withheld["row_labels"][r["row_id"]]
            require(type(weak_label) is int
                    and weak_label == int(r["evidence"]["evidence_id"] in supported),
                    "labels contradict frozen publisher support")
        def best(kind):
            # Evidence equality here is annotation support, not factual truth.
            winner = max(rows, key=lambda r: (
                pred[r["row_id"]][kind], -evidence_ids.index(r["evidence"]["evidence_id"])))
            return winner["evidence"]["evidence_id"] in supported
        outcomes.append({
            "question_sha256": digest(qid),
            "family": rows[0]["family"], "split": rows[0]["split"],
            "frozen_top1_weak_support": best("frozen_relevance"),
            "trained_top1_weak_support": best("trained_relevance"),
            "source_first_lexical_top1_weak_support": weak["lexical_hit_at_1"],
            "source_first_lexical_any_at_k": weak["lexical_any_hit_at_k"],
            "publisher_support_in_shortlist": weak["publisher_support_in_shortlist"],
            "publisher_support_count": weak["publisher_support_count"],
            "publisher_weak_annotation_not_entailment": True,
        })

    outcomes.sort(key=lambda r: (r["family"], r["split"], r["question_sha256"]))
    measures = ("frozen_top1_weak_support", "trained_top1_weak_support",
                "source_first_lexical_top1_weak_support",
                "source_first_lexical_any_at_k")
    summary = {arm: {
        "hits": sum(int(o[arm]) for o in outcomes),
        "questions": len(outcomes),
        "by_split": {split: {
            "questions": sum(o["split"] == split for o in outcomes),
            "hits": sum(int(o[arm]) for o in outcomes if o["split"] == split)}
            for split in ("select", "future_a", "future_b", "retention")}
        } for arm in measures}
    result = shadow_disposition(
        profile=PROFILE + ".source-first-scored.v2",
        source_sha256=info["dataset_sha256"],
        original_model_execution_receipt_sha256=digest(receipt),
        physically_verified_saved_Head_receipt=verified_head,
        model_prediction_sha256=digest(predictions),
        candidate_plan_sha256=digest(source_plans),
        publisher_weak_support_source_first=summary,
        zero_support_cases=sum(x["publisher_support_count"] == 0
                               for x in outcomes),
        zero_retrieved_support_cases=sum(x["publisher_support_in_shortlist"] == 0
                                         for x in outcomes),
        family_count_upper_bound=len(set(x["family"] for x in outcomes)),
        score_unit="publisher-weak-support-at-source-first-shortlist-not-reader-answer",
        supports_selected_without_labels=True,
        full_Reader_responses=0, semantic_citation_precision=None,
        true_future_calendar_windows=0,
        independent_evaluator_accepted=False)
    write_once(output, result)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    s=parser.add_subparsers(dest="operation", required=True)
    p=s.add_parser("prepare");p.add_argument("archive");p.add_argument("output")
    p=s.add_parser("train");p.add_argument("source");p.add_argument("public");p.add_argument("train_labels");p.add_argument("output")
    p=s.add_parser("score");p.add_argument("public");p.add_argument("withheld");p.add_argument("sealed");p.add_argument("output")
    args=parser.parse_args()
    if args.operation=="prepare":
        report=stage_from_historical_artifact(args.archive,args.output)
    elif args.operation=="train":
        report=train_from_only_public_and_train_labels(args.source,args.public,args.train_labels,args.output)
    else:
        report=score_only_after_seal(args.public,args.withheld,args.sealed,args.output)
    print(json.dumps(report,sort_keys=True,default=str))


if __name__=="__main__":
    main()
