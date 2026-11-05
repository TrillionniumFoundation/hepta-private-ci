#!/usr/bin/env python3
"""Operational create-only launcher; waits for software gates, then freezes once."""
import datetime
import hashlib
import json
import pathlib
import resource
import subprocess
import sys
import time

root = pathlib.Path('/home/qian-qi/work/hepta-wsp-certificate-20261105-01')
target = pathlib.Path('/home/qian-qi/work/hepta-wsp-certificate-20261105-01-target')
work = root / 'qualification/native-certificate-launch-r1'
work.mkdir(parents=True, exist_ok=False)
started, self_cpu = time.monotonic(), time.process_time()
before = resource.getrusage(resource.RUSAGE_CHILDREN)
record = {'schema': 'hepta-native-certificate-launch-v1', 'phases': [], 'passed': False,
          'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'qualification_wait_in_wall_cost': True,
          'launcher_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()}


def run(name, command, timeout):
    begin, usage = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    with (work / (name + '.stdout.log')).open('xb') as out, (work / (name + '.stderr.log')).open('xb') as err:
        result = subprocess.run(command, stdout=out, stderr=err, timeout=timeout, check=False)
    now = resource.getrusage(resource.RUSAGE_CHILDREN)
    record['phases'].append({'name': name, 'command': command, 'exit_code': result.returncode,
        'wall_seconds': time.monotonic()-begin,
        'child_cpu_seconds': now.ru_utime+now.ru_stime-usage.ru_utime-usage.ru_stime})
    if result.returncode:
        raise RuntimeError(name + ' failed with exit ' + str(result.returncode))


try:
    qualification = root / 'qualification/native-certificate-attempt-1/RESULT.json'
    deadline = started + 2700
    while True:
        try:
            value = json.loads(qualification.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            value = {}
        if value.get('completed'):
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('bounded software qualification wait expired')
        time.sleep(5)
    record['wait_wall_seconds'] = time.monotonic()-started
    if not value.get('all_passed') or not value.get('source_unchanged'):
        raise RuntimeError('software gate failed; native corpus was not launched')
    script = root / 'experiments/weight/native_certificate_20261105'
    inputs = root / 'qualification/native-certificate-inputs-r1'
    protocol = root / 'qualification/native-certificate-execution-r1.json'
    run('freeze', [sys.executable, '-B', str(script/'freeze_protocol.py'), '--root', str(root),
        '--qualification', str(qualification), '--inputs', str(inputs), '--output', str(protocol)], 60)
    identity = hashlib.sha256(protocol.read_bytes()).hexdigest()
    record['protocol_sha256'] = identity
    run('corpus', [sys.executable, '-B', str(script/'supervise.py'),
        '--output', str(root/'qualification/native-certificate-corpus-r1-outer'), '--timeout', '900', '--',
        sys.executable, '-B', str(script/'run_corpus.py'), '--binary', str(target/'debug/hepta-runtime'),
        '--inputs', str(inputs), '--protocol', str(protocol), '--protocol-sha256', identity,
        '--output', str(root/'qualification/native-certificate-corpus-r1')], 960)
    record['passed'] = True
except BaseException as error:
    record['error'] = repr(error)
    raise
finally:
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    record.update(completed=True, wall_seconds=time.monotonic()-started,
        self_cpu_seconds=time.process_time()-self_cpu,
        child_cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    with (work/'LAUNCHER_RECEIPT.json').open('x') as out:
        json.dump(record,out,sort_keys=True,indent=2);out.write('\n')
    print(json.dumps(record),flush=True)
