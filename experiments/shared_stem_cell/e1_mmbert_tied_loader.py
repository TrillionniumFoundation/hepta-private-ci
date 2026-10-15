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


def verify_tied_pretrained_table(torch, mlm, safetensors_path):
    """Checks a sample of actual checkpoint bytes, not merely two tied random tensors."""
    from safetensors import safe_open
    body = getattr(mlm, "model", None)
    embeddings = getattr(getattr(body, "embeddings", None), "tok_embeddings", None)
    decoder = getattr(mlm, "decoder", None)
    if body is None or embeddings is None or decoder is None:
        raise Invalid("checkpoint was not loaded as ModernBertForMaskedLM")
    word = embeddings.weight
    decoded = decoder.weight
    if (word.data_ptr() != decoded.data_ptr() or word.shape != decoded.shape or
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
        n = min(4, int(word.shape[0]))
        reference = view[0:n]
        final = view[int(word.shape[0]) - 1:int(word.shape[0])]
        if (not bool(torch.equal(word[:n].detach().cpu(), reference)) or
                not bool(torch.equal(word[-1:].detach().cpu(), final)) or
                not bool(torch.isfinite(word[:n]).all()) or
                not bool(torch.any(word[:n] != 0))):
            raise Invalid("tied embedding bytes do not match pinned pretrained source")
        sample_digest = hashlib.sha256(reference.contiguous().numpy().tobytes() +
                                        final.contiguous().numpy().tobytes()).hexdigest()
    return {"actual_local_tied_embedding_checkpoint_sample_checked": True,
            "sample_sha256": sample_digest,
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
        mlm = AutoModelForMaskedLM.from_pretrained(
            repo, use_safetensors=True, **opts).to(device).eval()
        if (getattr(mlm.config, "hidden_size", None) != 384 or
                getattr(mlm.config, "tie_word_embeddings", None) is not True):
            raise Invalid("unexpected mmBERT architecture or absent tying policy")
        weights = hf_hub_download(repo_id=repo, filename="model.safetensors",
                                  revision=revision, local_files_only=True)
        self.pretrained_weight_receipt = verify_tied_pretrained_table(torch, mlm, weights)
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
