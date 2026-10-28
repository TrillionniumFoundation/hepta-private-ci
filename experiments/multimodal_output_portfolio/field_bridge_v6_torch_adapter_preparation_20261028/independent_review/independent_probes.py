"""Tiny synthetic probes only; never imports scientific kernels or reads assets."""

import hashlib
import json
from pathlib import Path
import random
import sys
import time
from unittest.mock import patch

import numpy as np
import torch

ROOT = Path('/workspace/scratch/e8a4dc33549f/hepta')
DIRECTORY = ROOT / 'experiments/multimodal_output_portfolio/field_bridge_v6_torch_adapter_preparation_20261028'
sys.path.insert(0, str(ROOT))
from experiments.multimodal_output_portfolio.field_bridge_v6_torch_adapter_preparation_20261028 import adapter, tests

codec = adapter.codec


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def raw_native(value):
    if isinstance(value, torch.Tensor):
        return value.detach().numpy().copy()
    if isinstance(value, np.ndarray):
        return value.copy()
    if isinstance(value, dict):
        return {key: raw_native(item) for key, item in value.items()}
    if type(value) in (tuple, list):
        return type(value)(raw_native(item) for item in value)
    return value


def observation(a):
    tensors = {}
    for label, model in {'mutable_model': a.model, **a.references}.items():
        for name, value in list(model.named_parameters()) + list(model.named_buffers()):
            tensors[label + ':' + name] = {
                'bytes': raw_native(value), 'version': value._version,
                'object_id': id(value), 'storage_pointer': value.untyped_storage().data_ptr(),
                'requires_grad': value.requires_grad,
                'grad': None if value.grad is None else raw_native(value.grad),
            }
    return codec.digest({
        'tensors': tensors, 'optimizer': raw_native(a.optimizer.state_dict()),
        'optimizer_state_object_id': id(a.optimizer.state),
        'optimizer_groups_object_id': id(a.optimizer.param_groups),
        'torch_rng': raw_native(torch.get_rng_state()), 'python_rng': random.getstate(),
        'numpy_rng': raw_native(np.random.get_state()),
        'named_rng': {name: raw_native(adapter.generator_state(g, adapter.generator_kind(g))) for name, g in a.generators.items()},
    })


def rejected_before_apply(change, message_fragment):
    a, cursor, tape = tests.fixture()
    unused, raw, checksum = tests.seal(a, cursor, tape)
    handle = change(a)
    before = observation(a)
    with patch.object(a, '_apply', side_effect=AssertionError('Live apply must not be entered')) as apply:
        try:
            a.restore(raw, checksum, len(raw))
        except ValueError as error:
            assert message_fragment in str(error), str(error)
            detail = str(error)
        else:
            raise AssertionError('Unsupported target was accepted')
        assert apply.call_count == 0
    assert observation(a) == before
    if handle is not None:
        handle.remove()
    return {'rejected': True, 'reason': detail, 'apply_calls': 0, 'before_after_public_state_objects_versions_and_rng_equal': True, 'envelope_bytes': len(raw)}


def main():
    started = time.time_ns()
    sources_before = [identity(DIRECTORY / name) for name in ('adapter.py', 'tests.py')]
    checks = {}
    checks['parameter_backward_hook_preflight'] = rejected_before_apply(
        lambda a: a.model.p.register_hook(lambda gradient: gradient * 2), 'hooks')
    checks['parameter_post_accumulate_hook_preflight'] = rejected_before_apply(
        lambda a: a.model.p.register_post_accumulate_grad_hook(lambda parameter: None), 'hooks')

    def reference_alias(a):
        a.references['original_generator'].weight = torch.nn.Parameter(a.model.p.detach().reshape(1, 2), requires_grad=False)

    checks['mutable_to_immutable_reference_storage_alias'] = rejected_before_apply(reference_alias, 'Shared')

    def numpy_owner_alias(a):
        a.generators['second_numpy_wrapper'] = np.random.Generator(a.generators['numpy'].bit_generator)

    checks['shared_numpy_bitgenerator_wrappers'] = rejected_before_apply(numpy_owner_alias, 'alias')

    def tensor_custom_attribute(a):
        a.model.p.unrecorded_scale = 2.0

    checks['unrecorded_tensor_attribute'] = rejected_before_apply(tensor_custom_attribute, 'attribute')

    def optimizer_custom_array(a):
        a.optimizer.unrecorded_tensor = a.model.p

    checks['unrecorded_optimizer_tensor_attribute'] = rejected_before_apply(optimizer_custom_array, 'attribute')

    a, cursor, tape = tests.fixture()
    unused, raw, checksum = tests.seal(a, cursor, tape)
    pending_loss = a.model.p.square().sum()
    previous_version = a.model.p._version
    previous_public_bytes = tests.public_fingerprint(a)
    restored = a.restore(raw, checksum, len(raw))
    assert tests.public_fingerprint(a) == previous_public_bytes
    assert a.model.p._version > previous_version
    assert restored['autograd_version_counters_restored'] is False
    try:
        pending_loss.backward()
    except RuntimeError as error:
        assert 'version' in str(error) and 'modified' in str(error), str(error)
        pending_error = str(error)
    else:
        raise AssertionError('Pending-graph negative probe unexpectedly succeeded')
    checks['pending_external_autograd_graph_is_out_of_scope'] = {
        'expected_failure_observed': True, 'pre_restore_version': previous_version,
        'post_restore_version': a.model.p._version, 'public_record_restored_exact': True,
        'successful_restore_detects_pending_graph': False,
        'error': pending_error, 'envelope_bytes': len(raw),
        'interpretation': 'A caller must ensure a between-step boundary with no retained graph. Literal public-state restore is not autograd graph/version restore.',
    }
    sources_after = [identity(DIRECTORY / name) for name in ('adapter.py', 'tests.py')]
    assert sources_before == sources_after
    allowed = (
        'experiments.multimodal_output_portfolio.field_bridge_v6_preparation_20261028',
        'experiments.multimodal_output_portfolio.field_bridge_v6_torch_adapter_preparation_20261028',
    )
    scientific_imports = [name for name in sys.modules if name.startswith('experiments.multimodal_output_portfolio.') and not any(name == prefix or name.startswith(prefix + '.') for prefix in allowed)]
    assert not scientific_imports
    assert tests.WORK['toy_pipeline_forwards'] == 0 and tests.WORK['toy_optimizer_steps'] == 0
    result = {
        'schema': 'hepta.field-bridge.v6-torch-adapter.independent-probe.1',
        'started_unix_ns': started, 'completed_unix_ns': time.time_ns(),
        'status': 'PASS_SCOPED_ENGINEERING_PROBES', 'sources': sources_before,
        'sources_unchanged': True, 'checks': checks, 'runtime': adapter.runtime_descriptor(),
        'work': {**tests.WORK, 'additional_tiny_parameter_square_losses': 1, 'additional_backward_calls_expected_to_fail': 1},
        'boundary': {'new_research_registration': False, 'scientific_execution': False, 'scientific_kernel_replay': False, 'admission': False, 'scientific_imports': scientific_imports, 'downloads': 0, 'raw_uploads': 0, 'rust_builds': 0, 'persisted_checkpoint_files': 0, 'maximum_in_memory_envelope_bytes': max(row['envelope_bytes'] for row in checks.values())},
    }
    destination = ROOT.parent / 'v6_torch_adapter_independent_probe_20261028.json'
    with destination.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'receipt': identity(destination), 'check_groups': len(checks), 'status': result['status']}))


if __name__ == '__main__':
    main()
