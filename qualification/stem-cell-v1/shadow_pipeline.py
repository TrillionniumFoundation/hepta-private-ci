"""Read-only Encoder -> bounded projection -> per-Cell Q24 Head qualification.

The caller supplies a previously verified local HF Encoder and projection. This
layer never loads untrusted models, mints signed receipts, calls a production
Worker, or grants NDU/production authority. It *can* execute actual batched HF
Encoder tensors through ProjectedStemEngine if an independently audited local
snapshot was loaded by FrozenLocalHfBackend.
"""
from dataclasses import dataclass
import hashlib
import math
import time

from native_bridge import bundle_digest, native_logits, tensor_digest
from stem_projection import ProjectedStemEngine, Q

MAX_BATCH = 32
CANONICAL_HEAD_SCHEMA = "hepta.stem.q24-cpu-head-candidate.v1"


@dataclass(frozen=True)
class ShadowHeadResult:
    request_id: str
    cell_id: str
    source_feature_digest: str
    projected_input_digest: str
    projection_digest: str
    head_digest: str
    head_weights_digest: str
    logits_q24: tuple[int, ...]
    output_digest: str
    production_authorized: bool = False


@dataclass(frozen=True)
class ShadowPipelineObservation:
    results: tuple[ShadowHeadResult, ...]
    encoder_backend_calls: int
    distinct_inputs: int
    encoder_cache_hits: int
    projection_calls: int
    projection_cache_hits: int
    head_elapsed_ns: int
    source_is_simulated: bool
    production_authorized: bool = False


def validate_head(artifact, projection):
    if not isinstance(artifact, dict) or artifact.get("schema") != CANONICAL_HEAD_SCHEMA:
        raise ValueError("unregistered Q24 head schema")
    if artifact.get("shadow_only") is not True or artifact.get("production_authorized") is not False:
        raise ValueError("head claims unauthorized production activation")
    if artifact.get("encoder_digest") != projection.encoder_digest:
        raise ValueError("head/Encoder identity mismatch")
    width, classes = artifact.get("input_width"), artifact.get("output_width")
    if (type(width) is not int or width != projection.output_width or
            type(classes) is not int or not 1 <= classes <= 512):
        raise ValueError("head output or projected width mismatch")
    names = ("drive_weights_q24", "prediction_weights_q24", "gate_weights_q24",
             "drive_bias_q24", "prediction_bias_q24", "gate_bias_q24")
    tensors = tuple(artifact.get(k) for k in names)
    if any(type(t) is not list or any(type(x) is not int or abs(x) > 8 * Q for x in t)
           for t in tensors):
        raise ValueError("invalid bounded Q24 Head tensors")
    drive, prediction, gate, db, pb, gb = tensors
    if (len(drive) != width * classes or prediction or gate or
            len(db) != classes or pb != [0] * classes or gb != [Q] * classes):
        raise ValueError("only canonical constant-gate affine Head is supported")
    digest = tensor_digest(width, classes, tensors)
    if (artifact.get("head_digest") != digest or
            artifact.get("weights_digest") != bundle_digest(projection.encoder_digest, digest)):
        raise ValueError("Head tensor digest differs from selected bundle")
    return digest


class ShadowStemHeadPipeline:
    def __init__(self, encoder_engine, projection, cell_heads, *, cache_bytes=8 << 20):
        projection.validate()
        if not isinstance(cell_heads, dict) or not cell_heads:
            raise ValueError("nonempty explicit Cell head map required")
        self.encoder_projector = ProjectedStemEngine(
            encoder_engine, projection, maximum_projection_cache_bytes=cache_bytes,
        )
        self.projection = projection
        self.cell_heads = {}
        for cell, artifact in cell_heads.items():
            if not isinstance(cell, str) or not cell or len(cell) > 256:
                raise ValueError("invalid Cell identity")
            validate_head(artifact, projection)
            self.cell_heads[cell] = artifact.copy()

    def run(self, requests):
        if not isinstance(requests, (tuple, list)) or not 1 <= len(requests) <= MAX_BATCH:
            raise ValueError("unsupported pipeline batch size")
        seen = set()
        # Complete preflight before doing expensive Encoder work.
        for request in requests:
            request.validate()
            if request.request_id in seen or request.cell_id not in self.cell_heads:
                raise ValueError("duplicate/unknown Cell request")
            seen.add(request.request_id)
            validate_head(self.cell_heads[request.cell_id], self.projection)
        scoped = {(r.scope_digest, r.generation, r.revocation_frontier_digest) for r in requests}
        if len(scoped) != 1:
            raise ValueError("mixed runtime fence in pipeline batch")

        result = self.encoder_projector.run(requests)
        if len(result.refs) != len(requests):
            raise ValueError("encoder/projector returned incomplete batch")
        started = time.perf_counter_ns()
        outputs = []
        for request, ref in zip(requests, result.refs):
            artifact = self.cell_heads[request.cell_id]
            if (ref.request_id != request.request_id or ref.scope_digest != request.scope_digest or
                    ref.generation != request.generation or
                    ref.revocation_frontier_digest != request.revocation_frontier_digest or
                    ref.projection_digest != self.projection.digest or
                    len(ref.vector_q24) != artifact["input_width"]):
                raise ValueError("stale/mismatched bound projection receipt")
            logits = native_logits(artifact, [x / Q for x in ref.vector_q24])
            if len(logits) != artifact["output_width"] or any(not math.isfinite(x) for x in logits):
                raise ValueError("invalid Q24 Head output")
            q24 = tuple(round(x * Q) for x in logits)
            if any(abs(x) > 8 * Q for x in q24):
                raise ValueError("out-of-bounds Head output")
            raw = bytearray(b"hepta.stem.shadow-head-output.v1")
            for digest in (ref.projected_input_digest, artifact["head_digest"],
                           artifact["weights_digest"]):
                raw.extend(bytes.fromhex(digest))
            for value in q24:
                raw.extend(value.to_bytes(8, "big", signed=True))
            outputs.append(ShadowHeadResult(
                request_id=request.request_id, cell_id=request.cell_id,
                source_feature_digest=ref.source_feature_digest,
                projected_input_digest=ref.projected_input_digest,
                projection_digest=ref.projection_digest,
                head_digest=artifact["head_digest"],
                head_weights_digest=artifact["weights_digest"],
                logits_q24=q24, output_digest=hashlib.sha256(raw).hexdigest(),
            ))
        return ShadowPipelineObservation(
            results=tuple(outputs),
            encoder_backend_calls=result.encoder_observation.backend_calls,
            distinct_inputs=result.encoder_observation.distinct_inputs,
            encoder_cache_hits=result.encoder_observation.cache_hits,
            projection_calls=result.projection_calls,
            projection_cache_hits=result.projection_cache_hits,
            head_elapsed_ns=time.perf_counter_ns() - started,
            source_is_simulated=result.encoder_observation.simulated,
        )
