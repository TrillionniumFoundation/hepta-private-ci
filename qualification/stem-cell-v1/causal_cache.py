"""Request-local inference KV cache, never shared between calls or persisted.

Caps cover validated cache backing storage at forward boundaries, not arbitrary
model allocations, activations or kernel-time transient peaks. Hashes and checks
do not make an arbitrary stateful model trustworthy. No fallback to recomputation.
"""
from __future__ import annotations

import copy
import torch

from next_round_matrix import _digest
from paired_execution import _integer

SCHEMA = "hepta.request-kv-policy.v1"
FORMATS = ("legacy_tuple", "hf_dynamic_gpt2_4_57_1")


def freeze_cache(*, layers, heads, head_dim, max_cache_bytes, cache_format):
    for name, value, cap in (("layers", layers, 48), ("heads", heads, 64),
                             ("head_dim", head_dim, 256), ("bytes", max_cache_bytes, 1 << 30)):
        _integer(value, "cache " + name, 1)
        if value > cap:
            raise ValueError("cache geometry or byte bound exceeded")
    if cache_format not in FORMATS:
        raise ValueError("explicit supported cache format required")
    body = dict(schema=SCHEMA, layers=layers, heads=heads, head_dim=head_dim,
                max_cache_bytes=max_cache_bytes, cache_format=cache_format,
                scope="one_proposal", precision="cpu_fp32", batch_size=1)
    return {**body, "cache_policy_id": _digest(body)}


def validate_cache_policy(policy):
    try:
        expected = freeze_cache(**{k: policy[k] for k in
            ("layers", "heads", "head_dim", "max_cache_bytes", "cache_format")})
    except (KeyError, TypeError) as exc:
        raise ValueError("complete cache policy required") from exc
    if _digest(expected) != _digest(policy):
        raise ValueError("cache policy identity or scope changed")
    return expected


def _storage(tensor):
    storage = tensor.untyped_storage()
    return (str(tensor.device), storage.data_ptr()), storage.nbytes()


class RequestKV:
    """A local decoding session. Call close in finally, including failed forwards."""
    def __init__(self, model, policy, *, prompt_tokens, max_new_tokens):
        self.policy = validate_cache_policy(policy)
        _integer(prompt_tokens, "prompt tokens", 1)
        _integer(max_new_tokens, "new tokens", 1)
        self.limit = prompt_tokens + max_new_tokens - 1
        if self.limit > 8192:
            raise ValueError("cache token limit exceeded")
        p = self.policy
        minimum_payload = 2 * p['layers'] * p['heads'] * p['head_dim'] * self.limit * 4
        if minimum_payload > p['max_cache_bytes']:
            raise ValueError("declared cache cannot fit the token envelope")
        if p['cache_format'] == FORMATS[1]:
            import transformers
            if transformers.__version__ != "4.57.1" or model.config.model_type != "gpt2":
                raise ValueError("exact stock GPT2 cache profile required")
        self.model = model
        self.weight_storage = {_storage(t)[0] for t in model.state_dict().values()}
        self.cache, self.prefix, self.storage = None, [], {}
        self.closed = False
        self.stats = dict(cache_policy_id=p['cache_policy_id'], forwarded_tokens=0,
                          forward_attempts=0, cache_tokens=0, backing_bytes=0,
                          max_boundary_storage_union_bytes=0, released=False,
                          peak_process_memory_established=False)

    def _inspect(self, cache, length):
        p = self.policy
        if p['cache_format'] == FORMATS[1]:
            from transformers.cache_utils import DynamicCache, DynamicLayer
            if (type(cache) is not DynamicCache or cache.offloading
                    or len(cache.layers) != p['layers']
                    or any(type(layer) is not DynamicLayer for layer in cache.layers)):
                raise ValueError("only non-offloaded dynamic GPT2 KV layers are supported")
            if cache.get_seq_length() != length:
                raise ValueError("dynamic cache sequence length mismatch")
            cache = cache.to_legacy_cache()
        if type(cache) is not tuple or len(cache) != p['layers']:
            raise ValueError("cache layer inventory mismatch")
        storages = {}
        for pair in cache:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("exact key/value pairs required")
            for tensor in pair:
                if (type(tensor) is not torch.Tensor or tensor.layout != torch.strided
                        or tuple(tensor.shape) != (1, p['heads'], length, p['head_dim'])
                        or tensor.dtype != torch.float32 or tensor.device.type != 'cpu'
                        or tensor.requires_grad):
                    raise ValueError("cache tensor geometry, precision or ownership invalid")
                key, size = _storage(tensor)
                if key in self.weight_storage:
                    raise ValueError("cache aliases immutable model weights")
                storages[key] = size
                if sum(storages.values()) > p['max_cache_bytes']:
                    raise ValueError("cache backing storage exceeds budget")
                if not torch.isfinite(tensor).all().item():
                    raise ValueError("nonfinite cache state")
        return storages

    def forward(self, tokens):
        if self.closed:
            raise ValueError("closed cache cannot resume")
        if (tokens.dtype != torch.long or tokens.device.type != 'cpu' or tokens.ndim != 2
                or tokens.shape[0] != 1 or not 1 <= tokens.shape[1] <= self.limit):
            raise ValueError("bounded single unpadded token sequence required")
        ids = tokens[0].tolist()
        past = len(self.prefix)
        if past and (ids[:-1] != self.prefix or len(ids) != past + 1):
            raise ValueError("cache cannot be reused for a different prefix")
        query = tokens[:, past:]
        positions = torch.arange(past, len(ids), dtype=torch.long)
        self.stats['forward_attempts'] += 1
        self.stats['forwarded_tokens'] += query.shape[1]
        result = self.model(input_ids=query, attention_mask=torch.ones_like(tokens),
                            position_ids=positions.unsqueeze(0), cache_position=positions,
                            past_key_values=self.cache, use_cache=True, return_dict=True)
        returned = getattr(result, 'past_key_values', None)
        observed = self._inspect(returned, len(ids))
        # Union at the two boundaries: old dynamic storage can have been freed
        # inside forward. This is NOT a measured instantaneous process peak.
        union = dict(self.storage)
        for key, size in observed.items():
            union[key] = max(size, union.get(key, 0))
        union_bytes = sum(union.values())
        self.stats['max_boundary_storage_union_bytes'] = max(
            self.stats['max_boundary_storage_union_bytes'], union_bytes)
        if union_bytes > self.policy['max_cache_bytes']:
            raise ValueError("old/returned cache storage union exceeds budget")
        self.cache, self.storage, self.prefix = returned, observed, ids
        self.stats.update(cache_tokens=len(ids), backing_bytes=sum(observed.values()))
        return result.logits, query.shape[1]

    def close(self):
        self.cache, self.prefix, self.storage, self.model = None, [], {}, None
        self.closed = True
        self.stats['released'] = True  # Adapter references released, not an allocator/RSS claim.

    def receipt(self):
        return copy.deepcopy(self.stats)
