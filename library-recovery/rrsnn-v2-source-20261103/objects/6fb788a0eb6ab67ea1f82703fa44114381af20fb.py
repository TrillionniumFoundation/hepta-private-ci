"""Offline RR-SNN compatibility helpers, grounded in a frozen Hepta source SHA.

These helpers do not implement NeuronModelPort, issue LocalModelRuntimeReceiptV1,
publish a checkpoint, or activate a model. A ShadowProposal is deliberately a
different research schema. Hashes and input rules are transcribed from the exact
upstream runtime_types.rs / protocol.rs / identity.rs / digest.rs snapshots.
"""
import hashlib
import json
import math
import re
import struct

SOURCE_COMMIT = 'f8c9419df6ddeb36ff8b522a50219981fb8d9345'
SOURCE_REPOSITORY = 'TrillionniumFoundation/hepta-private-ci'
Q24 = 1 << 24
Q24_LIMIT = 8 * Q24
MAX_FEATURES = 512
MAX_PROTOCOL_BYTES = 262_144
ZERO = '0' * 64
TICK_KEYS = {
    'tickId', 'subjectId', 'logicalSequence', 'monotonicTimeMicros',
    'checkpointDigest', 'inputFeatureDigest', 'featureVectorQ24',
    'objectiveDigest', 'nduSnapshotDigest', 'bodyGeneration', 'modulatorDigest',
}
OPTIONAL_KEYS = {'bodyGeneration', 'modulatorDigest'}


def digest32(value, *, allow_zero=False):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('digest must be 64 lowercase hexadecimal characters')
    if not allow_zero and value == ZERO:
        raise ValueError('zero digest is not accepted here')
    return value


def stable_id(value):
    if not isinstance(value, str) or re.fullmatch('[A-Za-z0-9._:-]{1,128}', value) is None:
        raise ValueError('invalid stable-v1 identifier')
    return value


def uint64(value):
    if type(value) is not int or not 0 <= value <= (1 << 64) - 1:
        raise ValueError('u64 integer required')
    return value


def feature_digest_q24(values):
    """Exact upstream Q24 vector byte framing followed by SHA-256."""
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= MAX_FEATURES:
        raise ValueError('feature count outside 1..512')
    if any(type(v) is not int or not -Q24_LIMIT <= v <= Q24_LIMIT for v in values):
        raise ValueError('Q24 feature outside upstream [-8,8] bounds')
    framed = b'hepta.neuron.input-features.q24.v1' + struct.pack('>Q', len(values))
    framed += b''.join(struct.pack('>q', v) for v in values)
    return hashlib.sha256(framed).hexdigest()


def quantize_q24(values):
    """Explicit finite float -> Q24 conversion with ties to even, without clipping.

    This is a candidate input/output conversion. It does not change the upstream
    deterministic Q24 sparse mechanism, nor prove equivalence to its dynamics.
    """
    result = []
    for raw in values:
        if isinstance(raw, bool):
            raise ValueError('boolean is not a numerical feature')
        v = float(raw)
        if not math.isfinite(v) or not -8 <= v <= 8:
            raise ValueError('finite value in [-8,8] required; no clipping')
        result.append(round(v * Q24))
    if not result:
        raise ValueError('empty feature vector')
    return result


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def decode_tick_input(raw):
    """Strict offline decoder for observed NeuronTickInputV1 JSON semantics."""
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if not isinstance(raw, bytes) or len(raw) > MAX_PROTOCOL_BYTES:
        raise ValueError('invalid or oversized protocol payload')
    tick = json.loads(raw, object_pairs_hook=_unique_object)
    if not isinstance(tick, dict) or set(tick) - TICK_KEYS:
        raise ValueError('unknown critical field or non-object')
    if TICK_KEYS - OPTIONAL_KEYS - set(tick):
        raise ValueError('missing required field')
    for key in OPTIONAL_KEYS:
        tick.setdefault(key, None)
    stable_id(tick['tickId'])
    stable_id(tick['subjectId'])
    sequence = uint64(tick['logicalSequence'])
    if sequence == 0 or uint64(tick['monotonicTimeMicros']) == 0:
        raise ValueError('sequence and monotonic time must be positive')
    checkpoint = digest32(tick['checkpointDigest'], allow_zero=True)
    if (sequence == 1) != (checkpoint == ZERO):
        raise ValueError('genesis/non-genesis checkpoint mismatch')
    for key in ['inputFeatureDigest', 'objectiveDigest', 'nduSnapshotDigest']:
        digest32(tick[key])
    if feature_digest_q24(tick['featureVectorQ24']) != tick['inputFeatureDigest']:
        raise ValueError('FeatureDigestMismatch')
    if tick['bodyGeneration'] is not None:
        uint64(tick['bodyGeneration'])
    if tick['modulatorDigest'] is not None:
        digest32(tick['modulatorDigest'])
    return tick


def tick_semantic_digest(tick):
    """Exact runtime_types.rs input semantic framing; validation happens first."""
    tick = decode_tick_input(json.dumps(tick, separators=(',', ':')).encode())
    framed = bytearray(b'hepta.neuron.tick-input.v1')
    for name in ['tickId', 'subjectId']:
        raw = tick[name].encode()
        framed += struct.pack('>I', len(raw)) + raw
    framed += struct.pack('>QQ', tick['logicalSequence'], tick['monotonicTimeMicros'])
    for name in ['checkpointDigest', 'inputFeatureDigest', 'objectiveDigest', 'nduSnapshotDigest']:
        framed += bytes.fromhex(tick[name])
    body = tick['bodyGeneration']
    framed += b'\x00' if body is None else b'\x01' + struct.pack('>Q', body)
    modulator = tick['modulatorDigest']
    framed += b'\x00' if modulator is None else b'\x01' + bytes.fromhex(modulator)
    framed += b''.join(struct.pack('>q', v) for v in tick['featureVectorQ24'])
    return hashlib.sha256(framed).hexdigest()


def make_shadow_proposal(tick, candidate_values, candidate_artifact_sha256, *, output_width):
    """Bind an offline numeric candidate to an observed tick without product claims.

    A real host must separately obtain/verify a selected model receipt, calibration,
    configuration, checkpoint CAS and witness. This function intentionally cannot
    create those fields or return a NeuronModelOutputV1.
    """
    digest32(candidate_artifact_sha256)
    if type(output_width) is not int or not 5 <= output_width <= 256:
        raise ValueError('V1 sparse instance width must be in 5..256')
    qvalues = quantize_q24(candidate_values)
    if len(qvalues) != output_width:
        raise ValueError('candidate output width mismatch')
    source_input_digest = tick_semantic_digest(tick)
    proposal = {
        'schema': 'rrsnn.offline-shadow-proposal.v1',
        'sourceRepository': SOURCE_REPOSITORY,
        'sourceCommit': SOURCE_COMMIT,
        'sourceInputSemanticDigest': source_input_digest,
        'candidateArtifactSha256': candidate_artifact_sha256,
        'candidateValuesQ24': qvalues,
        'outputWidth': output_width,
        'authority': 'NONE',
        'officialRuntimeReceipt': None,
        'checkpointPublished': False,
        'productionActivationAllowed': False,
    }
    return proposal
