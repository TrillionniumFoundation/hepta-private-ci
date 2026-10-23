"""Exact historical-feature custody, not a signature or a fresh-extraction admission gate."""
import hashlib
import json
from pathlib import Path

import numpy as np

PLAN_SHA256 = '48ff3c003067370449254daefcf465c4960fbc01a39dae5b83d98123d3aec55c'
OBSERVED_EXTRACTION_SHA256 = '1bd5364c1851c238f4c2cb22c12bba5baa08019f763c86b14ff9874f5456e248'
SOURCE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def checked_arrays(path, expected):
    """Compare actual float32 tensor bytes, not only editable receipt assertions."""
    result = {}
    with np.load(path, allow_pickle=False) as archive:
        require(set(archive.files) == set(expected['splits']), 'Feature split inventory mismatch')
        for split, identity in expected['splits'].items():
            a = archive[split]
            require(a.dtype == np.dtype('float32'), f'{split}: feature dtype mismatch')
            require(a.shape == (identity['rows'], 640), f'{split}: feature shape mismatch')
            require(np.isfinite(a).all(), f'{split}: nonfinite feature')
            require(np.allclose(np.linalg.norm(a, axis=1), 1, atol=1e-5),
                    f'{split}: nonunit feature')
            require(hashlib.sha256(a.tobytes(order='C')).hexdigest() == identity['feature_sha256'],
                    f'{split}: frozen feature tensor mismatch')
            result[split] = np.asarray(a, dtype=np.float64)
    return result


def validate_inputs(folder, source=SOURCE):
    folder, source = Path(folder), Path(source)
    require(digest(folder/'plan.json') == PLAN_SHA256, 'Frozen plan mismatch')
    plan = json.loads((folder/'plan.json').read_text())
    require(digest(folder/'rows.json') == plan['rows_sha256'], 'Frozen row manifest mismatch')
    rows = json.loads((folder/'rows.json').read_text())
    anchor = source/'observed/extraction.json'
    require(digest(anchor) == OBSERVED_EXTRACTION_SHA256, 'Observed extraction anchor mismatch')
    expected = json.loads(anchor.read_text())
    actual = json.loads((folder/'extraction.json').read_text())
    require(actual.get('plan_sha256') == PLAN_SHA256, 'Receipt plan mismatch')
    require(actual.get('rows_sha256') == plan['rows_sha256'], 'Receipt row manifest mismatch')
    # Metadata comparisons do not authenticate a run. Actual tensor hashes below
    # independently anchor this exact historical replay to the reviewed arrays.
    for key in ['snapshot_inventory', 'snapshot_sha256', 'guard_sha256',
                'package_versions', 'splits', 'snapshots', 'native_pooling_parity_max_abs']:
        require(canonical(actual.get(key)) == canonical(expected[key]),
                f'Receipt frozen identity mismatch: {key}')
    allowed_drivers = {digest(source/'extract.py'), digest(source/'observed/source/extract.py')}
    require(actual.get('driver_sha256') in allowed_drivers, 'Unrecognized extraction driver')
    require(digest(folder/'features.npz') == actual.get('features_file_sha256'),
            'Feature archive receipt mismatch')
    arrays = checked_arrays(folder/'features.npz', expected)
    return plan, rows, actual, arrays
