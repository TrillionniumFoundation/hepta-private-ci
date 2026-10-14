#!/usr/bin/env python3
"""Read-only, independently recomputed public AG News val2 ZIP pairing.

Numeric and checkpoint integrity only. Does NOT authenticate HF weights, task
labels/signatures, CPU forward counts, NDU, total costs or future-window utility.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import stat
import zipfile

SCHEMA='hepta.stem-e1e2-public-receipt-numeric-audit.v1'
ARMS=('gemma2_frozen_head','gemma2_trained_head','gemma2_trained_head_scaled_1024','laya421_frozen')
MAX_ZIP=16*1024*1024
MAX_FILE=4*1024*1024
MAX_UNCOMPRESSED=32*1024*1024
class Invalid(ValueError):pass

def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=False).encode()

def sha_bytes(b):return hashlib.sha256(b).hexdigest()
def verify_sha(s):
    if type(s) is not str or len(s)!=64 or any(c not in '0123456789abcdef' for c in s):
        raise Invalid('invalid SHA256 pin')
    return s

def strict_pairs(pairs):
    obj={}
    for k,v in pairs:
        if k in obj:raise Invalid('duplicate JSON field: '+k)
        obj[k]=v
    return obj

def finite(v):
    if type(v) not in (float,int) or not math.isfinite(v):raise Invalid('nonfinite report number')
    return float(v)

def strict_json(raw):
    try:return json.loads(raw,object_pairs_hook=strict_pairs,
         parse_constant=lambda v: (_ for _ in ()).throw(Invalid('nonfinite JSON literal')))
    except (ValueError,UnicodeError) as e:raise Invalid('invalid JSON record: '+str(e)) from e

class CheckedZip:
    def __init__(self,path,pin):
        blob=Path(path).read_bytes()
        if not 0<len(blob)<=MAX_ZIP:raise Invalid('oversized/empty artifact ZIP')
        self.sha256=sha_bytes(blob)
        if self.sha256!=verify_sha(pin):raise Invalid('expected artifact ZIP hash mismatch')
        try:self.archive=zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:raise Invalid('invalid artifact ZIP') from exc
        infos=self.archive.infolist()
        if not infos or len(infos)>100 or len({x.filename for x in infos})!=len(infos):raise Invalid('duplicate/oversized ZIP manifest')
        if sum(i.file_size for i in infos)>MAX_UNCOMPRESSED:raise Invalid('ZIP bomb exceeds size allowance')
        self.names=set()
        for i in infos:
            path_parts=i.filename.split('/')
            mode=(i.external_attr>>16)
            if i.flag_bits&1 or i.file_size>MAX_FILE or i.filename.startswith('/') or '\\' in i.filename or '..' in path_parts or stat.S_ISLNK(mode):
                raise Invalid('unsafe ZIP entry')
            self.names.add(i.filename)
    def raw(self,name):
        if name not in self.names:raise Invalid('missing '+name)
        return self.archive.read(name)
    def json(self,name):return strict_json(self.raw(name))
    def close(self):self.archive.close()

def _case_index(panel):
    rows=panel.get('cases')
    if not isinstance(rows,list) or len(rows)!=128 or panel.get('case_count')!=128:raise Invalid('expected preregistered 128-case panel')
    result={};groups=set()
    for c in rows:
        if type(c) is not dict:raise Invalid('invalid case')
        ident=c.get('case_id')
        if not isinstance(ident,str) or not ident or ident in result:raise Invalid('duplicate/missing source case')
        if c.get('split')!='new_holdout' or type(c.get('label')) is not int or c['label'] not in (0,1):raise Invalid('invalid panel split/label')
        for k in ('joint_input_digest','source_digest'):
            verify_sha(c.get(k))
        if c.get('group_id') in groups or c.get('group_id')!=c['source_digest']:raise Invalid('nonindependent source group')
        groups.add(c['group_id']);result[ident]=c
    return result

def _arm_rows(arms,cases):
    indexed={}; metrics={}
    for a in arms:
        if a.get('arm_id') in indexed:raise Invalid('duplicate prediction arm')
        name=a.get('arm_id')
        if name not in ARMS or a.get('production_promotion')!='DENY_ALL':raise Invalid('invalid nonauthorizing arm')
        rows=a.get('rows')
        if type(rows) is not list or len(rows)!=len(cases):raise Invalid('missing prediction rows')
        by_id={};count=0;sq=0.;bin_cal=[[] for _ in range(8)];serving=0
        for r in rows:
            ident=r.get('case_id')
            if ident in by_id or ident not in cases:raise Invalid('duplicate/swapped prediction ID')
            c=cases[ident]
            if r.get('source_digest')!=c['source_digest'] or r.get('joint_input_digest')!=c['joint_input_digest']:
                raise Invalid('tampered source or joint prompt digest')
            if r.get('split')!='new_holdout':raise Invalid('different evaluation split')
            p=finite(r.get('prob_sports'))
            if not 0<=p<=1:raise Invalid('invalid probability')
            duration=finite(r.get('measured_serving_micros'))
            if duration<0:raise Invalid('negative serving cost')
            serving+=duration
            y=c['label'];correct=int((p>=.5)==bool(y));count+=correct;sq+=(p-y)**2
            confidence=max(p,1-p)
            bin_cal[min(7,int(8*confidence))].append((confidence,correct))
            by_id[ident]=r
        ece=sum(len(b)/len(cases)*abs(sum(x for x,y in b)/len(b)-sum(y for x,y in b)/len(b)) for b in bin_cal if b)
        indexed[name]=by_id
        metrics[name]={'cases':len(cases),'accuracy':count/len(cases),'brier':sq/len(cases),
                       'descriptive_ece_8bin':ece,'reported_serving_micros':serving}
    return indexed,metrics

def _check_metric_report(metrics,published,fields):
    if type(published) is not dict:raise Invalid('missing published numeric report')
    for arm,got in metrics.items():
        r=published.get(arm)
        if type(r) is not dict:raise Invalid('published arm missing')
        for out_name,report_name in fields.items():
            if report_name not in r or not math.isclose(float(r[report_name]),float(got[out_name]),rel_tol=0,abs_tol=1e-9):
                raise Invalid('published '+arm+' '+out_name+' mismatch')

def audit(paired_path,paired_sha,sealed_path,sealed_sha):
    a=CheckedZip(paired_path,paired_sha)
    try:
        b=CheckedZip(sealed_path,sealed_sha)
        try:
            panel=a.json('stem-agnews-new-source-panel.json')
            if panel!=b.json('stem-sealed-val2-panel.json'):raise Invalid('source panel changed between executions')
            cases=_case_index(panel)
            paired_gemma=a.json('stem-gemma-fresh-arms.json')
            paired_laya=a.json('stem-laya-fresh-arm.json')
            if not isinstance(paired_gemma,list) or len(paired_gemma)!=3:raise Invalid('incomplete Gemma arms')
            pairarms=paired_gemma+[paired_laya]
            obs,metrics=_arm_rows(pairarms,cases)
            if set(obs)!=set(ARMS):raise Invalid('missing arm')
            seal=b.json('stem-sealed-val2-replay.json')
            if seal.get('production_promotion')!='DENY_ALL' or seal.get('three_chronological_future_windows') is not False or seal.get('head_optimizer_steps_during_val2_evaluation')!=0:
                raise Invalid('invalid sealed replay evidence')
            saved=seal.get('arms')
            if type(saved) is not dict or set(saved)!=set(ARMS[:3]):raise Invalid('sealed Gemma coverage changed')
            for name in ARMS[:3]:
                rows=saved[name].get('rows')
                if type(rows) is not list or len(rows)!=128:raise Invalid('missing saved predictions')
                seq={r['case_id']:r for r in rows}
                if len(seq)!=128 or set(seq)!=set(cases):raise Invalid('duplicated sealed case')
                for ident,entry in seq.items():
                    original=obs[name][ident]
                    for key in ('prob_sports','source_digest','joint_input_digest'):
                        if entry.get(key)!=original[key]:raise Invalid('paired/sealed numeric replay drift')
            raw_bundle=a.raw('stem-cell-immutable-bundle.json')
            if raw_bundle!=b.raw('stem-cell-immutable-bundle.json'):raise Invalid('checkpoint bundle mismatch')
            receipt=a.json('stem-cell-immutable-receipt.json')
            if receipt!=b.json('stem-cell-immutable-receipt.json'):raise Invalid('reloaded receipt mismatch')
            bundle=strict_json(raw_bundle)
            if bundle.get('payload_sha256')!=sha_bytes(canonical(bundle.get('payload'))) or receipt.get('snapshot_payload_sha256')!=bundle['payload_sha256'] or receipt.get('snapshot_file_sha256')!=sha_bytes(raw_bundle):
                raise Invalid('checkpoint digest mismatch')
            if receipt.get('historical_20261014_head_byte_identity_claimed') is not False:
                raise Invalid('unproven historical Head byte identity')
            if receipt.get('trained_weights_exact_float64_reloaded') is not True or receipt.get('frozen_weights_exact_float64_reloaded') is not True or not (0<receipt.get('trainable_parameters',0)<=2048) or receipt.get('training_steps',0)<1:
                raise Invalid('small Head checkpoint not read back')
            if seal.get('snapshot_file_sha256')!=receipt['snapshot_file_sha256'] or seal.get('snapshot_payload_sha256')!=receipt['snapshot_payload_sha256']:
                raise Invalid('sealed snapshot drift')
            exploration=a.json('stem-head-exploratory-calibration.json')
            if exploration.get('selected_logit_multiplier')!=1024 or exploration.get('test_distribution_already_reviewed_by_researcher') is not True:
                raise Invalid('missing exploratory calibration selection disclosure')
            reported=a.json('stem-new-source-independent-review.json')
            sealed_report=b.json('stem-sealed-val2-independent-review.json')
            _check_metric_report(metrics,reported.get('metrics'),{'accuracy':'accuracy','brier':'brier','descriptive_ece_8bin':'descriptive_ece_8bin','reported_serving_micros':'allocated_serving_time_micros'})
            _check_metric_report({k:v for k,v in metrics.items() if k in ARMS[:3]},sealed_report.get('metrics'),{'accuracy':'accuracy','brier':'brier','descriptive_ece_8bin':'descriptive_ece_8_equal_width'})
            for key in ('new_window_is_chronologically_future','equal_total_lifecycle_cost_proven','model_forward_origin_independently_authenticated'):
                if reported.get(key) is not False:raise Invalid('overclaimed public replication')
            discordant={'both_correct':0,'only_laya_correct':0,'only_gemma_correct':0,'both_wrong':0}
            for ident,c in cases.items():
                laya=int((obs['laya421_frozen'][ident]['prob_sports']>=.5)==bool(c['label']))
                gemma=int((obs['gemma2_trained_head'][ident]['prob_sports']>=.5)==bool(c['label']))
                label=('both_correct' if laya and gemma else 'only_laya_correct' if laya
                       else 'only_gemma_correct' if gemma else 'both_wrong')
                discordant[label]+=1
            n=discordant['only_laya_correct']+discordant['only_gemma_correct']
            k=min(discordant['only_laya_correct'],discordant['only_gemma_correct'])
            descriptive_p=(min(1.,2*sum(math.comb(n,i) for i in range(k+1))/2**n) if n else 1.)
            return {'schema':SCHEMA,'source_artifact_ids':[11886761368,11886807698],
                    'laya_vs_gemma_paired_counts':discordant,
                    'laya_vs_gemma_mcnemar_exact_two_sided_unadjusted_p':descriptive_p,
                    'scaled_logits_selected_in_prior_exploratory_work':True,
                    'paired_archive_sha256':a.sha256,'sealed_archive_sha256':b.sha256,
                    'checkpoint_bundle_sha256':receipt['snapshot_file_sha256'],
                    'reloaded_head_parameter_count':receipt['trainable_parameters'],
                    'reloaded_head_training_steps':receipt['training_steps'],
                    'source_disjoint_within_val2_cases':True,'paired_val2_case_count':len(cases),
                    'paired_prediction_replay_exact':True,'metrics':metrics,
                    'learning_gain_accuracy_vs_frozen':metrics['gemma2_trained_head']['accuracy']-metrics['gemma2_frozen_head']['accuracy'],
                    'gemma_minus_laya_accuracy':metrics['gemma2_trained_head']['accuracy']-metrics['laya421_frozen']['accuracy'],
                    'gemma_scaled_minus_laya_brier':metrics['gemma2_trained_head_scaled_1024']['brier']-metrics['laya421_frozen']['brier'],
                    'same_dataset_family':True,'chronological_future_windows_confirmed':False,
                    'foundation_pretraining_overlap_excluded':False,'independent_origin_signatures_verified':False,
                    'independent_physical_transformer_forward_count_verified':False,
                    'equal_total_lifecycle_cost_verified':False,'reader_adequacy_verified':False,
                    'future_ndu_utility_verified':False,'production_promotion_permitted':False,'authority':'DENY_ALL'}
        finally:b.close()
    finally:a.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--paired-zip',type=Path,required=True)
    p.add_argument('--paired-sha256',required=True)
    p.add_argument('--sealed-zip',type=Path,required=True)
    p.add_argument('--sealed-sha256',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    result=audit(a.paired_zip,a.paired_sha256,a.sealed_zip,a.sealed_sha256)
    data=(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    with a.output.open('xb') as file:file.write(data)
if __name__=='__main__':main()
