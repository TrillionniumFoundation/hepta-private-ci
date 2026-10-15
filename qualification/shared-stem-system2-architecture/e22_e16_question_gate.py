"""E22 research: source-only bridge of E15/E16 frozen, 4-passage heldout answers.

No original human label, score ZIP, or parquet is ever opened in this process.
All seven historical source archives are pinned by the actual hosted ZIP digest;
results are *not* an online selection or NDU activation path.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from e21_whole_question import (load_blind_source, _zip, _json_bytes, once,
                                SOURCE_SHA, SCHEMA as E21_SCHEMA, ALL as E15_METHODS)
from e14_multirc_route import OBS_ID

SCHEMA = 'hepta.e22.original-pretrained-e16-e15-eight-arm-blind.v1'
E16_HEAD = '09d0528d95ca2cab997d4e17f499b098dc1fdb29'
E16_METHODS = ('centered_raw_5', 'centered_scaled_5')
E16_FOLDS = (
    (11950242845, '1ad37a6ce022e8d051467db52a59a9ea2a683aa57f04c9b51867f4c7db136ab9',
     '62f55e09ab8e669e0337c184a911ac5e4b00ff2adbd899f127bdeaea53cb93bd'),
    (11950188043, '67dff7033303ddef4fedd06b8b4e7af105b24d154eb4069072c69525bca2991e',
     'fc8eba10607f3b33c61b9c05607f71946fc5c4521fdd8356b2bf8a51da3b355d'),
    (11949868664, '990ba455578abe57ac8cb031633d3a73cc1dd488f5a418f20045334f845b9eaa',
     'f1ae0d287973ba942b05d57e0da3e5735c1505eae7f19b6fc7eda77c700f9c21'),
    (11950201953, 'ff172d1c44f31c134c5793520127a9fd166d9ad26138f88f86ce95191550f934',
     '5913dc0fb5d61f480db50225382b76b0556c34cf773c2b4a2f7157e771bb1eb2'),
)
ALL = E15_METHODS + E16_METHODS


def blind_e22(original_zip: str, e15_folds: list[str], e16_folds: list[str]) -> dict:
    if type(e15_folds) is not list or type(e16_folds) is not list or len(e16_folds) != 4:
        raise ValueError('four E15 and four E16 exact heldout folds required')
    ancestor = load_blind_source(original_zip, e15_folds)
    if (ancestor['schema'] != E21_SCHEMA or ancestor['authority'] != 'DENY_ALL'
            or ancestor['held_human_labels_opened'] is not False
            or ancestor['real_pretrained_forwards_new'] != 0):
        raise ValueError('E21 original blind state not admissible')
    rows = deepcopy(ancestor['rows'])
    groups = sorted({r['source_group'] for r in rows})
    registered = {r['task_id']: r for r in rows}
    touched = set()
    meters = []
    for fold, (_, outer, inner) in enumerate(E16_FOLDS):
        parts = _zip(e16_folds[fold], outer,
                     ('held-prediction.json', 'held-prediction.sha256', 'source-head.txt'))
        if sha256(parts['held-prediction.json']).hexdigest() != inner:
            raise ValueError('E16 exact held-model member tampered')
        if parts['held-prediction.sha256'].decode().split()[0] != inner:
            raise ValueError('original E16 model receipt differs from source')
        if parts['source-head.txt'].decode().strip() != E16_HEAD:
            raise ValueError('E16 physical Head committed at different source')
        d = _json_bytes(parts['held-prediction.json'])
        required = {'authority', 'fold', 'held_group', 'held_human_labels_accessed',
                    'meters', 'methods', 'natural_future_task_gain', 'original_archive_sha256',
                    'original_model_forwards_new', 'original_observation_id',
                    'physical_train_steps_completed', 'predictions', 'production_accepted',
                    'reader_semantic_adequacy_proven', 'schema', 'total_service_cost_measured',
                    'train_only_material_sha256', 'train_only_past_groups', 'train_only_scaling', 'weights'}
        if (type(d) is not dict or set(d) != required
                or d['schema'] != 'hepta.e16.answer-centered-real-logits.v1'
                or d['authority'] != 'DENY_ALL' or type(d['fold']) is not int
                or d['fold'] != fold or d['held_group'] != groups[fold]
                or d['original_archive_sha256'] != SOURCE_SHA
                or d['original_observation_id'] != OBS_ID
                or d['held_human_labels_accessed'] is not False
                or d['natural_future_task_gain'] is not False
                or d['production_accepted'] is not False
                or d['reader_semantic_adequacy_proven'] is not False
                or d['total_service_cost_measured'] is not False
                or type(d['original_model_forwards_new']) is not int
                or d['original_model_forwards_new'] != 0
                or d['physical_train_steps_completed'] != 48
                or d['train_only_past_groups'] != 3
                or d['methods'] != list(E16_METHODS)
                or type(d['predictions']) is not list
                or len(d['predictions']) != sum(r['source_group'] == groups[fold] for r in rows)):
            raise ValueError('unqualified or incomplete original E16 fold')
        if (type(d['weights']) is not dict or set(d['weights']) != set(E16_METHODS)
                or type(d['meters']) is not dict or set(d['meters']) != set(E16_METHODS)):
            raise ValueError('missing E16 learned tensor or physical meter')
        for method in E16_METHODS:
            w=d['weights'][method]
            m=d['meters'][method]
            if (type(w) is not list or len(w) != 5 or any(type(v) is not float for v in w)
                    or type(m) is not dict or set(m) != {'train_cpu_ns','held_cpu_ns','parameter_count','steps'}
                    or type(m['train_cpu_ns']) is not int or not 0<m['train_cpu_ns']<10**12
                    or type(m['held_cpu_ns']) is not int or not 0<m['held_cpu_ns']<10**12
                    or m['parameter_count'] != 5 or m['steps'] != 48):
                raise ValueError('E16 cost or five physical trainable parameters unqualified')
            meters.append({'fold':fold, 'method':method,'train_cpu_ns':m['train_cpu_ns'],
                           'held_cpu_ns':m['held_cpu_ns'], 'parameter_count':5, 'steps':48})
        for record in d['predictions']:
            if (type(record) is not dict or set(record) != {'task_id','source_group','question_slot',
                     'candidate_id','probabilities'} or record['source_group'] != groups[fold]
                    or record['task_id'] not in registered or record['task_id'] in touched):
                raise ValueError('E16 held source missing, repeated or changed')
            original = registered[record['task_id']]
            if (record['question_slot'] != original['question_slot']
                    or record['candidate_id'] != original['candidate_id']
                    or type(record['probabilities']) is not dict
                    or set(record['probabilities']) != set(E16_METHODS)):
                raise ValueError('E16 model decision not linked to authentic original candidate')
            for method in E16_METHODS:
                p=record['probabilities'][method]
                if type(p) is not float or not 0.0<p<1.0:
                    raise ValueError('invalid original trained heldout probability')
                original['probs'][method]=p
            touched.add(record['task_id'])
    if touched != set(registered) or any(set(r['probs']) != set(ALL) for r in rows):
        raise ValueError('not all original model actions represented')
    return {'schema':SCHEMA, 'authority':'DENY_ALL', 'production_accepted':False,
            'model_selected':False, 'system2_fbsde_permitted':False,
            'source_archive_sha256':SOURCE_SHA, 'e16_head':E16_HEAD,
            'human_labels_opened':False, 'new_pretrained_forwards':0,
            'source_passages':4, 'questions':8, 'candidates':33,
            'original_training_and_inference_costs_not_complete':True,
            'e16_observed_student_CPU_ns':meters, 'rows':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original',required=True)
    for i in range(4):
        p.add_argument(f'--e15-{i}',required=True)
        p.add_argument(f'--e16-{i}',required=True)
    p.add_argument('--out',required=True)
    a=p.parse_args()
    result=blind_e22(a.original,[getattr(a,f'e15_{i}') for i in range(4)],
                     [getattr(a,f'e16_{i}') for i in range(4)])
    print(once(a.out,result))

if __name__=='__main__':main()
