"""Independent stdlib-only source/receipt reviewer for paired Granite Reader study.

Recomputes frozen training truth, probabilities, gates, model-file hashes and
absence of fresh scoring after any failed seed. This verifies receipt coherence,
not remote host/clock attestation or physical pretrained Encoder execution.
"""
import hashlib
import json
import math
from pathlib import Path

from cross_fact_granite_campaign import (ARMS, SEEDS, _digest, full_fit_gate,
                                         matching_training_budgets, matched_fresh_gate)
from cross_fact_granite_receipt_oracle import verify_observed_training


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('regular bounded receipt file required')

    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate receipt JSON key')
            result[key] = value
        return result

    def finite_float(raw):
        number = float(raw)
        if not math.isfinite(number):
            raise ValueError('nonfinite receipt number')
        return number

    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_pairs,
                      parse_float=finite_float,
                      parse_constant=lambda raw: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def independent_training_score(cases, probabilities):
    require(len(cases) == len(probabilities) and len(cases) > 0,
            'complete training probabilities required')
    predictions = []
    groups = {}
    ce = 0.
    for case, p in zip(cases, probabilities):
        require(type(p) in (float, int) and math.isfinite(p) and 0 <= p <= 1,
                'invalid prediction probability')
        prediction = int(p > .5)
        predictions.append(prediction)
        ce -= math.log(max(1e-12, p if case.label else 1-p))
        key = (case.paragraph_id.rpartition('/world-')[0], case.candidate)
        groups.setdefault(key, []).append(prediction == case.label)
    require(len(groups) * 2 == len(cases) and all(len(v) == 2 for v in groups.values()),
            'incomplete paired-world membership')
    return dict(accuracy=sum(x == c.label for x, c in zip(predictions, cases))/len(cases),
                both_worlds_correct=sum(all(v) for v in groups.values())/len(groups),
                probability_CE=ce/len(cases))



def independent_fresh_score(cases, sealed, scores, expected_weight_digest, sealed_digest):
    """Reconstruct paired fresh truth after all fitting artifacts are frozen."""
    require(sealed['case_ids'] == [case.case_id for case in cases],
            'unaligned or incomplete fresh predictions')
    require(sealed['weights_sha256'] == expected_weight_digest
            and sealed['labels_entered_model'] is False
            and sealed['scoring_started'] is False,
            'fresh prediction seal or frozen weight identity invalid')
    require(scores['predictions_sha256'] == sealed_digest,
            'fresh score does not bind original pre-score probabilities')
    recomputed = independent_training_score(cases, sealed['probabilities'])
    declared = scores['metrics']
    for key in ('accuracy', 'both_worlds_correct', 'probability_CE'):
        require(abs(recomputed[key] - declared[key]) < 1e-12,
                'fresh independent scoring mismatch: ' + key)
    return recomputed


def review(root):
    from token_protocol import build_binding_cases

    root = Path(root).resolve()
    plan, summary, decision, terminal = (read(root / name) for name in
        ('plan.json', 'fit-summary.json', 'opening-decision.json', 'terminal.json'))
    require(plan['seeds'] == list(SEEDS), 'all three original seeds required')
    require(plan['arms'] == list(ARMS) and plan['steps'] == 8000
            and plan['hidden_width'] == 32 and plan['extra_parameters_per_arm'] == 4096,
            'unregistered architecture or training schedule')
    require(plan['production_authorized'] is False
            and plan['external_result_was_used_for_selection'] is False,
            'research and no-heldout-selection commitments required')
    code = Path(__file__).parent
    require(set(plan['new_code_sha256']) == {
        'cross_fact_bridge.py', 'cross_fact_granite_campaign.py',
        'cross_fact_granite_receipt_oracle.py'},
        'unexpected source inventory entries')
    require(all(_digest(code / name) == digest for name, digest in plan['new_code_sha256'].items()),
            'new source changed after run')
    cases = build_binding_cases('train', groups=32, seed=41)
    ids = [case.case_id for case in cases]
    digest = hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest()
    require(digest == plan['train_case_ids_sha256'], 'original TRAIN membership changed')
    require(set(summary) == {str(seed) for seed in SEEDS}, 'missing seed receipts')
    gates = {}
    for seed in SEEDS:
        actual = summary[str(seed)]
        require(set(actual) == set(ARMS), 'missing matched arm receipt')
        previous_init, previous_schedule, previous_count = None, None, None
        for arm in ARMS:
            row = actual[arm]
            folder = root / f'seed-{seed}'
            require(not folder.is_symlink(), 'symlinked seed directory forbidden')
            receipt = read(folder / f'{arm}-training.json')
            manifest = read(folder / f'{arm}-model.json')
            require(manifest['file'] == f'{arm}.pt'
                    and manifest['training_receipt_file'] == f'{arm}-training.json'
                    and not (folder / manifest['file']).is_symlink(),
                    'unexpected weight/receipt path')
            require(_digest(folder / manifest['file']) == manifest['file_sha256'] == row['model_file_sha256'],
                    'model file digest disagrees')
            require(_digest(folder / manifest['training_receipt_file']) == manifest['training_receipt_sha256'],
                    'training receipt digest disagrees')
            internal_path = folder / f'{arm}-natural-internal.json'
            require(not internal_path.is_symlink()
                    and _digest(internal_path) == row['natural_internal_file_sha256'],
                    'old-task internal-tune receipt changed')
            internal = read(internal_path)
            require(internal['scope'] == 'old_training_source_internal_tune_not_fresh'
                    and internal['threshold_selected'] is False
                    and row['old_task_internal_not_selection'] is True
                    and internal['metrics'] == row['natural_internal_tune']
                    and internal['model_execution_parameter_sha256'] == manifest['execution_parameter_sha256'],
                    'old-task retention was relabeled or linked to another model')
            require(receipt['seed'] == seed and receipt['requested_steps'] == 8000
                    and receipt['initial_model_sha256'] == row['original_parameter_digest']
                    and receipt['model_sha256'] == row['trained_parameter_digest']
                    and receipt['parameter_count'] == row['parameter_count'],
                    'seed, model or parameter receipt mismatch')
            require(receipt['schedule_sha256'] == row['schedule_sha256']
                    and receipt['completed_steps'] == row['completed_steps']
                    and receipt['actual_training_exposures'] == row['actual_training_exposures']
                    and receipt['actual_training_exposures'] == 16 * receipt['completed_steps'],
                    'training schedule/exposure mismatch')
            require(receipt['case_ids'] == ids and receipt['train_gate_passed'] is row['train_gate_passed'],
                    'training case or gate mismatch')
            replay = verify_observed_training(cases, seed, receipt,
                                              steps=8000, batch_size=16)
            require(replay['completed_steps'] == row['completed_steps']
                    and receipt['cpu_ns'] == row['training_cpu_ns']
                    and receipt['wall_ns'] == row['training_wall_ns']
                    and receipt['optimizer_tensor_bytes'] == row['optimizer_tensor_bytes'],
                    'independent physical update or observed resource cost differs from summary')
            last_step = receipt['diagnostics'][-1]['optimizer_step']
            require(0 <= last_step <= receipt['completed_steps'],
                    'training metric checkpoint inconsistent')
            if receipt['status'] != 'budget_stopped':
                require(last_step == receipt['completed_steps'], 'final diagnostic missing')
            else:
                require(not receipt['train_gate_passed'], 'budget stop cannot pass')
            metrics = independent_training_score(cases, receipt['diagnostics'][-1]['binding']['probabilities'])
            declared = receipt['diagnostics'][-1]['binding']
            require(abs(metrics['accuracy'] - declared['accuracy']) < 1e-12
                    and abs(metrics['both_worlds_correct'] - declared['both_worlds_correct']) < 1e-12,
                    'producer training accuracy disagrees with recomputed truth')
            # The diagnostic is logit-space CE, whereas saved FP32 softmax
            # probabilities have independent rounding and may underflow. Never
            # declare them numerically identical across arbitrary failed arms.
            require(math.isfinite(declared['binary_cross_entropy'])
                    and declared['binary_cross_entropy'] >= 0,
                    'invalid logit-space training CE')
            if receipt['train_gate_passed']:
                require(metrics['probability_CE'] <= .102,
                        'claimed passed model contradicts saved probabilities')
            verified_gate = (metrics['accuracy'] == 1 and metrics['both_worlds_correct'] == 1
                             and declared['binary_cross_entropy'] <= .10)
            require(verified_gate is receipt['train_gate_passed'], 'unjustified training gate')
            if previous_init is None:
                previous_init = row['original_parameter_digest']
                previous_schedule = row['schedule_sha256']
                previous_count = row['parameter_count']
            else:
                require(previous_init == row['original_parameter_digest']
                        and previous_schedule == row['schedule_sha256']
                        and previous_count == row['parameter_count'],
                        'same-seed initial weights, parameter parity and training stream required')
            gates[f'{seed}/{arm}'] = bool(verified_gate)
    fits = full_fit_gate(summary)
    budgets = matching_training_budgets(summary)
    permitted = matched_fresh_gate(summary)
    require(decision['all_model_fit_gates_passed'] is fits
            and decision['all_actual_training_budgets_equal'] is budgets
            and decision['matched_fresh_gate_passed'] is permitted,
            'opening decision not derived from complete matched training matrix')
    sealed = list(root.glob('sealed-*'))
    scored = list(root.glob('score-*'))
    fresh_scores = {}
    scoring_completed = (root/'scoring-completion.json').exists()
    if not permitted:
        expected_status = ('train_gate_failed_no_fresh_scoring' if not fits
                           else 'unequal_actual_budgets_no_fresh_scoring')
        require(not sealed and not scored and not scoring_completed
                and not (root/'all-models-frozen.json').exists()
                and terminal['status'] == expected_status
                and terminal['fresh_scoring_authorized'] is False,
                'fresh evaluation was opened despite failed fit or budget parity')
    else:
        require((root/'all-models-frozen.json').exists()
                and terminal['status'] == 'all_frozen_predictions_sealed_pending_independent_scoring'
                and terminal['fresh_prediction_seals_complete'] is True
                and terminal['fresh_scoring_authorized'] is False,
                'all models must freeze and seal independently of outcome scoring')
        from binding_protocol import build_binding_protocol
        all_fresh = build_binding_protocol(seed=41)
        frozen = read(root/'all-models-frozen.json')
        require(set(frozen) == {str(seed) for seed in SEEDS},
                'missing frozen global model manifest')
        for seed in SEEDS:
            require(frozen[str(seed)] == {arm: summary[str(seed)][arm]['model_file_sha256']
                                          for arm in ARMS},
                    'frozen model digest changed after training')
        expected_seals, expected_scores = set(), set()
        if scoring_completed:
            completion = read(root / 'scoring-completion.json')
            require(completion['schema'] == 'hepta.cross-fact.separate-score.v1'
                    and completion['completed_roles'] == ['fresh_combinations', 'fresh_vocabulary']
                    and completion['seeds'] == list(SEEDS) and completion['arms'] == list(ARMS)
                    and completion['scored_count'] == 12
                    and completion['score_from_frozen_prelabel_seals'] is True
                    and completion['independent_host_attested'] is False
                    and completion['production_authorized'] is False,
                    'incomplete separate scoring completion manifest')
        for role in ('fresh_combinations', 'fresh_vocabulary'):
            cases = tuple(all_fresh[role])
            require(len(cases) == 128, 'fresh source role size drift')
            require(hashlib.sha256(json.dumps([c.case_id for c in cases],
                    separators=(',', ':')).encode()).hexdigest()
                    == plan['fresh_case_roster_sha256'][role],
                    'fresh original-source roster digest mismatch')
            for seed in SEEDS:
                for arm in ARMS:
                    stem = f'{role}-{seed}-{arm}.json'
                    sealed_path = root / ('sealed-' + stem)
                    score_path = root / ('score-' + stem)
                    expected_seals.add(sealed_path.name)
                    expected_scores.add(score_path.name)
                    envelope = read(sealed_path)
                    require(envelope['case_ids'] == [c.case_id for c in cases]
                            and envelope['weights_sha256'] == frozen[str(seed)][arm]
                            and envelope['labels_entered_model'] is False
                            and envelope['scoring_started'] is False,
                            'unaligned or altered independently presealed predictions')
                    if scoring_completed:
                        fresh_scores[f'{role}/{seed}/{arm}'] = independent_fresh_score(
                            cases, envelope, read(score_path),
                            frozen[str(seed)][arm], _digest(sealed_path))
        require({p.name for p in sealed} == expected_seals,
                'missing or unauthorized extra fresh prediction seals')
        if scoring_completed:
            completion = read(root / 'scoring-completion.json')
            require({p.name for p in scored} == expected_scores
                    and set(completion['score_files']) == expected_scores
                    and all(_digest(root / name) == digest
                            for name, digest in completion['score_files'].items()),
                    'missing or changed separately scored fresh evidence')
        else:
            require(not scored, 'partial scoring without a completed independent phase')
    return dict(schema='hepta.cross-fact.independent-receipt-review.v1',
                receipt_consistency_passed=True, training_gates=gates,
                fresh_source_disjoint_scores=fresh_scores,
                all_training_gates_passed=permitted,
                fresh_scoring_permitted_under_existing_rule=permitted,
                separate_scoring_completed=scoring_completed,
                matched_training_budget_observed=budgets,
                independently_verified_pretrained_forward=False,
                model_ability_established=False, hardware_cost_attested=False,
                production_authorized=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    print(json.dumps(review(parser.parse_args().root), sort_keys=True, indent=2))
