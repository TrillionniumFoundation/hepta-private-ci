"""Label-blind, genuinely executed four-condition Reader evidence study.

Research-only DENY_ALL. Span annotations are externally supplied and unverified:
'support_candidate' is never an independently certified sufficient premise.
Independent labels must not reach run_blind; the separate reviewer can score
only unchanged original-label questions and reports causal sensitivity otherwise.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict

import torch

PLAN = 'hepta.reader.support-causal-plan.v1'
OBS = 'hepta.reader.support-causal-observation.v1'
SCORE = 'hepta.reader.support-causal-score.v1'
CONDITIONS = ('no_evidence', 'ordinary_retrieval', 'support_candidate', 'premise_removed')
NEUTRAL = 'Evidence unavailable.'
MAX_ROWS = 256
MAX_BYTES = 8 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def hex64(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _text(value, cap):
    return isinstance(value, str) and bool(value.strip()) and 0 < len(value.encode()) <= cap


def condition_texts(row):
    passage = row['evidence']
    pieces = [passage[span[0]:span[1]] for span in row['support_spans']]
    return dict(no_evidence=NEUTRAL, ordinary_retrieval=passage,
                support_candidate='\n'.join(pieces),
                premise_removed='\n'.join(piece for i, piece in enumerate(pieces)
                                           if i != row['critical_span_index']))


def validate_plan(plan):
    if (not isinstance(plan, dict) or set(plan) != {'schema', 'panel_sha256',
          'model_sha256', 'rows', 'labels_available_to_runner', 'support_independently_verified', 'plan_id'}
        or plan['schema'] != PLAN or plan['labels_available_to_runner'] is not False
        or plan['support_independently_verified'] is not False
        or any(not hex64(plan[k]) for k in ('panel_sha256', 'model_sha256'))
        or plan['plan_id'] != digest({k: v for k, v in plan.items() if k != 'plan_id'})
        or not isinstance(plan['rows'], list) or not 1 <= len(plan['rows']) <= MAX_ROWS):
        raise ValueError('invalid, unsealed or falsely certified support plan')
    seen = set(); groups = defaultdict(set); source_text = {}; all_bytes = 0
    for row in plan['rows']:
        if (not isinstance(row, dict) or set(row) != {'task_id', 'source_group',
               'evidence', 'question', 'answer', 'support_spans', 'critical_span_index'}
            or not _text(row['task_id'], 128) or not _text(row['source_group'], 128)
            or not _text(row['evidence'], 65536) or not _text(row['question'], 8192)
            or not _text(row['answer'], 4096)
            or not isinstance(row['support_spans'], list) or not 2 <= len(row['support_spans']) <= 8
            or type(row['critical_span_index']) is not int
            or not 0 <= row['critical_span_index'] < len(row['support_spans'])
            or row['task_id'] in seen):
            raise ValueError('incomplete task, source, or bounded support inventory')
        seen.add(row['task_id'])
        group = row['source_group']
        if group in source_text and source_text[group] != row['evidence']:
            raise ValueError('one source group cannot change original evidence')
        source_text[group] = row['evidence']
        groups[group].add(row['task_id'])
        before = -1
        for span in row['support_spans']:
            if (not isinstance(span, list) or len(span) != 2
                or any(type(z) is not int for z in span)
                or not 0 <= span[0] < span[1] <= len(row['evidence'])
                or span[0] < before or not row['evidence'][span[0]:span[1]].strip()):
                raise ValueError('invalid, overlapping or empty original-source span')
            before = span[1]
        cond = condition_texts(row)
        if (not _text(cond['premise_removed'], 65536)
            or cond['support_candidate'] == cond['premise_removed']
            or cond['support_candidate'] == NEUTRAL
            or cond['premise_removed'] == cond['ordinary_retrieval']):
            raise ValueError('evidence intervention does not actually remove a premise')
        all_bytes += sum(len(t.encode()) for t in cond.values())
        if all_bytes > MAX_BYTES:
            raise ValueError('unbounded full intervention features')
    if len(groups) < 2:
        raise ValueError('at least two actual distinct source groups needed')
    return True


def _good(tensor, shape=None):
    return (isinstance(tensor, torch.Tensor) and tensor.dtype == torch.float32
        and tensor.device.type == 'cpu' and not tensor.requires_grad
        and torch.isfinite(tensor).all().item()
        and (shape is None or tensor.shape == shape)
        and tensor.untyped_storage().nbytes() <= MAX_BYTES)


def _p1(logits):
    top = max(logits)
    a, b = (math.exp(z-top) for z in logits)
    return b/(a+b)


def run_blind(plan, *, encoder, question_encoder, reader, weight_sha256,
              reference_rows=None, tolerance=1e-5):
    """Perform actual encoder + Reader forwards; independent labels never passed.

    reference_rows, when provided, is the exact already-frozen original pair
    inventory: [{task_id, source_group, logits, weights_sha256}, ...].
    """
    validate_plan(plan)
    if (not hex64(weight_sha256) or not callable(encoder) or not callable(question_encoder)
        or not callable(reader) or type(tolerance) not in (float, int)
        or not math.isfinite(tolerance) or not 0 <= tolerance <= 1e-4):
        raise ValueError('actual typed frozen Reader and finite replay tolerance required')
    if isinstance(reader, torch.nn.Module):
        if reader.training or any(p.device.type != 'cpu' or p.dtype != torch.float32
                                   or not torch.isfinite(p).all().item()
                                   for p in reader.parameters()):
            raise ValueError('frozen CPU Reader required')
    refs = None
    if reference_rows is not None:
        if (not isinstance(reference_rows, list) or len(reference_rows) != len(plan['rows'])):
            raise ValueError('exact original paired prediction inventory required')
        refs = {}
        for item in reference_rows:
            if (not isinstance(item, dict) or set(item) != {'task_id', 'source_group',
                                                             'logits', 'weights_sha256'}
                or item['task_id'] in refs or item['weights_sha256'] != weight_sha256
                or not isinstance(item['logits'], list) or len(item['logits']) != 2
                or any(type(z) not in (int, float) or not math.isfinite(z)
                       for z in item['logits'])):
                raise ValueError('untrusted original frozen Reader predictions')
            refs[item['task_id']] = item
        if set(refs) != {row['task_id'] for row in plan['rows']}:
            raise ValueError('changed paired denominator in replay')
    rows = []; n_encoded = 0; n_read = 0; n_queries = 0; total_wall_ns = 0
    for item in plan['rows']:
        if refs is not None and refs[item['task_id']]['source_group'] != item['source_group']:
            raise ValueError('wrong original source on replay')
        question = item['question']+'\nCandidate answer: '+item['answer']+'\nIs this candidate correct?'
        start = time.perf_counter_ns()
        with torch.inference_mode():
            query = question_encoder(question)
        n_queries += 1
        if not _good(query) or query.ndim != 1 or not 1 <= len(query) <= 4096:
            raise ValueError('untrusted candidate query feature')
        predictions = {}; times = {}
        for name, content in condition_texts(item).items():
            t0 = time.perf_counter_ns()
            with torch.inference_mode():
                feature = encoder(content)
            n_encoded += 1
            if (not _good(feature) or feature.ndim != 2
                or not 1 <= feature.shape[0] <= 512 or feature.shape[1] != len(query)):
                raise ValueError('evidence Encoder lost token geometry')
            with torch.inference_mode():
                logits = reader(feature, query)
            n_read += 1
            if not _good(logits, (2,)):
                raise ValueError('invalid conditioned Reader logits')
            values = [float(z) for z in logits]
            predictions[name] = dict(logits=values, probability=_p1(values),
                                     evidence_sha256=hashlib.sha256(content.encode()).hexdigest())
            times[name] = max(1, time.perf_counter_ns()-t0)
        if refs is not None and any(abs(a-b) > tolerance for a,b in zip(
                predictions['ordinary_retrieval']['logits'], refs[item['task_id']]['logits'], strict=True)):
            raise ValueError('original heldout pretrained prediction cannot replay')
        total_wall_ns += time.perf_counter_ns() - start
        rows.append(dict(task_id=item['task_id'], source_group=item['source_group'],
                         original_input_sha256=hashlib.sha256(item['evidence'].encode()).hexdigest(),
                         observations=predictions, condition_wall_ns=times))
    if n_encoded != len(rows)*4 or n_read != len(rows)*4 or n_queries != len(rows):
        raise ValueError('actual full intervention call census incomplete')
    out = dict(schema=OBS, plan_id=plan['plan_id'], panel_sha256=plan['panel_sha256'],
               model_sha256=plan['model_sha256'], reader_weights_sha256=weight_sha256,
               condition_order=list(CONDITIONS), rows=rows, physical_encoder_calls=n_encoded,
               physical_reader_calls=n_read, physical_query_calls=n_queries,
               measured_whole_call_wall_ns=total_wall_ns,
               original_prediction_replay_verified=refs is not None,
               external_semantic_sufficiency_authenticated=False,
               independent_real_source_authenticated=False, reading_labels=False,
               measured_complete_model_lifecycle=False, production_authorized=False,
               authority='DENY_ALL')
    out['observation_id'] = digest(out)
    return out


def review(plan, observations, labels, *, expected_observation_id, expected_labels_sha256):
    """Label-only separate scoring: never call the Encoder or mutate weights."""
    validate_plan(plan)
    if (not isinstance(observations, dict) or observations.get('schema') != OBS
        or observations.get('observation_id') != expected_observation_id
        or digest({k:v for k,v in observations.items() if k != 'observation_id'}) != expected_observation_id
        or observations.get('plan_id') != plan['plan_id']
        or observations.get('condition_order') != list(CONDITIONS)
        or observations.get('authority') != 'DENY_ALL'
        or observations.get('external_semantic_sufficiency_authenticated') is not False
        or observations.get('production_authorized') is not False
        or not isinstance(labels, dict) or set(labels) != {'labels', 'schema', 'plan_id'}
        or labels['schema'] != 'hepta.reader.support-label-owner.v1'
        or labels['plan_id'] != plan['plan_id']
        or digest(labels) != expected_labels_sha256):
        raise ValueError('sealed real observations and independent label-owner receipt required')
    by_id = labels['labels']
    if (not isinstance(by_id, dict) or set(by_id) != {r['task_id'] for r in plan['rows']}
        or any(type(y) is not int or y not in (0,1) for y in by_id.values())
        or not isinstance(observations.get('rows'), list)
        or len(observations['rows']) != len(plan['rows'])):
        raise ValueError('incomplete label owner denominator')
    counts = {c:0 for c in ('no_evidence', 'ordinary_retrieval', 'support_candidate')}
    brier = dict.fromkeys(counts, 0.0)
    changes = dict.fromkeys(('no_evidence', 'support_candidate', 'premise_removed'), 0.0)
    cases = []
    for source, predicted in zip(plan['rows'], observations['rows'], strict=True):
        if (not isinstance(predicted, dict) or predicted.get('task_id') != source['task_id']
            or predicted.get('source_group') != source['source_group']
            or predicted.get('original_input_sha256') != hashlib.sha256(source['evidence'].encode()).hexdigest()
            or set(predicted) != {'task_id', 'source_group', 'original_input_sha256',
                                  'observations','condition_wall_ns'}
            or set(predicted['observations']) != set(CONDITIONS)
            or set(predicted['condition_wall_ns']) != set(CONDITIONS)):
            raise ValueError('original task, source, or conditions drifted')
        probabilities = {}
        for c, text in condition_texts(source).items():
            obs = predicted['observations'][c]
            if (not isinstance(obs, dict) or set(obs) != {'logits', 'probability', 'evidence_sha256'}
                or obs['evidence_sha256'] != hashlib.sha256(text.encode()).hexdigest()
                or not isinstance(obs['logits'], list) or len(obs['logits']) != 2
                or any(type(z) not in (int,float) or not math.isfinite(z) for z in obs['logits'])
                or type(obs['probability']) not in (int,float) or not math.isfinite(obs['probability'])
                or abs(_p1(obs['logits'])-obs['probability']) > 1e-8
                or type(predicted['condition_wall_ns'][c]) is not int
                or predicted['condition_wall_ns'][c] <= 0):
                raise ValueError('altered physical Reader prediction or timing record')
            probabilities[c] = obs['probability']
        y = by_id[source['task_id']]
        for c in counts:
            counts[c] += int((probabilities[c] >= 0.5) == bool(y))
            brier[c] += (probabilities[c]-y)**2
        for c in changes:
            changes[c] += abs(probabilities[c]-probabilities['ordinary_retrieval'])
        cases.append(dict(task_id=source['task_id'], source_group=source['source_group'],
                          removed_premise_probability_change=abs(
                              probabilities['support_candidate']-probabilities['premise_removed'])))
    n = len(cases)
    return dict(schema=SCORE, original_observation_id=expected_observation_id,
                owner_labels_sha256=expected_labels_sha256, tasks=n,
                source_groups=len({r['source_group'] for r in cases}),
                original_label_descriptive_accuracy={c:counts[c]/n for c in counts},
                original_label_descriptive_brier={c:brier[c]/n for c in counts},
                ordinary_evidence_absolute_probability_change={c:changes[c]/n for c in changes},
                premise_removed_descriptive_only=cases,
                premise_removed_has_no_valid_original_ground_truth=True,
                support_candidate_semantic_sufficiency_independently_verified=False,
                score_not_generalization_or_future_evidence=True,
                calibrated_abstention_established=False,
                production_authorized=False, authority='DENY_ALL')
