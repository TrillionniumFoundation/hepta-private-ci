#!/usr/bin/env python3
"""Train a matched question-and-answer-only prior on frozen shared Stem features.

Targets are the human annotations of the ORIGINAL MultiRC passage/question/answer;
no new truth label is assigned to a passage-free input. The same physical Encoder
bank serves the evidence and prior arms. No second model or authority is created.
"""
from __future__ import annotations

import copy
import math
import time

from p0_multirc_semantic_material import Invalid, canonical, sha, validate
from p0_multirc_semantic_execute import LR, SEED, STEPS, TEMPS
from p0_real_reader_cpu import tensor_sha

SCHEMA = 'hepta.p0.multirc-original-target-question-only-head.v1'


def task_key(row):
    return (row['split'], row['source_group'], row['question_id'], row['answer_id'])


def matched_pairs(fit_doc, blind_doc):
    """Return exact paired material without making an unknown intervention a label."""
    fit, blind = validate(fit_doc, blind_doc)
    pairs = {}
    for item in fit + blind:
        key = task_key(item)
        slot = pairs.setdefault(key, {})
        if item['condition'] in slot:
            raise Invalid('duplicate paired intervention')
        slot[item['condition']] = item
    if any(set(p) != {'original', 'no_evidence'} for p in pairs.values()):
        raise Invalid('missing original-question/no-evidence pair')
    chosen = {'train': [], 'calibration': [], 'test': []}
    for key, pair in pairs.items():
        orig, prior = pair['original'], pair['no_evidence']
        if (orig['joint_input']['question'] != prior['joint_input']['question'] or
                orig['candidate_text'] != prior['candidate_text'] or
                orig['original_question_text'] != prior['original_question_text'] or
                orig['view_sha256'] == prior['view_sha256'] or
                (key[0] != 'test' and (type(orig['label']) is not int or
                                     prior['label'] is not None)) or
                (key[0] == 'test' and ('label' in orig or 'label' in prior))):
            raise Invalid('counterfactual identity or label boundary changed')
        chosen[key[0]].append((orig, prior))
    return {part: sorted(rows, key=lambda p: p[0]['case_id']) for part, rows in chosen.items()}


def fit_question_only(fit_doc, blind_doc, features, width, evidence_training, *, replay_heads=None):
    """Actually fit a separately initialized SGD Head with matched steps and labels.

    Evidence labels come exclusively from original TRAIN material; no-evidence
    training vectors are task inputs to a *prior predictor* of original truth,
    not annotations of the altered evidence. Calibration is separate from SGD.
    """
    import torch
    import torch.nn.functional as F

    torch.set_num_threads(1)
    pairs = matched_pairs(fit_doc, blind_doc)
    fit_rows = fit_doc['cases']; blind_rows = blind_doc['cases']
    if (type(features) is not dict or set(features) != {r['case_id'] for r in fit_rows + blind_rows}
            or type(width) is not int or width not in (256, 384)):
        raise Invalid('incomplete physically encoded matched feature bank')
    if any((type(features[r['case_id']]) not in (list, tuple) or
            len(features[r['case_id']]) != width or
            any(type(v) not in (float, int) or not math.isfinite(v) or abs(v) > 8
                for v in features[r['case_id']])) for r in fit_rows + blind_rows):
        raise Invalid('unverified/nonfinite or wrong-size frozen vectors')
    evidence_initial = evidence_training.get('initial_frozen_head_sha256') if type(evidence_training) is dict else None
    if (evidence_training.get('optimizer') != 'torch.optim.SGD' or
            evidence_training.get('steps') != STEPS or
            evidence_training.get('seed') != SEED or
            evidence_training.get('learning_rate') != LR or
            evidence_training.get('parameter_count') != 2 * width + 2 or
            evidence_training.get('train_labels_only_in_gradient') is not True):
        raise Invalid('unequal evidence/prior training resource ceiling')
    training = pairs['train']; calibration = pairs['calibration']
    if (len(training) < 24 or len(calibration) < 8 or len(pairs['test']) < 16 or
            {o['label'] for o, _ in training} != {0, 1} or
            {o['label'] for o, _ in calibration} != {0, 1}):
        raise Invalid('missing human original-target learning material')
    original_train = [p[0]['case_id'] for p in sorted(training, key=lambda x: fit_rows.index(x[0]))]
    original_cal = [p[0]['case_id'] for p in sorted(calibration, key=lambda x: fit_rows.index(x[0]))]
    if (evidence_training.get('fit_train_case_ids_sha256') != sha(canonical(original_train)) or
            evidence_training.get('calibration_case_ids_sha256') != sha(canonical(original_cal))):
        raise Invalid('evidence-prior original TRAIN/CAL sample exposure mismatch')
    # Match the evidence arm's original physical source order rather than sorted
    # hash order; never use heldout labels or the future source as training input.
    positions = {r['case_id']: i for i, r in enumerate(fit_rows)}
    training.sort(key=lambda p: positions[p[0]['case_id']])
    calibration.sort(key=lambda p: positions[p[0]['case_id']])

    def X(rows):
        return torch.tensor([features[prior['case_id']] for _, prior in rows], dtype=torch.float32)

    x_train = X(training)
    y_train = torch.tensor([orig['label'] for orig, _ in training], dtype=torch.long)
    x_cal = X(calibration)
    y_cal = torch.tensor([orig['label'] for orig, _ in calibration], dtype=torch.long)
    torch.manual_seed(SEED)
    head = torch.nn.Linear(width, 2)
    frozen = copy.deepcopy(head).eval()
    initial_sha = tensor_sha(frozen)
    if initial_sha != evidence_initial:
        raise Invalid('initial Question-only and Evidence Head tensors are not identical')
    param_count = sum(p.numel() for p in head.parameters())
    if param_count != evidence_training['parameter_count'] or param_count > 2048:
        raise Invalid('unequal full trainable Head geometry')
    begin = time.perf_counter_ns()
    optimizer = torch.optim.SGD(head.parameters(), lr=LR)
    for _ in range(STEPS):
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(head(x_train), y_train)
        if not bool(torch.isfinite(loss).item()):
            raise Invalid('nonfinite original-target SGD loss')
        loss.backward()
        optimizer.step()
    ms = (time.perf_counter_ns() - begin) / 1e6
    if tensor_sha(frozen) != initial_sha or tensor_sha(head) == initial_sha:
        raise Invalid('frozen control mutated or learned Head made no parameter update')
    if replay_heads is not None:
        from p0_physical_replay_v5 import capture_head_tensors
        capture_head_tensors(replay_heads,'question_frozen',frozen)
        capture_head_tensors(replay_heads,'question_trained',head)

    controls = {}
    for mode, h in (('question_frozen_head', frozen), ('question_trained_head', head.eval())):
        with torch.inference_mode():
            temperature = min(TEMPS, key=lambda t: float(F.cross_entropy(h(x_cal) / t, y_cal)))
            predictions = []
            for original, no_evidence in pairs['test']:
                tick = time.perf_counter_ns()
                score = float(F.softmax(h(X([(original, no_evidence)])) / temperature, dim=-1)[0, 1])
                request_ms = (time.perf_counter_ns() - tick) / 1e6
                if not 0 <= score <= 1 or not math.isfinite(score) or not request_ms > 0:
                    raise Invalid('invalid physical prior prediction or timing')
                predictions.append({'original_case_id': original['case_id'],
                                    'no_evidence_case_id': no_evidence['case_id'],
                                    'no_evidence_view_sha256': no_evidence['view_sha256'],
                                    'positive_probability': score,
                                    'head_request_ms': request_ms})
        controls[mode] = {'head_sha256': tensor_sha(h), 'temperature': temperature,
                          'predictions': predictions}
    return {'schema': SCHEMA,
            'target': 'original_human_binary_label_predicted_without_passage_evidence',
            'no_evidence_material_has_new_human_ground_truth': False,
            'source_training_only': True,
            'per_head_trainable_parameters': param_count,
            'optimizer': 'torch.optim.SGD', 'steps': STEPS, 'seed': SEED, 'learning_rate': LR,
            'train_source_case_ids_sha256': evidence_training['fit_train_case_ids_sha256'],
            'calibration_source_case_ids_sha256': evidence_training['calibration_case_ids_sha256'],
            'train_question_case_ids_sha256': sha(canonical([p['case_id'] for _, p in training])),
            'calibration_question_case_ids_sha256': sha(canonical([p['case_id'] for _, p in calibration])),
            'matched_train_example_count': len(training),
            'matched_calibration_example_count': len(calibration),
            'original_and_prior_initial_tensor_sha256': initial_sha,
            'question_only_head_training_ms': ms,
            'reuse_same_original_shared_encoder_load': True,
            'additional_model_loads': 0, 'additional_encoder_forwards': 0,
            'complete_prior_controls': controls, 'production_promotion_permitted': False,
            'authority': 'DENY_ALL'}
