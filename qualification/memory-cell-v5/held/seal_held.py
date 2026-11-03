"""Seal the independent corpus once, without importing or running any router."""

import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from string import Formatter


ROOT = Path(__file__).resolve().parent
V3 = Path("/workspace/scratch/3df12f9191cd/hepta-memory-restored-v3/qualification/memory-cell-v3")
INTENTS = ("at", "previous", "change", "mean3", "range3", "peak3")
OFFSETS = {"at": [0], "previous": [-1], "change": [-1, 0], "mean3": [-2, -1, 0], "range3": [-2, -1, 0], "peak3": [-2, -1, 0]}


def identity(path):
    content = path.read_bytes()
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def canonical_text(text):
    return re.sub(r"\W+", " ", text.replace("{series}", "{series_name}").lower()).strip()


def create_json(path, value):
    content = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(content)
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def main():
    if (ROOT / "SEAL.json").exists() or (ROOT / "SEMANTIC_REVIEW.json").exists():
        raise ValueError("Seal/review already exists; no overwrite or reseal is allowed")
    corpus = json.loads((ROOT / "queries.en.json").read_bytes())
    if corpus["schema"] != "hepta.memory.v5.sealed-language.v1":
        raise ValueError("Unexpected corpus schema")
    rows = corpus["queries"]
    labels = Counter(row["gold_intent"] for row in rows)
    families = Counter(row["ood_family"] for row in rows if row["gold_intent"] is None)
    if len(rows) != 216 or labels[None] != 72 or any(labels[label] != 24 for label in INTENTS):
        raise ValueError("Declared label inventory differs")
    if len(families) != 12 or set(families.values()) != {6}:
        raise ValueError("Declared OOD inventory differs")
    ids, utterances = set(), set()
    for row in rows:
        fields = {field for _, field, _, _ in Formatter().parse(row["utterance"]) if field is not None}
        if fields != {"series_name", "date"}:
            raise ValueError("Unapproved materialization fields")
        if row["series_name"] != "{series_name}" or row["date"] != "{date}":
            raise ValueError("Slots are not templates")
        if row["language"] != "en" or row["partition"] != "sealed_held_v5":
            raise ValueError("Language or partition differs")
        normalized = canonical_text(row["utterance"])
        if row["query_id"] in ids or normalized in utterances:
            raise ValueError("Duplicate ID or normalized utterance")
        ids.add(row["query_id"])
        utterances.add(normalized)
        if row["gold_intent"] is None:
            valid = row["risk_group"] == "near" and row["allow_numeric_read"] is False and row["expected_provenance_offsets"] is None and row["ood_family"] in families
        else:
            valid = row["risk_group"] == "known" and row["allow_numeric_read"] is True and row["ood_family"] is None and row["expected_provenance_offsets"] == OFFSETS[row["gold_intent"]]
        if not valid:
            raise ValueError("Label and grading metadata disagree")
    legacy_source = (V3 / "v3/route_language.py").read_bytes()
    legacy_templates = {
        canonical_text(node.value)
        for node in ast.walk(ast.parse(legacy_source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and "{date}" in node.value and "{series}" in node.value
    }
    collisions = utterances & legacy_templates
    if collisions:
        raise ValueError("Corpus duplicates a legacy V3 template after slot normalization")
    similar_pairs = []
    token_sets = [set(canonical_text(row["utterance"]).split()) for row in rows]
    for left, first in enumerate(token_sets):
        for right in range(left + 1, len(rows)):
            second = token_sets[right]
            similarity = len(first & second) / len(first | second)
            if similarity >= 0.85:
                similar_pairs.append({"left": rows[left]["query_id"], "right": rows[right]["query_id"], "token_set_jaccard": similarity})
    review = {
        "schema": "hepta.memory.v5.held-semantic-review.v1",
        "authoring_source": "synthetic expressions authored separately by evaluation assistant /root/v3_capacity_codec",
        "independent_real_user_sample": False,
        "independent_second_annotator": False,
        "manual_author_review_rows": 216,
        "manual_review_criteria": ["one-calendar-month predecessor versus anchor month", "signed subtraction direction versus relative percentage or transformed difference", "three-month inclusive calendar support", "equal-weight arithmetic mean versus other statistics", "maximum value versus maximum month", "single-series scalar operation versus multi-series request", "requested operator controls label even when answers could coincide"],
        "schema_and_balance_checks_passed": True,
        "normalized_duplicate_utterances": 0,
        "duplicate_query_ids": 0,
        "legacy_v3_normalized_templates_compared": len(legacy_templates),
        "legacy_v3_exact_template_collisions": 0,
        "within_corpus_token_set_jaccard_at_least_0_85": similar_pairs,
        "new_v5_training_or_development_data_read": False,
        "router_predictions_or_candidate_metrics_read": False,
        "routing_models_executed": 0,
        "numeric_answers_present": False,
        "model_based_selection_used": False,
        "scope": "Author semantic review and literal/template/schema checks only; no model accuracy or natural-user generality is established.",
    }
    create_json(ROOT / "SEMANTIC_REVIEW.json", review)
    names = ["queries.en.json", "author_corpus.py", "CONTRACT.md", "seal_held.py", "SEMANTIC_REVIEW.json"]
    seal = {
        "schema": "hepta.memory.v5.held-seal.v1", "sealed": True,
        "sealed_utc": datetime.now(timezone.utc).isoformat(),
        "corpus_schema": corpus["schema"], "corpus_file": "queries.en.json",
        "files": {name: identity(ROOT / name) for name in names},
        "counts": {"total": 216, "known": 144, "near_ood": 72, "per_intent": {label: labels[label] for label in INTENTS}, "per_ood_family": dict(sorted(families.items()))},
        "inference_fields": ["utterance", "series_name", "date"],
        "slot_fields": ["series_name", "date"], "date_format": "YYYY-MM",
        "ood_gold_label": None, "evaluation_reject_alias": "__reject__",
        "synthetic_authorship": True, "evaluated_by_any_router": False,
        "new_v5_training_or_development_data_read": False,
        "materialization_after_model_and_threshold_freeze_only": True,
        "legacy_contract_reference_commit": "ddd2ec4f9167c5ccf22adb63f4ce7402ebd7ae19",
        "legacy_contract_files": {name: identity(V3 / name) for name in ["v3/route_language.py", "v3/numeric_graph.py", "PROTOCOL.json"]},
        "authoring_shuffle_seed": 2026102701,
        "post_seal_changes_allowed": False,
        "errata_policy": "Separate appended erratum only; preserve sealed bytes, primary identity, and original evaluation record. No result-dependent relabeling or model tuning.",
        "seal_self_hash_stored_externally": True,
    }
    seal_identity = create_json(ROOT / "SEAL.json", seal)
    print(json.dumps({"seal": str(ROOT / "SEAL.json"), **seal_identity, "corpus": seal["files"]["queries.en.json"], "total": 216, "known": 144, "near_ood": 72, "evaluated_by_any_router": False}, sort_keys=True))


if __name__ == "__main__":
    main()
