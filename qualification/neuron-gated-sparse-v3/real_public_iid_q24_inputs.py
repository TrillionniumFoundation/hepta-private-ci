#!/usr/bin/env python3
"""Prepare REAL public-text Q24 *IID* task inputs without inventing time.

Consumes a physical 96-case ModernBERT->Q24 snapshot from the parent producer;
only 64 registered training labels can cross into the candidate-fit envelope.
Heldout labels are NOT read by the candidate input composer. No signed V1
baseline, independent evaluator, future window, or Cell selection is granted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from real_encoder_q24_snapshot_gate import read, unique_json, validate

SOURCE_COMMIT = "758205d3de23ccbf76649b1446c271101dc917b0"
CLASSES = (
    "card_arrival", "cash_withdrawal_not_recognised",
    "exchange_rate", "lost_or_stolen_phone",
)
MAX_CASES = 96


class Refused(ValueError):
    pass


def need(ok: bool, why: str) -> None:
    if not ok:
        raise Refused(why)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True, allow_nan=False,
                       ensure_ascii=False) + "\n").encode("utf-8")


def verify_local_original_source(original_root: Path) -> Path:
    source = Path(original_root).resolve()
    sha = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True,
    ).strip()
    need(sha == SOURCE_COMMIT, "original public Encoder/BANKING77 source SHA changed")
    clean = subprocess.check_output(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=no"],
        text=True,
    ).strip()
    need(not clean, "original public source has dirty tracked files")
    owner = source / "qualification" / "stem-cell-v1"
    need(owner.is_dir() and not owner.is_symlink(), "original public source owner absent")
    if str(owner) not in sys.path:
        sys.path.insert(0, str(owner))
    return owner


def read_original_public_inputs(original_owner: Path, public_data: Path) -> dict:
    import banking77_material
    from public_cell_learning import validate_inputs
    root = Path(public_data)
    need(not root.is_symlink() and root.is_dir(), "public source root missing or symlinked")
    source = unique_json(read(root / "SOURCE.json"))
    material = unique_json(read(root / "MATERIAL.json"))
    need(source["schema"] == "hepta.banking77-source.v1"
         and source["revision"] == banking77_material.REVISION
         and source["license"] == "CC-BY-4.0"
         and source["blobs"] == banking77_material.BLOBS
         and material["source"] == source,
         "original external public dataset and license drift")
    files = {}
    for name, git_sha in sorted(banking77_material.BLOBS.items()):
        path = root / name
        raw = read(path, banking77_material.MAX_BYTES)
        git_blob = hashlib.sha1(
            b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
        ).hexdigest()
        need(git_blob == git_sha and
             material["sha256"][name] == digest(raw),
             "actual original public dataset Git blob / SHA drift")
        files[name] = raw
    inputs, _heldout_targets, selection = banking77_material.prepare(
        files["banking_data/train.csv"], files["banking_data/test.csv"],
    )
    # Deliberately discard the heldout labels without ever using them here.
    del _heldout_targets
    validate_inputs(inputs)
    need(len(inputs["fit"]) == 64 and len(inputs["heldout"]) == 32
         and selection["selected_ids"]["fit"] ==
             [r["id"] for r in inputs["fit"]]
         and selection["selected_ids"]["heldout"] ==
             [r["id"] for r in inputs["heldout"]],
         "original public train/test split identity drift")
    return inputs


def bind_public_iid(snapshot: dict, registry: dict, receipt: dict,
                    original_inputs: dict, *, projection_sha256: str,
                    registry_sha256: str, snapshot_sha256: str) -> tuple[dict, dict, dict]:
    need(type(receipt) is dict and
         receipt.get("schema") == "hepta.neuron.actual-public-encoder-q24-producer.v1" and
         receipt.get("original_public_input_id") == original_inputs.get("input_id") and
         receipt.get("real_pretrained_encoder_invoked") is True and
         receipt.get("physical_encoder_invocations") == MAX_CASES and
         receipt.get("train_only_projection_fit_count") == 64 and
         receipt.get("heldout_projection_fit_count") == 0 and
         receipt.get("production_qualification") is False and
         receipt.get("ndu_eligible") is False and
         receipt.get("original_selected_v1_no_change_verified") is False and
         receipt.get("projection_owner_signature_verified") is False,
         "physical public Encoder source producer lacks complete non-authorizing receipt")
    need(receipt.get("projection_safetensors_sha256") == projection_sha256
         and receipt.get("registry_sha256") == registry_sha256
         and receipt.get("snapshot_sha256") == snapshot_sha256,
         "frozen public source snapshot/projection/registry artifact SHA drift")
    validate(snapshot, registry,
             expected_encoder=receipt["encoder_snapshot_sha256"],
             expected_projection=projection_sha256,
             expected_registry_sha=registry_sha256)
    need(type(original_inputs) is dict and
         original_inputs.get("intents") == list(CLASSES) and
         len(original_inputs.get("fit", [])) == 64 and
         len(original_inputs.get("heldout", [])) == 32,
         "wrong original BANKING77 source family")
    source_by_id = {}
    for split in ("fit", "heldout"):
        for row in original_inputs[split]:
            name = row["id"]
            need(name not in source_by_id, "duplicate original public input ID")
            source_by_id[name] = (split, row)
    need(len(source_by_id) == MAX_CASES, "original public source registry incomplete")
    frozen = {}
    for row in snapshot["feature_rows"]:
        case_id = row["case_id"]
        need(case_id not in frozen and case_id in source_by_id,
             "missing/duplicate or foreign Q24 source record")
        split, original = source_by_id[case_id]
        need(row["split"] == split and
             row["source_text_sha256"] == digest(original["text"].encode("utf-8")),
             "Q24 feature row is not bound to its original public text/partition")
        frozen[case_id] = row["feature_q24"]
    need(set(frozen) == set(source_by_id), "incomplete real public feature census")
    # Labels are present ONLY for fit. Heldout is a different, label-free
    # evidence family. No fictional sequential timestamp is synthesized.
    fit_rows = []
    held_rows = []
    for split, target in (("fit", fit_rows), ("heldout", held_rows)):
        for row in original_inputs[split]:
            record = {
                "case_id": row["id"],
                "source_text_sha256": digest(row["text"].encode("utf-8")),
                "feature_q24": frozen[row["id"]],
                "split": split,
            }
            if split == "fit":
                need(type(row.get("label")) is int and 0 <= row["label"] < 4,
                     "missing valid real fit-only label")
                record["train_label"] = row["label"]
            else:
                need("label" not in row and "train_label" not in row,
                     "heldout label leaked to candidate input owner")
            target.append(record)
    common = {
        "source_input_id": original_inputs["input_id"],
        "real_pretrained_encoder_snapshot_sha256": receipt["encoder_snapshot_sha256"],
        "train_only_projection_safetensors_sha256": projection_sha256,
        "input_feature_snapshot_sha256": snapshot_sha256,
        "feature_dimension": 32,
        "temporal_observation_kind":
            "UNORDERED_IID_ONE_TICK_PER_CASE_NOT_FUTURE_OR_RETENTION",
        "authority": "DENY_ALL",
        "production_qualification": False,
        "ndu_eligible": False,
    }
    train_bundle = {
        "schema": "hepta.neuron.real-public-q24-iid-fit-inputs.v1",
        **common, "rows": fit_rows,
        "fit_labels_only": True,
        "holdout_labels_exposed": False,
    }
    heldout_bundle = {
        "schema": "hepta.neuron.real-public-q24-iid-heldout-unlabeled.v1",
        **common, "rows": held_rows,
        "fit_labels_only": False,
        "holdout_labels_exposed": False,
    }
    plan = {
        "schema": "hepta.neuron.real-public-q24-iid-predeclared-plan.v1",
        "same_frozen_feature_source": snapshot_sha256,
        "fit_case_count": 64, "heldout_case_count": 32,
        "binary_tasks": [
            {"class_id": k, "positive_intent": name,
             "label_rule": "ONE_VS_REST_FROM_FIT_ONLY"}
            for k, name in enumerate(CLASSES)
        ],
        "candidate_mechanisms": ["v2", "v3", "ssm", "min_gru"],
        "candidate_private_serialized_byte_budgets": [8192, 32768],
        "selected_original_v1_no_change_a0_verified": False,
        "longitudinal_or_future_task_efficacy_claim_permitted": False,
        "independent_heldout_labels_joined": False,
        "training_execution_performed": False,
        "authority": "DENY_ALL", "decision": "NO_MODEL_PROMOTION",
    }
    return train_bundle, heldout_bundle, plan


def produce_from_original(args) -> None:
    owner = verify_local_original_source(args.original_source)
    original = read_original_public_inputs(owner, args.public_data)
    root = Path(args.public_q24_dir)
    need(root.is_dir() and not root.is_symlink(),
         "missing/symlinked physical public Q24 feature producer")
    original_snapshot = read(root / "snapshot.json")
    projection = read(root / "projection.safetensors")
    registry_raw = read(root / "registry.json")
    receipt = unique_json(read(root / "producer-receipt.json"))
    fit, heldout, plan = bind_public_iid(
        unique_json(original_snapshot), unique_json(registry_raw), receipt, original,
        projection_sha256=digest(projection),
        registry_sha256=digest(registry_raw),
        snapshot_sha256=digest(original_snapshot),
    )
    root_out = Path(args.output)
    root_out.mkdir(parents=True, exist_ok=False)
    # Train labels stay local, separate from label-free heldout inputs.
    for name, object_value in (
        ("fit-only-q24.json", fit), ("heldout-unlabeled-q24.json", heldout),
        ("predeclared-iid-plan.json", plan),
    ):
        with (root_out / name).open("xb") as output:
            output.write(canonical(object_value))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--original-source", type=Path, required=True)
    ap.add_argument("--public-data", type=Path, required=True)
    ap.add_argument("--public-q24-dir", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    try:
        produce_from_original(args)
        return 0
    except (ValueError, OSError, TypeError, KeyError, subprocess.CalledProcessError) as exc:
        print("BLOCKED_REAL_PUBLIC_IID_Q24_INPUT: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
