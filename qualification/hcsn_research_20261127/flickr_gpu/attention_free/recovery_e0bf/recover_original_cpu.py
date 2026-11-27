"""Resume the original attention-free controller with one independently allocated CPU."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def preserve(path,data):
    if path.exists():
        if path.read_bytes()!=data:raise ValueError('existing receipt disagrees: '+str(path.name))
    else:
        with path.open('xb') as out:out.write(data)


def main():
    cli=argparse.ArgumentParser();cli.add_argument('root',type=Path);cli.add_argument('cpu',type=int);cli.add_argument('original_session');args=cli.parse_args()
    root=args.root.resolve();base=root/'attention_free';src=base/'src';rec=base/'recovery_e0bf';orig=args.original_session
    if not orig.startswith('dpty-') or not orig[5:].isalnum():raise ValueError('invalid original session ID')
    orig_path=Path.home()/'.local/state/hepta-runtime-mac-worker/terminals'/orig
    terminal=json.loads((orig_path/'exit.json').read_text());assert terminal['state']=='exited' and terminal['exit_code']==1
    trace=(orig_path/'output.log').read_bytes();assert b'tied_edit/summary.json' in trace and b'TimeoutError' in trace
    pre=json.loads((rec/'preflight.json').read_text());qual=base/'qualification.json';assert digest(qual)==pre['source_hashes']['qualification.json']
    for name,h in pre['source_hashes'].items():assert digest(qual if name=='qualification.json' else src/name)==h
    assert digest(base/'external/manifest.json')==pre['external_manifest_sha256']
    assert digest(base/'external/external.npz')==pre['external_arrays_sha256']
    for name in ['costs.jsonl','worker.log']:
        dst=rec/('before_recovery_'+name)
        if not dst.exists():preserve(dst,(base/name).read_bytes())
    assert digest(rec/'before_recovery_costs.jsonl')==pre['prior_costs_sha256']
    preserve(rec/'original_exit.json',json.dumps({k:terminal[k] for k in ['state','exit_code','created_unix_ms','pid','owner_pid']},sort_keys=True).encode()+b'\n')
    preserve(rec/'original_timeout.log',trace)
    assert args.cpu in os.sched_getaffinity(0);os.sched_setaffinity(0,{args.cpu});assert os.sched_getaffinity(0)=={args.cpu}
    os.environ.update(HEPTA_FLICKR_ROOT=str(root),OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',ROCR_VISIBLE_DEVICES='',PYTHONUNBUFFERED='1',PYTHONDONTWRITEBYTECODE='1')
    sys.path.insert(0,str(src));spec=importlib.util.spec_from_file_location('original_attention_free_controller',src/'run.py');controller=importlib.util.module_from_spec(spec);spec.loader.exec_module(controller)
    assert controller.ROOT==root and controller.BASE==base and controller.RESULT==base/'results'
    original_wait=controller.wait_for;gate=root/'tied_edit/summary.json'
    def wait_scoped(path,seconds):
        if path==gate and seconds==33000 and not path.exists():
            assert os.sched_getaffinity(0)=={args.cpu}
            event={'source_run_sha256':digest(src/'run.py'),'source_recovery_sha256':digest(Path(__file__)),'time_utc':datetime.now(timezone.utc).isoformat(),'cpu':args.cpu,'original_session':orig,'original_exit_code':1,'original_timeout_trace_sha256':digest(rec/'original_timeout.log'),'released_wait':'tied_edit/summary.json','registered_wait_seconds':33000,'reason':'independently allocated idle logical CPU; original resource-queue wait already expired','preserved_lock':'attention_free/worker.lock','experimental_change':'none'}
            with (rec/'recovery_events.jsonl').open('a') as f:f.write(json.dumps(event,sort_keys=True)+'\n')
            print('released expired scheduling wait under original lock',event['time_utc'],'CPU',args.cpu,flush=True)
            return
        return original_wait(path,seconds)
    if not gate.exists():controller.wait_for=wait_scoped
    print('entering original serial CPU controller',controller.ROOT,'affinity',sorted(os.sched_getaffinity(0)),flush=True)
    controller.main()
    print('original summary',digest(base/'summary.json'),flush=True)


if __name__=='__main__':main()
