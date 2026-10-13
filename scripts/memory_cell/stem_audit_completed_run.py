"""Independent, read-only audit of one complete native Stem research run.

The original six-arm matrix completed model execution. This audit does NOT
certify improved memory learning, semantic source entailment or production.
"""
from collections import Counter
import json
from pathlib import Path

from stem_audit_archive import PinnedArchive, require

ZIP_SHA256 = "1db7f8f7c13a1f718d5065956f14d554d3fe328c415fac4bb145d1eaf9d913c8"
SOURCE = "675970bb610c70bb0ec30a2dee05c025440510e6"
TREE = "d280ba53070fb6457c04ff0d97fbb14ebbdbc3fb"
STAGES = (16, 32, 48)
PHASES = ("select", "retention", "test", "transfer")
ARMS = ("frozen_rerank", "prototype", "linear", "gated",
        "lineage_lora_gated", "independent_lora_gated")


def reconcile(plan, attempts, scores, report):
    """Recompute outcomes from all original decisions; no new model calls."""
    require(tuple(plan["arms"]) == ARMS, "Stem arm registration changed")
    require(tuple(plan["curriculum_attempted_examples"]) == STAGES,
            "checkpoint schedule drift")
    groups = plan["questions"]
    require(set(groups) == {"train", *PHASES}
            and len(groups["train"]) == 48
            and all(len(groups[p]) == 8 for p in PHASES), "registered cohort drift")
    require(len({q for cohort in groups.values() for q in cohort}) == 80,
            "duplicate train or heldout question")
    expected = {(st, ph, q, a) for st in STAGES for ph in PHASES
                for q in groups[ph] for a in ARMS}

    def index(rows):
        result = {}
        for row in rows:
            k = (row["stage"], row["phase"], row["question_id"], row["arm"])
            require(k in expected and k not in result,
                    "missing, duplicated or fabricated policy attempt")
            require(row["status"] in ("succeeded", "failed"), "unknown policy status")
            result[k] = row
        require(set(result) == expected and len(result) == 576,
                "incomplete registered policy denominator")
        return result

    actual = index(attempts)
    scored = index(scores)
    require(Counter(x["status"] for x in actual.values()) == {"succeeded": 576},
            "not the completed native run")
    require(report["census"] == {"planned": 576, "recorded": 576, "complete": True},
            "summary silently omitted policy attempts")
    require(report["logical_policy_attempts"] == 576,
            "incorrect logical attempt count")
    for k in expected:
        require(actual[k]["answer"] == scored[k]["answer"]
                and actual[k]["status"] == scored[k]["status"],
                "post-policy scoring rewrote an original answer")
    reader = report["reader"]
    require((reader["actual_attempts"], reader["actual_successes"],
             reader["actual_failed_attempts"], reader["cache_hits"])
            == (44, 44, 0, 543), "Reader attempt or exact-cache census drift")
    empty = report["no_evidence_reader_call_accounting"]["isolated_no_evidence_reader"]
    require(empty["actual_attempts"] == empty["actual_successes"] == 32,
            "32 no-evidence reference Reader calls incomplete")

    controls, changed = {}, []
    for arm in ARMS[1:]:
        r = dict(paired_attempts=96, changed_source_top1=0, changed_answer_bytes=0,
                 weak_document_source_gains=0, weak_document_source_regressions=0)
        for stage in STAGES:
            for phase in PHASES:
                for qid in groups[phase]:
                    fk = (stage, phase, qid, "frozen_rerank")
                    lk = (stage, phase, qid, arm)
                    frozen, learned = actual[fk], actual[lk]
                    require(frozen["pool_digest"] == learned["pool_digest"]
                            and frozen["pool_digest"]
                            and frozen["family"] == learned["family"],
                            "matched candidate pool/family drift")
                    if frozen["selected"] != learned["selected"]:
                        r["changed_source_top1"] += 1
                        b = scored[fk]["source_choice_correct"]
                        l = scored[lk]["source_choice_correct"]
                        require(type(b) is int and type(l) is int
                                and b in (0, 1) and l in (0, 1),
                                "unscorable changed source interpreted as gain")
                        r["weak_document_source_gains"] += int(l > b)
                        r["weak_document_source_regressions"] += int(l < b)
                        changed.append(dict(checkpoint=stage, phase=phase,
                                            question_id=qid, arm=arm,
                                            frozen_candidate=frozen["selected"],
                                            learned_candidate=learned["selected"],
                                            frozen_weak_native_support=b,
                                            learned_weak_native_support=l,
                                            answer_changed=frozen["answer"] != learned["answer"]))
                    r["changed_answer_bytes"] += frozen["answer"] != learned["answer"]
        controls[arm] = r
    require(len(changed) == 1 and not changed[0]["answer_changed"]
            and sum(x["weak_document_source_gains"] for x in controls.values()) == 0
            and sum(x["changed_answer_bytes"] for x in controls.values()) == 0,
            "no confirmed learning benefit was misreported")

    fit = report["within_head_train_fit"]
    require(len(fit) == 30
            and len({(x["checkpoint"], x["arm"], x["cell"]) for x in fit}) == 30,
            "training Head snapshots missing")
    for row in fit:
        require(row["heldout_annotations_consulted"] is False
                and row["production_accepted"] is False
                and row["weak_source_top1_gains"] == 0,
                "training data reused as independent quality evidence")
    opportunities = report["adapter_pair_opportunities"]["checkpoint_prefixes"]
    expected_pairs = {"16": (16, 14, 10), "32": (32, 27, 17),
                      "48": (48, 40, 28)}
    for stage, target in expected_pairs.items():
        row = opportunities[stage]
        require((row["attempted_questions"],
                 row["admitted_weak_source_questions"],
                 row["positive_negative_pair_eligible_questions"]) == target,
                "contrastive train example count drift")

    phases = report["retrospective_weak_source_ceiling"]["phases"]
    require(set(phases) == set(PHASES), "source ceilings omit evaluation phase")
    ceiling = dict(
        registered_questions=sum(x["attempted"] for x in phases.values()),
        native_answerable_with_resolved_weak_support=sum(
            x["native_source_resolved"] for x in phases.values()),
        native_unanswerable=sum(x["native_unanswerable"] for x in phases.values()),
        weak_support_missing_from_candidates=sum(
            x["support_missing_from_pool"] for x in phases.values()),
        weak_support_retrieved_but_frozen_top1_missed=sum(
            x["frozen_missed_available_support"] for x in phases.values()),
        frozen_top1_selected_weak_native_support=sum(
            x["frozen_correct_source_choices"] for x in phases.values()),
    )
    require(tuple(ceiling.values()) == (32, 25, 7, 8, 4, 13),
            "native weak-source retrieval/ranking bottleneck drift")
    require(sum(x.get("citation_structure", {}).get("markers", 0)
                for x in scores) == 0, "new citation markers need fresh adjudication")
    require(report["semantic_citation_precision"] is None
            and report["production_accepted"] is False
            and report["superiority_claim"] is False,
            "unverified semantic citation or production certification")

    return dict(
        schema="hepta.stem-completed-native-independent-audit.v1",
        historical_execution_commit=SOURCE,
        historical_execution_tree=TREE,
        genuine_model_policy_successes=576,
        real_reader_call_count=44,
        exact_reader_cache_hits=543,
        isolated_no_evidence_reader_attempts=32,
        candidate_selection_and_answers_by_arm=controls,
        changed_selected_candidates=changed,
        adapter_train_pairs_by_checkpoint=expected_pairs,
        source_ceiling=ceiling,
        actual_head_fit_observations=30,
        independent_semantic_citation_precision=None,
        independently_adjudicated_qa_gain=False,
        production_accepted=False,
    )


def audit_pinned_zip(path):
    archive = PinnedArchive(Path(path), ZIP_SHA256)
    try:
        require(archive.read("tested-commit.txt").decode().strip() == SOURCE,
                "generating commit differs from pinned source")
        require(archive.read("tested-tree.txt").decode().strip() == TREE,
                "generating tree differs from pinned source")
        plan = archive.json("comparison/preregistered.json")
        require(plan["source_commit"] == SOURCE, "experiment plan not source-pinned")
        result = reconcile(
            plan,
            archive.jsonl("comparison/policy-predictions.jsonl"),
            archive.json("comparison/scored-policy-attempts.json"),
            archive.json("comparison/report.json"),
        )
        result.update(pinned_zip_sha256=archive.sha256,
                      verified_internal_sha256_members=archive.manifest_entries,
                      original_model_reexecuted_by_this_audit=False)
        require(archive.manifest_entries == 130, "source/cost receipt census drift")
        return result
    finally:
        archive.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit_pinned_zip(args.zip_path)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
