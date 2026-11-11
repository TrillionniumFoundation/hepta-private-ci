"""C2 boundary and terminal guards. This is not a training or snapshot runner.

Callers must separately bind byte hashes of source, plan, data, checkpoints,
journal, terminal result and outer process receipt. Passing these structural
checks alone never authorizes a run or grants scientific/numerical credit.
"""
import math
import random

import torch


class Ineligible(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Ineligible(reason)


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def expected_configuration(plan):
    require(plan['arm'] == 'hcsn', 'C2 proposal is restricted to original HCSN fits')
    return {'arm': 'hcsn', 'width': plan['width'], 'seed': plan['seed'],
        's4_repo': str(plan['s4_repo']) if plan['s4_repo'] is not None else None,
        'hcsn_grid': plan['hcsn_grid_json'], 'freeze_shared': not plan['train_shared'],
        'cache_frozen_tables': plan['cache_frozen_tables'],
        'learn_core_adapter': plan['learn_core_adapter'], 'plif_configuration': None}


def plateau_state(epochs, delta):
    best, best_epoch, anchor, stale = -1.0, None, -1.0, 0
    for number, row in enumerate(epochs, 1):
        require(row['epoch'] == number and row['complete'] is True, 'noncontiguous complete epoch prefix')
        score = row['development']['macro_f1_11_classes']
        require(finite_number(score) and 0 <= score <= 1, 'invalid development score')
        if score > best:
            best, best_epoch = score, number
        if score > anchor + delta:
            anchor, stale = score, 0
        else:
            stale += 1
    return {'best': best, 'best_epoch': best_epoch, 'plateau_anchor': anchor, 'stale_epochs': stale}


def first_plateau_epoch(epochs, delta, min_epochs, patience):
    """Find the first original stopping event, even if later scores improve."""
    require(type(min_epochs) is int and min_epochs > 0
            and type(patience) is int and patience > 0, 'invalid original stopping rule')
    anchor, stale = -1.0, 0
    for number, row in enumerate(epochs, 1):
        require(row['epoch'] == number and row['complete'] is True, 'noncontiguous stopping history')
        score = row['development']['macro_f1_11_classes']
        require(finite_number(score) and 0 <= score <= 1, 'invalid stopping-history score')
        if score > anchor + delta:
            anchor, stale = score, 0
        else:
            stale += 1
        if number >= min_epochs and stale >= patience:
            return number
    return None


def journal_boundary(events, plan, episodes, anchor_epoch, order_state):
    """Validate exact dataset ordering/batches and count retained/discarded work."""
    ids = [row['id'] for row in episodes]
    counts = {row['id']: len(row['y']) for row in episodes}
    require(len(ids) == len(set(ids)) and ids, 'empty or duplicate training episode identities')
    batch_size = plan['batch_size']
    require(type(batch_size) is int and batch_size > 0, 'invalid effective batch size')
    steps = math.ceil(len(ids) / batch_size)
    rng = random.Random(plan['seed'])
    completed, updates, current, pending, stepped, batch_index = [], 0, None, None, False, 0
    expected_batches, boundary_rng, last_times = [], None, (0.0, 0.0)
    for row in events:
        kind = row['kind']
        if kind == 'epoch_started':
            require(current is None and pending is None, 'epoch started before prior epoch completed')
            current = len(completed) + 1
            require(row['epoch'] == current, 'epoch numbering changed')
            order = list(range(len(ids)))
            rng.shuffle(order)
            ordered = [ids[i] for i in order]
            require(row['episode_order'] == ordered, 'epoch order differs from seed and saved order RNG')
            expected_batches = [ordered[i:i+batch_size] for i in range(0, len(ids), batch_size)]
            batch_index = 0
        elif kind == 'update_started' and row.get('phase') == 'main':
            require(current is not None and pending is None and batch_index < steps,
                    'main update outside declared epoch/batch')
            pending = row['episode_ids']
            require(pending == expected_batches[batch_index], 'main batch differs from declared full epoch order')
            stepped = False
        elif kind == 'optimizer_started' and row.get('phase') == 'main':
            require(pending is not None and not stepped, 'optimizer start without exactly one pending main batch')
            stepped = True
        elif kind == 'optimizer_completed' and row.get('phase') == 'main':
            require(pending is not None and stepped, 'optimizer completion without matching start')
            updates += 1
            require(row['number'] == updates, 'optimizer update counter skipped or repeated')
            require(row['events'] == sum(counts[i] for i in pending), 'optimizer event count differs')
            require(finite_number(row['loss']) and finite_number(row['gradient_norm']), 'nonfinite recorded update')
            require(row['gradient_norm'] >= 0, 'negative gradient norm')
            micro = plan.get('micro_batch_size') or batch_size
            require(row['micro_forward_calls'] == math.ceil(len(pending) / micro), 'microbatch calls differ')
            pending, stepped = None, False
            batch_index += 1
        elif kind == 'epoch_completed':
            require(current == row['epoch'] and pending is None and batch_index == steps,
                    'epoch completed without every complete optimizer batch')
            require(row.get('complete') is True and row['events'] == sum(counts.values()),
                    'complete epoch does not cover complete training event population')
            wall, cpu = row['process_wall_seconds'], row['process_cpu_seconds']
            require(finite_number(wall) and finite_number(cpu) and wall >= last_times[0] and cpu >= last_times[1],
                    'epoch process wall/CPU counters are invalid or decrease')
            last_times = wall, cpu
            completed.append(row)
            if current == anchor_epoch:
                boundary_rng = rng.getstate()
            current = None
    require(type(anchor_epoch) is int and 1 <= anchor_epoch <= len(completed), 'no complete journal prefix for checkpoint')
    require(order_state == boundary_rng, 'saved order RNG is not the declared epoch boundary')
    retained = anchor_epoch * steps
    return {'epochs': completed[:anchor_epoch], 'all_complete_epochs': completed,
        'retained_main_updates': retained, 'completed_updates_after_anchor': updates - retained,
        'complete_epochs_after_anchor': len(completed) - anchor_epoch,
        'optimizer_step_in_flight': bool(pending is not None and stepped),
        'unclosed_forward_or_backward': bool(pending is not None and not stepped),
        'inflight_optimizer_updates_unknown_interval': [0, 1] if pending is not None and stepped else [0, 0],
        'steps_per_epoch': steps, 'total_logged_main_optimizer_completions': updates}


def validate_checkpoint(state, configuration, expected_updates, expected_epochs, initial, model_factory, optimizer_factory, lr):
    require(state.get('model_configuration') == configuration, 'checkpoint full model configuration differs')
    require(state.get('epochs_completed') == expected_epochs and state.get('main_updates') == expected_updates,
            'checkpoint is not a complete epoch boundary; partial interrupted checkpoint forbidden')
    model = model_factory(**configuration)
    require(initial.get('model_configuration') == configuration, 'initial checkpoint configuration differs')
    fresh = model.state_dict()
    require(fresh.keys() == initial['model'].keys() == state['model'].keys(), 'checkpoint parameter/buffer names differ')
    for name, tensor in fresh.items():
        require(torch.equal(tensor, initial['model'][name]), 'initial bytes differ from independently reconstructed seed/config')
    frozen = {name for name, parameter in model.named_parameters() if not parameter.requires_grad}
    frozen.update(name for name, _ in model.named_buffers())
    for name, value in state['model'].items():
        require(value.dtype == fresh[name].dtype and value.shape == fresh[name].shape, 'model tensor dtype/shape changed')
        require(bool(torch.isfinite(value).all()), 'nonfinite checkpoint tensor')
        if name in frozen:
            require(torch.equal(value, initial['model'][name]), 'frozen shared/physics/buffer bytes changed')
    model.load_state_dict(state['model'], strict=True)
    optimizer, _ = optimizer_factory(model, lr, 0.0)
    require(state.get('optimizer') is not None, 'optimizer state missing')
    desired = optimizer.state_dict()['param_groups']
    observed = state['optimizer'].get('param_groups', [])
    require(len(desired) == len(observed), 'optimizer groups differ')
    for left, right in zip(desired, observed):
        require(left == right, 'optimizer parameter ordering or hyperparameters differ')
    optimizer.load_state_dict(state['optimizer'])
    active = [p for group in optimizer.param_groups for p in group['params']]
    require(len(optimizer.state) == len(active), 'optimizer state missing a connected trainable parameter')
    for parameter in active:
        item = optimizer.state[parameter]
        require(set(item) == {'step', 'exp_avg', 'exp_avg_sq'}, 'unexpected AdamW state fields')
        require(float(item['step']) == expected_updates, 'optimizer moment age differs from main update count')
        for name in ('exp_avg', 'exp_avg_sq'):
            require(item[name].shape == parameter.shape and item[name].dtype == parameter.dtype,
                    'optimizer moment dtype/shape differs')
            require(bool(torch.isfinite(item[name]).all()), 'nonfinite optimizer moment')
        require(bool((item['exp_avg_sq'] >= 0).all()), 'negative AdamW second moment')
    try:
        torch.Generator(device='cpu').set_state(state['torch_rng'])
        random.Random().setstate(state['order_rng'])
    except Exception as error:
        raise Ineligible('invalid Torch or order RNG state') from error


def validate_boundary(*, checkpoint, best, initial, events, plan, episodes, model_factory,
                      optimizer_factory, candidate_origin):
    require(candidate_origin in ('last.pt', 'immutable_snapshot_of_last.pt'), 'candidate is not original atomic last checkpoint')
    require(plan['train_shared'] is False and plan['cache_frozen_tables'] is True,
            'shared/physics/cache regime changed')
    configuration = expected_configuration(plan)
    require(checkpoint.get('data_manifest_sha256') == plan['manifest_sha256']
            and best.get('data_manifest_sha256') == plan['manifest_sha256'], 'checkpoint data identity differs')
    journal = journal_boundary(events, plan, episodes, checkpoint['epochs_completed'], checkpoint['order_rng'])
    stopping = plateau_state(journal['epochs'], plan['plateau_delta'])
    validate_checkpoint(checkpoint, configuration, journal['retained_main_updates'], checkpoint['epochs_completed'],
                        initial, model_factory, optimizer_factory, plan['learning_rate'])
    require(best['epochs_completed'] == stopping['best_epoch'],
            'best checkpoint is not strict prefix argmax; possibly overwritten ahead of last')
    validate_checkpoint(best, configuration, stopping['best_epoch'] * journal['steps_per_epoch'], stopping['best_epoch'],
                        initial, model_factory, optimizer_factory, plan['learning_rate'])
    return {'schema': 'c2-structural-boundary-validation-v1', 'boundary_structurally_consistent': True,
        'terminal_eligibility_checked': False, 'execution_authorized': False,
        'scientific_training_credit': False, 'candidate_origin': candidate_origin,
        'retained_epochs': checkpoint['epochs_completed'], 'stopping': stopping,
        'work': {k:v for k,v in journal.items() if k not in ('epochs', 'all_complete_epochs')},
        'logical_epochs': journal['epochs'], 'all_complete_epochs': journal['all_complete_epochs'],
        'byte_identity_status': 'separate verified file-hash/source/runtime contract required'}


def terminal_guard(*, outer, report, plan, boundary, max_active_wall=43200.0, max_epochs=200):
    """Conservative soft-wall path only. Hard-kill/missing result remains HOLD."""
    require(report is not None, 'terminal result missing; wall-only cause unproven')
    require(outer.get('status') == 'failed' and outer.get('returncode') == 2
            and outer.get('fit_status') == 'budget_exhausted', 'not a reported soft budget exhaustion')
    require(report.get('status') == 'budget_exhausted', 'parent result has another cause')
    require(report.get('error') == 'declared resource limit; not convergence', 'unexpected parent failure detail')
    require(report.get('source_unchanged') is True and report.get('common_weights_unchanged') is True,
            'parent source/shared evidence did not remain exact')
    require(report.get('stop_reason') != 'development_plateau', 'plateau already reached; finalization only, not C2 training')
    require(report.get('memorization', {}).get('passed') is True, 'original diagnostic has not passed; do not rerun it')
    require(finite_number(report.get('wall_seconds')) and report['wall_seconds'] >= plan['wall_seconds'],
            'wall trigger not proven from original inner clock')
    require(finite_number(report.get('peak_rss_bytes')) and report['peak_rss_bytes'] <= plan['rss_bytes'],
            'RSS trigger not excluded')
    require(boundary.get('boundary_structurally_consistent') is True, 'boundary did not pass')
    require(boundary['work']['complete_epochs_after_anchor'] == 0
            and len(report.get('epochs', [])) == boundary['retained_epochs'],
            'v1 terminal path requires latest complete epoch; older snapshot needs an explicit rollback protocol')
    for parent_row, log_row in zip(report['epochs'], boundary['logical_epochs']):
        require(parent_row == {k:v for k,v in log_row.items() if k != 'kind'}, 'parent report and epoch journal differ')
    require(report['main_updates'] == boundary['work']['total_logged_main_optimizer_completions'],
            'parent main update count and journal differ')
    state = plateau_state(boundary['logical_epochs'], plan['plateau_delta'])
    require(state == boundary['stopping'], 'supplied stopping state does not match its epoch history')
    first_stop = first_plateau_epoch(boundary['logical_epochs'], plan['plateau_delta'],
                                    plan['min_epochs'], plan['patience'])
    require(first_stop is None, 'original stopping rule already reached plateau in the retained history')
    spent = outer.get('whole_process_wall_seconds')
    ceiling = outer.get('hard_wall_seconds')
    require(finite_number(spent) and finite_number(ceiling) and spent > 0 and 0 < ceiling <= 14400,
            'original actual wall accounting missing or invalid')
    require(finite_number(max_active_wall) and ceiling <= max_active_wall <= 43200,
            'C2 active wall cap exceeds proposal')
    require(type(max_epochs) is int and boundary['retained_epochs'] < max_epochs <= 200,
            'C2 cumulative epoch ceiling invalid')
    require(max_active_wall > spent, 'no remaining cumulative active wall')
    return {'schema': 'c2-soft-wall-eligibility-v2', 'structural_terminal_checks_passed': True,
        'execution_authorized': False, 'source_data_runtime_hash_contract_still_required': True,
        'cumulative_active_wall_cap_seconds': max_active_wall, 'original_full_outer_wall_charged': spent,
        'remaining_before_c2_setup_and_validation_seconds': max_active_wall - spent,
        'cumulative_logical_epoch_cap': max_epochs, 'new_diagnostics': False, 'new_learning_rates': False,
        'rolled_back_logged_updates': boundary['work']['completed_updates_after_anchor'],
        'refund_for_discarded_parent_work_seconds': 0,
        'equal_resource_view': 'original phase/cutoffs remain unchanged', 'scientific_admission': 'HOLD'}
