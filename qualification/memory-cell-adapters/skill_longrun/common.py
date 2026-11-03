"""Evidence IO and public skill runtime contract; no maintenance targets."""

import hashlib
import json
import os
from pathlib import Path
import resource
import sqlite3
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ADAPTER = HERE.parent
sys.path.insert(0, str(ADAPTER))
from runtime_contract import canonical, execute_program

PROBES = ((0, (5, 3, 11)), (7, (9, 2, 15)), (17, (2, 7, 13)), (5, (11, 1, 8)))
GROUPS = ('active', 'retention', 'changed', 'revoked')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(path):
    raw = Path(path).read_bytes()
    return {'bytes': len(raw), 'sha256': sha(raw)}


def save(path, value):
    raw = canonical(value) + b'\n'
    with Path(path).open('xb') as handle:
        handle.write(raw)
    return {'bytes': len(raw), 'sha256': sha(raw)}


def file_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob('*') if p.is_file())


def snapshot(source, destination):
    if Path(destination).exists():
        raise FileExistsError(destination)
    with sqlite3.connect(f'file:{Path(source).resolve()}?mode=ro', uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def skill_rows(database):
    with sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro', uri=True) as db:
        rows = db.execute("SELECT idx,identity,version,active,payload FROM sources WHERE kind='skill' ORDER BY idx").fetchall()
    return [{'kind': 'skill', 'index': i, 'source_id': source, 'version': version,
             'active': bool(active), 'value': json.loads(payload)} for i, source, version, active, payload in rows]


def active_rows(state):
    return [{k: r[k] for k in ('kind', 'index', 'source_id', 'version', 'value')} for r in state if r['active']]


def validate_program(program):
    if (not isinstance(program, list) or len(program) != 4 or program[-1] != 6
            or any(type(op) is not int or not 0 <= op < 6 for op in program[:3])
            or type(program[-1]) is not int):
        raise ValueError('skill source requires three bounded operations and final stop')


def executions(program):
    return [{'input': value, 'policy': list(policy), 'max_steps': 4,
             'result': execute_program(value, policy, program, max_steps=4)} for value, policy in PROBES]


def validate_cell(cell):
    if (cell.config.input_dim != 384 or cell.config.rank != 4 or cell.head_frozen
            or [(s.name, s.kind, s.size, s.weight) for s in cell.config.outputs]
            != [(f'op{i}', 'multiclass', 7, 1.0) for i in range(4)]):
        raise ValueError('registered four-head skill architecture changed')


def command(executable, script, frame, stem):
    raw = canonical(frame) + b'\n'
    save(stem.with_suffix('.request.json'), frame)
    began, before = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    with subprocess.Popen([executable, '-I', '-B', str(script)], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          env={**os.environ, 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
                               'PYTHONDONTWRITEBYTECODE': '1'}) as child:
        try:
            stdout, stderr = child.communicate(raw, timeout=180)
        except subprocess.TimeoutExpired:
            timed_out = True
            child.kill()
            stdout, stderr = child.communicate()
    ended, after = time.monotonic_ns(), resource.getrusage(resource.RUSAGE_CHILDREN)
    stem.with_suffix('.stdout').write_bytes(stdout)
    stem.with_suffix('.stderr').write_bytes(stderr)
    try:
        parsed = json.loads(stdout)
        if not isinstance(parsed, dict):
            raise ValueError('child object required')
    except (ValueError, UnicodeError):
        parsed = {'error': 'child emitted no valid JSON object'}
    receipt = {'pid': child.pid, 'script': script.name, 'started_ns': began, 'exited_ns': ended,
               'exit_code': child.returncode, 'timed_out': timed_out, 'wall_ns': ended-began,
               'cpu_seconds': after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
               'kernel_input_blocks': after.ru_inblock-before.ru_inblock,
               'kernel_output_blocks': after.ru_oublock-before.ru_oublock,
               'request': {'bytes': len(raw), 'sha256': sha(raw)},
               'stdout': identity(stem.with_suffix('.stdout')), 'stderr': identity(stem.with_suffix('.stderr')),
               'passed': child.returncode == 0 and not timed_out and not parsed.get('error')}
    if parsed.get('request_sha256') != sha(raw):
        receipt['passed'] = False
    save(stem.with_suffix('.process.json'), receipt)
    return parsed, receipt


def child_main(run, schema):
    raw = sys.stdin.buffer.read(1048577)
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    try:
        if len(raw) > 1048576:
            raise ValueError('bounded request required')
        response, status = run(json.loads(raw)), 0
    except Exception as error:
        response, status = {'schema': schema+'-error', 'pid': os.getpid(),
                            'error': f'{type(error).__name__}: {error}'}, 2
    response.update(request_sha256=sha(raw), process_body_wall_ns=time.monotonic_ns()-started,
                    process_body_cpu_ns=time.process_time_ns()-cpu,
                    peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    sys.stdout.buffer.write(canonical(response)+b'\n')
    raise SystemExit(status)
