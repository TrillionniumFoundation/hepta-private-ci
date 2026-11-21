"""Portable, create-only research records and exact F64 readout contracts."""
from pathlib import Path
from fractions import Fraction
import gzip
import hashlib
import json
import math
import struct
import numpy as np

FITS = (11, 23, 37, 53, 71)
HEAD_IDS = ('Q_1', 'B_1', 'B_2', 'G_1', 'G_2', 'T_256', 'T_1024')
FAMILIES = {'Q': ('Q_1',), 'B': ('B_1', 'B_2'),
            'G': ('G_1', 'G_2'), 'T': ('T_256', 'T_1024')}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path):
    path = Path(path)
    raw = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(raw), 'sha256': digest(raw)}


def verify(expected):
    observed = pin(expected['path'])
    if any(observed[key] != expected[key] for key in ('bytes', 'sha256')):
        raise ValueError('source pin changed: ' + expected['path'])
    return observed


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix == '.gz':
        raw = gzip.decompress(raw)
    def invalid(value):
        raise ValueError('nonfinite JSON: ' + value)
    return json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid)


def serializable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [serializable(v) for v in value]
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (canonical(serializable(value)) + '\n').encode()
    if path.suffix == '.gz':
        raw = gzip.compress(raw, mtime=0)
    with path.open('xb') as handle:
        handle.write(raw)
    return pin(path)


def save_arrays(path, **arrays):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as handle:
        np.savez_compressed(handle, **arrays)
    return pin(path)


def head(model):
    return np.column_stack((np.asarray(model['network']['w2'], dtype=np.float64),
                            np.asarray(model['network']['b2'], dtype=np.float64)))


def flattened_readout(rows):
    return np.r_[rows[:, :48].reshape(-1), rows[:, 48]]


def f64_bits(value):
    return struct.pack('>d', float(value)).hex()


def exact_radius(anchor, candidate=None):
    """All squared numbers below are exact rationals, not float tolerances."""
    original = np.asarray(anchor, dtype=np.float64)
    if original.shape != (4, 49) or not np.isfinite(original).all():
        raise ValueError('finite original 4x49 readout required')
    q_squared = sum((Fraction.from_float(float(v)) ** 2
                     for v in original[:3].reshape(-1)), Fraction(0))
    squared = Fraction(0)
    if candidate is not None:
        candidate = np.asarray(candidate, dtype=np.float64)
        if original.shape != (4, 49) or candidate.shape != (4, 49):
            raise ValueError('readout shape')
        if not np.isfinite(candidate).all():
            raise ValueError('nonfinite candidate')
        squared = sum(((Fraction.from_float(float(b)) - Fraction.from_float(float(a))) ** 2
                       for a, b in zip(original.flat, candidate.flat)), Fraction(0))
    scale = 1 << 2148
    q_units, delta_units = q_squared * scale, squared * scale
    if q_units.denominator != 1 or delta_units.denominator != 1:
        raise ArithmeticError('F64 dyadic unit mismatch')
    return {'within_shared_ball': 4 * squared <= q_squared,
            'delta_squared_units_hex': format(delta_units.numerator, 'x'),
            'anchor_q147_squared_units_hex': format(q_units.numerator, 'x'),
            'radius_squared': {'numerator': str(q_squared.numerator),
                               'denominator': str(4 * q_squared.denominator)},
            'numeric_radius': math.sqrt(float(q_squared / 4)),
            'numeric_delta_norm': math.sqrt(float(squared))}


def model_with_head(base, rows, family):
    # JSON is the source format; a new independent object never mutates the anchor.
    if family not in ('Q', 'B', 'G', 'T'):
        raise ValueError('unknown editable parameter family')
    candidate = json.loads(canonical(base))
    original = head(base)
    rows = np.asarray(rows, dtype=np.float64)
    excluded = (3,) if family == 'Q' else ((0, 1, 2) if family == 'B' else ())
    if excluded and rows[list(excluded)].tobytes() != original[list(excluded)].tobytes():
        raise ArithmeticError('edit escaped row mask')
    norm = exact_radius(original, rows)
    if not norm['within_shared_ball']:
        raise ArithmeticError('saved F64 coordinates exceed exact shared radius')
    candidate['network']['w2'] = rows[:, :48].tolist()
    candidate['network']['b2'] = rows[:, 48].tolist()
    protected = json.loads(canonical(candidate))
    protected['network']['w2'] = base['network']['w2']
    protected['network']['b2'] = base['network']['b2']
    if protected != base:
        raise ArithmeticError('protected model fields changed')
    return candidate, norm


def choose(values, names, tolerance=1e-12):
    """Deterministic KEEP-first complete-task selection; unknown is not success."""
    chosen = 'KEEP'
    best = values[chosen]
    if not math.isfinite(best):
        raise ValueError('nonfinite KEEP utility')
    for name in names:
        value = values.get(name)
        if value is not None and math.isfinite(value) and value > best + tolerance:
            chosen, best = name, value
    return chosen


def retention(candidate, original, optimum):
    candidate, original, optimum = map(float, (candidate, original, optimum))
    denominator = optimum - original
    return {'utility': candidate, 'original_utility': original, 'optimal_utility': optimum,
            'delta_original': candidate - original, 'optimal_regret': optimum - candidate,
            'absolute_retention_denominator': optimum,
            'absolute_retention': candidate / optimum if optimum > 1e-12 else None,
            'opportunity_denominator': denominator,
            'opportunity_recovery': (candidate - original) / denominator if denominator > 1e-12 else None}
