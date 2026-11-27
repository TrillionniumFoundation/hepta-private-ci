"""Original-source task/cost Pareto replay; NEVER a model or promotion oracle.

Proofs here are finite and retrospective. Training updates and CPU are alternative
cost measures because observed CPU already includes optimizer work. Source rows,
model inputs and postseal truth are re-read; no reported score is trusted.
"""
from __future__ import annotations

import argparse
from fractions import Fraction as Q
from hashlib import sha256
import json
from pathlib import Path
import zipfile
import math

PUBLIC_SHA='195dfb9e5bedaf5cee7fe8b2994a10f7ebaaf9ecca2a3a94bb77b0185a4337a7'
TRIAL_SHA='c78cfe148e6d9544450836202f4da0f9bc5d93f980c96362238945b20a67898f'
SCHEMA='hepta.ndu-merton.original-pareto-frontier.v1'
ARMS=('zero','train_majority','fixed8','fixed32','fixed128','neutral',
      'fixed_risk','ndu_discrete','augmented_same_profile')
STEPS={'zero':0,'train_majority':0,'fixed8':8,'fixed32':32,
       'fixed128':128,'neutral':128,'fixed_risk':128,
       'ndu_discrete':128,'augmented_same_profile':128}


def reject(condition:bool, explanation:str)->None:
    if not condition:raise ValueError(explanation)


def read_json(z:zipfile.ZipFile,name:str):
    reject(name in z.namelist(),'original ZIP member missing: '+name)
    def no_dupes(pairs):
        out={}
        for k,v in pairs:
            reject(k not in out,'duplicate JSON key')
            out[k]=v
        return out
    return json.loads(z.read(name),object_pairs_hook=no_dupes,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


def archived_bytes(path, expected):
    b=Path(path).read_bytes()
    reject(sha256(b).hexdigest()==expected,'original archive SHA mismatch')
    return b


def original_labels(z):
    lines=z.read('hepta-public-study/dataset.jsonl').splitlines()
    records=[json.loads(x) for x in lines]
    reject(len(records)==128,'incorrect original denominator')
    reject(len({r['case_id'] for r in records})==128,'duplicate original record')
    split={s:[r for r in records if r['split']==s] for s in ('train','calibration','holdout')}
    reject(tuple(len(split[s]) for s in ('train','calibration','holdout'))==(64,32,32),
           'incorrect original split')
    reject(all(type(r['label']) is int and 0<=r['label']<4 and r['group']==r['case_id']
               for r in records),'bad original label or claimed source grouping')
    return {r['case_id']:r['label'] for r in split['holdout']}


def class_id(probs):
    reject(type(probs) is list and len(probs)==4 and
           all(type(x) in (int,float) and math.isfinite(x) and 0<=x<=1 for x in probs)
           and abs(sum(probs)-1)<1e-9,'bad model probabilities')
    return max(range(4),key=lambda k:probs[k])


def inspect_row(r, arm,repeat,original):
    """Return truth-checked decisions and raw alternative cost metrics."""
    reject(type(r) is dict and r.get('arm')==arm and r.get('repeat')==repeat,
           'wrong original arm or repetition')
    steps=r.get('actual_steps')
    reject(type(steps) is int and steps==STEPS[arm],'training actually executed differs')
    expected=0 if arm in ('zero','train_majority') else 8 if arm not in ('fixed32','fixed128') else (32 if arm=='fixed32' else 128)
    reject(type(r.get('selected_steps')) is int and r['selected_steps']==expected,
           'unearned or unsupported checkpoint selection')
    cpu=r.get('cpu_ns');wall=r.get('wall_ns')
    reject(type(cpu) is int and cpu>0 and type(wall) is int and wall>0,
           'missing original CPU/wall measurement')
    phases=r.get('phases')
    reject(type(phases) is dict and phases and
           all(type(p) is dict and set(p)=={'cpu_ns','wall_ns'} and
               type(p['cpu_ns']) is int and type(p['wall_ns']) is int and
               p['cpu_ns']>=0 and p['wall_ns']>=0 for p in phases.values())
           and sum(p['cpu_ns'] for p in phases.values())<=cpu,
           'unmetered or inconsistent original phase inventory')
    # Freeze the original 32 identifiers; never regard 3x2 repetitions as new groups.
    ids=r.get('holdout_ids');values=r.get('probabilities')
    reject(type(ids) is list and len(ids)==32 and set(ids)==set(original) and
           len(set(ids))==32,'original source sample mismatch')
    reject(type(values) is list and len(values)==32,'missing original probability vectors')
    pred={case:class_id(p) for case,p in zip(ids,values)}
    correctness=tuple(int(pred[k]==original[k]) for k in sorted(original))
    return {'arm':arm,'repeat':repeat,'actual_steps':steps,
            'cpu_ns':cpu,'wall_ns':wall,'correct':sum(correctness),
            'per_case_correct_sha256':sha256(bytes(correctness)).hexdigest(),
            'prediction_sha256':sha256(json.dumps(
                {k:values[ids.index(k)] for k in sorted(original)},
                sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            '_correct_vector':correctness,
            '_prob_by_case':{k:values[ids.index(k)] for k in original}}


def pareto_pair(challenger,baseline):
    """Observed tasks with a separate *alternative* step and CPU census."""
    diff=challenger['correct']-baseline['correct']
    steps=challenger['actual_steps']-baseline['actual_steps']
    cpu=challenger['cpu_ns']-baseline['cpu_ns']
    matching=challenger['_correct_vector']==baseline['_correct_vector']
    probabilities=challenger['_prob_by_case']==baseline['_prob_by_case']
    # With equal observed outcomes, both measured resource dimensions can be
    # weakly Pareto dominated, but unknown lifecycle phases bar service claims.
    dominated=(probabilities and steps>=0 and cpu>=0 and (steps>0 or cpu>0))
    return {'correct_delta':diff,'step_delta':steps,'observed_cpu_ns_delta':cpu,
            'same_per_task_outcomes':matching,
            'same_original_probabilities':probabilities,
            'observed_two_dimension_dominance':dominated,
            'source_family_independence_verified':False,
            'complete_online_cost_verified':False}


def exact_net_delta(task_correct_delta:int, step_delta:int,
                    utility_per_correct:Q, utility_per_step:Q)->Q:
    """Declared thought experiment, not authenticated real price or production ROI."""
    reject(type(task_correct_delta) is int and type(step_delta) is int,
           'integer observed deltas required')
    reject(type(utility_per_correct) is Q and type(utility_per_step) is Q and
           utility_per_correct>=0 and utility_per_step>=0,
           'only explicit nonnegative rational tariffs accepted')
    return utility_per_correct*task_correct_delta-utility_per_step*step_delta


def break_even_step_tariff(correct_delta:int, step_delta:int):
    """Minimum task value, in step-tariff units, for observed nonnegative delta."""
    reject(type(correct_delta) is int and type(step_delta) is int,'integer deltas required')
    if correct_delta<=0:return None
    return Q(step_delta,correct_delta) if step_delta>=0 else Q(0)


def original_frontier(public_zip:str|Path,trial_zip:str|Path):
    archived_bytes(public_zip,PUBLIC_SHA)
    archived_bytes(trial_zip,TRIAL_SHA)
    with zipfile.ZipFile(public_zip) as src,zipfile.ZipFile(trial_zip) as run:
        for z in (src,run):
            reject(len(z.namelist())==len(set(z.namelist())) and z.testzip() is None,
                   'duplicate member or broken archive')
        model=read_json(src,'hepta-public-study/model-source.json')
        reject(model['model_id']=='jhu-clsp/mmBERT-small' and
               model['revision']=='abc32620dd4f6ab06f5fbe905dc25f310618e09f',
               'wrong original pretrained model or revision')
        truth=original_labels(src)
        reject(truth==read_json(run,'news-material/scorer-labels.json'),
               'original human label/custody mismatch')
        base=read_json(run,'news-final-normal/protocol.json')
        reject(base['archive_sha256']==PUBLIC_SHA and base['model_id']==model['model_id']
               and base['model_revision']==model['revision'] and
               base['arms']==list(ARMS) and
               base['archive_previously_scored_by_other_research'] is True and
               base['record_ids_are_not_validated_independent_story_families'] is True,
               'experiment registration or historical nonclaim lost')
        rows=[];pairs=[]
        for mode in ('normal','optimized'):
            seal=read_json(run,'news-final-'+mode+'/sealed.json')
            reject(seal['archive_sha256']==PUBLIC_SHA and seal['heldout_labels_loaded'] is False
                   and seal['posture']=='RESEARCH_ONLY_DENY_ALL' and len(seal['rows'])==27,
                   'blind model seal or original complete census missing')
            saved={(x['repeat'],x['arm']):x for x in seal['rows']}
            reject(len(saved)==27,'duplicated original trial')
            for repeat in range(3):
                arms={}
                for arm in ARMS:
                    raw=read_json(run,f'news-final-{mode}/{repeat}-{arm}.json')
                    reject(raw==saved[(repeat,arm)],'postseal original row mutation')
                    arms[arm]=inspect_row(raw,arm,repeat,truth)
                # Do not manufacture 32 clusters / mode / repeat from reused 32 tasks.
                refs={a:pareto_pair(x,arms['fixed8']) for a,x in arms.items() if a!='fixed8'}
                reject(all(arms[a]['correct']==26 for a in
                           ('fixed8','neutral','fixed_risk','ndu_discrete','augmented_same_profile')),
                       'original task success counts changed')
                # Explicitly record if observation does not match old raw source.
                for a in ('neutral','fixed_risk','ndu_discrete','augmented_same_profile'):
                    reject(refs[a]['same_original_probabilities'],
                           'full search selected an unregistered different answer')
                pairs.append({'interpreter':mode,'repeat':repeat,'comparisons_to_fixed8':refs})
                rows += [{k:v for k,v in r.items() if not k.startswith('_')}
                         |{'interpreter':mode} for r in arms.values()]
    dominated=all(p['comparisons_to_fixed8']['ndu_discrete']['observed_two_dimension_dominance']
                  for p in pairs)
    return {'schema':SCHEMA,'source_sha256':PUBLIC_SHA,'trial_sha256':TRIAL_SHA,
            'posture':'RESEARCH_ONLY_DENY_ALL','case_count':32,
            'verified_independent_story_families':0,'prospective_windows':0,
            'repetitions_not_independent':True,'study_rows':len(rows),
            'matched_pairs':len(pairs),'observed_ndu_dominated_by_fixed8_all_pairs':dominated,
            'complete_online_service_cost_verified':False,'ndu_specific_gain_verified':False,
            'production_accepted':False,'all_rows':rows,'paired_reviews':pairs}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--original-source',type=Path,required=True)
    ap.add_argument('--original-trials',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    result=original_frontier(a.original_source,a.original_trials)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as f:
        json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({'pairs':result['matched_pairs'],'rows':result['study_rows'],
                      'observed_dominance':result['observed_ndu_dominated_by_fixed8_all_pairs']},sort_keys=True))


if __name__=='__main__':main()
