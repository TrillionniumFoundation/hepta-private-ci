import hashlib
import json
from pathlib import Path
import time
import types
import sys
import platform
import importlib.metadata
from unittest import mock

import numpy as np
import torch

from qualification.hcsn.baselines import UnavailableBaseline
from qualification.hcsn.content_tasks import CONDITIONS, make_content_batch, oracle_targets

def source_map():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('qualification/hcsn').glob('*.py'))}

source_before = source_map()
path = Path('qualification/hcsn/content_model.py')
source = path.read_bytes()
module = types.ModuleType('qualification.hcsn._content_fixture_snapshot')
module.__package__ = 'qualification.hcsn'
module.__file__ = str(path)
exec(compile(source, str(path), 'exec'), module.__dict__)
torch.set_num_threads(1)
cores = ('hx_dual', 'hx_call', 'hx_risk', 'margin_only', 'smooth_gate', 'gru', 'cfc',
         'transformer', 'lif', 'adaptive_lif', 'pif', 'population_flux',
         'population_flux_no_recovery', 'hx_fixed', 'no_rollover', 'no_recovery',
         'softplus', 'hx_attention', 'mamba2')
rows = []
start_wall, start_cpu = time.perf_counter(), time.process_time()
for core in cores:
    for condition in CONDITIONS:
        row = {'core': core, 'condition': condition, 'optimizer_steps': 0}
        try:
            batch = make_content_batch(9917, 1, keys=4, values=3, queries=2,
                                       delay_steps=2, condition=condition)
            np.testing.assert_array_equal(batch.targets, oracle_targets(batch.x, keys=4, values=3))
            torch.manual_seed(91033)
            model = module.AddressedContentModel(core, keys=4, values=3, hidden_size=4)
            logits = model(torch.from_numpy(batch.x))
            loss = module.query_loss(logits, torch.from_numpy(batch.targets), torch.from_numpy(batch.query_mask))
            loss.backward()
            activity = module.parameter_activity(model)
            if not bool(torch.isfinite(loss)) or not bool(torch.isfinite(logits).all()):
                raise RuntimeError('nonfinite forward or loss')
            if not all(x['finite_gradient'] is not False for x in activity['parameters']):
                raise RuntimeError('nonfinite gradient')
            if not activity['observed_nonzero_gradient']:
                raise RuntimeError('no observed nonzero gradients')
            row.update(status='passed', query_loss=float(loss.detach()), output_shape=list(logits.shape),
                       stored=activity['stored'], trainable=activity['trainable'],
                       observed_nonzero_gradient=activity['observed_nonzero_gradient'])
        except UnavailableBaseline as error:
            row.update(status='unavailable', reason=str(error))
        except Exception as error:
            row.update(status='failed', reason=f'{type(error).__name__}: {error}')
        rows.append(row)
controls = []

def control(name, action):
    try:
        action()
        controls.append({'name': name, 'status': 'passed'})
    except Exception as error:
        controls.append({'name': name, 'status': 'failed', 'reason': f'{type(error).__name__}: {error}'})

def expect_reject(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError('malformed input was accepted')

batch = make_content_batch(9917, 1, keys=4, values=3, queries=2, delay_steps=2)
valid = torch.from_numpy(batch.x)
for label, kind, address_count, payload_count in [('silence_key', 3, 1, 0), ('noise_empty', 2, 0, 0), ('noise_two_keys', 2, 2, 1), ('noise_two_payloads', 2, 1, 2)]:
    malformed = valid.clone()
    malformed[0, 2] = 0
    malformed[0, 2, kind] = 1
    malformed[0, 2, 4:4+address_count] = 1
    malformed[0, 2, 8:8+payload_count] = 1
    control(label, lambda bad=malformed: expect_reject(lambda: module.route_content(bad, 4, 3)))

model = module.AddressedContentModel('smooth_gate', keys=4, values=3, hidden_size=4)
logits = model(valid)
targets, mask = torch.from_numpy(batch.targets), torch.from_numpy(batch.query_mask)
ignored = targets.clone()
ignored[mask] = -100
control('query_ignore_index_rejected', lambda: expect_reject(lambda: module.query_loss(logits, ignored, mask)))

def no_finance():
    with mock.patch.object(module.ValueKernelCell, 'financial_parameters', side_effect=AssertionError('financial parameter transform called')), mock.patch.object(module.ValueKernelCell, '_base_boundary', side_effect=AssertionError('financial boundary called')):
        answer = model(valid)
        module.query_loss(answer, targets, mask).backward()
    if model.core.raw_financial.requires_grad or model.core.raw_financial.grad is not None:
        raise AssertionError('smooth financial parameters were active')
control('smooth_forward_backward_without_financial_computation', no_finance)

def stream_recovery(core):
    torch.manual_seed(91033)
    network = module.AddressedContentModel(core, keys=4, values=3, hidden_size=4).double()
    x = valid.double()
    edges = np.r_[0., np.cumsum(np.linspace(.04, .19, x.shape[1]))].tolist()
    full, state = network.stream(x, edges, subdivisions=2)
    left, checkpoint = network.stream(x[:, :3], edges[:4], subdivisions=2)
    right, restored = network.stream(x[:, 3:], edges[3:], initial_state=checkpoint, subdivisions=2)
    torch.testing.assert_close(torch.cat((left, right), 1), full, rtol=0, atol=0)
    torch.testing.assert_close(restored.memory, state.memory, rtol=0, atol=0)
    torch.testing.assert_close(restored.recovery, state.recovery, rtol=0, atol=0)
    module.query_loss(full, targets, mask).backward()
    if not all(row['finite_gradient'] is not False for row in module.parameter_activity(network)['parameters']):
        raise AssertionError('nonfinite resumed stream gradient')
for name in ('hx_dual', 'smooth_gate'):
    control('irregular_stream_resume_and_query_backward_' + name, lambda core=name: stream_recovery(core))

source_after = source_map()
report = {'scope': 'finite CPU forward/backward content integration fixtures; no training or model-quality claim',
          'model_source_sha256': hashlib.sha256(source).hexdigest(),
          'tasks_source_sha256': hashlib.sha256(Path('qualification/hcsn/content_tasks.py').read_bytes()).hexdigest(),
          'torch': torch.__version__, 'cpu_threads': 1, 'seed': 91033,
          'passed': sum(x['status'] == 'passed' for x in rows),
          'failed': sum(x['status'] == 'failed' for x in rows),
          'unavailable': sum(x['status'] == 'unavailable' for x in rows),
          'optimizer_steps': 0, 'cuda_training_attempts': 0,
          'python': sys.version, 'platform': platform.platform(), 'numpy': np.__version__,
          'ncps': importlib.metadata.version('ncps'), 'source_hashes': source_before,
          'source_stable_during_execution': source_before == source_after,
          'control_results': controls, 'controls_passed': sum(c['status'] == 'passed' for c in controls),
          'controls_failed': sum(c['status'] == 'failed' for c in controls),
          'cpu_seconds': time.process_time() - start_cpu,
          'wall_seconds': time.perf_counter() - start_wall, 'records': rows}
import argparse
parser = argparse.ArgumentParser(description="Finite content integration checks; zero optimizer updates")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--previous", type=Path, required=True)
args = parser.parse_args()
prior = json.loads(args.previous.read_text())
combined = {
    "schema": "hcsn-content-fixture-acceptance-v3",
    "scope": "finite engineering checks, not training, capacity matching, quality or multimodal qualification",
    "previous_receipt_sha256": hashlib.sha256(args.previous.read_bytes()).hexdigest(),
    "current_snapshot_attempt": report,
    "complete_known_fixture_cpu_seconds": prior["complete_known_fixture_cpu_seconds"] + report["cpu_seconds"],
    "complete_known_fixture_wall_seconds": prior["complete_known_fixture_wall_seconds"] + report["wall_seconds"],
    "cost_exclusions": ["interpreter startup", "imports", "other tests", "source review", "unmeasured energy"],
    "physical_energy_joules": None,
    "optimizer_steps_total": 0,
    "cuda_training_attempts_total": 0,
    "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}
args.output.write_text(json.dumps(combined, indent=2) + "\n")
print(json.dumps({key: report[key] for key in ("passed", "failed", "unavailable", "controls_passed", "controls_failed", "cpu_seconds", "wall_seconds", "source_stable_during_execution")}))
raise SystemExit(0 if report["failed"] == report["controls_failed"] == 0 and report["source_stable_during_execution"] else 1)
