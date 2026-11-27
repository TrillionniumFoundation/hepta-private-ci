"""Serial fixed-roster replay with explicit failed and unstarted entries."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback
from zipfile import ZipFile, ZIP_DEFLATED

from audit_io import require, save, sha, verify_program


def sampled_rss(pid):
    try:
        lines = Path(f'/proc/{pid}/status').read_text().splitlines()
        return next(int(line.split()[1]) * 1024 for line in lines if line.startswith('VmRSS:'))
    except (FileNotFoundError, ProcessLookupError, StopIteration):
        return None


def run_one(argv, directory, wall_limit, rss_limit, env):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    row = dict(argv=argv, process_started=False, wall_limit_seconds=wall_limit,
               RSS_limit_bytes=rss_limit, sampled_peak_rss_bytes=0,
               status='started', started_utc=datetime.now(timezone.utc).isoformat())
    process = None
    try:
        with (directory / 'stdout').open('xb') as stdout, (directory / 'stderr').open('xb') as stderr:
            process = subprocess.Popen(argv, env=dict(env, HCSN_REPLAY_FIT_STARTED=str(start)),
                                       stdout=stdout, stderr=stderr)
            row.update(process_started=True, pid=process.pid)
            while process.poll() is None:
                observed = sampled_rss(process.pid)
                if observed is not None:
                    row['sampled_peak_rss_bytes'] = max(observed, row['sampled_peak_rss_bytes'])
                if time.monotonic() - start > wall_limit or observed is not None and observed > rss_limit:
                    row['status'] = 'wall_capped' if time.monotonic() - start > wall_limit else 'RSS_capped'
                    process.kill()
                    break
                time.sleep(.05)
            process.wait()
        row['returncode'] = process.returncode
        if row['status'] == 'started':
            row['status'] = 'completed' if process.returncode == 0 else 'failed'
    except Exception:
        row.update(status='launch_or_monitor_failed', error=traceback.format_exc())
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        row['returncode'] = process.returncode if process is not None else None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    row.update(whole_child_wall_seconds=time.monotonic() - start,
               waited_child_CPU_seconds=usage.ru_utime + usage.ru_stime - before.ru_utime - before.ru_stime,
               finished_utc=datetime.now(timezone.utc).isoformat(),
               cost_scope='Complete child spawn/import/input-check/forward/serialization/exit; nested fit timers not additional.')
    if row['status'] == 'completed' and row['whole_child_wall_seconds'] > wall_limit:
        row['status'] = 'wall_capped_at_exit'
    for name in ('stdout', 'stderr'):
        path = directory / name
        row[name] = dict(bytes=path.stat().st_size, sha256=sha(path)) if path.exists() else {'missing': True}
    save(directory / 'outer.json', row)
    return row


def classify(outer, artifact):
    if outer['status'] != 'completed':
        return 'HOLD', 'outer process did not complete within its declared budget'
    if artifact is None:
        return 'HOLD', 'rc0 does not establish a readable result artifact'
    if artifact.get('quality_reproducibility') != 'passed' or not artifact.get('inputs_unchanged'):
        return 'HOLD', 'replay identity/metrics did not pass'
    if artifact.get('self_peak_rss_bytes', float('inf')) > outer['RSS_limit_bytes']:
        return 'HOLD', 'normal-exit self peak RSS exceeded cap'
    return 'passed', None


def main(output):
    program, out = Path(__file__).resolve().parent, Path(output)
    out.mkdir(parents=True, exist_ok=False)
    started = float(os.environ.get('HCSN_REPLAY_CONTROLLER_STARTED', time.monotonic()))
    usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    entries, report = [], dict(schema='independent-six-HCSN-best-D-controller-v1', scientific_admission='HOLD',
                              original_training_adequacy=False, confirmation_E_access=False)
    try:
        report['program_manifest_sha256_before'] = verify_program(program)
        plan = json.loads((program / 'PLAN.json').read_bytes())
        (out / 'PLAN.json').write_bytes((program / 'PLAN.json').read_bytes())
        caps = plan['resources']
        env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                   CUDA_VISIBLE_DEVICES='', PYTHONDONTWRITEBYTECODE='1')
        for name in plan['fit_roster']:
            remaining = max(0., caps['whole_controller_wall_seconds'] - (time.monotonic() - started))
            entry = dict(name=name, quality_reproducibility='HOLD', original_training_adequacy=False)
            entries.append(entry)
            if remaining <= 0:
                entry.update(execution_status='not_started_whole_budget', process_started=False)
                continue
            wrapper = ('import resource,runpy,sys; resource.setrlimit(resource.RLIMIT_AS,('
                       + str(caps['address_space_bytes']) + ',' + str(caps['address_space_bytes'])
                       + ')); script=sys.argv[1];sys.argv=sys.argv[1:];'
                         'sys.path.insert(0,str(__import__("pathlib").Path(script).parent));runpy.run_path(script,run_name="__main__")')
            argv = [sys.executable, '-B', '-c', wrapper, str(program / 'replay_fit.py'),
                    '--name', name, '--output', str(out / name)]
            outer = run_one(argv, out / (name + '-process'), min(caps['per_fit_wall_seconds'], remaining),
                            caps['per_fit_RSS_bytes'], env)
            entry.update(execution_status=outer['status'], process_started=outer['process_started'], outer=outer)
            path = out / name / 'RESULT.json'
            artifact = None
            try:
                artifact = json.loads(path.read_bytes())
                require(artifact['name'] == name, 'replay artifact candidate differs')
                entry.update(result_sha256=sha(path), result=artifact)
            except Exception:
                entry['artifact_error'] = traceback.format_exc()
                artifact = None
            entry['quality_reproducibility'], entry['withholding_reason'] = classify(outer, artifact)
            save(out / (name + '-SUMMARY.json'), entry)
            print(json.dumps(dict(name=name, status=entry['execution_status'], quality_reproducibility=entry['quality_reproducibility'])), flush=True)
        report['program_manifest_sha256_after'] = verify_program(program)
        report['execution_status'] = 'completed_fixed_roster'
    except Exception:
        report.update(execution_status='controller_failed', error=traceback.format_exc())
    finally:
        if 'plan' in locals():
            observed = {entry['name'] for entry in entries}
            entries.extend(dict(name=name, quality_reproducibility='HOLD', original_training_adequacy=False,
                                execution_status='not_started_controller_failure', process_started=False)
                           for name in plan['fit_roster'] if name not in observed)
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        report.update(entries=entries, completed_full_D_passes=sum(r['quality_reproducibility'] == 'passed' for r in entries),
                      process_wall_seconds=time.monotonic() - started, own_CPU_seconds=time.process_time(),
                      waited_children_CPU_seconds=usage.ru_utime + usage.ru_stime - usage0.ru_utime - usage0.ru_stime,
                      own_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      child_peak_rss_bytes=usage.ru_maxrss * 1024, energy_joules=None,
                      scope='All predeclared candidates; failed and missing results retain HOLD. D reuse is not independent E confirmation.')
        save(out / 'SUMMARY.json', report)
        manifest = {str(p.relative_to(out)): dict(bytes=p.stat().st_size, sha256=sha(p))
                    for p in sorted(out.rglob('*')) if p.is_file()}
        save(out / 'MANIFEST.json', dict(files=manifest))
        with ZipFile(str(out) + '.zip', 'x', compression=ZIP_DEFLATED) as zipped:
            for path in sorted(out.rglob('*')):
                if path.is_file():
                    zipped.write(path, str(path.relative_to(out)))
    return 0 if report['execution_status'] == 'completed_fixed_roster' and len(entries) == 6 else 2


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    raise SystemExit(main(parser.parse_args().output))
