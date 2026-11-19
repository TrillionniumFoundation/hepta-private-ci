"""Bounded synthetic process/durable-census qualification; not a sandbox.

No resume/retry, hard RSS, whole-tree or parent-death-cleanup guarantee.
Hashes bind local bytes, not hostile concurrent modification or disk rollback.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import time
if sys.platform=='linux':
    import fcntl
else:
    fcntl=None
from cell_field_fixed_actions import fixed_library
from cell_field_fixed_worker import FILES, canonical, unique

ROOT=Path(__file__).resolve().parent
MAX_JOURNAL=1024*1024
MAX_LINE=65536


def sha(value):return hashlib.sha256(canonical(value)).hexdigest()

def sync_directory(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def read_json(path,limit):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        with os.fdopen(fd,'rb') as stream:
            raw=stream.read(limit+1)
        if len(raw)>limit:raise ValueError('oversized evidence')
        return json.loads(raw,object_pairs_hook=unique)
    except BaseException:raise


def validate_plan(plan):
    if set(plan)!={'schema','fixture','sources','limits','records','fault','stop_after','interpreter_sha256','plan_sha256'}:raise ValueError('plan fields')
    body={k:v for k,v in plan.items() if k!='plan_sha256'}
    if type(plan['schema'])!=int or plan['schema']!=1 or plan['fixture']!='synthetic-linear36-h3-v1' or sha(body)!=plan['plan_sha256']:raise ValueError('plan identity')
    if set(plan['sources'])!=set(FILES) or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in plan['sources'].values()):raise ValueError('source identities')
    if plan['stop_after'] not in (None,'started','terminal'):raise ValueError('fixed stop window')
    if plan['fault'] not in ('none','hang','before_output','after_output','stderr_overflow','wrong_request'):raise ValueError('fixed fault')
    if not isinstance(plan['interpreter_sha256'],str) or len(plan['interpreter_sha256'])!=64:raise ValueError('interpreter identity')
    limits=plan['limits']
    if (set(limits)!={'attempts','wall_seconds','stream_bytes'} or type(limits['attempts'])!=int
        or not 1<=limits['attempts']<=3 or type(limits['wall_seconds']) not in (int,float)
        or not math.isfinite(limits['wall_seconds']) or not .05<=limits['wall_seconds']<=10
        or limits['stream_bytes']!=16384):raise ValueError('bounded qualification limits')
    expected=[{'index':i,'action':action,'mode':mode} for i,(action,mode) in enumerate((a,m) for a,_ in fixed_library(36) for m in ('loss2','q4','full'))]
    if plan['records']!=expected or any(type(r['index'])!=int for r in plan['records']):raise ValueError('complete fixed plan required')
    return plan


def request_for(plan,index):
    r=plan['records'][index]
    body={'fixture':plan['fixture'],'action':r['action'],'mode':r['mode'],
          'sources':plan['sources'],'limits':plan['limits'],'fault':plan['fault'],
          'interpreter_sha256':plan['interpreter_sha256'],'stop_window':plan['stop_after']}
    return {**body,'request_sha256':sha(body)}


def validate_outcome(outcome,request):
    if not isinstance(outcome,dict):raise ValueError('outcome object')
    if set(outcome)!={'status','reason','returncode','fields','wall_seconds','peak_rss_bytes','request_sha256'}:raise ValueError('outcome fields')
    if outcome['request_sha256']!=request['request_sha256']:raise ValueError('wrong outcome request')
    if outcome['status'] not in ('success','failed','indeterminate'):raise ValueError('outcome status')
    if outcome['reason'] not in ('ok','nonzero_exit','timeout','output_limit','invalid_result','launch_error','unreaped'):raise ValueError('outcome reason')
    if outcome['returncode'] is not None and type(outcome['returncode'])!=int:raise ValueError('exit code')
    if type(outcome['wall_seconds']) not in (float,int) or not math.isfinite(outcome['wall_seconds']) or outcome['wall_seconds']<0:raise ValueError('wall observation')
    if outcome['peak_rss_bytes'] is not None and (type(outcome['peak_rss_bytes'])!=int or not 0<=outcome['peak_rss_bytes']<2**63):raise ValueError('RSS observation')
    if (outcome['status']=='indeterminate')!=(outcome['reason']=='unreaped'):raise ValueError('unreaped uncertainty')
    if outcome['status']!='success' and outcome['reason']=='ok':raise ValueError('inconsistent reason')
    if outcome['reason']=='nonzero_exit' and outcome['returncode'] in (None,0):raise ValueError('missing nonzero exit')
    fields=outcome['fields']
    if outcome['status']=='success':
        if outcome['wall_seconds']>=request['limits']['wall_seconds']:raise ValueError('success exceeded deadline')
        if outcome['reason']!='ok' or outcome['returncode']!=0 or not isinstance(fields,list) or len(fields)!=4:raise ValueError('success requires complete result')
        if any(not isinstance(row,list) or len(row)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) for x in row) for row in fields):raise ValueError('finite loss paths')
    elif fields is not None:raise ValueError('failed result cannot supply utility')


class Writer:
    def __init__(self,directory,plan):
        if fcntl is None:raise NotImplementedError("Linux-only qualification gate")
        self.path=Path(directory);self.path.mkdir(mode=0o700)
        self.lock=os.open(self.path/'writer.lock',os.O_CREAT|os.O_EXCL|os.O_RDWR|os.O_NOFOLLOW,0o600)
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.poisoned=False;self.seq=0;self.previous=plan['plan_sha256']
        try:
            with (self.path/'plan.tmp').open('xb') as f:f.write(canonical(plan));f.flush();os.fsync(f.fileno())
            os.link(self.path/'plan.tmp',self.path/'plan.json');os.unlink(self.path/'plan.tmp')
            self.journal=os.open(self.path/'events.jsonl',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_APPEND|os.O_NOFOLLOW,0o600)
            os.fsync(self.journal);os.fsync(self.lock);sync_directory(self.path);sync_directory(self.path.parent)
        except BaseException:
            if hasattr(self,'journal'):os.close(self.journal)
            os.close(self.lock);raise
    def append(self,kind,index,request,outcome=None):
        if self.poisoned:raise RuntimeError('poisoned journal')
        event={'seq':self.seq,'previous':self.previous,'kind':kind,'index':index,'request':request,'outcome':outcome}
        line=canonical({**event,'event_sha256':sha(event)})+b'\n'
        try:
            if len(line)>MAX_LINE or os.fstat(self.journal).st_size+len(line)>MAX_JOURNAL:raise ValueError('journal bound')
            view=memoryview(line)
            while view:
                wrote=os.write(self.journal,view)
                if wrote<=0:raise OSError('short append')
                view=view[wrote:]
            os.fsync(self.journal)
        except BaseException:self.poisoned=True;raise
        self.seq+=1;self.previous=sha(event)
    def close(self):
        os.close(self.journal);os.close(self.lock)


def stop_owned(process):
    # Called only for our unreaped child; no PID lookup or unrelated process target.
    for sig,grace in ((signal.SIGTERM,.15),(signal.SIGKILL,.3)):
        if process.poll() is not None:return True
        try:os.killpg(process.pid,sig)
        except ProcessLookupError:pass
        try:process.wait(timeout=grace);return True
        except subprocess.TimeoutExpired:pass
    return process.poll() is not None


def execute(request):
    started=time.monotonic();peak=None;process=None;selector=None;reason='launch_error';fields=None;code=None
    try:
        if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest for name,digest in request['sources'].items()):raise ValueError('source changed before launch')
        env={'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','PYTHONHASHSEED':'0'}
        process=subprocess.Popen([sys.executable,'-I',str(ROOT/'cell_field_fixed_worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 start_new_session=True,env=env)
        process.stdin.write(canonical(request));process.stdin.close()
        buffers={};selector=selectors.DefaultSelector()
        for stream in (process.stdout,process.stderr):
            selector.register(stream,selectors.EVENT_READ);buffers[stream]=bytearray()
        reason=None
        while selector.get_map():
            elapsed=time.monotonic()-started
            if elapsed>=request['limits']['wall_seconds']:reason='timeout';break
            try:
                text=Path(f'/proc/{process.pid}/status').read_text()
                values=[line for line in text.splitlines() if line.startswith('VmRSS:')]
                if values:peak=max(peak or 0,int(values[0].split()[1])*1024)
            except (OSError,ValueError):pass
            for key,_ in selector.select(min(.02,request['limits']['wall_seconds']-elapsed)):
                chunk=os.read(key.fileobj.fileno(),min(4096,request['limits']['stream_bytes']-len(buffers[key.fileobj])+1))
                if not chunk:selector.unregister(key.fileobj)
                else:
                    buffers[key.fileobj].extend(chunk)
                    if len(buffers[key.fileobj])>request['limits']['stream_bytes']:reason='output_limit';break
            if reason:break
        selector.close()
        if reason:
            if not stop_owned(process):reason='unreaped'
        else:
            try:process.wait(timeout=max(.001,request['limits']['wall_seconds']-(time.monotonic()-started)))
            except subprocess.TimeoutExpired:
                reason='timeout' if stop_owned(process) else 'unreaped'
        code=process.poll()
        if reason is None and code!=0:reason='nonzero_exit'
        if reason is None:
            try:
                response=json.loads(buffers[process.stdout],object_pairs_hook=unique)
                if set(response)!={'request_sha256','fields'} or response['request_sha256']!=request['request_sha256']:raise ValueError('response identity')
                fields=response['fields'];reason='ok'
            except (ValueError,TypeError):reason='invalid_result'
    except Exception:
        reason='launch_error'
        if process is not None and not stop_owned(process):reason='unreaped'
        code=process.poll() if process is not None else None
    except BaseException:
        if process is not None:stop_owned(process)
        raise
    finally:
        if selector is not None:selector.close()
        if process is not None:
            for stream in (process.stdin,process.stdout,process.stderr):
                try:stream.close()
                except OSError:pass
    outcome={'status':'success' if reason=='ok' else 'indeterminate' if reason=='unreaped' else 'failed',
             'reason':reason,'returncode':code,'fields':fields if reason=='ok' else None,
             'wall_seconds':time.monotonic()-started,'peak_rss_bytes':peak,'request_sha256':request['request_sha256']}
    if outcome['status']=='success' and outcome['wall_seconds']>=request['limits']['wall_seconds']:
        outcome.update(status='failed',reason='timeout',fields=None)
    try:validate_outcome(outcome,request)
    except ValueError:outcome.update(status='failed',reason='invalid_result',fields=None)
    outcome['wall_seconds']=time.monotonic()-started
    if outcome['status']=='success' and outcome['wall_seconds']>=request['limits']['wall_seconds']:
        outcome.update(status='failed',reason='timeout',fields=None)
    return outcome


def read_census(directory):
    if fcntl is None:raise NotImplementedError("Linux-only qualification gate")
    path=Path(directory)
    lock=os.open(path/'writer.lock',os.O_RDONLY|os.O_NOFOLLOW)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=validate_plan(read_json(path/'plan.json',MAX_LINE))
        fd=os.open(path/'events.jsonl',os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:raw=stream.read(MAX_JOURNAL+1)
        if len(raw)>MAX_JOURNAL or (raw and not raw.endswith(b'\n')):raise ValueError('oversized or incomplete journal')
        records=[{**r,'status':'not_run'} for r in plan['records']]
        previous=plan['plan_sha256'];active=None;next_index=0;stopped=False
        for seq,line in enumerate(raw.splitlines()):
            if len(line)>MAX_LINE:raise ValueError('oversized event')
            e=json.loads(line,object_pairs_hook=unique)
            if set(e)!={'seq','previous','kind','index','request','outcome','event_sha256'}:raise ValueError('event fields')
            body={k:v for k,v in e.items() if k!='event_sha256'}
            if type(e['seq'])!=int or e['seq']!=seq or e['previous']!=previous or sha(body)!=e['event_sha256']:raise ValueError('event chain')
            index=e['index']
            if type(index)!=int or not 0<=index<plan['limits']['attempts']:raise ValueError('event index')
            req=e['request'];fault=req.get('fault') if isinstance(req,dict) else None
            if fault not in ('none','hang','before_output','after_output','stderr_overflow','wrong_request') or req!=request_for(plan,index):raise ValueError('event request')
            if e['kind']=='started':
                if stopped or active is not None or index!=next_index or e['outcome'] is not None:raise ValueError('illegal started')
                records[index]['status']='indeterminate';active=index
            elif e['kind']=='terminal':
                if active!=index:raise ValueError('illegal terminal')
                validate_outcome(e['outcome'],req)
                records[index].update(e['outcome']);active=None;next_index+=1
                stopped=e['outcome']['status']!='success'
            else:raise ValueError('unknown event')
            previous=e['event_sha256']
        return {'plan_sha256':plan['plan_sha256'],'records':records,'resume_allowed':False,
                'scope':'process-exit/fsync protocol only; not power-loss or parent-death cleanup'}
    finally:os.close(lock)


def run_gate(directory,*,attempts=1,wall_seconds=5.,fault='none',stop_after=None):
    if fcntl is None:raise NotImplementedError('Linux-only qualification gate')
    if shutil.disk_usage(ROOT).free<3*1024**3:raise RuntimeError('3 GiB free reserve required')
    if fault not in ('none','hang','before_output','after_output','stderr_overflow','wrong_request'):raise ValueError('fixed fault only')
    if stop_after not in (None,'started','terminal'):raise ValueError('fixed stop window only')
    plan={'schema':1,'fixture':'synthetic-linear36-h3-v1','fault':fault,'stop_after':stop_after,
          'interpreter_sha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
          'sources':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in FILES},
          'limits':{'attempts':attempts,'wall_seconds':wall_seconds,'stream_bytes':16384},
          'records':[{'index':i,'action':a,'mode':m} for i,(a,m) in enumerate((a,m) for a,_ in fixed_library(36) for m in ('loss2','q4','full'))]}
    plan['plan_sha256']=sha(plan);validate_plan(plan)
    writer=Writer(directory,plan)
    try:
        for i in range(attempts):
            req=request_for(plan,i);writer.append('started',i,req)
            if stop_after=='started':break
            outcome=execute(req);writer.append('terminal',i,req,outcome)
            if stop_after=='terminal' or outcome['status']!='success':break
    finally:writer.close()
    return read_census(directory)
