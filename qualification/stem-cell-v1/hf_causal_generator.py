"""One shared, pinned Llama causal LM as the existing System2 propose callback.

Local CPU FP32/eager only. Greedy autoregression recomputes the bounded prefix;
there is deliberately no persistent KV/cache, sampling, tools or answer oracle.
This is a correctness reference, not an efficient serving implementation. Loading
is separate from calls; use one instance across cells and retain their own inputs.
"""
from __future__ import annotations

import copy
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from hf_encoder_kernel import (snapshot_digest, validate_encoder_loading_info,
                               verify_loaded_safetensors)
from matrix_materials import strict_json
from next_round_matrix import _digest
from paired_execution import _sha
from system2_execution import PublicTask, _text

PROFILE = 'hepta.local-llama-causal-greedy.v1'
TRANSFORMERS_VERSION = '4.57.1'
ALIASES = {'lm_head.weight': 'model.embed_tokens.weight'}


@dataclass(frozen=True)
class DecodeLimits:
    prompt_tokens: int = 256
    new_tokens: int = 32
    input_bytes: int = 16384
    output_bytes: int = 16384

    def validate(self):
        for key, ceiling in (('prompt_tokens', 1024), ('new_tokens', 128),
                             ('input_bytes', 65536), ('output_bytes', 65536)):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= ceiling:
                raise ValueError('bounded integer decode limit required: ' + key)


def public_messages(task, previous, feedback, limits):
    limits.validate()
    if type(task) is not PublicTask:
        raise ValueError('typed public task required')
    task.validate()
    if (previous is None) != (feedback is None):
        raise ValueError('revision must carry both the actual candidate and feedback')
    if previous is not None:
        _text(previous); _text(feedback)
    parts = [task.prompt] + [text for text, _ in task.observations]
    if sum(len(s.encode('utf-8')) for s in parts + ([previous, feedback] if previous is not None else [])) > limits.input_bytes:
        raise ValueError('public input byte budget exceeded; no truncation')
    messages = [{'role': 'user', 'content': '\n'.join(parts)}]
    if previous is not None:
        messages += [{'role': 'assistant', 'content': previous},
                     {'role': 'user', 'content': 'Review the preceding response. Feedback: ' + feedback
                         + '\nGive a revised answer. Do not assume that the feedback is correct.'}]
    return messages


def checked_config(root):
    config = strict_json(Path(root) / 'config.json', max_bytes=1 << 20)
    if (not isinstance(config, dict) or config.get('model_type') != 'llama'
            or config.get('architectures') != ['LlamaForCausalLM']
            or config.get('tie_word_embeddings') is not True or config.get('auto_map')):
        raise ValueError('reviewed tied stock Llama causal architecture required')
    for key, ceiling in (('hidden_size', 2048), ('intermediate_size', 8192),
                         ('num_hidden_layers', 64), ('vocab_size', 100000),
                         ('num_attention_heads', 64), ('num_key_value_heads', 64),
                         ('max_position_embeddings', 131072)):
        value = config.get(key)
        if type(value) is not int or not 1 <= value <= ceiling:
            raise ValueError('unbounded causal model geometry: ' + key)
    d, m, n, v, h, kv = (config[k] for k in ('hidden_size', 'intermediate_size',
        'num_hidden_layers', 'vocab_size', 'num_attention_heads', 'num_key_value_heads'))
    if d % h or h % kv or d*v + n*(4*d*d + 3*d*m + 4*d) > 250_000_000:
        raise ValueError('causal model exceeds CPU loading envelope')
    if (config.get('rope_scaling') is not None or config.get('pretraining_tp', 1) != 1
            or config.get('head_dim', d // h) != d // h
            or config.get('hidden_act', 'silu') != 'silu'
            or config.get('attention_bias', False) is not False
            or config.get('mlp_bias', False) is not False):
        raise ValueError('unreviewed rotary or tensor-parallel profile')
    for key in ('bos_token_id', 'eos_token_id'):
        if type(config.get(key)) is not int or not 0 <= config[key] < v:
            raise ValueError('single in-vocabulary BOS/EOS required')
    files = list(Path(root).rglob('*.safetensors'))
    if not 1 <= len(files) <= 8 or sum(f.stat().st_size for f in files) > 800_000_000:
        raise ValueError('bounded safe tensor inventory required')
    return config


def load_local_causal(root):
    """Only a pinned stock architecture; every materialized tensor is checked."""
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer
    if transformers.__version__ != TRANSFORMERS_VERSION:
        raise ValueError('causal profile requires the reviewed Transformers version')
    checked_config(root)
    tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True, trust_remote_code=False)
    loaded = AutoModelForCausalLM.from_pretrained(str(root), local_files_only=True,
        trust_remote_code=False, use_safetensors=True, output_loading_info=True,
        attn_implementation='eager', torch_dtype=torch.float32)
    if not isinstance(loaded, tuple) or len(loaded) != 2:
        raise ValueError('complete causal loading report required')
    model, info = loaded
    model = model.to('cpu').eval().requires_grad_(False)
    material = verify_loaded_safetensors(torch, model, root, tied_aliases=ALIASES)
    if not isinstance(info, dict) or not isinstance(info.get('missing_keys'), (list, tuple)):
        raise ValueError('complete missing tensor report required')
    adjusted = {**info, 'missing_keys': [k for k in info['missing_keys'] if k not in material['omitted_tied_keys']]}
    loading = validate_encoder_loading_info(adjusted)
    if model.config.model_type != 'llama' or model.config._attn_implementation != 'eager':
        raise ValueError('loaded path differs from registered causal profile')
    if not isinstance(tokenizer.chat_template, str) or not tokenizer.chat_template:
        raise ValueError('pinned chat template required')
    if tokenizer.eos_token_id != model.config.eos_token_id:
        raise ValueError('tokenizer/model EOS mismatch')
    from head_surgery import tensor_inventory
    return model, tokenizer, dict(loading=loading, materialization=material,
        tensors=tensor_inventory(model), attention='eager', precision='float32',
        hardware='cpu', pretrained_provenance_authenticated=False)


def greedy_decode(model, tokenizer, messages, limits):
    """No truth computation here: every output token comes from model logits."""
    import torch
    limits.validate()
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    if not isinstance(prompt, str) or len(prompt.encode('utf-8')) > limits.input_bytes + 4096:
        raise ValueError('rendered prompt outside byte envelope')
    tokens = tokenizer(prompt, return_tensors='pt', add_special_tokens=False, truncation=False)
    ids, mask = tokens.get('input_ids'), tokens.get('attention_mask')
    if (not isinstance(ids, torch.Tensor) or not isinstance(mask, torch.Tensor)
            or ids.ndim != 2 or ids.shape[0] != 1 or mask.shape != ids.shape
            or ids.device.type != 'cpu' or ids.dtype != torch.long
            or not 1 <= ids.shape[1] <= limits.prompt_tokens or not torch.all(mask == 1).item()):
        raise ValueError('single unpadded bounded token input required')
    if ids.shape[1] + limits.new_tokens > model.config.max_position_embeddings:
        raise ValueError('prompt plus continuation exceeds context; no truncation')
    vocab, eos = model.config.vocab_size, model.config.eos_token_id
    if ids.min().item() < 0 or ids.max().item() >= vocab:
        raise ValueError('prompt token outside model vocabulary')
    generated, lengths, status = [], [], 'token_limit'
    started = time.perf_counter_ns()
    with torch.inference_mode():
        for _ in range(limits.new_tokens):
            lengths.append(ids.shape[1])
            result = model(input_ids=ids, attention_mask=mask, use_cache=False, return_dict=True)
            logits = result.logits
            if (logits.shape != (1, ids.shape[1], vocab) or logits.device.type != 'cpu'
                    or logits.dtype != torch.float32 or not torch.isfinite(logits[0, -1]).all().item()):
                raise ValueError('invalid causal vocabulary logits')
            next_id = int(logits[0, -1].argmax().item())
            generated.append(next_id)
            if next_id == eos:
                status = 'eos'; break
            ids = torch.cat((ids, torch.tensor([[next_id]], dtype=torch.long)), dim=1)
            mask = torch.ones_like(ids)
    text = tokenizer.decode(generated, skip_special_tokens=True, clean_up_tokenization_spaces=False)
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > limits.output_bytes:
        raise ValueError('empty or over-budget decoded answer; no fabricated fallback')
    return text, dict(schema='hepta.causal-generation-observation.v1', status=status,
        prompt_tokens=lengths[0], generated_token_ids=generated, forward_prefix_lengths=lengths,
        forward_calls=len(lengths), elapsed_ns=time.perf_counter_ns()-started,
        output_sha256=_digest(text), kv_cache_persisted=False, sample_rng_used=False,
        full_cost_qualified=False, answer_correctness_established=False)


class LocalCausalProposer:
    """Read-only shared weights; every call starts with a fresh public prefix."""
    def __init__(self, root, *, expected_snapshot_sha256, limits=DecodeLimits()):
        limits.validate(); _sha(expected_snapshot_sha256, 'externally retained model snapshot')
        self.root, self.limits = Path(root).resolve(), limits
        self.snapshot_id = expected_snapshot_sha256
        if snapshot_digest(self.root) != self.snapshot_id:
            raise ValueError('causal snapshot changed before loading')
        self.model, self.tokenizer, self.loading = load_local_causal(self.root)
        self.receipt = dict(profile=PROFILE, snapshot_sha256=self.snapshot_id, limits=asdict(limits),
            tokenizer_and_weights_pinned=True, cache_mode='none_full_prefix_recompute',
            source_sha256=__import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest(),
            loading=self.loading)
        self.profile_sha256 = _digest(self.receipt)
        self.last_observation = None
        self.reverify()

    def reverify(self):
        import torch
        if snapshot_digest(self.root) != self.snapshot_id:
            raise ValueError('causal snapshot bytes changed')
        verify_loaded_safetensors(torch, self.model, self.root, tied_aliases=ALIASES)
        if self.model.training or any(p.requires_grad for p in self.model.parameters()):
            raise ValueError('selected causal model must remain frozen')

    def __call__(self, task, previous, feedback):
        messages = public_messages(task, previous, feedback, self.limits)
        if self.model.training or any(p.requires_grad for p in self.model.parameters()):
            raise ValueError('causal model unexpectedly trainable')
        # Reverification of all file/tensor bytes belongs at acquisition/batch
        # boundaries, not an unreported per-token full-weight scan.
        text, observation = greedy_decode(self.model, self.tokenizer, messages, self.limits)
        self.last_observation = copy.deepcopy(observation)
        return text
