"""Independent stdlib-only source/receipt reviewer for paired Granite Reader study.

Recomputes frozen training truth, probabilities, gates, model-file hashes and
absence of fresh scoring after any failed seed. This verifies receipt coherence,
not remote host/clock attestation or physical pretrained Encoder execution.
"""
import hashlib
import json
import math
from pathlib import Path

from cross_fact_granite_campaign import ARMS, SEEDS, _digest, full_fit_gate


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


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
            receipt = read(folder / f'{arm}-training.json')
            manifest = read(folder / f'{arm}-model.json')
            require(_digest(folder / manifest['file']) == manifest['file_sha256'] == row['model_file_sha256'],
                    'model file digest disagrees')
            require(_digest(folder / manifest['training_receipt_file']) == manifest['training_receipt_sha256'],
                    'training receipt digest disagrees')
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
            require(receipt['diagnostics'][-1]['optimizer_step'] == receipt['completed_steps'],
                    'training metric checkpoint inconsistent')
            metrics = independent_training_score(cases, receipt['diagnostics'][-1]['binding']['probabilities'])
            declared = receipt['diagnostics'][-1]['binding']
            require(abs(metrics['accuracy'] - declared['accuracy']) < 1e-12
                    and abs(metrics['both_worlds_correct'] - declared['both_worlds_correct']) < 1e-12,
                    'producer training accuracy disagrees with recomputed truth')
            # PyTorch logit-CE and FP32 saved-softmax CE may differ slightly.
            require(abs(metrics['probability_CE'] - declared['binary_cross_entropy']) < .002,
                    'saved probabilities cannot reconstruct reported training CE')
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
    permitted = full_fit_gate(summary)
    require(decision['all_model_fit_gates_passed'] is permitted,
            'opening decision not derived from complete matrix')
    sealed = list(root.glob('sealed-*')) + list(root.glob('score-*'))
    if not permitted:
        require(not sealed and not (root/'all-models-frozen.json').exists()
                and terminal['status'] == 'train_gate_failed_no_fresh_scoring'
                and terminal['fresh_scoring_authorized'] is False,
                'fresh evaluation was opened despite a failed training gate')
    else:
        require((root/'all-models-frozen.json').exists()
                and terminal['status'] == 'all_frozen_scored_research_only',
                'frozen model and successful research receipt required')
        # Source-level reviewer stops here; fresh scores need their own source-
        # and label-independent observer, not a second use of training labels.
    return dict(schema='hepta.cross-fact.independent-receipt-review.v1',
                receipt_consistency_passed=True, training_gates=gates,
                all_training_gates_passed=permitted,
                fresh_scoring_permitted_under_existing_rule=permitted,
                independently_verified_pretrained_forward=False,
                model_ability_established=False, hardware_cost_attested=False,
                production_authorized=False)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    print(json.dumps(review(parser.parse_args().root), sort_keys=True, indent=2))
