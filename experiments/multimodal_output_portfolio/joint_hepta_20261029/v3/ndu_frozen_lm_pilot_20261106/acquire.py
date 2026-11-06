"""Acquire a pinned public small language model, preserving every metered attempt."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            result.update(chunk)
    return result.hexdigest()


def append(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def measured(ledger, label, action):
    start = time.perf_counter()
    own = time.process_time()
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    event = {'schema': 'ndu.public-acquisition.v1', 'id': uuid.uuid4().hex,
             'label': label, 'started_at_utc': stamp(), 'started_monotonic': start,
             'source_sha256': sha(Path(__file__)), 'phase': 'intent'}
    append(ledger, event)
    try:
        result = action()
        event.update(status='ok', result=result)
        return result
    except Exception as exc:
        event.update(status='failed', exception=type(exc).__name__, message=str(exc)[:1000])
        raise
    finally:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        event.update(phase='terminal', finished_at_utc=stamp(),
                     wall_seconds=time.perf_counter()-start,
                     self_cpu_seconds=time.process_time()-own,
                     children_cpu_seconds=after.ru_utime+after.ru_stime-child.ru_utime-child.ru_stime,
                     actual_host_currency_cost=None, paid_provider_requests=0)
        append(ledger, event)


def command(argv, destination, timeout):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        result = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    record = {'argv': argv, 'returncode': result.returncode, 'log_sha256': sha(destination)}
    if result.returncode:
        raise RuntimeError(json.dumps(record))
    return record


def download(manifest, row, directory):
    path = directory / row['name']
    if path.exists():
        if path.is_symlink() or path.stat().st_size != row['bytes']:
            raise ValueError('Existing model file differs')
        data_sha = sha(path)
        if row.get('sha256') != data_sha:
            raise ValueError('Existing file requires a registered SHA-256')
        return {'name': row['name'], 'sha256': data_sha, 'bytes': row['bytes'], 'reused': True}
    url = f"https://huggingface.co/{manifest['model_id']}/resolve/{manifest['revision']}/{row['name']}"
    partial = directory / (row['name']+'.partial-'+uuid.uuid4().hex)
    started = time.monotonic()
    size = 0
    digest = hashlib.sha256()
    git = hashlib.sha1(b'blob '+str(row['bytes']).encode()+b'\0')
    with urllib.request.urlopen(url, timeout=25) as response, partial.open('xb') as output:
        if not response.url.startswith('https://'):
            raise ValueError('HTTPS required')
        while chunk := response.read(1048576):
            size += len(chunk)
            if size > row['bytes'] or time.monotonic()-started > 240:
                raise ValueError('Acquisition byte/time cap exceeded')
            output.write(chunk)
            digest.update(chunk)
            git.update(chunk)
        output.flush()
        os.fsync(output.fileno())
    if size != row['bytes'] or (row.get('sha256') and digest.hexdigest() != row['sha256']):
        raise ValueError('Model file size/SHA mismatch; partial retained')
    if not row.get('sha256') and git.hexdigest() != row['git_blob']:
        raise ValueError('Model metadata Git blob mismatch; partial retained')
    partial.rename(path)
    return {'name': row['name'], 'sha256': digest.hexdigest(), 'bytes': size, 'url': url, 'reused': False}


def main(destination, ledger, stage):
    destination.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT/'model_manifest.json').read_text())
    environment = destination/'venv'
    if stage == 'environment':
        if environment.exists():
            raise ValueError('Refusing to replace existing environment')
        steps = [(['uv', 'venv', str(environment)], 60),
                 (['uv', 'pip', 'install', '--python', str(environment/'bin/python'),
                   '--index-url', 'https://download.pytorch.org/whl/cpu', 'torch==2.15.0+cpu'], 300),
                 (['uv', 'pip', 'install', '--python', str(environment/'bin/python'),
                   'transformers==5.22.1', 'safetensors==0.8.0'], 300)]
        for index, (argv, timeout) in enumerate(steps):
            measured(ledger, 'environment-'+str(index), lambda a=argv, i=index, t=timeout:
                     command(a, destination/('install-'+str(i)+'.log'), t))
    else:
        directory = destination/'model'
        directory.mkdir(exist_ok=True)
        files = [measured(ledger, 'download-'+row['name'], lambda r=row: download(manifest, r, directory))
                 for row in manifest['files']]
        output = destination/'materialized-model.json'
        with output.open('x') as stream:
            json.dump({'model_id': manifest['model_id'], 'revision': manifest['revision'],
                       'files': files, 'manifest_sha256': sha(ROOT/'model_manifest.json')}, stream, indent=2)
            stream.write('\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--stage', choices=('environment', 'weights'), required=True)
    args = parser.parse_args()
    main(args.destination, args.ledger, args.stage)
