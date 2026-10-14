"""Freeze round-2 protocol, execute complete fresh-process census, retain failures."""
import argparse
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

from run import digest, write_json
from structure_trial import source_hashes
from structured import panel_specs


def run_specs():
    runs = []
    base = [('raw', 'adam'), ('raw', 'trf'), ('structured', 'adam'), ('structured', 'trf')]
    for budget in (2, 8):
        for index, seed in enumerate((11, 23, 47)):
            order = base[index:] + base[:index]
            for family, optimizer in order:
                runs.append(dict(family=family, optimizer=optimizer, seed=seed, cpu_seconds=budget))
    for seed in (11, 23, 47):
        for family in ('raw', 'structured'):
            runs.append(dict(family=family, optimizer='lbfgs', seed=seed, cpu_seconds=8))
        runs.append(dict(family='transformer', optimizer='adam', seed=seed, cpu_seconds=8))
    for seed in (11, 23, 47):
        for family in ('raw', 'structured'):
            runs.append(dict(family=family, optimizer='none', seed=seed, cpu_seconds=1))
    runs.append(dict(family='direct', optimizer='none', seed=0, cpu_seconds=1))
    return runs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parent
    plan = dict(schema='hepta.native-stem.structure.sweep.r2', source_sha256=source_hashes(),
                runs=run_specs(), panels=panel_specs(),
                primary='structured TRF versus structured Adam: new_composed RMSE, 8 CPU-second cap, all seeds',
                secondary='new_uniform, long_horizon, larger_state, priced regret, single-coefficient shifts',
                structural_prior_control='identical untrained initial models, no fitted oracle',
                family_control='raw and structured have 65 weights; non-identical function classes',
                solve_control='same full residual and B/C initialization within each family, plus LBFGS',
                training_coverage='unchanged complete finite training law; no added zero-risk examples',
                risk_neutral_success='analytic prior only; not evidence of learned/general FBSDE intelligence',
                new_terminal_seeds=[2026101401, 2026101402, 2026101403],
                frozen_before_sweep=True, externally_preregistered=False,
                preliminary='48 math/mechanism tests including short optimizer tests; no held-out efficacy sweep before freeze',
                formal_success_rule='report every seed, panel and failure; no selection on evaluation',
                energy_joules=None, total_flops=None, exact_compute_matched=False,
                production_authorized=False)
    plan_hash = write_json(args.out / 'PLAN.json', plan)
    start = time.perf_counter()
    census = []
    for spec in plan['runs']:
        name = f"{spec['family']}-{spec['optimizer']}-s{spec['seed']}-b{spec['cpu_seconds']}"
        command = [sys.executable, str(root / 'structure_trial.py'), '--family', spec['family'],
                   '--optimizer', spec['optimizer'], '--seed', str(spec['seed']),
                   '--cpu-seconds', str(spec['cpu_seconds']), '--out', str(args.out / name)]
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        t = time.perf_counter()
        row = dict(name=name, **spec)
        with open(args.out / (name + '.log'), 'xb') as log:
            try:
                completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                           env=dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                                                    OPENBLAS_NUM_THREADS='1'), timeout=120, check=False)
                row['returncode'] = completed.returncode
                row['status'] = 'completed' if completed.returncode == 0 else 'failed'
            except subprocess.TimeoutExpired:
                row.update(status='timeout', returncode=None)
            except OSError as exc:
                row.update(status='launch_failed', returncode=None, error=str(exc))
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row['whole_child_wall_seconds'] = time.perf_counter() - t
        row['whole_child_cpu_seconds'] = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
        if row['status'] == 'completed':
            try:
                report_path = args.out / name / 'REPORT.json'
                report = json.loads(report_path.read_text())
                if report['plan_sha256'] != digest((args.out / name / 'PLAN.json').read_bytes()):
                    raise ValueError('child plan digest mismatch')
                if plan['source_sha256'] != source_hashes():
                    raise ValueError('source drift')
                row['report_sha256'] = digest(report_path.read_bytes())
                row['new_composed_rmse'] = report['metrics']['new_composed']['rmse']
            except (OSError, ValueError, KeyError) as exc:
                row.update(status='evidence_failed', error=str(exc))
        census.append(row)
        write_json(args.out / (name + '.completion.json'), row)
        print(json.dumps(row, sort_keys=True), flush=True)
    summary = dict(plan_sha256=plan_hash, census=census,
                   completed=sum(row['status'] == 'completed' for row in census),
                   failed=sum(row['status'] != 'completed' for row in census),
                   whole_sweep_wall_seconds=time.perf_counter() - start,
                   all_child_cpu_seconds=sum(row['whole_child_cpu_seconds'] for row in census),
                   production_authorized=False)
    write_json(args.out / 'COMPLETE.json', summary)
    if summary['failed']:
        raise SystemExit('failures retained; partial outputs are not a complete success')


if __name__ == '__main__':
    main()
