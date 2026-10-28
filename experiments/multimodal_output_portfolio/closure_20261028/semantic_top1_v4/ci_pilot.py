"""Portable, fixed eight-training-source CI mechanism; no fitting or holdout access."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import resource
import shutil
import subprocess
import sys
import tarfile
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .mechanism import cpu_seconds, sha, write_json
from .ci_runtime import resources
from .registration import digest, load_registration

HERE = Path(__file__).parent
REPO = HERE.parents[3]
REGISTRATION_SHA = '07152eb03b3df4d98ca97f5cf7b21b884eaac9311e9ece9c82d705c5143e30c2'


class HttpsRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise ValueError('A public weight download redirected outside HTTPS')
        return super().redirect_request(request, fp, code, message, headers, newurl)


def relative_path(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path) != name or not name:
        raise ValueError('Noncanonical relative path in fixed pilot evidence')
    return path


def read_manifest():
    path = HERE / 'ci/PILOT.json'
    manifest = json.loads(path.read_text())
    body = dict(manifest)
    expected = body.pop('pilot_sha256')
    if digest(body) != expected or manifest['registration_sha256'] != REGISTRATION_SHA:
        raise ValueError('Pilot identity differs from the frozen original-top1 registration')
    if manifest['maximum_sources'] != 8 or manifest['maximum_events'] != 43:
        raise ValueError('Fixed training mechanism budget differs')
    if manifest['training_updates'] != 0 or manifest['holdout_sources'] != 0:
        raise ValueError('This entry cannot fit or consume holdout data')
    for name, pin in manifest['implementation_sha256'].items():
        relative_path(name)
        if sha(REPO / name) != pin:
            raise ValueError('Pilot implementation changed: ' + name)
    registration_path = HERE / 'ci/REGISTRATION.json'
    if sha(registration_path) != manifest['registration_file_sha256']:
        raise ValueError('Exact registration bytes changed')
    return manifest


def seed_bytes(manifest):
    chunks = []
    for row in manifest['seed']['parts']:
        relative_path(row['path'])
        path = HERE / row['path']
        if path.stat().st_size != row['bytes'] or row['bytes'] > 40000:
            raise ValueError('Portable seed part length differs')
        if sha(path) != row['sha256']:
            raise ValueError('Portable seed part bytes changed')
        record = json.loads(path.read_text(encoding='ascii'))
        if set(record) != {'part', 'base64'} or record['part'] != row['part']:
            raise ValueError('Portable seed part structure differs')
        chunks.append(record['base64'])
    payload = base64.b64decode(''.join(chunks), validate=True)
    if len(payload) != manifest['seed']['bytes'] or digest(payload) != manifest['seed']['sha256']:
        raise ValueError('Portable seed archive changed')
    return payload


def unpack_seed(payload, manifest, destination):
    expected = {row['path']: row for row in manifest['seed']['members']}
    if len(expected) != len(manifest['seed']['members']):
        raise ValueError('Duplicate fixed seed member')
    destination.mkdir(parents=True, exist_ok=False)
    seen = set()
    total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        for member in archive:
            relative_path(member.name)
            if not member.isfile() or member.name not in expected or member.name in seen:
                raise ValueError('Unexpected, linked, or duplicate portable seed member')
            row = expected[member.name]
            if member.size != row['bytes'] or member.size > manifest['seed']['maximum_member_bytes']:
                raise ValueError('Portable seed member size differs')
            total += member.size
            if total > manifest['seed']['unpacked_bytes']:
                raise ValueError('Portable seed exceeds frozen byte budget')
            data = archive.extractfile(member).read(member.size + 1)
            if len(data) != row['bytes'] or digest(data) != row['sha256']:
                raise ValueError('Portable seed member identity differs')
            path = destination / member.name
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(data)
            seen.add(member.name)
    if seen != set(expected) or total != manifest['seed']['unpacked_bytes']:
        raise ValueError('Portable seed is incomplete')
    registration = load_registration(HERE / 'ci/REGISTRATION.json', destination)
    plan = json.loads((destination / 'SOURCE_PROTOCOL.json').read_text())
    selected = {row['source_id']: row for row in plan['selected']}
    training_root = destination / 'prepared/observer_train'
    actual = sorted(path.name for path in training_root.iterdir())
    if actual != sorted(registration['mechanism_source_ids']) or actual != sorted(manifest['source_ids']):
        raise ValueError('Portable prepared data are not exactly the fixed eight training sources')
    if [path.name for path in (destination / 'prepared').iterdir()] != ['observer_train']:
        raise ValueError('Portable seed contains another prepared role')
    count = 0
    for sid in actual:
        source = selected[sid]
        receipt = json.loads((training_root / sid / 'RECEIPT.json').read_text())
        if source['role'] != 'observer_train' or receipt['role'] != 'observer_train':
            raise ValueError('Nontraining source in mechanism seed')
        if receipt['source_id'] != sid or receipt['source_protocol_sha256'] != registration['parent_source_protocol_sha256']:
            raise ValueError('Training receipt belongs to another source or allocation')
        expected_events = source['events'][:source['retained_event_count']]
        if len(receipt['events']) != len(expected_events):
            raise ValueError('Training receipt event count differs')
        for event, observed in zip(expected_events, receipt['events'], strict=True):
            if any(observed[key] != value for key, value in event.items()):
                raise ValueError('Training event or its selected labels changed')
        if sha(training_root / sid / 'FEATURES.npz') != receipt['retained_files']['FEATURES.npz']:
            raise ValueError('Training reference features changed')
        count += len(expected_events)
    if count != manifest['maximum_events']:
        raise ValueError('Portable event count differs')
    return registration


def download_weight(row, destination, timeout):
    if urlsplit(row['url']).scheme != 'https' or row['bytes'] > 100000000:
        raise ValueError('Invalid fixed public weight endpoint or size')
    before_cpu, before_wall = cpu_seconds(), time.monotonic()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + '.partial')
    h = hashlib.sha256()
    size = 0
    opener = build_opener(HttpsRedirects())
    with opener.open(Request(row['url'], headers={'User-Agent': 'hepta-observer-v4-ci/1'}), timeout=timeout) as response:
        host = urlsplit(response.url).hostname
        declared = response.headers.get('Content-Length')
        if declared is not None and int(declared) != row['bytes']:
            raise ValueError('Official weight byte length changed')
        with temporary.open('xb') as stream:
            while True:
                block = response.read(min(1048576, row['bytes'] - size + 1))
                if not block:
                    break
                size += len(block)
                if size > row['bytes']:
                    raise ValueError('Official weight exceeded fixed byte bound')
                stream.write(block)
                h.update(block)
    if size != row['bytes'] or h.hexdigest() != row['sha256']:
        raise ValueError('Official pretrained weight identity changed')
    temporary.replace(destination)
    return {**row, 'redirect_final_host': host, 'cpu_seconds': cpu_seconds() - before_cpu,
            'wall_seconds': time.monotonic() - before_wall}


def run_command(command, name, output, remaining_seconds):
    before_cpu, before_wall = cpu_seconds(), time.monotonic()
    with (output / (name + '.log')).open('x') as stream:
        process = subprocess.run(command, cwd=REPO, stdout=stream, stderr=subprocess.STDOUT,
                                 timeout=remaining_seconds, check=False)
    row = {'command': command, 'returncode': process.returncode,
           'cpu_seconds_self_and_completed_children': cpu_seconds() - before_cpu,
           'wall_seconds': time.monotonic() - before_wall}
    write_json(output / (name + '.json'), row)
    if process.returncode:
        raise RuntimeError(name + ' failed with return code ' + str(process.returncode))
    return row


def main(output, verify_seed_only):
    started = time.monotonic()
    manifest = read_manifest()
    output.mkdir(parents=True, exist_ok=False)
    before = resources()
    disk = shutil.disk_usage(output)
    result = {'schema': 'hepta.closure.top1-v4-ci-pilot-result.v1', 'pilot_sha256': manifest['pilot_sha256'],
              'registration_sha256': REGISTRATION_SHA, 'source_ids': manifest['source_ids'],
              'fixed_events': manifest['maximum_events'], 'training_updates': 0, 'holdout_media_or_predictions': 0,
              'tested_sha': os.environ.get('TESTED_SHA'), 'github_event_sha': os.environ.get('GITHUB_SHA'), 'github_run_id': os.environ.get('GITHUB_RUN_ID'),
              'github_run_attempt': os.environ.get('GITHUB_RUN_ATTEMPT'),
              'resources_before_preparation': before, 'free_disk_bytes': disk.free,
              'torch_imported_in_wrapper': 'torch' in sys.modules,
              'cost_scope': 'This Python wrapper process and completed subprocesses from process start through result assembly, including dependency installation, weights, data preparation and mechanism. GitHub checkout/setup/artifact upload administrative CPU is outside this process and not inferred.',
              'stages': [], 'weights': [], 'native_owner_called': False, 'generator_called': False,
              'semantic_accuracy_evaluated': False, 'qualification_passed': False}
    write_json(output / 'ENTRY.json', result)
    deadline = started + manifest['maximum_wall_seconds']
    try:
        if not verify_seed_only and (before['effective_headroom_bytes'] < manifest['initial_headroom_minimum_bytes']
                                    or disk.free < manifest['initial_free_disk_minimum_bytes']):
            result['status'] = 'resource_gate_blocked_before_install_or_download'
            return result
        payload = seed_bytes(manifest)
        registration = unpack_seed(payload, manifest, output / 'assets')
        del payload
        result['seed_verified'] = True
        result['actual_events'] = registration['mechanism_events']
        if verify_seed_only:
            result['status'] = 'portable_seed_verified_without_network_models_or_holdouts'
            return result
        if platform.python_version() != registration['specification']['runtime_versions']['python']:
            raise ValueError('Registered Python runtime unavailable')
        if shutil.which('ffmpeg') is None:
            raise ValueError('Required FFmpeg executable is unavailable')
        for name, command in manifest['dependency_commands']:
            command = [sys.executable if item == '{python}' else str(output / item[9:])
                       if item.startswith('{output}/') else item for item in command]
            result['stages'].append(run_command(command, name, output, max(1, deadline - time.monotonic())))
        result['stages'].append(run_command(['ffmpeg', '-version'], 'ffmpeg-version', output,
                                           max(1, deadline - time.monotonic())))
        result['stages'].append(run_command([sys.executable, '-m', 'pip', 'freeze'], 'pip-freeze', output,
                                           max(1, deadline - time.monotonic())))
        for row in manifest['weights']:
            if time.monotonic() >= deadline:
                raise TimeoutError('Fixed mechanism preparation wall budget exhausted')
            result['weights'].append(download_weight(row, output / 'assets/pretrained' / row['name'],
                                                      min(120, max(1, deadline - time.monotonic()))))
        command = [sys.executable, '-B', '-m',
                   'experiments.multimodal_output_portfolio.closure_20261028.semantic_top1_v4.ci_mechanism',
                   '--registration', str(HERE / 'ci/REGISTRATION.json'),
                   '--assets', str(output / 'assets'), '--output', str(output / 'mechanism')]
        result['stages'].append(run_command(command, 'mechanism', output, max(1, deadline - time.monotonic())))
        mechanism = json.loads((output / 'mechanism/RESULT.json').read_text())
        if mechanism['status'] != 'passed' or mechanism['events_completed'] != 43:
            raise ValueError('Fixed mechanism did not complete all registered events')
        result['status'] = 'mechanism_passed_not_semantic_qualification'
        result['mechanism_result_sha256'] = sha(output / 'mechanism/RESULT.json')
        return result
    except Exception as exception:
        result['status'] = 'incomplete_or_failed'
        result['error'] = type(exception).__name__ + ': ' + str(exception)
        return result
    finally:
        result.update(total_process_self_children_cpu_seconds=cpu_seconds(),
                      wall_seconds_since_entry=time.monotonic() - started,
                      wrapper_resource_observation=resources(),
                      child_process_max_rss_bytes=int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) * 1024,
                      child_peak_scope='Maximum ru_maxrss among completed child processes, not their concurrent sum.')
        write_json(output / 'RESULT.json', result)
        evidence = {str(path.relative_to(output)): {'bytes': path.stat().st_size, 'sha256': sha(path)}
                    for path in sorted(output.rglob('*')) if path.is_file() and 'assets' not in path.relative_to(output).parts}
        write_json(output / 'EVIDENCE.json', {'files': evidence, 'excluded': 'Portable input assets and downloadable pretrained weights; their exact identities are retained in the frozen pilot manifest and acquisition receipts.'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-seed-only', action='store_true')
    arguments = parser.parse_args()
    value = main(arguments.output, arguments.verify_seed_only)
    print(json.dumps({key: value.get(key) for key in ('status', 'error', 'actual_events', 'total_process_self_children_cpu_seconds')}))
    allowed = ('portable_seed_verified_without_network_models_or_holdouts', 'mechanism_passed_not_semantic_qualification')
    raise SystemExit(0 if value['status'] in allowed else 3 if value['status'].startswith('resource_gate_blocked') else 1)
