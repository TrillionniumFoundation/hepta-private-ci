"""Fetch two pinned Git blobs and run one new, isolated native review."""

from datetime import datetime, timezone
import base64
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import traceback

base = Path('/home/qian-qi/hepta-hcsn-core-study-20261110-c385-training')
out = base / 'baseline36-c1-review-bootstrap-v2'
out.mkdir(exist_ok=False)
started = time.monotonic()
cpu0 = resource.getrusage(resource.RUSAGE_CHILDREN)
report = {'schema': 'pinned-Git-blob-review-bootstrap-v2',
          'started_utc': datetime.now(timezone.utc).isoformat(),
          'original_upload_stage_unchanged': True,
          'stable_review_key': 'hcsn-baseline36-c1-independent-review-c385-v2',
          'files': [], 'native_review_started': False}
source = sys.orig_argv[sys.orig_argv.index('-c') + 1]
(out / 'bootstrap-source.py').write_text(source)
report['bootstrap_source_sha256'] = hashlib.sha256(source.encode()).hexdigest()
items = [
    ('6e1c204a063b39f1fff14c405c09d153fe3ca57f', 'baseline36-c1-independent-reviewer-program-v2.zip', 174435,
     '6ede11014d33e219f6ebc109911ad50a8550bb585388b16b5c604a2d4cb54c51'),
    ('7c1d5728af45e5f3c337b6f1b724a47eaa720580', 'launch_baseline36_c1_review_v2.py', 5768,
     '94be43962ba77b72cc99ae12ea057dc8af6318e17908c496718828819ae6d6f4'),
]
try:
    for blob, filename, size, digest in items:
        argv = ['/usr/bin/gh', 'api', 'repos/TrillionniumFoundation/hepta-private-ci/git/blobs/' + blob]
        point = time.monotonic()
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, check=False)
        (out / (blob + '.json')).write_bytes(result.stdout)
        (out / (blob + '.stderr')).write_bytes(result.stderr)
        if result.returncode != 0:
            raise ValueError('Git blob retrieval failed; inspect retained stderr')
        value = json.loads(result.stdout)
        data = base64.b64decode(value['content'])
        if value['sha'] != blob or value['size'] != size or len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('pinned Git blob identity mismatch')
        path = base / filename
        with path.open('xb') as stream:
            stream.write(data)
        report['files'].append({'blob': blob, 'path': str(path), 'bytes': size, 'sha256': digest,
                                'download_wall_seconds': time.monotonic() - point, 'write': 'exclusive'})
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(download_phase_wall_seconds=time.monotonic() - started,
                  download_phase_waited_children_cpu_seconds=usage.ru_utime + usage.ru_stime - cpu0.ru_utime - cpu0.ru_stime)
    (out / 'download-receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    argv = [sys.executable, '-B', str(base / 'launch_baseline36_c1_review_v2.py')]
    report.update(native_review_started=True, argv=argv)
    result = subprocess.run(argv, cwd=base, check=False, timeout=1900)
    report.update(returncode=result.returncode, status='completed' if result.returncode == 0 else 'failed')
except Exception:
    report.update(status='bootstrap_failed', error=traceback.format_exc(), returncode=None)
finally:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    report.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                  complete_bootstrap_wall_seconds=time.monotonic() - started,
                  complete_waited_children_cpu_seconds=usage.ru_utime + usage.ru_stime - cpu0.ru_utime - cpu0.ru_stime,
                  scope='Bootstrap complete timers include downloads and nested review launcher/child. Do not add them to nested review totals.')
    (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
raise SystemExit(report['returncode'] if report.get('returncode') is not None else 1)
