"""Opt-in complete ModernBERT MLM checkpoint -> shared feature Encoder.

Keep and verify the original MLM head; do not silently strip or rename tensors.
Only the documented decoder/embedding physical alias may be absent from disk.
No pickle loading, weight conversion, network acquisition or random fallback.
"""
from pathlib import Path

from hf_encoder_kernel import verify_loaded_safetensors, validate_encoder_loading_info
from matrix_materials import strict_json

ENCODER_PROFILE = "modernbert_mlm_full_eager_v1"
TIED_ALIASES = {"decoder.weight": "model.embeddings.tok_embeddings.weight"}
TRANSFORMERS_VERSION = "4.57.1"


def checked_config(root):
    config = strict_json(Path(root) / "config.json", max_bytes=1 << 20)
    if (not isinstance(config, dict) or config.get("model_type") != "modernbert"
            or config.get("architectures") != ["ModernBertForMaskedLM"]
            or config.get("tie_word_embeddings", True) is not True):
        raise ValueError("registered tied ModernBERT MLM architecture required")
    limits = {"hidden_size": 2048, "intermediate_size": 8192,
              "num_hidden_layers": 64, "vocab_size": 300000,
              "num_attention_heads": 64, "max_position_embeddings": 131072}
    for key, limit in limits.items():
        value = config.get(key)
        if type(value) is not int or not 1 <= value <= limit:
            raise ValueError("unbounded checkpoint geometry: " + key)
    d, m, n, v = (config[k] for k in ("hidden_size", "intermediate_size", "num_hidden_layers", "vocab_size"))
    if d % config["num_attention_heads"] or d * v + n * (4*d*d + 3*d*m) > 600_000_000:
        raise ValueError("checkpoint geometry exceeds bounded CPU loading profile")
    files = list(Path(root).rglob("*.safetensors"))
    if not 1 <= len(files) <= 64 or sum(f.stat().st_size for f in files) > 2_500_000_000:
        raise ValueError("bounded local safetensors material required; no .bin fallback")
    return config


def verify_full_mlm(torch, model, root, loading_info):
    """Verify tensors first; only then reconcile a loader's omitted tied alias."""
    material = verify_loaded_safetensors(torch, model, root, tied_aliases=TIED_ALIASES)
    if not isinstance(loading_info, dict):
        raise ValueError("complete loading report required")
    adjusted = dict(loading_info)
    missing = adjusted.get("missing_keys")
    if not isinstance(missing, (list, tuple)):
        raise ValueError("complete missing-key report required")
    proved = set(material["omitted_tied_keys"])
    adjusted["missing_keys"] = [key for key in missing if key not in proved]
    loading = validate_encoder_loading_info(adjusted)
    loading.update(schema="hepta.local-hf-complete-mlm-load.v2",
                   reported_missing_keys=list(missing), reconciled_physical_aliases=sorted(proved))
    return loading, material


def load_complete_mlm(root):
    import torch
    import transformers
    from transformers import AutoConfig, AutoModelForMaskedLM
    if transformers.__version__ != TRANSFORMERS_VERSION:
        raise ValueError("complete MLM profile requires the reviewed Transformers version")
    checked_config(root)
    config = AutoConfig.from_pretrained(str(root), local_files_only=True, trust_remote_code=False)
    config.reference_compile = False
    config._attn_implementation = "eager"
    loaded = AutoModelForMaskedLM.from_pretrained(
        str(root), config=config, local_files_only=True, trust_remote_code=False,
        use_safetensors=True, output_loading_info=True,
        attn_implementation="eager", torch_dtype=torch.float32)
    if not isinstance(loaded, tuple) or len(loaded) != 2:
        raise ValueError("complete MLM loading report missing")
    complete, info = loaded
    complete = complete.to("cpu").eval().requires_grad_(False)
    if (complete.config.model_type != "modernbert"
            or complete.config.reference_compile is not False
            or complete.config._attn_implementation != "eager"):
        raise ValueError("loaded execution path differs from bound eager profile")
    loading, material = verify_full_mlm(torch, complete, root, info)
    feature_model = complete.model
    receipt = dict(profile=ENCODER_PROFILE, checkpoint_architecture="ModernBertForMaskedLM",
                   feature_architecture="ModernBertModel", reference_compile=False,
                   attention_implementation="eager", retained_mlm_head=True,
                   mlm_head_executed_for_features=False,
                   checkpoint_parameters=sum(p.numel() for p in complete.parameters()),
                   feature_parameters=sum(p.numel() for p in feature_model.parameters()),
                   loading=loading, materialization=material)
    return complete, feature_model, receipt
