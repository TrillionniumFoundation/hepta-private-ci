"""Produce small, directly readable loss, quality-time, dependence, and parameter tables."""
import argparse
import json
from pathlib import Path
import statistics as st


def read(p):
    return json.loads(p.read_bytes())


def keep_effect(z):
    return {k:v for k,v in z.items() if k not in ('video_delta',)}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('work',type=Path)
    ap.add_argument('destination',type=Path)
    a=ap.parse_args();w=a.work
    raw=read(w/'result/SUMMARY.json')
    costs=read(w/'table_cost.json')['runs']
    uncached=st.median(c['process_end_to_end_wall_s'] for c in costs)
    med_cpu=st.median(c['grid_build_write_check_cpu_s'] for c in costs)
    rows={}
    for name,by_rung in raw['curves'].items():
        if '180' not in by_rung:continue
        r=by_rung['180']
        rows[name]={k:r[k] for k in ('parameter_count','video_mae','pooled_mae','pearson_mean','sign_acc_nonzero','by_seed_mae','end_to_end_upper_wall')}
        rows[name]['gates']=raw['time_to_external_quality'][name]
    comparisons={}
    for width in (64,256,1024):
        physical=f'{width}-fp_h'
        for rival in ('fp_r','random_h','bp_h','transformer','raw_all','raw_text','raw_av'):
            rid= ('0' if rival.startswith('raw_') else str(width))+'-'+rival
            ck=f'{physical}_minus_{rid}-180'
            if ck not in raw['paired_fp_h']:continue
            ep=keep_effect(raw['paired_fp_h'][ck])
            ep['upper_CI_at_most_plus_0p05']=ep['two_way_ci95'][1]<=.05
            ep['both_CI_bounds_within_plusminus_0p05']=ep['two_way_ci95'][0]>=-.05 and ep['two_way_ci95'][1]<=.05
            ep['common_attained_gates']={}
            for gate,pv in rows[physical]['gates'].items():
                rv=rows[rid]['gates'][gate]
                if not(pv and rv):continue
                psec=pv['mean_end_to_end_upper_wall'];rsec=rv['mean_end_to_end_upper_wall']
                fixed_rival_prior=uncached if rival in ('random_h','bp_h') else 0
                ep['common_attained_gates'][gate]={
                   'fp_first_prefix':pv['first_observed_prefix'],'rival_first_prefix':rv['first_observed_prefix'],
                   'fp_wall_upper_s':psec, 'rival_wall_upper_s':rsec,
                   'observed_upper_wall_ratio_rival_over_fp':rsec/psec,
                   'cold_table_counterscenario_ratio_rival_over_fp':(rsec+fixed_rival_prior)/(psec+uncached)}
            comparisons[ck]=ep
    for rival in ('fp_h_text','transformer_text','fp_h_shuffle'):
        k=f'64-fp_h_minus_64-{rival}-180'
        if k in raw['paired_fp_h']:comparisons[k]=keep_effect(raw['paired_fp_h'][k])
    perturb={k:{m:keep_effect(v) for m,v in raw['perturbation_mae_minus_intact'][k].items()} for k in ('64-fp_h','256-fp_h','1024-fp_h','64-transformer','1024-transformer','0-raw_all') if k in raw['perturbation_mae_minus_intact']}
    writes={}
    for p in sorted((w/'models').glob('*-fp_h-*.json')):
        d=read(p)
        h=d['selected']['180']
        if h:
            assert h['hidden_writes']==3 and all(z>0 for z in h['hidden_write_fro'])
            writes[p.stem]={'three_frobenius_norm_changes_against_initial':h['hidden_write_fro'],'selected_penalty':h['penalty'],'complete_candidate_count':len(d['history'])}
    receipts=[read(p) for p in sorted((w/'models').glob('*.json'))]
    held=[read(p) for p in sorted((w/'cold').glob('*.json'))]
    assert len(receipts)==len(held)==63
    fit_spent={
        'aggregate_fit_process_cpu_s_excluding_checkpoint_serialization':sum(r['fit_cpu']+r['common_process']['cpu'] for r in receipts),
        'sum_fit_job_wall_s_concurrent_jobs_not_elapsed':sum(r['fit_wall']+r['common_process']['wall']+r['serialization_wall'] for r in receipts),
        'aggregate_primary_and_sensitivity_confirmation_process_cpu_s':sum(r['total_cpu'] for r in held),
        'sum_confirmation_job_wall_s_concurrent_jobs_not_elapsed':sum(r['all_perturbations_and_save_wall'] for r in held),
        'paid_history_evaluations':sum(len(r['history']) for r in receipts),
        'actual_fit_receipts':len(receipts)}
    payload={'scope':raw['scope'],'paid_experiment_resources':fit_spent,'terminal_by_design':rows,'fp_h_contrasts':comparisons,
             'masked_and_wrong_video_mae_increase':perturb,'all_hidden_writes':writes,
             'costs':{'upstream_feature_extraction_and_training':'unmeasured, common external pretrained corpus',
                      'provided_feature_preparation_s':read(w/'data/data.json')['feature_prep_total_wall_s'],
                      'cold_start_with_full_table_separate_5run_median_wall_s':uncached,
                      'table_construction_and_validation_median_cpu_s':med_cpu,
                      'table_price_buffer_floats':costs[0]['size_scalars']['fields'],
                      'timing_definition':'per-method development-selected first successful external gates, with conservative full selection wall charged including the first evaluation after each CPU cutoff, one-time restored feature packing and cold load/predict; input downloads, supplied pretrained extractors, scientific perturbations, archival verification excluded. Cold table counterscenario charges regeneration to physical models only. All time ratios descriptive. See full receipts for exact per-seed timings.'}}
    a.destination.write_text(json.dumps(payload,indent=1,sort_keys=True,allow_nan=False)+'\n')


if __name__=='__main__':
    main()
