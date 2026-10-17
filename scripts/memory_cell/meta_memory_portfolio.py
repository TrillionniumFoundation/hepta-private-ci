"""Source-bound, leave-one-dialogue-out MetaMemory portfolio research.

Only the postseal reviewer may open hidden reference labels. This is a
retrospective full-information evidence-ID policy diagnostic, NOT online RL,
NDU/FBSDE convergence, semantic Reader qualification, or production authority.
"""

from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory

import associative_graph_causal as graph
import associative_meta_evolution as meta

SCHEMA = "hepta.memory-meta-portfolio-shadow.v1"
CANDIDATES = ("temporal", "bm25", "fixed_graph", "shared_gate", "typed_split")
BASELINE = "temporal"
TEMPORAL_WORDS = frozenset(
    "when before after first last next earlier later yesterday tomorrow "
    "year month week day date time meanwhile then during".split()
)
PRIOR = 1.0
MIN_TRAIN_SAMPLES = 16
MIN_PREDICTED_GAIN = 0.025


def query_class(question):
    """Pre-registered source-visible feature; never examine target/source labels."""
    if not isinstance(question, str) or not graph.ascii_ok(question):
        raise ValueError("invalid source-visible question")
    return (
        "temporal" if TEMPORAL_WORDS.intersection(graph.words(question)) else "general"
    )


def _private(prepared, manifest):
    raw = graph.regular_bytes(Path(prepared) / "private.json")
    if graph.digest(raw) != manifest["private_sha256"]:
        raise ValueError("original private input digest mismatch")
    val = graph.strict_load(raw)
    if (
        not isinstance(val, dict)
        or set(val) != {"schema", "annotations"}
        or val["schema"] != graph.SCHEMA
    ):
        raise ValueError("unknown original private source schema")
    return val["annotations"]


def _rows(public, journal, annotations):
    """Collect a reviewer-only full-information retrospective outcome table."""
    sources = {g["family"]: {d["id"] for d in g["sources"]} for g in public["families"]}
    questions = {
        (g["family"], q["id"]): q["text"]
        for g in public["families"]
        for q in g["questions"]
    }
    expected = {qid for _, qid in questions}
    if not isinstance(annotations, dict) or set(annotations) != expected:
        raise ValueError("incomplete source questions or hidden annotations")
    if len(journal["rows"]) != 240 or tuple(journal["arms"]) != meta.ARMS:
        raise ValueError("missing original sealed candidate rows")
    records = []
    seen = set()
    for item in journal["rows"]:
        family, qid = item["family"], item["question_id"]
        key = (family, qid)
        if (
            key not in questions
            or key in seen
            or set(item) != {"family", "question_id", "arms"}
        ):
            raise ValueError("ambiguous retrospective question identity")
        seen.add(key)
        a = annotations[qid]
        if (
            not isinstance(a, dict)
            or set(a) != {"evidence", "unresolved_reference"}
            or type(a["unresolved_reference"]) is not bool
            or not isinstance(a["evidence"], list)
            or any(
                not isinstance(s, str) or not re.fullmatch(r"D\d+:\d+", s)
                for s in a["evidence"]
            )
        ):
            raise ValueError("untrusted original reference envelope")
        refs = set(a["evidence"])
        eligible = not a["unresolved_reference"] and bool(refs)
        if set(item["arms"]) != set(meta.ARMS):
            raise ValueError("incomplete candidate set")
        for arm, docs in item["arms"].items():
            if (
                not isinstance(docs, list)
                or len(docs) != graph.TOP_K
                or len(set(docs)) != graph.TOP_K
                or not set(docs) <= sources[family]
            ):
                raise ValueError("unadmitted source in candidate read")
        results = {
            arm: int(refs.issubset(set(item["arms"][arm]))) if eligible else None
            for arm in CANDIDATES
        }
        records.append(
            {
                "family": family,
                "query_class": query_class(questions[key]),
                "eligible": eligible,
                "values": results,
            }
        )
    if seen != set(questions):
        raise ValueError("incomplete sealed question census")
    return records


def fit(train, query_kind):
    """Fit a tiny retrospective memory-arm Head on *other* dialogue groups only.

    Task reward is source-ID complete@8 only; cost information is absent.
    Bayesian smoothing and gain margin reduce opportunistic overfitting.
    """
    if query_kind not in ("temporal", "general") or not train:
        raise ValueError("unregistered policy class or empty training set")
    seen = [r for r in train if r["eligible"] and r["query_class"] == query_kind]
    if len(seen) < MIN_TRAIN_SAMPLES:
        return BASELINE, {
            "support": len(seen),
            "reason": "insufficient_training_support",
        }
    estimated = {
        arm: (PRIOR + sum(r["values"][arm] for r in seen)) / (2 * PRIOR + len(seen))
        for arm in CANDIDATES
    }
    # Tie favors the simpler precommitted temporal graph, not learned proliferation.
    best = max(CANDIDATES, key=lambda arm: (estimated[arm], -CANDIDATES.index(arm)))
    expected_delta = estimated[best] - estimated[BASELINE]
    selected = best if expected_delta >= MIN_PREDICTED_GAIN else BASELINE
    return selected, {
        "support": len(seen),
        "predicted_gain": round(expected_delta, 8),
        "reason": "margin_passed" if selected != BASELINE else "no_credible_gain",
    }


def evaluate_folds(records):
    families = sorted({r["family"] for r in records})
    if len(families) != 10 or len(records) != 240:
        raise ValueError("ten complete original dialogue families required")
    outcomes = Counter()
    folds = {}
    for heldout in families:
        train = [r for r in records if r["family"] != heldout]
        test = [r for r in records if r["family"] == heldout]
        if len(train) != 216 or len(test) != 24:
            raise ValueError("source-family leakage or incomplete fold")
        policy = {kind: fit(train, kind) for kind in ("temporal", "general")}
        fold = Counter()
        for r in test:
            fold["planned"] += 1
            if not r["eligible"]:
                fold["unscorable"] += 1
                continue
            arm = policy[r["query_class"]][0]
            control = r["values"][BASELINE]
            candidate = r["values"][arm]
            fold["scored"] += 1
            fold["temporal_complete"] += control
            fold["policy_complete"] += candidate
            fold["wins"] += int(candidate > control)
            fold["losses"] += int(candidate < control)
            fold[f"selected_{arm}"] += 1
        if fold["scored"] + fold["unscorable"] != 24:
            raise ValueError("silently filtered original questions")
        outcomes.update(fold)
        folds[heldout] = {
            "counts": dict(fold),
            "policy": {
                kind: {"selected": policy[kind][0], **policy[kind][1]}
                for kind in ("temporal", "general")
            },
        }
    if (
        outcomes["planned"] != 240
        or outcomes["wins"] - outcomes["losses"]
        != outcomes["policy_complete"] - outcomes["temporal_complete"]
    ):
        raise ValueError("changed original reference or incomplete paired results")
    return folds, outcomes


def review(prepared_dir, sealed_dir, output_path):
    """Consume original references only after strict original algorithm replay."""
    public, manifest = graph.load_public(prepared_dir, reviewer=True)
    # The base reviewer recomputes ALL gate weights, seven arms and original
    # journal bytes from the public source alone before opening any gold labels.
    with TemporaryDirectory() as scratch:
        base = meta.review(prepared_dir, sealed_dir, Path(scratch) / "review.json")
    journal_bytes = graph.regular_bytes(Path(sealed_dir) / "predictions.json")
    journal = graph.strict_load(journal_bytes)
    refs = _private(prepared_dir, manifest)
    rows = _rows(public, journal, refs)
    folds, total = evaluate_folds(rows)
    if base["by_arm"]["temporal"]["complete_at_8"] != total["temporal_complete"]:
        raise ValueError("base reviewer and heldout portfolio disagree")
    # Even a positive descriptive delta cannot earn FinalUse with unknown cost,
    # absent semantic answers, and only ten correlated authored dialogue groups.
    summary = {
        "schema": SCHEMA,
        "source_dataset_sha256": graph.DATASET_SHA256,
        "public_sha256": manifest["public_sha256"],
        "seven_arm_journal_sha256": graph.digest(journal_bytes),
        "family_count": len(folds),
        "paired_question_count": total["scored"],
        "planned_question_count": total["planned"],
        "unscorable_count": total["unscorable"],
        "by_family": folds,
        "totals": dict(total),
        "exact_baseline": BASELINE,
        "policy_candidate_arms": list(CANDIDATES),
        "trained_parameters_in_production": 0,
        "offline_full_information_folds": True,
        "test_family_label_visible_to_its_policy_fit": False,
        "trained_on_original_benchmark_labels": True,
        "future_time_holdout": False,
        "semantic_answers_generated": 0,
        "independent_200_families": False,
        "lifecycle_cost_verified": False,
        "autonomous_cell_split_authorized": False,
        "final_use_authorized": False,
        "production_accepted": False,
        "disposition": "retain_temporal_deny_topology_growth",
    }
    graph.create_only(output_path, summary)
    return summary


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 4 or args[0] != "review":
        raise SystemExit(
            "review ORIGINAL_PREPARED SEALED_SEVEN_ARM_RUN NEW_PORTFOLIO_REPORT"
        )
    print(json.dumps(review(args[1], args[2], args[3]), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
