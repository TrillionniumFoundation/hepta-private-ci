"""Freeze the C2 reporting rules without reading active fits or confirmation data."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


ROOT = Path('/workspace/scratch/c385a7439f8e')
DEST = ROOT / 'c2-resource-analysis-plan-v1'


def identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def save(name, value):
    with (DEST / name).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def main():
    wall, cpu = time.perf_counter(), time.process_time()
    DEST.mkdir(exist_ok=False)
    repo = ROOT / 'hcsn-repo'
    source_files = [
        repo/'qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/resource-analysis-v1/PLAN.json',
        repo/'qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/resource-analysis-v1/output-v1/RESULT.json',
        repo/'qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/resource-analysis-v1/output-v1/POINTS.json',
        repo/'qualification/hcsn_differentiable/evidence/p0p5-resource-replay-20261110/resource-analysis-v1/analyze_resources.py',
        repo/'qualification/hcsn_differentiable/evidence/p0p5-c2-launch-20261110/decision/DECISION.json',
        ROOT/'c2-terminal-independent-auditor-program-v1.zip',
        ROOT/'c2-terminal-independent-auditor-v1/MANIFEST.json',
    ]
    before = {str(p): identity(p) for p in source_files}
    plan = {
        'schema': 'c2-resource-analysis-reporting-plan-v1',
        'status': 'preparation_only_not_executed',
        'frozen_utc': datetime.now(timezone.utc).isoformat(),
        'prospective_scope': 'Reporting rules fixed after C2 launch, its first three complete-epoch observations and the report of one candidate terminal. This is not preregistration of the experiment; complete final all-candidate outcomes are not yet available.',
        'purpose': 'Separate the original same-budget views from a longer-resource C2 terminal view, with every opportunity and cost retained.',
        'required_before_analysis': [
            'All six original C2 opportunities have immutable terminal status, or a separately reviewed terminal postmortem records missing outputs without pretending successful completion.',
            'Actual source/data/parent identities and all source-bound terminal costs are frozen.',
            'The independent terminal auditor has its external terminal receipt, complete archive identity and resource-bound assessment; internal finalized flags alone do not grant admission.',
            'Any missing, failed, over-budget or changed-source audit outcome remains explicit, not a missing seed silently dropped from a mean.',
        ],
        'fixed_inputs': before,
        'original_budget_view': {
            'cutoffs_seconds': [300, 900, 1800],
            'operation': 'Copy and verify the earlier original42 and separate C1 results without recalculating them with C2-selected hyperparameters.',
            'earlier_missing_values': 'Remain missing; no interpolation and no replacement by later scores.',
            'old_HCSN_adequacy': 'All original six remain budget-censored, even if a later C2 continuation becomes adequate.',
        },
        'longer_resource_terminal_view': {
            'population': 'All seven original cores; retain six candidates per core, all original failures, and the separate C1/C2 phase ancestry.',
            'HCSN_roster': [f'hcsn-s{seed}-lr{lr}' for seed in (101, 211, 307) for lr in ('0.001', '0.003')],
            'HCSN_selection': 'Use the independently bound first strict-best complete epoch for each of all six candidates. Select one common learning rate by the mean all-11-class D macro-F1 across seeds101/211/307; exact ties choose .001. If any candidate quality is missing or unverified, withhold the new common-LR selection and retain individual raw known results.',
            'baseline_selection': 'Use the previously independently checked original plus C1 all-candidate reports, keeping their fixed common-LR rule and inadequacy/failure statuses.',
            'reported_statistics': ['individual scores', 'mean across all three seeds', 'sample standard deviation with divisor2', 'producer adequacy', 'independently supported adequacy', 'termination reason', 'selected epoch'],
            'adequacy_gate': 'A descriptive quality value never grants adequate training. A sufficiently-trained comparison requires independently supported adequacy for every selected seed in every compared core.',
            'uncertainty': 'Three-seed SD describes initialization variability on reused D, not held-out population uncertainty or a significance test.',
            'failed_fit_rule': 'Retain independently reproducible scores as diagnostic observations where available, but never convert failed recording, missing terminal artifacts or resource censoring into an adequate successful fit.',
        },
        'time_to_quality': {
            'target_macro_F1': 0.30,
            'crossing_rule': 'First complete epoch that reaches the original target, preserving its actual cumulative charged wall. Keep before-training eligibility separate; do not mix it into the epoch-crossing definition.',
            'per_seed': 'Retain the individual first crossing or right-censoring status; do not interpolate.',
            'group_median': 'Report only when all three selected seeds have observed crossings. Otherwise report the count and individual censoring, never a successful-seed median.',
            'selection_scope': 'The longer-resource terminal common-LR view is labeled separately; it cannot change the earlier frozen original-budget choice or its original target-time result.',
        },
        'cost_accounting': {
            'wall': 'For each candidate, preserve the original complete outer process wall plus the full C1 or C2 attempt wrapper wall. Include failed diagnostics, failed starts, discarded partial updates, imports, capture, evaluation and finalization when inside that attempt scope.',
            'outer_vs_inner': 'Use one declared non-overlapping outer scope for each sum. Preserve process wall, attempt-wrapper wall, controller elapsed and calendar as separate fields; do not sum nested alternatives.',
            'tuning': 'All two-learning-rate/three-seed opportunities and historical diagnostics remain charged, including failed or inadequate candidates. A selected-checkpoint inference timer is not training cost.',
            'CPU': 'C2 per-child wait4 is exact for that child; the original post-report exit CPU was not fully measured. Any cumulative CPU that depends on it remains a lower bound or unknown with named missing components.',
            'memory': 'Report observed per-attempt peak RSS and the maximum across a candidate chain. Do not sum peaks as if simultaneous, call it GPU memory, or claim it was measured exactly at the quality crossing.',
            'calendar': 'C1 and C2 are later calendar phases. Explicitly retain different concurrency and concurrent independent auditing; do not claim an idle or controlled-throughput host.',
            'independent_audits_and_transport': 'Itemize separately from fit costs; failed transfers and preflight costs remain, with unknown CPU/billing stated as unknown.',
            'energy_joules': None,
            'billed_currency': None,
            'GPU_VRAM_bytes': None,
            'no_cost_refund_for_discarded_work': True,
        },
        'verification': 'One stdlib analysis over byte-bound saved metadata. Recompute confusion-matrix metrics, common-LR arithmetic and first-maximum/timing records independently; compare to the terminal auditor without calling producer admission code. Preserve any disagreement and withhold the affected aggregate.',
        'analysis_budget': {'whole_hard_wall_seconds': 120, 'workers': 1, 'threads': 1, 'peak_RSS_bytes': 536870912, 'automatic_retry': False},
        'not_authorized_by_this_plan': ['training', 'model forward or backward', 'new numerical oracle calls', 'E access', 'new seeds or learning rates', 'rewriting frozen old results', 'energy estimates from assumed power'],
        'confirmation_E_access': False,
        'scientific_admission': 'HOLD',
        'whole_training_numerical_admission': 'HOLD',
        'P5_benefit_gate': 'unchanged',
    }
    save('PLAN.json', plan)
    source = Path(__file__)
    (DEST/'freeze_source.py').write_bytes(source.read_bytes())
    assert before == {str(p): identity(p) for p in source_files}
    save('PREPARATION.json', {'scope': 'Exact prior-input hashes and fixed reporting rules only; no production C2 file, model or E data was read.',
          'main_wall_seconds': time.perf_counter()-wall, 'main_CPU_seconds': time.process_time()-cpu,
          'source_inputs_unchanged': True})
    save('MANIFEST.json', {'files': {p.name: identity(p) for p in sorted(DEST.iterdir()) if p.is_file()}})
    print(json.dumps({'plan': identity(DEST/'PLAN.json'), 'manifest': identity(DEST/'MANIFEST.json')}))


if __name__ == '__main__':
    main()
