"""Candidate C2 runner. Default is validation only; real execution needs a later bound decision."""
import os
import time

PROCESS_STARTED = float(os.environ.get('HCSN_PROCESS_STARTED', time.monotonic()))

import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import traceback

import torch

from c2_boundary import Ineligible, require, plateau_state
from c2_io import (atomic_alias, bind_parent, exclusive_json, identity, immutable_checkpoint,
                   semantic_digest, sha, state_equal, verify_files)
from c2_io import append_receipt
from c2_recording import ProgressRecorder, OptimizationRecorder, RecordingHold


class ResourceStop(TimeoutError):
    pass


class Budget:
    def __init__(self, parent_wall, total, started, rss_limit, reserve, peak_rss,
                 monotonic=time.monotonic):
        require(0 < parent_wall < total <= 43200 and 0 <= reserve < total - parent_wall,
                'invalid cumulative resource envelope')
        self.parent_wall, self.total, self.started = parent_wall, total, started
        self.rss_limit, self.reserve, self.peak_rss, self.clock = rss_limit, reserve, peak_rss, monotonic

    def elapsed(self):
        return self.clock() - self.started

    def remaining(self):
        return self.total - self.parent_wall - self.elapsed()

    def check(self, *unused, finalizing=False):
        rss = self.peak_rss()
        if rss is not None and rss > self.rss_limit:
            raise ResourceStop('declared C2 RSS budget exhausted')
        if self.remaining() <= (0 if finalizing else self.reserve):
            raise ResourceStop('declared cumulative active wall budget exhausted; not convergence')


def epoch_clocks(parent_wall, process_started, *, monotonic=time.monotonic, cpu=time.process_time):
    """Exactly one sample of each clock; never resample to compute cumulative wall."""
    elapsed, used = monotonic() - process_started, cpu()
    require(elapsed >= 0 and used >= 0, 'negative phase clock')
    return {'phase_process_wall_seconds': elapsed, 'cumulative_process_wall_seconds': parent_wall + elapsed,
            'phase_process_cpu_seconds': used, 'cumulative_process_cpu_seconds': None}


def snapshot(model, optimizer, order_rng, epoch, updates, data_sha):
    return {'model': model.state_dict(), 'model_configuration': model.construction_configuration,
            'optimizer': optimizer.state_dict(), 'torch_rng': torch.get_rng_state(),
            'order_rng': order_rng.getstate(), 'epochs_completed': epoch,
            'main_updates': updates, 'data_manifest_sha256': data_sha}


def verify_frozen(model, initial):
    frozen = {name for name, parameter in model.named_parameters() if not parameter.requires_grad}
    frozen.update(name for name, _ in model.named_buffers())
    actual = model.state_dict()
    require(all(torch.equal(actual[name], initial['model'][name]) for name in frozen),
            'frozen common, physical or buffer state changed')


def _exact_manifest_pairs(pairs):
    # A byte digest is not a unique semantic interpretation if JSON keys repeat.
    value = {}
    for key, item in pairs:
        require(key not in value, 'duplicate C2 program manifest JSON key')
        value[key] = item
    return value


def _no_manifest_constant(value):
    raise Ineligible('nonfinite C2 program manifest JSON constant: ' + value)


def _valid_source_identity(item):
    require(type(item) is dict and set(item) == {'bytes', 'sha256'}
            and type(item['bytes']) is int and item['bytes'] >= 0
            and type(item['sha256']) is str and len(item['sha256']) == 64
            and all(c in '0123456789abcdef' for c in item['sha256']),
            'invalid C2 program source identity')


def bind_program(manifest_path):
    # Validate the actual source descriptor *before* resolving it. resolve()
    # erases a symlink and can otherwise make an aliased path appear regular.
    path = Path(manifest_path)
    require(path.is_file() and not path.is_symlink()
            and not path.parent.is_symlink()
            and 0 < path.stat().st_size <= 65536,
            'unsafe, missing or oversized C2 program manifest')
    root = path.parent.resolve()
    try:
        value = json.loads(path.read_bytes(), object_pairs_hook=_exact_manifest_pairs,
                           parse_constant=_no_manifest_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Ineligible('malformed C2 program manifest JSON') from error
    require(type(value) is dict and set(value) == {
            'schema', 'scientific_admission', 'execution_authorized',
            'files', 'dependencies'},
            'C2 program manifest has unreviewed or missing metadata')
    require(value['schema'] == 'hcsn-c2-successor-source-manifest-v1'
            and value['scientific_admission'] == 'HOLD_NO_GO'
            and value['execution_authorized'] is False,
            'C2 source freeze may not silently authorize scientific execution')
    required = {'c2_runner.py', 'c2_io.py', 'c2_recording.py', 'c2_boundary.py',
                'c2_controller.py', 'POSTERIOR-POLICY.json',
                'OPTIMIZATION-POSTERIOR-POLICY-v2.json', 'CONTRACT.json'}
    expected = value['files']
    require(type(expected) is dict and set(expected) == required,
            'candidate program manifest has missing or unreviewed execution inputs')
    inputs = {}
    for name, item in expected.items():
        _valid_source_identity(item)
        source = root / name
        require(source.is_file() and not source.is_symlink()
                and not source.parent.is_symlink(),
                'unsafe or missing C2 source file: ' + name)
        resolved = source.resolve()
        require(resolved.is_relative_to(root),
                'C2 source escaped the frozen candidate root')
        require(identity(resolved) == item,
                'candidate program source differs: ' + name)
        inputs[str(resolved)] = item
    dependency_key = 'recovery_v1/c2_durable.py'
    dependencies = value['dependencies']
    require(type(dependencies) is dict and set(dependencies) == {dependency_key},
            'C2 program manifest lacks exact durable implementation dependency')
    _valid_source_identity(dependencies[dependency_key])
    dependency = Path(__file__).resolve().parent.parent / 'recovery_v1' / 'c2_durable.py'
    require(dependency.is_file() and not dependency.is_symlink()
            and not dependency.parent.is_symlink(),
            'durable dependency is missing or symlinked')
    require(identity(dependency) == dependencies[dependency_key],
            'durable publisher implementation changed since freeze')
    import c2_durable
    require(Path(c2_durable.__file__).resolve() == dependency.resolve(),
            'loaded durable publisher is not the pinned recovery module')
    inputs[str(dependency.resolve())] = dependencies[dependency_key]
    inputs[str(path.resolve())] = identity(path)
    require(str(Path(__file__).resolve()) in inputs, 'running unbound C2 entry point')
    return inputs


def require_decision(decision_path, decision_sha, contract_path, program_manifest):
    # This is a separate prospective authorization boundary: a byte digest
    # cannot make ambiguous JSON or an aliased decision file acceptable.
    require(decision_path is not None and type(decision_sha) is str
            and len(decision_sha) == 64
            and all(c in '0123456789abcdef' for c in decision_sha),
            'real C2 execution has no exact later bound decision identity')
    path = Path(decision_path)
    require(path.is_file() and not path.is_symlink()
            and not path.parent.is_symlink()
            and 0 < path.stat().st_size <= 16384,
            'unsafe, absent, or oversized C2 execution decision')
    raw = path.read_bytes()
    require(0 < len(raw) <= 16384
            and hashlib.sha256(raw).hexdigest() == decision_sha,
            'execution decision identity differs')
    try:
        decision = json.loads(raw, object_pairs_hook=_exact_manifest_pairs,
                              parse_constant=_no_manifest_constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Ineligible('malformed C2 execution decision JSON') from error
    require(type(decision) is dict and set(decision) == {
            'schema', 'execution_authorized', 'scope', 'confirmation_E_access',
            'contract_sha256', 'program_manifest_sha256'},
            'C2 execution decision has unreviewed or missing metadata')
    require(decision['schema'] == 'hcsn-c2-execution-decision-v1'
            and decision['execution_authorized'] is True
            and decision['contract_sha256'] == sha(contract_path)
            and decision['program_manifest_sha256'] == sha(program_manifest)
            and decision['scope'] == 'six-original-hcsn-c2-only'
            and decision['confirmation_E_access'] is False,
            'execution decision is not bound to this exact C2 candidate')
    return decision


def run_bound(bound, output, contract, policy_path, *, program_inputs=None,
              optimization_policy_path=None, process_started=None, production=True):
    """Optimize only a separately admitted context; tests use labelled tiny synthetic fixtures."""
    started = PROCESS_STARTED if process_started is None else process_started
    study, plan, prior = bound.study, bound.plan, bound.prior
    out = Path(output)
    out.mkdir(exist_ok=False)
    (out / 'checkpoints').mkdir()
    (out / 'commits').mkdir()
    program_inputs = program_inputs or {}
    torch.set_num_threads(plan['threads'])
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    parent_wall = bound.outer['whole_process_wall_seconds']
    budget = Budget(parent_wall, contract['cumulative_active_wall_seconds'], started,
        plan['rss_bytes'], contract['finalization_reserve_seconds'], study.peak_rss)
    report = {'schema': 'hcsn-c2-soft-wall-continuation-v1', 'status': 'started',
        'production_execution': production, 'scientific_admission': 'HOLD', 'numerical_admission': 'HOLD',
        'whole_training_domain': 'HOLD', 'confirmation_access': False,
        'fresh_independent_fits_started': 0, 'continuation_attempts_started': 1,
        'optimizer_update_count_scope': 'new_main_updates counts completed optimizer.step calls in this continuation; any unclosed call remains in events.jsonl',
        'parent': str(bound.parent), 'parent_status': prior['status'], 'parent_outer': bound.outer,
        'parent_report': bound.inputs.get(str(bound.parent / 'result.json')),
        'parent_full_outer_wall_charged': parent_wall, 'parent_full_process_cpu_seconds': None,
        'parent_recorded_fit_cpu_seconds': prior['cpu_seconds'],
        'parent_recorded_process_cpu_lower_bound_seconds': max([prior['cpu_seconds']] +
            [row['process_cpu_seconds'] for row in prior['epochs']]),
        'cpu_scope': 'new full process CPU prefix measured; original exit CPU unavailable; no exact cumulative CPU',
        'inherited_memorization': prior['memorization'], 'new_diagnostic_updates': 0,
        'arm': 'hcsn', 'seed': plan['seed'], 'learning_rate': plan['learning_rate'],
        'parent_retained_epochs': bound.boundary['retained_epochs'],
        'parent_work': bound.boundary['work'], 'refund_for_discarded_parent_work_seconds': 0,
        'cumulative_active_wall_cap_seconds': contract['cumulative_active_wall_seconds'],
        'maximum_cumulative_epochs': contract['maximum_epochs'],
        'retained_main_updates_at_resume': bound.boundary['work']['retained_main_updates'],
        'logical_main_updates': bound.boundary['work']['retained_main_updates'], 'new_main_updates': 0,
        'new_micro_forward_attempts': 0, 'epochs': [], 'cumulative_epochs_completed': bound.boundary['retained_epochs'],
        'model_configuration': bound.state['model_configuration'], 'source_before': prior['source_before'],
        'training_adequacy_established': False, 'energy_joules': None, 'peak_vram_bytes': None,
        'first_observed_quality_crossing_cumulative_wall_seconds': prior.get('process_time_to_quality_seconds'),
        'quality_threshold_macro_f1': plan['quality_threshold'], 'best_epoch': bound.boundary['stopping']['best_epoch'],
        'quality_clock_scope': 'first observed full-D evaluation; crossing between evaluations unknown',
        'cold_cache_reset': True, 'resumed_without_partial_work_loss': False}
    exclusive_json(out / 'ADMISSION.json', {'boundary': bound.boundary, 'eligibility': bound.eligibility,
        'inputs': bound.inputs, 'program_inputs': program_inputs, 'runtime': bound.runtime, 'contract': contract})
    journal = (out / 'events.jsonl').open('x')
    owner_start_id = os.environ.get('HCSN_C2_OWNER_START_ID', '')
    require(bool(owner_start_id), 'successor controller identity missing')
    model = optimizer = recorder = optimization_recorder = None
    order_rng = random.Random()
    stopping = copy.deepcopy(bound.boundary['stopping'])
    retained_epoch = bound.boundary['retained_epochs']
    last_path = best_path = None
    last_commit = None
    witness = None

    def event(kind, **values):
        # Existing epoch clocks override nothing: the same once-sampled row is written verbatim.
        row = {'kind': kind, **values}
        if 'phase_process_wall_seconds' not in row:
            row['phase_process_wall_seconds'] = budget.elapsed()
        append_receipt(out / 'runner-receipts', owner_start_id=owner_start_id,
                       attempt_id=out.name, event_type=kind, payload=row)
        journal.write(json.dumps(row, allow_nan=False) + '\n')
        journal.flush()
        os.fsync(journal.fileno())

    def evaluate(rows, *, retain=None, finalizing=False):
        model.eval()
        values, labels = [], []
        with torch.no_grad():
            for _, x, dt, y in study.batches(rows, list(range(len(rows))), plan['batch_size']):
                budget.check(finalizing=finalizing)
                logits = model(x, dt)
                values.append(logits[y >= 0])
                labels.append(y[y >= 0])
        logits, labels = torch.cat(values), torch.cat(labels)
        result = study.metrics(logits, labels)
        result['brier_mean_classes'] = result['brier_half_sum'] * (2 / 11)
        if retain:
            immutable_checkpoint(retain, {'logits': logits, 'labels': labels,
                'episode_ids': [r['id'] for r in rows]})
        return result

    try:
        budget.check()
        verify_files(bound.inputs)
        verify_files(program_inputs)
        if production:
            require(program_inputs, 'production execution has no frozen program identity')
            require(sha(policy_path) == contract['supplement_policy_sha256'], 'supplement policy differs from contract')
            prospective = Path(optimization_policy_path or Path(__file__).with_name('OPTIMIZATION-POSTERIOR-POLICY-v2.json'))
            require(sha(prospective) == contract['optimization_policy_sha256'], 'optimization policy differs from contract')
        model = study.CoreStudyModel(**bound.state['model_configuration'])
        model.load_state_dict(bound.state['model'], strict=True)
        optimizer, _ = study.adamw(model, plan['learning_rate'], 0.0)
        optimizer.load_state_dict(copy.deepcopy(bound.state['optimizer']))
        order_rng.setstate(bound.state['order_rng'])
        torch.set_rng_state(bound.state['torch_rng'])
        require(study.sources(model) == prior['source_before'], 'loaded v8 sources differ from original fit')
        verify_frozen(model, bound.initial)
        restored = snapshot(model, optimizer, order_rng, retained_epoch, report['logical_main_updates'], plan['manifest_sha256'])
        require(state_equal(restored, bound.state), 'actual restored model/optimizer/RNG differs from parent last')
        witness_path = out / 'resume-start.pt'
        witness_identity = immutable_checkpoint(witness_path, restored)
        reloaded = torch.load(witness_path, weights_only=True, map_location='cpu')
        require(state_equal(reloaded, bound.state), 'serialized resume-start differs from parent last')
        witness = {'schema': 'hcsn-c2-before-first-step-witness-v1', 'checkpoint': witness_identity,
            'parent_last': identity(bound.parent / 'last.pt'), 'semantic_sha256': semantic_digest(reloaded),
            'actual_restored_state_equal_parent_last': True, 'new_optimizer_steps_before_receipt': 0,
            'parent_complete_outer_wall_charged': parent_wall, 'discarded_parent_work': bound.boundary['work'],
            'source': study.sources(model), 'program_inputs': program_inputs,
            **epoch_clocks(parent_wall, started)}
        report['resume_start_receipt'] = exclusive_json(out / 'RESUME-START.json', witness)
        report['resume_start_checkpoint'] = witness_identity
        event('resume_start_committed', receipt=report['resume_start_receipt'], checkpoint=witness_identity)
        last_path = witness_path
        # Keep the inherited strict best in exact original bytes, without serialization drift.
        best_path = out / 'inherited-best.pt'
        with best_path.open('xb') as target, (bound.parent / 'best.pt').open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        require(identity(best_path) == identity(bound.parent / 'best.pt'), 'inherited best copy differs')
        atomic_alias(best_path, out / 'best.pt')
        atomic_alias(last_path, out / 'last.pt')
        policy = json.loads(Path(policy_path).read_bytes())
        recorder = ProgressRecorder(out / 'posterior-windows', bound, policy, policy_path, production=production)
        optimization_policy_path = Path(optimization_policy_path or Path(__file__).with_name('OPTIMIZATION-POSTERIOR-POLICY-v2.json'))
        optimization_policy = json.loads(optimization_policy_path.read_bytes())
        optimization_recorder = OptimizationRecorder(out / 'optimization-windows', bound,
            optimization_policy, optimization_policy_path, production=production)
        recorder.capture('resume-start', model, order_rng, last_path, epoch=retained_epoch,
            updates=report['logical_main_updates'], budget=budget.check)
        verify_files(bound.inputs)
        verify_files(program_inputs)
        targets = [y for row in bound.data['train'] for y in row['y']]
        require(sorted(set(targets)) == list(range(11)), 'complete original training support required')
        weights = torch.bincount(torch.tensor(targets), minlength=11).double().rsqrt()
        weights /= weights.mean()
        for epoch in range(retained_epoch + 1, contract['maximum_epochs'] + 1):
            budget.check()
            order = list(range(len(bound.data['train'])))
            order_rng.shuffle(order)
            event('epoch_started', epoch=epoch, episode_order=[bound.data['train'][i]['id'] for i in order])
            losses = []
            for batch_index, (ids, x, dt, y) in enumerate(study.batches(bound.data['train'], order, plan['batch_size'])):
                budget.check()
                model.train()
                optimizer.zero_grad(set_to_none=True)
                event('update_started', phase='main', episode_ids=ids)
                optimization_recorder.begin_batch(epoch, batch_index, ids, x, y, last_path, model,
                    report['logical_main_updates'], report['new_main_updates'])
                def before_forward(start, end):
                    budget.check()
                    report['new_micro_forward_attempts'] += 1
                    optimization_recorder.before_micro(model, start, end, ids, x, dt, y)
                try:
                    value = study.backward_effective_batch(model, x, dt, y, weights,
                        micro_batch_size=plan['micro_batch_size'], before_forward=before_forward)
                finally:
                    optimization_recorder.finish_pending(model)
                value['target_weight_sum'] = float(weights[y[y >= 0]].sum())
                value['weighted_loss_numerator'] = value['loss'] * value['target_weight_sum']
                active = [p for p in model.parameters() if p.requires_grad]
                require(all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in active),
                        'missing or nonfinite connected gradient')
                norm = torch.nn.utils.clip_grad_norm_(active, 1.0)
                require(bool(torch.isfinite(norm)), 'nonfinite clipped gradient norm')
                budget.check()
                require(witness is not None and identity(witness_path) == report['resume_start_checkpoint']
                        and identity(out / 'RESUME-START.json') == report['resume_start_receipt'],
                        'immutable first-step witness is absent or changed')
                event('optimizer_started', phase='main', logical_next_update=report['logical_main_updates'] + 1)
                optimizer.step()
                report['logical_main_updates'] += 1
                report['new_main_updates'] += 1
                event('optimizer_completed', phase='main', number=report['logical_main_updates'],
                      new_number=report['new_main_updates'], gradient_norm=float(norm), **value)
                optimization_recorder.mark_optimizer_completed(report['logical_main_updates'], report['new_main_updates'])
                losses.append(value)
            development = evaluate(bound.data['dev'])
            row = {'epoch': epoch, 'complete': True, 'events': sum(v['events'] for v in losses),
                'training_weighted_loss': study.aggregate_training_objectives(losses),
                'training_target_weight_sum': sum(v['target_weight_sum'] for v in losses),
                'training_weighted_loss_numerator': sum(v['weighted_loss_numerator'] for v in losses),
                'development': development, **epoch_clocks(parent_wall, started)}
            verify_frozen(model, bound.initial)
            require(study.sources(model) == prior['source_before'], 'source changed during C2')
            history = bound.boundary['logical_epochs'] + report['epochs'] + [row]
            next_stopping = plateau_state(history, plan['plateau_delta'])
            epoch_path = out / 'checkpoints' / f'epoch-{epoch:04d}.pt'
            item = immutable_checkpoint(epoch_path, snapshot(model, optimizer, order_rng,
                epoch, report['logical_main_updates'], plan['manifest_sha256']))
            next_best_path = epoch_path if next_stopping['best_epoch'] == epoch else best_path
            commit = {'schema': 'hcsn-c2-complete-epoch-commit-v1', 'epoch': row,
                'checkpoint_path': str(epoch_path), 'checkpoint': item,
                'best_path': str(next_best_path), 'best_checkpoint': identity(next_best_path),
                'stopping': next_stopping, 'previous_commit': last_commit,
                'logical_main_updates': report['logical_main_updates']}
            commit_path = out / 'commits' / f'epoch-{epoch:04d}.json'
            last_commit = {'path': str(commit_path), **exclusive_json(commit_path, commit)}
            # The complete boundary advances only after its immutable commit exists.
            report['epochs'].append(row)
            report['cumulative_epochs_completed'] = epoch
            stopping, best_path = next_stopping, next_best_path
            last_path = epoch_path
            report['last_checkpoint_sha256'] = atomic_alias(last_path, out / 'last.pt')['sha256']
            report['best_checkpoint_sha256'] = atomic_alias(best_path, out / 'best.pt')['sha256']
            report['best_epoch'] = stopping['best_epoch']
            event('epoch_completed', **row, commit=last_commit)
            if report['first_observed_quality_crossing_cumulative_wall_seconds'] is None and development['macro_f1_11_classes'] >= plan['quality_threshold']:
                report['first_observed_quality_crossing_cumulative_wall_seconds'] = row['cumulative_process_wall_seconds']
            if epoch in policy['absolute_complete_epoch_slots']:
                recorder.capture(f'epoch-{epoch:04d}', model, order_rng, last_path,
                    epoch=epoch, updates=report['logical_main_updates'], budget=budget.check)
            if epoch >= plan['min_epochs'] and stopping['stale_epochs'] >= plan['patience']:
                report['stop_reason'] = 'development_plateau'
                break
        report.setdefault('stop_reason', 'epoch_cap_not_convergence')
        report['status'] = 'training_phase_complete'
    except ResourceStop as error:
        report.update(status='budget_exhausted', error=str(error))
    except RecordingHold as error:
        report.update(status='recording_hold', error=str(error))
    except Exception:
        report.update(status='failed', error=traceback.format_exc())
    finally:
        # Preserve actual interrupted state before any terminal checkpoint replay.
        if model is not None and optimizer is not None and report['status'] != 'training_phase_complete':
            try:
                report['interrupted_checkpoint'] = immutable_checkpoint(out / 'interrupted.pt',
                    snapshot(model, optimizer, order_rng, report['cumulative_epochs_completed'],
                             report['logical_main_updates'], plan['manifest_sha256']))
            except Exception:
                report['interrupted_checkpoint_error'] = traceback.format_exc()
        if model is not None and best_path is not None:
            for slot, path in [('terminal-last', last_path), ('terminal-best', best_path)]:
                if recorder is None or path is None:
                    continue
                try:
                    budget.check(finalizing=True)
                    state = torch.load(path, weights_only=True, map_location='cpu')
                    model.load_state_dict(state['model'])
                    recorder.capture(slot, model, order_rng, path, epoch=state['epochs_completed'],
                        updates=state['main_updates'], budget=budget.check)
                except ResourceStop:
                    recorder.results[slot] = {'slot': slot, 'status': 'not_captured_budget'}
                    if report['status'] == 'training_phase_complete':
                        report['status'] = 'budget_exhausted_finalization'
                except Exception:
                    report.setdefault('terminal_observation_errors', []).append(traceback.format_exc())
                    report['status'] = 'recording_hold'
            try:
                budget.check(finalizing=True)
                model.load_state_dict(torch.load(best_path, weights_only=True, map_location='cpu')['model'])
                report['selected_development'] = evaluate(bound.data['dev'],
                    retain=out / 'development_logits.pt', finalizing=True)
                report['selected_development_logits'] = identity(out / 'development_logits.pt')
                if report['status'] == 'training_phase_complete':
                    report['status'] = 'completed_development'
            except ResourceStop:
                report['selected_development_status'] = 'not_completed_budget'
                if report['status'] == 'training_phase_complete':
                    report['status'] = 'budget_exhausted_finalization'
            except Exception:
                report.setdefault('finalization_errors', []).append(traceback.format_exc())
                report['status'] = 'failed'
        report['stopping'] = stopping
        report['last_commit'] = last_commit
        if last_path is not None:
            report['last_checkpoint_sha256'] = identity(last_path)['sha256']
        if best_path is not None:
            report['best_checkpoint_sha256'] = identity(best_path)['sha256']
        report['posterior_recording'] = recorder.summary(report['cumulative_epochs_completed']) if recorder else {'status': 'not_initialized'}
        report['actual_optimization_recording'] = optimization_recorder.summary(report['cumulative_epochs_completed']) if optimization_recorder else {'status': 'not_initialized'}
        report['actual_executed_main_updates_logged_all_phases'] = bound.boundary['work']['total_logged_main_optimizer_completions'] + report['new_main_updates']
        report['new_unretained_logged_updates'] = report['logical_main_updates'] - report['cumulative_epochs_completed'] * bound.boundary['work']['steps_per_epoch']
        try:
            verify_files(bound.inputs)
            verify_files(program_inputs)
            report['source_after'] = (study.sources(model) if model is not None
                else {name: sha(name) for name in report['source_before']})
            require(report['source_after'] == report['source_before'], 'loaded source changed at finalization')
            if model is not None:
                verify_frozen(model, bound.initial)
            report['source_and_parent_inputs_unchanged'] = True
            report['common_and_physical_weights_unchanged'] = True if model is not None else None
            report['live_model_restored'] = model is not None
        except Exception:
            report.update(status='source_or_parent_changed', source_and_parent_inputs_unchanged=False,
                          final_integrity_error=traceback.format_exc())
        report['training_adequacy_established'] = bool(report['status'] == 'completed_development'
            and report.get('stop_reason') == 'development_plateau' and prior['memorization']['passed'])
        if model is not None:
            report['frozen_table_cache'] = [layer.operator.cache_receipt() for layer in model.core.network.layers]
        report.update(**epoch_clocks(parent_wall, started), peak_rss_bytes=study.peak_rss())
        event('finished', status=report['status'])
        journal.close()
        report['events'] = identity(out / 'events.jsonl')
        exclusive_json(out / 'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent', type=Path, required=True)
    parser.add_argument('--outer', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--program-manifest', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--decision', type=Path)
    parser.add_argument('--decision-sha256')
    args = parser.parse_args()
    program_inputs = bind_program(args.program_manifest)
    require(str(args.contract.resolve()) in program_inputs and str(args.policy.resolve()) in program_inputs,
            'contract/policy is outside the frozen candidate manifest')
    contract = json.loads(args.contract.read_bytes())
    if args.execute:
        require_decision(args.decision, args.decision_sha256, args.contract, args.program_manifest)
        program_inputs[str(args.decision.resolve())] = identity(args.decision)
    bound = bind_parent(args.parent, args.outer, args.source, contract)
    if not args.execute:
        args.output.mkdir(exist_ok=False)
        exclusive_json(args.output / 'VALIDATION.json', {'boundary': bound.boundary,
            'eligibility': bound.eligibility, 'inputs': bound.inputs, 'program_inputs': program_inputs,
            'real_optimizer_steps': 0, 'execution_authorized': False,
            'phase_process_wall_seconds': time.monotonic() - PROCESS_STARTED,
            'phase_process_cpu_seconds': time.process_time()})
        return 0
    report = run_bound(bound, args.output, contract, args.policy, program_inputs=program_inputs)
    return 0 if report['status'] == 'completed_development' else 2


if __name__ == '__main__':
    raise SystemExit(main())
