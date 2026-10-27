"""Materialize only public training/selection/development language and audit it."""

from collections import Counter

from . import development_language, selection_language
from .contracts import INTENTS, LABELS, REJECT, canonical, normalized_request, sha256, unlabeled
from .training_language import training_templates


AUTHORSHIP = {
    "schema": "memory-cell-v5.public-language-authorship.v1",
    "kind": "synthetic-author-written-English-and-labeled-training-grammar-expansions",
    "author_role": "training-side-assistant",
    "date": "2026-10-27",
    "not_real_user_dialogue": True,
    "prior_material_access": ["restored-V3-six-intent-source-and-historical-language", "historical-V4-reported-failure-analysis"],
    "old_held_is_development_material_not_new_evidence": True,
    "new_independent_held_read_by_training_code": False,
    "given_slots": ["series_name", "date"],
    "strict_requested_operation_contract": "An unsupported request type is rejected even when special numeric data could make its answer coincide with a supported operation; e.g. singleton aggregate is not an at request.",
    "generated_examples_are_not_independent_authored_templates": True,
}


def _row(template, intent, family, partition, index):
    series_name, date = "monthly quantity R17", "2020-07"
    request = {"utterance": template.format(series_name=series_name, date=date), "series_name": series_name, "date": date}
    return {
        **request,
        "id": sha256(canonical([partition, index, template, intent]))[:24],
        "template": template,
        "intent": intent,
        "family": family,
        "partition": partition,
        "provenance": "new-V5-training-side-synthetic-author",
    }


def _public_fold(module, partition):
    rows = []
    if set(module.KNOWN) != set(INTENTS):
        raise ValueError("public language lacks one of the supported intent types")
    for intent, templates in module.KNOWN.items():
        for template in templates:
            rows.append(_row(template, intent, "supported-" + intent, partition, len(rows)))
    for family, templates in module.OOD.items():
        for template in templates:
            rows.append(_row(template, REJECT, family, partition, len(rows)))
    return rows


def build_public_corpus():
    generated = training_templates()
    train, seen, deduplicated = [], {}, []
    for entry in generated:
        row = _row(entry["template"], entry["intent"], entry["family"], "train", len(train))
        text = normalized_request(unlabeled(row))
        if text in seen:
            if seen[text] != row["intent"]:
                raise ValueError("conflicting training labels after slot normalization")
            deduplicated.append({"template": row["template"], "intent": row["intent"]})
            continue
        seen[text] = row["intent"]
        train.append(row)
    folds = {
        "train": train,
        "selection": _public_fold(selection_language, "selection"),
        "development": _public_fold(development_language, "development"),
    }
    all_text = {}
    for partition, rows in folds.items():
        if not rows:
            raise ValueError("empty public language fold")
        for row in rows:
            if row["intent"] not in LABELS:
                raise ValueError("unsupported label in public corpus")
            text = normalized_request(unlabeled(row))
            if text in all_text:
                raise ValueError("normalized text duplicated within or across public folds: " + text)
            all_text[text] = (partition, row["intent"])
    audit = {
        "schema": "memory-cell-v5.public-corpus-audit.v1",
        "authorship": AUTHORSHIP,
        "generated_training_rows_before_deduplication": len(generated),
        "training_duplicates_removed": len(deduplicated),
        "training_duplicates": deduplicated,
        "normalized_cross_label_conflicts": 0,
        "normalized_cross_fold_duplicates": 0,
        "folds": {name: {
            "rows": len(rows),
            "by_intent": dict(Counter(row["intent"] for row in rows)),
            "by_family": dict(Counter(row["family"] for row in rows)),
            "canonical_sha256": sha256(canonical(rows)),
        } for name, rows in folds.items()},
        "label_audit_scope": "Exact-text conflicts and declared grammar operand directions; does not establish independent human annotation correctness.",
    }
    return folds, audit
