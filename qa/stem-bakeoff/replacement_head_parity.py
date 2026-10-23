"""P42 original frozen-Encoder, fixed-budget Head parity; SHADOW_ONLY.

Full Laya policy scores remain independent.  Every arm projects an original
frozen Encoder output to 256 dimensions using an untrained deterministic
matrix, then fits precisely 1,028 parameters with P39's identical optimizer.
This is controlled research, NOT equivalence to native decisions or release.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Callable

CONTEXT_TOKENS = 192
PROJECTED_WIDTH = 256
PROJECTION_SEED = 2307
HEAD_CLASSES = 4
HEAD_PARAMETERS = PROJECTED_WIDTH * HEAD_CLASSES + HEAD_CLASSES
SCHEMA = "hepta.neuron.replacement-frozen-head-parity.v1"


def _tensor_hash(tensor: Any) -> str:
    t = tensor.detach().cpu().contiguous()
    h = hashlib.sha256()
    h.update(json.dumps([list(t.shape), str(t.dtype)], separators=(",", ":")).encode())
    h.update(t.numpy().tobytes())
    return h.hexdigest()


def frozen_encode_rows(encoder: Any, tokenizer: Any, selected: dict,
                       *, pooling: str) -> tuple[dict, int]:
    """Exactly one additional native frozen Encoder forward per original row.

    Input to every candidate is *only the same source text*, not a cached Laya
    question-conditioned representation. We separately retain original policy
    measurements. The caller owns model/source/hash verification.
    """
    import torch
    import torch.nn.functional as F

    if pooling not in ("cls", "last_nonpad") or encoder.training or any(
            p.requires_grad for p in encoder.parameters()):
        raise ValueError("Encoder must be frozen, eval and use registered pooling")
    vectors = {}
    count = 0
    with torch.inference_mode():
        for split, rows in selected.items():
            if not isinstance(rows, list) or not rows:
                raise ValueError("every frozen cohort must contain raw rows")
            out = []
            for row in rows:
                if not isinstance(row.get("text"), str) or not row["text"].strip():
                    raise ValueError("source text absent")
                batch = tokenizer(row["text"], truncation=True,
                                  max_length=CONTEXT_TOKENS, return_tensors="pt")
                ids, mask = batch["input_ids"], batch["attention_mask"]
                if (ids.ndim != 2 or mask.shape != ids.shape or ids.shape[0] != 1 or
                        not 0 < ids.shape[1] <= CONTEXT_TOKENS or
                        not torch.all((mask == 0) | (mask == 1)) or
                        int(mask.sum()) < 1):
                    raise ValueError("invalid masked input to original Encoder")
                result = encoder(input_ids=ids, attention_mask=mask)
                count += 1
                hidden = result.last_hidden_state
                if (hidden.ndim != 3 or hidden.shape[:2] != ids.shape or
                        hidden.shape[-1] < PROJECTED_WIDTH or
                        hidden.shape[-1] > 4096):
                    raise ValueError("invalid frozen original hidden state")
                if pooling == "cls":
                    ix = 0
                else:
                    active = torch.nonzero(mask[0], as_tuple=False).flatten()
                    ix = int(active[-1])
                v = hidden[0, ix].float().cpu()
                if not torch.isfinite(v).all() or float(torch.linalg.vector_norm(v)) <= 0:
                    raise ValueError("nonfinite or zero original embedding")
                out.append(F.normalize(v, p=2, dim=0))
            vectors[split] = torch.stack(out)
    if count != sum(len(rows) for rows in selected.values()):
        raise ValueError("incomplete original frozen Encoder forwards")
    return vectors, count


def project_untrained(features: dict) -> tuple[dict, str, int]:
    """No learned projector: one deterministic 256d adapter per input width."""
    import torch
    import torch.nn.functional as F

    if not isinstance(features, dict) or not features:
        raise ValueError("missing real original feature tensors")
    for vec in features.values():
        if not isinstance(vec, torch.Tensor) or vec.ndim != 2 or not len(vec) or (
                not torch.isfinite(vec).all()):
            raise ValueError("invalid original feature matrix")
    widths = {v.shape[1] for v in features.values()}
    if len(widths) != 1:
        raise ValueError("original feature widths disagree")
    width = next(iter(widths))
    if width < PROJECTED_WIDTH or width > 4096:
        raise ValueError("unapproved original feature width")
    generator = torch.Generator(device="cpu").manual_seed(PROJECTION_SEED)
    matrix = torch.randn(width, PROJECTED_WIDTH, generator=generator, dtype=torch.float32)
    matrix /= math.sqrt(PROJECTED_WIDTH)
    projected = {}
    for split, vec in features.items():
        z = F.normalize(vec.detach().cpu().float() @ matrix, dim=-1)
        if not torch.isfinite(z).all() or torch.any(torch.linalg.vector_norm(z, dim=1) <= 0):
            raise ValueError("projector collapsed a frozen representation")
        projected[split] = z
    return projected, _tensor_hash(matrix), width


def train_and_replay(features: dict, rows: dict, *, train_fn: Callable,
                     score_fn: Callable) -> tuple[dict, bytes]:
    """Fit and physically reload a fixed-size task Head; return unsigned evidence.

    train_fn is *exactly* P39 train_task_head (200 AdamW updates, seed 7,
    calibration cohort only). Safetensors are kept for independent-byte audit.
    """
    import torch
    import torch.nn.functional as F
    from safetensors.torch import load, save

    required = ("train", "calibration", "future_1", "future_2", "ood")
    if set(features) != set(required) or set(rows) != set(required):
        raise ValueError("all five exact cohorts required for frozen Head parity")
    for split in required:
        if not isinstance(rows[split], list) or len(rows[split]) != features[split].shape[0]:
            raise ValueError("cohort/feature row count drift")
        if any(type(r.get("label")) is not int or not 0 <= r["label"] < HEAD_CLASSES
               for r in rows[split]):
            raise ValueError("invalid source class label")
    projected, matrix_sha, orig_width = project_untrained(features)
    train_labels = torch.tensor([r["label"] for r in rows["train"]], dtype=torch.long)
    calibration_labels = torch.tensor([r["label"] for r in rows["calibration"]], dtype=torch.long)
    head, temp, training = train_fn(projected["train"], train_labels,
                                    projected["calibration"], calibration_labels)
    if (sum(p.numel() for p in head.parameters()) != HEAD_PARAMETERS or
            not math.isfinite(float(temp)) or float(temp) <= 0 or
            not isinstance(training, dict) or training.get("seed") != 7 or
            training.get("optimizer") != "AdamW" or training.get("steps") != 200 or
            training.get("learning_rate") != 0.05 or
            training.get("head_parameters") != HEAD_PARAMETERS):
        raise ValueError("shared task-Head budget or calibration changed")
    weights = {key: val.detach().cpu().contiguous() for key, val in head.state_dict().items()}
    if set(weights) != {"weight", "bias"} or weights["weight"].shape != (4, 256) or (
            weights["bias"].shape != (4,)):
        raise ValueError("trained task-Head tensor schema drift")
    artifact = save(weights)
    independent = torch.nn.Linear(PROJECTED_WIDTH, HEAD_CLASSES)
    independent.load_state_dict(load(artifact), strict=True)
    independent.requires_grad_(False).eval()
    scores = {}
    with torch.inference_mode():
        for split in required:
            a = head(projected[split])
            b = independent(projected[split])
            if not torch.equal(a, b):
                raise ValueError("reloaded original Head changes logits")
            probabilities = F.softmax(b / temp, dim=-1).tolist()
            observed = [{"source_id": r["source_id"],
                         "source_group_id": r["source_group_id"],
                         "label": r["label"],
                         "is_ood": split == "ood", "language": "en",
                         "probabilities": list(map(float, p))}
                        for r, p in zip(rows[split], probabilities, strict=True)]
            scores[split] = {"rows": observed, "metrics": score_fn(observed)}
    report = {"schema": SCHEMA, "projection": "frozen_gaussian_256d_v1",
              "projection_seed": PROJECTION_SEED,
              "projection_sha256": matrix_sha, "original_feature_width": orig_width,
              "output_width": PROJECTED_WIDTH, "context_tokens": CONTEXT_TOKENS,
              "trained_head_parameter_count": HEAD_PARAMETERS,
              "head_artifact_format": "safetensors-f32-linear",
              "head_artifact_sha256": hashlib.sha256(artifact).hexdigest(),
              "head_artifact_bytes": len(artifact),
              "head_reloaded_identical_logits": True,
              "head_training": training, "temperature": temp, "scores": scores,
              "evaluation_scope": "historical_2014_en_only_frozen_encoder_vs_task_head",
              "original_policy_unchanged": True,
              "independent_observer_attested": False,
              "target_host_qualified": False,
              "production_activation_allowed": False,
              "mode": "SHADOW_ONLY", "authority": "DENY_ALL"}
    return report, artifact
