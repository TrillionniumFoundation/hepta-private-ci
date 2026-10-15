#!/usr/bin/env python3
"""Independent numeric rescue of authentic but overall-failed E1 Action artifact.

This does NOT prove full model provenance, a valid mmBERT embedding, future
NDU, or a three-model winner. No models loaded. Only pinned ZIP is accepted.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import math
from pathlib import Path
from zipfile import ZipFile, BadZipFile

SCHEMA='hepta.e1.partial-actual-model-numeric-audit.v1'
RUN=38594668819
ARTIFACT=11926728554
ZIP_SHA='c90c5174eb8c2949dc64637ab2676ea756464723c3474cb56a8eb4a092434955'
HEAD='1a22e114c1c8ea081da51d4e94ccb9ff9ce9aeff'
PANEL_SHA='2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4'
REVISION='835ad14087e140460703cf0fae09f97d469d65c2'
FILES=('panel.json','granite_97m_r2.json','granite_97m_r2.e2.json',
       'mmbert_small.json','mmbert_small.e2.json','embeddinggemma_2_text.failed.txt')

class Invalid(ValueError): pass

def sha(v):return hashlib.sha256(v).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')
def dup(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise Invalid('duplicate JSON object key')
        d[k]=v
    return d

def parse(raw):
    if not 0<len(raw)<=6*1024*1024:raise Invalid('invalid JSON length')
    try:return json.loads(raw,object_pairs_hook=dup,parse_constant=lambda _:(_ for _ in ()).throw(Invalid('nonfinite JSON')))
    except (TypeError,ValueError,UnicodeError) as e:raise Invalid('invalid archived JSON') from e

def _contents(blob,approved_zip):
    if not 0<len(blob)<=3*1024*1024 or sha(blob)!=approved_zip:
        raise Invalid('archival ZIP not SHA256-pinned to actual failed Action')
    try:
        with ZipFile(io.BytesIO(blob)) as z:
            infos=z.infolist();names=[i.filename for i in infos]
            if len(names)!=len(set(names)) or sum(i.file_size for i in infos)>25*1024*1024:
                raise Invalid('duplicate/oversized ZIP entries')
            found={}
            for i in infos:
                name=i.filename
                if not name or name.startswith('/') or '\\' in name or '..' in name.split('/'):
                    raise Invalid('unsafe ZIP entry')
                if name.endswith('/'):
                    continue
                basename=name.rsplit('/',1)[-1]
                if basename in found:
                    raise Invalid('duplicate archived evidence basename')
                found[basename]=z.read(i)
            if not set(FILES).issubset(found):
                raise Invalid('incomplete real Granite/E2 record or failed-arm quarantine')
            return found
    except (BadZipFile,KeyError) as e:raise Invalid('invalid archived action ZIP') from e

def scores(panel,report):
    cases=panel['cases'];lookup={c['case_id']:c for c in cases}
    expected={c['case_id'] for c in cases if c['split'] in ('calibration','test')}
    if len(cases)!=224 or len(lookup)!=224 or len(expected)!=96:
        raise Invalid('missing/duplicate 224 original public cases')
    if (report.get('schema')!='hepta.e1-english-public-pretrained-head.v1' or
        report.get('model')!='granite_97m_r2' or report.get('model_revision')!=REVISION or
        report.get('feature_width')!=384 or report.get('public_panel_sha256')!=sha(canonical(panel)) or
        report.get('authority')!='DENY_ALL' or report.get('production_promotion_permitted') is not False or
        report.get('english_only') is not True or report.get('public_dataset_is_chronological_future') is not False or
        report.get('actual_pretrained_local_weight_execution_claimed') is not True or
        report.get('model_origin_independently_authenticated') is not False):
        raise Invalid('Granite report does not match pinned physical public pilot')
    fitting=report['fitting']
    if (fitting.get('steps')!=40 or fitting.get('seed')!=20261014 or fitting.get('learning_rate')!=.15 or
        fitting.get('head_parameter_count')!=770 or fitting.get('training_test_labels_accessed') is not False):
        raise Invalid('unexpected Granite train-only Head program')
    if set(report.get('tokens_per_case',{}))!=set(lookup) or any(type(n) is not int or not 1<=n<=512 for n in report['tokens_per_case'].values()):
        raise Invalid('missing original tokenizer inventories or truncation')
    if set(report.get('features_q24_identity',{}))!=set(lookup):
        raise Invalid('missing original frozen features')
    resource=report.get('physical_observations')
    if not isinstance(resource,dict) or set(resource.get('encode_ms_by_case',{}))!=set(lookup):
        raise Invalid('not all model invocations have physical latency entries')
    controls=fitting.get('controls')
    if type(controls) is not dict or set(controls)!= {'frozen_head','learned_head'}:
        raise Invalid('missing matched Head controls')
    raw_predictions={};descriptive={}
    for name,record in controls.items():
        if (type(record) is not dict or type(record.get('head_sha256')) is not str or
            len(record['head_sha256'])!=64 or record.get('calibration_temperature') not in (.5,.75,1.,1.5,2.,3.,4.)):
            raise Invalid('incomplete source Head identity/temperature')
        rows=record.get('predictions')
        if type(rows) is not list or len(rows)!=96:raise Invalid('incomplete original Head predictions')
        observed={}
        for row in rows:
            cid=row.get('case_id');p=row.get('positive_probability')
            if (cid not in expected or cid in observed or row.get('joint_input_digest')!=lookup[cid]['joint_input_digest'] or
                row.get('split')!=lookup[cid]['split'] or type(p) not in (float,int) or
                not math.isfinite(p) or not 0<=p<=1):
                raise Invalid('swapped or nonfinite original label/probability')
            observed[cid]=float(p)
        if set(observed)!=expected:raise Invalid('incomplete paired original cases')
        raw_predictions[name]=observed
        descriptive[name]={}
        for split in ('calibration','test'):
            subset=[r for r in cases if r['split']==split]
            correct=sum(int((observed[r['case_id']]>=.5)==bool(r['label'])) for r in subset)
            brier=sum((observed[r['case_id']]-r['label'])**2 for r in subset)/len(subset)
            descriptive[name][split]={'n':len(subset),'correct':correct,'accuracy':correct/len(subset),'brier':brier}
    frozen=raw_predictions['frozen_head'];trained=raw_predictions['learned_head']
    discord=[0,0]
    for c in cases:
        if c['split']!='test':continue
        k=c['case_id'];yes=(trained[k]>=.5)==bool(c['label']);no=(frozen[k]>=.5)==bool(c['label'])
        if yes and not no:discord[0]+=1
        if no and not yes:discord[1]+=1
    n=sum(discord)
    pvalue=min(1.,2.*sum(math.comb(n,i) for i in range(min(discord)+1))/(2**n)) if n else 1.
    return descriptive,{'trained_only_correct':discord[0],'frozen_only_correct':discord[1],
                        'unadjusted_exact_mcnemar_p':pvalue},resource

def audit(archive,approved_zip=ZIP_SHA,e2_review=None):
    content=_contents(archive,approved_zip)
    if content['embeddinggemma_2_text.failed.txt'].strip()!=b'embeddinggemma_2_text failed source-based real CPU trial':
        raise Invalid('Gemma failed-arm declaration altered')
    panel=parse(content['panel.json'])
    if sha(canonical(panel))!=PANEL_SHA or panel.get('cross_sectional_not_future') is not True or panel.get('production_promotion')!='DENY_ALL':
        raise Invalid('different or relabeled public source panel')
    granite=parse(content['granite_97m_r2.json'])
    metrics,paired,cost=scores(panel,granite)
    if e2_review is None:
        from e2_residual_review import review as e2_review
    e2=parse(content['granite_97m_r2.e2.json'])
    e2out=e2_review(panel,granite,sha(content['granite_97m_r2.json']),e2)
    if e2out.get('authority')!='DENY_ALL' or e2out.get('production_promotion_permitted') is not False:
        raise Invalid('original E2 independent reviewer falsely promoted a Head')
    # The mmBERT archive demonstrably ran with the missing pretrained token
    # table. It must NOT contribute any accuracy, score or contender ranking.
    invalid=parse(content['mmbert_small.json'])
    if invalid.get('model')!='mmbert_small' or invalid.get('production_promotion_permitted') is not False:
        raise Invalid('archived invalid arm identity altered')
    return {'schema':SCHEMA,'authority':'DENY_ALL','production_promotion_permitted':False,
            'run_id':RUN,'artifact_id':ARTIFACT,'original_head_sha':HEAD,'original_zip_sha256':ZIP_SHA,
            'pinned_source_panel_sha256':PANEL_SHA,'holdout_cases':64,
            'granite_original_e1_report_sha256':sha(content['granite_97m_r2.json']),
            'granite_original_e2_report_sha256':sha(content['granite_97m_r2.e2.json']),
            'granite_actual_model_executed_in_archived_job_claim':True,
            'granite_independently_signed_weight_and_forward_origin':False,
            'granite_recomputed_accuracy_brier':metrics,'granite_trained_vs_frozen_test':paired,
            'granite_e2_independent_numeric_review':e2out,
            'granite_cost_report_claim_ms':{'load':cost.get('load_ms'),
                'all_encode':sum(cost.get('encode_ms_by_case',{}).values()),
                'sgd':granite['fitting']['train_time_ms']},
            'mmbert_arm':{'status':'QUARANTINED_BAD_PRETRAINED_TIE',
                'report_sha256':sha(content['mmbert_small.json']),
                'source_loading_warning':'embeddings.tok_embeddings.weight MISSING; random init possible',
                'quality_scores_admitted':False},
            'embeddinggemma_2_text_arm':{'status':'FAILED_MISSING_TORCHVISION',
                'report_sha256':None,'quality_scores_admitted':False},
            'three_model_pairwise_scientific_comparison_complete':False,
            'new_source_chinese_code_or_chronological_future':False,
            'production_no_change_or_real_reader_four_conditions':False,
            'independent_future_ndu_or_full_cost_attested':False,
            'stem_winner_selected':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():raise FileExistsError('create-only physical archive review')
    result=audit(args.archive.read_bytes())
    with args.output.open('x',encoding='utf8') as f:json.dump(result,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
