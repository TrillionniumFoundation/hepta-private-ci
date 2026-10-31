"""Acquire a preselected, completely new actor cohort from pinned CREMA-D.

The old low-level decoder is reused byte-for-byte. Download, decode and transport
costs are separate, measurable stages; none is a model quality measurement.
"""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time
import traceback

from experiments.hcsn_real_av_v1 import data as original


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
PART_BYTES = 196608


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    original.write_json(path, value)


def measure(name, operation, output):
    cpu, wall = time.process_time(), time.perf_counter()
    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    failed = None
    try:
        operation()
    except BaseException:
        failed = traceback.format_exc()
    end = resource.getrusage(resource.RUSAGE_CHILDREN)
    save(output / (name + '_COST.json'), {
        'stage': name, 'success': failed is None, 'exception': failed,
        'python_cpu_seconds': time.process_time() - cpu,
        'direct_children_cpu_seconds': end.ru_utime + end.ru_stime - child.ru_utime - child.ru_stime,
        'wall_seconds': time.perf_counter() - wall,
        'parent_peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        'max_child_rss_bytes': end.ru_maxrss * 1024,
        'scope': 'Stage body after imports; child CPU is nested, never added twice.',
        'energy_joules': None,
    })
    if failed is not None:
        raise RuntimeError(f'{name} failed; full exception retained in stage receipt')


def register(cache, output):
    plan_path = HERE / 'COHORT_PLAN.json'
    plan = json.loads(plan_path.read_text())
    old_path = REPO / 'experiments/hcsn_real_av_v1/data/COHORT_PLAN.json'
    if digest(old_path) != plan['old_cohort_sha256']:
        raise ValueError('Previous cohort identity mismatch')
    excluded = set(plan['exclude_actors'])
    groups = [set(plan['splits'][s]) for s in ('train', 'validation', 'test')]
    if any(g & excluded for g in groups) or any(groups[i] & groups[j] for i in range(3) for j in range(i)):
        raise ValueError('Actor leakage between old or new cohorts')
    if [len(g) for g in groups] != [16, 6, 8]:
        raise ValueError('Registered actor count changed')
    upstream = cache / 'upstream'
    if upstream.exists():
        raise FileExistsError('Use an empty acquisition cache; attempts are immutable')
    cache.mkdir(parents=True, exist_ok=True)
    subprocess.run(['git', 'clone', '--depth', '1', '--filter=blob:none', '--no-checkout',
                    plan['upstream'], str(upstream)], check=True)
    subprocess.run(['git', 'fetch', '--depth', '1', 'origin', plan['upstream_commit']],
                   cwd=upstream, check=True)
    listing = subprocess.check_output(['git', 'ls-tree', '-r', plan['upstream_commit'], 'VideoFlash'],
                                     cwd=upstream, text=True)
    entries = {}
    for row in listing.splitlines():
        metadata, name = row.split('\t', 1)
        entries[Path(name).stem] = (name, metadata.split()[2])
    selected = [(split, actor, sentence, label, emotion,
                 f'{actor}_{sentence}_{emotion}_{plan["level"]}')
                for split, actors in plan['splits'].items() for actor in actors
                for sentence in plan['sentences'] for label, emotion in enumerate(plan['emotions'])]
    if len(selected) != plan['expected_clips'] or any(r[-1] not in entries for r in selected):
        raise ValueError('Preselected official files are unavailable')
    paths = [entries[r[-1]][0] for r in selected] + ['LICENSE.txt']
    env = dict(os.environ, GIT_LFS_SKIP_SMUDGE='1')
    git = ['git', '-c', 'filter.lfs.required=false', '-c', 'filter.lfs.smudge=', '-c', 'filter.lfs.process=']
    subprocess.run(git + ['sparse-checkout', 'set', '--no-cone', '--stdin'],
                   input='\n'.join('/' + p for p in paths) + '\n', cwd=upstream,
                   text=True, env=env, check=True)
    subprocess.run(git + ['reset', '--hard', plan['upstream_commit']], cwd=upstream, env=env, check=True)
    records = []
    for split, actor, sentence, label, emotion, clip in selected:
        name, blob = entries[clip]
        fields = dict(line.split(' ', 1) for line in (upstream / name).read_text().splitlines())
        if fields.get('version') != 'https://git-lfs.github.com/spec/v1':
            raise ValueError('Official object is not an LFS pointer')
        records.append(dict(clip=clip, actor=actor, sentence=sentence, emotion=emotion, label=label,
                            split=split, git_path=name, pointer_blob_sha1=blob,
                            sha256=fields['oid'].split(':')[1], bytes=int(fields['size']),
                            url='https://media.githubusercontent.com/media/CheyneyComputerScience/CREMA-D/'
                                + plan['upstream_commit'] + '/' + name))
    (output / 'CREMA_D_LICENSE.txt').write_bytes((upstream / 'LICENSE.txt').read_bytes())
    (output / 'COHORT_PLAN.json').write_bytes(plan_path.read_bytes())
    save(output / 'MANIFEST.json', dict(schema='hcsn-blocker-av-media.v1', records=records,
         commit=plan['upstream_commit'], cohort_plan_sha256=digest(plan_path),
         license_database='ODbL-1.0', license_contents='DbCL-1.0',
         total_bytes=sum(r['bytes'] for r in records), previously_seen_actors=0))


def prepare(cache, output):
    original.prepare(cache, output)
    import numpy as np

    dataset = json.loads((output / 'DATASET.json').read_text())
    plan = json.loads((HERE / 'COHORT_PLAN.json').read_text())
    checks = []
    for split, record in dataset['splits'].items():
        with np.load(output / record['path'], allow_pickle=False) as arrays:
            actors = set(arrays['actor'].tolist())
            dt = arrays['dt']
            checks.append(dict(split=split, actors=sorted(actors), samples=len(arrays['y']),
                               dt_min=float(dt.min()), dt_max=float(dt.max()),
                               dt_nonconstant=bool(np.ptp(dt) > 0), labels=np.bincount(arrays['y']).tolist()))
            if actors != set(plan['splits'][split]) or actors & set(plan['exclude_actors']):
                raise ValueError('Decoded actor identity changed')
            if not np.isfinite(dt).all() or not (dt > 0).all():
                raise ValueError('Invalid real elapsed time')
    save(output / 'DATA_AUDIT.json', dict(passed=True, checks=checks,
         cohort_sha256=digest(HERE / 'COHORT_PLAN.json'),
         test_arrays_access='Dataset construction and label balance only; no model predictions, tuning or evaluation.',
         causal_streaming=False, dt_override=None))


def package(output, transport):
    transport.mkdir(parents=True, exist_ok=False)
    rows = []
    for path in sorted(output.iterdir()):
        if not path.is_file():
            raise ValueError('Unexpected nested data evidence')
        data = path.read_bytes()
        parts = []
        for index, start in enumerate(range(0, len(data), PART_BYTES)):
            name = f'{path.name}.part{index:04d}.b64'
            payload = base64.b64encode(data[start:start + PART_BYTES]) + b'\n'
            (transport / name).write_bytes(payload)
            parts.append(dict(path=name, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                              raw_bytes=min(PART_BYTES, len(data) - start)))
        rows.append(dict(path=path.name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), parts=parts))
    save(transport / 'TRANSPORT.json', dict(schema='hcsn-blocker-av-transport.v1', files=rows,
         execution_seal=os.environ.get('GITHUB_SHA'), run_id=os.environ.get('GITHUB_RUN_ID'),
         raw_bytes=sum(r['bytes'] for r in rows), maximum_blob_bytes=262145,
         failures_preserved=True, raw_media_redistributed=False,
         license_database='ODbL-1.0', license_contents='DbCL-1.0'))


def restore(transport, output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((transport / 'TRANSPORT.json').read_text())
    for row in manifest['files']:
        if Path(row['path']).name != row['path']:
            raise ValueError('Invalid logical filename')
        values = []
        for item in row['parts']:
            if Path(item['path']).name != item['path']:
                raise ValueError('Invalid part filename')
            value = (transport / item['path']).read_bytes()
            if len(value) != item['bytes'] or hashlib.sha256(value).hexdigest() != item['sha256']:
                raise ValueError('Transport integrity failed')
            decoded = base64.b64decode(value.strip(), validate=True)
            if len(decoded) != item['raw_bytes']:
                raise ValueError('Transport decoded size changed')
            values.append(decoded)
        data = b''.join(values)
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('Logical file integrity failed')
        (output / row['path']).write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('acquire', 'package', 'restore'))
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--transport', type=Path)
    args = parser.parse_args()
    if args.command == 'acquire':
        args.output.mkdir(parents=True, exist_ok=False)
        measure('REGISTER', lambda: register(args.cache, args.output), args.output)
        measure('ACQUIRE', lambda: original.acquire(args.cache, args.output, workers=4), args.output)
        measure('PREPARE', lambda: prepare(args.cache, args.output), args.output)
    elif args.command == 'package':
        package(args.output, args.transport)
    else:
        restore(args.transport, args.output)


if __name__ == '__main__':
    main()
