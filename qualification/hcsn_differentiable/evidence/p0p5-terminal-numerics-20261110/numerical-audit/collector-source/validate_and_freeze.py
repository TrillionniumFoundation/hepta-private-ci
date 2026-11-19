"""Run metadata-only tests once against final source and freeze a source capsule."""
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time
import zipfile


ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = {str(p.relative_to(ROOT)): sha(p) for p in sorted(ROOT.rglob('*'))
              if p.is_file() and '__pycache__' not in p.parts}
    destination = ROOT / 'final-validation'
    destination.mkdir(exist_ok=False)
    argv = [sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(ROOT), '-p', 'test_*.py', '-v']
    start = time.monotonic()
    initial = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (destination/'stdout').open('wb') as stdout, (destination/'stderr').open('wb') as stderr:
        process = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=30)
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    record = {'schema': 'terminal-collector-metadata-validation-v1', 'argv': argv,
              'returncode': process.returncode, 'whole_child_wall_seconds': time.monotonic()-start,
              'waited_child_CPU_seconds': usage.ru_utime+usage.ru_stime-initial.ru_utime-initial.ru_stime,
              'peak_child_RSS_bytes': usage.ru_maxrss*1024, 'source_before': before,
              'source_unchanged': all(sha(ROOT/name)==digest for name,digest in before.items()),
              'stdout_sha256':sha(destination/'stdout'),'stderr_sha256':sha(destination/'stderr'),
              'expected_tests':14,'scope':'Metadata-only corruption tests; no trained model, oracle, forward, gradient or numerical fixture rerun.'}
    log = (destination/'stderr').read_text()
    record['passed'] = process.returncode == 0 and record['source_unchanged'] and 'Ran 14 tests in ' in log and '\nOK\n' in log
    (ROOT/'VALIDATION.json').write_text(json.dumps(record,indent=2,sort_keys=True)+'\n')
    if not record['passed']:
        raise SystemExit(1)
    members = {str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,'sha256':sha(p)}
               for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    (ROOT/'MANIFEST.json').write_text(json.dumps({'files':members},indent=2,sort_keys=True)+'\n')
    archive=ROOT.parent/(ROOT.name+'-program.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=9) as zipped:
        for path in sorted(ROOT.rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts:
                zipped.write(path,str(path.relative_to(ROOT)))
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:
            raise ValueError('source capsule CRC failed')
        for name,item in members.items():
            raw=zipped.read(name)
            if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
                raise ValueError('source capsule member differs')
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':sha(archive),
                      'manifest_sha256':sha(ROOT/'MANIFEST.json'),'validation_sha256':sha(ROOT/'VALIDATION.json'),
                      'tests_passed':14,'member_count':len(members)+1}))


if __name__ == '__main__':
    main()
