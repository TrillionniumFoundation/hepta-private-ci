"""Single terminal-only metadata collector launch, after the original audit exits."""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import stat
import subprocess
import sys
import time
import traceback
import zipfile


BASE = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
LAUNCH = BASE / 'numerics-terminal-postmortem-launch-v1'
PROGRAM = BASE / 'numerics-terminal-postmortem-program-v1'
OUTPUT = BASE / 'numerics-terminal-postmortem-v1'
KEY = 'hcsn-terminal-numerics-postmortem-c385-v1'
BLOB = 'e1318d30f975b409942f71b283db22c98ea1a0cf'
CAPSULE_SHA = '442196e551dffe877fedcef3ac25c5dd0de19010273692ffdee851fef61a6846'
MANIFEST_SHA = '365fdb5fda26e7bdc10b4f99cee5c58d2846c35a363b2c621dffdca85d2f4628'


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


started, own_cpu = time.monotonic(), time.process_time()
usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
report = {'schema': 'terminal-numerics-metadata-bootstrap-v1', 'stable_key': KEY,
          'started_utc': datetime.now(timezone.utc).isoformat(),
          'no_model_or_oracle_execution': True, 'numeric_retry_count': 0,
          'original_numerical_budget_extended': False, 'metadata_child_ceiling_seconds': 600,
          'metadata_child_address_limit_bytes': 2147483648,
          'program_zip_sha256': CAPSULE_SHA, 'program_blob': BLOB,
          'python': sys.version}
LAUNCH.mkdir(parents=True, exist_ok=False)
source = Path(__file__).read_text() if '__file__' in globals() else sys.orig_argv[sys.orig_argv.index('-c')+1]
(LAUNCH/'source.py').write_text(source)
report['source_sha256'] = sha(LAUNCH/'source.py')
save(LAUNCH/'launch.json', report)
try:
    original_launch = BASE/'numerics-final-audit-launch-v1/receipt.json'
    original_bootstrap = BASE/'numerics-final-audit-bootstrap-v1/receipt.json'
    original = json.loads(original_launch.read_bytes())
    old_bootstrap = json.loads(original_bootstrap.read_bytes())
    require(original.get('pid') == 1969758 and original.get('status') in ('completed','failed','whole_budget_exhausted'), 'original audit is not terminal')
    require(original.get('hard_whole_wall_seconds') == 10800, 'original ceiling differs')
    require(type(original.get('returncode')) is int and old_bootstrap.get('returncode') in (0,1), 'original exit evidence is incomplete')
    report['original_terminal_receipt_identities'] = {
        str(path): {'bytes': path.stat().st_size, 'sha256': sha(path)}
        for path in (original_launch, original_bootstrap)}
    require(not PROGRAM.exists() and not OUTPUT.exists(), 'new collector paths already exist')
    download_start = time.monotonic()
    with (LAUNCH/'git-response.json').open('wb') as stdout, (LAUNCH/'git.stderr').open('wb') as stderr:
        fetched = subprocess.run(['/usr/bin/gh','api','repos/TrillionniumFoundation/hepta-private-ci/git/blobs/'+BLOB],
                                 stdout=stdout, stderr=stderr, timeout=90)
    require(fetched.returncode == 0, 'source blob download failed')
    blob = json.loads((LAUNCH/'git-response.json').read_bytes())
    require(blob.get('sha') == BLOB and blob.get('encoding') == 'base64', 'Git blob identity differs')
    data = base64.b64decode(''.join(blob['content'].split()), validate=True)
    require(len(data) == 35529 and hashlib.sha256(data).hexdigest() == CAPSULE_SHA, 'source capsule bytes differ')
    capsule = LAUNCH/'program.zip'
    capsule.write_bytes(data)
    PROGRAM.mkdir(exist_ok=False)
    with zipfile.ZipFile(capsule) as zipped:
        require(zipped.testzip() is None, 'source capsule CRC failed')
        require(sum(item.file_size for item in zipped.infolist()) < 1048576, 'source capsule expansion differs')
        for item in zipped.infolist():
            member = Path(item.filename)
            require(not member.is_absolute() and '..' not in member.parts and not item.is_dir(), 'unsafe source member')
            require(stat.S_IFMT(item.external_attr >> 16) != stat.S_IFLNK, 'source capsule contains symlink')
            target = PROGRAM/member
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as handle:
                handle.write(zipped.read(item.filename))
    require(sha(PROGRAM/'MANIFEST.json') == MANIFEST_SHA, 'collector manifest differs')
    manifest = json.loads((PROGRAM/'MANIFEST.json').read_bytes())
    for name, item in manifest['files'].items():
        require((PROGRAM/name).stat().st_size == item['bytes'] and sha(PROGRAM/name) == item['sha256'], 'collector source member differs')
    report['download_phase_wall_seconds'] = time.monotonic()-download_start
    report['downloaded_members_verified'] = len(manifest['files'])
    save(LAUNCH/'download-receipt.json', report)
    argv = ['/usr/bin/python3','-B',str(PROGRAM/'collect_terminal.py'),'--output',str(OUTPUT)]
    child_start = time.monotonic()
    usage_child0 = resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    def limits():
        resource.setrlimit(resource.RLIMIT_AS, (2147483648, 2147483648))
    with (LAUNCH/'stdout').open('wb') as stdout, (LAUNCH/'stderr').open('wb') as stderr:
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True,
                                   preexec_fn=limits, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        report.update(metadata_argv=argv, metadata_pid=process.pid,
                      metadata_started_utc=datetime.now(timezone.utc).isoformat())
        save(LAUNCH/'collector-start.json', report)
        try:
            process.wait(timeout=600)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(metadata_returncode=process.returncode, metadata_timed_out=timed_out,
                  whole_metadata_child_wall_seconds=time.monotonic()-child_start,
                  metadata_waited_child_CPU_seconds=usage.ru_utime+usage.ru_stime-usage_child0.ru_utime-usage_child0.ru_stime)
    require(process.returncode == 0 and not timed_out, 'metadata collector did not complete')
    receipt = json.loads((OUTPUT/'COLLECTION-RECEIPT.json').read_bytes())
    require(receipt['metadata_collection_status'] == 'completed', 'metadata finality receipt is incomplete')
    archive = Path(receipt['archive']['path'])
    require(sha(archive) == receipt['archive']['sha256'], 'metadata archive differs from completed receipt')
    report.update(status='completed_metadata_collection', archive=receipt['archive'],
                  collection_receipt_sha256=sha(OUTPUT/'COLLECTION-RECEIPT.json'))
    require(all(sha(PROGRAM/name)==item['sha256'] for name,item in manifest['files'].items()), 'collector source changed')
except Exception:
    report.update(status='metadata_collection_failed', error=traceback.format_exc())
finally:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                  bootstrap_wall_sample_seconds=time.monotonic()-started,
                  bootstrap_own_CPU_sample_seconds=time.process_time()-own_cpu,
                  bootstrap_waited_children_CPU_seconds=usage.ru_utime+usage.ru_stime-usage0.ru_utime-usage0.ru_stime,
                  bootstrap_children_peak_RSS_bytes=usage.ru_maxrss*1024,
                  timing_scope='Metadata bootstrap sample before final serialization; download and collector timers are nested. No original audit CPU is included.')
    for name in ('stdout','stderr'):
        path=LAUNCH/name
        report[name]={'bytes':path.stat().st_size,'sha256':sha(path)} if path.exists() else {'missing':True}
    save(LAUNCH/'receipt.json', report)
    print(json.dumps({key:report.get(key) for key in ('status','stable_key','archive','error')}), flush=True)
raise SystemExit(0 if report['status']=='completed_metadata_collection' else 1)
