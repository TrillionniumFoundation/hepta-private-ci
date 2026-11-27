"""Two bounded verification phases, preserving pre-fix observations and exact costs."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time


HERE = Path(__file__).parent
OUTPUT = HERE/'evidence/reset-snapshot-20261119'


def main(phase):
    OUTPUT.mkdir(parents=True,exist_ok=True)
    cost_path = OUTPUT/(phase+'-cost.json')
    if cost_path.exists():
        raise FileExistsError('verification phase already recorded')
    old = json.loads((OUTPUT/'before-cost.json').read_text()) if phase == 'after' else {'cpu_seconds':0.,'wall_seconds':0.}
    cpu_limit = min(4 if phase == 'before' else 13,math.floor(20-old['cpu_seconds']-1)-1)
    wall_limit = min(8 if phase == 'before' else 30,40-old['wall_seconds']-1)
    if cpu_limit < 1 or wall_limit < 1:
        raise RuntimeError('combined verification budget exhausted')
    code = """import hashlib,json,torch,unittest
from pathlib import Path
torch.set_num_threads(1);torch.set_num_interop_threads(1)
from qualification.hcsn_currentstate.test_reset_snapshot import observe
rows=[observe(kind) for kind in ('atom','flux')]
p=Path('qualification/hcsn_currentstate')
result={'observations':rows,'kernel_sha256':hashlib.sha256((p/'differentiable.py').read_bytes()).hexdigest(),
        'torch':torch.__version__,'threads':torch.get_num_threads(),'interop_threads':torch.get_num_interop_threads()}
"""
    if phase == 'after':
        code += """suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in
 ['qualification.hcsn_currentstate.test_differentiable','qualification.hcsn_currentstate.test_reset_snapshot'])
run=unittest.TextTestRunner(verbosity=2).run(suite)
result.update(tests_run=run.testsRun,tests_successful=run.wasSuccessful())
"""
    code += f"\noutput=p/'evidence/reset-snapshot-20261119/{phase}-observations.json'\n"
    code += "with output.open('x') as stream:json.dump(result,stream,sort_keys=True,indent=2);stream.write('\\n')\n"
    if phase == 'after':
        code += "raise SystemExit(0 if run.wasSuccessful() else 1)\n"
    env = {**os.environ,**{key:'1' for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS')}}
    def constrain():
        resource.setrlimit(resource.RLIMIT_AS,(4*1024**3,)*2)
        resource.setrlimit(resource.RLIMIT_CPU,(cpu_limit,cpu_limit+1))
    started = time.monotonic()
    process = subprocess.Popen([sys.executable,'-c',code],cwd=HERE.parents[1],env=env,
                               stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,preexec_fn=constrain)
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    censored = False
    try:
        stdout,stderr = process.communicate(timeout=wall_limit)
    except subprocess.TimeoutExpired:
        process.kill();stdout,stderr=process.communicate();censored=True
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    (OUTPUT/(phase+'.stdout')).write_text(stdout);(OUTPUT/(phase+'.stderr')).write_text(stderr)
    report = {'phase':phase,'returncode':process.returncode,'censored_wall':censored,
              'wall_seconds':time.monotonic()-started,'cpu_seconds':after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
              'cpu_soft_limit':cpu_limit,'cpu_hard_limit':cpu_limit+1,'wall_limit':wall_limit,
              'source_sha256':{name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in
                               ('differentiable.py','test_reset_snapshot.py','check_reset_snapshot.py')}}
    cost_path.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    print(json.dumps(report,sort_keys=True))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=('before','after'))
    main(parser.parse_args().phase)
