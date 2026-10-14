"""Independent retrospective Encoder x Head joint comparison of two real stems.

No original Head optimizer, pretrained loading or output producer imports.
Each existing E2 source is independently weight-replayed before comparison.
Identical publisher rows and full three-seed trajectories are paired by case.
These are *not* prospectively observed NDU or independent source families.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np

from experiments.shared_stem_cell.e2_budget_review import review_sweep as review_mmbert
from experiments.shared_stem_cell.e2_modern_review import review_sweep as review_modern
from experiments.shared_stem_cell.preflight_review import checked_bytes, require
from experiments.shared_stem_cell.wire import canonical, decode, sha, write_once

SCHEMA = 'hepta.stem.e1e2-paired-retrospective.v1'
BUDGETS = (2048, 8192, 16384, 65536, 262144)
SEEDS = (11, 23, 47)
BOOTSTRAP_SEED = 20261014
N_BOOTSTRAP = 4000


def _probabilities(p):
    require(type(p) is list and len(p) == 4 and
            all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in p)
            and abs(math.fsum(p)-1) <= 1e-5, 'invalid paired model probability')
    return p


def _predictions(packet: dict, truth: dict) -> dict:
    require(type(packet) is dict and type(packet.get('predictions')) is list,
            'complete pre-sealed E2 packet required')
    seen = {}
    for p in packet['predictions']:
        require(type(p) is dict and set(p) == {
            'seed', 'ceiling', 'cell', 'role', 'case_id', 'scope', 'split', 'group',
            'input_sha256', 'probabilities'
        }, 'unexpected E2 prediction shape')
        if p['split'] != 'holdout' or p['role'] != 'trained':
            continue
        case = truth.get(p['case_id'])
        require(case is not None and p['role'] == 'trained' and p['seed'] in SEEDS
                and p['ceiling'] in BUDGETS and p['cell'] == case['cell']
                and p['scope'] == case['scope'] and p['group'] == case['group']
                and p['input_sha256'] == sha(canonical([case['scope'], case['text']])),
                'model prediction did not correspond to same original case')
        key = (p['ceiling'], p['seed'], p['case_id'])
        require(key not in seen, 'duplicate E1/E2 paired prediction')
        seen[key] = _probabilities(p['probabilities'])
    require(set(seen) == {(b, seed, cid) for b in BUDGETS for seed in SEEDS for cid in truth},
            'incomplete registered budget x seed x case pair')
    return seen


def paired_statistics(before: dict, after: dict, truth: dict,
                      *, replicates=N_BOOTSTRAP) -> list[dict]:
    """One whole original case (with all three seeds) per resampling draw."""
    require(type(replicates) is int and 1000 <= replicates <= 10000,
            'bounded preregistered bootstrap count required')
    require(type(truth) is dict and len(truth) == 32 and
            len({row['group'] for row in truth.values()}) == 32,
            'fixed unique publisher source identifiers required')
    expected = {(b, seed, cid) for b in BUDGETS for seed in SEEDS for cid in truth}
    require(set(before) == set(after) == expected, 'incomplete E1/E2 comparison grid')
    cases = sorted(truth)
    output = []
    familywise_alpha = .05 / len(BUDGETS)
    for b in BUDGETS:
        deltas, brier_deltas, wins, losses, ties = [], [], 0, 0, 0
        original_correct = modern_correct = 0
        for cid in cases:
            correct_diffs = []
            squared_diffs = []
            label = truth[cid]['label']
            for seed in SEEDS:
                p = np.asarray(_probabilities(before[b, seed, cid]), dtype=np.float64)
                q = np.asarray(_probabilities(after[b, seed, cid]), dtype=np.float64)
                gold = np.zeros(4, dtype=np.float64)
                gold[label] = 1
                a = int(p.argmax() == label)
                z = int(q.argmax() == label)
                wins += int(z > a)
                losses += int(a > z)
                ties += int(a == z)
                original_correct += a
                modern_correct += z
                correct_diffs.append(z-a)
                squared_diffs.append(float(((q-gold)**2).sum() - ((p-gold)**2).sum()))
            # Preserve complete correlated seed trajectory for the same case.
            deltas.append(sum(correct_diffs)/len(SEEDS))
            brier_deltas.append(sum(squared_diffs)/len(SEEDS))
        rng = np.random.default_rng(BOOTSTRAP_SEED + b)
        draws = np.empty(replicates, dtype=np.float64)
        values = np.asarray(deltas, dtype=np.float64)
        for i in range(replicates):
            draws[i] = values[rng.integers(0,len(cases),size=len(cases))].mean()
        lower, upper = np.quantile(draws, [familywise_alpha/2, 1-familywise_alpha/2])
        lo, hi = np.quantile(draws, [.025, .975])
        output.append({
            'head_budget_ceiling': b, 'paired_original_cases':len(cases),
            'repeated_seed_trajectories':len(SEEDS),
            'mmbert_correct_over_three_seeds':original_correct,
            'modernbert_correct_over_three_seeds':modern_correct,
            'modern_only_correct':wins,'mmbert_only_correct':losses,
            'correctness_ties':ties,
            'modern_minus_mmbert_accuracy':float(values.mean()),
            'modern_minus_mmbert_brier':float(np.mean(brier_deltas)),
            'retrospective_bootstrap_95': [float(lo),float(hi)],
            'bonferroni_five_budget_95': [float(lower),float(upper)],
            'apparent_familywise_nonzero_contrast':bool(lower>0 or upper<0),
            'external_source_family_independence_verified':False,
        })
    return output


def audit(mm_manifest:Path,mm_producer:Path,mm_report_sha256:str,mm_sweep:Path,
          modern_manifest:Path,modern_producer:Path,modern_report_sha256:str,
          modern_sweep:Path) -> dict:
    mm = review_mmbert(mm_manifest,mm_producer,mm_report_sha256,mm_sweep)
    modern = review_modern(modern_manifest,modern_producer,modern_report_sha256,modern_sweep)
    for result in (mm,modern):
        require(result['physical_head_checkpoint_count']==60 and
                result['independently_replayed_prediction_vectors']==1920 and
                result['production_accepted'] is False and
                result['future_ndu_evaluated'] is False,
                'real checkpoint-replayed E2 input required')
    before_plan = decode(checked_bytes(mm_manifest))
    after_plan = decode(checked_bytes(modern_manifest))
    require(before_plan['model']['model_id']=='jhu-clsp/mmBERT-small'
            and after_plan['model']['model_id']=='answerdotai/ModernBERT-base'
            and after_plan['model']['revision']=='fa3113d09d6dacfe5528708803dd92a62240237a',
            'registered physical Encoder pair differs')
    require(set(before_plan) == set(after_plan) and all(
        before_plan[k]==after_plan[k] for k in before_plan if k!='model'),
        'model arms received different experimental training plans')
    mm_data=checked_bytes(mm_manifest.parent/before_plan['dataset']['path'],
                          before_plan['dataset']['sha256'])
    modern_data=checked_bytes(modern_manifest.parent/after_plan['dataset']['path'],
                              after_plan['dataset']['sha256'])
    require(mm_data==modern_data, 'paired experiments did not use identical dataset bytes')
    rows=[decode(line) for line in mm_data.splitlines()]
    truth={r['case_id']:r for r in rows if r['split']=='holdout'}
    require(len(truth)==32 and len({r['group'] for r in truth.values()})==32,
            'original retrospective cohort mismatch')
    mm_run=decode(checked_bytes(mm_sweep/'run.json'))
    modern_run=decode(checked_bytes(modern_sweep/'run.json'))
    require(mm_run['feature_width']==384 and modern_run['feature_width']==768
            and mm_run['budgets']==modern_run['budgets']==list(BUDGETS)
            and mm_run['seeds']==modern_run['seeds']==list(SEEDS)
            and mm_run['train_steps']==modern_run['train_steps']==20
            and mm_run['training_batch_size']==modern_run['training_batch_size']==16
            and mm_run['architecture']==modern_run['architecture']=='factorized_tanh_no_dense_base',
            'mismatched budget/seed/optimizer settings')
    mm_work={(a['seed'],a['ceiling'],a['cell']):a for a in mm_run['artifacts']}
    modern_work={(a['seed'],a['ceiling'],a['cell']):a for a in modern_run['artifacts']}
    require(set(mm_work)==set(modern_work)=={(s,b,c) for s in SEEDS for b in BUDGETS for c in (0,1)},
            'missing physical seeded Cell arm')
    for key in mm_work:
        left,right=mm_work[key],modern_work[key]
        require(left['minibatch_sha256']==right['minibatch_sha256']
                and left['training_steps']==right['training_steps']==20
                and left['examples_processed']==right['examples_processed']==320
                and left['parameters']<=key[1] and right['parameters']<=key[1],
                'unfair per-Cell optimizer work or sample stream')
    def packet(sweep,run):
        return decode(checked_bytes(sweep/'predictions.json',run['predictions_sha256']))
    mm_predictions=_predictions(packet(mm_sweep,mm_run),truth)
    modern_predictions=_predictions(packet(modern_sweep,modern_run),truth)
    contrasts=paired_statistics(mm_predictions,modern_predictions,truth)
    for row in contrasts:
        ceiling=row['head_budget_ceiling']
        mm_counts={v['parameters'] for k,v in mm_work.items() if k[1]==ceiling}
        modern_counts={v['parameters'] for k,v in modern_work.items() if k[1]==ceiling}
        require(len(mm_counts)==len(modern_counts)==1,
                'actual per-budget parameter counts differ across Cells/seeds')
        row['mmbert_actual_parameters_per_cell']=next(iter(mm_counts))
        row['modern_actual_parameters_per_cell']=next(iter(modern_counts))
    mm_report=decode(checked_bytes(mm_producer/'report.json',mm_report_sha256))
    modern_report=decode(checked_bytes(modern_producer/'report.json',modern_report_sha256))
    for report in (mm_report,modern_report):
        peak=report.get('process_lifetime_peak_rss_bytes')
        require(peak is None or type(peak) is int and 0<=peak<2**63,
                'invalid process lifetime peak RSS observation')
    # This is a descriptive posterior diagnostic, not NDU-based model selection.
    return {'schema':SCHEMA,
        'original_dataset_sha256':sha(mm_data),
        'baseline_report_sha256':mm_report_sha256,
        'candidate_report_sha256':modern_report_sha256,
        'baseline_sweep_sha256':sha(checked_bytes(mm_sweep/'run.json')),
        'candidate_sweep_sha256':sha(checked_bytes(modern_sweep/'run.json')),
        'full_physical_checkpoint_count_each':60,
        'full_independent_prediction_vectors_each':1920,
        'original_paired_holdout_items':32,
        'mmbert_process_lifetime_peak_rss_bytes':mm_report.get('process_lifetime_peak_rss_bytes'),
        'modern_process_lifetime_peak_rss_bytes':modern_report.get('process_lifetime_peak_rss_bytes'),
        'physical_peak_is_isolated_per_head_arm':False,
        'target_host_peak_and_energy_independently_verified':False,
        'per_cell_sample_stream_identical_across_stems':True,
        'same_training_algorithm_and_steps_claimed':True,
        'per_budget_results':contrasts,
        'five_registered_compatible_budgets':list(BUDGETS),
        'independent_source_family_samples_verified':False,
        'retrospective_publisher_partition_not_future':True,
        'five_head_budgets_both_stems_executed':True,
        'all_four_registered_e1_stems_executed':False,
        'Laya_comparison_completed':False,
        'signed_future_NDU_verified':False,
        'research_winner_selected':False,
        'production_accepted':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for prefix in ('mmbert','modern'):
        ap.add_argument('--'+prefix+'-manifest',required=True,type=Path)
        ap.add_argument('--'+prefix+'-producer',required=True,type=Path)
        ap.add_argument('--'+prefix+'-report-sha256',required=True)
        ap.add_argument('--'+prefix+'-sweep',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    x=ap.parse_args()
    v=audit(x.mmbert_manifest,x.mmbert_producer,x.mmbert_report_sha256,x.mmbert_sweep,
            x.modern_manifest,x.modern_producer,x.modern_report_sha256,x.modern_sweep)
    x.output.parent.mkdir(parents=True,exist_ok=True)
    write_once(x.output,v)

if __name__=='__main__':main()
