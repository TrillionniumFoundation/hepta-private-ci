"""Fresh-Python action-boundary replay qualification; no mid-action/Rust claim."""
import time
ENTRY_WALL, ENTRY_CPU = time.perf_counter(), time.process_time()
import argparse
from concurrent.futures import ThreadPoolExecutor
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
from . import continuous_task_adapter as adapter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = HERE/'evidence/continuous_task_prepared_final2/qualification/RAW.json.gz'
PREPARED = RAW.parent.parent
MODULE = 'tools.hcsn.digital_read_followup_20261101.continuous_cold_replay'


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path=Path(path);raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    with path.open('xb') as stream:stream.write(gzip.compress(data,mtime=0) if path.suffix=='.gz' else data)
    return digest(path)


def input_hashes(raw):
    result=adapter.source_hashes()
    paths=[HERE/'continuous_cold_replay.py',HERE/'continuous_cold_protocol.json',RAW,PREPARED/'PREPARED_FREEZE.json']
    paths += [PREPARED/f'fit_{fit}_continuous_optin.json.gz' for fit in (11,23,37,53,71)]
    result.update({str(p.relative_to(ROOT)):digest(p) for p in paths})
    for cohort in raw['cohorts']:
        for name,expected in cohort['files'].items():
            path=RAW.parent/'worlds'/name
            if digest(path)!=expected:raise ValueError('archived world digest mismatch: '+name)
            result[str(path.relative_to(ROOT))]=expected
    return result


def prepare(out):
    protocol=read(HERE/'continuous_cold_protocol.json')
    if digest(RAW)!=protocol['input_sha256']:raise ValueError('declared input SHA mismatch')
    raw=read(RAW);out.mkdir(parents=True,exist_ok=False)
    freeze=dict(schema='continuous-cold-source-freeze-v1',protocol=protocol,
      inputs=input_hashes(raw),raw_episodes=len(raw['episodes']),
      boundaries=sum(len(e['episode']['checkpoints']) for e in raw['episodes']),workers_executed=False)
    h=write(out/'SOURCE_FREEZE.json',freeze)
    print(json.dumps(dict(prepared=str(out),source_freeze_sha256=h,boundaries=freeze['boundaries'],workers_executed=False)))


def worker():
    request=json.load(sys.stdin)
    public=read(ROOT/request['public_file']);artifact_path=ROOT/request['artifact_file']
    if digest(artifact_path)!=request['artifact_sha256']:raise ValueError('worker artifact mismatch')
    model=adapter.ContinuousPolicy(read(artifact_path));content=adapter.task.ContentAdapter()
    result=adapter.episode(public,ROOT/request['folder'],content,model,request['controller'],0,
                           request['artifact_sha256'],start=request['checkpoint'])
    value=dict(schema='continuous-cold-worker-v1',job=request['job'],pid=os.getpid(),ppid=os.getppid(),
      fresh_content_setup=content.setup,result=result,worker_wall_seconds=time.perf_counter()-ENTRY_WALL,
      worker_cpu_seconds=time.process_time()-ENTRY_CPU)
    json.dump(value,sys.stdout,sort_keys=True,separators=(',',':'),allow_nan=False)


def invoke(job,timeout):
    environment=os.environ.copy()
    environment.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
    start=time.perf_counter()
    try:
        process=subprocess.run([sys.executable,'-m',MODULE,'worker'],input=json.dumps(job).encode(),
          stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT,env=environment,timeout=timeout,check=False)
        stdout=process.stdout.decode('utf-8',errors='replace');stderr=process.stderr.decode('utf-8',errors='replace')
        result=json.loads(stdout) if process.returncode==0 else None
        return dict(job=job['job'],request=job,returncode=process.returncode,stderr=stderr,
          stdout_if_failure=stdout if result is None else None,worker=result,
          subprocess_wall_seconds=time.perf_counter()-start,timed_out=False)
    except (OSError,subprocess.TimeoutExpired,json.JSONDecodeError,UnicodeError) as error:
        return dict(job=job['job'],request=job,returncode=None,worker=None,error=repr(error),
          stderr=getattr(error,'stderr',None).decode('utf-8',errors='replace') if isinstance(getattr(error,'stderr',None),bytes) else None,
          stdout_if_failure=getattr(error,'stdout',None).decode('utf-8',errors='replace') if isinstance(getattr(error,'stdout',None),bytes) else None,
          subprocess_wall_seconds=time.perf_counter()-start,timed_out=isinstance(error,subprocess.TimeoutExpired))


def child_cpu():
    usage=resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime+usage.ru_stime


def run(out,published_commit):
    if len(published_commit)!=40 or any(c not in '0123456789abcdef' for c in published_commit):
        raise ValueError('full published source commit required')
    freeze=read(out/'SOURCE_FREEZE.json');raw=read(RAW);protocol=freeze['protocol']
    if input_hashes(raw)!=freeze['inputs']:raise ValueError('frozen inputs changed')
    dest=out/'execution';dest.mkdir(exist_ok=False)
    write(dest/'STARTED.json',dict(published_source_commit=published_commit,freeze_sha256=digest(out/'SOURCE_FREEZE.json')))
    jobs=[];expected={}
    for ei,e in enumerate(raw['episodes']):
        record=next(r for c in raw['cohorts'] for r in c['records'] if r['id']==e['world'])
        folder=Path(record['folder']);folder=folder if folder.is_absolute() else ROOT/folder
        artifact=PREPARED/f"fit_{e['fit']}_continuous_optin.json.gz"
        for boundary,checkpoint in enumerate(e['episode']['checkpoints']):
            name=f'episode_{ei:03d}_boundary_{boundary:02d}'
            jobs.append(dict(job=name,folder=str(folder.relative_to(ROOT)),public_file=str((folder/'public.json').relative_to(ROOT)),
              artifact_file=str(artifact.relative_to(ROOT)),artifact_sha256=digest(artifact),controller=e['controller'],checkpoint=checkpoint))
            expected[name]=dict(rows=e['episode']['rows'][boundary:],final=e['episode']['final'])
    start_wall,start_cpu,start_child=time.perf_counter(),time.process_time(),child_cpu()
    receipts=[]
    with ThreadPoolExecutor(max_workers=protocol['concurrency']) as pool:
        for receipt in pool.map(lambda job:invoke(job,protocol['worker_timeout_seconds']),jobs):
            result=receipt['worker'];target=expected[receipt['job']]
            receipt['matched']=bool(result is not None and result['pid']!=os.getpid() and
              adapter.stable(result['result']['rows'])==adapter.stable(target['rows']) and
              adapter.stable(result['result']['final'])==adapter.stable(target['final']))
            receipts.append(receipt)
            write(dest/'workers'/(receipt['job']+'.json.gz'),receipt)
    unchanged=input_hashes(raw)==freeze['inputs']
    allrows=[row for r in receipts if r['worker'] is not None for row in r['worker']['result']['rows']]
    summary=dict(schema='continuous-cold-qualification-v1',published_source_commit=published_commit,
      freeze_sha256=digest(out/'SOURCE_FREEZE.json'),raw_input_sha256=digest(RAW),
      workers_requested=len(jobs),workers_recorded=len(receipts),workers_matched=sum(r['matched'] for r in receipts),
      worker_failures=sum(r['worker'] is None for r in receipts),timeouts=sum(r['timed_out'] for r in receipts),
      unique_worker_pids=len({r['worker']['pid'] for r in receipts if r['worker'] is not None}),
      attempts=sum(r['receipt']['source_opened'] is not None for r in allrows),
      successes=sum(r['receipt']['completion'] is not None and not r['receipt']['completion'].get('failure',False) for r in allrows),
      events=sum(len(r['events']) for r in allrows),sources_worlds_models_unchanged_at_end=unchanged,
      wall_seconds=time.perf_counter()-start_wall,parent_cpu_seconds=time.process_time()-start_cpu,
      parent_entry_to_summary_wall_seconds=time.perf_counter()-ENTRY_WALL,
      parent_entry_to_summary_cpu_seconds=time.process_time()-ENTRY_CPU,
      children_user_system_cpu_seconds=child_cpu()-start_child,
      workers_reported_cpu_seconds=sum(r['worker']['worker_cpu_seconds'] for r in receipts if r['worker'] is not None),
      scope='new Python process per action boundary; no mid-action crash, Rust ACK or benefit claim')
    summary['passed']=all(r['matched'] for r in receipts) and unchanged and len(receipts)==freeze['boundaries']
    summary['worker_files']={p.name:digest(p) for p in sorted((dest/'workers').glob('*.json.gz'))}
    write(dest/'SUMMARY.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='worker_files'},indent=2))
    if not summary['passed']:raise RuntimeError('cold replay failures retained')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','run','worker'])
    parser.add_argument('--out',type=Path);parser.add_argument('--published-source-commit')
    args=parser.parse_args()
    if args.stage=='worker':worker()
    elif args.stage=='prepare':prepare(args.out)
    else:run(args.out,args.published_source_commit or '')
