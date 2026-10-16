"""Independent post-seal scoring of ORIGINAL publisher MultiRC labels.

This evaluator does not import the producer, trainer, policy, or model. It
reconstructs paragraph/question/answer IDs directly from the original pinned
validation parquet, checks complete slates, and computes whole-question scores.
It does not attest weights, computation metering or real task generalization.
"""

import argparse
from collections import defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path

AUTHORITY = 'DENY_ALL'
SCHEMA = 'hepta.e27.answer-token-cell-shadow.v1'
VAL_SHA = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
DATA_REV = '4e14482c58d790d467ecfb29b6790e1917bf8756'
MODEL_REV = '8949b909ec900327062f0ebf497f51aef5e6f0c8'
TRAIN_SHA = 'ced6d731a335a0e4fbd29f6f382f291518952c0f449448361d294000c39e6728'
HELD_COUNT = 8


def read_bytes(path, max_bytes=12_000_000):
    raw = Path(path).read_bytes()
    if not 0 < len(raw) <= max_bytes:
        raise ValueError('missing/oversized independently opened source')
    def no_duplicate(pairs):
        ret = {}
        for k, v in pairs:
            if k in ret: raise ValueError('duplicate JSON field')
            ret[k] = v
        return ret
    return json.loads(raw, object_pairs_hook=no_duplicate,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite source')))


def digest(obj):
    return sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def true_source_roster(rows):
    """Independently replay *every* complete original paragraph/source choice."""
    if type(rows) is not list:
        raise ValueError('original validation parquet required')
    groups = {}
    excluded = set()
    seen_native = set()
    for row in rows:
        if (type(row) is not dict or set(row) != {'paragraph', 'question', 'answer', 'label', 'idx'} or
            type(row['idx']) is not dict or set(row['idx']) != {'paragraph', 'question', 'answer'}):
            raise ValueError('missing original published MultiRC row fields')
        pid, qid, aid = (row['idx'][k] for k in ('paragraph', 'question', 'answer'))
        if (any(type(x) is not int or not 0 <= x <= 100_000_000 for x in (pid, qid, aid)) or
            type(row['label']) is not int or row['label'] not in (0, 1)):
            raise ValueError('invalid original source row value')
        native_id=(pid,qid,aid)
        if native_id in seen_native:
            raise ValueError('duplicate original publisher native ID')
        seen_native.add(native_id)
        evidence, question, answer = (row[k] for k in ('paragraph', 'question', 'answer'))
        original=(evidence,question,answer)
        if any(x is not None and type(x) is not str for x in original):
            raise ValueError('invalid source text type')
        if any(isinstance(x,str) and len(x.encode())>1_048_576 for x in original):
            raise ValueError('unbounded publisher source')
        if (any(x is None or not x.strip() for x in original) or
            not 0 < len(evidence.encode()) <= 32000 or
            not 0 < len(question.encode()) <= 4096 or
            not 0 < len(answer.encode()) <= 4096):
            excluded.add(pid)
            continue
        if pid in excluded:
            continue
        p = groups.setdefault(pid, {'evidence': evidence, 'q': {}})
        if p['evidence'] != evidence:
            raise ValueError('paragraph mismatch')
        q = p['q'].setdefault(qid, {'text': row['question'], 'a': {}})
        if q['text'] != row['question'] or aid in q['a']:
            raise ValueError('original answer collision')
        q['a'][aid] = (row['answer'], row['label'])
    result = []
    for pid, value in groups.items():
        if pid in excluded:
            continue
        p = value['evidence']
        p_id = sha256(f'validation:{pid}:{sha256(p.encode()).hexdigest()}'.encode()).hexdigest()
        questions = []
        for qid, q in sorted(value['q'].items()):
            if not 2 <= len(q['a']) <= 8: continue
            q_id = sha256(f'{p_id}:{qid}:{sha256(q["text"].encode()).hexdigest()}'.encode()).hexdigest()
            answers = []
            for aid, (text, label) in sorted(q['a'].items()):
                cid = sha256(f'{p_id}:{qid}:{aid}:{sha256(text.encode()).hexdigest()}'.encode()).hexdigest()
                answers.append((cid, label))
            questions.append((q_id, tuple(answers)))
        if 1 <= len(questions) <= 16:
            result.append((p_id, tuple(questions)))
    result.sort(key=lambda g: g[0])
    if len(result) < HELD_COUNT:
        raise ValueError('original source insufficient for frozen held count')
    return result[:HELD_COUNT]


def _sigmoid(value):
    if type(value) not in (float, int) or not math.isfinite(value) or abs(value) >= 100:
        raise ValueError('malformed neural Head logit')
    return 1 / (1 + math.exp(-value))


def exact_sign_test(increments):
    """Two-sided exact sign-flip over NONZERO SOURCE-PARAGRAPH differences."""
    vals = [abs(x) for x in increments if x]
    if not vals: return 1.0
    if len(vals) > 12: raise ValueError('unbounded exact source permutation panel')
    target = abs(sum(increments))
    extreme = 0
    for mask in range(1 << len(vals)):
        statistic = sum((1 if mask & (1 << i) else -1) * v for i,v in enumerate(vals))
        extreme += int(abs(statistic) >= target)
    return extreme / (1 << len(vals))


def score(blind, original_validation_rows, *, trained_source_sha=None, held_material=None, original_gold=None):
    if (type(blind) is not dict or set(blind) != {
        'schema', 'authority', 'train_material_sha256', 'held_material_sha256',
        'model_revision', 'encoder_checkpoint_digest_profile', 'shared_encoder_calls',
        'train_shared_encoder_calls', 'held_shared_encoder_calls', 'train_question_count',
        'held_question_count', 'train_candidate_count', 'held_candidate_count',
        'head_budgets', 'physical_meter', 'predictions', 'real_pretrained_encoder',
        'held_labels_loaded_during_fit_or_blind', 'task_gain_established',
        'ndu_fbsde_activation', 'production_accepted'
    } or blind['schema'] != SCHEMA + '.blind' or blind['authority'] != AUTHORITY or
        blind['model_revision'] != MODEL_REV or
        blind['real_pretrained_encoder'] is not True or
        blind['held_labels_loaded_during_fit_or_blind'] is not False or
        any(blind[k] is not False for k in
            ('task_gain_established', 'ndu_fbsde_activation', 'production_accepted')) or
        type(blind['train_material_sha256']) is not str or
        len(blind['train_material_sha256']) != 64 or
        type(blind['held_material_sha256']) is not str or
        len(blind['held_material_sha256']) != 64 or
        type(blind['encoder_checkpoint_digest_profile']) is not str or
        blind['encoder_checkpoint_digest_profile'] != '340ac08b74eef0d7bdec2d7981a6a3d4249bf0e6aab60634b72ad02c2b8023a9'):
        raise ValueError('missing owner / model / safety provenance')
    if trained_source_sha is not None and blind['train_material_sha256'] != trained_source_sha:
        raise ValueError('training source artifact identity mismatch')
    if (type(blind['head_budgets']) is not dict or set(blind['head_budgets']) != {'aware','answer_muted'} or
        any(type(x) is not dict for x in blind['head_budgets'].values())):
        raise ValueError('missing matched Head budget')
    aw, muted = blind['head_budgets']['aware'], blind['head_budgets']['answer_muted']
    if (aw['optimizer_steps'] != 64 or muted['optimizer_steps'] != 64 or
        aw['parameter_count'] != muted['parameter_count'] or
        aw['question_batches'] != muted['question_batches'] or
        aw['training_examples'] != muted['training_examples'] or
        aw['answer_visible'] is not True or muted['answer_visible'] is not False):
        raise ValueError('unmatched or unmeasured neural training')
    for measure in ['fit_cpu_ns','fit_wall_ns']:
        if any(type(v[measure]) is not int or v[measure] <= 0 for v in (aw,muted)):
            raise ValueError('training did not physically execute')
    roster = true_source_roster(original_validation_rows)
    expectation = {}
    for group_id, questions in roster:
        for qid, alternatives in questions:
            for cid, label in alternatives:
                key = (group_id, qid, cid)
                if key in expectation: raise ValueError('duplicate independent true source')
                expectation[key] = label
    if held_material is not None:
        if (type(held_material) is not dict or
            held_material.get('schema') != SCHEMA + '.material' or
            held_material.get('role') != 'held' or
            held_material.get('source_sha256') != VAL_SHA or
            held_material.get('authority') != AUTHORITY or
            digest(held_material) != blind['held_material_sha256'] or
            type(held_material.get('groups')) is not list or
            len(held_material['groups']) != HELD_COUNT):
            raise ValueError('unbound or mismatched public held source material')
        # Rebuild every text triple directly from original publisher rows,
        # independently of the original producer and its parsed material.
        truth_text = {}
        accepted_groups = {g for g,_ in roster}
        for source in original_validation_rows:
            pid, qid, aid = (source['idx'][k] for k in ('paragraph','question','answer'))
            evidence, question, answer = (source[k] for k in ('paragraph','question','answer'))
            if not isinstance(evidence,str) or not isinstance(question,str) or not isinstance(answer,str):
                continue
            gid = sha256(f'validation:{pid}:{sha256(evidence.encode()).hexdigest()}'.encode()).hexdigest()
            if gid not in accepted_groups:
                continue
            q = sha256(f'{gid}:{qid}:{sha256(question.encode()).hexdigest()}'.encode()).hexdigest()
            cid = sha256(f'{gid}:{qid}:{aid}:{sha256(answer.encode()).hexdigest()}'.encode()).hexdigest()
            triple = (evidence,question,answer)
            if (gid,q,cid) in truth_text and truth_text[(gid,q,cid)] != triple:
                raise ValueError('ambiguous original source content')
            truth_text[(gid,q,cid)] = triple
        reconstructed = set()
        for group in held_material['groups']:
            if set(group) != {'group_id','evidence','questions'}:
                raise ValueError('wrong source envelope')
            for question in group['questions']:
                if set(question) != {'question_id','text','candidates'}:
                    raise ValueError('wrong question envelope')
                for c in question['candidates']:
                    if set(c) != {'candidate_id','text'}:
                        raise ValueError('private label in public held source')
                    key=(group['group_id'],question['question_id'],c['candidate_id'])
                    if (key in reconstructed or
                        truth_text.get(key) != (group['evidence'],question['text'],c['text'])):
                        raise ValueError('forged original question, answer or evidence bytes')
                    reconstructed.add(key)
        if reconstructed != set(expectation):
            raise ValueError('omitted authentic original source candidate')
    if original_gold is not None:
        if (type(original_gold) is not dict or
            set(original_gold) != {'schema','authority','source_revision',
            'source_sha256','held_material_sha256','cases','production_accepted'} or
            original_gold['schema'] != SCHEMA + '.original-held-gold' or
            original_gold['authority'] != AUTHORITY or
            original_gold['source_revision'] != DATA_REV or
            original_gold['source_sha256'] != VAL_SHA or
            original_gold['production_accepted'] is not False or
            original_gold['held_material_sha256'] != blind['held_material_sha256'] or
            type(original_gold['cases']) is not list):
            raise ValueError('untrusted independently segregated gold receipt')
        external = {}
        for row in original_gold['cases']:
            if type(row) is not dict or set(row) != {'source_group','question_id','candidate_id','label'}:
                raise ValueError('original gold case is missing exact fields')
            key = (row['source_group'],row['question_id'],row['candidate_id'])
            if key in external or type(row['label']) is not int or row['label'] not in (0,1):
                raise ValueError('duplicates or invalid independent gold')
            external[key] = row['label']
        if external != expectation:
            raise ValueError('original publisher label or source mismatch')
    if (type(blind['predictions']) is not list or
        len(blind['predictions']) != len(expectation) or
        blind['held_question_count'] != sum(len(questions) for _, questions in roster) or
        blind['held_candidate_count'] != len(expectation)):
        raise ValueError('incomplete original held source inventory')
    num_train = blind['train_candidate_count']
    num_held = blind['held_candidate_count']
    n_train_q, n_held_q = blind['train_question_count'], blind['held_question_count']
    if (any(type(x) is not int or x < 1 for x in (num_train,num_held,n_train_q,n_held_q)) or
        blind['train_shared_encoder_calls'] != 48 + n_train_q + num_train or
        blind['held_shared_encoder_calls'] != HELD_COUNT + n_held_q + num_held or
        blind['shared_encoder_calls'] != blind['train_shared_encoder_calls'] + blind['held_shared_encoder_calls']):
        raise ValueError('missing/forged actual shared model-call census')
    physical = blind['physical_meter']
    if (type(physical) is not dict or set(physical) != {
        'feature_generation_cpu_ns','head_inference_cpu_ns','model_encoder_cpu_ns',
        'model_encoder_wall_ns','model_tokens','truncated_sequences'
    } or any(type(physical[k]) is not int or physical[k] <= 0 for k in physical if k != 'truncated_sequences') or
        type(physical['truncated_sequences']) is not int or
        not 0 <= physical['truncated_sequences'] <= blind['shared_encoder_calls']):
        raise ValueError('missing physical time/token model receipt')
    seen = set()
    totals = {arm: {'correct':0,'brier_sum':0.0,'whole_question_correct':0,
                    'within_question_span_sum':0.0,'mixed_label_questions':0}
              for arm in ('aware','answer_muted')}
    perquestion = defaultdict(lambda: defaultdict(list))
    perparagraph = defaultdict(lambda: {'aware':0,'answer_muted':0})
    for row in blind['predictions']:
        if type(row) is not dict or set(row) != {'source_group','question_id','candidate_id','logits'}:
            raise ValueError('untrusted Head prediction row')
        key = row['source_group'],row['question_id'],row['candidate_id']
        if key in seen or key not in expectation:
            raise ValueError('missing/duplicate/synthetic candidate')
        seen.add(key)
        if type(row['logits']) is not dict or set(row['logits']) != set(totals):
            raise ValueError('unregistered prediction arm')
        for arm in totals:
            p = _sigmoid(row['logits'][arm]); y = expectation[key]
            totals[arm]['correct'] += int((p >= 0.5) == y)
            totals[arm]['brier_sum'] += (p-y)**2
            perquestion[(key[0],key[1])][arm].append((p,y))
    if seen != set(expectation):
        raise ValueError('incomplete verified original candidates')
    for (group_id, _qid), v in perquestion.items():
        for arm, values in v.items():
            correct = all((p>=0.5)==y for p,y in values)
            totals[arm]['whole_question_correct'] += int(correct)
            perparagraph[group_id][arm] += int(correct)
            totals[arm]['within_question_span_sum'] += max(p for p,_ in values) - min(p for p,_ in values)
            totals[arm]['mixed_label_questions'] += int({y for _,y in values} == {0,1})
    n_questions = blind['held_question_count']
    result = {}
    for arm,v in totals.items():
        result[arm] = {
            'candidate_correct': v['correct'], 'candidate_total': len(expectation),
            'candidate_brier': v['brier_sum']/len(expectation),
            'whole_question_correct':v['whole_question_correct'],
            'whole_question_total': n_questions,
            'mean_answer_probability_span':v['within_question_span_sum']/n_questions,
            'mixed_label_question_count':v['mixed_label_questions'],
        }
    paired = [v['aware']-v['answer_muted'] for _,v in sorted(perparagraph.items())]
    return {'schema':SCHEMA+'.original-review', 'authority':AUTHORITY,
            'original_source_revision':DATA_REV,'original_validation_sha256':VAL_SHA,
            'original_training_sha256':TRAIN_SHA,
            'observed_publisher_source_paragraphs':HELD_COUNT,
            'blind_semantic_source_digest':digest(blind),
            'results':result,
            'by_source_question_gain_aware_minus_muted':paired,
            'source_level_exact_signflip_p_two_sided':exact_sign_test(paired),
            'same_original_dataset_family':True,
            'physical_pretrained_origin_signature_verified':False,
            'neural_training_numerically_replayed_independently':False,
            'model_logits_independently_reforwarded':False,
            'bounded_token_truncation_count':physical['truncated_sequences'],
            'complete_lifecycle_cost_or_energy_qualified':False,
            'future_time_or_independent_data_family_verified':False,
            'ndu_full_fbsde_gain_established':False,
            'model_selected':False,'production_accepted':False}


def main():
    p=argparse.ArgumentParser()
    for name in ('blind','validation-parquet','train-material','held-material','original-gold','output'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args()
    from multirc_materials import load_parquet
    raw=Path(a.validation_parquet).read_bytes()
    if sha256(raw).hexdigest()!=VAL_SHA:
        raise ValueError('original publisher validation Parquet SHA mismatch')
    orig=load_parquet(a.validation_parquet, expected_sha256=VAL_SHA)
    blind=read_bytes(a.blind)
    train=read_bytes(a.train_material)
    if (train.get('schema')!=SCHEMA+'.material' or train.get('role')!='train' or
        train.get('source_sha256')!=TRAIN_SHA or train.get('authority')!=AUTHORITY):
        raise ValueError('invalid frozen train-only registration')
    out=score(blind, orig, trained_source_sha=digest(train),
              held_material=read_bytes(a.held_material),
              original_gold=read_bytes(a.original_gold))
    b=(json.dumps(out,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    target=Path(a.output); target.parent.mkdir(parents=True,exist_ok=True)
    with target.open('xb') as f:
        f.write(b);f.flush()
        import os;os.fsync(f.fileno())
    print(json.dumps({'authority':AUTHORITY,'source_group_count':HELD_COUNT,
                      'sha256':sha256(b).hexdigest()}))

if __name__ == '__main__':
    main()
