"""E21: independently score E15 real human held-out questions, not just candidates.

Research-only. Producer loads ONLY original pretrained prelabel logits and four
immutable E15 held-out model predictions. A distinct scoring process loads
actual human annotations and both E15 original score artifacts AFTER the
blind prediction file is sealed. Never a production learning/selection path.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

SOURCE_SHA = '1a9b485b6b1ee28c952934069b2cd4d765a17742655f3f3cb3339d3ca672ad17'
OBS_ID = '7e4a0dc4ff48688b1ace0640a3290ee90011487843384a30565b65d3d240e7a5'
E15_HEAD = 'd4d71baa8c00821fe385c1a47ed7b68b4255ad6e'
E15_FOLDS = (
    # original source-HEAD E15 hosted archive id, outer sha256, held prediction sha256
    (11949475467,'01ce78555923bd641b3c072157f89dc22f9105a070d0fe167bb945c210a429fc','b4a85de1f22d84a08559c43c02080c65a04acaf05de66ae3402f0d33df5efe2e'),
    (11948693014,'035d1efa3e05c4a15d1dd31456bf571f2499e53de3fd783e0ab28f0028639271','ab067963379099a6a6c8e9dcfde4367da04eacfed958219ed9ac0ff8a93d2a47'),
    (11949330575,'2a84cb7e2cf4d1fafb478eba0fe3b0111067a844bc3a71ecb68376b4762871b3','693744f0ae7633eb029c2b202582527e7dcc1fcf91e6b82ccf5913dae7a81ae0'),
    (11948993287,'6a0df6d14eb1fb5d8ddde40b448ddeb48551f214187dc056974e771c5ca28316','939f75a6d2fbadb535c55a53817dacefcb59d21a3fbbaedb3e6e50a855847a5f'),
)
E15_SCORES = (
    (11950611472,'f332ab92181a0e088d941dbf4c77165ab2e4c40e48e9bbda4915e8d1543aceb8',E15_HEAD),
    (11950935731,'63da90cb7da7f2f6ef478e44731e548a62a4b3c1a071593864f23b5896290acc','b2b863da702df9a43c657c7e45ec6c431bdf37f9'),
)
VAL_SHA = '5eb64893afc5af7828b2f3b41d6a4574eb7a82cbb17c86c75842f5f95f679ada'
FROZEN = ('conditioned','mean_pool_query_fused','no_evidence','no_query')
LEARNED = ('learned_linear_5','learned_gated_3')
ALL = FROZEN + LEARNED
SCHEMA = 'hepta.e21.real-reader-whole-question-blind.v1'
SCORE_SCHEMA = 'hepta.e21.original-human-question-level-review.v1'


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(data):
    def hook(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('duplicate JSON field')
            result[key]=value
        return result
    return json.loads(data,object_pairs_hook=hook,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON value')))


def _zip(path, expected, names):
    raw=Path(path).read_bytes()
    if len(raw)>4_000_000 or _sha(raw)!=expected:raise ValueError('wrong pinned external ZIP bytes')
    with ZipFile(path) as z:
        infos=z.infolist()
        actual=[i.filename for i in infos]
        if len(actual)>90 or len(actual)!=len(set(actual)) or any(i.file_size>1_000_000 or
                 i.filename.startswith('/') or '..' in i.filename.split('/') for i in infos):
            raise ValueError('invalid original ZIP inventory')
        if not set(names)<=set(actual):raise ValueError('missing exact E15 source member')
        # No unrelated ZIP member is decompressed, particularly no score/labels
        return {n:z.read(n) for n in names}


def _sigmoid(z):
    if type(z) not in (int,float) or not math.isfinite(z) or abs(z)>100:raise ValueError('unsupported logit')
    return 1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))


def load_blind_source(source_zip, fold_zips):
    if len(fold_zips)!=4:raise ValueError('four complete independently sealed E15 folds mandatory')
    original=_zip(source_zip,SOURCE_SHA,('multirc-native-candidate-audit/audit.json',
                                    'multirc-native-candidate-audit/COMMITTED.json'))
    obs=_json_bytes(original['multirc-native-candidate-audit/audit.json'])
    seal=_json_bytes(original['multirc-native-candidate-audit/COMMITTED.json'])
    if (type(obs) is not dict or obs.get('observation_id')!=OBS_ID or
            obs.get('schema')!='hepta.multirc.genuine-answer-slate-frozen-readers.v1' or
            obs.get('evaluation_labels_loaded') is not False or
            obs.get('production_authorized') is not False or
            seal.get('observation_sha256')!=_sha(original['multirc-native-candidate-audit/audit.json']) or
            seal.get('observation_id')!=OBS_ID):
        raise ValueError('original no-label pretrained source receipt invalid')
    rows=obs.get('rows'); preds=obs.get('predictions')
    if type(rows) is not list or len(rows)!=33 or type(preds) is not dict or set(preds)!=set(FROZEN):
        raise ValueError('incomplete frozen MultiRC source')
    groups=sorted({r['source_group'] for r in rows})
    if (len(groups)!=4 or len({(r['source_group'],r['question_slot']) for r in rows})!=8 or
        len({r['task_id'] for r in rows})!=33):raise ValueError('wrong question/source group census')
    joined={}
    for fold,(id,outer_sha,member_sha) in enumerate(E15_FOLDS):
        member=_zip(fold_zips[fold],outer_sha,('held-prediction.json','held-prediction.sha256','source-head.txt'))
        if _sha(member['held-prediction.json'])!=member_sha:
            raise ValueError('incorrect original E15 held prediction member')
        if member['source-head.txt'].decode().strip()!=E15_HEAD:
            raise ValueError('wrong E15 training source HEAD')
        declared=member['held-prediction.sha256'].decode().split()[0]
        if declared!=member_sha:raise ValueError('inconsistent E15 held prediction seal')
        record=_json_bytes(member['held-prediction.json'])
        if (record.get('authority')!='DENY_ALL' or record.get('production_accepted') is not False or
                record.get('held_original_human_labels_accessed') is not False or
                record.get('causal_improvement_established') is not False or
                record.get('full_training_cost_included') is not False or
                record.get('original_archive_sha256')!=SOURCE_SHA or
                record.get('original_observation_id')!=OBS_ID or
                type(record.get('fold')) is not int or record.get('fold')!=fold or
                record.get('held_group')!=groups[fold] or record.get('methods')!=list(LEARNED) or
                record.get('new_pretrained_forwards')!=0):
            raise ValueError('unqualified source fold')
        prediction=record.get('predictions')
        expected=[r for r in rows if r['source_group']==groups[fold]]
        if type(prediction) is not list or len(prediction)!=len(expected):
            raise ValueError('incomplete original held slate')
        for item,meta in zip(prediction,expected,strict=True):
            if (type(item) is not dict or set(item)!={'candidate_id','question_slot','source_group','task_id','probs'} or
                    any(item[k]!=meta[k] for k in ('candidate_id','question_slot','source_group','task_id')) or
                    type(item['probs']) is not dict or set(item['probs'])!=set(LEARNED)):
                raise ValueError('changed original held candidate identity')
            ps=item['probs']
            if any(type(p) is not float or not 0<p<1 for p in ps.values()):
                raise ValueError('invalid E15 probabilities')
            if item['task_id'] in joined:raise ValueError('duplicate held prediction')
            joined[item['task_id']]=ps
    if set(joined)!={r['task_id'] for r in rows}:
        raise ValueError('incomplete original held predictions')
    output=[]
    for i,meta in enumerate(rows):
        v=dict(joined[meta['task_id']]);
        for arm in FROZEN:
            r=preds[arm]
            if (type(r) is not list or len(r)!=33 or r[i].get('task_id')!=meta['task_id'] or
                  r[i].get('source_group')!=meta['source_group'] or
                  r[i].get('question_slot')!=meta['question_slot']):
                raise ValueError('missing original frozen Reader prediction')
            logits=r[i].get('logits')
            if type(logits) is not list or len(logits)!=2:
                raise ValueError('invalid frozen Reader logits')
            v[arm]=_sigmoid(logits[1]-logits[0])
        output.append({**{k:meta[k] for k in ('task_id','source_group','question_slot','candidate_id','original_v1_candidate')},
                       'probs':{arm:v[arm] for arm in ALL}})
    return {'schema':SCHEMA,'authority':'DENY_ALL','production_accepted':False,
            'source_archive_sha256':SOURCE_SHA,'e15_head':E15_HEAD,
            'real_pretrained_forwards_new':0,'held_human_labels_opened':False,
            'source_group_count':4,'question_count':8,'candidate_count':33,'rows':output}


def score_from_labels(blind,labels):
    """Original human labeling is injected only by second scorer, not blind producer."""
    if (type(blind) is not dict or set(blind)!=
            {'schema','authority','production_accepted','source_archive_sha256','e15_head',
            'real_pretrained_forwards_new','held_human_labels_opened','source_group_count','question_count',
            'candidate_count','rows'} or blind['schema']!=SCHEMA or
            blind['authority']!='DENY_ALL' or blind['production_accepted'] is not False or
            blind['source_archive_sha256']!=SOURCE_SHA or blind['e15_head']!=E15_HEAD or
            type(blind['real_pretrained_forwards_new']) is not int or blind['real_pretrained_forwards_new']!=0 or
            blind['held_human_labels_opened'] is not False or
            tuple(blind[k] for k in ('source_group_count','question_count','candidate_count'))!=(4,8,33)):
        raise ValueError('unqualified E21 blind record')
    rows=blind['rows']
    if (type(rows) is not list or len(rows)!=33 or type(labels) is not dict or
             {r['task_id'] for r in rows}!=set(labels)):
        raise ValueError('human truth/source count mismatch')
    group_counts=defaultdict(int);questions=defaultdict(list);grouped=defaultdict(list)
    accum={name:{'correct':0,'sum_brier':0.,'passage':defaultdict(list),'questions':defaultdict(list)} for name in ALL}
    for row in rows:
        if (type(row) is not dict or set(row)!={'task_id','source_group','question_slot','candidate_id','original_v1_candidate','probs'} or
                type(row['probs']) is not dict or set(row['probs'])!=set(ALL)):
            raise ValueError('incomplete candidate prediction')
        if type(row['original_v1_candidate']) is not bool: raise ValueError('invalid original candidate anchoring')
        task=row['task_id']; y=labels[task]
        if type(y) is not int or y not in (0,1):raise ValueError('missing original binary label')
        key=(row['source_group'],row['question_slot']); group=row['source_group']
        group_counts[group]+=1; questions[key].append(y)
        grouped[group].append(task)
        for method,p in row['probs'].items():
            if type(p) not in (float,int) or not math.isfinite(p) or not 0<p<1:
                raise ValueError('invalid real Reader probability')
            # E15 trained Head uses >=.5; original frozen logits argmax chooses 0 on tie.
            hit=int(((p>=0.5) if method in LEARNED else (p>0.5))==bool(y))
            a=accum[method];a['correct']+=hit;a['sum_brier']+=2*(p-y)**2
            a['passage'][group].append(hit);a['questions'][key].append(hit)
    if (len(group_counts)!=4 or len(questions)!=8 or len({r['task_id'] for r in rows})!=33 or
            not all(set(v)=={0,1} for v in questions.values())):
        raise ValueError('original complete mixed-question census failed')
    methods={}
    for method,a in accum.items():
        methods[method]={'correct':a['correct'],'total':33,'brier':a['sum_brier']/33,
            'accuracy':a['correct']/33,
            'complete_question_count':sum(all(v) for v in a['questions'].values()),
            'complete_passage_count':sum(all(v) for v in a['passage'].values()),
            'passage_correct':{g:sum(v) for g,v in sorted(a['passage'].items())},
            'passage_total':{g:len(v) for g,v in sorted(a['passage'].items())}}
    return methods


def signflip_p(group_deltas):
    """Exact 4-cluster two-sided sign-flip enumeration, DESCRIPTIVE only."""
    if type(group_deltas) is not list or len(group_deltas)!=4 or any(
        type(x) not in (float,int) or not math.isfinite(x) for x in group_deltas):
        raise ValueError('exact four original passage groups required')
    observed=abs(sum(group_deltas))
    outcomes=[abs(sum(sign*d for sign,d in zip(v,group_deltas)))
              for v in itertools.product((-1,1),repeat=4)]
    return sum(a>=observed-1e-12 for a in outcomes)/len(outcomes)


def _scores_zip(path, expected):
    data=_zip(path,expected,('original-human-e15-lopo-result.json','score.sha256','source-head.txt'))
    record=_json_bytes(data['original-human-e15-lopo-result.json'])
    if _sha(data['original-human-e15-lopo-result.json'])!=data['score.sha256'].decode().split()[0]:
        raise ValueError('wrong source-HEAD E15 human score seal')
    if (record.get('schema')!='hepta.e15.independent-original-human-lopo-head-score.v1' or
       record.get('production_accepted') is not False or record.get('authority')!='DENY_ALL'):
        raise ValueError('unqualified inherited original human outcome')
    return record


def evaluate(blind, labels, source_score_zip, synthetic_score_zip):
    scores=score_from_labels(blind,labels)
    records=[]
    for path,(_,digest,expected_head) in zip((source_score_zip,synthetic_score_zip),E15_SCORES):
        r=_scores_zip(path,digest)
        data=_zip(path,digest,('source-head.txt',))
        if data['source-head.txt'].decode().strip()!=expected_head:
            raise ValueError('scorer not bound to correct E15 source identity')
        if (r.get('source_archive_sha256')!=SOURCE_SHA or r.get('human_validation_sha256')!=VAL_SHA or
            r.get('independent_future_generations_established') is not False or
            r.get('original_passage_groups')!=4 or r.get('original_candidate_count')!=33 or
            r.get('trained_cell_head_production_admitted') is not False):
            raise ValueError('incomplete/incorrect human-label lineage')
        for method,cur in scores.items():
            original=r['summary'].get(method)
            if (type(original) is not dict or original['correct']!=cur['correct'] or
                 abs(original['brier']-cur['brier'])>2e-12 or
                 original['passage_correct']!=cur['passage_correct'] or
                 original['passage_total']!=cur['passage_total']):
                raise ValueError('independent truth score disagrees with BOTH original source and synthetic E15 jobs')
        records.append(r)
    baseline=scores['mean_pool_query_fused']
    learned=scores['learned_linear_5']
    deltas=[learned['passage_correct'][g]-baseline['passage_correct'][g]
            for g in sorted(baseline['passage_correct'])]
    brier_delta=learned['brier']-baseline['brier']
    return {'schema':SCORE_SCHEMA,'authority':'DENY_ALL','production_accepted':False,
            'source_original_human_labels_sha256':VAL_SHA,'human_score_source_head_and_synthetic_merge_reconciled':True,
            'original_pretrained_forward_calls_new':0,'original_human_passage_groups':4,
            'candidate_count':33,'original_question_count':8,'model_selected':False,
            'natural_task_efficacy_established':False,'cost_adjusted_gain_established':False,
            'whole_service_cost_established':False,'independent_future_group_established':False,
            'fbsde_reactivation_allowed':False,'method_results':scores,
            'contrast':{'candidate':'learned_linear_5','baseline':'mean_pool_query_fused',
                        'paired_passage_correct_deltas':deltas,
                        'correct_delta':learned['correct']-baseline['correct'],
                        'brier_delta':brier_delta,
                        'four_group_signflip_p_descriptive_only':signflip_p(deltas),
                        'training_cpu_ns_reported_range':[min(r['self_reported_CPU_ns']['head_training'] for r in records),
                                                       max(r['self_reported_CPU_ns']['head_training'] for r in records)],
                        'no_positive_cost_adjusted_claim':True},
            'original_source_and_merge_scores_reconciled':True}


def once(path,obj):
    data=(json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with Path(path).open('xb') as f:f.write(data)
    return _sha(data)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    subs=parser.add_subparsers(dest='mode',required=True)
    a=subs.add_parser('blind');a.add_argument('--original',required=True)
    for i in range(4):a.add_argument(f'--fold-{i}',required=True)
    a.add_argument('--out',required=True)
    s=subs.add_parser('score');s.add_argument('--blind',required=True)
    s.add_argument('--validation',required=True)
    s.add_argument('--e15-source',required=True)
    s.add_argument('--e15-merge',required=True);s.add_argument('--out',required=True)
    args=parser.parse_args()
    if args.mode=='blind':
        result=load_blind_source(args.original,[getattr(args,f'fold_{i}') for i in range(4)])
    else:
        raw=Path(args.validation).read_bytes()
        if _sha(raw)!=VAL_SHA:raise ValueError('original human material changed')
        import pyarrow.parquet as pq
        from e14_multirc_score import original_labels
        frame=pq.read_table(args.validation,columns=['paragraph','question','answer','label','idx']).to_pylist()
        blind=_json_bytes(Path(args.blind).read_bytes())
        original_ids=[{k:r[k] for k in ('task_id','source_group','question_slot',
                       'candidate_id','original_v1_candidate')} for r in blind['rows']]
        # original_labels only uses true candidate source identity and original source.
        labels=original_labels(frame,original_ids)
        result=evaluate(blind,labels,args.e15_source,args.e15_merge)
    print(once(args.out,result))

if __name__=='__main__':main()
