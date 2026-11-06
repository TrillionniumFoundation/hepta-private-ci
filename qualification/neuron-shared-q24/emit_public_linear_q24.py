#!/usr/bin/env python3
"""DENY_ALL: export deterministic four-Cell linear Q24 parameters from public features.

No network, pretrained model execution, heldout labels, independent efficacy,
Final-use authorization, NDU acceptance or promotion.
Input: Actions 38902031341 / artifact 12068510329 (ZIP provided locally).
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import torch
from safetensors.torch import load

Q = 1 << 24
ROOT = 'public-q24-feature-snapshot/'
MEMBERS = {'SEALED.json', 'case-registry.json', 'feature-q24.safetensors',
           'pooled-f32.safetensors', 'train-only-pca32.safetensors'}
MODEL_REV = '8949b909ec900327062f0ebf497f51aef5e6f0c8'
DATA_REV = '57ec275d8078af65b7731c2a98be812d844a6d6b'
PINNED_ZIP_SHA256 = 'dfbef09702004bae8ce111f360584b6c9c641cc1b4475b71ef2b6d68af95a77a'
PINNED_SEAL_SHA256 = '180955ec4e74cb985851f7c1ba5ae295b91fc3b5ea2188379e8a958e557e7cc2'


def demand(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(raw):
    def pairs(entries):
        result = {}
        for k, v in entries:
            demand(k not in result, 'duplicate JSON key')
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def audited_inputs(path):
    raw = Path(path).read_bytes()
    demand(0 < len(raw) < 2_000_000, 'archive size')
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        demand(set(z.namelist()) == {ROOT + f for f in MEMBERS} |
               {'public-q24-independent-verdict.json'}, 'archive inventory')
        demand(all(0 < f.file_size <= 500_000 for f in z.infolist()), 'member cap')
        blobs = {f: z.read(ROOT + f) for f in MEMBERS}
        verdict = strict_json(z.read('public-q24-independent-verdict.json'))
    seal, cases = strict_json(blobs['SEALED.json']), strict_json(blobs['case-registry.json'])
    identity = seal.get('source_identity', {})
    demand(seal.get('schema') == 'hepta.neuron.real-public-modernbert-q24-features.v1'
           and seal.get('source_class') == 'REAL_PINNED_PUBLIC_ENCODER'
           and identity.get('model_id') == 'answerdotai/ModernBERT-base'
           and identity.get('model_revision') == MODEL_REV
           and identity.get('dataset_revision') == DATA_REV
           and seal.get('physical_encoder_forward_calls_this_snapshot') == 96
           and seal.get('authority') == 'DENY_ALL'
           and seal.get('decision') == 'NO_MODEL_PROMOTION'
           and seal.get('split_counts') == {'fit': 64, 'heldout': 32}
           and seal.get('projection_fitted_on') == 'UNLABELED_FIT_FEATURES_ONLY', 'source identity')
    demand(all(seal.get(k) is False for k in (
        'production_qualification', 'ndu_eligible', 'heldout_predictions_or_labels_scored',
        'future_window_utility_verified', 'no_change_production_v1_baseline_verified',
        'source_group_or_temporal_independence_verified')), 'overstated source authority')
    demand(set(seal.get('files', {})) == MEMBERS - {'SEALED.json'}, 'unsealed files')
    for n, proof in seal['files'].items():
        demand(proof['bytes'] == len(blobs[n]) and
               proof['sha256'] == hashlib.sha256(blobs[n]).hexdigest(), 'payload mismatch')
    seal_sha = hashlib.sha256(blobs['SEALED.json']).hexdigest()
    demand(verdict.get('sealed_sha256') == seal_sha and
           verdict.get('train_only_pca32_exact') is True and
           verdict.get('heldout_labels_absent') is True and
           verdict.get('fit_heldout_overlap_count') == 0 and
           verdict.get('production_qualification') is False, 'independent verdict mismatch')
    fit, hold = cases.get('fit', []), cases.get('heldout', [])
    demand(len(fit) == 64 and len(hold) == 32 and
           all(type(x.get('label')) is int and x['label'] in range(4) for x in fit) and
           all('label' not in x for x in hold) and
           len({x['id'] for x in fit + hold}) == 96, 'case leakage/shape')
    pooled = load(blobs['pooled-f32.safetensors'])
    q24 = load(blobs['feature-q24.safetensors'])
    pca = load(blobs['train-only-pca32.safetensors'])
    for split, count in [('fit',64),('heldout',32)]:
        demand(pooled[split].shape == (count,768) and pooled[split].dtype == torch.float32
               and torch.isfinite(pooled[split]).all().item()
               and q24[split].shape == (count,32) and q24[split].dtype == torch.int64
               and (q24[split].abs() <= 8*Q).all().item(), 'feature type/shape')
    demand(pca['components'].shape == (768,32) and pca['center'].shape == (768,)
           and pca['scale'].shape == (32,), 'PCA dimensions')
    archive_sha = hashlib.sha256(raw).hexdigest()
    demand(archive_sha == PINNED_ZIP_SHA256 and seal_sha == PINNED_SEAL_SHA256,
           'not the exact pinned physical public Q24 artifact')
    return fit, pooled, q24, pca, archive_sha, seal_sha



import struct

ENCODER_ID_BYTES = b"research-only pinned ModernBERT-base source"
EXPECTED_CATALOG = "147f1c8d6453ea51001e873b7dd93e37254f1e8b53aae3c103aa3441245f3640"


def signed_q48_to_q24(raw):
    floor, remainder = divmod(int(raw), Q)
    return floor + int(2 * remainder > Q or (2 * remainder == Q and floor % 2 != 0))


def native_logits(features, weights, biases):
    return [[signed_q48_to_q24(
        biases[category] * Q + sum(w * x for w, x in zip(weights[category], row))
    ) for category in range(4)] for row in features.tolist()]


def q24_head_digest(cell, encoder_digest, weights, bias):
    payload = bytearray(b"hepta.infer.gated-cpu-head.v2")
    ident = cell.encode("utf-8")
    payload.extend(struct.pack(">I", len(ident)))
    payload.extend(ident)
    payload.extend(encoder_digest.encode("ascii"))
    payload.extend(struct.pack(">QQ", 32, 1))
    for tensor in ([Q] * 32, weights, [0] * 32, [bias], [0]):
        payload.extend(struct.pack(">Q", len(tensor)))
        for number in tensor:
            payload.extend(struct.pack(">q", number))
    return hashlib.sha256(payload).hexdigest()


def export(path):
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(17)
    torch.backends.mkldnn.enabled = False
    cases, _pooled, features, _projector, zip_sha, seal_sha = audited_inputs(path)
    labels = torch.tensor([row["label"] for row in cases], dtype=torch.long)
    demand(torch.bincount(labels, minlength=4).tolist() == [16, 16, 16, 16],
           "bad class support")
    x_train = features["fit"].float() / Q
    model = torch.nn.Linear(32, 4)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.01, weight_decay=.01)
    for _ in range(120):
        optimizer.zero_grad(set_to_none=True)
        torch.nn.functional.cross_entropy(model(x_train), labels).backward()
        optimizer.step()
    model.eval()
    weights = [[round(float(w) * Q) for w in row]
               for row in model.weight.detach().tolist()]
    biases = [round(float(v) * Q) for v in model.bias.detach().tolist()]
    demand(all(abs(v) <= 8 * Q for row in weights for v in row)
           and all(abs(v) <= 8 * Q for v in biases), "unrepresentable Head tensors")
    observations = {}
    outputs = {}
    with torch.inference_mode():
        for split, count in (("fit", 64), ("heldout", 32)):
            output = native_logits(features[split], weights, biases)
            q24_result = torch.tensor(output, dtype=torch.int64)
            torch_result = model(features[split].float() / Q)
            reference = torch.round(torch_result.double() * Q).to(torch.int64)
            integer_error = int((q24_result - reference).abs().max())
            disagreements = int((q24_result.argmax(1) != torch_result.argmax(1)).sum())
            demand(integer_error <= 64 and disagreements == 0
                   and bool((q24_result.abs() <= 8 * Q).all()),
                   "native Q24 parity failed")
            observations[split] = {
                "rows": count, "max_integer_logit_drift": integer_error,
                "argmax_disagreements": disagreements,
            }
            outputs[split] = output
    encoder_digest = hashlib.sha256(ENCODER_ID_BYTES).hexdigest()
    heads = [q24_head_digest(f"cell.public.linear.{i}", encoder_digest, weights[i], biases[i])
             for i in range(4)]
    catalog = bytearray(b"hepta.infer.gated-cpu-catalog.v2")
    catalog.extend(struct.pack(">Q", len(heads)))
    for head in sorted(heads):
        catalog.extend(head.encode("ascii"))
    catalog_digest = hashlib.sha256(catalog).hexdigest()
    demand(catalog_digest == EXPECTED_CATALOG, "pinned native Head catalog drift")
    payload = b"".join(struct.pack(">q", value)
                       for split in ("fit", "heldout") for row in outputs[split] for value in row)
    result = {
        "schema": "hepta.public-q24-linear-native-parity.v1",
        "authority": "DENY_ALL", "promotion_permitted": False,
        "ndu_future_utility_verified": False, "heldout_labels_scored": False,
        "model_reexecution": False,
        "source_zip_sha256": zip_sha, "source_seal_sha256": seal_sha,
        "source_encoder_forwards": 96,
        "model_revision": MODEL_REV, "dataset_revision": DATA_REV,
        "training_seed": 17, "training_steps": 120,
        "torch_version": str(torch.__version__),
        "fixed_gate": "all Q24_ONE, not trainable",
        "trainable_fp32_linear_parameters": 132,
        "registered_rust_gated_head_tensor_parameters": 392,
        "registered_rust_gated_head_bytes": 392 * 8,
        "quantization": "Q24 nearest ties-even",
        "weights_q24": weights, "bias_q24": biases,
        "head_digests": heads, "head_catalog_digest": catalog_digest,
        "encoder_digest": encoder_digest,
        "training_only_fit_accuracy": float((model(x_train).argmax(1) == labels).float().mean()),
        "error_bounds": observations,
        "samples": {
            split: {
                "case_id": f"{split}-0",
                "features_q24": features[split][0].tolist(),
                "logits_q24": outputs[split][0],
            } for split in ("fit", "heldout")
        },
        "all_96_logits_q24_sha256": hashlib.sha256(payload).hexdigest(),
        "note": "Research only: saved real Encoder features and two numeric domains, not independent final-use, external utility or future-window learning acceptance.",
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    demand(not args.output.exists(), "cannot overwrite existing output")
    result = export(args.snapshot)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(json.dumps({"output": str(args.output), "catalog": result["head_catalog_digest"],
                      "error_bounds": result["error_bounds"]}))


if __name__ == "__main__":
    main()
