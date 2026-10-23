"""Check saved v4 support/plan metadata from the frozen integer-seed formulas."""

import hashlib
from itertools import product

import numpy as np


def audit_metadata(tree, policy, study_seed):
    """Reject changed banks even when separately saved tree tensors are correct."""
    if type(study_seed) is not int or not 0 <= study_seed < 2**20:
        raise AssertionError('registered integer study seed')

    def vector(key):
        raw = np.random.default_rng(key).normal(size=64)
        return (raw * (.8 / np.sqrt(np.mean(raw * raw)))).astype(np.float32)

    initial = np.stack([vector(4300000 + 1000 * study_seed + 10 * m) for m in range(4)])
    banks = np.empty((2, 4, 3, 64), dtype=np.float32)
    for step, modality in product(range(2), range(4)):
        positive = vector(4600000 + 1000 * study_seed + 100 * (step + 1) + modality)
        banks[step, modality] = np.stack((-positive, np.zeros(64, dtype=np.float32), positive))
    coefficients = np.asarray([1., .75, .5, .25], dtype=np.float32)
    modes = np.stack([np.stack([initial[m] * coefficients[(m - j) % 4]
                               for m in range(4)]) for j in range(4)])
    plans = [()] + [(m,) for m in range(4)] + list(product(range(4), repeat=2))
    expected_tree = {'initial_directions': initial, 'future_banks': banks, 'initial_modes': modes}
    expected_policy = {'plan_lengths': np.array([len(plan) for plan in plans], dtype=np.int64),
                       'plans': np.array([list(plan) + [-1] * (2 - len(plan)) for plan in plans],
                                         dtype=np.int64)}
    digests = {}
    for source, expected in ((tree, expected_tree), (policy, expected_policy)):
        for key, reference in expected.items():
            actual = np.asarray(source[key])
            if actual.dtype != reference.dtype or not np.array_equal(actual, reference):
                raise AssertionError(('independent metadata formula', key))
            digests[key] = hashlib.sha256(actual.tobytes(order='C')).hexdigest()
    minimum_separation = min(float(np.max(np.abs(modes[j, a] - modes[j, b])))
                             for j in range(4) for a in range(4) for b in range(a + 1, 4))
    if minimum_separation <= 0:
        raise AssertionError('initial four modality disturbances must be distinct')
    return {'passed': True, 'metadata_arrays': 5, 'metadata_tensor_sha256': digests,
            'minimum_initial_modality_linf_separation': minimum_separation,
            'plans_including_repeated_modality': len(plans), 'future_global_indices': [1, 2]}
