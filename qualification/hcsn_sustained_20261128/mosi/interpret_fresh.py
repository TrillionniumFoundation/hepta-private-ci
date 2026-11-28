"""Reduce the verified MOSI result to the predeclared quality, uncertainty, and speed contrasts."""
import argparse
import hashlib
import json
from pathlib import Path


def report(summary):
    data=json.loads(summary.read_text())
    scope=data['scope']
    assert scope['real_fit_jobs']==36 and scope['cases']==686 and scope['videos']==31
    assert scope['bootstrap_repetitions']==10000
    panel={}
    for arm,curve in data['curves'].items():
        if '180' not in curve:continue
        stat=curve['180']
        panel[arm]={k:stat[k] for k in ('parameter_count','video_mae','pooled_mae','pooled_rmse','pearson_mean',
                      'sign_acc_nonzero','end_to_end_upper_wall','by_seed_mae','by_seed_wall')}
    pairs={}
    for name,stat in data['paired_fp_h'].items():
        if not name.endswith('-180'):continue
        arm=name.removeprefix('64-fp_h_minus_').removesuffix('-180')
        pairs[arm]={'delta_MAE':stat['mae_delta'],'CI95':stat['two_way_ci95'],
                    'upper_within_margin_0_05':stat['two_way_ci95'][1]<=.05}
    sens={}
    for key,stat in data['perturbation_mae_minus_intact']['64-fp_h'].items():
        sens[key]={'delta_MAE':stat['mae_delta'],'CI95':stat['two_way_ci95']}
        if 'familywise_bonferroni9_ci' in stat:sens[key]['adjusted_CI']=stat['familywise_bonferroni9_ci']
    internal={}
    for arm in ('64-bp_h','64-transformer','0-raw_all','0-raw_text','64-fp_h_text','64-fp_h_av'):
        values={}
        for goal,left in data['time_to_external_quality']['64-fp_h'].items():
            right=data['time_to_external_quality'][arm][goal]
            if left is not None and right is not None:
                values[goal]={'FP_H_wall_upper':left['mean_end_to_end_upper_wall'],'other_wall_upper':right['mean_end_to_end_upper_wall'],
                   'other_over_FP_H':right['mean_end_to_end_upper_wall']/left['mean_end_to_end_upper_wall'],
                   'FP_H_rung_s':left['first_observed_prefix'],'other_rung_s':right['first_observed_prefix']}
        internal[arm]=values
    return {'summary_sha256':hashlib.sha256(summary.read_bytes()).hexdigest(),'scope':scope,'intact_180':panel,
            'paired_FP_H_minus_other_180':pairs,'FP_H_perturbations':sens,'matched_external_quality_time':internal,
            'first_gate_by_arm':data['time_to_external_quality']}


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('source',type=Path);a.add_argument('out',type=Path);op=a.parse_args()
    op.out.write_text(json.dumps(report(op.source),sort_keys=True,indent=2,allow_nan=False)+'\n')
