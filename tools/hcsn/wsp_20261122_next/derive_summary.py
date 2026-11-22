"""Post-run arithmetic only: no model evaluation, fitting, sampling or selection."""
from pathlib import Path
import json
import hashlib
import statistics
import time

ROOT=Path(__file__).resolve().parent
RUN=ROOT/'run'


def load(path):return json.loads(Path(path).read_text())
def pin(path):
    path=Path(path);b=path.read_bytes()
    return dict(path=str(path.resolve()),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())


def main():
    started=time.process_time()
    protocol=load(ROOT/'PROTOCOL_FROZEN.json')
    sources={phase:load(RUN/f'{phase}_attempt001/output/RESULTS.json')
             for phase in ('generation','selection','confirmation','verification')}
    assert sources['verification']['status']=='PASS'
    processes={phase:load(RUN/f'{phase}_attempt001/PROCESS.json') for phase in sources}
    assert all(p['status']=='COMPLETED' for p in processes.values())
    fits={}
    totals={family:dict(CPU_seconds=0.,objective_calls=0,gradient_calls=0,readout_forward_rows=0,
                        complete_policy_DPs=0,proposal_slots=0) for family in ('DIRECT','BP')}
    oracle_means={name:[] for name in ('KEEP','Q_ORACLE','B_ORACLE','BOTH_ORACLE')}
    for fit in protocol['fit_ids']:
        gen=sources['generation']['fits'][str(fit)]
        select=sources['selection']['fits'][str(fit)]
        confirm=sources['confirmation']['fits'][str(fit)]
        reports=load(gen['generation_pin']['path'])['optimizer_reports']
        oracles=load(gen['oracle_pin']['path'])['means']
        for name in oracle_means:oracle_means[name].append(oracles[name]['utility'])
        for family in totals:
            totals[family]['CPU_seconds']+=reports[family]['CPU_seconds']
            totals[family]['proposal_slots']+=reports[family]['slots_completed']
            for key,value in reports[family]['counters'].items():totals[family][key]+=value
        fits[str(fit)]=dict(
            original_model_pin=protocol['fits'][str(fit)]['model'],
            GEN={a:gen['GEN_means'][a] for a in ('KEEP','DIRECT','BP')},
            SELECT={a:select['means']['iid'][a] for a in ('KEEP','DIRECT','BP')},
            confirmation={d:{a:confirm['means'][d][a] for a in ('KEEP','DIRECT','BP')} for d in ('iid','ood')},
            choices=select['choices'],gates=select['gates'],
            direct_actual_norm=gen['models']['DIRECT']['exact_norm']['numeric_delta_norm'],
            gradient_actual_norm=gen['models']['BP']['exact_norm']['numeric_delta_norm'],
            direct_primary_alias=gen['models']['DIRECT']['canonical_model_sha256']==gen['models']['KEEP']['canonical_model_sha256'],
            direct_largest_proposal_minus_retained=max(x['objective'] for x in reports['DIRECT']['proposals'])-reports['DIRECT']['returned_best_objective'],
            raw_soft_objective={family:reports[family]['returned_best_objective'] for family in reports},
            GEN_oracle_values={a:oracles[a]['utility'] for a in oracles},
            representation_control=select['permutation_control'])
    oracle_values={k:statistics.mean(v) for k,v in oracle_means.items()}
    gap=oracle_values['BOTH_ORACLE']-oracle_values['KEEP']
    aggregate={}
    for phase,domain in [('GEN',None),('SELECT',None),('confirmation','iid'),('confirmation','ood')]:
        rows=[f[phase] if domain is None else f[phase][domain] for f in fits.values()]
        aggregate[phase if domain is None else phase+'_'+domain]={a:dict(
            utility=statistics.mean(r[a]['utility'] for r in rows),
            mean_delta=statistics.mean(r[a]['delta_original'] for r in rows),
            minimum_world_delta=min(r[a]['delta_original_min'] for r in rows)) for a in ('KEEP','DIRECT','BP')}
    unique=set(protocol['known_schedule_hashes'])
    schedule_counts={}
    for phase in ('selection','confirmation'):
        worlds=load(RUN/f'{phase}_attempt001/output/WORLDS_FROZEN.json')
        keys=[w['schedule_sha256'] for fit in worlds['groups'].values() for domain in fit.values() for w in domain['worlds']]
        assert len(keys)==80 and len(set(keys))==80 and not set(keys)&unique
        unique.update(keys);schedule_counts[phase]=len(keys)
    summary=dict(schema='hepta-value-sensitive-result-summary-v1',status='COMPLETED_NO_UPDATE',
        protocol_pin=pin(ROOT/'PROTOCOL_FROZEN.json'),fits=fits,aggregate_raw_arms=aggregate,
        optimizer_costs=totals,GEN_oracle_equal_checkpoint_means=oracle_values,
        GEN_oracle_opportunity_recovery={a:(oracle_values[a]-oracle_values['KEEP'])/gap for a in ('Q_ORACLE','B_ORACLE','BOTH_ORACLE')},
        selected_contrasts=sources['confirmation']['contrasts'],improvement_claim=sources['confirmation']['improvement_claim'],
        schedule_counts=schedule_counts,historical_unique_schedules=3796,final_unique_schedules=len(unique),
        independent_verification=sources['verification']['counts'],
        process_costs=processes,total_child_CPU_seconds=sum(x['child_CPU_seconds'] for x in processes.values()),
        total_supervisor_CPU_seconds=sum(x['supervisor_CPU_seconds'] for x in processes.values()),
        total_wall_seconds=sum(x['wall_seconds'] for x in processes.values()),
        historical_reused_preparation_CPU_seconds=sum(x['historical_shared_preparation_CPU_seconds'] for x in protocol['fits'].values()),
        mathematics_admission=load(ROOT/'math_attempt001/RESULTS.json'),metadata_CPU_seconds=protocol['metadata_preparation_CPU_seconds'],
        source_results={k:pin(RUN/f'{k}_attempt001/output/RESULTS.json') for k in sources},
        scope='Post-run aggregate; all scientific candidates and choices remained fixed. Zero direct delta makes its dose/direction controls KEEP aliases, not positive causal evidence.',
        arithmetic_CPU_seconds=time.process_time()-started)
    with (ROOT/'RESULT_SUMMARY.json').open('x') as stream:
        json.dump(summary,stream,indent=2);stream.write('\n')
    print(json.dumps({k:summary[k] for k in ('status','aggregate_raw_arms','optimizer_costs','GEN_oracle_opportunity_recovery',
        'independent_verification','total_child_CPU_seconds','total_supervisor_CPU_seconds','historical_reused_preparation_CPU_seconds')}))


if __name__=='__main__':main()
