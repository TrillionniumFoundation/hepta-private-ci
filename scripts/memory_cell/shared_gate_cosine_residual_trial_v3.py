"""Admission-census-correct entrypoint for the fixed cosine-residual study.

The benchmark selection census is intentionally larger than the later admitted
answer/evidence training census. The residual study must cover every and only
saved admitted TRAIN unit; it must not require rejected selected questions to
become training rows. This wrapper preserves the v2 immutable-artifact receipt
fix and delegates all remaining scientific execution to the original study.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[2]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

import five_causal_experiments as c
import shared_gate_cosine_residual_trial_v2 as receipt_fix  # installs validator fix
import shared_gate_cosine_residual_trial as legacy


def admitted_own_inputs(train, rebuilt, selected_questions):
    """Project exact admitted TRAIN positives from a larger selected census.

    Selection happens before target/evidence eligibility. A selected question
    rejected by the existing admission rules remains in the selection audit but
    must not be fabricated into training. Conversely, every saved admitted unit
    must have exactly one annotated-answer source row.
    """
    c.require(isinstance(train, list) and isinstance(rebuilt, dict)
              and isinstance(selected_questions, (list, tuple)),
              "TRAIN admission inputs required")
    identities = {}
    for question in selected_questions:
        identity = getattr(question, "identity", None)
        c.require(isinstance(identity, str) and identity, "invalid selected TRAIN identity")
        qid = c.digest(identity)
        c.require(qid not in identities, "duplicate selected TRAIN identity")
        identities[qid] = identity
    units = rebuilt.get("units")
    c.require(isinstance(units, list) and units, "admitted TRAIN units missing")
    unit_ids = []
    for unit in units:
        c.require(isinstance(unit, dict) and c.sha(unit.get("question_id")),
                  "invalid admitted TRAIN unit identity")
        unit_ids.append(unit["question_id"])
    c.require(len(unit_ids) == len(set(unit_ids)), "duplicate admitted TRAIN unit")
    admitted = set(unit_ids)
    selected = set(identities)
    c.require(admitted <= selected, "admitted TRAIN unit not in selected cohort")

    annotated = {}
    for row in train:
        c.require(isinstance(row, dict), "invalid TRAIN example")
        if row.get("kind") != "annotated_answer":
            continue
        qid = row.get("question_id")
        c.require(qid in selected and qid not in annotated
                  and row.get("split") == "train" and c.text_id(row.get("family"))
                  and isinstance(row.get("request"), dict),
                  "invalid/duplicate admitted TRAIN answer")
        c.validate_public(row["request"])
        annotated[qid] = row
    c.require(set(annotated) == admitted,
              "complete admitted TRAIN own-source census required")

    own_inputs = [{"question_id": identities[qid], "family": annotated[qid]["family"],
                   "split": "train", "condition": "own_sources",
                   "request": deepcopy(annotated[qid]["request"])}
                  for qid in sorted(admitted)]
    excluded = sorted(selected - admitted)
    receipt = {"selected_train_questions": len(selected),
               "admitted_train_questions": len(admitted),
               "selected_but_not_admitted_questions": len(excluded),
               "selected_question_ids_sha256": c.digest(sorted(selected)),
               "admitted_question_ids_sha256": c.digest(sorted(admitted)),
               "selected_but_not_admitted_ids_sha256": c.digest(excluded),
               "admission_rule": "exact_saved_relevance_units_not_all_preeligibility_selection",
               "replacement_selected": False}
    return own_inputs, receipt


def rebuild_train_material(original, clean, cancelled_root):
    """Rebuild exact saved admitted TRAIN units, preserving rejected selections."""
    from transformers import AutoTokenizer
    import five_reader_evidence_pair_trial as parent
    import five_reader_response_learning as learning
    import five_reader_response_trial as response
    import question_evidence_relevance as relevance
    import source_time_evidence as metadata
    from source_time_evidence_trial import project_examples
    from five_native_historical_smoke import LOCOMO_SHA256
    from native import load

    matches = [p for p in Path(original).rglob("*.json")
               if p.stat().st_size > 50000 and c.file_sha(p) == LOCOMO_SHA256]
    c.require(len(matches) == 1, "exact original benchmark missing")
    benchmark = load(matches[0], "locomo", expected_sha256=LOCOMO_SHA256,
                     allow_unresolved_evidence=True)
    chosen, excluded = parent.choose(benchmark)
    reader = Path(clean) / "reader"
    tokenizer = AutoTokenizer.from_pretrained(reader, local_files_only=True,
                                               trust_remote_code=False)
    position_cap = c.load(reader / "config.json")["max_position_embeddings"]
    original_train, census = response.training_examples(
        benchmark, chosen["train"], tokenizer, position_cap)
    train, projection = project_examples(
        original_train, chosen["train"], benchmark.history, metadata.SOURCE_TIME)
    forbidden = sorted(set(excluded) | {benchmark.families[q.family]
                                        for q in chosen["select"]})
    learning.validate_examples(train, forbidden)
    rebuilt = relevance.build_plan(train, forbidden)
    saved = c.load(Path(cancelled_root) / "study" / "train-plan.json")
    c.require(all(saved.get(k) == v for k, v in rebuilt.items())
              and saved.get("forbidden_families") == forbidden,
              "saved TRAIN relevance plan cannot be reproduced")
    own_inputs, admission = admitted_own_inputs(train, rebuilt, chosen["train"])
    return saved, own_inputs, {"training_census": census, "projection": projection,
        "chosen_train": [q.identity for q in chosen["train"]],
        "chosen_select": [q.identity for q in chosen["select"]],
        "forbidden_families": forbidden, "train_examples_sha256": c.digest(train),
        "own_inputs_sha256": c.digest(own_inputs), "admission": admission}


legacy.rebuild_train_material = rebuild_train_material


def main():
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
