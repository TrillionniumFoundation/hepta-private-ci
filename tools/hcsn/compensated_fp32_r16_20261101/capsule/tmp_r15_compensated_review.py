"""Independent financial identities and dtype instrumentation; no candidate edits."""
from collections import Counter
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time

import numpy as np

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate-root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
ROOT = arguments.candidate_root.resolve()
if arguments.output.exists():
    raise ValueError('Review evidence is create-only')
sys.path.insert(0, str(ROOT))
kernel = importlib.import_module('compensated_kernel')
fp = importlib.import_module('float32_pair')
source_files = ['compensated_kernel.py', 'float32_pair.py', 'frozen_kernel.py']
before = {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in source_files}
counts = Counter()
constant_inputs = set()
original_init = fp.Pair.__init__


def guarded_init(self, value, low=None):
    counts['pair_constructions'] += 1
    if not isinstance(value, (fp.Pair, np.ndarray, np.float32)) and low is None:
        constant_inputs.add((type(value).__name__, str(value)))
    original_init(self, value, low)
    for component in (self.hi, self.lo):
        if component.dtype != np.float32:
            raise AssertionError('Intermediate Pair storage is not FP32')


fp.Pair.__init__ = guarded_init
for name in ['two_sum', 'two_product']:
    original = getattr(fp, name)

    def guarded(a, b, original=original, name=name):
        counts[name] += 1
        assert np.asarray(a).dtype == np.float32
        assert np.asarray(b).dtype == np.float32
        result = original(a, b)
        assert all(np.asarray(x).dtype == np.float32 for x in result)
        return result

    setattr(fp, name, guarded)


def scaled(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return float(np.max(np.abs(a - b) / np.maximum(1, np.abs(b))))


started = time.perf_counter()
theta = np.array([.08, .02, .23, .6, .27, .01, 1., 4., 40.], dtype=np.float32)
model = kernel.build(theta)
base_y, base_j = model.state(np.float32(50), 'asset')
homogeneity = []
degree = np.array([1, 1, 0, 0, 1], dtype=np.float64)
for k in [.5, 2.]:
    scaled_theta = theta.copy()
    scaled_theta[[7, 8]] *= np.float32(k)
    y, j = kernel.evaluate(scaled_theta, np.float32(50 * k), 'asset')
    expected_y = base_y.astype(np.float64) * k ** degree
    expected_j = base_j.astype(np.float64) * (k ** degree)[:, None]
    expected_j[:, [7, 8, 9]] /= k
    homogeneity.append({'scale': k, 'value_error': scaled(y, expected_y),
                        'jacobian_error': scaled(j, expected_j)})

boundary_y, boundary_j = model.state(np.float32(0), 'log_distance')
b = float(boundary_y[0])
alpha, maturity = float(theta[3]), float(theta[6])
recovery_j = alpha / maturity * boundary_j[0].astype(np.float64)
recovery_j[3] += b / maturity
recovery_j[6] -= alpha * b / maturity ** 2
boundary = {
    'equity': float(boundary_y[1]),
    'equity_jacobian_max': float(np.abs(boundary_j[1]).max()),
    'F_G': boundary_y[2:4].tolist(),
    'F_G_parameter_jacobian_max': float(np.abs(boundary_j[2:4, :9]).max()),
    'right_risk_state_derivatives': boundary_j[2:4, 9].tolist(),
    'recovery_value_error': scaled(boundary_y[4], alpha * b / maturity),
    'recovery_parameter_jacobian_error': scaled(boundary_j[4, :9], recovery_j[:9]),
    'right_debt_state_derivative': float(boundary_j[4, 9]),
}
default_y, default_j = model.state(np.float32(.99 * b), 'asset')
default = {
    'equity_F_G': default_y[1:4].tolist(),
    'all_state_jacobian_max': float(np.abs(default_j[:, 9]).max()),
    'equity_F_G_jacobian_max': float(np.abs(default_j[1:4]).max()),
    'recovery_value_error': scaled(default_y[4], alpha * b / maturity),
    'recovery_jacobian_error': scaled(default_j[4], recovery_j),
}

asset = np.float32(50)
x = np.float32(np.log(float(asset) / float(model.b.v.hi + model.b.v.lo)))
yx, jx = model.state(x, 'log_distance')
expected_asset_j = jx.astype(np.float64)
expected_asset_j[:, :9] -= jx[:, 9, None].astype(np.float64) * boundary_j[0, :9] / b
expected_asset_j[:, 9] = jx[:, 9] / float(asset)
coordinate_chain = {'value_error': scaled(base_y, yx),
                    'jacobian_error': scaled(base_j, expected_asset_j),
                    'qualification': 'Coordinates are separately rounded to FP32, so this is a tolerance check, not bitwise equality.'}

with np.errstate(all='ignore'):
    zero_sqrt = fp.sqrt(fp.Pair(np.float32(0)))
    overflow_product = fp.Pair(np.float32(1e35)) * fp.Pair(np.float32(1e-10))
edge_limits = {
    'sqrt_zero_input': 0.0,
    'sqrt_zero_expected': 0.0,
    'sqrt_zero_finite': bool(np.isfinite(zero_sqrt.hi) & np.isfinite(zero_sqrt.lo)),
    'sqrt_zero_observed_words': [str(zero_sqrt.hi), str(zero_sqrt.lo)],
    'product_inputs_as_fp32': [float(np.float32(1e35)), float(np.float32(1e-10))],
    'product_expected_representable_as_fp32': bool(np.isfinite(np.float32(1e35) * np.float32(1e-10))),
    'finite_product_with_splitter_overflow': bool(np.isfinite(overflow_product.hi) & np.isfinite(overflow_product.lo)),
    'product_observed_words': [str(overflow_product.hi), str(overflow_product.lo)],
    'scope': 'Outside the tested financial path; these disprove a generic all-normal-FP32-range primitive guarantee, not the frozen development-grid result.'
}

result = {
    'schema': 'hcsn-compensated-independent-invariants-v2',
    'review_test_status': 'Post-development independent review witnesses, not preregistered holdout points.',
    'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'source_sha256': before,
    'dtype_instrumentation': dict(counts),
    'non_fp32_pair_input_constants': sorted(constant_inputs),
    'homogeneity': homogeneity,
    'value_matching_and_smooth_pasting': boundary,
    'default_extension': default,
    'default_seam': {
        'equity_smooth_pasting': 'Equity value and its state derivative vanish at the boundary.',
        'risk_and_debt_not_globally_C1': 'Default-region state derivatives are zero; continuation-side F, G and debt slopes are nonzero.',
        'right_risk_asset_derivatives': (boundary_j[2:4, 9] / b).tolist(),
        'right_debt_asset_derivative': float(boundary_j[4, 9] / b),
    },
    'coordinate_chain': coordinate_chain,
    'primitive_range_limits': edge_limits,
    'check_seconds': time.perf_counter() - started,
    'not_a_performance_benchmark': True,
}
assert before == {n: hashlib.sha256((ROOT / n).read_bytes()).hexdigest() for n in source_files}
assert all(r['value_error'] < 1e-6 and r['jacobian_error'] < 2e-5 for r in homogeneity)
assert boundary['equity'] == 0 and boundary['equity_jacobian_max'] == 0
assert boundary['F_G'] == [1., 1.] and boundary['recovery_parameter_jacobian_error'] < 2e-5
assert default['equity_F_G'] == [0., 1., 1.] and default['all_state_jacobian_max'] == 0
assert coordinate_chain['jacobian_error'] < 2e-5
with arguments.output.open('x') as handle:
    json.dump(result, handle, indent=2, allow_nan=False)
    handle.write('\n')
print(json.dumps({k: v for k, v in result.items() if k != 'non_fp32_pair_input_constants'}, indent=2))
