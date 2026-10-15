"""E25: frozen FOUR E24 original-source folds → six other real source groups.

Never fit a Head, tune tau or read original human validation truth in this
proposer. Original full pretrained ModernBERT+Reader inference MUST run again.
Unseen here means not in previous four sample passages; NOT new task family.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from math import exp,isfinite
from pathlib import Path
from time import process_time_ns
from zipfile import ZipFile

from e25_unseen_material import (ARCHIVE_SHA,MODERNBERT_SNAPSHOT_SHA,
                                 ORIGINAL_SOURCE_HEAD,write_once)

POLICY_SHA='dec01b016354733183d6feac374e6a333a22b08af8ef2d48196480064ff36a88'
SCHEMA='hepta.e25.frozen-original-human-heads-new-six-passages.v1'
ARMS=('conditioned','mean_pool_query_fused','no_evidence','no_query')
METHODS=('e16_scaled_brier_5','question_softworst_tau_001')


def source_json(path,max_size=2000000):
    data=Path(path).read_bytes()
    if not 0<len(data)<max_size:raise ValueError('source JSON missing/oversized')
    def pairs(entries):
        d={}
        for k,v in entries:
            if k in d:raise ValueError('duplicate untrusted JSON key')
            d[k]=v
        return d
    return json.loads(data,object_pairs_hook=pairs,
        parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite JSON')))


def frozen(path):
    if sha256(Path(path).read_bytes()).hexdigest()!=POLICY_SHA:
        raise ValueError('frozen original-sample policy bytes changed')
    d=source_json(path)
    if (set(d)!={'schema','authority','source_pr','source_commit',
          'model_archive_sha256','original_training_data',
          'initial_training_source_group_count_per_fold','original_optimization',
          'fixed_hypotheses','tau_posthoc_on_original_family',
          'parameter_count_per_fitted_head','head_count_per_policy',
          'novel_validation_groups_not_seen_during_original_fourfold_fit',
          'label_independent_new_test_selection','new_time_or_source_family',
          'new_pretrained_model_required','production_accepted','folds'}
        or d['schema']!='hepta.e25.frozen-fourfold-five-param-transfer.v1'
        or d['authority']!='DENY_ALL' or d['source_pr']!=2322
        or d['model_archive_sha256']!=ARCHIVE_SHA
        or d['fixed_hypotheses']!=list(METHODS)
        or d['head_count_per_policy']!=4
        or d['parameter_count_per_fitted_head']!=5
        or d['initial_training_source_group_count_per_fold']!=3
        or d['tau_posthoc_on_original_family'] is not True
        or d['new_pretrained_model_required'] is not True
        or d['new_time_or_source_family'] is not False
        or d['production_accepted'] is not False
        or type(d['folds']) is not list or len(d['folds'])!=4):
        raise ValueError('unsupported frozen research configuration')
    for i,fold in enumerate(d['folds']):
        if (type(fold) is not dict or set(fold)!={
                'fold','held_group','train_only_material_sha256','original_e24_local_receipt_sha256',
                'scale','weights'} or type(fold['fold']) is not int or fold['fold']!=i
            or type(fold['scale']) is not list or len(fold['scale'])!=4
            or type(fold['weights']) is not dict or set(fold['weights'])!=set(METHODS)):
            raise ValueError('incomplete signed-off historical learner geometry')
        if any(type(z) is not float or not isfinite(z) or not 1e-5<=z<=128 for z in fold['scale']):
            raise ValueError('unsupported training-only normalization')
        for name in METHODS:
            w=fold['weights'][name]
            if (type(w) is not list or len(w)!=5 or any(
                type(z) is not float or not isfinite(z) or abs(z)>128 for z in w)):
                raise ValueError('unstable/changed frozen weights')
    return d


def previous_model_from_zip(archive):
    path=Path(archive)
    if sha256(path.read_bytes()).hexdigest()!=ARCHIVE_SHA:
        raise ValueError('historic source ZIP byte identity mismatch')
    with ZipFile(path) as z:
        old=json.loads(z.read('multirc-run/predictions.json'))
    if (old.get('actual_train_encoder_calls')!=8 or old.get('steps')!=64
        or old.get('seed')!=7347 or old.get('model_snapshot_sha256')!=MODERNBERT_SNAPSHOT_SHA
        or set(old.get('training',{}))!=set(ARMS)):
        raise ValueError('historic original Reader fitting source changed')
    return old


def sigmoid(z):
    if type(z) not in (float,int) or not isfinite(z) or abs(z)>1000:
        raise ValueError('invalid live original Reader score')
    t=exp(-abs(z))
    return 1/(1+t) if z>=0 else t/(1+t)


def geometry(audit,source_meta,slate,owner_run,original_archive):
    old=previous_model_from_zip(original_archive)
    if (source_meta.get('new_candidate_count')!=audit.get('actual_candidate_count')
        or source_meta.get('new_question_count')!=12
        or source_meta.get('new_source_groups')!=[x['source_group'] for x in slate['rows']]
        or source_meta.get('original_archive_sha256')!=ARCHIVE_SHA
        or source_meta.get('original_source_head')!=ORIGINAL_SOURCE_HEAD
        or source_meta.get('selection_uses_labels_or_predictions') is not False
        or source_meta.get('future_time_or_independent_family') is not False
        or source_meta.get('production_accepted') is not False):
        raise ValueError('unregistered novel-panel source')
    if (audit.get('evaluation_labels_loaded') is not False
        or audit.get('previous_v1_training_unchanged') is not True
        or audit.get('native_candidates_not_cross_question_fabrications') is not True
        or audit.get('source_panel_id')!=slate.get('source_panel_id')
        or audit.get('model_snapshot_sha256')!=MODERNBERT_SNAPSHOT_SHA
        or audit.get('shared_evidence_encoder_calls')!=6
        or audit.get('actual_question_encoder_calls')!=audit.get('actual_candidate_count')
        or audit.get('actual_reader_calls')!=audit.get('actual_candidate_count')*4
        or audit.get('production_authorized') is not False):
        raise ValueError('physical six-passage model execution not established')
    if (owner_run.get('panel_id')!=slate.get('source_panel_id')
        or owner_run.get('actual_train_encoder_calls')!=8
        or owner_run.get('actual_eval_encoder_calls')!=6
        or owner_run.get('steps')!=64 or owner_run.get('seed')!=7347
        or owner_run.get('model_snapshot_sha256')!=MODERNBERT_SNAPSHOT_SHA):
        raise ValueError('original 64-step pretrained model was not newly executed')
    for arm in ARMS:
        if (owner_run['training'][arm]['weights_sha256']!=old['training'][arm]['weights_sha256']
            or audit['arm_parameter_counts'][arm]!=old['arm_parameter_counts'][arm]):
            raise ValueError('historical identical Reader weights not reproduced')
    listed=[{'task_id':c['task_id'],'source_group':p['source_group'],
            'question_slot':q['question_slot'],'candidate_id':c['candidate_id'],
            'original_v1_candidate':c['task_id']==q['original_task_id']}
        for p in slate['rows'] for q in p['questions'] for c in q['candidates']]
    if audit.get('rows')!=listed or not 24<=len(listed)<=96 or len(set(x['task_id'] for x in listed))!=len(listed):
        raise ValueError('missing/reordered authentic candidate inventory')
    qs=defaultdict(list)
    margins=[]
    for i,row in enumerate(listed):
        vector=[]
        for arm in ARMS:
            arm_rows=audit['predictions'][arm]
            if type(arm_rows) is not list or len(arm_rows)!=len(listed):
                raise ValueError('incomplete physical Reader prediction')
            x=arm_rows[i]
            if (x.get('task_id')!=row['task_id'] or x.get('source_group')!=row['source_group']
                or x.get('question_slot')!=row['question_slot'] or
                x.get('weights_sha256')!=old['training'][arm]['weights_sha256']):
                raise ValueError('original model output provenance changed')
            logits=x.get('logits')
            if type(logits) is not list or len(logits)!=2 or any(type(z) not in (float,int) or not isfinite(z) or abs(z)>128 for z in logits):
                raise ValueError('unsupported original model output')
            vector.append(logits[1]-logits[0])
        margins.append(tuple(vector))
        qs[(row['source_group'],row['question_slot'])].append(i)
    if len(qs)!=12 or any(not 2<=len(v)<=8 for v in qs.values()):
        raise ValueError('not twelve complete registered original questions')
    out=[]
    for i,row in enumerate(listed):
        m=margins[i];indices=qs[(row['source_group'],row['question_slot'])]
        averages=[sum(margins[k][j] for k in indices)/len(indices) for j in range(4)]
        centered=[m[j]-averages[j] for j in range(4)]
        x=(centered[0],centered[1],centered[2],centered[1]*centered[2])
        if any(not isfinite(z) or abs(z)>128 for z in x):
            raise ValueError('centered new-source signal exceeds original profile')
        out.append(dict(**row,centered=x,raw=m))
    return out,old


def propose(audit,source_meta,slate,owner_run,policy,original_archive):
    rows,old=geometry(audit,source_meta,slate,owner_run,original_archive)
    out=[]
    timing={m:0 for m in METHODS}
    for r in rows:
        pp={a:sigmoid(r['raw'][i]) for i,a in enumerate(ARMS)}
        for m in METHODS:
            tic=process_time_ns()
            four=[]
            for fold in policy['folds']:
                scale=fold['scale'];w=fold['weights'][m]
                x=(1.0,)+tuple(r['centered'][j]/scale[j] for j in range(4))
                if any(not isfinite(z) or abs(z)>128 for z in x):
                    raise ValueError('new source feature exceeds originally registered normalization region')
                four.append(sigmoid(sum(a*b for a,b in zip(w,x,strict=True))))
            pp[m]=sum(four)/4
            timing[m]+=max(1,process_time_ns()-tic)
        out.append({k:r[k] for k in ('task_id','source_group','question_slot','candidate_id')}|
                   {'probabilities':pp})
    return {'schema':SCHEMA,'authority':'DENY_ALL','production_accepted':False,
        'source_panel_id':slate['source_panel_id'],'slate_id':slate['slate_id'],
        'historic_original_pretrained_zip_sha256':ARCHIVE_SHA,
        'historical_reader_weights_reproduced':True,
        'policy_sha256':POLICY_SHA,'frozen_tau':0.01,
        'old_passages_reused_as_new_evaluation':False,
        'new_reader_train_anchor_slate_evidence_forwards':20,
        'original_checkpoint_probe_forwards_additional_and_not_in_reader_count':True,
        'new_original_candidate_reader_forward_calls':owner_run['actual_eval_encoder_calls']*4+audit['actual_reader_calls'],
        'human_validation_labels_read_before_seal':False,
        'new_validation_passages':6,'new_validation_questions':12,
        'new_validation_candidates':len(rows),'rows':out,
        'actual_new_frozen_fourfold_student_cpu_ns':timing,
        'four_trained_heads_per_policy':True,
        'new_time_or_data_family':False,
        'learning_or_model_selected':False,
        'complete_service_cost_measured':False}



def verify_original_two_seals(owner_path,owner_seal_path,audit_path,candidate_seal_path):
    """Verify BOTH original source-owner and native-slate byte identities.

    These are same-run self-seals, NOT independently signed external owners.
    New fingerprint checks are separate and mandatory in geometry().
    """
    owner=source_json(owner_path);seal=source_json(owner_seal_path)
    audit=source_json(audit_path);child=source_json(candidate_seal_path)
    if (seal.get('schema')!='hepta.multirc.unscored-model-seal.v1'
        or seal.get('labels_loaded_during_training') is not False
        or seal.get('production_authorized') is not False
        or child.get('schema')!='hepta.multirc.genuine-answer-slate-seal.v1'
        or child.get('labels_loaded') is not False
        or child.get('model_weights_uploaded') is not False
        or child.get('production_authorized') is not False
        or child.get('source_owner_seal')!=seal.get('seal_id')
        or owner.get('observation_id')!=seal.get('observation_id')
        or audit.get('observation_id')!=child.get('observation_id')
        or seal.get('files',{}).get('predictions.json')!=sha256(Path(owner_path).read_bytes()).hexdigest()
        or child.get('observation_sha256')!=sha256(Path(audit_path).read_bytes()).hexdigest()):
        raise ValueError('source/child original model exact bytes and original seal missing')
    for raw in (seal,child):
        frozen_body={k:v for k,v in raw.items() if k!='seal_id'}
        original=sha256(json.dumps(frozen_body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        if raw.get('seal_id')!=original:
            raise ValueError('source/child original model canonical JSON seal changed')
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('candidate-audit','candidate-seal','material-source','candidate-slate',
              'owner-run','owner-seal','frozen-policy','historic-original-archive','output'):
        p.add_argument('--'+k,required=True)
    a=p.parse_args()
    verify_original_two_seals(a.owner_run,a.owner_seal,a.candidate_audit,a.candidate_seal)
    result=propose(source_json(a.candidate_audit),source_json(a.material_source),
       source_json(a.candidate_slate),source_json(a.owner_run),frozen(a.frozen_policy),
       a.historic_original_archive)
    print(write_once(a.output,result),'DENY_ALL')

if __name__=='__main__':main()
