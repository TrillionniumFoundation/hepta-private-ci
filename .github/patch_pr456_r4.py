#!/usr/bin/env python3
"""Apply the exact PR #456 review follow-up to the a04ba237 source."""
from pathlib import Path

ROOT = Path(".g1/trillionnium_os_external_evidence")
SOURCE = ROOT / "trusted_executor.py"
DOC = ROOT / "EXECUTOR.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


source = SOURCE.read_text(encoding="utf-8")
source = replace_once(
    source,
    '''def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC); os.fsync(fd); os.close(fd)
''',
    '''def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try: os.fsync(fd)
    finally: os.close(fd)
''',
    "fsync directory cleanup",
)
source = replace_once(
    source,
    '''        if not error and not exited(proc.pid):
            while time.monotonic()<deadline and not exited(proc.pid): time.sleep(.02)
            if not exited(proc.pid): error="execution_timeout"
''',
    '''        if not error and not exited(proc.pid):
            while time.monotonic()<deadline and not exited(proc.pid):
                if clock()>=authority_expiry:
                    error="authorization_expired_during_execution"
                    break
                time.sleep(.02)
            if not error and not exited(proc.pid): error="execution_timeout"
''',
    "closed-pipe authority deadline",
)
source = replace_once(
    source,
    '''def inspect_bundle(bundle,uid,p,a,target):
    secure_dir(bundle,uid); entries=[]; total=0; manifest_raw=None
    for root,dirs,files in os.walk(bundle,followlinks=False):
''',
    '''def inspect_bundle(bundle,uid,p,a,target):
    secure_dir(bundle,uid); entries=[]; total=0; manifest_raw=None
    def walk_error(error): raise ExecutionError(f"bundle traversal failed: {error}")
    for root,dirs,files in os.walk(bundle,followlinks=False,onerror=walk_error):
''',
    "bundle walk error propagation",
)
source = replace_once(
    source,
    '''def execute(nonce,*,config:Config,now=None,clock:Callable[[],datetime]|None=None):
    if sys.platform!="linux" or not NONCE.fullmatch(nonce): raise ExecutionError("Linux and a valid nonce are required")
    fixed_now=now is not None; now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); clock=clock or ((lambda: now) if fixed_now else (lambda: datetime.now(timezone.utc))); snaps=[]; started=False; a=None; state=None
    try:
''',
    '''def execute(nonce,*,config:Config,now=None,clock:Callable[[],datetime]|None=None):
    if sys.platform!="linux" or not NONCE.fullmatch(nonce): raise ExecutionError("Linux and a valid nonce are required")
    fixed_now=now is not None; now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); clock=clock or ((lambda: now) if fixed_now else (lambda: datetime.now(timezone.utc))); snaps=[]; started=False; a=None; state=None; ads=None; hs=None; ts=None; kind=None; target=None; run=None; target_contact_attempted=False
    try:
''',
    "post-start failure state",
)
source = replace_once(
    source,
    '''        run=run_harness(executable,cwd,env,kind,clock,authority_expiry); failure=run["failure"] or (f"harness_exit_{run['exit_code']}" if run["exit_code"] else None); info=None
''',
    '''        target_contact_attempted=True; run=run_harness(executable,cwd,env,kind,clock,authority_expiry); failure=run["failure"] or (f"harness_exit_{run['exit_code']}" if run["exit_code"] else None); info=None
''',
    "target contact attempt tracking",
)
source = replace_once(
    source,
    '''"target_contact_performed":True,"candidate_code_executed":False,"capture_performed":True,''',
    '''"target_contact_performed":run["target_contact_performed"],"candidate_code_executed":False,"capture_performed":run["target_contact_performed"],''',
    "truthful target contact result",
)
source = replace_once(
    source,
    '''    except ExecutionError: raise
    except Exception as e:
        if started: raise ExecutionError(f"post-start failure; execution remains non-retryable: {e}") from e
        raise ExecutionError(f"pre-start failure: {e}") from e
    finally:
''',
    '''    except Exception as e:
        original=e if isinstance(e,ExecutionError) else ExecutionError(f"{'post' if started else 'pre'}-start failure: {e}")
        if started and state is not None and a is not None and ads is not None and hs is not None and ts is not None and kind is not None and target is not None:
            stdout=run["stdout"] if isinstance(run,dict) else b""; stderr=run["stderr"] if isinstance(run,dict) else b""
            failure_text=str(original)[:1024] or type(original).__name__
            terminal={"schema":RESULT_SCHEMA,"version":"1","status":"CAPTURE_FAILED_NO_RETRY","repository":a["repository"],"source_commit":a["source_commit"],"source_tree":a["source_tree"],"evidence_kind":a["evidence_kind"],"evidence_level":a["evidence_level"],"authorization_nonce":nonce,"target_id":target,"admission_sha256":ads.digest,"harness_sha256":hs.digest,"target_attestation_sha256":ts.digest,"exit_code":run["exit_code"] if isinstance(run,dict) else -1,"stdout_sha256":hashlib.sha256(stdout).hexdigest(),"stdout_bytes":len(stdout),"stderr_sha256":hashlib.sha256(stderr).hexdigest(),"stderr_bytes":len(stderr),"failure":failure_text,"leader_reaped":run["leader_reaped"] if isinstance(run,dict) else False,"cleanup_scope":"original_process_group_only","cleanup_confirmed":run["cleanup_confirmed"] if isinstance(run,dict) else False,"escaped_descendants_absence_proven":False,"target_contact_performed":run["target_contact_performed"] if isinstance(run,dict) else target_contact_attempted,"candidate_code_executed":False,"capture_performed":run["target_contact_performed"] if isinstance(run,dict) else target_contact_attempted,"evidence_reviewed":False,"gap_transition_authorized":False,"finished_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
            try: write_once(state["results"],f"{nonce}.json",terminal)
            except ReplayError:
                try:
                    existing=snapshot(state["results"]/f"{nonce}.json",state["results"],config.owner_uid,1048576)
                    try:
                        record=load_json(existing.data,"existing terminal result",1048576)
                        required=set(terminal)
                        if not required.issubset(record): raise ExecutionError("existing terminal result is incomplete")
                        for key in ("schema","version","status","repository","source_commit","source_tree","evidence_kind","evidence_level","authorization_nonce","target_id","admission_sha256","harness_sha256","target_attestation_sha256"):
                            if record[key]!=terminal[key]: raise ExecutionError(f"existing terminal result mismatch at {key}")
                        for key in ("automatic_redispatch","promotion_authorized","public_release"):
                            false(record,key,"existing terminal result")
                    finally: existing.close()
                except Exception as persist_error: raise ExecutionError(f"{original}; terminal failure receipt persistence failed: {persist_error}") from e
            except Exception as persist_error: raise ExecutionError(f"{original}; terminal failure receipt persistence failed: {persist_error}") from e
        if isinstance(e,ExecutionError): raise
        raise original from e
    finally:
''',
    "terminal no-retry receipt",
)
SOURCE.write_text(source, encoding="utf-8")

doc = DOC.read_text(encoding="utf-8")
doc = replace_once(
    doc,
    '''Stdout/stderr, runtime and bundle sizes are bounded. Timeout, output overflow,
nonzero exit, invalid bundle or unconfirmed original-process-group cleanup are
terminal failures. Every started nonce is non-retryable. A successful capture is
''',
    '''Stdout/stderr, runtime and bundle sizes are bounded. Authorization expiry is
checked before contact, while pipes are open, after pipes close, and before a
bundle can be accepted. Bundle traversal errors and non-regular entries fail
closed instead of being treated as partial evidence. Timeout, output overflow,
nonzero exit, invalid bundle or unconfirmed original-process-group cleanup are
terminal failures. Every failure after `STARTED_NO_AUTOMATIC_RETRY` persists one
validated `CAPTURE_FAILED_NO_RETRY` result before the error is surfaced; a
secondary persistence error retains the original failure. Every started nonce is
non-retryable. A successful capture is
''',
    "executor documentation",
)
DOC.write_text(doc, encoding="utf-8")
