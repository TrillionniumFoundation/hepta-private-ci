"""Independent stdlib replay of original four-row paired-world schedule.

Does not call the training sampler or trainer. Reconstructs deterministic TRAIN
membership and every sampled update from original public case identifiers.
It checks file/receipt integrity but cannot attest that GPU/CPU model ops ran.
"""
from collections import Counter
import hashlib
import json
import random


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                    allow_nan=False).encode()).hexdigest()


def ordered_four_row_groups(cases):
    """Infer exact original pair memberships independently of producer helpers."""
    if not cases or len({case.case_id for case in cases}) != len(cases):
        raise ValueError('nonempty unique TRAIN case identities required')
    groups = {}
    for index, case in enumerate(cases):
        if type(case.paragraph_id) is not str or type(case.answer_id) is not str:
            raise ValueError('typed original pairing required')
        prefix, sep, world = case.paragraph_id.rpartition('/world-')
        if not sep or world not in ('0', '1') or case.answer_id not in ('0', '1'):
            raise ValueError('registered paired-world source expected')
        key = (world, case.answer_id)
        membership = groups.setdefault(prefix, {})
        if key in membership:
            raise ValueError('duplicate original pairing')
        membership[key] = index
    result = []
    for members in groups.values():
        if set(members) != {(w,a) for w in ('0','1') for a in ('0','1')}:
            raise ValueError('complete original four-row pairing required')
        result.append(tuple(members[(w,a)] for w in ('0','1') for a in ('0','1')))
    return tuple(result)


def derive_schedule(cases, seed, *, steps=8000, batch_size=16):
    """Same registered mathematical sampler, independent source implementation."""
    if (type(seed) is not int or not 0 <= seed < 2**32
            or type(steps) is not int or not 1 <= steps <= 10000
            or type(batch_size) is not int or batch_size < 4 or batch_size % 4):
        raise ValueError('bounded schedule profile required')
    groups = ordered_four_row_groups(cases)
    if len(groups) % (batch_size // 4):
        raise ValueError('all original groups must divide complete minibatches')
    rng = random.Random(seed)
    draws, order, position = [], [], len(groups)
    for _ in range(steps):
        if position == len(groups):
            order = list(range(len(groups)))
            rng.shuffle(order)
            position = 0
        chosen = order[position:position + batch_size // 4]
        position += batch_size // 4
        draws.append([position for group in chosen for position in groups[group]])
    return draws


def verify_observed_training(cases, seed, receipt, *, steps=8000, batch_size=16):
    """Every *completed* step must correspond to the preregistered TRAIN rows.

    The full schedule's hash includes future planned draws, but no unfinished
    step is counted as observed compute. Actual work receipts remain claims by
    one observer, not independently witnessed execution.
    """
    schedule = derive_schedule(cases, seed, steps=steps, batch_size=batch_size)
    if receipt.get('schedule_sha256') != _hash(schedule):
        raise ValueError('training schedule SHA is not reproducible from original TRAIN cases')
    updates = receipt.get('updates')
    completed = receipt.get('completed_steps')
    if (type(completed) is not int or not 1 <= completed <= steps
            or type(updates) is not list or len(updates) != completed):
        raise ValueError('missing or extra completed physical optimizer update receipts')
    exposure_counter = Counter()
    summed_cpu, summed_wall = 0, 0
    for i, (receipt_step, expected_indices) in enumerate(zip(updates, schedule), 1):
        if i > completed:
            break
        case_ids = [cases[index].case_id for index in expected_indices]
        if not isinstance(receipt_step, dict) or (
                receipt_step.get('step') != i
                or receipt_step.get('indices') != expected_indices
                or receipt_step.get('case_ids') != case_ids
                or receipt_step.get('sample_sha256') != _hash(case_ids)
                or receipt_step.get('exposures') != batch_size
                or receipt_step.get('depth') != 3
                or receipt_step.get('pair_weight') != .5
                or receipt_step.get('finite_gradients') is not True
                or receipt_step.get('inference_feature_arguments') != 6):
            raise ValueError('observed training step or original source membership mismatch')
        for clock in ('cpu_ns', 'wall_ns'):
            if type(receipt_step.get(clock)) is not int or receipt_step[clock] <= 0:
                raise ValueError('missing actual training cost field')
        exposure_counter.update(case_ids)
        summed_cpu += receipt_step['cpu_ns']
        summed_wall += receipt_step['wall_ns']
    for clock, lower_bound in (('cpu_ns', summed_cpu), ('wall_ns', summed_wall)):
        total = receipt.get(clock)
        if type(total) is not int or total < lower_bound:
            raise ValueError('training lifecycle cost is smaller than completed physical work')
    if (receipt.get('case_exposures') != dict(exposure_counter)
            or receipt.get('actual_training_exposures') != completed * batch_size):
        raise ValueError('completed source exposures do not reconcile to physical receipts')
    return dict(completed_steps=completed, source_exposures=dict(exposure_counter),
                nested_update_cpu_ns=summed_cpu, nested_update_wall_ns=summed_wall,
                training_schedule_sha256=_hash(schedule),
                labels_entered_sampling=False, independently_attested_execution=False)
