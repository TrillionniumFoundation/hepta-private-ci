"""Physical mmBERT-small MLM checkpoint loader, never a random base-Encoder fallback.

A ModernBertForMaskedLM checkpoint ties its decoder weight to its token input
embeddings. Loading AutoModel alone can silently initialize the missing token
table at random. Require tied weight bytes to match a pinned local safetensors
checkpoint before any E1 model-derived predictions are emitted.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
import time


class Invalid(ValueError):
    pass


def require_verified_alias_only_loading_info(info):
    """Parse exact pinned MLM loading keys; no claim of physical weight validity.

    Both tied alias names may occur in a Transformers loading report, even
    though only one physical table is saved. This returns a PROVISIONAL allow
    list. Full physically tied source-table and all serialized weight byte
    comparisons below remain mandatory before exposing any Encoder outputs.
    """
    if type(info) is not dict:
        raise Invalid("full original pretrained MLM loading report required")
    missing = info.get("missing_keys")
    if (type(missing) not in (tuple, list) or len(missing) > 2 or
            any(type(name) is not str for name in missing) or
            len(set(missing)) != len(missing) or
            set(missing) - {"decoder.weight", "model.embeddings.tok_embeddings.weight"}):
        raise Invalid("unrecognized missing pretrained MLM tensor (not an allowed tied alias)")
    for field in ("unexpected_keys", "mismatched_keys", "error_msgs"):
        values = info.get(field, ())
        if type(values) not in (list, tuple) or values:
            raise Invalid("original pretrained MLM loading report contains unverified tensors")
    return tuple(sorted(missing))


def verify_tied_pretrained_table(torch, mlm, safetensors_path):
    """Checks a sample of actual checkpoint bytes, not merely two tied random tensors."""
    from safetensors import safe_open
    body = getattr(mlm, "model", None)
    embeddings = getattr(getattr(body, "embeddings", None), "tok_embeddings", None)
    decoder = getattr(mlm, "decoder", None)
    if body is None or embeddings is None or decoder is None:
        raise Invalid("checkpoint was not loaded as ModernBertForMaskedLM")
    from multimodal_exact_tied_alias_v11 import same_physical_view
    word = embeddings.weight
    decoded = decoder.weight
    if (not same_physical_view(word, decoded) or word.shape != decoded.shape or
            word.ndim != 2 or word.shape[1] != 384 or word.shape[0] < 8):
        raise Invalid("token embedding and pretrained MLM decoder are not tied at 384D")
    path = Path(safetensors_path)
    if path.is_symlink() or not path.is_file():
        raise Invalid("missing or symlinked pinned checkpoint")
    with safe_open(str(path), framework="pt", device="cpu") as file:
        names = set(file.keys())
        source = ("decoder.weight" if "decoder.weight" in names else
                  "model.embeddings.tok_embeddings.weight" if "model.embeddings.tok_embeddings.weight" in names else None)
        if source is None:
            raise Invalid("no pretrained tied-table tensor in source safetensors")
        view = file.get_slice(source)
        if tuple(view.get_shape()) != tuple(word.shape):
            raise Invalid("pretrained vocabulary size/width mismatch")
        whole = hashlib.sha256(b"hepta.e1.mmbert-complete-tied-table.v1")
        nonzero = False
        rows = int(word.shape[0])
        for start in range(0, rows, 8192):
            end = min(rows, start + 8192)
            raw = view[start:end]
            observed = word[start:end].detach().cpu()
            if (not bool(torch.equal(observed, raw)) or
                    not bool(torch.isfinite(observed).all())):
                raise Invalid("pretrained token embedding bytes differ from pinned checkpoint")
            nonzero = nonzero or bool(torch.any(observed != 0))
            whole.update(raw.contiguous().numpy().tobytes())
        if not nonzero:
            raise Invalid("all-zero pretrained table")
        full_digest = whole.hexdigest()
    return {"actual_local_full_tied_embedding_checkpoint_verified": True,
            "complete_table_sha256": full_digest,
            "publisher_signature_independently_verified": False,
            "authority": "DENY_ALL"}



def verify_complete_pretrained_state(torch, mlm, safetensors_path):
    """Byte-compare EVERY serialized tensor; allow one physically proven tied alias."""
    from safetensors import safe_open
    path = Path(safetensors_path)
    if path.is_symlink() or not path.is_file():
        raise Invalid("no pinned safe checkpoint for complete parameter verification")
    state = mlm.state_dict()
    if not state:
        raise Invalid("empty physical model parameter state")
    alias = {"decoder.weight", "model.embeddings.tok_embeddings.weight"}
    whole = hashlib.sha256(b"hepta.e1.mmbert-whole-pretrained-mlm-v1")
    with safe_open(str(path), framework="pt", device="cpu") as checkpoint:
        names = set(checkpoint.keys())
        unverified = set(state) - names
        if unverified not in (set(), {"decoder.weight"},
                             {"model.embeddings.tok_embeddings.weight"}):
            raise Invalid("model contains unverified or newly initialized saved weights")
        if not names or names - set(state):
            raise Invalid("checkpoint contains unmapped original weight tensors")
        for name in sorted(names):
            observed = state[name].detach().cpu().contiguous()
            saved = checkpoint.get_slice(name)
            shape = tuple(saved.get_shape())
            if shape != tuple(observed.shape) or observed.numel() == 0:
                raise Invalid("parameter shape differs from original tensor: "+name)
            whole.update(name.encode("utf8")+b"\0")
            if not shape:
                raw = checkpoint.get_tensor(name)
                if not bool(torch.equal(observed, raw)):
                    raise Invalid("parameter value differs from original scalar: "+name)
                whole.update(raw.contiguous().numpy().tobytes())
            else:
                for start in range(0, shape[0], 8192):
                    end = min(shape[0], start+8192)
                    raw = saved[start:end]
                    current = observed[start:end]
                    if not bool(torch.equal(current, raw)) or not bool(torch.isfinite(current).all()):
                        raise Invalid("loaded model parameter is not the pretrained source: "+name)
                    whole.update(raw.contiguous().numpy().tobytes())
    return {"all_serialized_pretrained_tensor_bytes_verified": True,
            "source_tensor_count": len(names),
            "whole_pretrained_state_sha256": whole.hexdigest(),
            "publisher_signature_independently_verified": False,
            "authority": "DENY_ALL"}


class FrozenMMBert:
    """Matches compact Stem's encode(row) API; pinned local checkpoint only."""
    def __init__(self, revision, *, device="cpu", max_tokens=512):
        import torch
        from huggingface_hub import hf_hub_download
        from transformers import AutoModelForMaskedLM, AutoTokenizer

        if type(revision) is not str or len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
            raise Invalid("immutable full model revision required")
        if type(max_tokens) is not int or not 16 <= max_tokens <= 512 or device != "cpu":
            raise Invalid("wrong CPU Stem task cap")
        begin = time.perf_counter_ns()
        repo = "jhu-clsp/mmBERT-small"
        opts = dict(revision=revision, local_files_only=True, trust_remote_code=False)
        self.tokenizer = AutoTokenizer.from_pretrained(repo, **opts)
        loaded = AutoModelForMaskedLM.from_pretrained(
            repo, use_safetensors=True, output_loading_info=True, **opts)
        if type(loaded) is not tuple or len(loaded) != 2 or type(loaded[1]) is not dict:
            raise Invalid("full pretrained MLM parameter load report required")
        mlm, info = loaded
        # The key report is not sufficient evidence that a tie was loaded.
        # Do not accept any inferred alias until BOTH original source-byte
        # verifiers below have completed without one unverified tensor.
        require_verified_alias_only_loading_info(info)
        mlm = mlm.to(device).eval()
        if (getattr(mlm.config, "hidden_size", None) != 384 or
                getattr(mlm.config, "tie_word_embeddings", None) is not True):
            raise Invalid("unexpected mmBERT architecture or absent tying policy")
        weights = hf_hub_download(repo_id=repo, filename="model.safetensors",
                                  revision=revision, local_files_only=True)
        self.pretrained_weight_receipt = verify_tied_pretrained_table(torch, mlm, weights)
        self.complete_weight_receipt = verify_complete_pretrained_state(torch, mlm, weights)
        self.model = mlm.model.eval()
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)
        self.torch = torch
        self.device = device
        self.max_tokens = max_tokens
        self.model_load_ms = (time.perf_counter_ns() - begin) / 1e6

    def encode(self, row, *, allow_truncation=False):
        from compact_stem_trial import pool_states, render_joint
        from q24_bridge import Q24, quantize_q24, shadow_feature_digest

        text = render_joint(row)
        raw = self.tokenizer(text, return_tensors="pt", truncation=False)
        original_tokens = int(raw["input_ids"].shape[1])
        if original_tokens > self.max_tokens:
            raise Invalid("matched experimental token cap exceeded; no truncation fallback")
        encoded = {key: tensor.to(self.device) for key, tensor in raw.items()}
        began = time.perf_counter_ns()
        with self.torch.inference_mode():
            outputs = self.model(**encoded)
            vector = pool_states(self.torch, outputs, encoded["attention_mask"], "masked_mean_l2")
        elapsed = (time.perf_counter_ns() - began) / 1e6
        q24 = quantize_q24(vector.detach().cpu().tolist())
        feature = self.torch.tensor([value/Q24 for value in q24], dtype=self.torch.float32)
        return feature, shadow_feature_digest([value/Q24 for value in q24]), {
            "original_tokens": original_tokens, "truncated": False,
            "encoder_forward_ms": elapsed}
