"""Independent outward-rounded discrete-FBSDE action choice audit on sealed P5 source.

No production optimizer or inference claim. Computes math certificate using exact
IEEE coefficient values and pure integer intervals; replays work via independent
prefix-indexed FP64 reference solely to challenge claimed operator work.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
from time import process_time_ns, perf_counter_ns
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]/'ndu-p5-coupled-study'))
from independent_reference import direct_map  # WORK REPLAY ONLY, never mathematical bounds
from rigorous_tree import action_bounds,resolve,SCALE,Unqualified

SCHEMA='hepta.ndu.p5.roundoff-independent-audit.v1'
PARENT_SCHEMA='hepta.ndu.p5.costed-decision.v1'
EXPECTED_SOURCE='e420444337d163508cd7ba8122894ffd334566b52d57073e67b94203e301eac2'
EXPECTED_ORIGINAL_PLAN='92c568e9694c259b64ac1f8bb1f6db9d9214dd14ca13c81ff7d1f75bbea7a607'
REQUIRED_PROVENANCE={
    'authority':'DENY_ALL',
    'production_accepted':False,
}

class AuditError(ValueError):pass

def require(pred,msg):
    if not pred:raise AuditError(msg)

def canonical(o):return json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
def digest(o):return hashlib.sha256(canonical(o)).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def fsha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

class Profile:
    """Only supplies independent_reference with input profile geometry.
    Not used by rigorous interval solver.
    """
    def __init__(self,c,o):
        self.steps=c['steps'];self.horizon=c['horizon'];self.a=o['a'];self.beta=c['beta'];self.lam=c['lam'];self.sigma=c['sigma'];self.x0=c['x0']
    @property
    def h(self):return self.horizon/self.steps


def audit(source,sealed,prior=None,*,check_replay=True):
    started_cpu=process_time_ns();started_wall=perf_counter_ns()
    require(type(source) is dict and source.get('schema')==PARENT_SCHEMA and source.get('kind')=='plan', 'invalid source protocol')
    require(source.get('synthetic_only') is True and source.get('true_future_time_verified') is False, 'unsupported natural/future claim')
    for k,v in REQUIRED_PROVENANCE.items():require(source.get(k) is v if type(v) is bool else source.get(k)==v,'source authority')
    require(digest(source)==EXPECTED_SOURCE,'source task identity changed')
    cases=source.get('cases')
    require(type(cases) is list and len(cases)==192 and len({t['task_id'] for t in cases})==192,'source incomplete')
    require(sum(c['cohort']=='cohort_a' for c in cases)==96 and sum(c['cohort']=='cohort_b' for c in cases)==96,'source group count')
    require(type(sealed) is dict and sealed.get('schema')==PARENT_SCHEMA and sealed.get('kind')=='sealed_predictions' and sealed.get('source_sha256')==EXPECTED_SOURCE,'wrong pred/source binding')
    for k,v in REQUIRED_PROVENANCE.items():require(sealed.get(k) is v if type(v) is bool else sealed.get(k)==v,'prediction authority')
    require(sealed.get('reference_oracle_read_before_seal') is False,'unsealed future oracle')
    data=sealed.get('entries')
    require(type(data) is list and len(data)==192,'incomplete predicted task inventory')
    before={}
    if prior is not None:
        require(type(prior) is dict and prior.get('schema')==PARENT_SCHEMA and prior.get('kind')=='independent_score' and prior.get('source_sha256')==EXPECTED_SOURCE and prior.get('sealed_prediction_sha256')==digest(sealed),'historical independent score changed')
        require(prior.get('production_accepted') is False and prior.get('authority')=='DENY_ALL' and prior.get('continuous_FBSDE_or_roundoff_rigorous') is False,'original overclaim')
        q=prior.get('rows');require(type(q) is list and len(q)==192,'prior score incomplete')
        before={v['task_id']:v for v in q}
        require(len(before)==192,'prior duplicate')
    count=0; gaps=[]; minnom=[]; uncertified=[]; groups={'cohort_a':[],'cohort_b':[]}; picard_calls=0
    for i,(task,record) in enumerate(zip(cases,data)):
        require(record.get('task_id')==task['task_id'] and record.get('cohort')==task['cohort'],'source ordering drift')
        options=task.get('options')
        require(type(options) is list and len(options)==3 and [o['action_id'] for o in options]==['control_0','control_1','control_2'],'action/legal set changed')
        nominal=record.get('nominal_early')
        require(type(nominal) is dict and nominal.get('production_accepted') is False and nominal.get('authority')=='DENY_ALL' and nominal.get('continuum_or_FP64_rigorous_certificate') is False,'nominal claim incompatible')
        edges=nominal.get('per_action')
        require(type(edges) is list and len(edges)==3,'missing action trajectory')
        interval=[];calls=0
        for opt,obs in zip(options,edges):
            require(obs.get('action_id')==opt['action_id'] and obs.get('a')==opt['a'] and obs.get('cost')==opt['cost'],'changed option')
            require(type(obs.get('calls')) is int and 1<=obs['calls']<=90,'invalid computation counter')
            y=obs.get('y');require(type(y) is list and len(y)==2**task['steps']-1 and all(type(x) in (float,int) and math.isfinite(x) for x in y),'unbound or nonfinite Y')
            calls+=obs['calls']
            if check_replay:
                pp=Profile(task,opt)
                base=[0.0]*(2**pp.steps-1)
                for _ in range(obs['calls']-1):
                    base=direct_map(pp,base)
                require(max(abs(v-w) for v,w in zip(base,y))<=2e-11,'source-held work trajectory not reproduced')
            cert=action_bounds(task,opt,y)
            # Nominal values must lie approximately at their expected fixed-point intervals.
            # Crucially, only cert (not original reported radius) determines outcome.
            for field in ('radius','residual','lower','upper','contraction_q'):
                require(type(obs.get(field)) in (int,float) and math.isfinite(obs[field]),
                        'missing/nonfinite originally asserted '+field)
            require(obs['radius']>=0 and abs(obs['radius']-cert['radius_ticks']/SCALE)<2e-10 and
                    abs(obs['lower']-cert['lower_ticks']/SCALE)<2e-10 and
                    abs(obs['upper']-cert['upper_ticks']/SCALE)<2e-10 and
                    abs(obs['residual']-cert['residual_ticks']/SCALE)<2e-10 and
                    abs(obs['contraction_q']-cert['q_exact_numerator']/cert['q_exact_denominator'])<2e-13,
                    'original nominal interval differs materially from rigorous re-evaluation')
            interval.append(cert)
        require(calls==nominal.get('work_calls') and calls<=90,'fake total calls')
        choice,margin=resolve(interval)
        old=nominal.get('choice')
        if choice is not None:
            require(choice==old and nominal.get('certified_nominal') is True,'outward rounding contradicts nominal winner')
        if old not in {'control_0','control_1','control_2','abstain',None}:
            raise AuditError('illegal nominal action')
        nominal_margin=nominal.get('positive_gap_lower_bound')
        if choice is not None:
            require(type(nominal_margin) in (int,float) and math.isfinite(nominal_margin) and
                    nominal_margin>0 and abs(nominal_margin-margin/SCALE)<2e-10,
                    'original positive nominal gap changed or inconsistent')
        else:
            require(nominal_margin is None or (type(nominal_margin) in (int,float) and
                    math.isfinite(nominal_margin)), 'invalid incomplete nominal gap')
        if choice is None:uncertified.append(task['task_id'])
        if task['task_id'] in before:
            require(before[task['task_id']]['early_action']==old and before[task['task_id']]['certified']==nominal['certified_nominal'],'original final-score identity mismatch')
            if choice is not None:
                require(before[task['task_id']]['optimum']==choice,'independent postseal reference selected different action')
        record_out={'task_id':task['task_id'],'cohort':task['cohort'],'rigorously_enclosed_discrete_action':choice,
                    'nonzero_gap_ticks':margin if choice is not None else None,
                    'guaranteed_additive_value_drift_per_action_ticks':margin//2 if choice is not None else None,
                    'original_nominal_choice':old,'nominal_work_calls':calls,'nominal_certified':nominal.get('certified_nominal'),
                    'roundoff_reaudit_passed':choice is not None}
        groups[task['cohort']].append(record_out)
        count+=choice is not None
        if choice is not None:gaps.append(margin)
        if nominal.get('positive_gap_lower_bound') is not None:minnom.append(nominal['positive_gap_lower_bound'])
        picard_calls+=calls
    summary={}
    for cohort,records in groups.items():
        summary[cohort]={'cases':len(records),'roundoff_enclosed_winners':sum(z['roundoff_reaudit_passed'] for z in records),
                         'nominal_map_calls_charged':sum(z['nominal_work_calls'] for z in records),
                         'min_positive_action_gap_lower_bound': min((z['nonzero_gap_ticks']/SCALE for z in records if z['nonzero_gap_ticks'] is not None),default=None)}
    return {'schema':SCHEMA,'original_source_digest':EXPECTED_SOURCE,'original_seal_digest':digest(sealed),
            'source_task_count':len(cases),'nominal_certified_total':sum(x['nominal_early']['certified_nominal'] for x in data),
            'roundoff_enclosed_action_count':count,'unverified_action_ids':uncertified,
            'nominal_map_calls_charged':picard_calls,'min_positive_gap_lower_bound':min(gaps)/SCALE if gaps else None,
            'min_nominal_gap':min(minnom) if minnom else None,'cohorts':summary,
            'rows':[v for k in ('cohort_a','cohort_b') for v in groups[k]],
            'independent_full_reference_checked':prior is not None,
            'IEEE_binary64_source_coefficients_enclosed':True,
            'exact_integer_directional_rounding_and_tanh_taylor_bounds_used':True,
            'certified_target':'registered discrete binary-tree FBSDE action under exact IEEE source coefficients',
            'continuous_time_FBSDE_certified':False,'generalized_language_reasoning_certified':False,
            'model_origin_authenticated':False,'roundoff_runtime_overhead_charged_separately':True,
            'independent_hardware_attestation':False,
            'production_accepted':False,'authority':'DENY_ALL',
            'audit_cpu_ns':max(1,process_time_ns()-started_cpu),'audit_wall_ns':max(1,perf_counter_ns()-started_wall)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True);p.add_argument('--source-sha256',required=True)
    p.add_argument('--sealed',required=True);p.add_argument('--sealed-sha256',required=True)
    p.add_argument('--independent-score');p.add_argument('--independent-score-sha256')
    p.add_argument('--output',required=True)
    a=p.parse_args()
    for path,hashv in ((a.source,a.source_sha256),(a.sealed,a.sealed_sha256)):
        require(fsha(path)==hashv,'source or sealed file bytes not bound')
    if a.independent_score:
        require(a.independent_score_sha256 and fsha(a.independent_score)==a.independent_score_sha256,'independent score file bytes not bound')
    else:
        require(a.independent_score_sha256 is None,'score digest without score input')
    result=audit(read(a.source),read(a.sealed),read(a.independent_score) if a.independent_score else None)
    with Path(a.output).open('xb') as f:f.write(canonical(result)+b'\n')
    print(json.dumps({'schema':SCHEMA,'source_digest':result['original_source_digest'],
        'count':result['roundoff_enclosed_action_count'],'cpu_ns':result['audit_cpu_ns'],
        'production_accepted':False},sort_keys=True))

if __name__=='__main__':main()
