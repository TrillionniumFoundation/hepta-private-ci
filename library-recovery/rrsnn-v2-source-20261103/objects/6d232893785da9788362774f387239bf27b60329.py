"""Independent initialization-law and scoped-factory audit, using no holdout data."""
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from ...policy import Policy
from .. import sampled_policy
from .factory import OriginalRollout, SharedInitialRollout, use_shared_initial_factory

ROOT = Path(__file__).resolve().parent


def run_audit():
    torch.set_num_threads(1)
    torch.manual_seed(991201)
    model = Policy('rr_density').eval()
    groups = 4096
    rows = []
    # Independent reset law calculation: coordinates of zero reset on the grid.
    op = model.encoder.operator
    z = float(np.float32(np.float32(op.reset-op.lower_bound)/
              np.float32(model.encoder.fixed_boundary-op.lower_bound))*np.float32(op.grid_size))
    lo = int(np.floor(z));fraction = z-lo
    expected = np.zeros(op.state_size)
    expected[lo] += 1-fraction
    expected[min(lo+1, op.grid_size-1)] += fraction
    for seed in (991211, 991223, 991237, 991243):
        engine = SharedInitialRollout(model.encoder, groups*4, seed=seed, record_spikes=False)
        receipt = engine.strict_initial_receipt
        assert all(receipt['within_group_bitwise_equal'].values())
        marginal = engine.indices[::4]
        assert np.all(marginal[..., None] == engine.indices.reshape(groups,4,8).transpose(0,2,1))
        counts = np.bincount(marginal.reshape(-1), minlength=op.state_size)
        n = marginal.size  # Do not count the four deterministic copies as new samples.
        frequencies = counts/n
        supported = expected > 0
        assert np.all(counts[~supported] == 0)
        standard_error = np.sqrt(expected[supported]*(1-expected[supported])/n)
        z_score = (frequencies[supported]-expected[supported])/standard_error
        assert np.max(np.abs(z_score)) < 6
        actual_law = np.asarray(receipt['reset_law_probabilities'])
        assert np.allclose(actual_law, expected[None, :], rtol=0, atol=1e-12)
        assert engine.batch == groups*4 and engine.indices.shape == (groups*4,8)
        assert not np.shares_memory(engine.indices[0], engine.indices[1])
        rows.append({'seed':seed, 'independent_initial_vectors':groups,
                     'independent_scalar_draws':n, 'four_copies_not_counted_as_new_draws':True,
                     'observed_frequencies':frequencies.tolist(), 'supported_bin_z_scores':z_score.tolist(),
                     'all_actual_initial_fields_identical_within_groups':True})
    with use_shared_initial_factory() as instances:
        assert sampled_policy.SampledDensityRollout is not OriginalRollout
        sampled_policy.SampledDensityRollout(model.encoder, 4, seed=991251)
        assert len(instances) == 1
    assert sampled_policy.SampledDensityRollout is OriginalRollout
    report = {'schema':'rrsnn.strict-initial-law-audit.v1', 'all_passed':True,
              'uses_holdout_scenarios_or_metrics':False,
              'reset_law_derived_without_calling_operator_reset_distribution':expected.tolist(),
              'exact_marginal_argument':'Each condition is a deterministic copy of the one original reset-law group draw, so every condition retains the exact marginal law. Copies are dependent within group, and this dependence is deliberate.',
              'groups_per_audit_seed':groups, 'checks':rows,
              'context_patch_restored_after_exit':True,
              'post_initial_common_noise_claimed':False,
              'factory_sha256':hashlib.sha256((ROOT/'factory.py').read_bytes()).hexdigest()}
    (ROOT/'initialization_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
