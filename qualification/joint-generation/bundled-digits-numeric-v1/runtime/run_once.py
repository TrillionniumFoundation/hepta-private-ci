"""Adapted from independently reviewed real-partition supervisor; no data inputs."""
import fcntl,hashlib,json,os,resource,signal,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
LOCK=Path('/workspace/shared/rgb-class-preservation-20261030/benchmark.lock')
CAP=4*2**20
CACHE_PREFIX=str(ROOT/'BYTECODE_DISABLED')

def bounded(path,cap):
    if path.is_symlink() or not path.is_file():raise ValueError('file_type')
    with path.open('rb') as f:raw=f.read(cap+1)
    if len(raw)>cap:raise ValueError('file_cap')
    return raw

def main():
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:return 2
    if sys.pycache_prefix!=CACHE_PREFIX or Path(CACHE_PREFIX).exists() or Path(CACHE_PREFIX).is_symlink():return 2
    resource.setrlimit(resource.RLIMIT_CPU,(4,4));resource.setrlimit(resource.RLIMIT_AS,(256*2**20,256*2**20));resource.setrlimit(resource.RLIMIT_FSIZE,(2*2**20,2*2**20))
    output=ROOT/'RUN_ONCE';output.mkdir() # Consumes attempt before all validation.
    receipt={'passed':False,'category':'supervisor_failure','children_started':0,'children_reaped':0,'complete_wait':False}
    start=time.monotonic();pid=None;reaped=False;killed=False
    try:
        freeze=json.loads(bounded(ROOT/'FREEZE.json',16384))
        for name,digest in freeze.items():
            if hashlib.sha256(bounded(ROOT/name,2*2**20)).hexdigest()!=digest:raise ValueError('source_binding')
        admission=json.loads(bounded(ROOT/'SOURCE_PASS.json',16384))
        if admission.get('verdict')!='PASS' or admission.get('freeze_sha256')!=hashlib.sha256(bounded(ROOT/'FREEZE.json',16384)).hexdigest():raise ValueError('source_review')
        runtime=json.loads(bounded(ROOT/'RUNTIME.json',2*2**20))
        if str(Path(sys.executable).resolve())!=runtime['executable']:raise ValueError('executable')
        for path,digest in runtime['files'].items():
            with open(path,'rb') as f:
                h=hashlib.file_digest(f,'sha256').hexdigest()
            if h!=digest:raise ValueError('runtime_binding')
        with LOCK.open('rb') as lock:
            st=os.fstat(lock.fileno())
            if (st.st_dev,st.st_ino)!=(27,536619):raise ValueError('lock_identity')
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            pid=os.fork()
            if pid==0:
                try:
                    resource.setrlimit(resource.RLIMIT_CPU,(4,4));resource.setrlimit(resource.RLIMIT_AS,(256*2**20,256*2**20));resource.setrlimit(resource.RLIMIT_FSIZE,(2*2**20,2*2**20));signal.alarm(30)
                    with open(os.devnull,'wb') as null:os.dup2(null.fileno(),1);os.dup2(null.fileno(),2)
                    env={'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','VECLIB_MAXIMUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1','LANG':'C','LC_ALL':'C'}
                    bootstrap='import sys; sys.path[:0]='+repr([str(ROOT),runtime['site']])+'; import worker; sys.exit(worker.run())'
                    os.execve(sys.executable,[sys.executable,'-I','-S','-B','-X','pycache_prefix='+CACHE_PREFIX,'-c',bootstrap],env)
                except BaseException:os._exit(120)
            receipt['children_started']=1;launched=time.monotonic()
            try:
                while True:
                    child,status,usage=os.wait4(pid,os.WNOHANG)
                    if child:reaped=True;break
                    if time.monotonic()-launched>=32:
                        killed=True;os.kill(pid,signal.SIGKILL);_,status,usage=os.wait4(pid,0);reaped=True;break
                    time.sleep(.02)
            finally:
                if not reaped:
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    _,status,usage=os.wait4(pid,0);reaped=True;killed=True
            receipt.update(children_reaped=1,complete_wait=True,child_exit=os.waitstatus_to_exitcode(status),killed=killed,child_cpu_seconds=usage.ru_utime+usage.ru_stime,child_peak_rss_kib=usage.ru_maxrss)
            inventory={}
            for path in output.iterdir():
                raw=bounded(path,2*2**20);inventory[path.name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            if set(inventory)!={'RESULT.json'}:raise ValueError('inventory')
            if sum(v['bytes'] for v in inventory.values())>CAP-65536:raise ValueError('output_cap')
            result=json.loads(bounded(output/'RESULT.json',256*1024))
            receipt.update(category=result['category'],inventory=inventory,passed=receipt['child_exit']==0 and not killed and result.get('passed') is True and result.get('category')=='complete')
    except BaseException:
        receipt['passed']=False
    receipt.update(wall_observed_prefix_seconds=time.monotonic()-start,parent_cpu_observed_prefix_seconds=time.process_time(),parent_final_tail='Unknown nonzero; not strict total CPU. Tool/source/review work additional unknown.',limits={'child_CPU_seconds':4,'child_wall_seconds':30,'kill_after_seconds':32,'child_AS_bytes':256*2**20,'file_bytes':2*2**20,'retained_bytes':CAP,'supervisor_CPU_seconds':4},real_training_authorized=False)
    raw=(json.dumps(receipt,sort_keys=True,separators=(',',':'))+'\n').encode('ascii')
    if len(raw)>49152:return 2
    with (output/'WAIT4_RECEIPT.json').open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    return 0 if receipt['passed'] else 1
if __name__=='__main__':
    try:code=main()
    except BaseException:code=2
    sys.exit(code)
