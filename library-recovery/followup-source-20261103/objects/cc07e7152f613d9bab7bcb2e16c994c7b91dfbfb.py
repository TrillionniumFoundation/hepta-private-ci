#!/usr/bin/env python3
"""Reproduce four independent linear Cell heads on sealed PUBLIC Q24 features.

Research only. No authority, no pretrained weight reload, no test labels, no
production baseline or future-window/ND U claim. The GitHub Actions source
artifact must be obtained separately and supplied as a local ZIP file.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import struct
from pathlib import Path
from zipfile import ZipFile

Q = 1 << 24
SOURCE_ZIP_SHA256 = "dfbef09702004bae8ce111f360584b6c9c641cc1b4475b71ef2b6d68af95a77a"
SOURCE_SEAL_SHA256 = "180955ec4e74cb985851f7c1ba5ae295b91fc3b5ea2188379e8a958e557e7cc2"
MODEL_REV = "8949b909ec900327062f0ebf497f51aef5e6f0c8"
DATA_REV = "57ec275d8078af65b7731c2a98be812d844a6d6b"
ENCODER_IDENTITY = b"research-only pinned ModernBERT-base source"
ROOT = "public-q24-feature-snapshot/"
FILES = {
    "case-registry.json", "feature-q24.safetensors", "pooled-f32.safetensors",
    "train-only-pca32.safetensors",
}
SEED = 17
STEPS = 120


def must(yes, reason):
    if not yes:
        raise ValueError(reason)


def strict_json(raw):
    def pairs(values):
        result = {}
        for k, v in values:
            must(k not in result, "duplicate JSON field")
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def source(path):
    from safetensors.torch import load
    import torch

    contents = Path(path).read_bytes()
    must(len(contents) < 2_000_000 and hashlib.sha256(contents).hexdigest() == SOURCE_ZIP_SHA256,
         "unexpected source ZIP revision")
    with ZipFile(io.BytesIO(contents)) as z:
        must(set(z.namelist()) == {ROOT + name for name in FILES | {"SEALED.json"}}
             | {"public-q24-independent-verdict.json"}, "archive inventory mismatch")
        raw = {name: z.read(ROOT + name) for name in FILES | {"SEALED.json"}}
        verdict = strict_json(z.read("public-q24-independent-verdict.json"))
    must(hashlib.sha256(raw["SEALED.json"]).hexdigest() == SOURCE_SEAL_SHA256,
         "seal digest mismatch")
    seal, cases = strict_json(raw["SEALED.json"]), strict_json(raw["case-registry.json"])
    ident = seal["source_identity"]
    must(seal.get("source_class") == "REAL_PINNED_PUBLIC_ENCODER"
         and seal.get("authority") == "DENY_ALL"
         and seal.get("decision") == "NO_MODEL_PROMOTION"
         and seal.get("physical_encoder_forward_calls_this_snapshot") == 96
         and ident.get("model_revision") == MODEL_REV
         and ident.get("dataset_revision") == DATA_REV
         and seal.get("split_counts") == {"fit":64, "heldout":32}
         and verdict.get("train_only_pca32_exact") is True
         and verdict.get("heldout_labels_absent") is True,
         "source manifest not the pinned research profile")
    must(all(seal.get(field) is False for field in (
        "production_qualification", "ndu_eligible", "heldout_predictions_or_labels_scored",
        "future_window_utility_verified", "no_change_production_v1_baseline_verified",
        "source_group_or_temporal_independence_verified"
    )), "unexpected claimed authority")
    for name in FILES:
        proof = seal["files"][name]
        must(proof["bytes"] == len(raw[name])
             and proof["sha256"] == hashlib.sha256(raw[name]).hexdigest(),
             "source member tampered: " + name)
    fit, heldout = cases["fit"], cases["heldout"]
    must(len(fit) == 64 and len(heldout) == 32
         and len({r["id"] for r in fit + heldout}) == 96
         and all(type(r.get("label")) is int and 0 <= r["label"] < 4 for r in fit)
         and all("label" not in r for r in heldout),
         "label leakage or case drift")
    payload = load(raw["feature-q24.safetensors"])
    must(set(payload) == {"fit", "heldout"}, "unknown feature split")
    for split, count in (("fit", 64), ("heldout", 32)):
        data = payload[split]
        must(data.shape == (count, 32) and data.dtype == torch.int64
             and bool((data.abs() <= 8 * Q).all()), "invalid Q24 tensor")
    return payload, [r["label"] for r in fit], hashlib.sha256(raw["SEALED.json"]).hexdigest()


def qround(raw):
    floor, remainder = divmod(int(raw), Q)
    return floor + int(2 * remainder > Q or (2 * remainder == Q and floor % 2 != 0))


def head_digest(cell, encoder, row, bias):
    payload = bytearray(b"hepta.infer.gated-cpu-head.v2")
    name = cell.encode("utf-8")
    payload.extend(struct.pack(">I", len(name)))
    payload.extend(name)
    payload.extend(encoder.encode("ascii"))
    payload.extend(struct.pack(">QQ", 32, 1))
    blocks = ([Q] * 32, row, [0] * 32, [bias], [0])
    for values in blocks:
        payload.extend(struct.pack(">Q", len(values)))
        for value in values:
            payload.extend(struct.pack(">q", value))
    return hashlib.sha256(payload).hexdigest()


def q24_outputs(features, weights, biases):
    rows = features.tolist()
    return [[qround(biases[c] * Q + sum(w * x for w, x in zip(weights[c], row)))
             for c in range(4)] for row in rows]


def build(path):
    import torch
    features, labels, sealed_sha = source(path)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(SEED)
    torch.backends.mkldnn.enabled = False
    model = torch.nn.Linear(32, 4)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.01, weight_decay=.01)
    inputs = features["fit"].float() / Q
    target = torch.tensor(labels, dtype=torch.long)
    must(torch.bincount(target, minlength=4).tolist() == [16, 16, 16, 16], "class imbalance")
    for _ in range(STEPS):
        optimizer.zero_grad(set_to_none=True)
        torch.nn.functional.cross_entropy(model(inputs), target).backward()
        optimizer.step()
    model.eval()
    weights = [[round(float(w) * Q) for w in row]
               for row in model.weight.detach().tolist()]
    biases = [round(float(b) * Q) for b in model.bias.detach().tolist()]
    must(all(abs(v) <= 8 * Q for row in weights for v in row)
         and all(abs(v) <= 8 * Q for v in biases), "Q24 weight limit")
    outputs = {split: q24_outputs(features[split], weights, biases)
               for split in ("fit", "heldout")}
    tolerance_q24 = 64
    errors = {}
    with torch.inference_mode():
        for split, count in (("fit", 64), ("heldout", 32)):
            native = torch.tensor(outputs[split], dtype=torch.int64)
            fp32 = model(features[split].float() / Q)
            expected = torch.round(fp32.double() * Q).to(torch.int64)
            err = int((expected - native).abs().max())
            disagreements = int((native.argmax(1) != fp32.argmax(1)).sum())
            must(err <= tolerance_q24 and disagreements == 0,
                 "quantization changed argmax or exceeded parity budget")
            must(bool((native.abs() <= 8 * Q).all()), "Rust output profile exceeded")
            errors[split] = {"rows": count, "max_integer_logit_drift": err,
                             "argmax_disagreements": disagreements}
    encoder = hashlib.sha256(ENCODER_IDENTITY).hexdigest()
    head_digests = [head_digest(f"cell.public.linear.{i}", encoder, weights[i], biases[i])
                    for i in range(4)]
    catalog = bytearray(b"hepta.infer.gated-cpu-catalog.v2")
    catalog.extend(struct.pack(">Q", 4))
    for digest in sorted(head_digests):
        catalog.extend(digest.encode("ascii"))
    full = b"".join(struct.pack(">q", n)
                    for split in ("fit", "heldout") for row in outputs[split] for n in row)
    return {
        "schema":"hepta.public-q24-linear-native-parity.v1",
        "authority":"DENY_ALL", "promotion_permitted":False,
        "training_only_fit_accuracy": float((model(inputs).argmax(1) == target).float().mean()),
        "heldout_labels_scored":False, "ndu_future_utility_verified":False,
        "model_reexecution":False, "model_revision":MODEL_REV, "dataset_revision":DATA_REV,
        "source_zip_sha256":SOURCE_ZIP_SHA256, "source_seal_sha256":sealed_sha,
        "source_encoder_forwards":96, "training_seed":SEED, "training_steps":STEPS,
        "torch_version":torch.__version__, "quantization":"Q24 nearest ties-even",
        "encoder_digest":encoder, "fixed_gate":"all Q24_ONE, not trainable",
        "trainable_fp32_linear_parameters":132,
        "registered_rust_gated_head_tensor_parameters":392,
        "registered_rust_gated_head_bytes":392 * 8,
        "head_digests":head_digests,
        "head_catalog_digest":hashlib.sha256(catalog).hexdigest(),
        "weights_q24":weights, "bias_q24":biases, "error_bounds":errors,
        "samples": {
            split: {"case_id": split + "-0", "features_q24":features[split][0].tolist(),
                    "logits_q24":outputs[split][0]}
            for split in ("fit", "heldout")
        },
        "all_96_logits_q24_sha256":hashlib.sha256(full).hexdigest(),
        "note":"Real saved public Encoder features; one training cohort only. Rust CPU head and Q24 transfer are not independent model/production authorization, efficacy, NDU or target-host acceptance.",
    }


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--snapshot",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args()
    must(not a.output.exists(),"output already exists")
    result=build(a.snapshot)
    a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"output":str(a.output), "parity":result["error_bounds"],
                      "catalog":result["head_catalog_digest"]}))


if __name__ == "__main__":
    main()
