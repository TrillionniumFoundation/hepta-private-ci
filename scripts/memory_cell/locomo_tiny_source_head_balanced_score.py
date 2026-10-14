"""Independent post-seal published LoCoMo selection-support audit.

Score only after the original source-only six-family SGD weights and 16x4
selections have been independently sealed. Published source-support annotations
are weak labels, not complete reader success or human semantic sufficiency.
This is retrospective; published selection families were used by older studies.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

from locomo_tiny_source_head_balanced import SCHEMA, SPLIT
from locomo_tiny_source_head_transfer import (
    ARMS, DEC_SHA, PUB_SHA, loaded_public, original_zip,
    regular, sha, strict,
)

TARGET_ZIP_SHA = "ba8e2282034c5bb51fe319e8909e11d028619f85dfbbce5a6fff78284f9f220c"
OLD_POLICY_ZIP_SHA = "3913c112ff417a1d9e6aa5c0f11e61286a98815fc32b4eb5df9da8bac59b690d"


def postseal_score(public_zip, decision_zip, policy_file, predictions_file,
                   preseal_file, targets_zip, original_frozen_policy_zip,
                   *, expected_preseal_sha):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_preseal_sha):
        raise ValueError("original pre-gold SHA256 must be supplied")
    if sha(regular(preseal_file)) != expected_preseal_sha:
        raise ValueError("original pre-target artifact was changed after sealing")
    preseal = strict(regular(preseal_file))
    policy = strict(regular(policy_file))
    predictions = strict(regular(predictions_file))
    if (
        preseal.get("schema") != SCHEMA
        or preseal.get("scored_split") != SPLIT
        or preseal.get("train_family_proxy_count") != 6
        or preseal.get("evaluation_family_proxy_count") != 2
        or preseal.get("original_target_zip_opened") is not False
        or preseal.get("source_only_gradient_updates") != 384
        or preseal.get("files") != {
            Path(policy_file).name: sha(regular(policy_file)),
            Path(predictions_file).name: sha(regular(predictions_file)),
        }
        or policy.get("schema") != SCHEMA
        or policy.get("total_gradient_updates") != 384
        or policy.get("actual_optimizer_source_family_count") != 6
        or policy.get("original_benchmark_QA_labels_read") is not False
        or predictions.get("schema") != SCHEMA
        or predictions.get("split") != SPLIT
        or predictions.get("source_only_before_annotated_target") is not True
        or predictions.get("published_benchmark_not_prospective") is not True
        or predictions.get("frozen_policy_sha256") != sha(regular(policy_file))
        or predictions.get("model_answer_calls") != 0
    ):
        raise ValueError("missing source-only six-family frozen Head evidence")
    population, docs, catalog = loaded_public(public_zip, decision_zip)
    cases = {row["question_id"]: row for row in population["splits"][SPLIT]}
    seen = {}
    for row in predictions.get("predictions", []):
        qid, arm = row.get("question_id"), row.get("arm")
        case = cases.get(qid)
        key = (qid, arm)
        if (
            case is None or arm not in ARMS or key in seen
            or row.get("family_proxy_digest") != case["family_proxy_digest"]
            or row.get("scope") != case["scope"]
            or row.get("source_census_sha256") != case["source_census_sha256"]
            or not isinstance(row.get("selected"), list)
            or len(row["selected"]) != 8
            or len(set(row["selected"])) != 8
            or not set(row["selected"]).issubset(case["source_ids"])
            or row.get("selected_source_bytes") != sum(
                len(docs[ident]["content"].encode()) for ident in row["selected"]
            )
            or row.get("heldout_annotated_targets_opened") is not False
            or row.get("model_answer_calls") != 0
        ):
            raise ValueError("missing or forged original selected-source receipt")
        if arm.startswith("frozen_"):
            original_arm = "lexical_k8" if arm == "frozen_lexical_k8" else "recent_k8"
            if row["selected"] != catalog[qid, original_arm]["selected"]:
                raise ValueError("the prior immutable strong retrieval baseline changed")
        seen[key] = row
    if set(seen) != {(qid, arm) for qid in cases for arm in ARMS}:
        raise ValueError("incomplete frozen 16x4 labelled-output-excluded census")
    # The first original target read occurs after all checks above pass.
    published_gold = strict(original_zip(targets_zip, TARGET_ZIP_SHA,
                                        ("targets.json",))["targets.json"])
    old = strict(original_zip(original_frozen_policy_zip, OLD_POLICY_ZIP_SHA,
                              ("SHA256SUMS", "selection-policy.json"))["selection-policy.json"])
    if (
        not isinstance(published_gold, dict)
        or set(published_gold) != set(cases)
        or old.get("schema") != "hepta.memorycell.locomo-frozen-retrieval.v1"
        or old.get("selection_arm") != "lexical_k8"
        or old.get("heldout_labels_opened") is not False
    ):
        raise ValueError("original prior selection source population drift")
    totals = {arm: dict(planned=16, eligible=0, covered=0, evidence_bytes=0,
                        by_published_family=defaultdict(lambda: dict(eligible=0, covered=0)))
              for arm in ARMS}
    pairs = {}
    for qid, case in cases.items():
        gold = published_gold[qid]
        support, unresolved = gold.get("support"), gold.get("unresolved_support")
        if (
            not isinstance(support, list)
            or not isinstance(unresolved, list)
            or type(gold.get("unanswerable")) is not bool
            or len(support) != len(set(support))
            or any(type(x) is not str for x in support + unresolved)
        ):
            raise ValueError("malformed original publisher support annotation")
        eligible = bool(support) and not unresolved and not gold["unanswerable"]
        eligible = eligible and set(support).issubset(case["source_ids"])
        pairs[qid] = {}
        for arm in ARMS:
            info = totals[arm]
            row = seen[qid, arm]
            info["evidence_bytes"] += row["selected_source_bytes"]
            covered = bool(eligible and set(support).issubset(row["selected"]))
            if eligible:
                info["eligible"] += 1
                info["covered"] += int(covered)
                family = info["by_published_family"][case["family_proxy_digest"]]
                family["eligible"] += 1
                family["covered"] += int(covered)
            pairs[qid][arm] = dict(eligible=eligible, covered=covered)
    baseline = totals["frozen_lexical_k8"]
    previous = old["selection_scores"]["lexical_k8"]
    if (
        baseline["eligible"] != previous["eligible"]
        or baseline["covered"] != previous["full_annotated_support_covered"]
        or baseline["evidence_bytes"] != previous["selected_source_bytes"]
    ):
        raise ValueError("original published frozen retrieval metric not reproduced")
    comparison = {}
    for arm, info in totals.items():
        wins = losses = ties = 0
        for qid, values in pairs.items():
            if not values[arm]["eligible"]:
                continue
            current = values[arm]["covered"]
            reference = values["frozen_lexical_k8"]["covered"]
            wins += current and not reference
            losses += reference and not current
            ties += current == reference
        comparison[arm] = dict(
            planned=16, eligible=info["eligible"],
            covered=info["covered"], source_bytes=info["evidence_bytes"],
            wins_over_strong_lexical=wins, losses_to_strong_lexical=losses,
            ties=ties,
            per_family={key: dict(value) for key, value in info["by_published_family"].items()},
        )
    return dict(
        schema="hepta.memorycell.locomo-actual-balanced-tiny-head-target-replay.v1",
        original_public_sha256=PUB_SHA,
        original_retrieval_sha256=DEC_SHA,
        original_private_selection_gold_sha256=TARGET_ZIP_SHA,
        originally_selected_strong_retriever_sha256=OLD_POLICY_ZIP_SHA,
        pre_target_seal_sha256=expected_preseal_sha,
        original_published_proxy_family_count=2,
        evaluated_original_questions=16,
        actual_pre_gold_torch_gradient_updates=384,
        original_frozen_lexical_report_reproduced=True,
        label_blind_frozen_predictions=True,
        independent_future_source_families=0,
        human_semantic_sufficiency_certified=False,
        full_reader_task_success_evaluated=False,
        language_model_generations=0,
        learned_memory_superiority_proven=False,
        production_accepted=False,
        scores=comparison,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("public", "decisions", "policy", "predictions", "preseal", "targets", "original_policy", "output"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--sealed-sha256", required=True)
    a = parser.parse_args()
    result = postseal_score(
        a.public, a.decisions, a.policy, a.predictions,
        a.preseal, a.targets, a.original_policy,
        expected_preseal_sha=a.sealed_sha256,
    )
    with a.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({arm: (r["covered"], r["eligible"]) for arm,r in result["scores"].items()}, sort_keys=True))


if __name__ == "__main__":
    main()
