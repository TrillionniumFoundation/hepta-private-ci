"""Read-only Torch affine-Head -> compact native Q24 candidate exporter.

No Encoder execution, signed artifact, authority receipt, or production selection.
Only calibration data can drive the explicit post-training parity check.
"""

import hashlib
import json
import math
from pathlib import Path

Q24 = 1 << 24
MAX_ABS = 8 * Q24
MAX_WIDTH = 512
SUPPORTED = {'linear', 'film', 'rank8', 'rank16'}


def _q24(value):
    number = float(value)
    if not math.isfinite(number) or abs(number) > 8:
        raise ValueError('Q24 scalar outside representable [-8, 8] range')
    integer = round(number * Q24)  # ties to even
    if abs(integer) > MAX_ABS:
        raise ValueError('Q24 scalar rounds outside range')
    return integer


def _round_q48(value):
    quotient, remainder = divmod(value, Q24)
    if remainder * 2 > Q24 or (remainder * 2 == Q24 and quotient % 2):
        quotient += 1
    if abs(quotient) > MAX_ABS:
        raise ValueError('Q24 inference output outside range')
    return quotient


def _tensor_hash(dim_in, dim_out, drive, pred, gate, db, pb, gb):
    h = hashlib.sha256(b'hepta.cpu-gated-head.v1')
    h.update(dim_in.to_bytes(8, 'big'))
    h.update(dim_out.to_bytes(8, 'big'))
    for tensor in (drive, pred, gate, db, pb, gb):
        h.update(len(tensor).to_bytes(8, 'big'))
        for item in tensor:
            h.update(int(item).to_bytes(8, 'big', signed=True))
    return h.hexdigest()


def _bundle_hash(encoder_digest, head_hash):
    if len(encoder_digest) != 64 or any(c not in '0123456789abcdef' for c in encoder_digest):
        raise ValueError('must bind exact 64-hex encoder digest')
    h = hashlib.sha256(b'hepta.cpu-gated-bundle.v1')
    h.update(encoder_digest.encode('ascii'))
    h.update((1).to_bytes(8, 'big'))
    h.update(head_hash.encode('ascii'))
    return h.hexdigest()


def extract_affine(torch, head, kind):
    """Fold only *mathematically affine* Head families, no nonlinear shortcuts."""
    if kind not in SUPPORTED:
        raise ValueError('nonaffine Head needs a separately implemented native operator')
    head.eval()
    with torch.no_grad():
        if kind == 'linear':
            w, b = head.weight.detach().float(), head.bias.detach().float()
        elif kind == 'film':
            w0 = head.readout.weight.detach().float()
            b = head.readout.bias.detach().float() + w0 @ head.beta.detach().float()
            w = w0 * head.gamma.detach().float().unsqueeze(0)
        else:
            w = (head[1].weight.detach().float() @ head[0].weight.detach().float())
            b = head[1].bias.detach().float()
    return w.cpu(), b.cpu()


def _native_logits(artifact, input_vector):
    dim_in = artifact['input_width']
    dim_out = artifact['output_width']
    if len(input_vector) != dim_in:
        raise ValueError('native feature shape mismatch')
    features = [_q24(x) for x in input_vector]
    weight = artifact['drive_weights_q24']
    bias = artifact['drive_bias_q24']
    out = []
    for row in range(dim_out):
        value = bias[row] * Q24
        start = row * dim_in
        for i, feature in enumerate(features):
            value += feature * weight[start + i]
        out.append(_round_q48(value) / Q24)
    return out


def build_q24_head_candidate(torch, head, kind, encoder_digest, calibration_features,
                             *, max_calibration_abs_error=0.02):
    """Build a non-authorizing artifact; validate parity on calibration ONLY."""
    weights, bias = extract_affine(torch, head, kind)
    if weights.ndim != 2 or bias.shape != (weights.shape[0],):
        raise ValueError('affine Head must have [classes,input] weight and [classes] bias')
    out_width, in_width = weights.shape
    if not 1 <= in_width <= MAX_WIDTH or not 1 <= out_width <= MAX_WIDTH:
        raise ValueError('native neuron feature contract is limited to 512; projection required')
    drive = [_q24(x) for x in weights.reshape(-1).tolist()]
    db = [_q24(x) for x in bias.tolist()]
    pred, gate = [], []  # canonical zero matrices, no dense dummy storage
    pb, gb = [0] * out_width, [Q24] * out_width
    digest = _tensor_hash(in_width, out_width, drive, pred, gate, db, pb, gb)
    art = {
        'schema': 'hepta.stem.q24-cpu-head-candidate.v1',
        'shadow_only': True,
        'production_authorized': False,
        'numeric_profile': 'signed-Q24-hard-sigmoid-constant-1-gate',
        'source_head_kind': kind,
        'encoder_digest': encoder_digest,
        'input_width': in_width,
        'output_width': out_width,
        'drive_weights_q24': drive,
        'prediction_weights_q24': pred,
        'gate_weights_q24': gate,
        'drive_bias_q24': db,
        'prediction_bias_q24': pb,
        'gate_bias_q24': gb,
        'head_digest': digest,
        'weights_digest': _bundle_hash(encoder_digest, digest),
        'native_stored_coefficients': len(drive) + len(db) + len(pb) + len(gb),
        'native_stored_tensor_bytes': 8 * (len(drive) + len(db) + len(pb) + len(gb)),
    }
    if art['native_stored_coefficients'] <= 0:
        raise ValueError('empty native head')
    if not calibration_features:
        raise ValueError('disjoint calibration vectors are mandatory for Q24 parity')
    error_max = 0.0
    margins_wrong = 0
    with torch.inference_mode():
        for feature in calibration_features:
            expected = head(feature.reshape(1, -1)).flatten().cpu().tolist()
            actual = _native_logits(art, feature.flatten().cpu().tolist())
            error_max = max(error_max, *(abs(a - b) for a, b in zip(expected, actual)))
            if max(range(out_width), key=lambda j: expected[j]) != max(range(out_width), key=lambda j: actual[j]):
                margins_wrong += 1
    if not math.isfinite(error_max) or error_max > max_calibration_abs_error or margins_wrong:
        raise ValueError('Q24 calibration parity failed; candidate must remain unexported')
    art['calibration_vector_count'] = len(calibration_features)
    art['calibration_max_abs_logit_error'] = error_max
    art['calibration_argmax_mismatch_count'] = 0
    art['parity_limit'] = max_calibration_abs_error
    return art


def write_q24_head_candidate(path, artifact):
    """Append-only local output; filesystem artifact is not signed or authoritative."""
    p = Path(path)
    content = json.dumps(artifact, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
    with p.open('x', encoding='utf-8') as f:
        f.write(content)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()
