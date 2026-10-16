"""V14 physically executable two-stage public-only IDF graph qualification.

This study makes no Encoder forward or learned-Head optimization: it tests whether
low-cost entity identification and directed chaining require a neural Cell on
synthetic ownership/storage grammar. The transductive arm uses UNLABELED held
source texts and CANNOT count as prospective or inductive learning.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import resource
import time
from zipfile import ZipFile

from v14_candidate_graph import (build_df, build_public_pairs, digest,
                                  predict_pair, transform)

PUBLIC_ZIP_SHA256='efee1e07fdb26cb9f3222a86244ad8a41062b0c647a3be762d76c688826995af'
PUBLIC_FILE_SHA256='1b027fd2708068da25674415789906a575a00383abe5712255a432e8679e913c'
SOURCE_SEAL_SHA256='4de11a06a4d481696fe6efc3a6a1f8085806aeffc7f20a3d14fb07d4dc30d608'
ARMS=('train_idf', 'unlabeled_transductive_idf',
      'unlabeled_transductive_reverse', 'first_candidate')
VARIANTS=('original', 'fact_permutation', 'meaning_preserving_paraphrase')


def load_public(zip_path):
    archive=Path(zip_path)
    if archive.is_dir():
        # The GitHub action downloads/unzips exactly the original two members;
        # verify both ORIGINAL MEMBER bytes, not a new repackaged ZIP hash.
        public_bytes=(archive/'public.json').read_bytes()
        seal_bytes=(archive/'source-seal.json').read_bytes()
    else:
        if sha256(archive.read_bytes()).hexdigest()!=PUBLIC_ZIP_SHA256:
            raise ValueError('original registered public source ZIP SHA mismatch')
        with ZipFile(archive) as source:
            if source.testzip() is not None or set(source.namelist())!={'public.json','source-seal.json'}:
                raise ValueError('source archive CRC or inventory changed')
            public_bytes=source.read('public.json')
            seal_bytes=source.read('source-seal.json')
    if (sha256(public_bytes).hexdigest()!=PUBLIC_FILE_SHA256
            or sha256(seal_bytes).hexdigest()!=SOURCE_SEAL_SHA256):
        raise ValueError('original public members are not bit-for-bit preserved')
    rows=json.loads(public_bytes)
    owner=json.loads(seal_bytes)
    if (len(rows)!=1248 or len({x['case_id'] for x in rows})!=1248
            or owner.get('public_sha256')!=digest(rows)
            or owner.get('source_groups')!=312
            or owner.get('held_rows')!=960 or owner.get('train_rows')!=288
            or owner.get('authority')!='DENY_ALL'):
        raise ValueError('original content-addressed public source incomplete')
    if any(set(x)!={'case_id','source_group','facts','question','candidate'} for x in rows):
        raise ValueError('public source contains answer or metadata oracle')
    return rows,owner


def write_new(path,data):
    with Path(path).open('x',encoding='utf8') as f:
        json.dump(data,f,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
        f.write('\n')


def prepare(public_path,output):
    rows,owner=load_public(public_path)
    train=build_df(rows,scope='train_only')
    trans=build_df(rows,scope='unlabeled_transductive')
    if train['independent_groups']!=72 or trans['independent_groups']!=312:
        raise ValueError('source role census invalid')
    returnvalue=dict(schema='hepta.v14.all-evidence-slot-protocol.v1',
        original_public_zip_sha256=PUBLIC_ZIP_SHA256,
        source_sha256=digest(rows),source_owner_sha256=digest(owner),
        df={'train_idf':train,'unlabeled_transductive_idf':trans},
        arms=list(ARMS),variants=list(VARIANTS),
        original_predictions_use_no_registered_relation_templates=True,
        synthetic_paraphrase_generation_uses_six_registered_templates=True,
        relation_candidate_pairs_provided=False,
        train_labels_loaded=False,held_truth_loaded=False,
        transductive_held_unlabeled_source_access=True,
        real_granite_forward_count=0,model_selected=False,
        production_accepted=False,authority='DENY_ALL')
    returnvalue['protocol_sha256']=digest({k:v for k,v in returnvalue.items() if k!='protocol_sha256'})
    write_new(output,returnvalue)
    return returnvalue


def check_plan(plan,rows,owner):
    if (plan.get('schema')!='hepta.v14.all-evidence-slot-protocol.v1'
            or plan.get('source_sha256')!=digest(rows)
            or plan.get('source_owner_sha256')!=digest(owner)
            or plan.get('original_public_zip_sha256')!=PUBLIC_ZIP_SHA256
            or plan.get('arms')!=list(ARMS) or plan.get('variants')!=list(VARIANTS)
            or plan.get('protocol_sha256')!=digest({k:v for k,v in plan.items() if k!='protocol_sha256'})
            or plan.get('held_truth_loaded') is not False
            or plan.get('train_labels_loaded') is not False
            or plan.get('authority')!='DENY_ALL'
            or plan.get('production_accepted') is not False):
        raise ValueError('immutable public-only study plan mismatch')
    actual_train=build_df(rows,scope='train_only')
    actual_trans=build_df(rows,scope='unlabeled_transductive')
    if plan.get('df')!={'train_idf':actual_train,'unlabeled_transductive_idf':actual_trans}:
        raise ValueError('training-only and unlabeled-held DF source proof mismatch')


def predict(public_path,plan_path,output):
    rows,owner=load_public(public_path)
    plan=json.loads(Path(plan_path).read_text())
    check_plan(plan,rows,owner)
    cpu=time.process_time_ns()
    predictions={}; traces={}; accounts={}
    # No labels or model weights can reach this routine.
    for variant in VARIANTS:
        changed=[transform(row,variant) for row in rows]
        cases=[x for x in changed if not x['case_id'].startswith('train/')]
        pairs=build_public_pairs(cases)
        if len(pairs)!=480:
            raise ValueError('exact 480 held public-world questions required')
        predictions[variant]={};traces[variant]={}
        for arm in ARMS:
            start=time.process_time_ns()
            results={};proofs={}
            for a,b in pairs:
                if arm=='first_candidate':
                    best=min((a,b),key=lambda x:x['candidate'])['case_id']
                    updates={a['case_id']:int(a['case_id']==best),
                             b['case_id']:int(b['case_id']==best)}
                    these={}
                else:
                    dfr=plan['df']['train_idf' if arm=='train_idf' else 'unlabeled_transductive_idf']
                    updates,these=predict_pair(a,b,dfr,reverse=arm.endswith('_reverse'))
                results.update(updates);proofs.update(these)
            if len(results)!=960 or not set(results).issuperset(proofs):
                raise ValueError('every original held candidate must be scored exactly once')
            predictions[variant][arm]=results
            traces[variant][arm]=proofs
            accounts[f'{variant}/{arm}']=dict(cpu_ns=time.process_time_ns()-start,
               answered=sum(x is not None for x in results.values()),
               abstained=sum(x is None for x in results.values()),
               physical_graph_candidates_examined=len(cases) if arm!='first_candidate' else 0)
    seal=dict(schema='hepta.v14.no-oracle-raw-public-predictions.v1',
       source_sha256=digest(rows),source_owner_sha256=digest(owner),
       preregistered_plan_sha256=plan['protocol_sha256'],
       predicted_variants=list(VARIANTS),predicted_arms=list(ARMS),
       predictions=predictions,discovered_slots_and_paths=traces,
       per_arm_costs=accounts,run_cpu_ns=time.process_time_ns()-cpu,
       process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
       independent_held_sources=240,held_rows_per_arm=960,
       original_held_answer_labels_loaded=False,
       trained_Reader_weights_accessed=False,
       pretrained_forward_count=0,sgd_optimizer_updates=0,
       transductive_arm_uses_unlabeled_held_source=True,
       original_predictions_use_no_registered_relation_templates=True,
       synthetic_paraphrases_are_template_generated=True,
       relation_candidate_lists_provided=False,
       model_selection_permitted=False,production_accepted=False,authority='DENY_ALL')
    seal['prediction_sha256']=digest(predictions)
    write_new(output,seal)
    return seal


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('prepare','predict'))
    p.add_argument('--public',required=True)
    p.add_argument('--plan')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    if a.phase=='prepare':
        r=prepare(a.public,a.output)
        print(json.dumps(dict(plan_sha256=r['protocol_sha256'],source_groups=[72,312])))
    else:
        if not a.plan:
            p.error('predict requires sealed plan')
        r=predict(a.public,a.plan,a.output)
        print(json.dumps(dict(prediction_sha256=r['prediction_sha256'],variants=len(VARIANTS),arms=len(ARMS),cpu_ns=r['run_cpu_ns'])))

if __name__=='__main__':main()
