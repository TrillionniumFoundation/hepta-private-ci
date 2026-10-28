"""Independent engineering-only GRU cross-object restore and preflight probes."""

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
import traceback
from unittest.mock import patch


REPOSITORY = Path('/workspace/scratch/e8a4dc33549f/hepta')
DIRECTORY = REPOSITORY / 'experiments/multimodal_output_portfolio/field_bridge_v6_gru_adapter_preparation_20261028'
EXPECTED = {
    'adapter.py': 'ffdc3aef38040531e8f4933f05be7e672e83d6a8e753d493217f65a281276919',
    'contract.py': 'ca7b33dca165aa22b953bb1528fefb80f8d8c4f26079c1cecba0ffd61e176827',
    'equivalence.py': '3952ae7f4347bb44694f0d779221de725b43a449629ae163e2eb72ec2e518d89',
    'tests.py': '11c16a15032e5cb94d116da6b3c1b0fc7852499fd67d884f09a86ef1f2f6cec6',
}
COUNTS = {
    'fixture_root_module_objects': 0,
    'explicit_fixture_sgd_constructions': 0,
    'toy_forward_calls': 0,
    'toy_backward_calls': 0,
    'toy_optimizer_steps': 0,
    'explicit_random_draw_calls': 0,
    'scientific_model_calls': 0,
    'scientific_training_steps': 0,
    'fresh_holdout_reads': 0,
}


def source_identity():
    return {name: {'sha256': hashlib.sha256((DIRECTORY / name).read_bytes()).hexdigest(),
                   'bytes': (DIRECTORY / name).stat().st_size} for name in EXPECTED}


def check_source():
    observed = source_identity()
    assert {name: row['sha256'] for name, row in observed.items()} == EXPECTED
    return observed


def fixture():
    torch.manual_seed(101)
    random.seed(103)
    np.random.seed(107)
    model = torch.nn.GRU(2, 2, num_layers=1, bias=True, batch_first=True, dropout=0., bidirectional=False)
    original = copy.deepcopy(model).eval().requires_grad_(False)
    observer = torch.nn.Linear(2, 1, bias=False).eval().requires_grad_(False)
    COUNTS['fixture_root_module_objects'] += 3
    parameters = list(model.parameters())
    optimizer = torch.optim.SGD([{'params': parameters[:2]}, {'params': parameters[2:], 'lr': .025}],
                                lr=.0125, momentum=.8)
    COUNTS['explicit_fixture_sgd_constructions'] += 1
    parameters[0].grad = torch.full_like(parameters[0], .03125)
    parameters[1].grad = torch.zeros_like(parameters[1])
    optimizer.state[parameters[0]] = {'momentum_buffer': torch.full_like(parameters[0], .125)}
    digest = hashlib.sha256(b'independent-gru-cross-object-NOT_REGISTERED').hexdigest()
    binding = {'study_id': 'independent-gru-cross-object-NOT_REGISTERED',
               **{key: digest for key in ('proposal_sha256', 'source_freeze_sha256',
                   'prospective_protocol_sha256', 'global_resource_limits_sha256')},
               'runtime_sha256': codec.digest(strict.runtime_descriptor())}
    context = {'source_ids': [('synthetic-a', 'synthetic-b')], 'inputs': np.arange(6, dtype=np.float32)}
    guard = {'panel_sha256': codec.digest(context), 'source_ids': [('synthetic-a', 'synthetic-b')],
             'output_sha256': [digest], 'values': np.asarray([.125], dtype=np.float64)}
    target = adapter.GRUAdapter(model, optimizer, binding=binding,
        architecture={'toy': 'independent-stock-gru-2-by-2', 'scientific': False},
        original_generator=original, reward_observer=observer, context_inputs=context,
        guard_baseline=guard, named_generators={'independent_torch': torch.Generator().manual_seed(109)})
    tape = [{'step': step, 'adapt_seed': step + 11, 'clean_seed': step + 13,
             'noise_seed': step + 17, 'condition': 'clean'} for step in range(240, 288)]
    cursor = {'seed': 17, 'schedule_id': 6000, 'path_kind': 'baseline', 'clock': 240,
              'total_steps': 288, 'remaining_steps': 48, 'decision_index': 5, 'guard_grain': 48,
              'baseline_action_index': 2, 'schedule_sha256': codec.digest(tape)}
    return target, cursor, tape


def measured(value):
    return value.detach().contiguous().numpy().copy()


def next_step(target):
    assert COUNTS['toy_forward_calls'] < 2
    COUNTS['explicit_random_draw_calls'] += 4
    inputs = torch.randn(2, 3, 2) + torch.rand(2, 3, 2, generator=target.generators['independent_torch'])
    inputs = inputs + torch.from_numpy(np.random.standard_normal((2, 3, 2)).astype(np.float32)) + random.random()
    hidden = torch.arange(4, dtype=torch.float32).reshape(1, 2, 2) / 16
    # Deliberately accumulate onto recorded incoming gradients; no zero_grad here.
    COUNTS['toy_forward_calls'] += 1
    output, final_hidden = target.model(inputs, hidden)
    loss = output.square().mean() + final_hidden.square().mean()
    COUNTS['toy_backward_calls'] += 1
    loss.backward()
    COUNTS['toy_optimizer_steps'] += 1
    target.optimizer.step()
    return {name: measured(value) for name, value in {'inputs': inputs, 'hidden_in': hidden,
        'output': output, 'hidden_out': final_hidden, 'loss': loss}.items()}


def caches(target):
    model = target.model
    return {'names': list(model._flat_weights_names), 'parameter_ids': [id(p) for p in model.parameters()],
            'cached_ids': [id(p) for p in model._flat_weights],
            'weakref_ids': [id(p) for p in model._flat_weight_refs],
            'weakref_referent_ids': [id(p()) for p in model._flat_weight_refs]}


def public_fingerprint(target):
    params = dict(target.model.named_parameters())
    return codec.digest({'parameters': {name: measured(p) for name, p in params.items()},
        'grads': {name: None if p.grad is None else measured(p.grad) for name, p in params.items()},
        'optimizer': strict.native(target.optimizer.state_dict()),
        'references': {name: strict.native(model.state_dict()) for name, model in target.references.items()},
        'modes': {name: child.training for name, child in target.model.named_modules()},
        'context': strict.native(target.context_inputs), 'guard': strict.native(target.guard_baseline),
        'rng': {'torch': measured(torch.get_rng_state()), 'python': random.getstate(),
                'numpy': strict.native(np.random.get_state()),
                'named': {name: strict.generator_state(g, strict.generator_kind(g))
                          for name, g in target.generators.items()}}})


def expect_rejected(target, raw, checksum, label):
    before = public_fingerprint(target)
    object_ids = {'cache': caches(target), 'model': id(target.model), 'optimizer': id(target.optimizer),
                  'state': id(target.optimizer.state), 'groups': id(target.optimizer.param_groups),
                  'grads': [None if p.grad is None else id(p.grad) for p in target.model.parameters()]}
    versions = [p._version for p in target.model.parameters()]
    error = None
    with patch.object(target, '_apply') as apply:
        try:
            target.restore(raw, checksum, 65536)
        except (ValueError, TypeError, RuntimeError) as exc:
            error = type(exc).__name__ + ': ' + str(exc)
        assert error is not None, label + ' unexpectedly accepted'
        apply.assert_not_called()
    assert public_fingerprint(target) == before
    assert {'cache': caches(target), 'model': id(target.model), 'optimizer': id(target.optimizer),
            'state': id(target.optimizer.state), 'groups': id(target.optimizer.param_groups),
            'grads': [None if p.grad is None else id(p.grad) for p in target.model.parameters()]} == object_ids
    assert [p._version for p in target.model.parameters()] == versions
    return {'case': label, 'rejected': True, 'error': error, 'apply_calls': 0,
            'public_state_objects_versions_and_rng_unchanged': True}


def review(output):
    evidence = {'sources_before': check_source(), 'method_count': len(contract.EXPECTED_METHODS),
                'equivalence': equivalence.verify(adapter.GRUAdapter)}
    assert evidence['method_count'] == 18
    contract.verify_stock_methods()
    first, cursor, tape = fixture()
    fresh, cursor2, tape2 = fixture()
    assert first is not fresh and first.model is not fresh.model and first.optimizer is not fresh.optimizer
    assert first.environment_sha256 == fresh.environment_sha256 and cursor == cursor2 and tape == tape2
    record = first.capture(cursor, tape)
    raw, checksum = state.seal(record, first.environment_sha256)
    assert len(raw) < 65536
    assert np.any(record['gradients']['weight_ih_l0'] != 0)
    assert np.all(record['gradients']['weight_hh_l0'] == 0) and record['gradients']['bias_hh_l0'] is None
    saved = codec.save(output / 'tiny_cross_object.state', record, 65536)
    assert saved['sha256'] == checksum
    first_outputs = next_step(first)
    first_after = codec.dumps(first.capture(cursor, tape))
    fresh_cache = caches(fresh)
    with torch.no_grad():
        fresh.model.weight_ih_l0.add_(.5)
        fresh.optimizer.state[fresh.model.weight_ih_l0]['momentum_buffer'].mul_(2)
    fresh.model.weight_ih_l0.grad = None
    fresh.model.bias_hh_l0.grad = torch.ones_like(fresh.model.bias_hh_l0)
    fresh.optimizer.param_groups[0]['lr'] = .3
    torch.manual_seed(907); random.seed(911); np.random.seed(919)
    fresh.generators['independent_torch'].manual_seed(929)
    assert codec.dumps(fresh.capture(cursor, tape)) != raw
    restore_receipt = fresh.restore((output / 'tiny_cross_object.state').read_bytes(), checksum, 65536)
    assert codec.dumps(fresh.capture(cursor, tape)) == raw
    assert caches(fresh) == fresh_cache
    assert codec.dumps(next_step(fresh)) == codec.dumps(first_outputs)
    assert codec.dumps(fresh.capture(cursor, tape)) == first_after
    evidence['cross_object_replay'] = {'fresh_distinct_target': True, 'checkpoint_bytes': len(raw),
        'checkpoint_sha256': checksum, 'outputs_input_hidden_loss_sha256': codec.digest(first_outputs),
        'after_full_record_sha256': hashlib.sha256(first_after).hexdigest(),
        'before_and_after_literal_equality': True, 'caches_keep_target_parameter_identity': True,
        'incoming_nonzero_and_zero_and_none_gradients_exercised': True,
        'restored_sgd_momentum_groups_and_all_used_rngs': True, 'restore_receipt': restore_receipt}
    negatives = []
    saved_cache = fresh.model._flat_weights[0]
    try:
        fresh.model._flat_weights[0] = fresh.model.weight_hh_l0
        negatives.append(expect_rejected(fresh, raw, checksum, 'same_shape_wrong_cached_parameter'))
    finally:
        fresh.model._flat_weights[0] = saved_cache
    reference_parameter = fresh.references['original_generator'].weight_ih_l0
    old_reference_data = reference_parameter.data
    try:
        reference_parameter.data = fresh.model.weight_ih_l0.data
        negatives.append(expect_rejected(fresh, raw, checksum, 'immutable_reference_cross_storage_alias'))
    finally:
        reference_parameter.data = old_reference_data
    with patch.object(torch.nn.GRU, 'permute_hidden', lambda self, hidden, permutation: hidden + 1):
        negatives.append(expect_rejected(fresh, raw, checksum, 'class_permute_hidden_override'))
    function = contract.RNN.RNNBase.__init__
    original_defaults = function.__defaults__
    assert type(original_defaults[0]) is int and original_defaults[0] == 1
    try:
        function.__defaults__ = (True, *original_defaults[1:])
        negatives.append(expect_rejected(fresh, raw, checksum, 'stock_default_int_to_bool'))
    finally:
        function.__defaults__ = original_defaults
    evidence['rejections'] = negatives
    contract.verify_stock_methods()
    evidence['sources_after'] = check_source()
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'kind': 'independent_engineering_only_gru_extension_review',
              'status': 'FAIL', 'admission': False, 'scientific_kernel_replay': False,
              'original_scientific_status': 'FAIL', 'counts': COUNTS,
              'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    try:
        report['evidence'] = review(args.output)
        allowed = ('experiments.multimodal_output_portfolio.field_bridge_v6_preparation_20261028',
                   'experiments.multimodal_output_portfolio.field_bridge_v6_torch_adapter_preparation_20261028',
                   'experiments.multimodal_output_portfolio.field_bridge_v6_gru_adapter_preparation_20261028')
        report['scientific_module_imports'] = [name for name in sys.modules
            if name.startswith('experiments.multimodal_output_portfolio.') and not name.startswith(allowed)]
        assert not report['scientific_module_imports']
        assert COUNTS['toy_forward_calls'] == COUNTS['toy_backward_calls'] == COUNTS['toy_optimizer_steps'] == 2
        report['status'] = 'PASS'
    except BaseException as exc:
        report['error'] = repr(exc)
        report['traceback'] = traceback.format_exc()
    report['limits'] = ['Only two tiny synthetic GRU steps; no scientific kernel/assets/holdout.',
        'No pending autograd graph or concurrent writer; autograd version counters are not rewound.',
        'Hidden input is local fixed test data; cross-step carried hidden state is not covered.',
        'Runtime/builtin/dispatcher malicious replacement is outside this preparation contract.',
        'Counts identify explicit fixtures and real toy calls. Inherited isolated preflight SGD/RNG constructors are validation work, not model steps.',
        'The writer suite was read but not executed; no old adapter suite was repeated.']
    path = args.output / 'INDEPENDENT_REVIEW.json'
    with path.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    print(json.dumps({'status': report['status'], 'path': str(path), 'bytes': path.stat().st_size,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'counts': COUNTS,
                      'error': report.get('error')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    check_source()
    sys.path.insert(0, str(REPOSITORY))
    import numpy as np
    import torch
    from experiments.multimodal_output_portfolio.field_bridge_v6_gru_adapter_preparation_20261028 import adapter, contract, equivalence
    strict, codec, state = contract.strict, contract.codec, contract.strict.branch_state
    raise SystemExit(main())
