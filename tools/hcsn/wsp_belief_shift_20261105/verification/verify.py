"""Independent evidence arithmetic and pinned-evaluator selected-world replay."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import math
import numpy as np
from scipy.stats import t

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import planning as p
from run_shift_ablation import Scores


def load(path):
    b=path.read_bytes()
    return json.loads(gzip.decompress(b) if path.suffix=='.gz' else b)


class ScoreAdapter:
    def __init__(self, score): self.score=score
    def scores(self,state,theta,structural): return self.score(state)


def main(inputs, evidence, output):
    started,wall=time.process_time(),time.perf_counter()
    protocol=load(ROOT/'PROTOCOL_FROZEN.json')
    report=load(evidence/'RESULTS.json')
    allrows=[]
    for f in sorted(evidence.glob('fit_*.json.gz')):allrows.extend(load(f))
    assert len(allrows)==240
    assert len({x['world_id'] for x in allrows})==240
    assert all(x['cold_compile']['bellman_residual_max']<=2e-11 for x in allrows)
    assert all(x['cold_compile']['probability_sum_error_max']<=2e-11 for x in allrows)
    for path,digest in protocol['input_files'].items():
        assert hashlib.sha256((inputs/path).read_bytes()).hexdigest()==digest, path
    extended={}
    for domain in protocol['domains']:
        group=[x for x in allrows if x['domain']==domain]
        per_fit={f:{a:float(np.mean([x['arms'][a]['utility'] for x in group if x['fit']==f])) for a in ('C','P','Q','J','M')} for f in protocol['fits']}
        for f in protocol['fits']:
            assert per_fit[f]==report['domains'][domain]['per_fit'][str(f)]
        for b in ('C','P','Q'):
            d=np.asarray([per_fit[f]['J']-per_fit[f][b] for f in protocol['fits']])
            interval=d.mean()+np.array([-1,1])*t.ppf(1-.05/18,4)*d.std(ddof=1)/np.sqrt(5)
            assert np.max(np.abs(interval-np.asarray(report['domains'][domain]['contrasts']['J_minus_'+b]['familywise_95_interval'])))<1e-15
        contrast=np.array([per_fit[f]['J']-per_fit[f]['M'] for f in protocol['fits']])
        interaction=np.array([per_fit[f]['J']-per_fit[f]['P']-per_fit[f]['Q']+per_fit[f]['C'] for f in protocol['fits']])
        extended[domain]=dict(J_minus_M=dict(mean=float(contrast.mean()),per_fit=contrast.tolist(),
            posthoc_twelve_contrast_familywise95=(contrast.mean()+np.array([-1,1])*t.ppf(1-.05/24,4)*contrast.std(ddof=1)/np.sqrt(5)).tolist()),
            interaction=dict(per_fit=interaction.tolist(),mean=float(interaction.mean()),positive_count=int((interaction>0).sum())),
            cost_break_even={})
        for b in ('C','M'):
            delta_u=float(np.mean([x['arms']['J']['utility']-x['arms'][b]['utility'] for x in group]))
            extended[domain]['cost_break_even']['J_vs_'+b]={}
            for n in ('1','10','100'):
                delta_cpu=float(np.mean([x['arms']['J']['amortized_total_cpu_seconds'][n]-x['arms'][b]['amortized_total_cpu_seconds'][n] for x in group]))
                extended[domain]['cost_break_even']['J_vs_'+b][n]=dict(delta_utility=delta_u,delta_cpu_seconds=delta_cpu,
                    utility_units_per_cpu_second=delta_u/delta_cpu if delta_cpu>0 else None)
        for x in group:
            cold=x['cold_compile']['full_cold_preparation_cpu_seconds']+x['table_serialization']['cpu_seconds']
            for arm,a in x['arms'].items():
                measured=np.mean([e['policy_cpu_seconds'] for e in a['episodes']])
                assert abs(a['mean_resident_execution_cpu_seconds']-measured)<1e-14
                for n,cpu in a['amortized_total_cpu_seconds'].items():
                    assert abs(cpu-((cold/int(n) if arm in ('J','Q') else 0)+measured))<1e-14
    ctx=p.load_context(inputs/'frozen_joint')
    old={x['fit']:x for x in load(inputs/'history/OLD_CONTINUATION_HEADS.json.gz')['fits']}
    worlds=load(evidence/'WORLDS_BEFORE_SCORING.json.gz')
    selected=[]
    for f in protocol['fits']:
        artifact=load(inputs/f'inputs/fit_{f}/model_renewal/model.json')
        artifact['network']['w2']=old[f]['network_w2'];artifact['network']['b2']=old[f]['network_b2']
        model=ctx.NumpyPolicy(artifact);head=ctx.head(artifact)
        for domain in protocol['domains']:
            public=worlds[f'{f}_{domain}'][0]['public']
            table,compile_receipt,own=p.compile_own(ctx,model,public,3000)
            truth=ctx.Oracle(public,ctx.law,model.confusion)
            row=next(x for x in allrows if x['world_id']==public['id'])
            for arm in ('C','P','Q','J','M'):
                if arm in ('C','P','J'):
                    wp=p.WorldPolicy(ctx,public,model,table if arm=='J' else None)
                    evaluated=p.evaluate(ctx,public,wp,head,'head' if arm=='C' else arm,truth)
                else:
                    evaluated=p.evaluate(ctx,public,ScoreAdapter(Scores(ctx,public,model,arm,table if arm=='Q' else None)),head,'head',truth)
                error=abs(evaluated['utility']-row['arms'][arm]['utility'])
                assert error<1e-12,(public['id'],arm,error)
                selected.append(dict(world_id=public['id'],arm=arm,original_utility=row['arms'][arm]['utility'],pinned_evaluator_utility=evaluated['utility'],error=error))
    result=dict(schema='wsp-shift-verification-v1',rows=240,all_raw_arithmetic_pass=True,
        selected_replays=selected,selected_worlds=15,selected_arm_replays=75,
        max_selected_replay_error=max(x['error'] for x in selected),extended_descriptive_results=extended,
        posthoc_note='J versus M intervals were not a frozen primary comparison; Bonferroni twelve includes the nine primary contrasts and three J-M comparisons. They are explicitly post hoc. Interaction signs are descriptive, not an adoption test.',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),cpu_seconds=time.process_time()-started,wall_seconds=time.perf_counter()-wall)
    payload=json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n'
    with output.open('x') as out:out.write(payload)
    print(json.dumps({k:v for k,v in result.items() if k not in ('selected_replays','extended_descriptive_results')},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for key in ('inputs','evidence','output'):parser.add_argument('--'+key,type=Path,required=True)
    a=parser.parse_args();main(a.inputs,a.evidence,a.output)
