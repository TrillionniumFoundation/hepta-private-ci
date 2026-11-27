"""Source-only bridge from pinned original-human MultiRC P0 material to P2.

This module does NOT read dataset Parquet or a held-label owner. The upstream P0
material generator is pinned separately and must run in the source-owning job.
Input source docs contain FIT/CAL original human labels; only FIT labels leave
this adapter, through a DIFFERENT private output path from label-free views.
No model, feature, selected Head, inference, effect or authority is produced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

import gate
import matched_head
import physical_feature_bank

SOURCE_SCHEMA = "hepta.p0.multirc-human-semantic.v1"
SOURCE_REPO = "aps/super_glue"
SOURCE_REVISION = "4e14482c58d790d467ecfb29b6790e1917bf8756"
SOURCE_RULE = "sha256-passage-first-two-questions-all-first-four-answer-ids:blind:v1"
SOURCE_COUNTS = {"train": 12, "calibration": 4, "test": 8}
ORIGINAL_SCRIPT_COMMIT = "883b7c107348675153aece3db40a1d00e41c0a09"
ORIGINAL_SCRIPT_BLOB = "637a73a8735ff706ac256dca13a0614373255da1"
BRIDGE_SCHEMA = "hepta.stem.equal-size.multirc-source-bridge.v1"
CONDITIONS = {"original", "no_evidence"}
OUTPUT_SPLITS = {"train": "fit", "calibration": "cal", "test": "test"}
HEX32 = re.compile(r"[0-9a-f]{32}\Z")
EXPECTED_QUESTIONS_PER_SOURCE = 2
MAX_CASES = 48


def require(ok, message):
    gate.require(ok, message)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _checked_row(row, is_test):
    base = {"case_id", "source_id", "source_group", "split", "question_id",
            "answer_id", "condition", "candidate_text", "original_question_text",
            "joint_input", "view_sha256"}
    require(type(row) is dict and set(row) == (base if is_test else base | {"label"}),
            "changed original MultiRC source row or leaked test labels")
    for item in ("case_id", "question_id", "answer_id"):
        require(type(row[item]) is str and HEX32.fullmatch(row[item]),
                "invalid original MultiRC case/question/answer ID")
    require(gate.sha(row["source_id"]) and gate.sha(row["source_group"]) and
            gate.sha(row["view_sha256"]) and
            row["split"] in SOURCE_COUNTS and row["condition"] in CONDITIONS,
            "incomplete or invalid original source identity")
    view = row["joint_input"]
    require(type(view) is dict and set(view) == {"state", "question", "options"} and
            type(view["state"]) is str and type(view["question"]) is str and
            view["options"] == ["not_supported", "supported"],
            "changed original question/evidence/ordered options")
    require(row["view_sha256"] == _sha(_json(view)),
            "original model input digest mismatch")
    for key in ("candidate_text", "original_question_text"):
        require(type(row[key]) is str and row[key].strip() and len(row[key]) <= 512,
                "invalid original candidate/question")
    expected = ("Is the proposed answer supported by the original passage? Question: " +
                json.dumps(row["original_question_text"], ensure_ascii=False) +
                " Candidate answer: " +
                json.dumps(row["candidate_text"], ensure_ascii=False))
    require(view["question"] == expected, "changed original answer-conditioned question framing")
    if row["condition"] == "original":
        require(100 <= len(view["state"]) <= 950 and
                _sha(view["state"].encode("utf-8")) == row["source_id"] and
                _sha(" ".join(view["state"].split()).casefold().encode("utf-8")) ==
                row["source_group"],
                "original passage/group bytes or source ID changed")
        if not is_test:
            require(type(row["label"]) is int and row["label"] in (0, 1),
                    "FIT/CAL original human label invalid")
    else:
        require(view["state"] == "(no passage evidence available)" and
                (is_test or row["label"] is None),
                "unlabeled no-evidence counterfactual was given a human label")


def _provenance(fit, blind):
    require(type(fit) is dict and type(blind) is dict and
            set(fit) == set(blind) == {"metadata", "cases"},
            "missing original P0 material pair")
    meta = fit["metadata"]
    require(type(meta) is dict and meta == blind["metadata"] and set(meta) == {
        "schema", "repo", "revision", "train_sha256", "validation_sha256",
        "selection_rule", "source_passages_by_split", "training_license_independently_approved",
        "contamination_ruled_out", "temporal_future_windows_verified", "authority",
        "production_promotion_permitted", "panel_id"},
        "changed upstream original source metadata")
    require(meta["schema"] == SOURCE_SCHEMA and meta["repo"] == SOURCE_REPO and
            meta["revision"] == SOURCE_REVISION and meta["selection_rule"] == SOURCE_RULE and
            meta["source_passages_by_split"] == SOURCE_COUNTS and
            gate.sha(meta["train_sha256"]) and gate.sha(meta["validation_sha256"]) and
            gate.sha(meta["panel_id"]) and meta["authority"] == "DENY_ALL" and
            meta["training_license_independently_approved"] is False and
            meta["contamination_ruled_out"] is False and
            meta["temporal_future_windows_verified"] is False and
            meta["production_promotion_permitted"] is False,
            "original MultiRC source cannot confer production/source independence")
    base = {k: v for k, v in meta.items() if k != "panel_id"}
    require(_sha(_json({"base": base, "fit": fit["cases"], "blind": blind["cases"]})) ==
            meta["panel_id"], "original P0 panel digest not reproducible")
    return meta


def convert(fit, blind):
    """Generate label-free original features plan and private FIT-only label input.

    Exactly two cases per original source group, sorted by preregistered source
    case ID only. Never consult human labels to choose examples or splits.
    """
    meta = _provenance(fit, blind)
    rows = []
    seen_case_ids = set()
    seen_key = set()
    pairs = {}
    by_group = {key: {} for key in SOURCE_COUNTS}
    for doc, test in ((fit, False), (blind, True)):
        original_rows = doc["cases"]
        require(type(original_rows) is list and original_rows,
                "empty or invalid original P0 rows")
        for row in original_rows:
            _checked_row(row, test)
            require((row["split"] == "test") == test, "original test labels/split mixed")
            require(row["case_id"] not in seen_case_ids, "duplicate original P0 case")
            seen_case_ids.add(row["case_id"])
            group_key = (row["split"], row["source_group"])
            group = by_group[row["split"]].setdefault(row["source_group"], [])
            if row["condition"] == "original":
                group.append(row)
            relation = (row["split"], row["source_id"], row["source_group"],
                        row["question_id"], row["answer_id"])
            pair = pairs.setdefault(relation, {})
            require(row["condition"] not in pair, "duplicate original/no-evidence member")
            pair[row["condition"]] = row
    require(len(seen_case_ids) <= 4096 and len(pairs) * 2 == len(seen_case_ids),
            "missing or oversized original paired candidate population")
    all_groups = {}
    for split, groups in by_group.items():
        require(len(groups) == SOURCE_COUNTS[split], "original passage-group census drift")
        for gid, group in groups.items():
            require(gid not in all_groups and len(group) >= EXPECTED_QUESTIONS_PER_SOURCE and
                    len({entry["source_id"] for entry in group}) == 1,
                    "non-independent original passage group or too few alternatives")
            all_groups[gid] = split
    for pair in pairs.values():
        require(set(pair) == CONDITIONS, "incomplete original/no-evidence pair")
        a, b = pair["original"], pair["no_evidence"]
        require(a["joint_input"]["question"] == b["joint_input"]["question"] and
                a["joint_input"]["options"] == b["joint_input"]["options"] and
                a["source_id"] == b["source_id"],
                "counterfactual changed real task identity")
    chosen = []
    for split in ("train", "calibration", "test"):
        for gid, group in sorted(by_group[split].items()):
            # IDs are fixed by the original P0 question/answer/source selection
            # rule; labels cannot influence this choice or sample count.
            ranked = sorted(group, key=lambda x: x["case_id"])
            chosen.extend(ranked[:EXPECTED_QUESTIONS_PER_SOURCE])
    require(len(chosen) == MAX_CASES, "incomplete fixed 48-case source panel")
    source_material = _sha(_json({
        "repo": SOURCE_REPO, "revision": SOURCE_REVISION,
        "train_original_sha256": meta["train_sha256"],
        "validation_original_sha256": meta["validation_sha256"],
        "upstream_panel_id": meta["panel_id"], "selection": SOURCE_RULE,
    }))
    plan_cases, views, fit_targets = [], [], []
    for row in chosen:
        visible = row["joint_input"]
        split = OUTPUT_SPLITS[row["split"]]
        # This offline count is only an auditable approximate word count.
        # Every model must independently verify actual nontruncated tokens.
        estimate = len(visible["state"].split()) + len(visible["question"].split()) + 2
        require(0 < estimate <= gate.MAX_TOKENS, "source exceeds unqualified word budget")
        case = {"case_id": row["case_id"], "group_id": row["source_group"],
                "family_id": "multirc_original_human", "split": split,
                "source_sha256": row["source_id"],
                "input_sha256": row["view_sha256"], "token_count": estimate}
        plan_cases.append(case)
        views.append({"case_id": row["case_id"],
                      "state": visible["state"], "question": visible["question"],
                      "options": visible["options"], "source_sha256": row["source_id"],
                      "input_sha256": row["view_sha256"]})
        if split == "fit":
            fit_targets.append({"case_id": row["case_id"], "target": row["label"]})
    panel = {"schema": gate.SCHEMA, "source_revision": SOURCE_REVISION,
             "source_material_sha256": source_material, "purpose": "binary-support-research-only",
             "budget": {"max_tokens": gate.MAX_TOKENS, "head_steps": 40,
                        "head_trainable_params": matched_head.PARAMS,
                        "head_seed": 41, "head_optimizer": "sgd-lr-0.1", "precision": "float32"},
             "cases": plan_cases, "authority": "DENY_ALL",
             "production_promotion_permitted": False, "future_window_verified": False}
    panel_sha = gate.digest(panel)
    material = {"schema": physical_feature_bank.SCHEMA,
                "panel_sha256": panel_sha, "source_revision": SOURCE_REVISION,
                "source_material_sha256": source_material, "cases": views,
                "authority": "DENY_ALL", "production_authorized": False}
    fit_ledger = {"schema": matched_head.FIT_SCHEMA,
                  "panel_sha256": panel_sha,
                  "source_label_owner_sha256": _sha(_json({
                      "upstream_panel_id": meta["panel_id"],
                      "selected_fit_human_labels": fit_targets})),
                  "targets": fit_targets, "authority": "DENY_ALL",
                  "production_authorized": False}
    gate.validate_panel(panel)
    physical_feature_bank.manifest_views(panel, material)
    matched_head.validate_fit(panel, fit_ledger)
    provenance = {"schema": BRIDGE_SCHEMA, "upstream_source_schema": SOURCE_SCHEMA,
                  "upstream_source_commit": ORIGINAL_SCRIPT_COMMIT,
                  "upstream_source_blob": ORIGINAL_SCRIPT_BLOB,
                  "public_repo": SOURCE_REPO, "revision": SOURCE_REVISION,
                  "original_parquet_sha256": [meta["train_sha256"],meta["validation_sha256"]],
                  "original_p0_panel_id": meta["panel_id"],
                  "panel_sha256": panel_sha,
                  "fit_count": len(fit_targets),
                  "cal_count": sum(c["split"] == "cal" for c in plan_cases),
                  "test_count": sum(c["split"] == "test" for c in plan_cases),
                  "number_source_groups": len(all_groups),
                  "train_labels_sent_to_feature_producer": False,
                  "cal_or_test_labels_exported": False,
                  "actual_model_tokenizer_count_verified": False,
                  "actual_pretrained_encoder_forward_verified": False,
                  "original_human_gold_independently_scored": False,
                  "source_publisher_signature_verified": False,
                  "production_authorized": False, "authority": "DENY_ALL",
                  "disposition": "HOLD_NO_GO"}
    return panel, material, fit_ledger, provenance


def _new_json(path, obj):
    path = Path(path)
    require(path.parent.is_dir() and not path.parent.is_symlink() and
            not path.exists(), "source output must be create-new in ordinary directory")
    raw = _json(obj) + b"\n"
    require(0 < len(raw) <= 16 * 1024 * 1024, "oversized research source output")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pinned MultiRC source → private P2 label-blind feature view")
    ap.add_argument("--fit", type=Path, required=True)
    ap.add_argument("--blind", type=Path, required=True)
    ap.add_argument("--public-out", type=Path, required=True)
    ap.add_argument("--fit-labels-out", type=Path, required=True)
    args = ap.parse_args(argv)
    require(args.public_out != args.fit_labels_out and
            args.public_out.parent.resolve() != args.fit_labels_out.parent.resolve(),
            "public unlabeled and FIT-only label outputs must be separately owned")
    fit, blind = gate.strict_load(args.fit), gate.strict_load(args.blind)
    panel, views, ledger, receipt = convert(fit, blind)
    dest = args.public_out
    require(dest.parent.is_dir() and not dest.parent.is_symlink() and
            not dest.exists(), "public research source directory must be new")
    dest.mkdir(mode=0o700)
    _new_json(dest / "panel.json", panel)
    _new_json(dest / "views.json", views)
    _new_json(dest / "source-receipt.json", receipt)
    _new_json(args.fit_labels_out, ledger)
    print(json.dumps({"source_panel_sha256": receipt["panel_sha256"],
                      "cases": MAX_CASES, "fit": receipt["fit_count"],
                      "cal": receipt["cal_count"], "test": receipt["test_count"],
                      "original_human_fit_labels_private": True,
                      "original_human_test_labels_exported": False,
                      "model_effect_or_promotion_permitted": False}, sort_keys=True))


if __name__ == "__main__":
    main()
