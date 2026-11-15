"""Single new stdlib validation stage, preserving complete test-child wall and wait4 cost."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from zipfile import ZipFile, ZIP_DEFLATED

program, pattern, target = Path(sys.argv[1]).resolve(), sys.argv[2], Path(sys.argv[3]).resolve()
target.mkdir(exist_ok=False)
source = target/'source'
source.mkdir()
def identity(path):
    raw = path.read_bytes()
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
for path in sorted(program.iterdir()):
    if path.is_file():
        shutil.copyfile(path, source/path.name)
before = {p.name:identity(p) for p in sorted(source.iterdir())}
(target/'SOURCE-MANIFEST.json').write_text(json.dumps({'files':before},indent=2,sort_keys=True)+'\n')
argv = [sys.executable,'-B','-m','unittest','discover','-s',str(source),'-p',pattern,'-v']
env = dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
with (target/'stdout').open('xb') as out, (target/'stderr').open('xb') as err:
    start = time.monotonic()
    child = subprocess.Popen(argv,cwd=source,env=env,stdout=out,stderr=err,start_new_session=True)
    killed = False
    while True:
        pid,status,usage = os.wait4(child.pid,os.WNOHANG)
        if pid:
            complete_wall = time.monotonic()-start
            child.returncode = os.waitstatus_to_exitcode(status)
            break
        if time.monotonic()-start > 30 and not killed:
            os.killpg(child.pid,signal.SIGKILL)
            killed = True
        time.sleep(.01)
after = {p.name:identity(p) for p in sorted(source.iterdir()) if p.is_file()}
receipt = {'schema':'c2-resource-rebuild-stage-validation-v2','returncode':child.returncode,'timed_out':killed,
    'scope':'New final v2 synthetic metadata tests; complete flat program/config bytes copied and bound. No inherited lost24-test credit, actual C2, model, oracle or E access.',
    'complete_flat_program_config_copied':True,
    'whole_test_child_wall_seconds':complete_wall,'wait4_test_child_CPU_seconds':usage.ru_utime+usage.ru_stime,
    'wait4_test_child_peak_RSS_bytes':usage.ru_maxrss*1024,'source_before':before,'source_after':after,
    'source_unchanged':before==after,'argv':argv,'python':sys.version,'stdout':identity(target/'stdout'),
    'stderr':identity(target/'stderr'),'timing_scope':'Popen-before through actual wait4; subsequent driver archive/receipt work is excluded.'}
(target/'RESULT.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
shutil.copyfile(Path(__file__),target/'validation_driver.py')
members = {str(p.relative_to(target)):identity(p) for p in sorted(target.rglob('*')) if p.is_file()}
(target/'MEMBER-MANIFEST.json').write_text(json.dumps({'files':members},indent=2,sort_keys=True)+'\n')
archive = Path(str(target)+'.zip')
with ZipFile(archive,'x',compression=ZIP_DEFLATED) as zipped:
    for path in sorted(target.rglob('*')):
        if path.is_file():
            zipped.write(path,str(path.relative_to(target)))
with ZipFile(archive) as zipped:
    assert zipped.testzip() is None
    for name,item in members.items():
        raw = zipped.read(name)
        assert {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()} == item
print(json.dumps({'returncode':child.returncode,'source_unchanged':before==after,
    'whole_test_child_wall_seconds':complete_wall,'wait4_test_child_CPU_seconds':receipt['wait4_test_child_CPU_seconds'],
    'receipt':identity(target/'RESULT.json'),'archive':identity(archive)}))
raise SystemExit(child.returncode)

