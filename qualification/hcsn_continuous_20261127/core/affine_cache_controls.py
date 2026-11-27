"""Bounded, synthetic copy/load controls; never runs a population rollout or fit."""
import argparse
import copy
import dataclasses
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import time


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = Path(args.output); out.mkdir()
    here = Path(__file__).resolve().parent
    protocol_raw = (here/'AFFINE_CACHE_PROTOCOL.json').read_bytes()
    protocol = json.loads(protocol_raw)
    started = time.monotonic(); cpu = time.process_time()
    result = {'schema': 'hepta.affine-cache-copy-load-controls.v1',
              'status': 'STARTED', 'counts_complete': False, 'cases': [],
              'counts_started': {}, 'counts_returned': {}, 'failure': None,
              'protocol_sha256': hashlib.sha256(protocol_raw).hexdigest(),
              'new_full_model_rollouts': 0, 'new_optimizer_steps': 0,
              'new_task_loss_backwards': 0, 'new_task_data_rows': 0,
              'new_task_candidates': 0, 'price_output_values_returned': 0,
              'gradient_scope': 'Published construction uses autograd; these calls are counted, not zero-gradient.'}

    def snapshot():
        result['wall_seconds_so_far'] = time.monotonic()-started
        result['process_cpu_seconds_so_far'] = time.process_time()-cpu
        write_json(out/'PROGRESS.json', result)

    def counted(category, operation):
        def call(*values, **options):
            counts = result['counts_started']
            counts[category] = counts.get(category, 0)+1
            snapshot()
            if counts[category] > protocol['call_caps'][category]:
                raise RuntimeError('CALL_CAP_EXCEEDED: '+category)
            returned = operation(*values, **options)
            counts = result['counts_returned']
            counts[category] = counts.get(category, 0)+1
            if category in {'literal_price_calls', 'affine_price_calls'}:
                result['price_output_values_returned'] += sum(value.numel() for value in returned)
                if result['price_output_values_returned'] > protocol['price_output_value_cap']:
                    raise RuntimeError('PRICE_OUTPUT_VALUE_CAP_EXCEEDED')
            snapshot()
            return returned
        return call

    def check(condition, reason):
        if not condition:
            raise RuntimeError(reason)

    def deny(event, _args):
        if event.startswith('socket.') or event in {
                'subprocess.Popen', 'os.system', 'os.fork', 'os.forkpty',
                'os.exec', 'os.posix_spawn'}:
            raise RuntimeError('CHILD_OR_NETWORK_EVENT_DENIED: '+event)

    def forbidden(*_args, **_kwargs):
        raise RuntimeError('ROLLOUT_OR_TASK_BACKWARD_FORBIDDEN')

    try:
        identities = []
        for row in protocol['source_bindings']:
            path = here/row['path']; raw = path.read_bytes()
            check(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
                  'SOURCE_BINDING_MISMATCH: '+row['path'])
            identities.append(row)
        result['source_bindings'] = identities
        cgroups = [line.split(':', 2) for line in Path('/proc/self/cgroup').read_text().splitlines()]
        paths = [path for hierarchy, controllers, path in cgroups if hierarchy == '0' and not controllers]
        check(len(paths) == 1 and '..' not in Path(paths[0]).parts, 'UNQUALIFIED_CGROUP_V2')
        cgroup = Path('/sys/fs/cgroup')/paths[0].lstrip('/')
        limits = {name: (cgroup/name).read_text().strip()
                  for name in ['memory.max', 'memory.swap.max', 'cpu.max', 'pids.max']}
        quota, period = limits['cpu.max'].split()
        check(limits['memory.max'] != 'max' and int(limits['memory.max']) <= 1073741824
              and limits['memory.swap.max'] == '0' and quota != 'max'
              and 0 < int(quota) <= int(period) and limits['pids.max'] != 'max'
              and 0 < int(limits['pids.max']) <= 64, 'UNQUALIFIED_RESOURCE_SCOPE')
        result['resource_scope'] = {'path': str(cgroup), 'limits': limits}
        snapshot()
        sys.addaudithook(deny)
        import torch
        import population
        import he_xiong
        import affine_ports
        import affine_cache_fixture_b3fd as legacy
        check(torch.__version__ == protocol['torch_version'], 'UNQUALIFIED_TORCH_VERSION')
        torch.set_num_threads(1); torch.set_num_interop_threads(1)
        torch.manual_seed(protocol['constructor_rng_seed'])
        result['runtime'] = {'python': sys.version, 'torch': torch.__version__,
                             'device': 'cpu', 'dtype': 'torch.float64',
                             'threads': torch.get_num_threads(), 'constructor_rng_seed_calls': 1}
        population.BoundaryPopulation.__init__ = counted('population_constructors', population.BoundaryPopulation.__init__)
        he_xiong.Published.__init__ = counted('published_constructors', he_xiong.Published.__init__)
        he_xiong.Published.values = counted('constructor_value_calls', he_xiong.Published.values)
        torch.autograd.grad = counted('constructor_autograd_grad_calls', torch.autograd.grad)
        torch.nn.Module.load_state_dict = counted('module_load_state_dict_calls', torch.nn.Module.load_state_dict)
        population.BoundaryPopulation.priced_channels = counted('literal_price_calls', population.BoundaryPopulation.priced_channels)
        affine_ports.AffineBoundaryPopulation.priced_channels = counted('affine_price_calls', affine_ports.AffineBoundaryPopulation.priced_channels)
        legacy.AffineBoundaryPopulation.priced_channels = counted('affine_price_calls', legacy.AffineBoundaryPopulation.priced_channels)
        affine_ports.AffineBoundaryPopulation.rebuild_price_cache = counted('fixed_cache_rebuilds', affine_ports.AffineBoundaryPopulation.rebuild_price_cache)
        population.BoundaryPopulation.forward = forbidden
        population.BoundaryPopulation.step = forbidden
        population.ContinuousSpikingNetwork.forward = forbidden
        torch.Tensor.backward = forbidden

        def tensor_identity(value):
            check(value.device.type == 'cpu' and value.dtype == torch.float64, 'UNSUPPORTED_TENSOR_PROFILE')
            numbers = value.detach().reshape(-1).tolist()
            check(all(math.isfinite(v) for v in numbers), 'NONFINITE_TENSOR')
            raw = b''.join(struct.pack('<d', v) for v in numbers)
            return {'shape': list(value.shape), 'sha256': hashlib.sha256(raw).hexdigest()}

        def reference_identity(ref):
            tensor_state = {key: tensor_identity(value) for key, value in ref.state_dict().items()}
            constants = {key: value for key, value in vars(ref.prices).items()
                         if isinstance(value, (int, float)) and not isinstance(value, bool)}
            return {'law': dataclasses.asdict(ref.prices.p), 'constants': constants,
                    'dt': ref.dt, 'probe_horizons': list(ref.probe_horizons), 'state': tensor_state}

        def validate_reference(ref):
            check(torch.equal(ref.prices.basis_y, ref.grid.new_tensor(
                [ref.prices.a, -ref.prices.a, ref.prices.zb, -ref.prices.zb])), 'REFERENCE_LAW_BASIS_MISMATCH')
            check(bool(torch.all(ref.grid[1:] > ref.grid[:-1])), 'REFERENCE_GRID_UNORDERED')
            check(torch.equal(ref.cuts, .5*(ref.grid[:-1]+ref.grid[1:])), 'REFERENCE_CUTS_MISMATCH')
            check(bool(torch.all(ref.reset_weights >= 0)), 'REFERENCE_RESET_NEGATIVE')
            check(abs(float(ref.reset_weights.sum())-1.) <= 2e-14 and
                  abs(float((ref.grid*ref.reset_weights).sum())-.30) <= 2e-14, 'REFERENCE_RESET_INCOHERENT')

        def nonuniform_grid(ref):
            grid = ref.grid.new_tensor(protocol['nonuniform_grid'])
            k = int(torch.searchsorted(grid, grid.new_tensor(.30), right=True))
            weights = torch.zeros_like(grid)
            weights[k] = (.30-grid[k-1])/(grid[k]-grid[k-1]); weights[k-1] = 1-weights[k]
            ref.grid = grid; ref.cuts = .5*(grid[:-1]+grid[1:]); ref.reset_weights = weights
            validate_reference(ref)

        def evaluate(ref):
            principal = ref.grid.new_tensor(protocol['principal_ratios'])*ref.prices.p.P0
            with torch.no_grad():
                pair = ref.priced_channels(principal)
            check(len(pair) == 2 and all(tuple(v.shape) == (2, 3, 5) and bool(torch.isfinite(v).all()) for v in pair),
                  'PRICE_OUTPUT_PROFILE')
            return pair

        def max_error(left, right):
            return max(float((a-b).abs().max()) for a, b in zip(left, right))

        def begin(name):
            row = {'name': name, 'status': 'STARTED'}
            result['cases'].append(row); snapshot(); return row

        def close(row, detail):
            row.update(detail); row['status'] = 'PASS'; snapshot()

        def copy_case(name, ref, expect_legacy_failure):
            row = begin(name); validate_reference(ref); before = reference_identity(ref)
            fixed = affine_ports.copy_reference(ref); old = legacy.copy_reference(ref)
            check(fixed.prices is not ref.prices and fixed.prices.p == ref.prices.p, 'COPIED_LAW_ALIAS_OR_VALUE')
            check({key: tensor_identity(fixed.state_dict()[key]) for key in ref.state_dict()} == before['state'],
                  'COPIED_REFERENCE_STATE_CHANGED')
            check(all(fixed.state_dict()[key].data_ptr() != value.data_ptr() for key, value in ref.state_dict().items()),
                  'COPIED_REFERENCE_STORAGE_ALIAS')
            actual = evaluate(ref); repaired = evaluate(fixed); stale = evaluate(old)
            repaired_error = max_error(actual, repaired); stale_error = max_error(actual, stale)
            check(repaired_error <= protocol['absolute_price_tolerance'], 'FIXED_PRICE_PARITY_FAILED')
            check(stale_error >= protocol['legacy_failure_minimum'] if expect_legacy_failure
                  else stale_error <= protocol['absolute_price_tolerance'], 'LEGACY_CONTROL_FAILED')
            check(reference_identity(ref) == before, 'REFERENCE_MUTATED')
            close(row, {'reference': before, 'fixed_max_price_error': repaired_error,
                        'legacy_max_price_error': stale_error,
                        'legacy_expected_to_fail': expect_legacy_failure})
            return fixed, old, actual

        default = population.BoundaryPopulation(3, 2, atoms=5)
        fast_default, old_default, _ = copy_case('default_profile_unchanged', default, False)
        changed_law = population.BoundaryPopulation(3, 2, atoms=5, dt=.125, probe_horizons=(.1, .2, .4, 2.))
        changed_law.prices = he_xiong.Published(he_xiong.Law(**protocol['nondefault_law']))
        fast_law, _, law_prices = copy_case('nondefault_complete_law', changed_law, True)
        changed_grid = population.BoundaryPopulation(3, 2, atoms=5)
        nonuniform_grid(changed_grid)
        _, _, grid_prices = copy_case('coherent_nonuniform_grid', changed_grid, True)

        row = begin('parent_recursive_load_rebuilds_child_cache')
        parent = torch.nn.Module(); parent.cell = fast_default
        old_parent = torch.nn.Module(); old_parent.cell = old_default
        donor = torch.nn.Module(); donor.cell = changed_grid
        missing, extra = parent.load_state_dict(donor.state_dict(), strict=False)
        check(set(missing) == {'cell.price_center', 'cell.price_relative_slope'} and not extra, 'NESTED_KEY_CONTRACT')
        old_parent.load_state_dict(donor.state_dict(), strict=False)
        repaired_error = max_error(grid_prices, evaluate(parent.cell))
        stale_error = max_error(grid_prices, evaluate(old_parent.cell))
        check(repaired_error <= protocol['absolute_price_tolerance'] and stale_error >= protocol['legacy_failure_minimum'],
              'NESTED_LOAD_CONTROL_FAILED')
        close(row, {'fixed_max_price_error': repaired_error, 'legacy_max_price_error': stale_error})

        row = begin('same_key_serialized_cache_is_recomputed')
        state = {key: value.detach().clone() for key, value in fast_law.state_dict().items()}
        state['price_center'].fill_(10000.); state['price_relative_slope'].fill_(-777.)
        missing, extra = fast_law.load_state_dict(state)
        check(not missing and not extra, 'SAME_KEY_LOAD_CONTRACT')
        error = max_error(law_prices, evaluate(fast_law))
        check(error <= protocol['absolute_price_tolerance'], 'SERIALIZED_CACHE_TRUSTED')
        close(row, {'fixed_max_price_error': error, 'serialized_cache_recomputed': True})

        row = begin('deepcopied_hook_owner_uses_its_loaded_state')
        ref = copy.deepcopy(changed_law); nonuniform_grid(ref)
        fixed = copy.deepcopy(fast_law); before = reference_identity(fast_law)
        missing, extra = fixed.load_state_dict(ref.state_dict(), strict=False)
        check(set(missing) == {'price_center', 'price_relative_slope'} and not extra, 'DEEPCOPY_KEY_CONTRACT')
        error = max_error(evaluate(ref), evaluate(fixed))
        check(error <= protocol['absolute_price_tolerance'], 'DEEPCOPIED_HOOK_FAILED')
        check(reference_identity(fast_law) == before, 'DEEPCOPIED_HOOK_CHANGED_ORIGINAL')
        close(row, {'fixed_max_price_error': error, 'reference': reference_identity(ref)})

        check(result['counts_started'] == protocol['call_caps'] == result['counts_returned'], 'EXACT_COMPLETED_CALL_COUNTS')
        check(result['price_output_values_returned'] == protocol['price_output_value_cap'], 'EXACT_PRICE_OUTPUT_VALUE_COUNT')
        check(len(result['cases']) == 6 and all(row['status'] == 'PASS' for row in result['cases']), 'CASE_DENOMINATOR')
        for bound in protocol['source_bindings']:
            check(hashlib.sha256((here/bound['path']).read_bytes()).hexdigest() == bound['sha256'], 'FINAL_SOURCE_CHANGED')
        result['status'] = 'COMPLETED_ALL_SIX_SYNTHETIC_CONTROLS'
        result['counts_complete'] = True
    except BaseException as error:
        result['status'] = 'FAILED_OR_INCOMPLETE'
        result['failure'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        snapshot(); write_json(out/'RESULT.json', result)
    return 0 if result['counts_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
