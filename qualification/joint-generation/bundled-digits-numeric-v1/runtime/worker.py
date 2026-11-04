"""One bounded synthetic test worker. Imports numerical code only inside run."""
import hashlib,json,math,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

CACHE_PREFIX=str(ROOT/'BYTECODE_DISABLED')

def audit(event,args):
    if event=='open' and isinstance(args[0],(str,bytes)) and os.fsdecode(args[0]).endswith('.pyc'):
        raise PermissionError('bytecode_forbidden')
    if event in ('os.fork','os.forkpty','os.posix_spawn','subprocess.Popen','os.system','socket.__new__','os.exec'):
        raise RuntimeError('forbidden_process_or_network')

def run():
    if sys.pycache_prefix!=CACHE_PREFIX or Path(CACHE_PREFIX).exists() or Path(CACHE_PREFIX).is_symlink():return 2
    sys.addaudithook(audit)
    result={'passed':False,'category':'internal_failure','synthetic_only':True}
    try:
        import numpy as np
        import tests
        if np.__version__!='2.3.5':raise ValueError('version')
        if len(list(Path('/proc/self/task').iterdir()))!=1:raise ValueError('threads')
        result['diagnostics']=tests.run(json.loads((ROOT/'FIXTURES.json').read_text()))
        if len(list(Path('/proc/self/task').iterdir()))!=1:raise ValueError('threads')
        result.update(passed=True,category='complete',numpy_version=np.__version__,worker_threads=1)
    except AssertionError as exc:
        # Codes originate exclusively from frozen tests, never raw tensors/data.
        result['category']='assertion_failure';result['assertion']=str(exc)[:64]
    except BaseException:
        result['category']='internal_failure'
    if not result['passed'] and 'tests' in sys.modules:
        result['partial_diagnostics']=sys.modules['tests'].STATE
    # Explicit bounded nonfinite tags retain ordinary diagnostic failures.
    # Unknown types, depth/size breaches or serialization resource failure yield
    # a small failure receipt, never an invented numerical PASS.
    nodes=[0];nonfinite=[False]
    def safe(value,depth=0):
        nodes[0]+=1
        if nodes[0]>20000 or depth>10:raise ValueError('diagnostic_bound')
        if value is None or type(value) in (bool,int):return value
        if type(value) is float:
            if math.isfinite(value):return value
            nonfinite[0]=True
            return {'nonfinite':'nan' if math.isnan(value) else ('positive_infinity' if value>0 else 'negative_infinity')}
        if type(value) is str and len(value)<=256:return value
        if type(value) is list and len(value)<=128:return [safe(v,depth+1) for v in value]
        if type(value) is dict and len(value)<=64 and all(type(k) is str and len(k)<=64 for k in value):return {k:safe(v,depth+1) for k,v in value.items()}
        raise ValueError('diagnostic_type')
    try:
        clean=safe(result)
        if nonfinite[0]:clean.update(passed=False,category='nonfinite_diagnostic');result['passed']=False
        raw=(json.dumps(clean,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode('ascii')
        if len(raw)>256*1024:raise ValueError('diagnostic_size')
    except BaseException:
        result['passed']=False
        raw=b'{"passed":false,"category":"diagnostic_serialization_failure","numerical_results_retained":false}\n'
    with (ROOT/'RUN_ONCE'/'RESULT.json').open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return 0 if result['passed'] else 1
