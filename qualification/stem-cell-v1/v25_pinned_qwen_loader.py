"""Source-only Qwen3 loader compatibility port for pinned Transformers 4.53.3.

Does not acquire checkpoints, authenticate artifact bytes or grant a model policy.
The caller MUST validate its full material manifest before and after invocation.
"""
from __future__ import annotations

from os import PathLike


def load_local_qwen_fp32(model_dir, *, model_loader, torch_dtype):
    """Load only regular local safetensors using the audited legacy API keyword.

    Transformers 4.53.3 uses ``torch_dtype`` here. Passing ``dtype`` is forwarded
    into Qwen3ForCausalLM.__init__ and crashes before the first model forward.
    Injection of ``model_loader`` permits a no-download test of actual kwargs.
    """
    if not isinstance(model_dir, (str, PathLike)) or not str(model_dir).strip():
        raise ValueError('missing immutable local Qwen3 directory')
    if torch_dtype is None:
        raise ValueError('model dtype must be declared explicitly')
    return model_loader.from_pretrained(
        str(model_dir),
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
        torch_dtype=torch_dtype,
    ).eval()


def real_tiny_qwen_loader_contract():
    """Exercise actual Qwen3 model construction from synthetic *random* safetensors.

    This is only a dependency/runtime compatibility check; no published Qwen3
    pretrained weights, text QA, original LoCoMo labels or generation claims.
    """
    from hashlib import sha256
    from pathlib import Path
    from tempfile import TemporaryDirectory

    import torch
    from transformers import AutoModelForCausalLM, Qwen3Config, Qwen3ForCausalLM

    torch.set_num_threads(1)
    cfg = Qwen3Config(
        vocab_size=128,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=1,
        num_attention_heads=4,
        num_key_value_heads=2,
        head_dim=8,
        max_position_embeddings=64,
        tie_word_embeddings=False,
    )
    with TemporaryDirectory(prefix='qwen3-compat-synthetic-') as folder:
        torch.manual_seed(0)
        tiny = Qwen3ForCausalLM(cfg).eval()
        tiny.save_pretrained(folder, safe_serialization=True)
        weights = Path(folder) / 'model.safetensors'
        if not weights.is_file():
            raise RuntimeError('synthetic Qwen3 local safetensors not materialized')
        before = sha256(weights.read_bytes()).hexdigest()
        reread = load_local_qwen_fp32(
            folder, model_loader=AutoModelForCausalLM, torch_dtype=torch.float32
        )
        if sha256(weights.read_bytes()).hexdigest() != before:
            raise RuntimeError('synthetic model bytes changed during loading')
        with torch.inference_mode():
            out = reread(input_ids=torch.tensor([[1, 2, 3]], dtype=torch.long))
        if (tuple(out.logits.shape) != (1, 3, 128)
                or out.logits.dtype != torch.float32
                or not bool(torch.isfinite(out.logits).all())):
            raise RuntimeError('synthetic Qwen3 forward returned invalid logits')
        return {
            'status': 'SYNTHETIC_QWEN3_CONSTRUCTOR_COMPATIBLE_NOT_PRETRAINED',
            'model_type': 'qwen3',
            'output_shape': list(out.logits.shape),
            'source_real_pretrained_forwards': 0,
            'real_128_reference_requests': 0,
            'production_authorized': False,
        }


if __name__ == '__main__':
    import json
    print(json.dumps(real_tiny_qwen_loader_contract(), sort_keys=True))
