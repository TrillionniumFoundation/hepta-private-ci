"""P1 factorial attribution from actual (synthetic-task) CPU train receipts.

Design 2^3 arms, within-seed identical initialization and data. It *does not*
match feature FLOPs, time, joules or hyperparameter tuning budget. p values are
exploratory sign-flip diagnostics with only 2-3 seeds, not confirmatory evidence.
Global Holm across every task*contrast family protects against arm cherry-pick.
"""
from __future__ import annotations
from collections import defaultdict
import hashlib
import itertools
import json
import math
from pathlib import Path
from fair_ablation import ARMS
from factorial_evidence import CONTRASTS,exact_two_sided_signflip

TASKS=('overwrite_reset','irregular_time','mqar','long_range','selective_copy','regeneration')


def _sign(a, contrast):
    selected=set() if a=='control' else set(a.split('+'))
    subset=set(contrast.split('+'))
    return 1 if (len(selected&subset)-len(subset))%2==0 else -1


def estimate(data_by_task:dict[str,dict]):
    diagnostics=[]
    contrast_rows=[]
    for task,raw in data_by_task.items():
        seeds=raw['seeds']
        if len(seeds)!=len(set(seeds)) or not seeds:
            raise ValueError('missing/duplicate seed ids')
        rows={(r['seed'],r['arm']):r for r in raw['rows']}
        expected={(seed,arm) for seed in seeds for arm in ARMS}
        if len(rows)!=len(raw['rows']) or set(rows)!=expected:
            raise ValueError('incomplete or duplicate factorial rows')
        for seed in seeds:
            cohort=[rows[seed,arm] for arm in ARMS]
            for field in ('initial_parameters_sha256','parameter_count','train_set_sha256',
                          'holdout_set_sha256','training_steps','train_tokens'):
                if len({r[field] for r in cohort})!=1:
                    raise ValueError('unmatched data/model/step: '+field)
        for contrast in CONTRASTS:
            effects=[]
            for seed in seeds:
                # Standard factorial effect: mean(on sign) - mean(off sign),
                # equivalent to sum(sign*quality)/4 with 8 arms.
                contrasts=[_sign(arm,contrast)*rows[seed,arm]['holdout_accuracy'] for arm in ARMS]
                effects.append(sum(contrasts)/4)
            p=exact_two_sided_signflip(effects)
            contrast_rows.append({'task':task,'contrast':contrast,'seed_ids':seeds,
                                  'seed_effects':effects,'mean_effect':sum(effects)/len(effects),
                                  'unadjusted_two_sided_signflip_p':p,
                                  'full_compute_matched':False,
                                  'confirmatory':False})
        diagnostics.append({'task':task,'seeds':len(seeds),
                            'heldout_split_different_from_train':True,
                            'initial_weights_params_data_steps_paired':True,
                            'feature_FLOPs_matched':False,
                            'true_physical_energy_meter':False})
    # Familywise multiplicity across ALL 6 tasks and ALL 7 factorial effects.
    ordered=sorted(range(len(contrast_rows)),key=lambda i:contrast_rows[i]['unadjusted_two_sided_signflip_p'])
    prev=0.
    for k,i in enumerate(ordered):
        value=contrast_rows[i]['unadjusted_two_sided_signflip_p']
        adjusted=min(1.,max(prev,(len(ordered)-k)*value))
        contrast_rows[i]['holm_across_tasks_and_contrasts']=adjusted
        prev=adjusted
    return {'scope':'actually trained small CPU surrogate on synthetic tasks',
            'n_tasks':len(data_by_task),'n_rows':sum(len(r['rows']) for r in data_by_task.values()),
            'factorial_effect_count':len(contrast_rows),
            'main_pair_triple_factorial_effects':contrast_rows,
            'source_design_diagnostics':diagnostics,
            'global_familywise_alpha':0.05,
            'any_holm_significant':any(v['holm_across_tasks_and_contrasts']<.05 for v in contrast_rows),
            'all_arms_equally_tuned_and_compute_matched':False,
            'original_HCSN_kernel_tested':False,
            'attribution_gate':'DENY','production_evidence_accepted':False}


def main():
    root=Path(__file__).resolve().parent
    data={t:json.loads((root/'reports'/f'p1_p2_{t}.json').read_text()) for t in TASKS}
    report=estimate(data)
    path=root/'reports'/'p1_v4_42_exploratory_factorial_effects.json'
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(f'Actual trained factorial {report["n_rows"]} rows, {report["factorial_effect_count"]} effects; Holm significant: {report["any_holm_significant"]}')
    print('Gate: ',report['attribution_gate'])

if __name__=='__main__':main()
