"""Pre-registered hard-charge BANKING77 cohort for real shared-Stem comparison.

Separate v3 source/receipt identities preserve all v1 and v2 original bytes.
This is a same-publisher IID stress cohort, never a future/NDU qualification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stem-optimal-v1"))
import stem_candidate_v1 as base

COHORT = "hard-charge-four-intents-v3"
DATA_SCHEMA = "hepta.stem.charge-stress.source.v3"
RUN_SCHEMA = "hepta.stem.charge-stress.physical-unattested.v3"
INTENTS = (
    "card_payment_fee_charged",
    "cash_withdrawal_charge",
    "exchange_charge",
    "transfer_fee_charged",
)
SAMPLE_SALT = "hepta-stem-hard-charge-v3\x00"
ORDER_SALT = "hepta-stem-hard-charge-order-v3\x00"


def _select(train, test):
    selected = {"train": [], "heldout": []}
    for split, rows, n in (("train", train, 16), ("heldout", test, 8)):
        for label, intent in enumerate(INTENTS):
            eligible = [text for text, category in rows.items()
                        if category == intent and (split == "train" or text not in train)]
            eligible.sort(key=lambda text: base.sha256((SAMPLE_SALT + text).encode()))
            base.need(len(eligible) >= n, f"too few original {split} cases for registered intent")
            for text in eligible[:n]:
                digest = base.sha256(text.encode("utf-8"))
                row = {"case_id": ("fit:" if split == "train" else "heldout:") + digest,
                       "source_sha256": digest, "text": text}
                if split == "train":
                    row["label"] = label
                selected[split].append(row)
    for split in selected:
        selected[split].sort(
            key=lambda row: base.sha256((ORDER_SALT + row["case_id"]).encode())
        )
    return selected


def prepare(train_raw: bytes, test_raw: bytes, *, hashes=base.ORIGINAL_SHA):
    base.need(set(hashes) == {"train", "test"}, "invalid publisher manifest")
    train = base._parse_source(train_raw, hashes["train"])
    test = base._parse_source(test_raw, hashes["test"])
    selected = _select(train, test)
    result = {
        "schema": DATA_SCHEMA, "cohort": COHORT, "intents": list(INTENTS),
        "publisher_revision": base.ORIGINAL_COMMIT, "publisher_sha256": hashes,
        "train": selected["train"], "heldout": selected["heldout"],
        "heldout_labels_excluded": True, "research_only": True,
        "production_authorized": False,
    }
    result["source_plan_sha256"] = base.sha256(base.canonical(result))
    return result


def verify_source(source, *, hashes=base.ORIGINAL_SHA):
    expected = {"schema", "cohort", "intents", "publisher_revision",
                "publisher_sha256", "train", "heldout", "heldout_labels_excluded",
                "research_only", "production_authorized", "source_plan_sha256"}
    base.need(type(source) is dict and set(source) == expected, "invalid v3 source envelope")
    base.need(source["schema"] == DATA_SCHEMA and source["cohort"] == COHORT
              and source["intents"] == list(INTENTS), "wrong cohort/profile")
    base.need(source["publisher_revision"] == base.ORIGINAL_COMMIT
              and source["publisher_sha256"] == hashes, "wrong original publisher")
    base.need(source["heldout_labels_excluded"] is True
              and source["research_only"] is True
              and source["production_authorized"] is False, "source authority or labels")
    base.need(type(source["source_plan_sha256"]) is str
              and base.sha256(base.canonical({k: v for k, v in source.items()
                                              if k != "source_plan_sha256"}))
              == source["source_plan_sha256"], "source plan digest mismatch")
    base.need(type(source["train"]) is list and len(source["train"]) == 64
              and type(source["heldout"]) is list and len(source["heldout"]) == 32,
              "v3 cohort cardinality")
    seen = set()
    counts = [0] * len(INTENTS)
    for split in ("train", "heldout"):
        for row in source[split]:
            fields = {"case_id", "source_sha256", "text", "label"} if split == "train" else {
                "case_id", "source_sha256", "text"
            }
            base.need(type(row) is dict and set(row) == fields, "unexpected source/heldout labels")
            text = row["text"]
            base.need(type(text) is str and 0 < len(text.encode()) <= 4096
                      and base.norm(text) == text, "noncanonical source text")
            digest = base.sha256(text.encode())
            base.need(row["source_sha256"] == digest and row["case_id"]
                      == ("fit:" if split == "train" else "heldout:") + digest,
                      "source row identity mismatch")
            base.need(digest not in seen, "source leak/duplicate across splits")
            seen.add(digest)
            if split == "train":
                label = row["label"]
                base.need(type(label) is int and 0 <= label < len(INTENTS),
                          "invalid fit class")
                counts[label] += 1
    base.need(counts == [16] * len(INTENTS), "unequal registered fit sampling")


def physical_run(source, materials, candidate):
    verify_source(source)
    base.need(candidate in base.MODEL_NAMES, "unregistered Encoder")
    base.need(materials["training"] == {
        "seed": 17, "steps": 100, "learning_rate": 0.006,
        "per_cell_parameters": 6914, "cells": 4
    }, "training budget changed")
    spec = materials["candidates"][candidate]
    import torch
    torch.set_num_threads(2)
    start = time.perf_counter()
    cpu = time.process_time()
    tok, model = base._material_model(spec)
    model_load = time.perf_counter() - start
    encode_start = time.perf_counter()
    fit, n_fit = base._encode([row["text"] for row in source["train"]], tok, model)
    held, n_held = base._encode([row["text"] for row in source["heldout"]], tok, model)
    encode_wall = time.perf_counter() - encode_start
    base.need(tuple(fit.shape) == (64, 384) and tuple(held.shape) == (32, 384),
              "real Encoder width/cardinality mismatch")
    heads = base._torch_head_training(
        fit, [row["label"] for row in source["train"]],
        held, config=materials["training"]
    )
    rows = [
        {"case_id": row["case_id"], "source_sha256": row["source_sha256"],
         "scores": {arm: heads[arm][i]
                    for arm in ("frozen_init", "centroid", "learned")}}
        for i, row in enumerate(source["heldout"])
    ]
    return {
        "schema": RUN_SCHEMA, "cohort": COHORT, "candidate": candidate,
        "source_plan_sha256": source["source_plan_sha256"],
        "material_manifest_sha256": base.sha256(base.canonical(materials)),
        "model_repo": spec["repo"], "model_revision": spec["revision"],
        "actual_weight_sha256": spec["weight_sha256"],
        "initial_head_sha256": heads["initial_head_sha256"],
        "trained_head_sha256": heads["trained_head_sha256"],
        "head_parameters": heads["total_head_parameters"],
        "optimizer_steps": heads["steps"], "rows": rows,
        "cost": {
            "physical_encoder_sequences": 96, "encoder_forward_batches": n_fit + n_held,
            "elapsed_wall_seconds": time.perf_counter() - start,
            "elapsed_cpu_seconds": time.process_time() - cpu,
            "model_download_load_wall_seconds": model_load,
            "feature_encode_wall_seconds": encode_wall,
            "head_train_wall_seconds": heads["training_wall_seconds"],
            "maxrss_bytes": base._peak_rss_bytes(),
            "energy_joules": None, "p99_latency_ms": None,
        },
        "publisher_future_windows": 0, "matched_421m_lifecycle": False,
        "physical_claim_unattested": True, "production_authorized": False,
        "disposition": "HOLD_NO_GO", "authority": "DENY_ALL",
    }


def main():
    parser = argparse.ArgumentParser()
    modes = parser.add_subparsers(dest="mode", required=True)
    p = modes.add_parser("prepare")
    p.add_argument("--train", required=True)
    p.add_argument("--test", required=True)
    p.add_argument("--output", required=True)
    p = modes.add_parser("infer")
    p.add_argument("--source", required=True)
    p.add_argument("--materials", required=True)
    p.add_argument("--candidate", required=True, choices=base.MODEL_NAMES)
    p.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        result = prepare(Path(args.train).read_bytes(), Path(args.test).read_bytes())
    else:
        source = json.loads(Path(args.source).read_text(encoding="utf-8"))
        verify_source(source)
        materials = base.load_materials(Path(args.materials))
        result = physical_run(source, materials, args.candidate)
    base._write_new(args.output, result)
    print(json.dumps({"schema": result["schema"], "sha256":
                      base.sha256(Path(args.output).read_bytes()),
                      "authority": "DENY_ALL"}, sort_keys=True))


if __name__ == "__main__":
    main()
