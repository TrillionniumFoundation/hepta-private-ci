"""Re-run the original 3,520 typed MiniLM Head forwards from immutable bytes.

Unlike receipt-only review, this independently computes all five original
arm probabilities from six physical FP32 safetensors, source-row-matched
features, and the original prediction seal.  NOT an HF Encoder or Reader run.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

import torch
from torch.nn import functional as F
from safetensors import safe_open

from amcn_core import digest, require, shadow_disposition
from amcn_typed_physical_audit import audit_local_materials

PROFILE = "hepta.amcn.original-typed-3520-head-forward-replay.shadow.v1"
TYPES = ("episodic", "semantic")
ARMS = ("frozen", "single_shared", "typed_equal_budget",
        "untyped_equal_budget", "typed_swapped_negative")
HEAD_SHAPES = {"base.bias": (2,), "base.weight": (2, 384),
               "down.bias": (8,), "down.weight": (8, 384),
               "gate.bias": (2,), "gate.weight": (2, 384),
               "up.weight": (2, 8)}


def _tensor_hash(t):
    t = t.detach().cpu().contiguous()
    header = (json.dumps([str(t.dtype), list(t.shape)], sort_keys=True,
                         ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False) + "\n").encode()
    return sha256(header + t.reshape(-1).view(torch.uint8).numpy().tobytes()).hexdigest()


def _head(weights, x):
    base = F.linear(x, weights["base.weight"], weights["base.bias"])
    hidden = torch.tanh(F.linear(x, weights["down.weight"], weights["down.bias"]))
    up = F.linear(hidden, weights["up.weight"])
    gate = torch.sigmoid(F.linear(x, weights["gate.weight"], weights["gate.bias"]))
    return (base + up * gate).softmax(-1)[0, 1].item()


def replay_original_head_forwards(archive, corpus, encoder_weights, vocab,
                                   features, feature_manifest, seal, bank,
                                   question_score, public, *, tolerance=2e-6):
    """Replay original sealed 704x5 Head probabilities; fail closed on mismatch.

    The original public/source and model must be staged by a separate owner;
    absence of any physical material is a hard refusal, never fake fallback.
    """
    require(type(tolerance) is float and 0 < tolerance <= 2e-6,
            "tolerance must not be widened")
    original = audit_local_materials(archive, corpus, encoder_weights, vocab,
                                     features, feature_manifest, seal, bank, question_score)
    require(original["production_accepted"] is False and
            original["physical_bytes_checked"] is True,
            "original physical material prerequisite incomplete")
    public = Path(public)
    require(public.is_file() and not public.is_symlink() and
            0 < public.stat().st_size < 8 * 1024 * 1024, "unsafe original public source")
    raw_public = public.read_bytes()
    p = json.loads(raw_public)
    f = json.loads(Path(feature_manifest).read_bytes())
    s = json.loads(Path(seal).read_bytes())
    b = json.loads((Path(bank) / "manifest.json").read_bytes())
    require(sha256(raw_public).hexdigest() == s.get("original_public_sha256")
            and p.get("source_first_sha256") == f.get("original_source_first_sha256")
            and p.get("corpus_sha256") == f.get("source_original_locomo_sha256"),
            "original public source not bound to archive/feature/seal")
    rows = p.get("rows")
    require(isinstance(rows, list) and len(rows) == 1472
            and all(isinstance(r, dict) and all(k in r for k in
                    ("row_id", "input_sha256", "source_root", "family", "split", "memory_type"))
                    for r in rows), "original feature row roster incomplete")
    require(digest([r["row_id"] for r in rows]) == f["row_ids_sha256"]
            and len({r["row_id"] for r in rows}) == len(rows),
            "original source row order/uniqueness drift")
    with safe_open(str(features), framework="pt", device="cpu") as reader:
        require(reader.keys() == ["features"], "unexpected feature tensor")
        x = reader.get_tensor("features")
    require(x.dtype == torch.float32 and tuple(x.shape) == (1472, 384)
            and bool(torch.isfinite(x).all()), "unsafe feature material")
    feature_id = digest({
        "encoder": f["model_safetensors_sha256"],
        "scope": "amcn.original.locomo.shadow", "generation": "historical",
        "profile": "mechanics_fixture", "execution_receipt": None,
        "rows": [(r["row_id"], r["input_sha256"], r["family"],
                  r["source_root"], r["split"]) for r in rows],
        "tensors": _tensor_hash(x)})
    require(feature_id == b.get("feature_sha256"),
            "trained Head references different source-feature identity")
    typed = digest({"profile": "hepta.amcn.typed-equal-budget.shadow.v1",
                    "features": feature_id,
                    "types": [(r["row_id"], r["memory_type"]) for r in rows]})
    require(typed == b.get("type_inventory_sha256"),
            "trained Head references different functional type inventory")
    weights = {}
    for name in sorted(b["entries"]):
        entry = b["entries"][name]
        path = Path(bank) / entry["file"]
        with safe_open(str(path), framework="pt", device="cpu") as reader:
            require(set(reader.keys()) == set(HEAD_SHAPES),
                    "unregistered Head parameter names")
            tensors = {key: reader.get_tensor(key) for key in HEAD_SHAPES}
        require(all(v.dtype == torch.float32 and
                    tuple(v.shape) == HEAD_SHAPES[k] and bool(torch.isfinite(v).all())
                    for k, v in tensors.items()), "unsafe Head geometry")
        params = entry["parameters"]
        require(params["parameters"] == 4636 and params["parameter_bytes"] == 18544,
                "Head trainable parameter budget drift")
        # The original training parameter digest uses a newline unlike source digests.
        original_param_sha = sha256((json.dumps({
            k: _tensor_hash(v) for k, v in sorted(tensors.items())},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
            allow_nan=False) + "\n").encode()).hexdigest()
        require(original_param_sha == params["sha256"],
                "original Head tensor SHA is not reproducible")
        weights[name] = tensors

    original_predictions = s.get("predictions")
    require(isinstance(original_predictions, list) and len(original_predictions) == 704,
            "original sealed prediction census incomplete")
    by_id = {r["row_id"]: (i, r) for i, r in enumerate(rows)}
    require({v["row_id"] for v in original_predictions} ==
            {r["row_id"] for r in rows if r["split"] != "train"},
            "non-TRAIN prediction identity mismatch")
    maximum_error, evaluated = 0.0, 0
    with torch.inference_mode():
        for item in original_predictions:
            idx, row = by_id[item["row_id"]]
            require(all(item[k] == row[k] for k in
                        ("family", "split", "input_sha256", "memory_type")),
                    "source-to-prediction content identity drift")
            require(row["memory_type"] in TYPES and
                    set(item["probabilities"]) == set(ARMS),
                    "unknown type or incomplete original arm")
            other = TYPES[1 - TYPES.index(row["memory_type"])]
            routing = {
                "frozen": "frozen", "single_shared": "single_shared",
                "typed_equal_budget": "typed_equal_budget__" + row["memory_type"],
                "untyped_equal_budget": "untyped_equal_budget__" + row["memory_type"],
                "typed_swapped_negative": "typed_equal_budget__" + other}
            for arm, head in routing.items():
                actual = _head(weights[head], x[idx:idx + 1])
                original_p = item["probabilities"][arm]
                require(type(original_p) in (float, int) and isfinite(original_p)
                        and 0 <= original_p <= 1 and isfinite(actual),
                        "invalid sealed or computed probability")
                delta = abs(actual - original_p)
                require(delta <= tolerance,
                        "actual safetensors Head forward disagrees with sealed probability")
                maximum_error = max(maximum_error, delta)
                evaluated += 1
    require(evaluated == 704 * 5, "partial original physical replay")
    return shadow_disposition(
        profile=PROFILE, original_prediction_sha256=s["original_prediction_digest"],
        original_source_sha256=f["source_original_locomo_sha256"],
        original_pretrained_weight_sha256=f["model_safetensors_sha256"],
        actual_forward_calls=evaluated, original_predictions_verified=704,
        physically_reloaded_head_count=len(weights),
        max_abs_probability_error=maximum_error, original_model_encoder_replayed=False,
        original_reader_executions=0, authenticated_source_issuers=False,
        hf_model_tokenizer_operator_parity_qualified=False,
        independent_future_calendar_windows=0,
        strong_hybrid_rag_superiority=False, publication_authorized=False)
