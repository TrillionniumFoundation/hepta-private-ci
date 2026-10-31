"""Actual old-generator policy requests and strictly subsequent private branches."""

from collections import Counter
import time

import numpy as np
import torch

from ...abc_followup.control.features import ExactFeatureCache
from ...abc_recovery.runtime import ACTIONS, initialize, public_digest, public_frame, transition
from ...abc_recovery.trees import stable_seed
from ...closure_20261025.control.rollout import emit_json
from ...next_20261025.control.run import payload, persist
from ...v6.data import Observation
from .features import encode
from .model import choose


POLICIES = ('masked_teacher', 'constrained_paired')


class AffinePolicy:
    def __init__(self, record):
        if (record['schema'] != 'hepta.advance.admission-aware-paired-moments.v1'
                or record['feature_width'] != 109 or record['ridge'] != .1):
            raise ValueError('The single previously selected ridge-0.1 candidate is required')
        self.heads = [{**head, 'weight': np.asarray(head['weight']),
                       'bias': np.asarray(head['bias'])} for head in record['heads']]

    def predict(self, compact, remaining):
        head = self.heads[remaining - 1]
        return np.clip(compact @ head['weight'].T + head['bias'],
                       head['minimum'], head['maximum'])


def teacher_moments(teacher, public, remaining):
    if teacher.mode != 'enriched':
        raise ValueError('The frozen teacher requires all 763 enriched public inputs')
    result = (teacher.one if remaining == 1 else teacher.two)(public).double().numpy()
    if not np.isfinite(result).all() or (result <= 0).any():
        raise ValueError('Invalid teacher moments')
    return result


def draw_rng(spec, seed, case, view, draw, path):
    return torch.Generator().manual_seed(stable_seed(
        spec['future_namespace'], seed, case, view, draw, tuple(path)))


@torch.inference_mode()
def request(model, observation, teacher, candidate, sensor, predictor, calibration,
            *, policy, seed, case, view, draw, spec, media, commitments):
    if type(observation) is not Observation or policy not in POLICIES:
        raise ValueError('Registered policy and public Observation required')
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    row = dict(seed=seed, case=case, view=view, draw=draw, policy=policy, status='failed')
    work, path, decisions = Counter(), [], []
    attempted = 0
    run = diagnostic = None
    try:
        run = initialize(model, observation, generator=torch.Generator().manual_seed(
            stable_seed(spec['initial_namespace'], seed, case, view)))
        cache = ExactFeatureCache(model, sensor, observation, work)
        while not run.done:
            frame = public_frame(run)
            feature_start = time.process_time_ns(); public = cache.read(frame)
            feature_cpu = time.process_time_ns() - feature_start
            gate_start = time.process_time_ns()
            compact, allowed, confidence = encode(public.numpy(), frame.remaining, predictor, calibration)
            gate_cpu = time.process_time_ns() - gate_start
            head_start = time.process_time_ns()
            prediction = (candidate.predict(compact, frame.remaining) if policy == 'constrained_paired'
                          else teacher_moments(teacher, public, frame.remaining))
            chosen = int(choose(prediction, allowed)[0])
            head_cpu = time.process_time_ns() - head_start
            detail = {'decision_index': len(decisions), 'remaining': frame.remaining,
                'selected_index': chosen, 'action': ACTIONS[chosen] if chosen >= 0 else 'reject',
                'public_sha256': public_digest(frame), 'predicted_moments': prediction[0].tolist(),
                'predicted_action_minus_stop': (prediction[0] - prediction[0, 0]).tolist(),
                'admitted': allowed[0].tolist(), 'calibrated_confidence': confidence[0].tolist(),
                'feature_cpu_ns': feature_cpu, 'admission_cpu_ns': gate_cpu, 'head_cpu_ns': head_cpu,
                'mask_scope': 'Frozen content correctness gate; no native resource qualification is inherited'}
            # Durable selection precedes every possible future innovation.
            emit_json(commitments, {**row, **detail}); decisions.append(detail)
            if policy == 'constrained_paired' and frame.remaining == 1:
                diagnostic = (run, public.detach().clone(), tuple(path), detail)
            if chosen < 0:
                row['status'] = 'rejected'
                break
            action = ACTIONS[chosen]
            attempted += int(chosen > 0)
            run = transition(model, run, action,
                generator=draw_rng(spec, seed, case, view, draw, (*path, action)))
            if chosen:
                path.append(action)
            if len(decisions) > 2:
                raise ValueError('Original H2 continuation budget exceeded')
        if run.done:
            row.update(status='completed', terminal=persist(media, payload(run.pixels, run.tokens)))
    except Exception as error:
        row['error'] = {'type': type(error).__name__, 'message': str(error),
                        'transition_ledger': getattr(error, 'ledger', None)}
    if run is not None:
        for entry in run.ledger:
            work.update(entry.get('work', {}))
    row.update(wall_ns=time.perf_counter_ns() - began, cpu_ns=time.process_time_ns() - cpu,
               path=path, attempted_continuations=attempted, decisions=decisions, work=dict(work))
    return row, diagnostic


@torch.inference_mode()
def counterfactuals(model, teacher, retained, selected, spec, media, commitments):
    """Enumerate same-state alternatives only after the actual request has ended."""
    run, public, prefix, detail = retained
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    old_prediction = teacher_moments(teacher, public, 1)[0]
    alternatives, work = [], Counter()
    for index, action in enumerate(ACTIONS):
        item = {'action': action, 'index': index, 'admitted': detail['admitted'][index],
                'status': 'failed'}
        if index == detail['selected_index'] and selected['status'] == 'completed':
            item.update(status='completed', media=selected['terminal'], reused_actual_selected_result=True)
        else:
            emit_json(commitments, {**{key: selected[key] for key in ('seed', 'case', 'view', 'draw')},
                'action': action, 'parent_public_sha256': detail['public_sha256'],
                'phase': 'offline_after_actual_commit_and_request_completion'})
            try:
                generated = transition(model, run, action, generator=draw_rng(spec, selected['seed'],
                    selected['case'], selected['view'], selected['draw'], (*prefix, action)))
                for entry in generated.ledger[len(run.ledger):]:
                    work.update(entry.get('work', {}))
                item.update(status='completed', media=persist(media, payload(generated.pixels, generated.tokens)),
                            reused_actual_selected_result=False)
            except Exception as error:
                item['error'] = {'type': type(error).__name__, 'message': str(error)}
        alternatives.append(item)
    return {**{key: selected[key] for key in ('seed', 'case', 'view', 'draw')},
        'parent_public_sha256': detail['public_sha256'], 'selected_index': detail['selected_index'],
        'candidate_prediction': detail['predicted_moments'], 'teacher_prediction': old_prediction.tolist(),
        'admitted': detail['admitted'], 'alternatives': alternatives, 'not_visible_to_policy': True,
        'offline_wall_ns': time.perf_counter_ns() - began, 'offline_cpu_ns': time.process_time_ns() - cpu,
        'work': dict(work)}
