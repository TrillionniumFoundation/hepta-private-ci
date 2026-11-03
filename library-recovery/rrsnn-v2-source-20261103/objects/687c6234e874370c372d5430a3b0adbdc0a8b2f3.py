"""Resume actual CTMC spikes, policy actions and the deadline/resource ledger.

The fixtures are synthetic correctness checks, with no oracle/future labels in
policy execution. --checkpoint accepts a completed v2 model.pt parameter file.
No training data or scientific holdout task metric is opened by this validator.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import time

if hasattr(os, 'sched_setaffinity') and 6 in os.sched_getaffinity(0):
    os.sched_setaffinity(0, {6})
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'

import torch
from joint_checkpoint import (
    DOMAIN, JointRollout, Policy, Scenario, canonical, load_model, read_checkpoint, sha,
)

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--output-name', default='fixed_weights')
    args = parser.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]{1,64}', args.output_name):
        raise ValueError('Use a simple output label')
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    output = ROOT / 'joint_replay_results' / args.output_name
    output.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    artifact = args.checkpoint
    if artifact is None:
        artifact = output / 'fixed_untrained_model.pt'
        if not artifact.exists():
            torch.manual_seed(99001)
            initial = Policy('rr_density')
            with torch.no_grad():
                initial.encoder.input_layer.bias.fill_(0.9)
                initial.encoder.input_layer.weight.mul_(0.2)
            torch.save({'state_dict': initial.state_dict(), 'variant': 'rr_density',
                        'metadata': initial.metadata(), 'seed': 99001,
                        'origin': 'Untrained fixed random weights; a positive control bias ensures the fixture exercises real repeated spikes.'}, artifact)
    artifact = artifact.resolve()
    model, blob = load_model(artifact)
    common = dict(values=(1.4, 1.2, .7, .5), budget=5, shock_amount=2, refill_amount=2,
                  split='synthetic_checkpoint_fixture')
    cases = [Scenario(deadlines=(1., 1., 3., 3.), profile='A', **common),
             Scenario(deadlines=(2., 2., 2., 2.), profile='B', **common)]
    checks = []
    negative = []
    first_checkpoint = None
    for case_index, scenario in enumerate(cases):
        uninterrupted = JointRollout(model, artifact, scenario, seed=99011+case_index)
        checkpoints = []
        while uninterrupted.next_index < len(uninterrupted.times):
            row = uninterrupted.advance(uninterrupted.next_index)
            if row['time'] in (scenario.shock_time, scenario.refill_time):
                checkpoint = uninterrupted.checkpoint()
                checkpoint_file = output / f'{scenario.profile}_after_{row["time"]:.2f}.json'
                checkpoint_file.write_bytes(canonical(checkpoint)+b'\n')
                checkpoints.append((checkpoint_file, checkpoint['payload_sha256']))
        final = uninterrupted.checkpoint()
        if scenario.profile == 'B':
            # A live item initially due at 2 was renewed once, is due at 4,
            # and is queried at the terminal left limit without renewal to 6.
            assert all(row['next_deadline'] == 4.0 for row in final['payload']['deadline_queue'])
        for checkpoint_file, trusted_digest in checkpoints:
            checkpoint = read_checkpoint(checkpoint_file)
            resumed_model, _ = load_model(artifact)
            resumed = JointRollout.restore(checkpoint, resumed_model, artifact, trusted_digest)
            frontier = resumed.next_index
            prefix = copy.deepcopy(resumed.committed)
            while resumed.next_index < len(resumed.times):
                resumed.advance(resumed.next_index)
            assert canonical(resumed.committed[:frontier]) == canonical(prefix)
            assert canonical(resumed.committed[frontier:]) == canonical(uninterrupted.committed[frontier:])
            assert canonical(resumed.checkpoint()) == canonical(final)
            continued = resumed.committed[frontier:]
            spikes = sum(len(row['spikes']) for row in continued)
            fixture = {'schema': 'rrsnn.joint-ctmc-replay-fixture.v1',
                       'synthetic_fixture': True, 'checkpoint': checkpoint,
                       'externally_retained_expected_sha256': trusted_digest,
                       'continuation_event_indices': list(range(frontier, len(resumed.times))),
                       'expected_continuation_events': continued, 'expected_final': final}
            fixture_file = checkpoint_file.with_name(checkpoint_file.stem+'_continuation.json')
            fixture_file.write_bytes(canonical(fixture)+b'\n')
            checks.append({'case': scenario.profile, 'snapshot_after_time': checkpoint['payload']['execution']['time'][0],
                           'next_event_index': frontier, 'continued_event_count': len(continued),
                           'continued_actual_spike_count': spikes,
                           'actual_spike_times_actions_ledger_bitwise_reproduced': True,
                           'final_physical_context_rng_and_ledger_identical': True,
                           'terminal_utility': resumed.ledger['terminal_utility'],
                           'terminal_budget': resumed.ledger['budget'],
                           'checkpoint_bytes': checkpoint_file.stat().st_size,
                           'checkpoint_sha256': trusted_digest,
                           'fixture_file': str(fixture_file.relative_to(ROOT)),
                           'fixture_sha256': sha(fixture_file)})
            if first_checkpoint is None:
                first_checkpoint = checkpoint
    assert first_checkpoint is not None
    if args.checkpoint is None:
        assert any(row['continued_actual_spike_count'] > 0 for row in checks)

    def rejected(name, callable):
        try:
            callable()
        except (ValueError, TypeError, KeyError) as error:
            negative.append({'name': name, 'rejected': True, 'reason': str(error)})
        else:
            raise AssertionError('Negative case unexpectedly accepted: '+name)

    def restore_altered(change):
        altered = copy.deepcopy(first_checkpoint)
        change(altered['payload'])
        # Re-seal to exercise semantic checks, not merely the outer hash check.
        altered['payload_sha256'] = hashlib.sha256(DOMAIN+canonical(altered['payload'])).hexdigest()
        candidate, _ = load_model(artifact)
        JointRollout.restore(altered, candidate, artifact, altered['payload_sha256'])

    rejected('tampered_budget_even_if_resealed', lambda: restore_altered(
        lambda p: p['ledger'].__setitem__('budget', p['ledger']['budget']+1)))
    rejected('wrong_model_artifact_hash', lambda: restore_altered(
        lambda p: p['binding'].__setitem__('model_artifact_sha256', '0'*64)))
    rejected('wrong_source_hash', lambda: restore_altered(
        lambda p: p['binding']['source_sha256'].__setitem__('rrsnn_v2/audit/sampled_policy.py', '0'*64)))
    rejected('tampered_context_even_if_resealed', lambda: restore_altered(
        lambda p: p['execution']['context'][0].__setitem__(0, p['execution']['context'][0][0]+.1)))
    changed_weights, _ = load_model(artifact)
    with torch.no_grad():
        changed_weights.head.bias[0].add_(.125)
    rejected('wrong_actual_model_weights', lambda: JointRollout.restore(
        first_checkpoint, changed_weights, artifact, first_checkpoint['payload_sha256']))
    restored_model, _ = load_model(artifact)
    restored = JointRollout.restore(first_checkpoint, restored_model, artifact, first_checkpoint['payload_sha256'])
    before = canonical(restored.checkpoint())
    rejected('duplicate_previously_committed_tick', lambda: restored.advance(restored.next_index-1))
    assert before == canonical(restored.checkpoint())
    rejected('wrong_external_expected_checkpoint_digest', lambda: JointRollout.restore(
        first_checkpoint, restored_model, artifact, '0'*64))
    new = JointRollout(model, artifact, cases[0])
    rejected('snapshot_before_first_committed_event', new.checkpoint)
    report = {'schema': 'rrsnn.joint-ctmc-resource-restore-validation.v1', 'all_passed': True,
              'model_artifact': str(artifact), 'model_artifact_sha256': sha(artifact),
              'model_weights_sha256': first_checkpoint['payload']['binding']['model_weights_sha256'],
              'model_origin': 'completed_parameter_artifact' if args.checkpoint else 'fixed_untrained_fixture',
              'model_run_name': blob.get('run_name'), 'model_seed': blob.get('seed'),
              'operator_profile': first_checkpoint['payload']['binding']['operator_profile'],
              'source_sha256': first_checkpoint['payload']['binding']['source_sha256'],
              'numpy_version': first_checkpoint['payload']['binding']['numpy_version'],
              'torch_version': first_checkpoint['payload']['binding']['torch_version'],
              'checks': checks, 'negative_cases': negative,
              'old_tick_rejected_before_rng_or_ledger_mutation': True,
              'terminal_deadline_queue_preserves_left_limit': True,
              'policy_received_oracle_or_future_labels': False,
              'shared_feasible_action_mask_used': True,
              'ledger_conservation_is_environment_guarantee_not_rr_advantage': True,
              'elapsed_seconds': time.perf_counter()-start,
              'real_future_window': False, 'actual_hepta_owner_executed': False,
              'registered_hepta_schema_modified': False, 'all_rust_joint_execution': False,
              'checkpoint_phase': 'after a complete observation/CTMC advance/action/ledger commit',
              'limitations': [
                  'Single-episode Python research owner, float32 controller and exact finite-CTMC event sampler.',
                  'This is the finite CTMC law, not exact continuous Brownian dynamics.',
                  'SHA bindings require an independently retained expected digest for alteration detection; no owner authentication is supplied.',
                  'Only completed event boundaries are supported; no mid-step rollback, process crash, filesystem durability, distributed CAS or concurrent-writer claim.',
                  'Known synthetic Scenario is stored by the environment; the policy receives only state_features and its common legal-action mask.',
                  'The torch .pt file supplies immutable model parameters only; complete live execution state is carried separately in JSON.',
                  'The separate Rust bridge carries Brownian physical checkpoint fixtures; this joint CTMC/ledger wrapper remains Python.',
              ]}
    (output/'validation.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'all_passed': True, 'checks': checks, 'negative_cases': len(negative),
                      'elapsed_seconds': report['elapsed_seconds']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
