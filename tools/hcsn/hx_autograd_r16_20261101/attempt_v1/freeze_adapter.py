"""Freeze functional inputs, thresholds and source before running any fixture."""
from datetime import datetime, timezone
import json
import platform

import numpy as np
import torch

from adapter_common import ROOT, sha, write
from hx_autograd import FROZEN_PROTOCOL_SHA256


def run():
    baseline = np.asarray([.08, .02, .23, .6, .27, .01, 1., 6.39, 61.68], dtype=np.float32)
    short = baseline.copy(); short[6] = np.float32(.1)
    specifications = [('baseline_continuation_asset', baseline, 'asset', 100.),
                      ('baseline_default_asset', baseline, 'asset', 40.),
                      ('baseline_continuation_log', baseline, 'log_distance', .1),
                      ('baseline_boundary_right', baseline, 'log_distance', 0.),
                      ('short_continuation_asset', short, 'asset', 100.),
                      ('short_boundary_right', short, 'log_distance', 0.)]
    rng = np.random.default_rng(2026110137)
    mixed = rng.normal(size=(4, 10)); mixed /= np.max(abs(mixed), axis=1, keepdims=True)
    cases = []
    for name, theta, coordinate, state in specifications:
        directions = np.vstack((np.eye(10), mixed.copy()))
        if coordinate == 'log_distance' and state == 0:
            directions[10:, 9] = 0.
        cases.append({'id': name, 'coordinate': coordinate, 'packed': np.r_[theta, np.float32(state)].astype(np.float32).tolist(), 'directions': directions.tolist()})
    fixture_path = ROOT/'ADAPTER_FIXTURES.json'
    write(fixture_path, {'schema': 'hcsn.hx-autograd-fixtures.v1', 'direction_seed': 2026110137,
                         'scope': 'Fixed functional integration fixtures in previously known financial cases; not a new financial holdout', 'cases': cases})
    names = ('hx_autograd.py', 'adapter_common.py', 'audit_gradients.py', 'training_smoke.py', 'freeze_adapter.py')
    protocol = {
        'schema': 'hcsn.hx-autograd-protocol.v1', 'frozen_utc': datetime.now(timezone.utc).isoformat(),
        'financial_protocol_sha256': FROZEN_PROTOCOL_SHA256,
        'financial_binary_sha256': 'a96fbe8ee36be2fdaa2a5894462f415f9724acf199ae31745c471092c26f6615',
        'source_sha256': {name: sha(ROOT/name) for name in names}, 'fixture_sha256': sha(fixture_path),
        'input_contract': 'Only CPU torch.float32, packed[...,10]=nine financial parameters plus state. No float64 input downcast. Positive V for asset; independent x>=0 for log_distance.',
        'output_contract': 'Five original financial outputs float64; features append new R=1-(1-F)^2 and information-preserving x. Financial evaluation always uses frozen FP64 mode.',
        'gradient_contract': 'First-order VJP of continuous real formulas evaluated at represented FP32 inputs; float64 contraction, float32 leaf gradient. Not derivative of the rounding map. No double backward/JVP/torch.compile/GPU support claimed.',
        'boundary_contract': 'Asset V<=b uses original default-branch derivatives; positive V remains visible in x. Original F/G are not globally C1. Log x=0 uses a continuation-side right derivative; R is an additional C1 observable, not a C2 force.',
        'finite_difference_steps': [1e-3, 5e-4],
        'finite_difference_rule': 'Scale each direction coordinate by max(.01,abs(input)); quantize both endpoints to FP32, use actual effective central direction and record midpoint offset. Boundary state basis uses nonuniform-node three-point right derivative; all asset endpoints must remain on base branch. No financial MP80 oracle imported.',
        'gates': {'feature_value_scaled': 1e-12, 'chain_jacobian_scaled': 1e-6, 'directional_difference_scaled': 5e-4},
        'gate_scope': 'Integration finite-step checks only; these thresholds do not modify or replace the frozen R16 financial values/Jacobian gates.',
        'training_smoke': {'seed': 2026110141, 'batch_size': 32, 'steps': 80, 'learning_rate': .02,
                           'optimizer': 'Adam', 'pass_rule': 'All gradients/parameters finite; all named parameter tensors update; final loss below initial loss. Same synthetic training grid only.'},
        'retention': 'Keep every directional record and failure. No source or threshold edits after opening without a new version. Fixed integration checks do not establish generalization.',
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'torch': torch.__version__, 'cuda_available': torch.cuda.is_available()},
        'supporting_docs': ['https://docs.pytorch.org/docs/2.15/notes/extending.html'],
        'forbidden_claims': ['ordinary FP32 financial qualification', 'original F/G are C1', 'smooth observation proves C2 force', 'higher-order BP', 'GPU or model/task superiority'],
    }
    receipt = write(ROOT/'ADAPTER_PROTOCOL.json', protocol)
    print(json.dumps({'protocol': receipt, 'fixture_sha256': sha(fixture_path), 'numerical_fixture_calls': 0}, indent=2))


if __name__ == '__main__':
    run()
