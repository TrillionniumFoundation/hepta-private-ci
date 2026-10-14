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
MAX_SOURCE_BYTES = 32768


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
    query_groups = {}
    for q in benchmark.questions:
        query_groups.setdefault(benchmark.families[q.family], []).append(q)
    train_labels, blind_scores, public, skipped = {}, {}, [], []
    for fam in families:
        accepted = 0
        for q in sorted(query_groups.get(fam, ()), key=lambda q: digest(q.identity)):
            target = benchmark.targets[q.identity]
            history = benchmark.history(q)
            indexed = {d.identity: d for d in history}
            supports = sorted((indexed[e] for e in target.evidence
                               if e in indexed and 1 <= len(indexed[e].content.encode()) <= MAX_SOURCE_BYTES),
                              key=lambda d: digest(d.identity))
            negatives = sorted((d for d in history
                                if d.identity not in set(target.evidence)
                                and 1 <= len(d.content.encode()) <= MAX_SOURCE_BYTES),
                               key=lambda d: digest(d.identity))
            if target.unanswerable or not supports or not negatives:
                continue
            split = assignments[fam]
            # TRAIN family second question is a genuine old-source retention
            # probe, not a second independent test source family.
            if split == "train" and accepted == 1:
                split = "retention"
            elif accepted >= (2 if split == "train" else 1):
                break
            for label, doc in ((1, supports[0]), (0, negatives[0])):
                rid = digest([q.identity, doc.identity, split])
                source = Evidence(
                    evidence_id=doc.identity, source_root=doc.root, scope=SCOPE,
                    revision=1, text=doc.content,
                    content_sha256=sha256(doc.content.encode()).hexdigest(),
                    generation=GENERATION, revoked=False)
                public.append({"row_id": rid, "question_id": q.identity,
                               "question": q.content, "family": fam, "split": split,
                               "evidence": asdict(source)})
                (train_labels if split == "train" else blind_scores)[rid] = label
            accepted += 1
        if accepted < (2 if assignments[fam] == "train" else 1):
            skipped.append(fam)
    require(not skipped, "source family missing precommitted positive/negative pair")
    require(set(train_labels) and blind_scores, "no split data")
    # These are two distinct files. Future labels never appear in TRAIN input.
    inputs = {"schema": PROFILE + ".public", "scope": SCOPE,
              "generation": GENERATION, "rows": public,
              "model_manifest": model, "family_plan": assignments,
              "archive_sha256": ARCHIVE_SHA256,
              "dataset_sha256": CORPUS, "independent_future_observation": False}
    write_once(output / "public-input.json", inputs)
    write_once(output / "train-labels.json", train_labels)
    # Scorer-only label file; NEVER provided to trainer process.
    write_once(output / "withheld-labels.json", blind_scores)
    write_once(output / "preparation-receipt.json", shadow_disposition(
        phase="prepare", cohort_sha256=digest(public),
        originally_published_question_families=len(families),
        counts_by_split={split:sum(x["split"]==split for x in public)
                         for split in ("train", "select", "future_a", "future_b", "retention")},
        labels_are_publisher_weak_support=True,
        source_group_not_independently_reviewer_qualified=True,
        real_future_windows=0,
        material_staging_sha256=digest(staging),
        physical_pretrained_encoder_execution=False))
    return {"public_rows": len(public), "train_labels": len(train_labels),
            "withheld_labels": len(blind_scores), "families": len(families)}


def train_from_only_public_and_train_labels(root, public_path, labels_path, output):
    """Separate process receives no withheld-label argument or evaluator API."""
    info = read_bounded(public_path)
    require(info.get("schema") == PROFILE + ".public", "unreviewed public input shape")
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
    """Weak-label descriptive ranking, NOT independent semantic Reader scoring."""
    info = read_bounded(public_path)
    scores = read_bounded(withheld_path)
    folder = Path(sealed_dir)
    predictions = read_bounded(folder / "sealed-predictions.json")
    receipt = read_bounded(folder / "candidate-receipt.json")
    expected = {x["row_id"]:x for x in info["rows"]}
    require(receipt["schema"] == "hepta.amcn.real-head-candidate.v1"
            and receipt["prediction_digest"] == digest(predictions)
            and receipt["production_accepted"] is False, "not an immutable model result")
    require(set(x["row_id"] for x in predictions) == set(expected)
            and len(predictions) == len(expected), "unmatched generated predictions")
    require(set(scores) == {x["row_id"] for x in info["rows"] if x["split"] != "train"},
            "withheld test denominator drift")
    groups = {}
    for row in info["rows"]:
        if row["split"] == "train":
            continue
        bucket = groups.setdefault(row["question_id"], [])
        bucket.append(row)
    pred = {x["row_id"]:x for x in predictions}
    outcomes = []
    for qid, cases in sorted(groups.items()):
        require(len(cases) == 2
                and set(scores[x["row_id"]] for x in cases) == {0, 1},
                "incomplete weakly labeled QA pair")
        pos, neg = (next(x for x in cases if scores[x["row_id"]] == label)
                    for label in (1, 0))
        p1, p0 = pred[pos["row_id"]], pred[neg["row_id"]]
        source_items = [Evidence(**item["evidence"]) for item in cases]
        lexical = bm25(pos["question"], source_items, scope=SCOPE,
                       generation=GENERATION, maximum=2)
        outcomes.append({
            "question_sha256": digest(qid), "family": pos["family"],
            "split": pos["split"],
            "frozen_pairwise_correct": p1["frozen_relevance"] > p0["frozen_relevance"],
            "trained_pairwise_correct": p1["trained_relevance"] > p0["trained_relevance"],
            "simple_bm25_pairwise_correct": bool(lexical and lexical[0][0] == pos["evidence"]["evidence_id"]),
            "publisher_support_is_independent_entailment": False,
        })
    summary = {arm:{
        "correct":sum(x[arm] for x in outcomes),
        "pairs":len(outcomes),
        "by_split":{split: {"pairs": sum(x["split"]==split for x in outcomes),
                            "correct":sum(x[arm] for x in outcomes if x["split"]==split)}
                    for split in ("select", "future_a", "future_b", "retention")}}
        for arm in ("frozen_pairwise_correct","trained_pairwise_correct",
                    "simple_bm25_pairwise_correct")}
    result = shadow_disposition(
        profile=PROFILE, source_sha256=info["dataset_sha256"],
        original_model_execution_receipt_sha256=digest(receipt),
        model_prediction_sha256=digest(predictions),
        publisher_weak_support_pairwise_score=summary,
        family_count_upper_bound=len(set(x["family"] for x in outcomes)),
        score_unit="source-selection-pair-not-reader-answer",
        supported_knowledge_generalization=False, full_Reader_responses=0,
        semantic_citation_precision=None, true_future_calendar_windows=0,
        independent_evaluator_accepted=False)
    write_once(output,result)
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
