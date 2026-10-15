"""Read-only independent original V11 source-first weak publisher evidence recount.

No producer model/prediction code imported and no training. Four original source
families are correlated; paired question deltas are descriptive, not inferential.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path

ROOTS=('conv-47','conv-48','conv-49','conv-50')
EXPECTED={'conv-47':190,'conv-48':239,'conv-49':196,'conv-50':204}
SOURCE_SHA='1cb2d1d7194137cdea48ef8a13e8002c6612a9c98a1ffa71e28e7263c61bf84c'
V9_PREDICTIONS='df05ec7906d58834cf7856a0dce4dc77f6b639c0a7c910c88d49cb191f1cd01c'
LOCOMO_SHA='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'
ARMS=['bm25_full','dense_full']+[f'seed{s}/{kind}' for s in (41,47,53) for kind in ('residual','safe_two')]


def sha(b):return sha256(b).hexdigest()


def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()+b'\n'


def compare(rankings, supports, owners):
    """Count exact paired source gains/losses on a fixed complete case inventory."""
    if not isinstance(rankings,dict) or set(rankings)!=set(supports) or set(rankings)!=set(owners):
        raise ValueError('case inventory missing or shifted')
    totals={a:0 for a in ARMS}
    families={a:{fam:{'n':0,'hit':0,'gained_vs_bm25':0,'lost_vs_bm25':0,'unknown':0}
                 for fam in ROOTS} for a in ARMS}
    for qid, row in rankings.items():
        if not isinstance(row,dict) or set(row)!=set(ARMS):raise ValueError('arm inventory changed')
        fam=owners[qid]
        if fam not in ROOTS:raise ValueError('unknown family')
        truth=supports[qid]
        bmhit=truth is not None and bool(set(row['bm25_full'])&truth)
        for arm in ARMS:
            delivered=row[arm]
            if not isinstance(delivered,list) or len(delivered)!=3 or len(set(delivered))!=3:
                raise ValueError('delivered source is missing or duplicated')
            f=families[arm][fam]
            f['n']+=1
            if truth is None:
                f['unknown']+=1
                continue
            hit=bool(set(delivered)&truth)
            totals[arm]+=int(hit)
            f['hit']+=int(hit)
            f['gained_vs_bm25']+=int(hit and not bmhit)
            f['lost_vs_bm25']+=int(bmhit and not hit)
    if {a:{fam:d['n'] for fam,d in roots.items()} for a,roots in families.items()} != {
        arm:EXPECTED for arm in ARMS}:
        raise ValueError('family denominator mismatch')
    if totals['bm25_full']!=372 or totals['dense_full']!=223:
        raise ValueError('unchanged original physical baseline does not match')
    return totals,families


def recount(v9_root,original_root,study_root,output):
    for path in (v9_root/'source-only.json',original_root/'locomo.json',
                 study_root/'plan.json',study_root/'predictions.json',study_root/'physical.json',study_root/'score.json'):
        if not path.is_file() or path.is_symlink():raise ValueError('unsafe or missing original research evidence')
    if sha((v9_root/'source-only.json').read_bytes())!=SOURCE_SHA or sha((original_root/'locomo.json').read_bytes())!=LOCOMO_SHA:
        raise ValueError('source or publisher archive mismatch')
    v9=json.loads((v9_root/'source-only.json').read_bytes())
    original=json.loads((original_root/'locomo.json').read_bytes())
    plan=json.loads((study_root/'plan.json').read_bytes())
    predicted=json.loads((study_root/'predictions.json').read_bytes())
    physical=json.loads((study_root/'physical.json').read_bytes())
    scored=json.loads((study_root/'score.json').read_bytes())
    if (set(v9.get('families',{}))!=set(['conv-26','conv-30','conv-41','conv-42','conv-43','conv-44',*ROOTS])
        or predicted.get('original_v9_predictions_sha256')!=V9_PREDICTIONS
        or plan.get('original_train_only_labels') is not True
        or plan.get('heldout_labels_read') is not False
        or predicted.get('labels_read_before_seal') is not False
        or predicted.get('plan_sha256')!=sha(canonical(plan))
        or physical.get('prediction_sha256')!=sha(canonical(predicted))
        or scored.get('prediction_sha256')!=sha(canonical(predicted))
        or scored.get('physical_receipt_sha256')!=sha(canonical(physical))
        or physical.get('new_encoder_batch_forwards')!=0
        or any(x.get('production_authorized') is not False for x in (plan,predicted,physical,scored))):
        raise ValueError('invalid original research/authority lineage')
    truth={}
    seen=set()
    for sample in original:
        fam=sample['sample_id']
        if fam not in ROOTS:continue
        seen.add(fam)
        valid={x['id'] for x in v9['families'][fam]['passages']}
        qlist=v9['families'][fam]['questions']
        if len(qlist)!=EXPECTED[fam] or len(sample['qa'])!=len(qlist):raise ValueError('question roster shifted')
        for i,q in enumerate(sample['qa']):
            qid=f'{fam}/q{i}'
            if qlist[i]['id']!=qid or qlist[i]['text']!=q['question']:
                raise ValueError('source question changed')
            refs=q.get('evidence')
            truth[qid]=(set(refs) if isinstance(refs,list) and refs and
                         all(isinstance(e,str) and e in valid for e in refs) else None)
    if seen!=set(ROOTS):raise ValueError('missing original source roots')
    owners={q['id']:fam for fam in ROOTS for q in v9['families'][fam]['questions']}
    for qid,row in predicted['predictions'].items():
        fam=owners.get(qid)
        if fam is None:raise ValueError('unknown question')
        ids={x['id'] for x in v9['families'][fam]['passages']}
        for arm,delivered in row.items():
            if not set(delivered)<=ids:raise ValueError('invented source in original rank')
            if arm.endswith('safe_two') and delivered[:2]!=row['bm25_full'][:2]:
                raise ValueError('safe two-slot contract violated')
    totals,families=compare(predicted['predictions'],truth,owners)
    if totals!=scored['per_arm_weak_hit3']:
        raise ValueError('independent recomputation disagrees with producer score')
    for a in ARMS:
        if {f:d['hit'] for f,d in families[a].items()} != {
            f:scored['family_counts'][a][f]['hits'] for f in ROOTS}:
            raise ValueError('independent original family disagreement')
    result={'schema':'hepta.stem.v11.original-independent-paired-recount.shadow.v1',
            'original_v9_predictions_sha256':V9_PREDICTIONS,
            'plan_sha256':sha(canonical(plan)),
            'prediction_sha256':sha(canonical(predicted)),
            'original_heldout_questions':len(truth),'independent_family_roots':4,
            'weak_hit3_counts':totals,'paired_family_counts':families,
            'semantic_answer_success':None,'paired_confidence_or_significance_authorized':False,
            'source_fresh_future_windows':0,'end_to_end_cost_matched':False,
            'v6_retention_gate_closed':False,'selected_stem':False,'production_authorized':False}
    with output.open('x') as f:f.write(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n')
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--v9-root',type=Path,required=True)
    ap.add_argument('--original-root',type=Path,required=True)
    ap.add_argument('--study-root',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();r=recount(args.v9_root,args.original_root,args.study_root,args.output)
    print(json.dumps({'total':r['original_heldout_questions'],'results':r['weak_hit3_counts'],'admission':False}))
if __name__=='__main__':main()
