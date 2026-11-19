"""Immutable receipts and predeclared v2 contrasts; execution is not efficacy."""

import hashlib
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import time

import numpy as np
import torch

from generation_control import bottom_up_reference
from metrics import paired_bootstrap


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as destination:
        json.dump(value, destination, indent=2, sort_keys=True, allow_nan=False)
        destination.write('\n')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_manifest():
    files = [*HERE.parent.glob('*.py'), *HERE.glob('*.py'), HERE / 'protocol.json']
    files += [HERE / 'run_cloud.sh', ROOT / '.github/workflows/ndu-controlled-generation-v2.yml']
    hashes = {str(path.relative_to(ROOT)): digest(path)
              for path in sorted(files) if path.exists()}
    combined = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {'files': hashes, 'combined_sha256': combined}


def runtime_receipt(tier, smoke, manifest):
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    frozen = True
    for name, expected in manifest['files'].items():
        committed = subprocess.run(['git', 'show', f'{head}:{name}'], cwd=ROOT,
                                   capture_output=True, check=False)
        frozen &= (committed.returncode == 0 and
                   hashlib.sha256(committed.stdout).hexdigest() == expected)
    asserted = os.environ.get('HEPTA_EXPERIMENT_SOURCE_COMMIT')
    if asserted is not None and asserted != head:
        raise RuntimeError('launcher source commit does not match checkout')
    if not smoke and not frozen:
        raise RuntimeError('confirmation requires every source dependency committed unchanged')
    dedicated = (tier == 'dedicated-cloud' and os.environ.get('RUNNER_NAME') == 'desktop'
                 and os.environ.get('HEPTA_DEDICATED_RUNNER_VERIFIED') == '1'
                 and bool(os.environ.get('GITHUB_RUN_ID')))
    if tier == 'dedicated-cloud' and not dedicated:
        raise RuntimeError('dedicated tier requires the exact verified project launcher')
    hosted = (tier == 'hosted-cpu' and os.environ.get('GITHUB_ACTIONS') == 'true'
              and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
              and bool(os.environ.get('GITHUB_RUN_ID')))
    if tier == 'hosted-cpu' and not hosted:
        raise RuntimeError('hosted tier requires a GitHub-hosted Actions environment')
    return {'tier': tier, 'smoke_only': smoke, 'source_frozen': bool(frozen),
            'source_commit': head, 'source_manifest': manifest,
            'host': socket.gethostname(), 'platform': platform.platform(),
            'python': sys.version, 'executable': sys.executable,
            'numpy': np.__version__, 'torch': str(torch.__version__),
            'device': 'cpu', 'cuda_available': torch.cuda.is_available(),
            'cpu_count': os.cpu_count(), 'threads': torch.get_num_threads(),
            'runner_name': os.environ.get('RUNNER_NAME'),
            'github_run_id': os.environ.get('GITHUB_RUN_ID'),
            'dedicated_launcher_verified': bool(dedicated),
            'hosted_environment_asserted': bool(hosted),
            'dedicated_external_attestation': 'requires external Actions job receipt',
            'command': sys.argv, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}


def audit(planner, budgets):
    roots = [((report, -1, -1, -1), budget, 0)
             for budget in budgets for report in range(9)]
    start, cpu = time.perf_counter(), time.process_time()
    reference = bottom_up_reference(planner.model.joint, planner.loss,
                                    planner.portfolios, roots, gamma=planner.gamma,
                                    mode=planner.mode, penalty=planner.penalty,
                                    controller_cost=planner.controller_cost)
    difference, mismatch = 0.0, 0
    for state, expected in reference.items():
        actual = planner.solve(*state)
        difference = max(difference, abs(actual.value - expected.value))
        mismatch += ((actual.action, actual.portfolio, actual.depth) !=
                     (expected.action, expected.portfolio, expected.depth))
    result = {'states': len(reference), 'max_value_error': difference,
              'action_portfolio_depth_mismatches': mismatch,
              'passed': difference <= 1e-10 and mismatch == 0,
              'wall_seconds': time.perf_counter() - start,
              'process_cpu_seconds': time.process_time() - cpu,
              'selection_improvement_tolerance': 1e-12}
    if not result['passed']:
        raise AssertionError(f'independent policy audit failed: {result}')
    return result


def contrasts(retained, protocol, audits, smoke):
    rows = []
    scenarios = ('test_iid', 'correlation_shift', 'all_shared_wrong')
    baselines = [arm for arm in protocol['arms'] if arm != 'joint_ndu']
    for scenario in scenarios:
        for budget in protocol['budgets_after_initial_text']:
            candidate = retained[(scenario, budget, 'joint_ndu')]
            for baseline_name in baselines:
                baseline = retained[(scenario, budget, baseline_name)]
                result = {'scenario': scenario, 'budget': budget, 'baseline': baseline_name}
                for metric, statistic in [('loss', 'mean'), ('loss', 'cvar90'),
                                          ('quality', 'mean'), ('omission', 'mean')]:
                    result[f'{metric}_{statistic}'] = paired_bootstrap(
                        np.stack([row[metric] for row in candidate]),
                        np.stack([row[metric] for row in baseline]),
                        statistic=statistic, seed=7891, replicates=1000,
                        shared_worlds=False)
                result['mean_linear_mac_ratio'] = float(
                    np.mean([row['linear_macs'].mean() for row in candidate]) /
                    np.mean([row['linear_macs'].mean() for row in baseline]))
                result['depth_disagreement_fraction'] = float(np.mean([
                    np.mean(left['depth'] != right['depth'])
                    for left, right in zip(candidate, baseline)]))
                result['portfolio_disagreement_fraction'] = float(np.mean([
                    np.mean(left['portfolio'] != right['portfolio'])
                    for left, right in zip(candidate, baseline)]))
                rows.append(result)
    primary = next(row for row in rows if row['scenario'] == 'test_iid'
                   and row['budget'] == 12 and row['baseline'] == 'supervised_static')
    endpoint = primary['loss_cvar90']
    gates = {'cvar_reduction_at_least_0_02': endpoint['estimate'] <= -0.02,
             'cvar_ci_upper_below_zero': endpoint['ci_high'] < 0,
             'quality_noninferiority_point_margin_0_02': primary['quality_mean']['estimate'] >= -0.02,
             'linear_mac_ratio_at_most_1_05': primary['mean_linear_mac_ratio'] <= 1.05,
             'three_registered_seeds': not smoke and endpoint['n_seeds'] == 3,
             'independent_oracle_parity': all(row['passed'] for row in audits),
             'output_and_budget_contracts': True}
    return {'primary': primary, 'gates': gates, 'primary_passed': all(gates.values()),
            'eligible_confirmation': not smoke, 'contrasts': rows,
            'inference_scope': 'paired hierarchical percentile intervals; only three training seeds',
            'secondary_interval_scope': 'unadjusted descriptive exploratory intervals; only the single preregistered primary contrast is confirmatory',
            'cost_scope': 'primary MAC ratio is online dense Linear forward work, not lifecycle FLOPs'}


def report_text(results, summaries, runtime):
    primary, gates = results['primary'], results['gates']
    endpoint = primary['loss_cvar90']
    lines = ['# Controlled generation v2 result', '',
             f"Source: `{runtime['source_commit']}`. Tier: `{runtime['tier']}`.", '',
             f"Smoke only: **{runtime['smoke_only']}**. Registered primary passed: **{results['primary_passed']}**.", '',
             '## Primary comparison', '',
             'Joint NDU minus matched supervised static, IID, budget 12 after initial text.', '',
             f"CVaR90 difference: {endpoint['estimate']:.9f}; 95% CI [{endpoint['ci_low']:.9f}, {endpoint['ci_high']:.9f}].", '',
             f"Quality difference: {primary['quality_mean']['estimate']:.9f}; ideal online Linear MAC ratio: {primary['mean_linear_mac_ratio']:.6f}.", '',
             '| Gate | Passed |', '| --- | --- |']
    lines.extend(f'| {name} | {passed} |' for name, passed in gates.items())
    lines += ['', '## Per-seed IID budget-12 results', '',
              '| Seed | Arm | Mean loss | CVaR90 | Quality | Mean MAC | Depth 0/1/2/3 counts |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    for row in summaries:
        if row['scenario'] == 'test_iid' and row['budget'] == 12:
            lines.append(f"| {row['seed']} | {row['arm']} | {row['mean_loss']:.6f} | "
                         f"{row['cvar90']:.6f} | {row['mean_quality']:.6f} | "
                         f"{row['mean_linear_macs']:.0f} | {row['depth_counts']} |")
    lines += ['', 'Declared budget units exclude the initial text event by protocol; measured model MACs include its actual encoder work.', '',
              'Training, calibration, validation, candidate generation, controller compilation and independent auditing are recorded separately. Matched optimizer updates and forward MACs do not equate total lifetime cost.', '',
              'This finite synthetic mechanism result does not close native runtime integration, within-refinement feedback control, learned preference identification, general stochastic FBSDE, natural-data foundation-model validation, or external dedicated-runner attestation.', '']
    return '\n'.join(lines)
