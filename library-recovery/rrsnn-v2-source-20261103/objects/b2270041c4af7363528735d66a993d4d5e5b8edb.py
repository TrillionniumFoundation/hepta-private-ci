"""A scoped factory for shared actual initial states within four-condition groups.

Only initialization is changed. Each group draws one H-vector from the original
reset distribution, then copies it to its four conditions. Subsequent draws
are ordinary independent draws of the frozen sampler, not common-noise copies.
This process-local context manager is intentionally used in a single thread.
"""
from contextlib import contextmanager
import hashlib
import json

import numpy as np
import torch

from .. import sampled_policy

OriginalRollout = sampled_policy.SampledDensityRollout


def array_digest(array):
    value = np.ascontiguousarray(array)
    header = json.dumps({'dtype': str(value.dtype), 'shape': value.shape}, sort_keys=True).encode()
    return hashlib.sha256(header+b'\0'+value.tobytes()).hexdigest()


class SharedInitialRollout(OriginalRollout):
    def __init__(self, encoder, batch_size, backend='ctmc', seed=101, record_spikes=True):
        if backend != 'ctmc' or batch_size <= 0 or batch_size % 4:
            raise ValueError('This profile requires complete four-condition CTMC groups')
        groups = batch_size//4
        # Exactly one correctly distributed initial draw per group/component.
        super().__init__(encoder, groups, backend, seed, record_spikes)
        for name in ('indices', 'time', 'total_counts', 'has_observed'):
            setattr(self, name, np.repeat(getattr(self, name), 4, axis=0))
        for name in ('context', 'drift', 'boundary', 'initial_resource'):
            value = getattr(self.state, name)
            if value is not None:
                setattr(self.state, name, value.repeat_interleave(4, dim=0))
        self.batch = batch_size
        fields = {name: getattr(self, name) for name in
                  ('indices', 'time', 'total_counts', 'has_observed')}
        for name in ('context', 'drift', 'boundary', 'initial_resource'):
            value = getattr(self.state, name)
            if value is not None:
                fields[name] = value.detach().numpy()
        nodes = self.operator.nodes(self.state.boundary).detach().numpy()
        evidence = np.take_along_axis(nodes, self.indices[..., None], axis=-1)[..., 0]
        fields['physical_evidence'] = evidence
        checks = {}
        for name, value in fields.items():
            grouped = value.reshape(groups, 4, *value.shape[1:])
            checks[name] = all(grouped[:, i].tobytes() == grouped[:, 0].tobytes() for i in range(1, 4))
        if not all(checks.values()):
            raise AssertionError('Four conditions do not have exactly equal actual initial states')
        if not (np.all(self.total_counts == 0) and np.all(self.time == 0) and not self.has_observed.any()):
            raise AssertionError('Initial state was captured after execution began')
        initial = encoder.initial_state(1, device='cpu', dtype=self.dtype)
        self.strict_initial_receipt = {
            'schema': 'rrsnn.strict-initial-state-receipt.v1',
            'groups': groups, 'conditions_per_group': 4, 'components': self.hidden,
            'captured_before_first_observation': True, 'within_group_bitwise_equal': checks,
            'group_initial_indices': self.indices[::4].tolist(),
            'group_initial_physical_evidence': evidence[::4].tolist(),
            'reset_law_probabilities': initial.probability[0].detach().numpy().tolist(),
            'initial_buffer_sha256': {name: array_digest(value) for name, value in fields.items()},
            'initial_resource_is_none': self.state.initial_resource is None,
            'persistent_exponential_spike_trace_present': False,
            'trace_note': 'This main candidate has deterministic context and counts, not a persistent exponential spike-trace buffer. No artificial trace buffer was added.',
            'sampling_rule': 'One original reset-law H-vector per group, copied to its four conditions; original sampler then continues from the RNG state after those group draws.',
            'common_noise_after_initialization': False,
        }


@contextmanager
def use_shared_initial_factory():
    if sampled_policy.SampledDensityRollout is not OriginalRollout:
        raise RuntimeError('A conflicting process-local sampler patch is active')
    instances = []

    class CapturedRollout(SharedInitialRollout):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    sampled_policy.SampledDensityRollout = CapturedRollout
    try:
        yield instances
    finally:
        sampled_policy.SampledDensityRollout = OriginalRollout
