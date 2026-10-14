"""Independent stdlib rederivation of source-wise calibration stability decisions.

Depends only on persisted records and the independent ORIGINAL FIFO source auditor.
It imports no Torch, candidate selectors, pretrained model or score functions.
Audit cannot authenticate the OS clock, external source independence, or energy.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics

from experiments.shared_stem_cell import audit_video_cpu_queue as original

POLICIES = ('1:0', '2:0', '4:0', '4:2000000', '4:8000000')
P95_LIMIT = .95
SOURCE_LIMIT = 1.05
FIRST_LIMIT = 1.5
WALL_LIMIT = 1.1


def require(flag, message):
    if not flag:
        raise ValueError(message)


def derive(arms):
    require(set(arms) == set(POLICIES), 'missing source guard calibration arm')
    reference = arms['1:0']
    require(isinstance(reference, list) and 2 <= len(reference) <= 7, 'bounded matched rounds')
    ids = reference[0]['case_ids']
    identities = [r['source_id'] for r in reference[0]['records']]
    distribution = {k:identities.count(k) for k in sorted(set(identities))}
    sufficient = len(distribution) >= 2 and min(distribution.values()) >= 4
    outcome = {}
    acceptable = []
    for name in POLICIES:
        trials = arms[name]
        require(len(trials) == len(reference), 'missing matched source rounds')
        cells = []
        for position, (run, base) in enumerate(zip(trials, reference)):
            require(run['case_ids'] == ids == base['case_ids']
                    and run['arrival_offsets_ns'] == base['arrival_offsets_ns']
                    and [r['source_id'] for r in run['records']] == identities
                    and [r['case_id'] for r in run['records']] == ids
                    and run['policy_key'] == name and run['iteration'] == base['iteration'],
                    'source identity and paired timing drift')
            source_ratios = {}
            for k in distribution:
                samples = [r['response_latency_ns'] for r in run['records'] if r['source_id'] == k]
                originals = [r['response_latency_ns'] for r in base['records'] if r['source_id'] == k]
                top = sorted(samples)[(95*len(samples)+99)//100-1]
                bottom = sorted(originals)[(95*len(originals)+99)//100-1]
                source_ratios[k] = top / max(bottom, 1)
            p95 = run['latency_p95_ns']/base['latency_p95_ns']
            first = run['first_response_ns']/base['first_response_ns']
            wall = run['whole_run_wall_ns']/base['whole_run_wall_ns']
            cells.append({'iteration': position, 'p95_ratio':p95,
                'first_response_ratio':first, 'whole_wall_ratio':wall,
                'source_p95_ratios':source_ratios,
                'passes':bool(p95 <= P95_LIMIT and first <= FIRST_LIMIT
                    and wall <= WALL_LIMIT and all(math.isfinite(x) and x <= SOURCE_LIMIT
                                                  for x in source_ratios.values()))})
        median = int(statistics.median(v['latency_p95_ns'] for v in trials))
        valid = name != '1:0' and sufficient and all(x['passes'] for x in cells)
        outcome[name] = {'paired_rounds':cells, 'median_p95_ns':median,
            'eligible':valid, 'reason':('baseline' if name=='1:0' else
                'insufficient_source_groups' if not sufficient else
                'some_paired_round_or_source_failed' if not valid else 'all_guards_pass')}
        if valid: acceptable.append(name)
    winner=min(acceptable,key=lambda k:(outcome[k]['median_p95_ns'],POLICIES.index(k))) if acceptable else '1:0'
    return {'schema':'hepta.video-arrival-source-guard.v1', 'selected_policy_key':winner,
        'qualified':acceptable, 'source_groups':distribution,'calibration_rounds':len(reference),
        'comparison':outcome,'minimum_distinct_sources':2,'minimum_cells_per_source':4,
        'max_source_p95_ratio':SOURCE_LIMIT,'max_round_p95_ratio':P95_LIMIT,
        'max_round_first_response_ratio':FIRST_LIMIT,'max_round_wall_ratio':WALL_LIMIT,
        'all_guards_are_calibration_only':True,
        'empirical_guard_not_population_certificate':True,
        'same_queue_sources_not_independent':True,
        'uses_previously_exposed_public_source_family':True,
        'production_accepted':False}


def audit(root, output):
    root, output=Path(root),Path(output)
    prior=original.audit(root,output)
    calibration=original.read(output/'calibration.json')
    selection=original.read(output/'selection.json')
    report=original.read(output/'report.json')
    require(set(selection['source_guard_by_workload']) == set(prior['audited_workloads']),
            'all source guard selections must be sealed before holdout')
    outcomes={}
    for name, trials in calibration['measurements'].items():
        expected=derive(trials)
        observed=selection['source_guard_by_workload'][name]
        require(observed==expected, 'source-guard selection or paired calibration forged')
        winner=expected['selected_policy_key']
        info=report['summaries'][name]
        opts=info['by_policy']
        scalar=opts['1:0']['p95_response_median_ns']
        ratio=scalar/opts[winner]['p95_response_median_ns']
        require(info['source_guard_selected_policy_key']==winner
                and math.isclose(info['source_guard_selected_vs_scalar_p95_ratio'], ratio,
                                 rel_tol=0,abs_tol=1e-12)
                and info['source_guard_selected_is_faster_p95']==
                      (opts[winner]['p95_response_median_ns']<scalar),
                'source guard heldout latency or policy summary forged')
        outcomes[name] = {'original_median_winner':info['selected_policy_key'],
            'conservative_source_winner':winner,
            'two_source_guard_sufficient':len(expected['source_groups'])>=2,
            'exploratory_heldout_p95_ratio':ratio}
    return {'schema':'hepta.video-arrival-source-guard-independent-audit.v1',
        'by_workload':outcomes,'original_audit':prior,
        'external_hardware_clock_attested':False,'new_unseen_source_data':False,
        'clip_pretrained_executed':False,'production_accepted':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    a=parser.parse_args()
    print(json.dumps(audit(a.root,a.output),sort_keys=True))
