"""Train-only policy selection on archived REAL pretrained model predictions.

No pretrained model is executed here. It performs a counterfactual routing replay
on original, completed Granite97/mmBERT source-bound probabilities and times.
Never read or pass heldout owner labels to fit()/main().
"""
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path

SCHEMA='hepta.real-archive.confidence-cascade-observation.v1'
MATERIAL='hepta.real-archive.stem-cascade-input.v1'
BUDGETS=(0,10,25,50,100)
THRESHOLDS=(0.,.005,.01,.025,.05,.1,.2,.3,.4,.5)
SALT='hepta-20261015-mmbert-random-matched-v1'
FIXED={'fixed_margin_020':.2,'fixed_margin_040':.4}


def canon(obj):return json.dumps(obj,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf8')
def digest(obj):return hashlib.sha256(canon(obj)).hexdigest()
def unique(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ValueError('duplicate JSON key')
        d[k]=v
    return d

def read(path):
    p=Path(path)
    if not p.is_file() or not 10<p.stat().st_size<400000:raise ValueError('bounded regular JSON file required')
    return json.loads(p.read_bytes(),object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))

def validate(c,e):
    for doc,part,labels in ((c,'calibration',True),(e,'evaluation',False)):
        if (not isinstance(doc,dict) or doc.get('schema')!=MATERIAL or doc.get('partition')!=part
            or doc.get('material_id')!=digest({k:v for k,v in doc.items() if k!='material_id'})
            or doc.get('source_panel_sha256')!='8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a'
            or doc.get('original_model_prediction_sha256')!={'granite97':'6098b3e5141694fbf841f092631ef7f00abee606eca12a6c82d6249211ee4e57','mmbert_small':'d5382f28e60627c0b4e35446b7bef84e9dc5ffb00cd76e4c1ab1b2a99f1cb2ac'}
            or doc.get('archive_original_sha256')!='e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d'
            or doc.get('archive_physical_sha256')!='d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa'
            or doc.get('model_forward_newly_executed') is not False
            or doc.get('true_future_window') is not False
            or doc.get('external_source_signer_verified') is not False
            or doc.get('production_authorized') is not False or doc.get('authority')!='DENY_ALL'
            or not isinstance(doc.get('rows'),list) or len(doc['rows'])!=64):
            raise ValueError('independently sourced retrospective research material required')
        for row in doc['rows']:
            expected={'case_id','source_group','joint_input_digest','granite_probability','mmbert_probability',
                      'granite_encoder_ns','mmbert_encoder_ns','granite_head_ns','mmbert_head_ns'} | ({'label'} if labels else set())
            if not isinstance(row,dict) or set(row)!=expected:raise ValueError('wrong row provenance or hidden label leaked to policy')
            for field in ('case_id','source_group','joint_input_digest'):
                if not isinstance(row[field],str) or not row[field]:raise ValueError('incomplete case identity')
            for field in ('granite_probability','mmbert_probability'):
                if type(row[field]) not in (int,float) or not math.isfinite(row[field]) or not 0<row[field]<1:raise ValueError('invalid model probability')
            for field in ('granite_encoder_ns','mmbert_encoder_ns','granite_head_ns','mmbert_head_ns'):
                if type(row[field]) is not int or row[field]<=0:raise ValueError('missing real forward cost')
            if labels and (type(row['label']) is not int or row['label'] not in (0,1)):raise ValueError('missing honest training label')
        if [x['case_id'] for x in doc['rows']]!=sorted(x['case_id'] for x in doc['rows']):raise ValueError('unstable cohort ordering')
        if len({x['source_group'] for x in doc['rows']})!=64 or len({x['case_id'] for x in doc['rows']})!=64 or len({x['joint_input_digest'] for x in doc['rows']})!=64:
            raise ValueError('duplicated original source, case or input digest')
    for field in set(c)-{'partition','rows','material_id'}:
        if c[field]!=e[field]:raise ValueError('changed model/panel/authority provenance between splits')
    if ({x['source_group'] for x in c['rows']} & {x['source_group'] for x in e['rows']}) or ({x['case_id'] for x in c['rows']} & {x['case_id'] for x in e['rows']}):
        raise ValueError('training/evaluation source group contamination')
    return True


def routed_probability(row,thr):
    second=abs(float(row['granite_probability'])-.5)<=thr
    return (float(row['mmbert_probability']) if second else float(row['granite_probability'])),second


def pick_threshold(rows,budget):
    if budget not in BUDGETS:raise ValueError('unregistered extra model budget')
    cap=(len(rows)*budget)//100
    candidates=[]
    for t in THRESHOLDS:
        probs=[routed_probability(r,t) for r in rows]
        calls=sum(int(sel) for _,sel in probs)
        if calls>cap:continue
        hits=sum(int((p>=.5)==bool(r['label'])) for (p,_),r in zip(probs,rows,strict=True))
        brier=sum((p-r['label'])**2 for (p,_),r in zip(probs,rows,strict=True))/len(rows)
        candidates.append((hits,-brier,-calls,-t,t,calls))
    if not candidates:raise ValueError('every budget needs a feasible no-secondary control')
    _,minus_brier,_,_,threshold,calls=max(candidates)
    return dict(budget_percent=budget,calibration_calls=calls,calibration_accuracy=max(candidates)[0]/len(rows),
                calibration_brier=-minus_brier,confidence_margin=threshold)


def make_prediction(row,second,policy):
    g=float(row['granite_probability']);m=float(row['mmbert_probability'])
    if policy=='granite_only':p=g;secondary=False
    elif policy=='mmbert_only':p=m;secondary=True
    elif policy=='dual_most_confident':p=(m if abs(m-.5)>abs(g-.5) else g);secondary=True
    elif policy in ('fallback','random_matched','fixed_margin'):p=m if second else g;secondary=bool(second)
    else:raise ValueError('unknown policy')
    # This is a counterfactual *sum* of measured separate model runs;
    # it is NOT actual jointly executed latency, hardware p99 or one real request.
    encoder_cost=(0 if policy=='mmbert_only' else row['granite_encoder_ns'])+(row['mmbert_encoder_ns'] if secondary else 0)
    head_cost=(0 if policy=='mmbert_only' else row['granite_head_ns'])+(row['mmbert_head_ns'] if secondary else 0)
    return dict(case_id=row['case_id'],source_group=row['source_group'],joint_input_digest=row['joint_input_digest'],
         probability=p,secondary_called=secondary,mode=policy,observed_ledger_encoder_sum_ns=encoder_cost,
         observed_ledger_head_sum_ns=head_cost)


def fit(c,e):
    validate(c,e)
    policies={}
    for budget in BUDGETS:policies[f'fallback_{budget}']=pick_threshold(c['rows'],budget)
    outputs={}
    eval_rows=e['rows']
    for name in ('granite_only','mmbert_only','dual_most_confident'):
        outputs[name]=[make_prediction(r,True,name) for r in eval_rows]
    for budget in BUDGETS:
        name=f'fallback_{budget}'
        threshold=policies[name]['confidence_margin']
        chosen={r['case_id'] for r in eval_rows if routed_probability(r,threshold)[1]}
        outputs[name]=[make_prediction(r,r['case_id'] in chosen,'fallback') for r in eval_rows]
        matched=set(sorted((r['case_id'] for r in eval_rows),
                         key=lambda s:(hashlib.sha256((SALT+':'+name+':'+s).encode()).hexdigest(),s))[:len(chosen)])
        outputs[f'random_matched_{budget}']=[make_prediction(r,r['case_id'] in matched,'random_matched') for r in eval_rows]
    # Fixed, preregistered nonzero-control margins are NEVER selected by heldout labels.
    for name,threshold in FIXED.items():
        selected={r['case_id'] for r in eval_rows if routed_probability(r,threshold)[1]}
        outputs[name]=[make_prediction(r,r['case_id'] in selected,'fixed_margin') for r in eval_rows]
        random=set(sorted((r['case_id'] for r in eval_rows),key=lambda s:(hashlib.sha256((SALT+':'+name+':'+s).encode()).hexdigest(),s))[:len(selected)])
        outputs['random_equal_'+name]=[make_prediction(r,r['case_id'] in random,'random_matched') for r in eval_rows]
    obs=dict(schema=SCHEMA,calibration_material_id=c['material_id'],evaluation_material_id=e['material_id'],
             historical_source_panel_sha256=e['source_panel_sha256'],split_protocol=e['source_split_salt'],
             rules=policies,observations=outputs,calibration_count=64,evaluation_count=64,
             selected_after_evaluation_labels=False,full_model_inference_reexecuted=False,
             joint_model_request_physically_timed=False,historical_real_pretrained_predictors=True,
             future_time_independent=False,statistical_winner_certified=False,
             production_authorized=False,authority='DENY_ALL')
    obs['observation_id']=digest(obs)
    return obs


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--calibration',required=True);p.add_argument('--evaluation-blind',required=True);p.add_argument('--output-dir',required=True)
    a=p.parse_args();root=Path(a.output_dir);root.mkdir(parents=True,exist_ok=False)
    try:
        obs=fit(read(a.calibration),read(a.evaluation_blind))
        with (root/'predictions.json').open('x') as f:f.write(canon(obs).decode()+'\n')
        receipt=dict(schema=SCHEMA,observation_id=obs['observation_id'],
            observations_file_sha256=hashlib.sha256((root/'predictions.json').read_bytes()).hexdigest(),
            evaluation_labels_loaded=False,production_authorized=False)
        with (root/'COMMITTED.json').open('x') as f:f.write(canon(receipt).decode()+'\n')
    except Exception as exc:
        with (root/'FAILED.json').open('x') as f:f.write(canon(dict(type=type(exc).__name__,production_authorized=False)).decode()+'\n')
        raise
if __name__=='__main__':main()
