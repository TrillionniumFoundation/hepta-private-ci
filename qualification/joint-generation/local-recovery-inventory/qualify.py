"""One source-pinned synthetic suite; complete child wait and failed cost retained."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time
from decimal import Decimal

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
FILES = ['inventory.py', 'test_inventory.py', 'qualify.py', 'README.md']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, sort_keys=True, indent=2); handle.write('\n')
        handle.flush(); os.fsync(handle.fileno())
    fd = os.open(path.parent, os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def process_identity(pid):
    text = Path(f'/proc/{pid}/stat').read_text()
    return dict(pid=pid,birth_ticks=int(text[text.rfind(')')+2:].split()[19]),
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        pid_namespace=os.readlink(f'/proc/{pid}/ns/pid'))


def main():
    # This is NOT the missing historical scientific benchmark lock.
    lock = HERE / 'SYNTHETIC_ONLY.lock'
    with lock.open('a') as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run = HERE / 'qualification-001'; run.mkdir()
        files = [HERE/n for n in FILES] + [HERE.parent/'local-accounting-batch/support.py']
        hashes = {str(p.relative_to(ROOT)):digest(p) for p in files}
        write(run/'INPUT_MANIFEST.json', dict(source_files=hashes,test_cases=19, scientific_execution=False,
            scope='one stdlib handmade-metadata test child',historical_shared_lock_available=False,
            lock_scope='synthetic-only, not scientific admission',limits=dict(cpu_s=3,wall_s=20,as_bytes=128*2**20)))
        stdout = os.open(run/'stdout.txt', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        stderr = os.open(run/'stderr.txt', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        read_fd, write_fd = os.pipe(); pid = identity = usage = waited = status = None; errors = []
        start = time.monotonic_ns()
        try:
            pid = os.fork()
            if pid == 0:
                try:
                    os.close(write_fd); os.dup2(stdout,1); os.dup2(stderr,2); os.close(stdout); os.close(stderr)
                    resource.setrlimit(resource.RLIMIT_CPU,(3,3)); resource.setrlimit(resource.RLIMIT_AS,(128*2**20,128*2**20))
                    resource.setrlimit(resource.RLIMIT_FSIZE,(2**20,2**20))
                    signal.signal(signal.SIGALRM,signal.SIG_DFL); signal.alarm(20)
                    if os.read(read_fd,1) != b'1': raise RuntimeError('no bound release')
                    os.close(read_fd)
                    os.execv(sys.executable,[sys.executable,'-I','-B','-W','error',str(HERE/'test_inventory.py')])
                finally: os._exit(70)
            os.close(read_fd); read_fd=None
            identity=process_identity(pid)
            write(run/'BOUND_PROCESS.json',dict(process=identity,manifest_sha256=digest(run/'INPUT_MANIFEST.json')))
            if os.write(write_fd,b'1') != 1: raise RuntimeError('uncertain gate; never repeat')
        except BaseException as exc: errors.append(repr(exc))
        finally:
            for fd in (read_fd,write_fd,stdout,stderr):
                if fd is not None:
                    try: os.close(fd)
                    except BaseException as exc: errors.append(repr(exc))
            if pid is not None and pid>0:
                try:
                    while True:
                        try: waited,status,usage=os.wait4(pid,0);break
                        except (InterruptedError,KeyboardInterrupt,TimeoutError):continue
                except BaseException as exc:errors.append(repr(exc))
        complete = pid is not None and waited==pid and usage is not None
        receipt=dict(schema='SYNTHETIC-INVENTORY-QUALIFICATION-WAIT-v1',complete_wait=complete,process=identity,
            fork_pid=pid,waited_pid=waited,errors=errors,exit_code=os.waitstatus_to_exitcode(status) if complete else None,
            user_cpu_seconds=str(usage.ru_utime) if complete else None,system_cpu_seconds=str(usage.ru_stime) if complete else None,
            wall_ns=time.monotonic_ns()-start,max_rss_kib=usage.ru_maxrss if complete else None,
            scope='one test interpreter; no fixture subprocesses or scientific work',observer_tail='UNKNOWN_EXCLUDED')
        write(run/'RAW_WAIT.json',receipt)
        result=dict(status='FAIL_OR_UNKNOWN',raw_wait_sha256=digest(run/'RAW_WAIT.json'),source_files=hashes,reason=None)
        try:
            actual=json.loads((run/'stdout.txt').read_text().splitlines()[-1])
            if not complete or errors or receipt['exit_code']!=0 or identity is None:raise ValueError('complete successful bound child wait required')
            total=Decimal(receipt['user_cpu_seconds'])+Decimal(receipt['system_cpu_seconds'])
            result['complete_child_cpu_seconds']=str(total)
            if actual != dict(tests_run=19,failures=0,errors=0,success=True,scope='HANDMADE_METADATA_ONLY'):raise ValueError('test result')
            if any(digest(ROOT/p)!=h for p,h in hashes.items()):raise ValueError('source changed')
            if total>3 or receipt['wall_ns']>20*10**9 or usage.ru_maxrss>128*1024:raise ValueError('qualification budget')
            result.update(status='PASS',tests=actual,stdout_sha256=digest(run/'stdout.txt'),stderr_sha256=digest(run/'stderr.txt'))
        except BaseException as exc:result['reason']=repr(exc)
        write(run/'QUALIFICATION.json',result); print(json.dumps(result,sort_keys=True))
        return 0 if result['status']=='PASS' else 1


if __name__=='__main__':sys.exit(main())
