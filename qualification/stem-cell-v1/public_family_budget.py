"""Public-task family split under a common train+transition formula budget.

A single budget boundary is fixed before training. Only training residuals may
trigger the split. Direct32 and split reset AdamW at that boundary, not at equal
update counts. Rejecting growth keeps the failed arm, never a renamed direct run.
No NDU, multigeneration/retention or 421M claim is implied by geometry recipes.
"""
from __future__ import annotations

import math
import torch
from torch import nn

from budgeted_learning import step_upper_bound, train_to_budget, used_training_work
from family_routing import FamilyCellBank, transition_parity, ROUTING_PROFILE
from matrix_bank import CellBank, state_digest

TOPOLOGIES = (('family_direct32', 32, 2), ('family_split16to32', 32, 2))
POLICY_SCHEMA = 'hepta.public-family-budget-policy.v1'


class FamilyBudgetRejected(ValueError):
    """A measured but inadmissible split is retained, never relabeled as direct."""
    def __init__(self, report):
        super().__init__(report['reason'])
        self.report = report


def policy():
    # Fixed experiment definition, not tuned after viewing validation/final labels.
    return dict(schema=POLICY_SCHEMA, first_stage_fraction_ppm=400000,
                loss_threshold=0.05, gate_noise_scale=0.001, sibling_loss_weight=0.1,
                transition_atol=1e-6, transition_rtol=1e-5,
                max_live_parameter_multiplier=2, optimizer_reset_count=1)


def make_bank(dimension, profile, study, topology):
    if topology not in {r[0] for r in TOPOLOGIES} or study['width_units'] % 2:
        raise ValueError('registered family topology and even width required')
    if topology == 'family_direct32':
        return FamilyCellBank(dimension, 4, profile, study['width_units'],
                              sibling_loss_weight=study['family_policy']['sibling_loss_weight'])
    parent = {**profile, 'logical_cells': 16, 'initial_logical_cells': 16}
    return CellBank(dimension, 4, parent, study['width_units']//2)


def split_candidate(parent, study, *, parameter_cap):
    """Copy independent Heads; keep parent group mass and check parity separately."""
    if type(parent) is not CellBank or len(parent.heads) != 16 or parent.top_k != 2:
        raise ValueError('exact 16-parent source required')
    count = sum(p.numel() for p in parent.parameters())
    if type(parameter_cap) is not int or 3*count > parameter_cap:
        raise ValueError('parent+successor exceeds live model-parameter budget')
    profile = dict(logical_cells=32, initial_logical_cells=32, split=False, ndu=False,
        resident_stem_copies=1, cell_head_budget_params=1_000_000,
        total_head_budget_params=32_000_000, active_cells_per_round_cap=2)
    before = state_digest(parent)
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(study['seed']+1)
        child = FamilyCellBank(parent.dimension, parent.classes, profile, study['width_units'],
                              sibling_loss_weight=study['family_policy']['sibling_loss_weight'])
        with torch.no_grad():
            for i, head in enumerate(child.heads):
                head.load_state_dict(parent.heads[i % 16].state_dict())
            child.gate.weight[:16].copy_(parent.gate.weight)
            child.gate.bias[:16].copy_(parent.gate.bias)
            child.gate.weight[16:].uniform_(-study['family_policy']['gate_noise_scale'],
                                           study['family_policy']['gate_noise_scale'])
            child.gate.bias[16:].zero_()
    if state_digest(parent) != before or sum(p.numel() for p in child.parameters()) != 2*count:
        raise ValueError('parent mutation or wrong successor inventory')
    return child


def train_family(bank, features, targets, study, *, meter, topology):
    """Reuse whole-update admission; migration is separate and reduces train room."""
    if (study.get('family_policy') != policy() or topology not in {r[0] for r in TOPOLOGIES}
            or type(bank) is not (CellBank if topology == 'family_split16to32' else FamilyCellBank)):
        raise ValueError('bound family experiment required')
    cfg = {**study, 'schedule': 'formula_budget_whole_updates_v1'}
    budget = study['training_flops_budget']
    split = topology == 'family_split16to32'
    if meter.caps.get('migration') != budget or meter.caps.get('train') != budget:
        raise ValueError('both original phase caps must match the pooled budget')
    params = sum(p.numel() for p in bank.parameters())
    final_params = params*2 if split else params
    cap = final_params*study['family_policy']['max_live_parameter_multiplier']
    first_limit = budget*study['family_policy']['first_stage_fraction_ppm']//1_000_000
    first = train_to_budget(bank, features, targets, {**cfg, 'max_budget_steps': study['max_budget_steps']//2},
                            study['seed'], meter=meter, stop_at_work=first_limit)
    # Optimizer is gone at the boundary; both arms clear old gradients.
    bank.zero_grad(set_to_none=True)
    train_before = used_training_work(meter)
    # Conservative reservation covers construction, residual/probe forwards,
    # cloning and numeric checks. It uses no uncharged calibration execution.
    transition_bound = 16*final_params + 8*step_upper_bound(bank, len(features))
    if transition_bound >= budget-train_before:
        raise FamilyBudgetRejected(dict(reason='transition_not_funded', first_stage=first,
            reserved_transition_work=transition_bound, remaining=budget-train_before))
    with meter.scope('migration', 'bank'), torch.no_grad():
        logits = bank(features)
        residual = float(nn.functional.cross_entropy(logits, targets))
        if not math.isfinite(residual):
            raise ValueError('nonfinite training residual')
        parent_id = state_digest(bank)
        parity = None
        if split:
            if residual <= study['family_policy']['loss_threshold']:
                raise FamilyBudgetRejected(dict(reason='residual_did_not_trigger_split', first_stage=first,
                    training_residual=residual, expected_final_cells=32))
            successor = split_candidate(bank, study, parameter_cap=cap)
            parity = transition_parity(bank, successor, features, study['family_policy'])
            if not parity['passed']:
                raise FamilyBudgetRejected(dict(reason='transition_parity_failed', first_stage=first,
                    transition_probe=parity, expected_final_cells=32))
            # The caller drops its original reference when installing our return.
            bank = successor
    rows = [r for r in meter.rows.values() if r['phase']=='migration']
    if any(r['failed_calls'] or r['unknown_operators'] for r in rows):
        raise ValueError('incomplete transition cost')
    migration = sum(r['formula_flops'] for r in rows)
    if migration > transition_bound:
        raise ValueError('transition exceeded reserved work bound')
    second = train_to_budget(bank, features, targets, {**cfg, 'max_budget_steps': study['max_budget_steps']-first['steps']},
                             study['seed']+1, meter=meter, stop_at_work=budget-migration)
    used = used_training_work(meter)+migration
    if used > budget:
        raise ValueError('pooled offline budget exceeded')
    receipt = dict(schema='hepta.public-family-budget-training.v1', topology=topology,
        stages=[first, second], steps=first['steps']+second['steps'],
        examples_seen=first['examples_seen']+second['examples_seen'],
        peak_optimizer_tensor_bytes=max(first['optimizer_tensor_bytes'],second['optimizer_tensor_bytes']),
        first_stage_limit=first_limit, optimizer_reset_count=1, training_residual=residual,
        split_performed=split, parent_sha256=parent_id, initial_parameters=params,
        final_parameters=final_params, max_live_parameter_cap=cap,
        peak_live_model_parameters=params+final_params if split else params,
        peak_scope='simultaneously_live_model_parameters_not_optimizer_activations_or_encoder',
        transition_probe=parity, transition_reserved_bound=transition_bound,
        transition_formula_flops=migration, observed_offline_formula_flops=used,
        remaining=budget-used, budget=budget, routing_profile=ROUTING_PROFILE,
        train_and_transition_counted_once=True, independent_gain_established=False)
    return bank, receipt


def validate_results(study, arms):
    """Validate stage reservations and actual pooled work; not an attestation."""
    from work_record import validate_work_record
    results = []
    for arm in arms:
        validate_work_record(arm['work'], expected_policy=study['measurement_policy'])
        if arm['status'] != 'completed':
            results.append(dict(topology=arm['topology'], status='failed'))
            continue
        r, counts = arm['training'], arm['work']['phase_flops']
        split = arm['topology']=='family_split16to32'
        final = arm['inventory']['parameters']
        if (r['schema']!='hepta.public-family-budget-training.v1' or r['topology']!=arm['topology']
                or r['split_performed'] is not split or len(r['stages'])!=2
                or r['routing_profile']!=ROUTING_PROFILE or arm['inventory'].get('routing_profile')!=ROUTING_PROFILE
                or r['budget']!=study['training_flops_budget'] or r['final_parameters']!=final
                or r['initial_parameters']*(2 if split else 1)!=final
                or r['max_live_parameter_cap']!=final*study['family_policy']['max_live_parameter_multiplier']
                or r['peak_live_model_parameters']!=(r['initial_parameters']+final if split else final)
                or r['peak_live_model_parameters']>r['max_live_parameter_cap']
                or r['first_stage_limit']!=r['budget']*study['family_policy']['first_stage_fraction_ppm']//1_000_000
                or r['optimizer_reset_count']!=1 or r['train_and_transition_counted_once'] is not True
                or any(type(counts[p]) is not int or counts[p]<0 for p in ('train','migration'))
                or counts['train']+counts['migration']!=r['observed_offline_formula_flops']
                or r['transition_formula_flops']!=counts['migration']
                or counts['migration']>r['transition_reserved_bound']
                or r['remaining']!=r['budget']-r['observed_offline_formula_flops'] or r['remaining']<0):
            raise ValueError('inconsistent pooled family cost or topology')
        residual = r['training_residual']
        if type(residual) not in (int,float) or not math.isfinite(residual) or residual<0:
            raise ValueError('invalid training-only trigger')
        if split:
            probe = r['transition_probe']
            if (residual<=study['family_policy']['loss_threshold'] or probe['passed'] is not True
                    or probe['data_role']!='training_only' or probe['global_float_parity_established'] is not False
                    or probe['atol']!=study['family_policy']['transition_atol']
                    or probe['rtol']!=study['family_policy']['transition_rtol']
                    or not 0<=probe['max_tolerance_ratio']<=1):
                raise ValueError('invalid transition parity or split trigger')
        elif r['transition_probe'] is not None:
            raise ValueError('direct control cannot claim a split')
        first, second = r['stages']
        limits = [r['first_stage_limit'],r['budget']-counts['migration']]
        inv=arm['inventory']
        auxiliary_examples = second['examples_seen'] if split else r['examples_seen']
        if (sum(inv['sibling_probe_rows'])!=4*auxiliary_examples
                or not 0<=inv['sibling_supervised_rows']<=2*auxiliary_examples):
            raise ValueError('auxiliary training rows omitted or duplicated')
        if first['budget']['observed']+r['transition_reserved_bound']>=r['budget']:
            raise ValueError('unfunded transition')
        previous = 0
        maxima=[study['max_budget_steps']//2,study['max_budget_steps']-first['steps']]
        for stage, limit, maximum in zip(r['stages'],limits,maxima,strict=True):
            b = stage['budget']; observed = b['observed']
            if (b.get('schema')!='hepta.cell-training-budget.v1'
                    or any(type(b.get(k)) is not int or b[k]<0 for k in ('observed','limit','remaining'))
                    or type(stage['steps']) is not int or not 1<=stage['steps']<=maximum
                    or type(b['smallest_complete_update_bound']) is not int or b['smallest_complete_update_bound']<1
                    or b['conservative_reservations_are_not_charges'] is not True
                    or b['hardware_or_full_system_cost'] is not False
                    or b['stop_reason'] not in ('step_limit','insufficient_room_for_complete_update')
                    or (b['stop_reason']=='step_limit' and stage['steps']!=maximum)
                    or (b['stop_reason']=='insufficient_room_for_complete_update' and b['remaining']>=b['smallest_complete_update_bound'])
                    or any(any(type(u[k]) is not int for k in ('index','batch_size','actual_formula_flops','reserved_upper_bound'))
                           or type(u['loss']) not in (int,float) or not math.isfinite(u['loss']) for u in b['updates'])
                    or stage['losses']!=[u['loss'] for u in b['updates']]):
                raise ValueError('incomplete stage update record')
            if observed < previous or b['limit']!=limit:
                raise ValueError('invalid stage cost boundary')
            # Reconstruct cumulative train prefixes across both stages.
            # No projected profiler record is produced or published.
            prefix = observed-sum(u['actual_formula_flops'] for u in b['updates'])
            if prefix<previous:
                raise ValueError('stage omitted earlier work')
            for u in b['updates']:
                if prefix+u['reserved_upper_bound']>limit:
                    raise ValueError('stage update was not fully reserved')
                prefix+=u['actual_formula_flops']
            if (b['remaining']!=limit-observed or b['remaining']<0 or b['unit']!=arm['work']['profile']
                    or b['utilization']!=observed/limit or len(b['updates'])!=stage['steps'] or not stage['steps']
                    or stage['examples_seen']!=sum(u['batch_size'] for u in b['updates'])
                    or any(u['index']!=i or not 0<u['actual_formula_flops']<=u['reserved_upper_bound']
                           or not 1<=u['batch_size']<=study['batch_size'] for i,u in enumerate(b['updates']))):
                raise ValueError('invalid stage update accounting')
            previous=observed
        if (second['budget']['observed']!=counts['train'] or r['steps']!=first['steps']+second['steps']
                or r['examples_seen']!=first['examples_seen']+second['examples_seen']):
            raise ValueError('stage/pooled totals disagree')
        results.append(dict(topology=arm['topology'],status='completed',steps=r['steps'],
            examples_seen=r['examples_seen'],formula_flops=r['observed_offline_formula_flops'],
            remaining=r['remaining'],utilization=r['observed_offline_formula_flops']/r['budget'],
            peak_live_model_parameters=r['peak_live_model_parameters']))
    return results
