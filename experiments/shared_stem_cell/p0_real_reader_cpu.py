#!/usr/bin/env python3
"""Physical pretrained P0 Reader pilot; three frozen Encoder+SGD Head arms and Laya no-change.

Uses the *existing* E1 physical, source-verified encoders from this exact branch.
Each invocation runs one model only; no model fallback, no synthetic model score,
no read of labels.json or validation/test labels, no tool-effect capability.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import resource
import re
import time

from p0_squad_materials import (SCHEMA, canonical, digest, read, write_new, CONDITIONS,
                                WANTED, DATASET_COMMIT, TRAIN_SHA, VALID_SHA, Invalid,
                                bm25_neighbors, remove_answer_sentence)

COMPACT_REVISIONS = {
    'granite_97m_r2': ('835ad14087e140460703cf0fae09f97d469d65c2', 384),
    'mmbert_small': ('0eb3d056ec1d6333cf4e19b0966dfde342a41a3a', 384),
    'embeddinggemma_2_text': ('914f7f89142e33e77833254d9c9b90c3cef7303b', 256),
}
LAYA_ID = 'convaiinnovations/laya'
LAYA_SHA = 'c5d78730f3493e4fe16d61507ef4b78eef7318cf'
MODELS = tuple(COMPACT_REVISIONS) + ('laya421_nochange',)
STEPS, SEED, LR = 40, 20261015, .1
TEMPERATURES = (.5, .75, 1., 1.5, 2., 3.)


def validate_materials(fit, blind):
    if (type(fit) is not dict or type(blind) is not dict or
            set(fit) != {'metadata', 'cases'} or set(blind) != {'metadata', 'cases'}):
        raise Invalid('missing complete source material pair')
    meta = fit['metadata']
    if (meta != blind['metadata'] or meta.get('schema') != SCHEMA or
            meta.get('authority') != 'DENY_ALL' or
            meta.get('production_promotion_permitted') is not False or
            meta.get('future_chronology_verified') is not False or
            meta.get('dataset_commit')!=DATASET_COMMIT or
            meta.get('train_original_sha256')!=TRAIN_SHA or
            meta.get('validation_original_sha256')!=VALID_SHA or
            meta.get('question_groups_by_split')!=WANTED or
            meta.get('sample_rule')!='sha256-title-rank:answer-not-in-question:v2' or
            meta.get('retriever')!='bm25:k1=1.2:b=0.75:question-only:within-partition:v2'):
        raise Invalid('changed or falsely authoritative source metadata')
    groups = {'train': set(), 'calibration': set(), 'test': set()}
    ids = set()
    for doc, is_blind in ((fit, False), (blind, True)):
        cases = doc['cases']
        if type(cases) is not list or not cases:
            raise Invalid('missing source case rows')
        for c in cases:
            required = {'case_id','source_id','group_id','condition','joint_input',
                        'view_sha256','evidence_sha256','retrieved_source_id',
                        'annotated_answer_source_sha256','split'}
            if type(c) is not dict or set(c) != (required if is_blind else required | {'label'}):
                raise Invalid('case contains forbidden/unknown label fields')
            if (c['case_id'] in ids or type(c['case_id']) is not str or
                    c['case_id'] != digest(f"{c['source_id']}:{c['condition']}".encode())[:24]):
                raise Invalid('duplicate/invalid case identity')
            ids.add(c['case_id'])
            j = c['joint_input']
            if (type(j) is not dict or set(j) != {'state','question','options'} or
                    j['options'] != ['not_supported','supported'] or
                    type(j['question']) is not str or type(j['state']) is not str or
                    digest(canonical(j)) != c['view_sha256'] or
                    digest(j['state'].encode()) != c['evidence_sha256']):
                raise Invalid('modified visible model input')
            part = c['split']
            if part not in groups or (is_blind != (part == 'test')):
                raise Invalid('evaluation labels/source mixed into fitting material')
            if c['condition'] not in CONDITIONS:
                raise Invalid('unregistered Reader intervention')
            if not is_blind:
                expected=(1 if c['condition']=='sufficient' else
                          0 if c['condition'] in ('none','premise_removed') else
                          1 if c['retrieved_source_id']==c['source_id'] else None)
                if (c['label'] != expected or
                        (c['label'] is not None and type(c['label']) is not int)):
                    raise Invalid('invalid original-span/mechanical training class')
            groups[part].add(c['group_id'])
    for a in groups:
        if len(groups[a]) != WANTED[a]:
            raise Invalid(f'missing source groups in {a}')
        for b in groups:
            if a != b and groups[a] & groups[b]:
                raise Invalid('shared document across fit/calibration/test')
    # Independently reconstruct all source-condition views from their actual
    # model-facing bytes. Self-consistent SHA updates are not source authority.
    # This check runs before ANY pretrained loader is imported or executed.
    prompt_pattern = re.compile(
        r'Can the supplied passage explicitly support the proposed answer "(.+?)" '
        r'to the question "(.+?)"\?')
    for doc in (fit, blind):
        by_split = {}
        for c in doc['cases']:
            part = c['split']
            by_split.setdefault(part, {}).setdefault(c['source_id'], {})
            siblings = by_split[part][c['source_id']]
            if c['condition'] in siblings:
                raise Invalid('duplicate original source evidence condition')
            siblings[c['condition']] = c
        for split, groups_for_split in by_split.items():
            selected = []
            for source_id, paired in groups_for_split.items():
                if set(paired) != set(CONDITIONS):
                    raise Invalid('missing one of four paired evidence interventions')
                original = paired['sufficient']
                group = original['group_id']
                origin_sha = original['annotated_answer_source_sha256']
                original_view = original['joint_input']
                if digest(original_view['state'].encode()) != origin_sha:
                    raise Invalid('source context and annotated original digest disagree')
                original_prompt = original_view['question']
                match = prompt_pattern.fullmatch(original_prompt)
                if match is None or not match.group(1) or not match.group(2):
                    raise Invalid('unregistered original answer/question framing')
                answer, question = match.groups()
                for c in paired.values():
                    if (c['group_id'] != group or c['annotated_answer_source_sha256'] != origin_sha or
                            c['split'] != split or c['joint_input']['question'] != original_prompt or
                            c['joint_input']['options'] != original_view['options']):
                        raise Invalid('four evidence conditions changed original task identity')
                if (paired['none']['joint_input']['state'] != '(no evidence provided)' or
                        any(c['retrieved_source_id'] is not None for key,c in paired.items() if key != 'retrieved')):
                    raise Invalid('no-evidence or nonretrieved input changed')
                evidence = original_view['state']
                if answer.casefold() not in evidence.casefold():
                    raise Invalid('human positive answer absent from original evidence')
                try:
                    # SQuAD span start is intentionally NOT in the model input.
                    # A unique answer-bearing sentence must be reproducibly removed.
                    expected_removed, _ = remove_answer_sentence(
                        evidence, evidence.index(answer), answer)
                except (Invalid, ValueError) as error:
                    raise Invalid('original evidence cannot reproduce premise deletion') from error
                if paired['premise_removed']['joint_input']['state'] != expected_removed:
                    raise Invalid('premise deletion was altered despite valid-looking hashes')
                selected.append({'source_id': source_id, 'context': evidence, 'question': question})
            matched = bm25_neighbors(selected)
            for source_id, paired in groups_for_split.items():
                expected_donor = matched[source_id]
                retrieved = paired['retrieved']
                if (retrieved['retrieved_source_id'] != expected_donor or
                        retrieved['joint_input']['state'] !=
                        groups_for_split[expected_donor]['sufficient']['joint_input']['state']):
                    raise Invalid('retrieval not equal to registered question-only BM25 source')
    return fit['cases'], blind['cases']


def tensor_sha(module):
    import torch
    h = hashlib.sha256(b'hepta.p0-reader-head-f32.v1')
    for key, tensor in sorted(module.state_dict().items()):
        t = tensor.detach().cpu().to(torch.float32).contiguous()
        h.update(key.encode()+b'\0'+t.numpy().tobytes())
    return h.hexdigest()


def train_frozen_heads(fit_rows, blind_rows, feature_map, width):
    """Actual Torch SGD over train labels only; calibration used ONLY for temperature."""
    import torch
    import torch.nn.functional as F
    torch.set_num_threads(1)
    if set(feature_map) != {x['case_id'] for x in fit_rows+blind_rows}:
        raise Invalid('partial Encoder features')
    if any(len(feature_map[x['case_id']]) != width for x in fit_rows+blind_rows):
        raise Invalid('feature dimension mismatch')
    train = [x for x in fit_rows if x['split']=='train' and x['label'] is not None and x['condition']!='retrieved']
    cal = [x for x in fit_rows if x['split']=='calibration' and x['label'] is not None and x['condition']!='retrieved']
    if len(train) != WANTED['train']*3 or len(cal) != WANTED['calibration']*3:
        raise Invalid('missing human-backed sufficient and mechanical negative training set')
    def xs(rows):
        return torch.tensor([feature_map[x['case_id']] for x in rows], dtype=torch.float32)
    torch.manual_seed(SEED)
    learner = torch.nn.Linear(width, 2)
    original = copy.deepcopy(learner).eval()
    param_count = sum(p.numel() for p in learner.parameters())
    if param_count != 2*width+2 or param_count > 2048:
        raise Invalid('unregistered Head parameter ceiling')
    init_sha = tensor_sha(original)
    train_x = xs(train)
    train_y = torch.tensor([x['label'] for x in train], dtype=torch.long)
    cal_x = xs(cal)
    cal_y = torch.tensor([x['label'] for x in cal], dtype=torch.long)
    opt = torch.optim.SGD(learner.parameters(), lr=LR)
    start = time.perf_counter_ns()
    for _ in range(STEPS):
        opt.zero_grad(set_to_none=True)
        logits = learner(train_x)
        loss = F.cross_entropy(logits, train_y, weight=torch.tensor([1., 2.]))
        if not torch.isfinite(loss).item():
            raise Invalid('nonfinite training objective')
        loss.backward()
        opt.step()
    train_ms = (time.perf_counter_ns()-start)/1e6
    if tensor_sha(original) != init_sha or tensor_sha(learner) == init_sha:
        raise Invalid('frozen control mutated or training changed no weights')
    outputs = {}
    for name, net in (('frozen_head', original), ('trained_head', learner.eval())):
        with torch.inference_mode():
            # Only calibration labels are used to select temperature.
            logits = net(cal_x)
            tau = min(TEMPERATURES, key=lambda t: float(F.cross_entropy(logits/t,cal_y)))
            scores = []
            for row in blind_rows:
                start = time.perf_counter_ns()
                feature = torch.tensor(feature_map[row['case_id']], dtype=torch.float32).unsqueeze(0)
                prob = float(F.softmax(net(feature)/tau, dim=-1)[0,1])
                latency = (time.perf_counter_ns()-start)/1e6
                if not math.isfinite(prob):
                    raise Invalid('nonfinite evidence probability')
                scores.append({'case_id':row['case_id'],'view_sha256':row['view_sha256'],
                               'positive_probability':prob,'head_forward_ms':latency})
        outputs[name] = {'head_sha256': tensor_sha(net), 'calibration_temperature':tau,
                         'predictions': scores}
    return {'optimization': 'torch.optim.SGD', 'learning_rate': LR, 'seed': SEED,
            'steps': STEPS, 'trained_head_parameters':param_count,
            'head_train_ms':train_ms, 'initialized_frozen_weight_sha256':init_sha,
            'fit_case_id_sha256':digest(canonical([x['case_id'] for x in train])),
            'calibration_case_id_sha256':digest(canonical([x['case_id'] for x in cal])),
            'train_only_gradient_update':True, 'control':outputs}


def do_compact(model_name, fit, blind, args):
    from e1_public_triplet_real_cpu import encode_pretrained
    revision, width = COMPACT_REVISIONS[model_name]
    all_cases = fit+blind
    start = time.perf_counter_ns()
    feature_map, tokens, feature_digests, physical = encode_pretrained(
        all_cases, model_name, args.compact_checkout, args.gemma_checkout, args.gemma_manifest)
    if not len(feature_map) == len(all_cases) or any(v>512 for v in tokens.values()):
        raise Invalid('missing physical pretrained feature or truncation')
    encoder_ms=(time.perf_counter_ns()-start)/1e6
    fit_result = train_frozen_heads(fit, blind, feature_map, width)
    for control in fit_result['control'].values():
        for item in control['predictions']:
            item['encoder_forward_ms'] = physical['encode_ms_by_case'][item['case_id']]
    return {'model':model_name,'model_revision':revision,'feature_width':width,
            'head_mode':'frozen_same_initialization_vs_real_sgd',
            'physical_model_load_and_encodings_ms':encoder_ms,
            'model_load_ms':physical['load_ms'],
            'original_e1_loader_preflight_claimed':True,
            'mmbert_whole_serialized_checkpoint_byte_checked':(
                physical['mmbert_all_serialized_weights_byte_verified'] is True
                if model_name=='mmbert_small' else None),
            'whole_checkpoint_sha256':physical.get('mmbert_whole_pretrained_checkpoint_sha256'),
            'physical_encoder_api_requests':physical['local_model_api_requests'],
            'source_feature_q24_sha256':digest(canonical(feature_digests)),
            'training':fit_result}


def do_laya(blind):
    # A different, checkpoint-native decision policy: not a trained 2K Head arm.
    # Laya 0.3.20 native load() does NOT expose revision or compile
    # keywords. Fetch and SHA-verify the exact original snapshot first,
    # then require its native loader to consume that local checkpoint only.
    from p0_laya_snapshot_v14 import load_pinned_laya
    start = time.perf_counter_ns()
    agent, original_snapshot = load_pinned_laya()
    load_ms = (time.perf_counter_ns()-start)/1e6
    if (original_snapshot['model_revision'] != LAYA_SHA or
            original_snapshot['model'] != LAYA_ID or
            original_snapshot['authority'] != 'DENY_ALL'):
        raise Invalid('Laya original pinned snapshot lineage mismatch')
    results=[]
    for row in blind:
        start = time.perf_counter_ns()
        prompt = row['joint_input']
        questions = {'supports': {'type':'noul', 'instructions': prompt['question']}}
        answer = agent.predict(prompt['state'], questions)
        probability = answer['answers']['supports']['noul']
        if type(probability) not in (int,float) or not math.isfinite(probability) or not 0<=probability<=1:
            raise Invalid('Laya no-change probability missing/out of bounds')
        results.append({'case_id':row['case_id'],'view_sha256':row['view_sha256'],
                        'positive_probability':float(probability),
                        'full_request_ms':(time.perf_counter_ns()-start)/1e6})
    return {'model':'laya421_nochange','model_revision':LAYA_SHA,
            'feature_width':None,'head_mode':'pretrained_checkpoint_native_noul_nochange_not_equal_head',
            'model_load_ms':load_ms,'physical_encoder_api_requests':len(blind),
            'original_laya_snapshot_observation':original_snapshot,
            'training':None,'control':{'laya_native_nochange':{'predictions':results}}}


def run(args):
    fit_doc = read(args.fit)
    blind_doc = read(args.blind)
    fit, blind = validate_materials(fit_doc, blind_doc)
    if args.output.exists():
        raise FileExistsError('create-only original prediction seal')
    if args.model in COMPACT_REVISIONS:
        if args.compact_checkout is None or (args.model=='embeddinggemma_2_text' and
                                            (args.gemma_checkout is None or args.gemma_manifest is None)):
            raise Invalid('missing reviewed-source checkout / Gemma tensor manifest')
    started = time.perf_counter_ns()
    cpu_start = time.process_time_ns()
    if args.model == 'laya421_nochange':
        observed = do_laya(blind)
    else:
        observed = do_compact(args.model, fit, blind, args)
    observed.update({'schema': 'hepta.p0.squad-physical-reader-receipt.v1',
                     'fit_material_sha256': digest(canonical(fit_doc)),
                     'blind_material_sha256': digest(canonical(blind_doc)),
                     'number_blind_cases':len(blind),
                     'actual_pretrained_execution_claimed':True,
                     'source_model_independently_authenticated':False,
                     'physical_model_calls_independently_authenticated':False,
                     'human_independent_premise_reviewed':False,
                     'future_outcomes_verified':False,
                     'cpu_process_ms':(time.process_time_ns()-cpu_start)/1e6,
                     'end_to_end_wall_ms':(time.perf_counter_ns()-started)/1e6,
                     'peak_process_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                     'model_winner_selected':False,
                     'production_promotion_permitted':False,'authority':'DENY_ALL'})
    # Prediction seal is entirely label-free; label scoring lives in a different job.
    write_new(args.output, observed)
    return observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',choices=MODELS,required=True)
    parser.add_argument('--fit',type=Path,required=True)
    parser.add_argument('--blind',type=Path,required=True)
    parser.add_argument('--compact-checkout',type=Path)
    parser.add_argument('--gemma-checkout',type=Path)
    parser.add_argument('--gemma-manifest',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    r=run(args)
    print(json.dumps({'model':r['model'],'sealed_original_prediction_sha256':digest(canonical(r)),
                      'full_weight_execution_claimed':True,'promotion':False},sort_keys=True))


if __name__ == '__main__':
    main()
