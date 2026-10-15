"""Independent stdlib-only audit of real PREEXISTING Granite/mmBERT model predictions.

Never imports original producer/materials/policy, torch or Transformers. All
original score, source, decision, latency and negative outcomes are rechecked.
"""
from __future__ import annotations
import argparse,hashlib,json,math,zipfile
from pathlib import Path

OLDZIP='e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d'
REALZIP='d8e2af397d7ea862245fae0337588ab491dd70e8a8a9a42879e4a7f2d4be3afa'
GRANITESHA='6098b3e5141694fbf841f092631ef7f00abee606eca12a6c82d6249211ee4e57'
MMBERTSHA='d5382f28e60627c0b4e35446b7bef84e9dc5ffb00cd76e4c1ab1b2a99f1cb2ac'
PANEL='8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a'
SCHEMA='hepta.real-archive.confidence-cascade-observation.v1'
SALT='hepta-20261015-mmbert-random-matched-v1'
GRID=(0.,.005,.01,.025,.05,.1,.2,.3,.4,.5)
BUDGETS=(0,10,25,50,100)
FIXED={'fixed_margin_020':.2,'fixed_margin_040':.4}

class Invalid(ValueError):pass

def check(ok,why):
    if not ok:raise Invalid(why)

def rawsha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def sha(v):return rawsha(canonical(v))
def pairs_unique(pairs):
    d={}
    for k,v in pairs:
        check(k not in d,'duplicate JSON key')
        d[k]=v
    return d

def read_json(path,cap=450000):
    p=Path(path)
    check(p.is_file() and not p.is_symlink() and 5<p.stat().st_size<cap,'bounded non-symlink review material')
    return json.loads(p.read_bytes(),object_pairs_hook=pairs_unique,parse_constant=lambda x:(_ for _ in ()).throw(Invalid('nonfinite JSON')))

def zread(z,name):
    names=z.namelist()
    check(len(names)==len(set(names)) and name in names and z.getinfo(name).file_size<800000,'original ZIP member inventory')
    return json.loads(z.read(name),object_pairs_hook=pairs_unique)

def original_archive(original_zip,physical_zip):
    check(rawsha(Path(original_zip).read_bytes())==OLDZIP,'historical source bytes changed')
    check(rawsha(Path(physical_zip).read_bytes())==REALZIP,'real pretrained report ZIP bytes changed')
    with zipfile.ZipFile(original_zip) as z:
        source=zread(z,'stem-agnews-new-source-panel.json')
    with zipfile.ZipFile(physical_zip) as z:
        granite=zread(z,'granite97.report.json');mmbert=zread(z,'mmbert_small.report.json');prior=zread(z,'independent-scores.json')
    check(sha(source)==PANEL and len(source['cases'])==128 and
      source.get('chronological_future_claim') is False and
      source.get('source_signer_independently_authenticated') is False and
      source.get('production_promotion')=='DENY_ALL','historical source identity')
    original={c['case_id']:c for c in source['cases']}
    check(len(original)==128 and all(c['split']=='new_holdout' and c['source_digest']==c['group_id'] and c['source_digest'][:24]==c['case_id'] for c in original.values()),'original source groups')
    models={}
    for name,doc,expected in [('granite97',granite,GRANITESHA),('mmbert_small',mmbert,MMBERTSHA)]:
        check(sha(doc)==expected and doc['model_id']==name and doc['model_weights_executed_locally'] is True
              and doc['authority']=='DENY_ALL' and doc['production_accepted'] is False and
              doc['actual_encoder_forward_count']==352,'pretrained source model identity')
        rows={p['case_id']:p for p in doc['future_predictions'] if p['split']=='new_holdout'}
        check(len(rows)==128 and set(rows)==set(original),'original complete paired predictions')
        for k,row in rows.items():
            check(row['group_id']==original[k]['group_id'] and row['joint_input_digest']==original[k]['joint_input_digest'], 'original model/source pair identity')
        check(prior['report_sha256'][name]==expected and prior['models'][name]['quality']['new_holdout']['learned_gate']['correct']==sum(int((p['probs']['learned_gate']>=.5)==bool(original[k]['label'])) for k,p in rows.items()),'independent original source score replay')
        models[name]=rows
    return original,models


def expected_rule(rows,percent):
    cap=len(rows)*percent//100
    choices=[]
    for threshold in GRID:
        called=[abs(r['granite_probability']-.5)<=threshold for r in rows]
        n=sum(called)
        if n>cap:continue
        probabilities=[r['mmbert_probability'] if call else r['granite_probability'] for r,call in zip(rows,called)]
        correct=sum(int((p>=.5)==bool(r['label'])) for p,r in zip(probabilities,rows))
        brier=sum((p-r['label'])**2 for p,r in zip(probabilities,rows))/len(rows)
        choices.append((correct,-brier,-n,-threshold,threshold,n))
    check(bool(choices),'no registered budget feasible')
    best=max(choices)
    return {'budget_percent':percent,'calibration_calls':best[5],'calibration_accuracy':best[0]/len(rows),
             'calibration_brier':-best[1],'confidence_margin':best[4]}


def rank_values(values,percent):
    check(values and all(type(x) in (int,float) and math.isfinite(x) and x>0 for x in values),'positive real time samples')
    ordered=sorted(values)
    return ordered[max(0,math.ceil(percent*len(ordered))-1)]


def audit(calibration,blind,owner,observation,*,original_zip,physical_zip,receipt=None):
    base,models=original_archive(original_zip,physical_zip)
    c=calibration;e=blind;o=owner;ob=observation
    check(isinstance(c,dict) and c.get('partition')=='calibration' and isinstance(e,dict) and e.get('partition')=='evaluation','separate partitions')
    check(c.get('material_id')==sha({k:v for k,v in c.items() if k!='material_id'}) and e.get('material_id')==sha({k:v for k,v in e.items() if k!='material_id'}),'tampered material seal')
    check(c.get('authority')==e.get('authority')=='DENY_ALL' and c.get('model_forward_newly_executed') is False and e.get('model_forward_newly_executed') is False,'false capability claims')
    check(c.get('source_panel_sha256')==e.get('source_panel_sha256')==PANEL and len(c.get('rows',[]))==len(e.get('rows',[]))==64,'source cohort count')
    check(isinstance(o,dict) and o.get('schema')=='hepta.real-archive.stem-cascade-owner-label.v1'
          and o.get('evaluation_material_id')==e['material_id'] and o.get('owner_id')==sha({k:v for k,v in o.items() if k!='owner_id'})
          and o.get('production_authorized') is False and o.get('authority')=='DENY_ALL','wrong original label owner seal')
    check(set(o['labels'])=={r['case_id'] for r in e['rows']},'complete heldout label denominator')
    allids={x['case_id'] for x in c['rows']+e['rows']}
    check(len(allids)==128 and set(base)==allids,'source selected subset drift')
    for part,rows in [('calibration',c['rows']),('evaluation',e['rows'])]:
        check([r['case_id'] for r in rows]==sorted(r['case_id'] for r in rows),'row order')
        for r in rows:
            expected={'case_id','source_group','joint_input_digest','granite_probability','mmbert_probability',
                      'granite_encoder_ns','mmbert_encoder_ns','granite_head_ns','mmbert_head_ns'}|({'label'} if part=='calibration' else set())
            check(set(r)==expected,'labels leaked or changed row field inventory')
            ident=r['case_id'];truth=base[ident]
            check(r['source_group']==truth['group_id'] and r['joint_input_digest']==truth['joint_input_digest'],'row identity differs original source')
            if part=='calibration':check(r['label']==truth['label'],'calibration human label drift')
            else:check(o['labels'][ident]==truth['label'],'withheld owner labels do not match source')
            for model,slug in [('granite97','granite'),('mmbert_small','mmbert')]:
                obs=models[model][ident]
                check(r[slug+'_probability']==obs['probs']['learned_gate']
                   and r[slug+'_encoder_ns']==obs['encoder_forward_ns']
                   and r[slug+'_head_ns']==obs['head_ns']['learned_gate'],
                   'forged original model prediction or cost')
    check(ob.get('schema')==SCHEMA and ob.get('observation_id')==sha({k:v for k,v in ob.items() if k!='observation_id'})
        and ob.get('calibration_material_id')==c['material_id'] and ob.get('evaluation_material_id')==e['material_id']
        and ob.get('calibration_count')==ob.get('evaluation_count')==64
        and ob.get('selected_after_evaluation_labels') is False
        and ob.get('full_model_inference_reexecuted') is False
        and ob.get('joint_model_request_physically_timed') is False
        and ob.get('historical_real_pretrained_predictors') is True
        and ob.get('future_time_independent') is False and ob.get('statistical_winner_certified') is False
        and ob.get('production_authorized') is False and ob.get('authority')=='DENY_ALL',
        'unsafe observation receipt or source mismatch')
    if receipt is not None:
        check(receipt.get('observation_id')==ob['observation_id'] and receipt.get('evaluation_labels_loaded') is False,'holdout used before seal')
    check(set(ob['rules'])=={f'fallback_{b}' for b in BUDGETS},'missing prospective budget policy')
    for b in BUDGETS:
        key=f'fallback_{b}'
        check(ob['rules'][key]==expected_rule(c['rows'],b),'policy selected from heldout or altered calibration rule')
    expected_names={'granite_only','mmbert_only','dual_most_confident'}|{f'fallback_{b}' for b in BUDGETS}|{f'random_matched_{b}' for b in BUDGETS}|set(FIXED)|{'random_equal_'+k for k in FIXED}
    check(set(ob['observations'])==expected_names,'missing strong controls or budget arms')
    outcomes={}
    baseline=[(r['granite_probability']>=.5)==bool(o['labels'][r['case_id']]) for r in e['rows']]
    for name,rows in ob['observations'].items():
        check(len(rows)==64,'changed heldout denominator')
        if name.startswith('random_matched_') or name.startswith('random_equal_'):
            origin=name[len('random_equal_'):] if name.startswith('random_equal_') else 'fallback_'+name.rsplit('_',1)[-1]
            thr=FIXED[origin] if origin in FIXED else ob['rules'][origin]['confidence_margin']
            n=sum(int(abs(r['granite_probability']-.5)<=thr) for r in e['rows'])
            chosen=set(sorted((r['case_id'] for r in e['rows']),key=lambda k:(rawsha((SALT+':'+origin+':'+k).encode()),k))[:n])
        else:chosen=set()
        prob=[];hits=[];encoder=[];head=[];secondary_count=0;wins=0;losses=0
        for pred,original in zip(rows,e['rows']):
            check(set(pred)=={'case_id','source_group','joint_input_digest','probability','secondary_called','mode','observed_ledger_encoder_sum_ns','observed_ledger_head_sum_ns'},'unregistered prediction field')
            check(pred['case_id']==original['case_id'] and pred['source_group']==original['source_group'] and pred['joint_input_digest']==original['joint_input_digest'],'changed case attribution')
            g=original['granite_probability'];m=original['mmbert_probability']
            if name=='granite_only':selected=False;expected=g;mode='granite_only'
            elif name=='mmbert_only':selected=True;expected=m;mode='mmbert_only'
            elif name=='dual_most_confident':selected=True;expected=m if abs(m-.5)>abs(g-.5) else g;mode='dual_most_confident'
            elif name.startswith('random_matched_') or name.startswith('random_equal_'):selected=original['case_id'] in chosen;expected=m if selected else g;mode='random_matched'
            elif name in FIXED:selected=abs(g-.5)<=FIXED[name];expected=m if selected else g;mode='fixed_margin'
            elif name.startswith('fallback_'):
                b=int(name.split('_')[-1]);selected=abs(g-.5)<=ob['rules'][name]['confidence_margin'];expected=m if selected else g;mode='fallback'
            else:raise Invalid('unknown prediction arm')
            check(pred['mode']==mode and pred['secondary_called'] is selected and abs(pred['probability']-expected)<1e-14,'forged heldout policy prediction')
            cost=(0 if name=='mmbert_only' else original['granite_encoder_ns'])+(original['mmbert_encoder_ns'] if selected else 0)
            hcost=(0 if name=='mmbert_only' else original['granite_head_ns'])+(original['mmbert_head_ns'] if selected else 0)
            check(pred['observed_ledger_encoder_sum_ns']==cost and pred['observed_ledger_head_sum_ns']==hcost,
                  'fake zero second model cost')
            secondary_count+=selected;encoder.append(cost);head.append(hcost)
            y=o['labels'][original['case_id']];prob.append(expected)
            hit=(expected>=.5)==bool(y);hits.append(hit)
            baseline_hit=baseline[len(hits)-1]
            wins+=int(hit and not baseline_hit);losses+=int(baseline_hit and not hit)
        outcomes[name]=dict(correct=sum(hits),tasks=64,accuracy=sum(hits)/64,
            brier=sum((p-o['labels'][r['case_id']])**2 for p,r in zip(prob,e['rows']))/64,
            extra_second_stem_calls=secondary_count if name!='mmbert_only' else 0,
            number_of_stem_forwards_estimated=secondary_count+(0 if name=='mmbert_only' else 64),
            total_replayed_encoder_ns=sum(encoder),
            extra_replayed_encoder_ns=(sum(r['mmbert_encoder_ns'] for r,p in zip(e['rows'],rows) if p['secondary_called']) if name!='mmbert_only' else 0),
            actual_encoder_calls_in_this_study=0,
            counterfactual_serial_encoder_ns_p50=rank_values(encoder,.5),
            counterfactual_serial_encoder_ns_p95=rank_values(encoder,.95),
            counterfactual_serial_encoder_ns_p99=rank_values(encoder,.99),
            source_observed_head_ns_total=sum(head),granite_recovered=wins,granite_regressed=losses)
    for budget in BUDGETS:
        key=f'fallback_{budget}'
        # Evaluation requests may exceed the calibration-selected budget by chance;
        # report excess and NEVER suppress it. Budget is training-side only.
        outcomes[key]['heldout_budget_fraction_may_differ']=True
    return dict(schema='hepta.real-archive.cascade-independent-audit.v1',source_observation_id=ob['observation_id'],
        original_zip_sha256=OLDZIP,physical_zip_sha256=REALZIP,source_panel_sha256=PANEL,
        report=outcomes,calibration_policy=ob['rules'],calibration_cases=64,heldout_cases=64,
        retrospectively_source_disjoint_not_future=True,source_and_model_issuer_signature_verified=False,
        real_pretrained_model_forward_newly_executed=False,physical_joint_fallback_request_timed=False,
        counterfactual_latency_is_sum_of_separate_observed_model_times=True,
        head_parameter_and_training_cost_matched=False,statistical_model_winner_selected=False,
        production_authorized=False,authority='DENY_ALL')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for flag in ('calibration','evaluation-blind','owner-labels','predictions-dir','historical-source-zip','real-physical-zip','output-dir'):
        ap.add_argument('--'+flag,required=True)
    a=ap.parse_args();dest=Path(a.output_dir);dest.mkdir(parents=True,exist_ok=False)
    try:
        pre=Path(a.predictions_dir)
        check(not (pre/'FAILED.json').exists() and (pre/'COMMITTED.json').exists(),'prelabel phase did not succeed')
        commit=read_json(pre/'COMMITTED.json');obs=read_json(pre/'predictions.json')
        check(commit.get('observations_file_sha256')==rawsha((pre/'predictions.json').read_bytes()),'predictions file changed')
        score=audit(read_json(a.calibration),read_json(a.evaluation_blind),read_json(a.owner_labels),obs,
             original_zip=a.historical_source_zip,physical_zip=a.real_physical_zip,receipt=commit)
        with (dest/'scores.json').open('x') as f:f.write(canonical(score).decode()+'\n')
        with (dest/'COMMITTED.json').open('x') as f:f.write(canonical(dict(schema=score['schema'],source_observation_id=score['source_observation_id'],
           report_file_sha256=rawsha((dest/'scores.json').read_bytes()),production_authorized=False)).decode()+'\n')
    except Exception as exc:
        with (dest/'FAILED.json').open('x') as f:f.write(canonical(dict(error_type=type(exc).__name__,production_authorized=False)).decode()+'\n')
        raise
if __name__=='__main__':main()
