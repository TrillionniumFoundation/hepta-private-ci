"""Frozen one-attempt supervisor. Invoke only after independent source admission."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

ROOT = Path(__file__).resolve().parent
LOCK = Path('/workspace/shared/rgb-class-preservation-20261030/benchmark.lock')
CAP = 4*1024*1024

def encode(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode('ascii')

def bounded(path, cap):
    if path.is_symlink() or not path.is_file():
        raise ValueError('artifact_type')
    with path.open('rb') as f:
        raw=f.read(cap+1)
    if len(raw)>cap:
        raise ValueError('artifact_cap')
    return raw

def main():
    if not sys.flags.isolated or not sys.flags.no_site or not sys.dont_write_bytecode:
        return 2
    freeze=json.loads(bounded(ROOT/'FREEZE.json',16384))
    for name,digest in freeze.items():
        if hashlib.sha256(bounded(ROOT/name,2*1024*1024)).hexdigest()!=digest:
            return 2
    inputs=json.loads(bounded(ROOT/'INPUTS.json',16384))
    output=ROOT/'RUN_ONCE'
    # Exclusive reservation consumes the attempt even on subsequent failure.
    output.mkdir()
    receipt={'source':inputs['source'],'passed':False,'category':'supervisor_failure','children_started':0,'children_reaped':0,'complete_wait':False}
    start=time.monotonic()
    pid=None; reaped=False; status=None; usage=None; killed=False
    try:
        with LOCK.open('rb') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            pid=os.fork()
            if pid==0:
                try:
                    resource.setrlimit(resource.RLIMIT_CPU,(4,4))
                    resource.setrlimit(resource.RLIMIT_AS,(128*2**20,128*2**20))
                    resource.setrlimit(resource.RLIMIT_FSIZE,(2*2**20,2*2**20))
                    signal.alarm(30)
                    with open(os.devnull,'wb') as null:
                        os.dup2(null.fileno(),1);os.dup2(null.fileno(),2)
                    bootstrap='import sys; sys.path.insert(0, '+repr(str(ROOT))+'); import worker; sys.exit(worker.run())'
                    os.execv(sys.executable,[sys.executable,'-I','-S','-B','-c',bootstrap])
                except BaseException:
                    os._exit(120)
            receipt['children_started']=1
            try:
                while True:
                    child,status,usage=os.wait4(pid,os.WNOHANG)
                    if child:
                        reaped=True;break
                    if time.monotonic()-start>=32:
                        killed=True
                        os.kill(pid,signal.SIGKILL)
                        _,status,usage=os.wait4(pid,0)
                        reaped=True;break
                    time.sleep(0.02)
            finally:
                if not reaped:
                    try: os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    _,status,usage=os.wait4(pid,0)
                    reaped=True;killed=True
            receipt.update(children_reaped=1,complete_wait=True,child_exit=os.waitstatus_to_exitcode(status),killed=killed,child_cpu_seconds=usage.ru_utime+usage.ru_stime,child_peak_rss_kib=usage.ru_maxrss)
            # Management-only byte binding: no records or manifest parsed here.
            inventory={}
            for path in sorted(output.rglob('*')):
                if path.is_symlink(): raise ValueError('artifact_type')
                if path.is_file():
                    raw=bounded(path,2*1024*1024)
                    inventory[str(path.relative_to(output))]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            used=sum(x['bytes'] for x in inventory.values())
            if used>CAP-65536: raise ValueError('output_cap')
            result=json.loads(bounded(output/'RESULT.json',16384))
            if result.get('source')!=inputs['source'] or type(result.get('passed')) is not bool:
                raise ValueError('result_schema')
            if result['passed']:
                marker=json.loads(bounded(output/'private_manager/COMPLETE.json',8192))
                expected={'TRAIN/records.jsonl','management/selection.jsonl','management/final.jsonl','management/manifest.json','PUBLIC_RECEIPT.json'}
                if set(marker)!=expected: raise ValueError('completion_schema')
                if set(inventory)!={'RESULT.json','private_manager/COMPLETE.json'}|{'private_manager/'+n for n in expected}: raise ValueError('inventory_schema')
                for name,binding in marker.items():
                    if inventory['private_manager/'+name]!=binding: raise ValueError('binding_mismatch')
                # Only the reviewed child produces this aggregate schema.
                public=json.loads(bounded(output/'private_manager/PUBLIC_RECEIPT.json',16384))
                if public!=result.get('aggregate'): raise ValueError('public_binding')
                receipt['aggregate']=public
                receipt['attribution']=inputs['attribution']
            allowed={'complete','compressed_cap','source_identity','gzip','decoded_cap','gzip_boundary','newline','row_count','row_length','integer_csv','range','conflicting_group','minimum_groups','output_cap','artifact_set','output_directory','artifact_type','artifact_cap','completion_json','completion_schema','binding_schema','binding_mismatch','documentary_identity','io_failure','resource_failure','internal_failure'}
            category=result.get('category')
            receipt['category']=category if category in allowed else 'internal_failure'
            receipt['inventory']=inventory
            receipt['retained_bytes_before_receipt']=used
            receipt['passed']=receipt['child_exit']==0 and not killed and result['passed'] and category=='complete'
    except BaseException:
        receipt['passed']=False
        receipt['category']='supervisor_failure'
        if pid is not None and not reaped:
            try: os.kill(pid,signal.SIGKILL)
            except ProcessLookupError: pass
            _,status,usage=os.wait4(pid,0)
            reaped=True
            receipt.update(children_reaped=1,complete_wait=True,child_exit=os.waitstatus_to_exitcode(status),child_cpu_seconds=usage.ru_utime+usage.ru_stime)
    receipt.update(wall_observed_prefix_seconds=time.monotonic()-start,parent_cpu_observed_prefix_seconds=time.process_time(),parent_final_tail='Unknown, nonzero; serialization/write/teardown and review/tool work excluded. No strict aggregate CPU or wall proof.',limits={'child_CPU_seconds':4,'child_wall_seconds':30,'supervisor_kill_after_seconds':32,'child_AS_bytes':128*2**20,'child_file_bytes':2*2**20,'retained_bytes':CAP},training_authorized=False)
    raw=encode(receipt)
    if len(raw)>49152: return 2
    with (output/'WAIT4_RECEIPT.json').open('xb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    return 0 if receipt['passed'] else 1

if __name__=='__main__':
    try:
        code=main()
    except BaseException:
        code=2
    sys.exit(code)
