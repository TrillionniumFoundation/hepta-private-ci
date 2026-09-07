#!/usr/bin/env python3
"""Materialize the exact final Hepta gap-closure follow-up on b4f02458."""
from pathlib import Path

ROOT = Path(".g1/trillionnium_os_external_evidence")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


source_path = ROOT / "trusted_executor.py"
source = source_path.read_text(encoding="utf-8")
source = replace_once(
    source,
    "import argparse, fcntl, hashlib, json, multiprocessing, os, re, selectors, signal, stat, subprocess, sys, time",
    "import argparse, ctypes, fcntl, hashlib, json, multiprocessing, os, re, selectors, signal, stat, subprocess, sys, time",
    "ctypes import",
)
source = replace_once(
    source,
    '''def group_members(pgid):
    if not Path("/proc").is_dir(): raise ExecutionError("procfs is required")
    out=[]; count=0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit(): continue
        count+=1
        if count>65536: raise ExecutionError("procfs scan ceiling exceeded")
        try: raw=(entry/"stat").read_bytes()
        except (FileNotFoundError,PermissionError,ProcessLookupError): continue
        if len(raw)>8192: raise ExecutionError("procfs stat too large")
        end=raw.rfind(b")"); fields=raw[end+2:].split() if end>=0 else []
        try:
            if len(fields)>=3 and int(fields[2])==pgid and fields[0]!=b"Z": out.append(int(entry.name))
        except ValueError: pass
    return out

def exited(pid):
    try: return os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is not None
    except ChildProcessError: return True

def retire(proc):
    observation_ok=True; signal_ok=True
    for sig,grace in ((signal.SIGTERM,.25),(signal.SIGKILL,1.0)):
        try: os.killpg(proc.pid,sig)
        except ProcessLookupError: pass
        except OSError: signal_ok=False
        deadline=time.monotonic()+grace
        while time.monotonic()<deadline:
            try: done=exited(proc.pid) and not group_members(proc.pid)
            except ExecutionError: observation_ok=False; break
            if done: break
            time.sleep(.02)
    try: clean1=not group_members(proc.pid)
    except ExecutionError: observation_ok=False; clean1=False
    time.sleep(.02)
    try: clean2=not group_members(proc.pid)
    except ExecutionError: observation_ok=False; clean2=False
    try: proc.wait(timeout=1); reaped=True
    except subprocess.TimeoutExpired:
        try: os.killpg(proc.pid,signal.SIGKILL)
        except OSError: signal_ok=False
        try: proc.wait(timeout=1); reaped=True
        except subprocess.TimeoutExpired: reaped=False
    return reaped,signal_ok and observation_ok and reaped and clean1 and clean2
''',
    '''PR_SET_CHILD_SUBREAPER=36
PR_GET_CHILD_SUBREAPER=37
CONTAINMENT_SCOPE="linux_subreaper_pidfd_descendant_tree_v1"
_LIBC=ctypes.CDLL(None,use_errno=True)

@dataclass(frozen=True)
class ProcIdentity:
    pid:int; ppid:int; pgrp:int; state:str; starttime:int

def _prctl(option,arg=0):
    ctypes.set_errno(0)
    rc=_LIBC.prctl(option,arg,0,0,0)
    if rc!=0:
        code=ctypes.get_errno()
        raise ExecutionError(f"prctl {option} failed: {os.strerror(code)}")

def _subreaper_state():
    value=ctypes.c_int()
    ctypes.set_errno(0)
    rc=_LIBC.prctl(PR_GET_CHILD_SUBREAPER,ctypes.byref(value),0,0,0)
    if rc!=0:
        code=ctypes.get_errno()
        raise ExecutionError(f"cannot read child-subreaper state: {os.strerror(code)}")
    return bool(value.value)

def _set_subreaper(enabled):
    _prctl(PR_SET_CHILD_SUBREAPER,1 if enabled else 0)
    if _subreaper_state()!=bool(enabled): raise ExecutionError("child-subreaper state did not converge")

def _read_proc_identity(pid):
    try: raw=(Path("/proc")/str(pid)/"stat").read_bytes()
    except (FileNotFoundError,ProcessLookupError): return None
    except PermissionError as e: raise ExecutionError(f"cannot inspect process {pid}: {e}") from e
    if len(raw)>8192: raise ExecutionError("procfs stat too large")
    end=raw.rfind(b")")
    if end<0: raise ExecutionError(f"malformed procfs stat for {pid}")
    fields=raw[end+2:].split()
    if len(fields)<20: raise ExecutionError(f"short procfs stat for {pid}")
    try: return ProcIdentity(pid,int(fields[1]),int(fields[2]),fields[0].decode("ascii"),int(fields[19]))
    except (UnicodeDecodeError,ValueError) as e: raise ExecutionError(f"invalid procfs stat for {pid}") from e

def _proc_table():
    if not Path("/proc").is_dir(): raise ExecutionError("procfs is required")
    try: entries=list(Path("/proc").iterdir())
    except OSError as e: raise ExecutionError(f"cannot enumerate procfs: {e}") from e
    if len(entries)>65536: raise ExecutionError("procfs scan ceiling exceeded")
    out={}
    for entry in entries:
        if not entry.name.isdigit(): continue
        ident=_read_proc_identity(int(entry.name))
        if ident is not None: out[ident.pid]=ident
    return out

def _descendant_identities(root_pid):
    table=_proc_table()
    if root_pid not in table: raise ExecutionError("executor disappeared from procfs")
    children={}
    for ident in table.values(): children.setdefault(ident.ppid,[]).append(ident)
    out=[]; frontier=[root_pid]; seen={root_pid}
    while frontier:
        parent=frontier.pop()
        for ident in children.get(parent,[]):
            if ident.pid in seen: raise ExecutionError("procfs parent cycle detected")
            seen.add(ident.pid); out.append(ident); frontier.append(ident.pid)
            if len(out)>65536: raise ExecutionError("descendant scan ceiling exceeded")
    return out

def _signal_identity(ident,sig):
    if ident.pid==os.getpid(): return False
    try: fd=os.pidfd_open(ident.pid,0)
    except ProcessLookupError: return True
    except OSError: return False
    try:
        current=_read_proc_identity(ident.pid)
        if current is None or current.starttime!=ident.starttime: return True
        try: signal.pidfd_send_signal(fd,sig,None,0)
        except ProcessLookupError: return True
        except OSError: return False
        return True
    finally: os.close(fd)

def _active_descendants(owner_pid,baseline):
    return [x for x in _descendant_identities(owner_pid) if (x.pid,x.starttime) not in baseline]

def _reap_adopted(owner_pid,leader_pid,baseline):
    try: descendants=_active_descendants(owner_pid,baseline)
    except ExecutionError: return False
    ok=True
    for ident in descendants:
        if ident.ppid!=owner_pid or ident.pid==leader_pid: continue
        try: os.waitpid(ident.pid,os.WNOHANG)
        except ChildProcessError: pass
        except OSError: ok=False
    return ok

def exited(pid):
    try: return os.waitid(os.P_PID,pid,os.WEXITED|os.WNOHANG|os.WNOWAIT) is not None
    except ChildProcessError: return True

def _enter_descendant_containment():
    if not hasattr(os,"pidfd_open") or not hasattr(signal,"pidfd_send_signal"): raise ExecutionError("pidfd descendant containment is required")
    owner=os.getpid(); baseline={(x.pid,x.starttime) for x in _descendant_identities(owner)}
    prior=_subreaper_state()
    if not prior: _set_subreaper(True)
    return owner,prior,baseline

def _restore_descendant_containment(prior,clean):
    if clean and not prior: _set_subreaper(False)

def retire(proc,owner_pid,baseline):
    observation_ok=True; signal_ok=True; reap_ok=True; lingering=False

    def observe_live():
        nonlocal observation_ok,lingering
        try: descendants=_active_descendants(owner_pid,baseline)
        except ExecutionError:
            observation_ok=False; return None
        live=[x for x in descendants if x.state!="Z"]
        leader_done=proc.poll() is not None or exited(proc.pid)
        if leader_done and any(x.pid!=proc.pid for x in live): lingering=True
        return live

    for sig,grace in ((signal.SIGTERM,.25),(signal.SIGKILL,1.0)):
        deadline=time.monotonic()+grace
        while time.monotonic()<deadline:
            live=observe_live()
            if live is None or not live: break
            for ident in reversed(live): signal_ok=_signal_identity(ident,sig) and signal_ok
            if proc.poll() is not None: reap_ok=_reap_adopted(owner_pid,proc.pid,baseline) and reap_ok
            live=observe_live()
            if live is None or not live: break
            time.sleep(.02)
    try: proc.wait(timeout=1); reaped=True
    except subprocess.TimeoutExpired:
        ident=_read_proc_identity(proc.pid)
        if ident is not None: signal_ok=_signal_identity(ident,signal.SIGKILL) and signal_ok
        try: proc.wait(timeout=1); reaped=True
        except subprocess.TimeoutExpired: reaped=False
    observe_live()
    for _ in range(8):
        reap_ok=_reap_adopted(owner_pid,proc.pid,baseline) and reap_ok
        remaining=observe_live()
        if remaining is None: remaining=[ProcIdentity(-1,-1,-1,"?",-1)]
        if not remaining: break
        for ident in reversed(remaining): signal_ok=_signal_identity(ident,signal.SIGKILL) and signal_ok
        time.sleep(.02)
    remaining=observe_live(); clean1=remaining==[]
    time.sleep(.02)
    reap_ok=_reap_adopted(owner_pid,proc.pid,baseline) and reap_ok
    remaining=observe_live(); clean2=remaining==[]
    clean=signal_ok and observation_ok and reap_ok and reaped and clean1 and clean2
    return reaped,clean,lingering
''',
    "complete descendant containment",
)
source = replace_once(
    source,
    '''def run_harness(harness,cwd,env,kind,clock:Callable[[],datetime],authority_expiry):
    if clock()>=authority_expiry: return {"exit_code":-1,"stdout":b"","stderr":b"","failure":"authorization_expired_before_target_contact","leader_reaped":True,"cleanup_confirmed":True,"target_contact_performed":False}
    cmd=f"/proc/self/fd/{harness.fd}"
    proc=subprocess.Popen([cmd],executable=cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=cwd,env=env,close_fds=True,pass_fds=(harness.fd,),start_new_session=True)
    sel=None; data={"stdout":bytearray(),"stderr":bytearray()}; drain=None; error=None
    try:
        if proc.stdout is None or proc.stderr is None: raise ExecutionError("harness pipes were not created")
        sel=selectors.DefaultSelector()
        for pipe in (proc.stdout,proc.stderr): os.set_blocking(pipe.fileno(),False)
        sel.register(proc.stdout,selectors.EVENT_READ,("stdout",kind["stdout_max_bytes"])); sel.register(proc.stderr,selectors.EVENT_READ,("stderr",kind["stderr_max_bytes"])); deadline=time.monotonic()+kind["timeout_seconds"]
        while sel.get_map():
            now=time.monotonic()
            if clock()>=authority_expiry: error="authorization_expired_during_execution"; break
            if now>=deadline: error="execution_timeout"; break
            if exited(proc.pid):
                drain=drain or min(deadline,now+1)
                if now>=drain: error="pipe_drain_timeout"; break
            for key,_ in sel.select(min(.1,deadline-now)):
                label,limit=key.data
                try: chunk=os.read(key.fileobj.fileno(),min(65536,limit+1-len(data[label])))
                except BlockingIOError: continue
                if not chunk: sel.unregister(key.fileobj); continue
                data[label]+=chunk
                if len(data[label])>limit: error=f"{label}_limit_exceeded"; break
            if error: break
        if not error and not exited(proc.pid):
            while not exited(proc.pid):
                if clock()>=authority_expiry: error="authorization_expired_during_execution"; break
                if time.monotonic()>=deadline: error="execution_timeout"; break
                time.sleep(.02)
    finally:
        try: reaped,clean=retire(proc)
        finally:
            if sel is not None: sel.close()
            if proc.stdout is not None: proc.stdout.close()
            if proc.stderr is not None: proc.stderr.close()
    if not clean and not error: error="process_group_cleanup_unconfirmed"
    return {"exit_code":proc.returncode if proc.returncode is not None else -9,"stdout":bytes(data["stdout"]),"stderr":bytes(data["stderr"]),"failure":error,"leader_reaped":reaped,"cleanup_confirmed":clean,"target_contact_performed":True}
''',
    '''def run_harness(harness,cwd,env,kind,clock:Callable[[],datetime],authority_expiry):
    if clock()>=authority_expiry: return {"exit_code":-1,"stdout":b"","stderr":b"","failure":"authorization_expired_before_target_contact","leader_reaped":True,"cleanup_confirmed":True,"escaped_descendants_absence_proven":True,"target_contact_performed":False}
    owner_pid,prior_subreaper,baseline=_enter_descendant_containment()
    cmd=f"/proc/self/fd/{harness.fd}"; proc=None; clean=False
    try: proc=subprocess.Popen([cmd],executable=cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=cwd,env=env,close_fds=True,pass_fds=(harness.fd,),start_new_session=True)
    except Exception:
        _restore_descendant_containment(prior_subreaper,True); raise
    sel=None; data={"stdout":bytearray(),"stderr":bytearray()}; drain=None; error=None; lingering=False
    try:
        if proc.stdout is None or proc.stderr is None: raise ExecutionError("harness pipes were not created")
        sel=selectors.DefaultSelector()
        for pipe in (proc.stdout,proc.stderr): os.set_blocking(pipe.fileno(),False)
        sel.register(proc.stdout,selectors.EVENT_READ,("stdout",kind["stdout_max_bytes"])); sel.register(proc.stderr,selectors.EVENT_READ,("stderr",kind["stderr_max_bytes"])); deadline=time.monotonic()+kind["timeout_seconds"]
        while sel.get_map():
            now=time.monotonic()
            if clock()>=authority_expiry: error="authorization_expired_during_execution"; break
            if now>=deadline: error="execution_timeout"; break
            if exited(proc.pid):
                drain=drain or min(deadline,now+1)
                if now>=drain: error="pipe_drain_timeout"; break
            for key,_ in sel.select(min(.1,deadline-now)):
                label,limit=key.data
                try: chunk=os.read(key.fileobj.fileno(),min(65536,limit+1-len(data[label])))
                except BlockingIOError: continue
                if not chunk: sel.unregister(key.fileobj); continue
                data[label]+=chunk
                if len(data[label])>limit: error=f"{label}_limit_exceeded"; break
            if error: break
        if not error and not exited(proc.pid):
            while not exited(proc.pid):
                if clock()>=authority_expiry: error="authorization_expired_during_execution"; break
                if time.monotonic()>=deadline: error="execution_timeout"; break
                time.sleep(.02)
    finally:
        try: reaped,clean,lingering=retire(proc,owner_pid,baseline)
        finally:
            try: _restore_descendant_containment(prior_subreaper,clean)
            finally:
                if sel is not None: sel.close()
                if proc.stdout is not None: proc.stdout.close()
                if proc.stderr is not None: proc.stderr.close()
    if lingering and not error: error="escaped_descendant_detected"
    if not clean and not error: error="descendant_cleanup_unconfirmed"
    return {"exit_code":proc.returncode if proc.returncode is not None else -9,"stdout":bytes(data["stdout"]),"stderr":bytes(data["stderr"]),"failure":error,"leader_reaped":reaped,"cleanup_confirmed":clean,"escaped_descendants_absence_proven":clean,"target_contact_performed":True}
''',
    "harness containment integration",
)
source = replace_once(
    source,
    '"cleanup_scope":"original_process_group_only","cleanup_confirmed":bool(run.get("cleanup_confirmed",False)),"escaped_descendants_absence_proven":False',
    '"cleanup_scope":CONTAINMENT_SCOPE,"cleanup_confirmed":bool(run.get("cleanup_confirmed",False)),"escaped_descendants_absence_proven":bool(run.get("escaped_descendants_absence_proven",False))',
    "terminal containment receipt",
)
source = replace_once(
    source,
    '"leader_reaped":False,"cleanup_confirmed":False,"target_contact_performed":contact_may_have_occurred',
    '"leader_reaped":False,"cleanup_confirmed":False,"escaped_descendants_absence_proven":False,"target_contact_performed":contact_may_have_occurred',
    "fallback containment receipt",
)
source_path.write_text(source, encoding="utf-8")


test_path = ROOT / "tests/test_trusted_executor.py"
tests = test_path.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    "    def prepare(self, *, exit_code=0, output_bytes=0, sleep_seconds=0, expiry_seconds=1800, manifest_extra=None, bundle_fifo=False, close_output=False, delayed_marker=False, mutate_admission=None, mutate_policy=None, symlink_harness=False):",
    "    def prepare(self, *, exit_code=0, output_bytes=0, sleep_seconds=0, expiry_seconds=1800, manifest_extra=None, bundle_fifo=False, close_output=False, delayed_marker=False, escape_descendant=False, mutate_admission=None, mutate_policy=None, symlink_harness=False):",
    "hostile descendant fixture argument",
)
tests = replace_once(
    tests,
    '''        if bundle_fifo: script+='mkfifo "$OWNER_OPEN_R5_OUTPUT_DIR/blocked.fifo"\nchmod 600 "$OWNER_OPEN_R5_OUTPUT_DIR/blocked.fifo"\n'
        script+=f"exit {exit_code}\n"
''',
    '''        if bundle_fifo: script+='mkfifo "$OWNER_OPEN_R5_OUTPUT_DIR/blocked.fifo"\nchmod 600 "$OWNER_OPEN_R5_OUTPUT_DIR/blocked.fifo"\n'
        if escape_descendant:
            script+=("python3 - <<'PY' &\n"
                     "import os,signal,time\n"
                     "from pathlib import Path\n"
                     "if os.fork(): os._exit(0)\n"
                     "os.setsid()\n"
                     "if os.fork(): os._exit(0)\n"
                     "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                     "os.close(1); os.close(2)\n"
                     "Path(os.environ['TMPDIR'],'escape-ready').write_text('ready')\n"
                     "time.sleep(3)\n"
                     "Path(os.environ['TMPDIR'],'escaped-marker').write_text('escaped')\n"
                     "Path(os.environ['OWNER_OPEN_R5_OUTPUT_DIR'],'escaped-bundle-mutation').write_text('escaped')\n"
                     "PY\n"
                     "i=0; while [ ! -f \"$TMPDIR/escape-ready\" ] && [ $i -lt 200 ]; do i=$((i+1)); sleep .01; done\n"
                     "test -f \"$TMPDIR/escape-ready\"\n")
        script+=f"exit {exit_code}\n"
''',
    "double-fork setsid fixture",
)
tests = replace_once(
    tests,
    '        self.assertEqual(result["status"],"CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW"); self.assertFalse(result["promotion_authorized"]); self.assertTrue(result["cleanup_confirmed"])',
    '        self.assertEqual(result["status"],"CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW"); self.assertFalse(result["promotion_authorized"]); self.assertTrue(result["cleanup_confirmed"]); self.assertTrue(result["escaped_descendants_absence_proven"]); self.assertEqual(result["cleanup_scope"],trusted_executor.CONTAINMENT_SCOPE)',
    "success containment assertions",
)
tests = replace_once(
    tests,
    '''    def test_bundle_walk_errors_fail_closed(self):
''',
    '''    def test_double_fork_setsid_descendant_is_contained_and_terminalized(self):
        self.prepare(escape_descendant=True); started=time.monotonic()
        with self.assertRaisesRegex(ExecutionError,"escaped_descendant_detected"): execute(NONCE,config=self.config,now=NOW)
        self.assertLess(time.monotonic()-started,2.0); time.sleep(.15)
        result=self.result(); self.assertEqual(result["status"],"CAPTURE_FAILED_NO_RETRY"); self.assertEqual(result["failure"],"escaped_descendant_detected"); self.assertTrue(result["cleanup_confirmed"]); self.assertTrue(result["escaped_descendants_absence_proven"]); self.assertEqual(result["cleanup_scope"],trusted_executor.CONTAINMENT_SCOPE)
        self.assertFalse((self.state/"work"/NONCE/"cwd"/"escaped-marker").exists()); self.assertFalse((self.state/"work"/NONCE/"bundle"/"escaped-bundle-mutation").exists())
        with self.assertRaises(ReplayError): execute(NONCE,config=self.config,now=NOW)

    def test_bundle_walk_errors_fail_closed(self):
''',
    "hostile descendant regression",
)
tests = replace_once(
    tests,
    '''        self.tearDown(); self.setUp(); self.prepare()
        with mock.patch.object(trusted_executor,"group_members",side_effect=ExecutionError("injected procfs failure")):
            with self.assertRaisesRegex(ExecutionError,"process_group_cleanup_unconfirmed"): execute(NONCE,config=self.config,now=NOW)
        result=self.result(); self.assertEqual(result["status"],"CAPTURE_FAILED_NO_RETRY"); self.assertFalse(result["cleanup_confirmed"])
        with self.assertRaises(ReplayError): execute(NONCE,config=self.config,now=NOW)
''',
    '''        self.tearDown(); self.setUp(); self.prepare(); original_descendants=trusted_executor._descendant_identities; calls=0
        def fail_cleanup_observation(owner):
            nonlocal calls
            calls+=1
            if calls>2: raise ExecutionError("injected procfs failure")
            return original_descendants(owner)
        with mock.patch.object(trusted_executor,"_descendant_identities",side_effect=fail_cleanup_observation):
            with self.assertRaisesRegex(ExecutionError,"descendant_cleanup_unconfirmed"): execute(NONCE,config=self.config,now=NOW)
        result=self.result(); self.assertEqual(result["status"],"CAPTURE_FAILED_NO_RETRY"); self.assertFalse(result["cleanup_confirmed"]); self.assertFalse(result["escaped_descendants_absence_proven"])
        with self.assertRaises(ReplayError): execute(NONCE,config=self.config,now=NOW)
''',
    "procfs containment failure regression",
)
test_path.write_text(tests, encoding="utf-8")


doc_path = ROOT / "EXECUTOR.md"
doc = doc_path.read_text(encoding="utf-8")
doc = replace_once(
    doc,
    '''Timeout, output overflow, nonzero exit, invalid bundle or unconfirmed
original-process-group cleanup are terminal failures. After
`STARTED_NO_AUTOMATIC_RETRY` is durable, unexpected working-directory, fsync,
process-launch, worker or inspection failures are converted to a non-overwriting
`CAPTURE_FAILED_NO_RETRY` receipt. If the ordinary result medium is unavailable,
a separate non-overwriting terminal-failure receipt binds the intended result
digest. If both media are unavailable, the durable STARTED record remains the
authoritative no-retry boundary and the service reports that degradation
explicitly. Every started nonce is non-retryable. A successful capture is only
`CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW`; it does not change a gap.
Setsid-escaped descendants are explicitly not proven absent.
''',
    '''Timeout, output overflow, nonzero exit, invalid bundle, an outliving descendant
or unconfirmed complete-descendant cleanup are terminal failures. Before launch,
the executor enables Linux child-subreaper semantics and requires pidfd signaling
plus procfs identity/start-time observation. Daemonized or `setsid()` descendants
therefore remain in the executor-owned descendant tree, are signaled by stable
pidfd identity, reaped, and observed absent twice before any successful receipt.
After
`STARTED_NO_AUTOMATIC_RETRY` is durable, unexpected working-directory, fsync,
process-launch, worker or inspection failures are converted to a non-overwriting
`CAPTURE_FAILED_NO_RETRY` receipt. If the ordinary result medium is unavailable,
a separate non-overwriting terminal-failure receipt binds the intended result
digest. If both media are unavailable, the durable STARTED record remains the
authoritative no-retry boundary and the service reports that degradation
explicitly. Every started nonce is non-retryable. A successful capture is only
`CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW`; it does not change a gap. A
success receipt records `linux_subreaper_pidfd_descendant_tree_v1` and proves the
complete spawned descendant tree empty. Any observation or signaling ambiguity
fails closed and leaves the durable one-shot boundary authoritative.
''',
    "executor containment documentation",
)
doc_path.write_text(doc, encoding="utf-8")

print("materialized final gap closure:")
for path in (source_path, test_path, doc_path):
    print(path)
