"""Shadow-only shared Encoder batching and feature cache.

A real Hugging Face model can be used from a pre-verified *local* snapshot,
without network access. Synthetic backends in unit tests are never production
model evidence. This module produces no authority, signed receipts, NDU values,
or native Rust batch attestation.
"""

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import math
import struct
import time

MAX_ITEMS = 32
MAX_TEXT_BYTES = 65536
MAX_FEATURE_WIDTH = 65536
MAX_ENCODED_TOKENS = 8192  # Matches the admitted local HF token cap.
NATIVE_Q24_INPUT_LIMIT = 512


def digest_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def digest_ok(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class FeatureRequest:
    request_id: str
    cell_id: str
    scope_digest: str
    generation: int
    revocation_frontier_digest: str
    encoder_digest: str
    preprocessor_digest: str
    runtime_digest: str
    input_digest: str
    text: str
    representation: str = "mean"

    def validate(self):
        if not all(isinstance(x, str) and 0 < len(x) <= 256 for x in (self.request_id, self.cell_id)):
            raise ValueError("request/cell identity must be bounded")
        for name in ("scope_digest", "revocation_frontier_digest", "encoder_digest", "preprocessor_digest", "runtime_digest", "input_digest"):
            if not digest_ok(getattr(self, name)):
                raise ValueError(f"invalid {name}")
        if not isinstance(self.generation, int) or isinstance(self.generation, bool) or self.generation < 1:
            raise ValueError("invalid generation")
        if not isinstance(self.text, str) or not self.text or len(self.text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("invalid text length")
        if digest_text(self.text) != self.input_digest:
            raise ValueError("input content digest mismatch")
        if self.representation not in {"mean", "landmark8"}:
            raise ValueError("unknown representation")

    def cache_key(self):
        return (
            self.scope_digest, self.generation, self.revocation_frontier_digest,
            self.encoder_digest, self.preprocessor_digest, self.runtime_digest, self.input_digest, self.representation,
        )


@dataclass(frozen=True)
class FrozenFeature:
    values: tuple[float, ...]
    token_count: int
    representation: str
    feature_digest: str

    @classmethod
    def from_values(cls, values, token_count, representation):
        if (type(token_count) is not int or
                not 1 <= token_count <= MAX_ENCODED_TOKENS or
                not 0 < len(values) <= MAX_FEATURE_WIDTH):
            raise ValueError("invalid encoded feature shape")
        if type(representation) is not str or representation not in ("mean", "landmark8"):
            raise ValueError("invalid representation")
        normalized = []
        chunks = [b"hepta.stem.feature.f32.v1", len(values).to_bytes(8, "big")]
        for value in values:
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("non-finite encoded feature")
            try:
                encoded = struct.pack(">f", float(value))
            except (OverflowError, struct.error) as error:
                raise ValueError("unrepresentable feature value") from error
            normalized.append(struct.unpack(">f", encoded)[0])
            chunks.append(encoded)
        chunks.append(token_count.to_bytes(8, "big"))
        chunks.append(representation.encode("ascii"))
        return cls(tuple(normalized), token_count, representation, hashlib.sha256(b"".join(chunks)).hexdigest())

    def verify_integrity(self):
        """Bind every returned backend float32 bit pattern to its declared digest.

        Frozen dataclasses can be constructed directly without from_values,
        so neither a backend response nor a cache admission is trusted simply
        because isinstance(value, FrozenFeature) succeeds.
        """
        if type(self.values) is not tuple or not digest_ok(self.feature_digest):
            raise ValueError("unverified immutable encoded feature")
        reconstructed = self.from_values(
            self.values, self.token_count, self.representation)
        if (reconstructed.feature_digest != self.feature_digest or
                reconstructed.values != self.values):
            raise ValueError("encoded feature content/digest mismatch")


@dataclass(frozen=True)
class FeatureReceipt:
    request_id: str
    cell_id: str
    scope_digest: str
    generation: int
    revocation_frontier_digest: str
    encoder_digest: str
    input_digest: str
    preprocessor_digest: str
    runtime_digest: str
    feature_digest: str
    feature_width: int
    tokens: int
    cache_hit: bool
    native_q24_compatible_width: bool
    status: str = "shadow_only_not_authorized"


class ScopedFeatureCache:
    """Bounded LRU of immutable Python float tuples, scoped at every reuse.

    The byte ceiling is an object-aware conservative estimate, NOT raw f32
    payload bytes or measured process RSS. We never claim GPU allocation.
    """

    def __init__(self, maximum_bytes):
        if type(maximum_bytes) is not int or maximum_bytes < 0:
            raise ValueError("cache capacity must be a non-negative integer")
        self.maximum_bytes = maximum_bytes
        # key -> (FrozenFeature, charged resident estimate)
        self._entries = OrderedDict()
        self.size_bytes = 0
        self.evictions = 0

    def get(self, key):
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key][0]

    def put(self, key, value):
        from cache_accounting import estimated_python_cache_entry_bytes

        if type(value) is not FrozenFeature:
            raise ValueError("invalid shared-feature cache payload")
        value.verify_integrity()
        existing = self._entries.get(key)
        if existing is not None and existing[0].feature_digest != value.feature_digest:
            raise ValueError("different feature content for identical scoped cache key")
        size = estimated_python_cache_entry_bytes(key, value, value.values)
        if size > self.maximum_bytes:
            return
        if key in self._entries:
            _, old_size = self._entries.pop(key)
            self.size_bytes -= old_size
        while self.size_bytes + size > self.maximum_bytes:
            _, (_, old_size) = self._entries.popitem(last=False)
            self.size_bytes -= old_size
            self.evictions += 1
        self._entries[key] = (value, size)
        self.size_bytes += size

    def invalidate_scope(self, scope_digest):
        for key in list(self._entries):
            if key[0] == scope_digest:
                _, size = self._entries.pop(key)
                self.size_bytes -= size

    def invalidate_generation(self, scope_digest, generation):
        for key in list(self._entries):
            if key[0] == scope_digest and key[1] != generation:
                _, size = self._entries.pop(key)
                self.size_bytes -= size


@dataclass(frozen=True)
class BatchObservation:
    receipts: tuple[FeatureReceipt, ...]
    batch_identity: str
    distinct_inputs: int
    cache_hits: int
    backend_calls: int
    backend_batch_widths: tuple[int, ...]
    elapsed_ns: int
    cpu_ns: int
    cache_bytes: int
    simulated: bool
    production_authorized: bool = False


class SharedStemEngine:
    """Preflights the whole request set then executes distinct inputs once."""

    def __init__(self, backend, *, max_cache_bytes=64 * 1024 * 1024):
        self.backend = backend
        self.cache = ScopedFeatureCache(max_cache_bytes)

    def run(self, requests, *, return_features=False):
        # Do not expose feature vectors in standard receipts. A privileged
        # shadow-only projection caller must opt in to ephemeral immutable values.
        if type(return_features) is not bool:
            raise ValueError("invalid feature-return mode")
        start_ns, cpu_start = time.perf_counter_ns(), time.process_time_ns()
        if not isinstance(requests, (list, tuple)) or not 1 <= len(requests) <= MAX_ITEMS:
            raise ValueError("batch size must be within 1..32")
        ids = set()
        for r in requests:
            if not isinstance(r, FeatureRequest):
                raise ValueError("invalid feature request")
            r.validate()
            if r.request_id in ids:
                raise ValueError("duplicate request_id")
            ids.add(r.request_id)
            if (r.encoder_digest != self.backend.encoder_digest
                    or r.preprocessor_digest != self.backend.preprocessor_digest
                    or r.runtime_digest != self.backend.runtime_digest):
                raise ValueError("unselected or changed model/preprocessor")
        # A single batch may never combine different tenants, generations,
        # revocation frontiers, or representation schemas.
        scoped = {(r.scope_digest, r.generation, r.revocation_frontier_digest, r.representation) for r in requests}
        if len(scoped) != 1:
            raise ValueError("mixed scope/generation/revocation/representation batch")
        batch_bytes = bytearray(b"hepta.stem.batch.shadow.v1")
        for r in requests:
            for field in (
                r.request_id, r.input_digest, r.cell_id, r.scope_digest,
                str(r.generation), r.revocation_frontier_digest,
                r.encoder_digest, r.preprocessor_digest, r.runtime_digest,
                r.representation,
            ):
                encoded = field.encode("utf-8")
                batch_bytes.extend(len(encoded).to_bytes(8, "big"))
                batch_bytes.extend(encoded)
        ident = hashlib.sha256(batch_bytes).hexdigest()
        missing = OrderedDict()
        hits = 0
        for r in requests:
            key = r.cache_key()
            if self.cache.get(key) is None:
                missing.setdefault(key, r.text)
            else:
                hits += 1
        calls = 0
        batch_widths = []
        if missing:
            # Requests that coalesce within this batch share one model result.
            keys, texts = list(missing), list(missing.values())
            outcomes = self.backend.encode_many(texts, requests[0].representation)
            calls = 1
            batch_widths.append(len(texts))
            if len(outcomes) != len(texts):
                raise ValueError("backend returned wrong batch count")
            verified = []
            for item in outcomes:
                if type(item) is not FrozenFeature or item.representation != requests[0].representation:
                    raise ValueError("backend returned invalid representation")
                item.verify_integrity()
                verified.append(item)
            for k, out in zip(keys, verified):
                self.cache.put(k, out)
            # When cache is disabled/too small, use invocation-local results.
            local_results = dict(zip(keys, verified))
        else:
            local_results = {}
        receipts = []
        ephemeral_features = []
        for r in requests:
            item = self.cache.get(r.cache_key()) or local_results.get(r.cache_key())
            if item is None:
                raise ValueError("unresolved feature after backend invocation")
            if return_features:
                ephemeral_features.append(item)
            receipts.append(FeatureReceipt(
                request_id=r.request_id, cell_id=r.cell_id, scope_digest=r.scope_digest,
                generation=r.generation, revocation_frontier_digest=r.revocation_frontier_digest,
                encoder_digest=r.encoder_digest, input_digest=r.input_digest,
                preprocessor_digest=r.preprocessor_digest, runtime_digest=r.runtime_digest,
                feature_digest=item.feature_digest,
                feature_width=len(item.values), tokens=item.token_count,
                cache_hit=r.cache_key() not in missing,
                native_q24_compatible_width=len(item.values) <= NATIVE_Q24_INPUT_LIMIT,
            ))
        observed = BatchObservation(
            tuple(receipts), ident, len(missing), hits, calls, tuple(batch_widths),
            time.perf_counter_ns() - start_ns, time.process_time_ns() - cpu_start,
            self.cache.size_bytes, getattr(self.backend, "simulated", True),
        )
        if return_features:
            return observed, tuple(ephemeral_features)
        return observed


class FrozenLocalHfBackend:
    """Real batched HF Encoder execution; offline and snapshot-verified.

    This backend never downloads models or runs unaudited repository code.
    It requires a complete local snapshot; nonstandard remote-code models must
    use a separately reviewed, installed implementation, not trust_remote_code.
    """

    simulated = False

    def __init__(self, snapshot, *, expected_snapshot_digest, preprocessor_digest,
                 runtime_digest, max_tokens, device="cpu"):
        from model_runner import snapshot_digest
        self.encoder_digest = expected_snapshot_digest
        self.preprocessor_digest = preprocessor_digest
        self.runtime_digest = runtime_digest
        if (not digest_ok(expected_snapshot_digest) or not digest_ok(preprocessor_digest)
                or not digest_ok(runtime_digest)):
            raise ValueError("invalid model/preprocessor digest")
        if snapshot_digest(snapshot) != expected_snapshot_digest:
            raise ValueError("unverified local model snapshot")
        if not isinstance(max_tokens, int) or max_tokens < 1 or max_tokens > 8192:
            raise ValueError("invalid token cap")
        import torch
        from transformers import AutoModel, AutoTokenizer
        from hf_joint_decision_runner import (
            validate_encoder_loading_info, verify_loaded_safetensors,
        )
        self.torch = torch
        self.device = device
        self.max_tokens = max_tokens
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(snapshot), local_files_only=True, trust_remote_code=False)
        loaded = AutoModel.from_pretrained(
            str(snapshot), local_files_only=True, trust_remote_code=False,
            use_safetensors=True, output_loading_info=True)
        if type(loaded) is not tuple or len(loaded) != 2:
            raise ValueError("shared Encoder requires audited complete HF loading report")
        model, loading_info = loaded
        self.verified_loading = validate_encoder_loading_info(loading_info)
        model = model.to(device).eval()
        # A loading-info summary alone cannot detect a backend that silently
        # leaves a tensor randomized. Compare every actual model tensor against
        # the immutable, already SHA-pinned local safetensors inventory.
        self.verified_materialization = verify_loaded_safetensors(
            torch, model, snapshot)
        self.model = model
        for p in self.model.parameters():
            p.requires_grad_(False)
        self.invocations = 0

    def encode_many(self, texts, representation):
        if not texts or len(texts) > MAX_ITEMS or representation not in {"mean", "landmark8"}:
            raise ValueError("invalid encoder call")
        t = self.torch
        tokenized = self.tokenizer(texts, return_tensors="pt", padding=True, truncation=False)
        masks = tokenized["attention_mask"]
        lengths = [int(x) for x in masks.sum(dim=1).tolist()]
        if any(x > self.max_tokens or x < 1 for x in lengths):
            raise ValueError("input exceeds frozen token capacity; no silent truncation")
        args = {k: v.to(self.device) for k, v in tokenized.items()}
        if self.device.startswith("cuda"):
            t.cuda.synchronize()
        with t.inference_mode():
            hidden = self.model(**args).last_hidden_state.detach().float().cpu()
        if self.device.startswith("cuda"):
            t.cuda.synchronize()
        self.invocations += 1
        results = []
        masks_cpu = masks.bool().cpu()
        for i, count in enumerate(lengths):
            # Works for both left- and right-padding; :count silently reads
            # padding on left-padded models and drops valid suffix tokens.
            tokens = hidden[i][masks_cpu[i]]
            if representation == "mean":
                values = tokens.mean(dim=0).tolist()
            else:
                # Eight contiguous, deterministic token landmarks, retaining
                # position coverage without silently discarding the suffix.
                values = []
                for b in range(8):
                    a = (b * count) // 8
                    z = ((b + 1) * count) // 8
                    if z <= a:
                        z = min(count, a + 1)
                    values.extend(tokens[a:z].mean(dim=0).tolist())
            results.append(FrozenFeature.from_values(values, count, representation))
        return results


if __name__ == "__main__":
    raise SystemExit("Use this module from a separately admitted shadow run; no production CLI")
