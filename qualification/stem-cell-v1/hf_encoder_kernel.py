"""Shared local HF encoding/head primitives extracted without algorithm changes.

The joint runner and the bound matrix runner use this same implementation.
Importing this leaf does not import study/decision_421m or load model weights.
"""
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path


def snapshot_digest(folder):
    """Same name/length/content hash as the original model_runner snapshot."""
    root = Path(folder).resolve()
    if not root.is_dir():
        raise ValueError("model snapshot must be a local directory")
    h = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise ValueError("empty model snapshot")
    for item in files:
        if not item.resolve().is_relative_to(root):
            raise ValueError("model snapshot contains escaping symlink")
        name = item.relative_to(root).as_posix().encode("utf-8")
        h.update(len(name).to_bytes(8, "big"))
        h.update(name)
        h.update(item.stat().st_size.to_bytes(8, "big"))
        with item.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                h.update(chunk)
    return h.hexdigest()


def render_joint(row):
    if not isinstance(row.get("state"), str) or not isinstance(row.get("question"), str):
        raise ValueError("typed model state/question required")
    if not row["state"] or not row["question"]:
        raise ValueError("empty state or question")
    if not isinstance(row.get("options"), list) or not 2 <= len(row["options"]) <= 16:
        raise ValueError("ordered legal options required")
    if any(not isinstance(opt, str) or not opt for opt in row["options"]):
        raise ValueError("empty legal option")
    # The label is intentionally NEVER interpolated into the model source.
    return "\n".join(["[STATE]", row["state"], "[QUESTION]", row["question"],
                      "[ALL ORDERED OPTIONS]", *[
                          f"Option {i}: {value}" for i, value in enumerate(row["options"])]]).strip()


def head_width(hidden, classes, ceiling, max_width=256):
    if (any(type(v) is not int for v in (hidden, classes, ceiling)) or
            hidden < 1 or not 2 <= classes <= 16 or ceiling <= classes):
        raise ValueError("invalid dimensions or parameter budget ceiling")
    width = min(max_width, (ceiling - classes) // (hidden + classes + 1))
    if width < 1:
        raise ValueError("head cannot fit the registered parameter budget")
    count = hidden * width + width + width * classes + classes
    if count > ceiling:
        raise ValueError("miscomputed physical Head parameter budget")
    return width, count


def build_head(torch, hidden, classes, ceiling):
    from torch import nn
    width, expected = head_width(hidden, classes, ceiling)
    head = nn.Sequential(nn.Linear(hidden, width), nn.GELU(),
                         nn.Linear(width, classes))
    actual = sum(p.numel() for p in head.parameters())
    if actual != expected:
        raise ValueError("unaccounted trainable Head tensor")
    return head, actual


def head_sha256(head):
    import torch
    digest = hashlib.sha256(b"hepta.typed-hf-joint-head.v1\x00")
    for name, tensor in sorted(head.state_dict().items()):
        values = tensor.detach().to(device="cpu", dtype=torch.float32).contiguous()
        pieces = (name.encode("utf-8"),
                  json.dumps(list(values.shape), separators=(",", ":")).encode("utf-8"),
                  values.numpy().tobytes())
        for part in pieces:
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


def train_head(torch, head, features, labels, *, batch_size, steps, seed):
    if any(type(v) is not int or v < 1 for v in (batch_size, steps)):
        raise ValueError("training steps/batch must be positive")
    if features.ndim != 2 or labels.ndim != 1 or features.shape[0] != labels.shape[0]:
        raise ValueError("training feature/label shape mismatch")
    rng = torch.Generator(device="cpu").manual_seed(seed)
    opt = torch.optim.AdamW(head.parameters(), lr=0.001, weight_decay=0.01)
    head.train()
    for _ in range(steps):
        chosen = torch.randint(len(labels), (min(batch_size, len(labels)),),
                               generator=rng).to(features.device)
        logits = head(features[chosen])
        loss = torch.nn.functional.cross_entropy(logits, labels[chosen])
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(head.parameters(), 1.0)
        opt.step()
        if not all(torch.isfinite(p).all().item() for p in head.parameters()):
            raise ValueError("invalid trained weights")
    head.eval()
    return head_sha256(head)


def validate_encoder_loading_info(info):
    """Refuse missing/randomly initialized or silently ignored pretrained tensors.

    A safetensors file and checkpoint SHA alone do not guarantee that AutoModel
    successfully loaded every intended pretrained parameter. Model-specific
    intentional drops must be resolved by a reviewed base-model conversion
    before this qualification lane, not suppressed in this evaluator.
    """
    required = ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")
    if not isinstance(info, Mapping) or any(key not in info for key in required):
        raise ValueError("pretrained Encoder missing complete loading report")
    problems = {}
    for key in required:
        values = info[key]
        if not isinstance(values, (list, tuple)):
            raise ValueError("pretrained Encoder loading report has invalid field: " + key)
        if values:
            problems[key] = len(values)
    if problems:
        raise ValueError(
            "pretrained Encoder partially initialized or ignored weights: "
            + json.dumps(problems, sort_keys=True))
    return {
        "schema": "hepta.local-hf-encoder-weight-load.v1",
        "complete": True,
        "missing_keys": 0,
        "unexpected_keys": 0,
        "mismatched_keys": 0,
        "error_msgs": 0,
    }


def verify_loaded_safetensors(torch, model, root, *, tied_aliases=None):
    """Exact, read-only tensor comparison against every pinned safetensors key.

    Transformers loading_info is advisory for some version/architecture
    combinations; a clean list by itself is NOT sufficient. Require that
    the locally admitted, base-only safetensors inventory equals the actual
    model.state_dict() inventory and every tensor value after the requested
    model dtype conversion matches. The default V1 rejects missing keys.
    An explicit versioned profile may supply direct aliases; each omission
    requires a serialized target and the exact same loaded physical view.
    """
    from safetensors import safe_open

    files = sorted(Path(root).rglob("*.safetensors"))
    if not files or len(files) > 64:
        raise ValueError("empty or excessive safetensors shard inventory")
    if sum(p.stat().st_size for p in files) > 2_500_000_000:
        raise ValueError("pretrained safetensors exceed local research weight envelope")
    stored = model.state_dict()
    if not isinstance(stored, Mapping) or not stored or len(stored) > 250_000:
        raise ValueError("unsupported pretrained model tensor inventory")
    aliases = {} if tied_aliases is None else dict(tied_aliases)
    for alias, target in aliases.items():
        if alias == target or alias not in stored or target not in stored or target in aliases:
            raise ValueError("invalid direct tied-weight alias")
        a, b = stored[alias], stored[target]
        # Equal values alone do NOT prove tying: the loaded tensors must share
        # exactly the same physical view, not copies or overlapping slices.
        if (a.device.type == "meta" or a.numel() == 0 or
                (a.device, a.dtype, a.shape, a.stride(), a.storage_offset(), a.data_ptr()) !=
                (b.device, b.dtype, b.shape, b.stride(), b.storage_offset(), b.data_ptr())):
            raise ValueError("declared tied weights are not the same physical view")
    seen = set()
    elements = 0
    for file in files:
        with safe_open(str(file), framework="pt", device="cpu") as handle:
            for key in handle.keys():
                if key in seen or key not in stored:
                    raise ValueError("duplicate or unexpected safetensors parameter key")
                observed = stored[key]
                expected = handle.get_tensor(key)
                if (not hasattr(observed, "shape") or
                        tuple(observed.shape) != tuple(expected.shape) or
                        observed.device.type == "meta"):
                    raise ValueError("safetensors tensor shape or materialization mismatch")
                # Loading at bf16/fp16 legitimately casts source values.
                # Compare at the exact dtype actually held by the model.
                source = expected.to(dtype=observed.dtype, device="cpu")
                actual = observed.detach().to(device="cpu")
                if not torch.equal(source, actual):
                    raise ValueError("loaded pretrained tensor differs from pinned safetensors")
                elements += int(expected.numel())
                seen.add(key)
    omitted = set(stored) - seen
    if any(alias not in aliases or aliases[alias] not in seen for alias in omitted):
        raise ValueError("incomplete safetensors inventory for loaded Encoder")
    result = {
        "schema": "hepta.local-hf-exact-tensor-materialization.v1",
        "complete": True,
        "all_state_dict_tensors_compared": True,
        "tensor_count": len(seen),
        "tensor_elements": elements,
        "safetensors_shards": len(files),
        "production_authorization": False,
    }
    if tied_aliases is not None:
        result.update(schema="hepta.local-hf-exact-tied-materialization.v2",
                      omitted_tied_keys=sorted(omitted),
                      physical_aliases=aliases,
                      all_state_dict_tensors_compared=not omitted,
                      all_state_dict_tensors_accounted=True)
    return result


def vectorize_case(torch, model, tokenizer, row, device, *, max_tokens):
    text = render_joint(row)
    tokens = tokenizer(text, return_tensors="pt", truncation=False)
    if not isinstance(tokens, Mapping) or "input_ids" not in tokens or "attention_mask" not in tokens:
        raise ValueError("tokenizer did not produce input IDs and padding mask")
    mask = tokens["attention_mask"]
    if mask.ndim != 2 or mask.shape[0] != 1:
        raise ValueError("unexpected token mask shape")
    seq_len = int(mask.sum().item())
    if not 1 <= seq_len <= max_tokens:
        raise ValueError("input exceeds shared token budget, no silent truncation")
    args = {name: tensor.to(device) for name, tensor in tokens.items()}
    with torch.inference_mode():
        states = model(**args).last_hidden_state
        weights = args["attention_mask"].unsqueeze(-1).to(states.dtype)
        if states.ndim != 3 or states.shape[0] != 1 or states.shape[1] != weights.shape[1]:
            raise ValueError("unsupported encoder hidden-state layout")
        pooled = (states * weights).sum(1) / weights.sum(1).clamp_min(1)
        feature = pooled[0].to(torch.float32).detach().cpu()
    if not torch.isfinite(feature).all().item():
        raise ValueError("nonfinite encoder feature")
    return feature, seq_len


def vectorize_scope_batch(torch, model, tokenizer, rows, device, *, max_tokens):
    """One genuine HF forward for 2..32 same-Scope joint decision cases.

    No model weights are fetched, no source labels reach the Encoder, and
    unrelated Scopes are never coalesced by the shadow microbatch scheduler.
    """
    if not 2 <= len(rows) <= 32:
        raise ValueError("physical Encoder microbatch requires 2..32 inputs")
    if len({row["scope"] for row in rows}) != 1:
        raise ValueError("cross-Scope Encoder batch is forbidden")
    encoded, lengths = [], []
    for row in rows:
        tokens = tokenizer(render_joint(row), return_tensors="pt",
                           truncation=False)
        if (not isinstance(tokens, Mapping) or
                "input_ids" not in tokens or "attention_mask" not in tokens):
            raise ValueError("incomplete joint tokenizer output")
        mask = tokens["attention_mask"]
        if mask.ndim != 2 or mask.shape[0] != 1:
            raise ValueError("invalid per-case Encoder mask")
        count = int(mask.sum().item())
        if not 1 <= count <= max_tokens:
            raise ValueError("Encoder batch would silently truncate input")
        sample = {}
        for name, tensor in tokens.items():
            if (tensor.ndim != 2 or tensor.shape[0] != 1 or
                    tensor.shape[1] != mask.shape[1]):
                raise ValueError("tokenizer emitted incompatible per-case tensor")
            sample[name] = tensor[0].tolist()
        encoded.append(sample)
        lengths.append(count)
    padded = tokenizer.pad(encoded, padding=True, return_tensors="pt")
    if (not isinstance(padded, Mapping) or
            "attention_mask" not in padded or
            padded["attention_mask"].ndim != 2 or
            padded["attention_mask"].shape[0] != len(rows)):
        raise ValueError("incompatible physical Encoder padding layout")
    masks = padded["attention_mask"]
    if masks.shape[1] * len(rows) > max_tokens * 32:
        raise ValueError("physical Encoder batch exceeds joint token memory envelope")
    if [int(mask.sum().item()) for mask in masks] != lengths:
        raise ValueError("Encoder padding changed original token identities")
    args = {name: value.to(device) for name, value in padded.items()}
    with torch.inference_mode():
        states = model(**args).last_hidden_state
        weights = args["attention_mask"].unsqueeze(-1).to(states.dtype)
        if (states.ndim != 3 or states.shape[0] != len(rows) or
                states.shape[1] != weights.shape[1]):
            raise ValueError("physical Encoder batch returned invalid hidden geometry")
        pooled = (states * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1)
        features = pooled.to(torch.float32).detach().cpu()
    if not torch.isfinite(features).all().item():
        raise ValueError("nonfinite physical Encoder batch output")
    return [(features[j], lengths[j]) for j in range(len(rows))]
