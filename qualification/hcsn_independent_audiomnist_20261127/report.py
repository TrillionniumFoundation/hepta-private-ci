"""Combine immutable per-seed cold scores, budgets and costs, preserving all comparisons."""
import argparse
import json
from pathlib import Path
import numpy as np


def main():
    p=argparse.ArgumentParser()
    for k in ('primary','site','models','data','out'):p.add_argument(k,type=Path)
    a=p.parse_args();summ=json.loads(a.primary.read_bytes());site=json.loads(a.site.read_bytes());data=json.loads((a.data/'data.json').read_bytes())
    seeds=summ['seeds'];rows={};targets={};costs={s:json.loads((a.models/f'parent_{s}.json').read_bytes())['common_prep_wall'] for s in seeds}
    for arm in ['keep','direct','bp','lora','wrong']:
        for t in ([0] if arm=='keep' else summ['budgets']):
            keys=[f'{arm}_{s}_{t}' for s in seeds];cold=[summ['per_model'][k] for k in keys]
            info={} if arm=='keep' else summ['vs_keep'][f'{arm}_{t}']
            times=[0. if arm=='keep' else summ['calibration_costs'][k]['wall'] for k in keys]
            # Wall is the paid budget up to stopping the optimizer, not the time of its
            # best selected edit. Prepare the common raw corpus once per quoted pipeline.
            wall=[data['wall_seconds']+costs[s]+w+c['cold_wall'] for s,w,c in zip(seeds,times,cold)]
            rows[f'{arm}_{t}']={**info,'new_accuracy':float(np.mean([o['new']['accuracy'] for o in cold])),'old_accuracy':float(np.mean([o['old']['accuracy'] for o in cold])),'new_brier':float(np.mean([o['new']['brier'] for o in cold])),'old_brier':float(np.mean([o['old']['brier'] for o in cold])),'optimizer_wall':times,'pipeline_wall':wall,'pipeline_wall_mean':float(np.mean(wall)),'new_seed_accuracy':[o['new']['accuracy'] for o in cold],'old_seed_accuracy':[o['old']['accuracy'] for o in cold],'hidden_change_ranks':([0]*3 if arm=='keep' else [site[str(s)]['write_site'][f'{arm}_{t}']['rank'] for s in seeds])}
        if arm!='keep':
            good=[t for t in summ['budgets'] if rows[f'{arm}_{t}']['confirmatory_all_parents']]
            targets[arm]=None if not good else {'earliest_eligible_cpu_budget':good[0],'mean_end_to_end_measured_wall':rows[f'{arm}_{good[0]}']['pipeline_wall_mean']}
    z={'scope':{'target_speakers':12,'source_speakers':6,'unique_target':summ['new_unique_recordings'],'unique_source':summ['old_unique_recordings'],'score_entries':summ['total_class_scores'],'shared_waveform_processing_wall':data['wall_seconds'],'per_parent_common_wall':costs,'wall_timing':'waveform conversion + common parent/keys + optimizer full stopped run + sealed model inference including score file. Python interpreter startup, corpus download and separate scientific reporting excluded.'},'arms':rows,'direct_paired':summ['paired_arms'],'time_to_joint_registered_endpoint':targets}
    a.out.write_text(json.dumps(z,indent=2,sort_keys=True,allow_nan=False)+'\n')


if __name__=='__main__':main()
