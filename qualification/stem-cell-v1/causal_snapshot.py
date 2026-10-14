"""Opt-in exact local GPT2 causal snapshot loader; no download or pickle fallback.

A deliberately narrow architecture profile, not a choice of the optimal Hepta
backbone. Exact tensor correspondence establishes materialization, not provenance
or suitability of pretraining for the registered JSON/revision prompt protocol.
"""
from pathlib import Path

from causal_generation import LocalCausalProposer, freeze_generation, tokenizer_digest
from hf_encoder_kernel import snapshot_digest, validate_encoder_loading_info, verify_loaded_safetensors
from matrix_bank import state_digest
from matrix_materials import strict_json
from paired_execution import _sha

TRANSFORMERS_VERSION = "4.57.1"
ALIASES = {"lm_head.weight": "transformer.wte.weight"}


def inspect_snapshot(root, expected_sha256):
    _sha(expected_sha256, "pinned snapshot")
    if snapshot_digest(root) != expected_sha256:
        raise ValueError("causal snapshot differs from admitted bytes")
    cfg = strict_json(Path(root) / "config.json", max_bytes=1 << 20)
    if (not isinstance(cfg, dict) or cfg.get("model_type") != "gpt2" or cfg.get("architectures") != ["GPT2LMHeadModel"]
            or cfg.get("tie_word_embeddings", True) is not True
            or cfg.get("add_cross_attention", False) is not False or cfg.get("auto_map")):
        raise ValueError("reviewed tied stock GPT2 architecture required")
    for key, limit in (("n_embd", 2048), ("n_layer", 48), ("n_head", 64),
                       ("vocab_size", 65536), ("n_positions", 8192)):
        if type(cfg.get(key)) is not int or not 1 <= cfg[key] <= limit:
            raise ValueError("unbounded causal geometry: " + key)
    d, n, v = cfg["n_embd"], cfg["n_layer"], cfg["vocab_size"]
    inner = 4*d if cfg.get("n_inner") is None else cfg["n_inner"]
    if (type(inner) is not int or not 1 <= inner <= 8192 or d % cfg["n_head"]
            or d*v + cfg["n_positions"]*d + n*(4*d*d + 2*d*inner + 32*d) > 600_000_000):
        raise ValueError("causal parameter envelope exceeded")
    files = list(Path(root).rglob("*.safetensors"))
    if not 1 <= len(files) <= 64 or sum(p.stat().st_size for p in files) > 2_500_000_000:
        raise ValueError("bounded local safetensors required; no unsafe fallback")
    return cfg


def load_local_causal(root, *, expected_snapshot_sha256, material_approval_sha256,
                      context_tokens=1024, max_new_tokens=64, max_output_bytes=16384, cache_policy=None):
    import torch
    _sha(material_approval_sha256, "external material approval reference")
    cfg = inspect_snapshot(root, expected_snapshot_sha256)
    if type(context_tokens) is not int or not 1 <= context_tokens <= cfg["n_positions"]:
        raise ValueError("generation context exceeds the actual model position budget")
    if cache_policy is not None:
        from causal_cache import validate_cache_policy
        cache_policy = validate_cache_policy(cache_policy)
        if (cache_policy["cache_format"] != "hf_dynamic_gpt2_4_57_1"
                or (cache_policy["layers"], cache_policy["heads"], cache_policy["head_dim"]) !=
                   (cfg["n_layer"], cfg["n_head"], cfg["n_embd"] // cfg["n_head"])):
            raise ValueError("cache policy differs from the pinned GPT2 geometry")
    # Validate requested bounds before constructing any large model.
    freeze_generation(model_sha256="0"*64, tokenizer_sha256="0"*64,
                      vocab_size=cfg["vocab_size"], eos_token_id=0, context_tokens=context_tokens,
                      max_new_tokens=max_new_tokens, max_output_bytes=max_output_bytes, cache_policy=cache_policy)
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer
    if transformers.__version__ != TRANSFORMERS_VERSION:
        raise ValueError("reviewed causal Transformers version required")
    tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True, trust_remote_code=False, use_fast=True)
    if not getattr(tokenizer, "is_fast", False):
        raise ValueError("serialized fast tokenizer required")
    loaded = AutoModelForCausalLM.from_pretrained(str(root), local_files_only=True, trust_remote_code=False,
              use_safetensors=True, output_loading_info=True, attn_implementation="eager", torch_dtype=torch.float32)
    if not isinstance(loaded, tuple) or len(loaded) != 2:
        raise ValueError("full causal loading report required")
    model, info = loaded
    model = model.to("cpu").eval().requires_grad_(False)
    if model.config.model_type != "gpt2" or model.config._attn_implementation != "eager":
        raise ValueError("loaded architecture differs from the reviewed profile")
    material = verify_loaded_safetensors(torch, model, root, tied_aliases=ALIASES)
    if not isinstance(info, dict) or not isinstance(info.get("missing_keys"), (list, tuple)):
        raise ValueError("missing complete causal loading report")
    adjusted = dict(info)
    adjusted["missing_keys"] = [k for k in info["missing_keys"] if k not in material["omitted_tied_keys"]]
    loading = validate_encoder_loading_info(adjusted)
    if snapshot_digest(root) != expected_snapshot_sha256:
        raise ValueError("snapshot changed while loading causal model")
    policy = freeze_generation(model_sha256=state_digest(model), tokenizer_sha256=tokenizer_digest(tokenizer),
                               vocab_size=cfg["vocab_size"], eos_token_id=tokenizer.eos_token_id,
                               context_tokens=context_tokens, max_new_tokens=max_new_tokens,
                               max_output_bytes=max_output_bytes, cache_policy=cache_policy)
    proposer = LocalCausalProposer(model, tokenizer, policy)
    return proposer, dict(snapshot_sha256=expected_snapshot_sha256,
                         material_approval_sha256=material_approval_sha256,
                         exact_loading=loading, materialization=material,
                         profile_id=policy["profile_id"], pretrained_provenance_verified=False,
                         production_authorized=False)
