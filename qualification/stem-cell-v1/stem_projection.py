"""Shadow-only deterministic, versioned low-rank Q24 Stem projection.

This never attests Encoder execution, checks grants or publishes a selected
model. Its outputs must cross Hepta's existing authorization and inference
control boundary. No implicit slicing of a 768/1152/6144-wide feature.
"""

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import math
import struct

Q = 1 << 24
LIMIT = 8 * Q
MAX_SOURCE_WIDTH = 8192
MAX_NATIVE_WIDTH = 512
MAX_RANK = 64
MAX_COEFFICIENTS = 600_000
DOMAIN = b"hepta.stem.low-rank-projection.q24.v1"
BOUND_DOMAIN = b"hepta.stem.projected-feature-bound.v1"


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _u64(n):
    if type(n) is not int or n < 0 or n >= (1 << 64):
        raise ValueError("invalid unsigned 64-bit field")
    return n.to_bytes(8, "big")


def _field(value):
    if not isinstance(value, str):
        raise ValueError("invalid binding field")
    encoded = value.encode("utf-8")
    return _u64(len(encoded)) + encoded


def _int64(n):
    if type(n) is not int or n < -(1 << 63) or n >= (1 << 63):
        raise ValueError("invalid Q24 coefficient")
    return n.to_bytes(8, "big", signed=True)


def q24_from_float(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("non-finite numeric feature")
    value = struct.unpack(">f", struct.pack(">f", float(value)))[0]
    if abs(value) > 8:
        raise ValueError("Q24 input outside [-8,8]")
    return int(round(value * Q))


def round_q48(acc):
    if type(acc) is not int:
        raise ValueError("noninteger accumulator")
    quotient, remainder = divmod(acc, Q)
    if remainder * 2 > Q or (remainder * 2 == Q and quotient % 2):
        quotient += 1
    if not -LIMIT <= quotient <= LIMIT:
        raise ValueError("Q24 projection output outside [-8,8]")
    return quotient


@dataclass(frozen=True)
class LowRankProjectionQ24:
    encoder_digest: str
    preprocessor_digest: str
    runtime_digest: str
    normalizer_digest: str
    representation: str
    input_width: int
    output_width: int
    rank: int
    a_q24: tuple[int, ...]  # [rank,input_width] row-major
    b_q24: tuple[int, ...]  # [output_width,rank] row-major
    bias_q24: tuple[int, ...]

    def validate(self):
        if any(not _sha(d) for d in (
            self.encoder_digest, self.preprocessor_digest,
            self.runtime_digest, self.normalizer_digest,
        )):
            raise ValueError("unpinned Encoder/normalizer identity")
        if self.representation not in ("mean", "landmark8"):
            raise ValueError("invalid representation")
        if any(type(x) is not int for x in (self.input_width, self.output_width, self.rank)):
            raise ValueError("invalid projection dimensions")
        if not (1 <= self.input_width <= MAX_SOURCE_WIDTH and
                1 <= self.output_width <= MAX_NATIVE_WIDTH and
                1 <= self.rank <= MAX_RANK):
            raise ValueError("projection dimensions exceed registered bounds")
        if (len(self.a_q24) != self.input_width * self.rank or
                len(self.b_q24) != self.output_width * self.rank or
                len(self.bias_q24) != self.output_width or
                sum(map(len, (self.a_q24, self.b_q24, self.bias_q24))) > MAX_COEFFICIENTS):
            raise ValueError("projection tensor shapes/cost mismatch")
        for values in (self.a_q24, self.b_q24, self.bias_q24):
            if any(type(x) is not int or not -LIMIT <= x <= LIMIT for x in values):
                raise ValueError("unbounded Q24 projection coefficient")

    @property
    def digest(self):
        self.validate()
        h = hashlib.sha256()
        h.update(DOMAIN)
        for value in (self.encoder_digest, self.preprocessor_digest,
                      self.runtime_digest, self.normalizer_digest, self.representation):
            h.update(_field(value))
        for value in (self.input_width, self.output_width, self.rank):
            h.update(_u64(value))
        for tensor in (self.a_q24, self.b_q24, self.bias_q24):
            h.update(_u64(len(tensor)))
            for x in tensor:
                h.update(_int64(x))
        return h.hexdigest()

    def project_q24(self, inputs):
        self.validate()
        if len(inputs) != self.input_width or any(
                type(x) is not int or not -LIMIT <= x <= LIMIT for x in inputs):
            raise ValueError("wrong-width/unsafe projection input")
        hidden = []
        for k in range(self.rank):
            off = k * self.input_width
            acc = sum(inputs[j] * self.a_q24[off+j] for j in range(self.input_width))
            hidden.append(round_q48(acc))
        out = []
        for k in range(self.output_width):
            off = k * self.rank
            acc = self.bias_q24[k] * Q
            acc += sum(hidden[j] * self.b_q24[off+j] for j in range(self.rank))
            out.append(round_q48(acc))
        return tuple(out)

    def project_float32(self, values):
        return self.project_q24(tuple(q24_from_float(x) for x in values))


@dataclass(frozen=True)
class ProjectedFeatureRef:
    request_id: str
    scope_digest: str
    generation: int
    revocation_frontier_digest: str
    encoder_digest: str
    source_input_digest: str
    source_feature_digest: str
    projection_digest: str
    vector_q24: tuple[int, ...]
    projected_input_digest: str
    production_authorized: bool = False


def project_ref(request, frozen_feature, projection):
    """Bind selected and independently supplied frozen Feature to Q24 vector.

    No raw text, gradients, or auth token is retained. A digest is not a signature.
    """
    projection.validate()
    request.validate()
    if (request.encoder_digest != projection.encoder_digest or
            request.preprocessor_digest != projection.preprocessor_digest or
            request.runtime_digest != projection.runtime_digest or
            request.representation != projection.representation):
        raise ValueError("incompatible frozen Encoder/representation")
    if not _sha(frozen_feature.feature_digest):
        raise ValueError("feature digest missing")
    if (frozen_feature.representation != projection.representation or
            len(frozen_feature.values) != projection.input_width):
        raise ValueError("feature width/schema requires explicit projection")
    # Reconstruct the canonical source f32 digest. A digest provided by an
    # untrusted backend is not acceptable evidence by itself.
    if (type(frozen_feature.token_count) is not int or frozen_feature.token_count < 1):
        raise ValueError("invalid token count")
    h_source = hashlib.sha256(b"hepta.stem.feature.f32.v1")
    h_source.update(_u64(len(frozen_feature.values)))
    for value in frozen_feature.values:
        try:
            h_source.update(struct.pack(">f", float(value)))
        except (OverflowError, ValueError, struct.error) as exc:
            raise ValueError("invalid source f32 feature") from exc
    h_source.update(_u64(frozen_feature.token_count))
    h_source.update(frozen_feature.representation.encode("ascii"))
    if h_source.hexdigest() != frozen_feature.feature_digest:
        raise ValueError("source feature content/digest mismatch")
    projected = projection.project_float32(frozen_feature.values)
    h = hashlib.sha256(BOUND_DOMAIN)
    for value in (request.scope_digest, request.revocation_frontier_digest,
                  request.encoder_digest, request.preprocessor_digest,
                  request.runtime_digest, request.input_digest,
                  frozen_feature.feature_digest, projection.digest):
        h.update(_field(value))
    h.update(_u64(request.generation))
    h.update(_u64(len(projected)))
    for scalar in projected:
        h.update(_int64(scalar))
    return ProjectedFeatureRef(
        request_id=request.request_id,
        scope_digest=request.scope_digest,
        generation=request.generation,
        revocation_frontier_digest=request.revocation_frontier_digest,
        encoder_digest=request.encoder_digest,
        source_input_digest=request.input_digest,
        source_feature_digest=frozen_feature.feature_digest,
        projection_digest=projection.digest,
        vector_q24=projected,
        projected_input_digest=h.hexdigest(),
    )


class ScopedProjectionCache:
    """Immutable LRU scoped by owner identity, source feature, and projection version."""
    def __init__(self, maximum_bytes):
        if type(maximum_bytes) is not int or maximum_bytes < 0:
            raise ValueError("invalid cache capacity")
        self.maximum_bytes = maximum_bytes
        self._data = OrderedDict()
        self.bytes_used = 0

    def get(self, key):
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key, ref):
        size = len(ref.vector_q24) * 8
        if size > self.maximum_bytes:
            return
        if key in self._data:
            self.bytes_used -= len(self._data.pop(key).vector_q24) * 8
        while self.bytes_used + size > self.maximum_bytes:
            _, old = self._data.popitem(last=False)
            self.bytes_used -= len(old.vector_q24) * 8
        self._data[key] = ref
        self.bytes_used += size

    def invalidate_scope(self, scope_digest):
        for key in list(self._data):
            if key[0] == scope_digest:
                self.bytes_used -= len(self._data.pop(key).vector_q24) * 8


class ProjectedBatch:
    def __init__(self, encoder_observation, refs, cache_hits,
                 projection_calls, in_batch_reuses, elapsed_ns, cpu_ns, cache_bytes):
        self.encoder_observation = encoder_observation
        self.refs = tuple(refs)
        self.projection_cache_hits = cache_hits
        self.projection_calls = projection_calls
        self.projection_reuses_within_batch = in_batch_reuses
        self.projection_elapsed_ns = elapsed_ns
        self.projection_cpu_ns = cpu_ns
        self.projection_cache_bytes = cache_bytes
        self.production_authorized = False


class ProjectedStemEngine:
    """End-to-end shadow projection over the existing true Encoder batch path."""
    def __init__(self, shared_encoder_engine, projection, *, maximum_projection_cache_bytes=8 << 20):
        projection.validate()
        self.shared_encoder_engine = shared_encoder_engine
        self.projection = projection
        self.cache = ScopedProjectionCache(maximum_projection_cache_bytes)

    def run(self, requests):
        # Preflight projection compatibility before any actual Encoder execution.
        if not isinstance(requests, (tuple, list)) or not 1 <= len(requests) <= 32:
            raise ValueError("invalid projected batch count")
        for request in requests:
            request.validate()
            if (request.encoder_digest != self.projection.encoder_digest or
                    request.preprocessor_digest != self.projection.preprocessor_digest or
                    request.runtime_digest != self.projection.runtime_digest or
                    request.representation != self.projection.representation):
                raise ValueError("projector/backend identity mismatch")
        scopes = {(r.scope_digest, r.generation,
                   r.revocation_frontier_digest, r.representation) for r in requests}
        if len(scopes) != 1:
            raise ValueError("mixed scope/generation/revocation projection batch")
        observation, frozen = self.shared_encoder_engine.run(requests, return_features=True)
        if len(frozen) != len(requests):
            raise ValueError("Encoder feature bundle count mismatch")
        import time
        projection_start = time.perf_counter_ns()
        cpu_start = time.process_time_ns()
        pending, refs, cache_hits, projection_calls, in_batch_reuses = {}, [], 0, 0, 0
        for request, feature in zip(requests, frozen):
            key = (request.scope_digest, request.generation,
                   request.revocation_frontier_digest, request.encoder_digest,
                   request.preprocessor_digest, request.runtime_digest,
                   request.input_digest, feature.feature_digest, self.projection.digest)
            cached = self.cache.get(key)
            if cached is not None:
                cache_hits += 1
                # Cache values are only shared within the exact source identity.
                refs.append(ProjectedFeatureRef(
                    request_id=request.request_id, scope_digest=cached.scope_digest,
                    generation=cached.generation,
                    revocation_frontier_digest=cached.revocation_frontier_digest,
                    encoder_digest=cached.encoder_digest,
                    source_input_digest=cached.source_input_digest,
                    source_feature_digest=cached.source_feature_digest,
                    projection_digest=cached.projection_digest,
                    vector_q24=cached.vector_q24,
                    projected_input_digest=cached.projected_input_digest,
                ))
            else:
                ref = pending.get(key)
                if ref is None:
                    ref = project_ref(request, feature, self.projection)
                    pending[key] = ref
                    projection_calls += 1
                else:
                    in_batch_reuses += 1
                refs.append(ProjectedFeatureRef(
                    request_id=request.request_id, scope_digest=ref.scope_digest,
                    generation=ref.generation,
                    revocation_frontier_digest=ref.revocation_frontier_digest,
                    encoder_digest=ref.encoder_digest,
                    source_input_digest=ref.source_input_digest,
                    source_feature_digest=ref.source_feature_digest,
                    projection_digest=ref.projection_digest,
                    vector_q24=ref.vector_q24,
                    projected_input_digest=ref.projected_input_digest,
                ))
        # Publish only after all outputs have validated; no partial poisoned cache.
        for key, ref in pending.items():
            self.cache.put(key, ref)
        return ProjectedBatch(
            observation, refs, cache_hits, projection_calls, in_batch_reuses,
            time.perf_counter_ns() - projection_start,
            time.process_time_ns() - cpu_start, self.cache.bytes_used,
        )

PROJECTION_MANIFEST_SCHEMA = "hepta.stem.low-rank-projection.q24.v1"


def save_shadow_projection(path, projection, *, training_lineage_digest):
    """Write a never-overwrite shadow proposal; never writes Artifact CAS."""
    import json
    from pathlib import Path
    if not _sha(training_lineage_digest):
        raise ValueError("training lineage must be pinned")
    projection.validate()
    data = {
        "schema": PROJECTION_MANIFEST_SCHEMA,
        "shadow_only": True,
        "production_authorized": False,
        "training_lineage_digest": training_lineage_digest,
        "projection_digest": projection.digest,
    }
    for name in projection.__dataclass_fields__:
        value = getattr(projection, name)
        data[name] = list(value) if isinstance(value, tuple) else value
    encoded = (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with Path(path).open("xb") as handle:
        handle.write(encoded)
    return hashlib.sha256(encoded).hexdigest()


def load_shadow_projection(path, *, expected_file_sha256):
    """Fail-closed, exact-format JSON loader. Digest is NOT a signature."""
    import json
    from pathlib import Path
    if not _sha(expected_file_sha256):
        raise ValueError("untrusted projection file identity")
    with Path(path).open("rb") as handle:
        raw = handle.read(22_000_001)
    if len(raw) > 22_000_000 or hashlib.sha256(raw).hexdigest() != expected_file_sha256:
        raise ValueError("changed/oversize projection file")
    def object_pairs_no_duplicates(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate projection manifest key")
            result[k] = v
        return result
    data = json.loads(raw, object_pairs_hook=object_pairs_no_duplicates)
    required = set(LowRankProjectionQ24.__dataclass_fields__) | {
        "schema", "shadow_only", "production_authorized",
        "training_lineage_digest", "projection_digest",
    }
    if (type(data) is not dict or set(data) != required or
            data.get("schema") != PROJECTION_MANIFEST_SCHEMA or
            data.get("shadow_only") is not True or
            data.get("production_authorized") is not False or
            not _sha(data.get("training_lineage_digest")) or
            not _sha(data.get("projection_digest"))):
        raise ValueError("unknown or non-shadow projection manifest")
    for key in ("a_q24", "b_q24", "bias_q24"):
        if type(data[key]) is not list:
            raise ValueError("invalid projection tensor serialization")
        data[key] = tuple(data[key])
    projector = LowRankProjectionQ24(**{k: data[k] for k in LowRankProjectionQ24.__dataclass_fields__})
    if projector.digest != data["projection_digest"]:
        raise ValueError("projector weights changed without revision")
    return projector

# Only candidate bytes for the existing Learning Artifact CAS; no signature,
# publication, selection, CURRENT witness or inference authority is issued.
CAS_PROJECTION_PAYLOAD_SCHEMA = "hepta.stem.low-rank-projection-payload.v1"
CAS_PROJECTION_MAX_BYTES = 8 * 1024 * 1024


def encode_cas_projection_candidate(projection):
    """Encode a candidate payload; training/source lineage belongs to the
    separately signed ArtifactManifest and independent evaluator."""
    import json
    projection.validate()
    payload = {"schema": CAS_PROJECTION_PAYLOAD_SCHEMA, "projection": {}}
    for name in projection.__dataclass_fields__:
        value = getattr(projection, name)
        payload["projection"][name] = list(value) if isinstance(value, tuple) else value
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    if len(raw) > CAS_PROJECTION_MAX_BYTES:
        raise ValueError("CAS candidate exceeds pinned payload cap")
    return raw


def decode_cas_projection_candidate(raw, *, expected_payload_sha256,
                                    expected_projection_digest):
    """Untrusted shadow decoder; does NOT verify signatures or CURRENT."""
    import json
    if (type(raw) is not bytes or not 0 < len(raw) <= CAS_PROJECTION_MAX_BYTES or
            not _sha(expected_payload_sha256) or not _sha(expected_projection_digest) or
            hashlib.sha256(raw).hexdigest() != expected_payload_sha256):
        raise ValueError("CAS content digest/size mismatch")
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate CAS candidate key")
            out[key] = value
        return out
    try:
        data = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid CAS payload JSON") from error
    if (type(data) is not dict or set(data) != {"schema", "projection"} or
            data["schema"] != CAS_PROJECTION_PAYLOAD_SCHEMA or
            type(data["projection"]) is not dict or
            set(data["projection"]) != set(LowRankProjectionQ24.__dataclass_fields__)):
        raise ValueError("CAS projection schema mismatch")
    props = dict(data["projection"])
    for name in ("a_q24", "b_q24", "bias_q24"):
        if type(props[name]) is not list:
            raise ValueError("invalid CAS projection tensor")
        props[name] = tuple(props[name])
    candidate = LowRankProjectionQ24(**props)
    if candidate.digest != expected_projection_digest or raw != encode_cas_projection_candidate(candidate):
        raise ValueError("CAS projection revision/canonical bytes mismatch")
    return candidate
