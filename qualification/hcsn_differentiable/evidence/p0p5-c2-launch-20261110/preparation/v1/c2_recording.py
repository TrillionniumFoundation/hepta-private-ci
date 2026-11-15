"""Bounded, progress-spaced observation of actual C2 checkpoint posteriors."""
import copy
import json
from pathlib import Path
import time
import traceback

import torch

from c2_boundary import require
from c2_io import exclusive_json, identity, semantic_digest, state_equal


class RecordingHold(RuntimeError):
    pass


def scheduled_slots(policy):
    return ['resume-start'] + [f'epoch-{e:04d}' for e in policy['absolute_complete_epoch_slots']] + ['terminal-last', 'terminal-best']


def validate_policy(policy, bound, *, production=True):
    require(policy['data_manifest_sha256'] == bound.plan['manifest_sha256'], 'posterior policy data differs')
    require(policy['batch_size'] == 1 and policy['dtype'] == 'float64'
            and policy['device'] == 'cpu' and policy['grad_enabled'] is False,
            'posterior observation layout changed')
    require(policy['confirmation_E_access'] is False and policy['optimizer_steps'] == 0,
            'posterior observation must not score E or optimize')
    slots = policy['absolute_complete_epoch_slots']
    require(slots == sorted(set(slots)) and all(type(e) is int and 1 <= e <= 200 for e in slots),
            'invalid posterior epoch schedule')
    require(len(scheduled_slots(policy)) == policy['maximum_slots_per_fit'], 'posterior slot budget differs')
    require(policy['maximum_records_per_episode'] >= max(r['events'] for r in policy['episodes']),
            'posterior record budget cannot cover the declared episode')
    require(65536 <= policy['maximum_bytes_per_episode'] <= 8 * 1024**2,
            'posterior per-episode byte cap exceeds frozen design')
    require(0 < policy['per_window_soft_wall_seconds'] <= 120, 'posterior window time cap differs')
    if production:
        require(slots == [50, 75, 100, 125, 150, 175, 200]
                and [r['id'] for r in policy['episodes']] == ['A01-0', 'A01-256', 'A04-3072']
                and all(r['events'] == 256 for r in policy['episodes'])
                and policy['maximum_records_per_episode'] == 256,
                'production posterior schedule is not the frozen three-episode policy')
    rows = {r['id']: r for r in bound.data['train']}
    prepared = Path(bound.plan['prepared']).resolve()
    seen = set()
    result = []
    for entry in policy['episodes']:
        require(entry['id'] not in seen and entry['id'] in rows, 'posterior episode missing or duplicated')
        seen.add(entry['id'])
        path = (prepared / entry['path']).resolve()
        require(path.is_relative_to(prepared) and not path.is_symlink(), 'posterior path escapes data root')
        require(identity(path)['sha256'] == entry['sha256'], 'posterior episode bytes differ')
        row = rows[entry['id']]
        require(len(row['y']) == entry['events'] and json.loads(path.read_bytes()) == row,
                'posterior row differs from its bound original bytes')
        result.append(row)
    return result


def gradient_state(model):
    return {name: None if parameter.grad is None else parameter.grad.detach().clone()
            for name, parameter in model.named_parameters()}


class ProgressRecorder:
    """Separate no-grad captures; never reconnect or append the old training trace."""
    def __init__(self, output, bound, policy, policy_path, *, production=True):
        self.root = Path(output)
        self.root.mkdir(exist_ok=False)
        self.bound, self.policy = bound, copy.deepcopy(policy)
        self.rows = validate_policy(policy, bound, production=production)
        self.policy_identity = identity(policy_path)
        self.results = {}

    def capture(self, slot, model, order_rng, checkpoint_path, *, epoch, updates, budget):
        from qualification.hcsn_differentiable.training_domain import TrainingDomainRecorder, read_trace

        require(slot in scheduled_slots(self.policy) and slot not in self.results,
                'posterior slot unplanned or already observed')
        budget(finalizing=slot.startswith('terminal-'))
        directory = self.root / slot
        directory.mkdir(exist_ok=False)
        started, cpu = time.monotonic(), time.process_time()
        checkpoint_identity = identity(checkpoint_path)
        state = torch.load(checkpoint_path, weights_only=True, map_location='cpu')
        require(state_equal(model.state_dict(), state['model']), 'posterior live state differs from supplied checkpoint')
        before_model = semantic_digest(model.state_dict())
        before_grad = gradient_state(model)
        before_torch, before_order = torch.get_rng_state().clone(), order_rng.getstate()
        modes = [(module, module.training) for module in model.modules()]
        old_recorder, old_context = model.core.recorder, model.core.record_context
        sources_before = self.bound.study.sources(model)
        receipt = {'schema': 'hcsn-c2-posterior-window-v1', 'slot': slot, 'status': 'started',
            'epoch': epoch, 'logical_main_updates': updates, 'checkpoint_path': str(checkpoint_path),
            'checkpoint': checkpoint_identity, 'configuration': state['model_configuration'],
            'model_semantic_sha256': before_model, 'policy': self.policy_identity,
            'data_manifest_sha256': self.bound.plan['manifest_sha256'], 'source_before': sources_before,
            'scope': 'separate evaluation posteriors at this exact checkpoint; not all optimization states',
            'whole_training_domain': 'HOLD', 'numerical_admission': 'HOLD', 'confirmation_access': False,
            'episodes': [], 'optimizer_steps': 0}
        try:
            model.eval()
            with torch.no_grad():
                for entry, row in zip(self.policy['episodes'], self.rows):
                    budget(finalizing=slot.startswith('terminal-'))
                    if time.monotonic() - started >= self.policy['per_window_soft_wall_seconds']:
                        raise RecordingHold('posterior window soft wall exceeded')
                    path = directory / (entry['id'] + '.jsonl')
                    recorder = TrainingDomainRecorder(path, data_sha256=self.bound.plan['manifest_sha256'],
                        configuration_sha256=self.policy_identity['sha256'],
                        max_records=self.policy['maximum_records_per_episode'],
                        max_bytes=self.policy['maximum_bytes_per_episode'])
                    model.core.recorder = recorder
                    model.core.record_context = {'episode_id': entry['id'], 'update_index': updates}
                    try:
                        _, x, dt, _ = next(self.bound.study.batches([row], [0], 1))
                        model(x, dt)
                    finally:
                        recorder.close()
                        model.core.recorder = None
                    header, visits, footer, digest = read_trace(path)
                    receipt['episodes'].append({'episode': entry, 'trace': identity(path), 'footer': footer})
                    require(header['data_sha256'] == self.bound.plan['manifest_sha256']
                            and header['configuration_sha256'] == self.policy_identity['sha256']
                            and footer['source_unchanged'] and not footer['truncated']
                            and footer['seen_records'] == entry['events']
                            and footer['retained_records'] == entry['events']
                            and len(visits) == entry['events']
                            and footer['captures'] == 1 and footer['padded_states_excluded'] == 0,
                            'posterior capture incomplete, truncated, or source changed')
                    require([v['position'] for v in visits] == list(range(entry['events']))
                            and all(v['episode_id'] == entry['id'] and v['batch_indices'] == [0] for v in visits),
                            'posterior positions/episode/batch coverage differs')
            require(time.monotonic() - started <= self.policy['per_window_soft_wall_seconds'],
                    'posterior window soft wall exceeded')
            receipt['status'] = 'captured_complete_window'
        except Exception:
            receipt.update(status='recording_hold', error=traceback.format_exc())
        finally:
            model.core.recorder, model.core.record_context = old_recorder, old_context
            for module, mode in modes:
                module.training = mode
            receipt['neutrality'] = {
                'model_unchanged': semantic_digest(model.state_dict()) == before_model,
                'existing_gradients_unchanged': state_equal(gradient_state(model), before_grad),
                'torch_rng_unchanged': torch.equal(torch.get_rng_state(), before_torch),
                'order_rng_unchanged': order_rng.getstate() == before_order,
                'training_modes_restored': all(module.training == mode for module, mode in modes),
                'checkpoint_bytes_unchanged': identity(checkpoint_path) == checkpoint_identity}
            # Even a failing observation must not leak RNG consumption to a later action.
            torch.set_rng_state(before_torch)
            order_rng.setstate(before_order)
            receipt['source_after'] = self.bound.study.sources(model)
            receipt['source_unchanged'] = sources_before == receipt['source_after']
            if not all(receipt['neutrality'].values()) or not receipt['source_unchanged']:
                receipt['status'] = 'recording_hold'
            receipt.update(wall_seconds=time.monotonic() - started,
                cpu_seconds=time.process_time() - cpu, peak_rss_bytes=self.bound.study.peak_rss())
            receipt['receipt'] = exclusive_json(directory / 'RESULT.json', receipt)
            self.results[slot] = receipt
        if receipt['status'] != 'captured_complete_window':
            raise RecordingHold('posterior slot failed: ' + slot)
        return receipt

    def summary(self, epochs_completed):
        rows = []
        for slot in scheduled_slots(self.policy):
            if slot in self.results:
                rows.append(self.results[slot])
            else:
                epoch = int(slot[6:]) if slot.startswith('epoch-') else None
                status = 'not_reached' if epoch is not None and epoch > epochs_completed else 'not_captured'
                rows.append({'slot': slot, 'status': status})
        return {'policy': self.policy_identity, 'slots': rows,
                'whole_training_domain': 'HOLD', 'numerical_admission': 'HOLD'}


class OptimizationRecorder:
    """Observe scheduled real gradient microbatches through the unchanged core recorder."""
    def __init__(self, output, bound, policy, policy_path, *, production=True):
        self.root = Path(output)
        self.root.mkdir(exist_ok=False)
        self.bound, self.policy = bound, copy.deepcopy(policy)
        self.policy_identity = identity(policy_path)
        require(policy['data_manifest_sha256'] == bound.plan['manifest_sha256']
                and policy['grad_enabled'] is True and policy['confirmation_E_access'] is False,
                'actual-optimization trace policy differs')
        require(policy['absolute_epoch_slots'] == sorted(set(policy['absolute_epoch_slots']))
                and policy['maximum_slots_per_fit'] == 1 + len(policy['absolute_epoch_slots'])
                and 65536 <= policy['maximum_bytes_per_slot'] <= 32 * 1024**2,
                'invalid actual-optimization trace budget/schedule')
        if production:
            require(policy['absolute_epoch_slots'] == [50, 75, 100, 125, 150, 175, 200]
                    and policy['maximum_records_per_slot'] == 256
                    and bound.plan['micro_batch_size'] == 8 and bound.plan['batch_size'] == 32,
                    'production optimization trace geometry changed')
        self.pending = None
        self.current = None
        self.results = {}
        self.first_epoch = bound.boundary['retained_epochs'] + 1

    def begin_batch(self, epoch, batch_index, ids, x, y, checkpoint_path, model,
                    logical_updates, new_updates):
        require(self.pending is None, 'previous optimizer trace not closed')
        self.current = None
        if batch_index != 0:
            return
        labels = []
        if epoch == self.first_epoch:
            labels.append('resume-first-main-microbatch')
        if epoch in self.policy['absolute_epoch_slots']:
            labels.append(f'epoch-{epoch:04d}-first-main-microbatch')
        if not labels:
            return
        require(not any(label in self.results for label in labels), 'optimization slot repeated')
        slot = f'epoch-{epoch:04d}-first-main-microbatch'
        directory = self.root / slot
        directory.mkdir(exist_ok=False)
        state = torch.load(checkpoint_path, weights_only=True, map_location='cpu')
        require(state_equal(model.state_dict(), state['model']), 'actual optimization state differs from prior complete boundary')
        self.current = {'directory': directory, 'labels': labels, 'slot': slot,
            'epoch': epoch, 'effective_batch_index': batch_index, 'effective_batch_episode_ids': ids,
            'checkpoint_path': str(checkpoint_path), 'checkpoint': identity(checkpoint_path),
            'model_semantic_sha256': semantic_digest(model.state_dict()),
            'model_configuration': model.construction_configuration,
            'logical_completed_updates_before_step': logical_updates,
            'actual_logged_main_updates_before_step': self.bound.boundary['work']['total_logged_main_optimizer_completions'] + new_updates,
            'source_before': self.bound.study.sources(model), 'policy': self.policy_identity,
            'data_manifest_sha256': self.bound.plan['manifest_sha256'],
            'scope': 'actual main gradient microbatch; no separate replay',
            'whole_training_domain': 'HOLD', 'numerical_admission': 'HOLD',
            'optimizer_step_completed': False, 'status': 'scheduled',
            'effective_batch_valid_mask_sha256': semantic_digest(y >= 0)}

    def before_micro(self, model, start, end, ids, x, y):
        self.finish_pending(model)
        if self.current is None or start != 0:
            return
        from qualification.hcsn_differentiable.training_domain import TrainingDomainRecorder
        require(torch.is_grad_enabled() and model.training, 'optimization capture is outside actual gradient training')
        require(model.core.recorder is None, 'another recorder is already attached')
        row = self.current
        row.update(microbatch_range=[start, end], microbatch_episode_ids=ids[start:end],
            padded_events=x.shape[1], expected_rows=int((y[start:end] >= 0).any(0).sum()),
            microbatch_valid_mask_sha256=semantic_digest(y[start:end] >= 0),
            capture_grad_enabled=True, started_wall=time.monotonic(), started_cpu=time.process_time())
        require(torch.equal(x[start:end, :, 12:24].bool().any(-1), y[start:end] >= 0),
                'observed-mask and labelled-event validity differ')
        row['path'] = row['directory'] / 'trace.jsonl'
        recorder = TrainingDomainRecorder(row['path'], data_sha256=self.bound.plan['manifest_sha256'],
            configuration_sha256=self.policy_identity['sha256'],
            max_records=self.policy['maximum_records_per_slot'], max_bytes=self.policy['maximum_bytes_per_slot'])
        model.core.recorder = recorder
        model.core.record_context = {'episode_id': '+'.join(ids[start:end]),
                                    'update_index': row['logical_completed_updates_before_step']}
        self.pending = recorder

    def finish_pending(self, model):
        if self.pending is None:
            return
        from qualification.hcsn_differentiable.training_domain import read_trace
        row, recorder = self.current, self.pending
        self.pending = None
        model.core.recorder = None
        model.core.record_context = None
        error = None
        try:
            recorder.close()
            header, visits, footer, _ = read_trace(row['path'])
            row.update(trace=identity(row['path']), footer=footer)
            require(header['data_sha256'] == self.bound.plan['manifest_sha256']
                    and header['configuration_sha256'] == self.policy_identity['sha256']
                    and footer['source_unchanged'] and not footer['truncated']
                    and footer['captures'] == 1 and footer['seen_records'] == row['expected_rows']
                    and len(visits) == row['expected_rows'], 'actual optimization capture truncated or incomplete')
            require(all(v['update_index'] == row['logical_completed_updates_before_step']
                        and v['episode_id'] == '+'.join(row['microbatch_episode_ids']) for v in visits),
                    'actual optimization update/sample identity differs')
            require(semantic_digest(model.state_dict()) == row['model_semantic_sha256'],
                    'parameters changed before optimization trace closed')
            require(self.bound.study.sources(model) == row['source_before'], 'optimization trace source changed')
            row['status'] = 'captured_actual_gradient_microbatch'
        except Exception:
            row.update(status='recording_hold', error=traceback.format_exc())
            error = RecordingHold('actual optimizer trace incomplete: ' + row['slot'])
        finally:
            row.update(wall_seconds=time.monotonic() - row['started_wall'],
                       cpu_seconds=time.process_time() - row['started_cpu'])
            saved = {k: str(v) if isinstance(v, Path) else v for k, v in row.items()}
            row['receipt'] = exclusive_json(row['directory'] / 'CAPTURE.json', saved)
            for label in row['labels']:
                self.results[label] = row
        if error:
            raise error

    def mark_optimizer_completed(self, logical_step, new_step):
        if self.current is None:
            return
        row = self.current
        require(row.get('status') == 'captured_actual_gradient_microbatch', 'optimizer step lacks a complete scheduled capture')
        require(logical_step == row['logical_completed_updates_before_step'] + 1, 'recorded step index differs')
        item = {'schema': 'hcsn-c2-captured-optimizer-step-completed-v1', 'slot': row['slot'],
            'capture': row['receipt'], 'logical_step': logical_step, 'new_step': new_step,
            'optimizer_step_completed': True}
        row['optimizer_completion'] = exclusive_json(row['directory'] / 'STEP-COMPLETED.json', item)
        row['optimizer_step_completed'] = True
        self.current = None

    def summary(self, epochs_completed):
        labels = ['resume-first-main-microbatch'] + [f'epoch-{e:04d}-first-main-microbatch' for e in self.policy['absolute_epoch_slots']]
        rows = []
        for label in labels:
            if label in self.results:
                row = self.results[label]
                rows.append({'label': label, **{k: str(v) if isinstance(v, Path) else v for k, v in row.items()}})
            else:
                epoch = self.first_epoch if label.startswith('resume') else int(label.split('-')[1])
                rows.append({'label': label, 'status': 'not_reached' if epoch > epochs_completed else 'not_captured'})
        return {'policy': self.policy_identity, 'slots': rows, 'whole_training_domain': 'HOLD', 'numerical_admission': 'HOLD'}
