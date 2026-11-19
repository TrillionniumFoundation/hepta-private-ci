#!/usr/bin/env python3
"""Independently join archived *evidence identities*; never compare unlike Cells.

One study physically executed a frozen ModernBERT on BANKING77 public text;
the other used synthetic 32D Q24 features. Their quality/latency results
must NOT be pooled, converted to a common score, or used for NDU promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import stat
import sys
import zipfile

PUBLIC_ZIP_SHA = "fd89f174057d98bd2d4f03447d5d5dd9372723e70128ccdf2dcbe73f67a0a03a"
Q24_ZIP_SHA = "fc74e1720fc104ccbd573808c1ed9c6714a3a15b486410351065021dbe82b0ed"
REVISION = "57ec275d8078af65b7731c2a98be812d844a6d6b"
PREFIX = "public-cell-learning/"
ARMS = ("dense16", "sparse16_top2")
PUBLIC_NAMES = frozenset({
    "public-cell-learning.log",
    *(PREFIX + s for s in (
        "pre-execution-plan.json", "selection.json", "scores.json",
        "data/SOURCE.json", "data/MATERIAL.json", "data/LICENSE",
        "trial/COMMITTED.json", "trial/plan.json", "trial/shared-encoder.json",
        *(f"trial/{arm}/{name}" for arm in ARMS for name in (
            "COMMITTED.json", "bank.safetensors", "execution.json", "predictions.json"
        )),
    )),
})
Q24_NAMES = frozenset((
    "hepta-near-matched-audit.json",
    "hepta-near-matched-fixture.json",
    "hepta-near-matched-trained/training-receipt.json",
    "hepta-physical-byte-plan.json",
    "hepta-byte-matched-native-audit.json",
    "hepta-byte-matched-trained/training-receipt.json",
))


class Rejected(ValueError):
    pass


def need(test: bool, reason: str) -> None:
    if not test:
        raise Rejected(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def document(raw: bytes):
    def reject_repeats(items):
        result = {}
        for key, value in items:
            need(key not in result, "duplicate evidence JSON key")
            result[key] = value
        return result

    def finite(token):
        value = float(token)
        need(math.isfinite(value), "nonfinite evidence numeric field")
        return value

    return json.loads(
        raw, object_pairs_hook=reject_repeats, parse_float=finite,
        parse_constant=lambda _: (_ for _ in ()).throw(Rejected("nonfinite JSON")),
    )


def immutable_zip(path: Path, digest: str, names: frozenset, limit: int) -> dict:
    need(not path.is_symlink(), "symlinked hosted ZIP")
    prior = path.stat()
    need(stat.S_ISREG(prior.st_mode) and 100 < prior.st_size <= limit,
         "unbounded/nonregular archive")
    raw = path.read_bytes()
    after = path.stat()
    need(all(getattr(prior, k) == getattr(after, k) for k in (
        "st_dev", "st_ino", "st_size", "st_ctime_ns", "st_mtime_ns"
    )), "original ZIP changed while reading")
    need(sha(raw) == digest, "frozen original ZIP SHA256 mismatch")
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        need(len(infos) == len(names) and {i.filename for i in infos} == names,
             "foreign/duplicate/missing artifact member")
        need(all(
            0 < i.file_size < 2_000_000 and 0 < i.compress_size < 2_000_000
            and not stat.S_ISLNK(i.external_attr >> 16)
            for i in infos
        ), "unsafe/unbounded ZIP member")
        return {i.filename: archive.read(i) for i in infos}


def public_census(blobs: dict) -> dict:
    read = lambda relative: document(blobs[PREFIX + relative])
    origin = read("data/SOURCE.json")
    material = read("data/MATERIAL.json")
    plan = read("pre-execution-plan.json")
    selection = read("selection.json")
    scores = read("scores.json")
    terminals = read("trial/COMMITTED.json")
    shared_bytes = blobs[PREFIX + "trial/shared-encoder.json"]
    shared = document(shared_bytes)
    encoder_sha = sha(shared_bytes)
    need(origin["revision"] == material["source"]["revision"]
         == scores["dataset_revision"] == REVISION,
         "public BANKING77 source revision drift")
    need(origin["license"] == "CC-BY-4.0", "public dataset attribution missing")
    for split, name in (("train", "train"), ("test", "test")):
        need(material["sha256"][f"banking_data/{name}.csv"]
             == selection["raw_sha256"][split]
             == scores["dataset_files_sha256"][split],
             "public source file identity mismatch")
    need(plan == read("trial/plan.json") and
         sha(blobs[PREFIX + "trial/plan.json"]) == terminals["plan_sha256"]
         and plan["train_steps"] == 64
         and plan["arms"] == {"dense16": 16, "sparse16_top2": 2},
         "unfrozen source plan or changed training exposure")
    fit, held = selection["selected_ids"]["fit"], selection["selected_ids"]["heldout"]
    need(len(fit) == len(set(fit)) == 64
         and len(held) == len(set(held)) == 32
         and set(fit).isdisjoint(held),
         "public fit/test leak or incomplete sample census")
    need(scores["fitting_examples"] == 64 and scores["heldout_examples"] == 32
         and scores["all_arms_completed"] is True
         and scores["production_authorized"] is False
         and scores["efficacy_established"] is False
         and scores["observer_independence_established"] is False
         and scores["pretraining_contamination_checked"] is False,
         "archived public study overclaimed efficacy or was incomplete")
    need(terminals["shared_encoder_sha256"] == encoder_sha
         and scores["shared_encoder"] == shared
         and shared["counted_once_for_both_arms"] is True
         and shared["feature_payload_bytes"] == 294_912,
         "original shared Encoder physical identity/shape drift")
    encoder = shared["encoder_receipt"]
    need(encoder["complete_checkpoint"]["loading"]["complete"] is True
         and encoder["pretrained_provenance_independently_verified"] is False
         and encoder["snapshot_sha256"] == plan["snapshot_sha256"],
         "original pretrained weights improperly qualified")

    observations = []
    for arm in ARMS:
        root = f"trial/{arm}/"
        seal = read(root + "COMMITTED.json")
        execution = read(root + "execution.json")
        predictions = read(root + "predictions.json")
        need(type(predictions) is list and len(predictions) == 32
             and {record["id"] for record in predictions} == set(held),
             "wrong original heldout prediction IDs")
        for record in predictions:
            for key in ("before_logits", "after_logits"):
                values = record[key]
                need(type(values) is list and len(values) == 4
                     and all(type(x) in (int, float) and math.isfinite(x) for x in values),
                     "incomplete or nonfinite public prediction logits")
        need(all(
            sha(blobs[PREFIX + root + name]) == digest
            for name, digest in seal["files"].items()
        ), "original public weight/prediction/execution seal SHA mismatch")
        need(seal["seal_id"] == terminals["terminals"][arm]["id"]
             and terminals["terminals"][arm]["kind"] == "completed",
             "original terminal not committed")
        need(execution == scores["scores"][arm]["execution"]
             and execution["shared_encoder_sha256"] == encoder_sha
             and execution["plan_id"] == terminals["plan_id"] == plan["plan_id"]
             and execution["heldout_labels_loaded"] is False
             and execution["production_authorized"] is False,
             "published public learning execution/encoder drift")
        result = scores["scores"][arm]
        need(result["status"] == "completed" and
             result["before"]["count"] == result["after"]["count"] == 32,
             "missing public test observations")
        for stage in ("before", "after"):
            accuracy = result[stage]["accuracy"]
            need(type(accuracy) in (int, float) and 0 <= accuracy <= 1
                 and abs(accuracy * 32 - round(accuracy * 32)) < 1e-10,
                 "implausible heldout aggregate")
        observations.append({
            "arm": arm, "heldout_count": 32,
            "physical_bank_sha256": seal["files"]["bank.safetensors"],
            "before_accuracy": result["before"]["accuracy"],
            "after_accuracy": result["after"]["accuracy"],
            "reported_gain": result["after"]["accuracy"] - result["before"]["accuracy"],
            "private_parameters": execution["inventory"]["parameters"],
            "optimizer_steps": execution["training"]["steps"],
        })
    return {
        "dataset": "BANKING77_PUBLIC_4_CLASS_SUBSET",
        "dataset_revision": REVISION,
        "shared_encoder_sha256": encoder_sha,
        "training_count": 64,
        "heldout_count": 32,
        "arms": observations,
        "original_heldout_labels_reopened": False,
        "reported_accuracy_independently_recomputed": False,
    }


def q24_census(blobs: dict) -> dict:
    obj = lambda name: document(blobs[name])
    fixture = obj("hepta-near-matched-fixture.json")
    preflight = obj("hepta-physical-byte-plan.json")
    need(fixture["source_kind"] == "SYNTHETIC_ONLY"
         and fixture["real_encoder_executed"] is False
         and preflight["predeclared_byte_caps"] == [8192, 32768]
         and preflight["genuine_learned_weights_measured"] is False,
         "Q24 synthetic input presented as real pretrained Encoder")
    unique_weights = set()
    observations = []
    for kind, training_path, verdict_path in (
        ("parameters", "hepta-near-matched-trained/training-receipt.json",
         "hepta-near-matched-audit.json"),
        ("bytes", "hepta-byte-matched-trained/training-receipt.json",
         "hepta-byte-matched-native-audit.json"),
    ):
        training = obj(training_path)
        verdict = obj(verdict_path)
        need(verdict["training_receipt_sha256"] == sha(blobs[training_path])
             and training["actual_train_input_sha256"] == fixture["train_sha256"]
             and verdict["frozen_input_trace_sha256"] == fixture["trace_sha256"],
             "Q24 original input/trainer/native SHA drift")
        need(training["physical_model_file_count"] == 8
             and verdict["physically_loaded_models"] == 8
             and verdict["actual_native_os_processes"] == 16
             and verdict["independent_integer_adapter_head_parity"] is True
             and verdict["independent_temporal_model_parity"] is False
             and training["production_qualification"] is False
             and verdict["production_qualification"] is False,
             "Q24 produced unsupported production/model qualifications")
        models, rows = training["cells"], verdict["rows"]
        need(type(models) is list and type(rows) is list
             and len(models) == len(rows) == 8
             and len({(m["cap"], m["arm"]) for m in models}) == 8,
             "Q24 physical model census incomplete")
        for model in models:
            need(model["weight_sha256"] not in unique_weights,
                 "Q24 studies reused same model weights")
            unique_weights.add(model["weight_sha256"])
        for row in rows:
            found = [m for m in models
                     if m["cap"] == row["cap"] and m["arm"] == row["arm"]]
            need(len(found) == 1
                 and row["physical_weight_sha256"] == found[0]["weight_sha256"]
                 and row["verified_native_adapter_head_event_count"] == 8,
                 "Q24 independent integer replay not bound to trained weights")
        observations.append({
            "budget_kind": kind, "trained_model_count": 8,
            "native_process_count": 16, "head_adapter_integer_parity": True,
        })
    return {"study_input_kind": "SYNTHETIC_32D_Q24",
            "unique_model_sha256_count": len(unique_weights),
            "studies": observations, "actual_future_task_quality_verified": False}


def audit(public_path: Path, q24_path: Path) -> dict:
    public = public_census(immutable_zip(public_path, PUBLIC_ZIP_SHA,
                                         PUBLIC_NAMES, 6_000_000))
    q24 = q24_census(immutable_zip(q24_path, Q24_ZIP_SHA,
                                   Q24_NAMES, 150_000))
    need(q24["unique_model_sha256_count"] == 16, "missing Q24 model census")
    return {
        "schema": "hepta.neuron.real-public-to-q24-evidence-boundary.v1",
        "input_zip_sha256": {"public": PUBLIC_ZIP_SHA, "q24": Q24_ZIP_SHA},
        "public_encoder_learning": public,
        "synthetic_q24_mechanism": q24,
        "authority": "DENY_ALL", "decision": "NO_CROSS_STUDY_MODEL_SELECTION",
        "same_training_and_heldout_samples": False,
        "real_public_encoder_features_q24_32d_archived": False,
        "real_public_encoder_executed_in_q24_cell": False,
        "independent_prospective_future_window_verified": False,
        "equal_training_flops_or_memory_verified": False,
        "ndu_eligible": False, "production_qualification": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-zip", type=Path, required=True)
    parser.add_argument("--q24-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.public_zip, args.q24_zip)
        with args.output.open("x", encoding="utf-8") as out:
            json.dump(result, out, indent=2, sort_keys=True, allow_nan=False)
            out.write("\n")
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print("BLOCKED_REAL_PUBLIC_Q24_EVIDENCE_JOIN: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
