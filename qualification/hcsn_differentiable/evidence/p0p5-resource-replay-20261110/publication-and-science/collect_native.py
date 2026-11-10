"""Read-only publication provenance collection and one hosted CI artifact download."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import time
import traceback
from zipfile import ZipFile, ZIP_DEFLATED

BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
OUT = BASE / 'best-D-publication-and-science-artifact-collection-v1'
ARTIFACT_ID = 13797877354
ARTIFACT_SIZE = 77859
ARTIFACT_SHA = 'cab12a2f8f73660e3436e68c2dc84f072f1be857dc5513e8f956c995f2e7d743'
ENDPOINT = 'repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/13797877354/zip'


def require(condition, text):
    if not condition:
        raise ValueError(text)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def safe_members(zipped):
    names = zipped.namelist()
    require(len(names) == len(set(names)), 'duplicate ZIP names')
    for item in zipped.infolist():
        name = item.filename
        require(not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name,
                'unsafe ZIP member')
        require(((item.external_attr >> 16) & 0o170000) != 0o120000, 'ZIP symlink')
    require(zipped.testzip() is None, 'ZIP CRC failure')
    return {name: dict(bytes=len(zipped.read(name)), sha256=hashlib.sha256(zipped.read(name)).hexdigest())
            for name in names if not name.endswith('/')}


def publication_copy():
    tick, cpu = time.monotonic(), time.process_time()
    expected = {
        'best-full-D-archive-upload-v1/RESULT.json': '91c233ff48bc35cd5cc4a97d372b425d45c11595f24051ea001fc0c4d3abab90',
        'best-full-D-asset-upload-v2/RESULT.json': 'cde8f4c7aafd00178ec0c103af3c4c865c287add27dc3db1498e1fd6c7a8ee22',
        'best-full-D-archive-launch-v1/receipt.json': 'c127b8898af0af0d3a721eddd97e2da306d8db9fe713ad158d2eeb7f9d733fac',
        'best-full-D-asset-launch-v2/receipt.json': 'd193694cf917adcca4cfdd75bd7d3dbaf0d03c5ad4fbe91c731713b23fa18bb9',
    }
    for relative, digest in expected.items():
        require(sha(BASE / relative) == digest, 'publication receipt identity mismatch')
    members = {}
    for dirname in ('best-full-D-archive-upload-v1', 'best-full-D-archive-launch-v1',
                    'best-full-D-asset-upload-v2', 'best-full-D-asset-launch-v2'):
        for path in sorted((BASE / dirname).iterdir()):
            if path.is_dir() or path.suffix == '.zip':
                continue
            require(path.is_file() and not path.is_symlink(), 'unexpected publication input')
            require(path.stat().st_size < 262144, 'unexpected large publication input')
            members[str(path.relative_to(BASE))] = path
    manifest = {name: dict(bytes=path.stat().st_size, sha256=sha(path), native_path=str(path))
                for name, path in members.items()}
    destination = OUT / 'full-D-publication-originals-v1.zip'
    with ZipFile(destination, 'x', compression=ZIP_DEFLATED) as zipped:
        for name, path in members.items():
            zipped.write(path, name)
        zipped.writestr('MANIFEST.json', json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    with ZipFile(destination) as zipped:
        checked = safe_members(zipped)
        for name, item in manifest.items():
            require(checked[name] == dict(bytes=item['bytes'], sha256=item['sha256']), 'copied publication differs')
    require(all(sha(path) == manifest[name]['sha256'] for name, path in members.items()), 'publication source changed')
    return dict(status='passed', archive=str(destination), bytes=destination.stat().st_size,
                sha256=sha(destination), members=len(checked), originals_unchanged=True,
                whole_stage_wall_seconds=time.monotonic()-tick, stage_CPU_seconds=time.process_time()-cpu,
                scope='Local read/hash/ZIP verification only; prior publication costs are nested in copied receipts, not incurred again.')


def download_artifact():
    tick = time.monotonic()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    target = OUT / 'science-run-42890048946-attempt1-artifact-13797877354.zip'
    row = dict(status='started', download_attempts=1, endpoint=ENDPOINT,
               expected_bytes=ARTIFACT_SIZE, expected_sha256=ARTIFACT_SHA,
               workflow_rerun=False, source_head='cd3b7ac49294174a98e02636247615534c19bd89',
               tested_merge='f63b067ac577a6eea363c37d1358f65dc7b4f4ba',
               source_and_merge_tree='4bb4995c3c1058d268c032a0d15cdfe9297a6ff8',
               identity_context='Run/head/tree context supplied and separately checked by root; this collector verifies the exact artifact bytes.')
    env = dict(os.environ)
    env.pop('GH_DEBUG', None)
    try:
        with target.open('xb') as stdout, (OUT / 'artifact-download.stderr').open('xb') as stderr:
            result = subprocess.run(['/usr/bin/gh', 'api', ENDPOINT], stdout=stdout, stderr=stderr,
                                    env=env, timeout=240)
        row['returncode'] = result.returncode
        require(result.returncode == 0, 'artifact download failed, no retry')
        require(target.stat().st_size == ARTIFACT_SIZE and sha(target) == ARTIFACT_SHA,
                'artifact exact byte identity mismatch')
        with ZipFile(target) as zipped:
            manifest = safe_members(zipped)
        save(OUT / 'ARTIFACT-MEMBERS.json', manifest)
        row.update(status='exact_artifact_bytes_verified', bytes=target.stat().st_size, sha256=sha(target),
                   members=len(manifest), CRC_duplicate_names_and_paths_passed=True)
    except Exception:
        row.update(status='failed_preserved_no_retry', error=traceback.format_exc())
        if target.exists():
            row.update(partial_bytes=target.stat().st_size, partial_sha256=sha(target))
    finally:
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(stage_wall_seconds=time.monotonic()-tick,
                   waited_gh_CPU_seconds=usage.ru_utime+usage.ru_stime-before.ru_utime-before.ru_stime)
        save(OUT / 'ARTIFACT-RECEIPT.json', row)
    return row


def main():
    OUT.mkdir(exist_ok=False)
    tick, cpu = time.monotonic(), time.process_time()
    report = dict(schema='science-artifact-and-publication-readonly-collection-v1',
                  started_utc=datetime.now(timezone.utc).isoformat(), source_sha256=sha(Path(__file__)),
                  training_steps=0, model_reads=0, release_mutations=0, automatic_retry=False,
                  overall_CI_claim='not_assessed; hosted science artifact alone cannot establish all CI', tasks={})
    for label, operation in (('publication_originals', publication_copy), ('science_artifact', download_artifact)):
        try:
            report['tasks'][label] = operation()
        except Exception:
            report['tasks'][label] = dict(status='failed_preserved_no_retry', error=traceback.format_exc())
    report.update(main_entry_wall_seconds=time.monotonic()-tick, main_CPU_seconds=time.process_time()-cpu,
                  absolute_own_CPU_seconds=time.process_time(),
                  finished_utc=datetime.now(timezone.utc).isoformat(), energy_joules=None)
    report['status'] = 'completed' if all(v['status'] in ('passed', 'exact_artifact_bytes_verified')
                                        for v in report['tasks'].values()) else 'failed_preserved'
    save(OUT / 'RESULT.json', report)
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
