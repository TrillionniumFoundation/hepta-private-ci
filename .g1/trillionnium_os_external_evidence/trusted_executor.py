#!/usr/bin/env python3
"""One-shot fixed-harness executor for admitted Trillionnium OS evidence capture."""
from __future__ import annotations
import argparse, fcntl, hashlib, json, multiprocessing, os, re, selectors, signal, stat, subprocess, sys, time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

ADMISSION_SCHEMA="org.trillionnium.external-evidence-admission.v1"
POLICY_SCHEMA="org.trillionnium.external-evidence-execution-policy.v1"
ATTEST_SCHEMA="org.trillionnium.target-evidence-target-attestation.v1"
BUNDLE_SCHEMA="org.trillionnium.target-evidence-bundle.v1"
RESULT_SCHEMA="org.trillionnium.external-evidence-execution-result.v1"
PROD_ADMISSIONS=Path("/var/lib/owner-open-r5/admission/admitted")
PROD_HARNESSES=Path("/opt/owner-open-r5/harnesses")
PROD_ATTESTATIONS=Path("/etc/owner-open-r5/attestations")
PROD_POLICY=Path("/etc/owner-open-r5/execution-policy.v1.json")
PROD_STATE=Path("/var/lib/owner-open-r5/executor")
HEX40=re.compile(r"[0-9a-f]{40}"); HEX64=re.compile(r"[0-9a-f]{64}")
NONCE=re.compile(r"[0-9a-f]{32,64}"); IDENT=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}")
ADMISSION_FIELDS={"schema","version","status","repository","source_commit","source_tree","promotion_pr_number","promotion_pr_head","evidence_kind","evidence_level","external_lane","authorization_nonce","authorization_ticket","authorization_expires_at","requester","roles","grant_id","issuer","key_id","request_sha256","grant_sha256","grant_signature_sha256","grant_public_key_sha256","admission_policy_sha256","authorization_class","grant_issued_at","grant_expires_at","harness_sha256","target_attestation_sha256","admitted_at","target_contact_performed","candidate_code_executed","capture_scheduled","automatic_redispatch","promotion_authorized","public_release"}
ATTEST_FIELDS={"schema","version","status","repository","source_commit","source_tree","evidence_kind","evidence_level","external_lane","authorization_nonce","target_id","environment_class","custodian","harness_sha256","issued_at","expires_at","automatic_redispatch","promotion_authorized","public_release"}
BUNDLE_FIELDS={"schema","repository","source_commit","source_tree","evidence_kind","evidence_level","authorization_nonce","target_id","synthetic","automatic_redispatch","promotion_authorized","public_release"}

class ExecutionError(RuntimeError): pass
class ReplayError(ExecutionError): pass

@dataclass(frozen=True)
class Config:
    admissions:Path; harnesses:Path; attestations:Path; policy:Path; state:Path; owner_uid:int=0

@dataclass
class Snap:
    fd:int; data:bytes; digest:str
    def close(self):
        if self.fd>=0: os.close(self.fd); self.fd=-1

def pairs(items):
    out={}
    for k,v in items:
        if k in out: raise ExecutionError(f"duplicate JSON member: {k}")
        out[k]=v
    return out

def load_json(raw:bytes,label:str,limit:int):
    if len(raw)>limit: raise ExecutionError(f"{label} exceeds {limit} bytes")
    try: value=json.loads(raw.decode(),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ExecutionError(f"non-finite number: {x}")))
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as e: raise ExecutionError(f"invalid {label}: {e}") from e
    if not isinstance(value,dict): raise ExecutionError(f"{label} must be an object")
    return value

def utc(value,label):
    if not isinstance(value,str) or not value.endswith("Z"): raise ExecutionError(f"invalid {label}")
    try: return datetime.fromisoformat(value[:-1]+"+00:00").astimezone(timezone.utc)
    except ValueError as e: raise ExecutionError(f"invalid {label}") from e

def exact(value:Mapping[str,Any],fields:set[str],label:str):
    if set(value)!=fields: raise ExecutionError(f"{label} fields differ")

def false(value,key,label):
    if type(value.get(key)) is not bool or value[key]: raise ExecutionError(f"{label}.{key} must be false")

def identity(value,label):
    if not isinstance(value,str) or not IDENT.fullmatch(value): raise ExecutionError(f"invalid {label}")
    return value

def secure_dir(path:Path,uid:int):
    try: st=os.lstat(path)
    except OSError as e: raise ExecutionError(f"cannot stat directory {path}: {e}") from e
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_uid!=uid or st.st_mode&0o022: raise ExecutionError(f"insecure directory: {path}")

def snapshot(path:Path,root:Path,uid:int,limit:int,executable=False):
    secure_dir(root,uid)
    try: rel=path.relative_to(root)
    except ValueError as e: raise ExecutionError(f"path escapes secure root: {path}") from e
    if not rel.parts or any(x in {"",".",".."} for x in rel.parts): raise ExecutionError(f"unsafe path: {path}")
    cur=root
    for part in rel.parts[:-1]: cur/=part; secure_dir(cur,uid)
    try: fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0))
    except OSError as e: raise ExecutionError(f"cannot open {path}: {e}") from e
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=uid or before.st_mode&0o022: raise ExecutionError(f"insecure file: {path}")
        if executable and not before.st_mode&stat.S_IXUSR: raise ExecutionError(f"harness is not executable: {path}")
        if not executable and before.st_mode&0o111: raise ExecutionError(f"data file is executable: {path}")
        parts=[]; total=0
        while True:
            chunk=os.read(fd,min(65536,limit+1-total))
            if not chunk: break
            parts.append(chunk); total+=len(chunk)
            if total>limit: raise ExecutionError(f"file too large: {path}")
        after=os.fstat(fd); named=os.stat(path,follow_symlinks=False); key=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_mode,s.st_uid,s.st_nlink)
        if key(before)!=key(after) or key(after)!=key(named): raise ExecutionError(f"file changed while read: {path}")
        data=b"".join(parts); os.lseek(fd,0,os.SEEK_SET); return Snap(fd,data,hashlib.sha256(data).hexdigest())
    except Exception: os.close(fd); raise

def read_policy(cfg):
    s=snapshot(cfg.policy,cfg.policy.parent,cfg.owner_uid,262144)
    try:
        p=load_json(s.data,"execution policy",262144)
        fields={"schema","version","status","repository","required_uid","admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist","issuer_allowlist","allowed_subjects","max_bundle_files","max_bundle_bytes","bundle_inspection_timeout_seconds","evidence_kinds"}; exact(p,fields,"execution policy")
        if (p["schema"],p["version"],p["status"],p["required_uid"])!=(POLICY_SCHEMA,"1","ACTIVE",cfg.owner_uid): raise ExecutionError("execution policy is not active")
        for k in ("admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist","issuer_allowlist","allowed_subjects"):
            if not isinstance(p[k],list) or not p[k]: raise ExecutionError(f"empty policy allowlist: {k}")
        for k in ("admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist"):
            if any(not isinstance(v,str) or not HEX64.fullmatch(v) for v in p[k]): raise ExecutionError(f"bad digest allowlist: {k}")
        for k in ("max_bundle_files","max_bundle_bytes"):
            if type(p[k]) is not int or not 0<p[k]<=2**31: raise ExecutionError(f"bad policy bound: {k}")
        timeout=p["bundle_inspection_timeout_seconds"]
        if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not 0<timeout<=2**31: raise ExecutionError("bad policy bound: bundle_inspection_timeout_seconds")
        if not isinstance(p["evidence_kinds"],dict): raise ExecutionError("missing evidence policy")
        return p,s
    except Exception:
        s.close(); raise

def check_admission(a,p,now):
    exact(a,ADMISSION_FIELDS,"admission")
    if (a["schema"],a["version"],a["status"],a["repository"])!=(ADMISSION_SCHEMA,"1","ADMITTED_PENDING_FIXED_TARGET_EXECUTION",p["repository"]): raise ExecutionError("unsupported admission")
    for k in ("source_commit","source_tree","promotion_pr_head"):
        if not isinstance(a[k],str) or not HEX40.fullmatch(a[k]): raise ExecutionError(f"bad {k}")
    if type(a["promotion_pr_number"]) is not int or a["promotion_pr_number"]<=0: raise ExecutionError("bad promotion PR")
    subject={k:a[k] for k in ("source_commit","source_tree","promotion_pr_number","promotion_pr_head")}
    if subject not in p["allowed_subjects"]: raise ExecutionError("admission subject is outside execution policy")
    if a["admission_policy_sha256"] not in p["admission_policy_sha256_allowlist"] or a["grant_public_key_sha256"] not in p["grant_public_key_sha256_allowlist"] or a["issuer"] not in p["issuer_allowlist"]: raise ExecutionError("admission trust chain is not allowlisted")
    kind=p["evidence_kinds"].get(a["evidence_kind"])
    if not isinstance(kind,dict): raise ExecutionError("unknown evidence kind")
    exact(kind,{"level","lane","authorization_class","required_roles","custodian_role","environment_class","timeout_seconds","stdout_max_bytes","stderr_max_bytes"},"evidence policy")
    if not isinstance(kind["required_roles"],list) or kind["custodian_role"] not in kind["required_roles"] or not isinstance(kind["environment_class"],str): raise ExecutionError("invalid evidence policy roles")
    for bound in ("timeout_seconds","stdout_max_bytes","stderr_max_bytes"):
        if type(kind[bound]) is not int or not 0<kind[bound]<=2**31: raise ExecutionError(f"bad evidence policy bound: {bound}")
    if (a["evidence_level"],a["external_lane"],a["authorization_class"])!=(kind["level"],kind["lane"],kind["authorization_class"]): raise ExecutionError("admission route mismatch")
    if not isinstance(a["authorization_nonce"],str) or not NONCE.fullmatch(a["authorization_nonce"]): raise ExecutionError("bad nonce")
    if not isinstance(a["roles"],dict) or set(a["roles"])!=set(kind["required_roles"]): raise ExecutionError("role set mismatch")
    identity(a["requester"],"requester"); identity(a["issuer"],"issuer"); identity(a["key_id"],"key id")
    if not isinstance(a["grant_id"],str) or not NONCE.fullmatch(a["grant_id"]): raise ExecutionError("bad grant id")
    roles={role:identity(value,f"role {role}") for role,value in a["roles"].items()}
    if roles.get("producer")!=a["requester"] or roles.get("admission_issuer")!=a["issuer"] or len({value.casefold() for value in roles.values()})!=len(roles): raise ExecutionError("admission roles are not separated")
    for k in ("request_sha256","grant_sha256","grant_signature_sha256","grant_public_key_sha256","admission_policy_sha256","harness_sha256","target_attestation_sha256"):
        if not isinstance(a[k],str) or not HEX64.fullmatch(a[k]): raise ExecutionError(f"bad digest: {k}")
    issued=utc(a["grant_issued_at"],"grant issued_at"); grant_expiry=utc(a["grant_expires_at"],"grant expiry"); route_expiry=utc(a["authorization_expires_at"],"route expiry")
    if utc(a["admitted_at"],"admitted_at")>now or issued>=grant_expiry or grant_expiry<=now or route_expiry<=now or grant_expiry>route_expiry: raise ExecutionError("admission time bounds are invalid")
    for k in ("target_contact_performed","candidate_code_executed","capture_scheduled","automatic_redispatch","promotion_authorized","public_release"): false(a,k,"admission")
    return kind,min(grant_expiry,route_expiry)

def check_attestation(t,a,kind,harness_digest,now):
    exact(t,ATTEST_FIELDS,"target attestation")
    if (t["schema"],t["version"],t["status"])!=(ATTEST_SCHEMA,"1","READY"): raise ExecutionError("unsupported target attestation")
    for k in ("repository","source_commit","source_tree","evidence_kind","evidence_level","external_lane","authorization_nonce"):
        if t[k]!=a[k]: raise ExecutionError(f"attestation cross-splice at {k}")
    if t["harness_sha256"]!=harness_digest or a["harness_sha256"]!=harness_digest: raise ExecutionError("harness digest mismatch")
    if t["environment_class"]!=kind["environment_class"] or t["custodian"]!=a["roles"][kind["custodian_role"]]: raise ExecutionError("target environment or custodian mismatch")
    target=identity(t["target_id"],"target id")
    issued=utc(t["issued_at"],"attestation issued_at"); expires=utc(t["expires_at"],"attestation expiry")
    if issued>now or issued>=expires or expires<=now or expires>utc(a["grant_expires_at"],"grant expiry"): raise ExecutionError("target attestation time bounds are invalid")
    for k in ("automatic_redispatch","promotion_authorized","public_release"): false(t,k,"target attestation")
    return target,expires

def sealed_harness(data,digest):
    if not hasattr(os,"memfd_create") or not Path("/proc/self/fd").is_dir(): raise ExecutionError("sealed Linux memfds are required")
    fd=os.memfd_create("owner-open-r5-harness",getattr(os,"MFD_CLOEXEC",1)|getattr(os,"MFD_ALLOW_SEALING",2))
    try:
        off=0
        while off<len(data):
            n=os.write(fd,data[off:])
            if n<=0: raise ExecutionError("sealed harness write stalled")
            off+=n
        os.fchmod(fd,0o500); os.lseek(fd,0,os.SEEK_SET)
        seals=sum(getattr(fcntl,n,d) for n,d in (("F_SEAL_SEAL",1),("F_SEAL_SHRINK",2),("F_SEAL_GROW",4),("F_SEAL_WRITE",8)))
        fcntl.fcntl(fd,getattr(fcntl,"F_ADD_SEALS",1033),seals)
        snap=Snap(fd,data,digest); fd=-1; return snap
    finally:
        if fd>=0: os.close(fd)

def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
    try: os.fsync(fd)
    finally: os.close(fd)

def ensure_state(root,uid):
    secure_dir(root,uid); out={}
    for name in ("started","results","terminal_failures","work"):
        p=root/name
        try: os.mkdir(p,0o700); fsync_dir(root)
        except FileExistsError: pass
        secure_dir(p,uid); out[name]=p
    return out

def write_raw_once(directory,name,raw):
    path=directory/name
    try: fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0),0o600)
    except FileExistsError as e: raise ReplayError(f"one-shot record already exists: {name}") from e
    try:
        off=0
        while off<len(raw):
            n=os.write(fd,raw[off:])
            if n<=0: raise ExecutionError("record write stalled")
            off+=n
        os.fsync(fd)
    finally: os.close(fd)
    fsync_dir(directory); return path

def write_once(directory,name,value):
    raw=(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode(); path=directory/name
    try: fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0),0o600)
    except FileExistsError as e: raise ReplayError(f"one-shot record already exists: {name}") from e
    try:
        off=0
        while off<len(raw):
            n=os.write(fd,raw[off:])
            if n<=0: raise ExecutionError("record write stalled")
            off+=n
        os.fsync(fd)
    finally: os.close(fd)
    fsync_dir(directory); return path

def group_members(pgid):
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

def run_harness(harness,cwd,env,kind,clock:Callable[[],datetime],authority_expiry):
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

def inspect_bundle(bundle,uid,p,a,target):
    secure_dir(bundle,uid); entries=[]; total=0; manifest_raw=None
    def walk_error(error): raise ExecutionError(f"bundle traversal failed: {error}")
    for root,dirs,files in os.walk(bundle,followlinks=False,onerror=walk_error):
        root=Path(root); dirs.sort(); files.sort()
        for name in dirs: secure_dir(root/name,uid)
        for name in files:
            path=root/name; snap=snapshot(path,bundle,uid,p["max_bundle_bytes"])
            try:
                rel=path.relative_to(bundle).as_posix(); entries.append({"path":rel,"bytes":len(snap.data),"sha256":snap.digest}); total+=len(snap.data)
                if rel=="manifest.json": manifest_raw=snap.data
            finally: snap.close()
            if len(entries)>p["max_bundle_files"] or total>p["max_bundle_bytes"]: raise ExecutionError("bundle exceeds policy")
    manifest=next((x for x in entries if x["path"]=="manifest.json"),None)
    if not manifest or manifest_raw is None: raise ExecutionError("bundle manifest is missing")
    m=load_json(manifest_raw,"bundle manifest",1048576); exact(m,BUNDLE_FIELDS,"bundle manifest")
    required={"schema":BUNDLE_SCHEMA,"repository":a["repository"],"source_commit":a["source_commit"],"source_tree":a["source_tree"],"evidence_kind":a["evidence_kind"],"evidence_level":a["evidence_level"],"authorization_nonce":a["authorization_nonce"],"target_id":target,"synthetic":False,"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
    for k,v in required.items():
        if m[k]!=v or type(m[k]) is not type(v): raise ExecutionError(f"bundle manifest mismatch at {k}")
    entries.sort(key=lambda x:x["path"]); tree=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"manifest_sha256":manifest["sha256"],"bundle_tree_sha256":tree,"bundle_file_count":len(entries),"bundle_total_bytes":total}

def _inspect_worker(sender,bundle,uid,p,a,target):
    try:
        try: payload={"ok":True,"info":inspect_bundle(bundle,uid,p,a,target)}
        except BaseException as e: payload={"ok":False,"error":str(e)}
        raw=json.dumps(payload,sort_keys=True,separators=(",",":")).encode()
        sender.send_bytes(raw if len(raw)<=65536 else b'{"ok":false,"error":"inspection response too large"}')
    finally: sender.close()

def _stop_worker(proc):
    if proc.is_alive(): proc.kill()
    proc.join(timeout=1)
    if proc.is_alive(): raise ExecutionError("bundle inspection worker could not be retired")

def inspect_bundle_bounded(bundle,uid,p,a,target,clock,authority_expiry):
    ctx=multiprocessing.get_context("spawn"); receiver,sender=ctx.Pipe(duplex=False)
    proc=ctx.Process(target=_inspect_worker,args=(sender,bundle,uid,p,a,target),daemon=True); deadline=time.monotonic()+p["bundle_inspection_timeout_seconds"]; worker_started=False
    try:
        proc.start(); worker_started=True; sender.close()
        while True:
            if clock()>=authority_expiry: _stop_worker(proc); raise ExecutionError("authorization_expired_during_bundle_inspection")
            remaining=deadline-time.monotonic()
            if remaining<=0: _stop_worker(proc); raise ExecutionError("bundle_inspection_timeout")
            if receiver.poll(min(.05,remaining)):
                try: raw=receiver.recv_bytes(65536)
                except EOFError as e: raise ExecutionError("bundle inspection worker returned no result") from e
                break
            if not proc.is_alive(): proc.join(timeout=1); raise ExecutionError("bundle inspection worker exited without a result")
        proc.join(timeout=max(0,deadline-time.monotonic()))
        if proc.is_alive(): _stop_worker(proc); raise ExecutionError("bundle_inspection_timeout")
        if proc.exitcode!=0: raise ExecutionError("bundle inspection worker failed")
        if clock()>=authority_expiry: raise ExecutionError("authorization_expired_during_bundle_inspection")
        response=load_json(raw,"bundle inspection response",65536)
        if set(response)=={"ok","info"} and response["ok"] is True and isinstance(response["info"],dict): return response["info"]
        if set(response)=={"ok","error"} and response["ok"] is False: raise ExecutionError(str(response["error"]))
        raise ExecutionError("invalid bundle inspection response")
    finally:
        receiver.close(); sender.close()
        if worker_started and proc.is_alive(): _stop_worker(proc)

def _json_bytes(value): return (json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode()

def _clock_stamp(clock):
    try: value=clock().astimezone(timezone.utc)
    except Exception: value=datetime.now(timezone.utc)
    return value.isoformat().replace("+00:00","Z")

def _result_record(a,target,ads,hs,ts,run,failure,clock,info=None):
    run=run or {}; stdout=run.get("stdout",b""); stderr=run.get("stderr",b""); contacted=bool(run.get("target_contact_performed",False))
    result={"schema":RESULT_SCHEMA,"version":"1","status":"CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW" if not failure else "CAPTURE_FAILED_NO_RETRY","repository":a["repository"],"source_commit":a["source_commit"],"source_tree":a["source_tree"],"evidence_kind":a["evidence_kind"],"evidence_level":a["evidence_level"],"authorization_nonce":a["authorization_nonce"],"target_id":target,"admission_sha256":ads.digest,"harness_sha256":hs.digest,"target_attestation_sha256":ts.digest,"exit_code":run.get("exit_code",-1),"stdout_sha256":hashlib.sha256(stdout).hexdigest(),"stdout_bytes":len(stdout),"stderr_sha256":hashlib.sha256(stderr).hexdigest(),"stderr_bytes":len(stderr),"failure":failure,"leader_reaped":bool(run.get("leader_reaped",False)),"cleanup_scope":"original_process_group_only","cleanup_confirmed":bool(run.get("cleanup_confirmed",False)),"escaped_descendants_absence_proven":False,"target_contact_performed":contacted,"candidate_code_executed":False,"capture_performed":contacted,"evidence_reviewed":False,"gap_transition_authorized":False,"finished_at":_clock_stamp(clock),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
    if info: result.update(info)
    return result

def persist_terminal_result(state,nonce,result,start_sha256,clock):
    raw=_json_bytes(result)
    try:
        write_raw_once(state["results"],f"{nonce}.json",raw); return "results"
    except ReplayError:
        raise
    except Exception as primary:
        fallback={"schema":"org.trillionnium.external-evidence-terminal-fallback.v1","version":"1","status":"TERMINAL_RESULT_PERSISTENCE_FAILED_NO_RETRY","repository":result["repository"],"source_commit":result["source_commit"],"source_tree":result["source_tree"],"evidence_kind":result["evidence_kind"],"evidence_level":result["evidence_level"],"authorization_nonce":nonce,"target_id":result["target_id"],"started_record_sha256":start_sha256,"intended_result_sha256":hashlib.sha256(raw).hexdigest(),"intended_status":result["status"],"failure":"terminal_result_persistence_failed","target_contact_performed":result["target_contact_performed"],"recorded_at":_clock_stamp(clock),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
        try: write_once(state["terminal_failures"],f"{nonce}.json",fallback)
        except Exception as secondary: raise ExecutionError("terminal result and fallback receipt could not be persisted; durable STARTED_NO_AUTOMATIC_RETRY remains authoritative") from secondary
        return "terminal_failures"

def execute(nonce,*,config:Config,now=None,clock:Callable[[],datetime]|None=None):
    if sys.platform!="linux" or not NONCE.fullmatch(nonce): raise ExecutionError("Linux and a valid nonce are required")
    fixed_now=now is not None; now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); clock=clock or ((lambda: now) if fixed_now else (lambda: datetime.now(timezone.utc)))
    snaps=[]; started=False; terminalized=False; terminalization_attempted=False; stage="pre_start"; a=state=target=ads=hs=ts=None; run=None; start_sha256=""; contact_may_have_occurred=False
    try:
        p,ps=read_policy(config); snaps.append(ps)
        ads=snapshot(config.admissions/f"{nonce}.json",config.admissions,config.owner_uid,131072); snaps.append(ads); a=load_json(ads.data,"admission",131072)
        if a.get("authorization_nonce")!=nonce: raise ExecutionError("admission filename nonce mismatch")
        kind,authority_expiry=check_admission(a,p,now)
        hs=snapshot(config.harnesses/a["evidence_kind"],config.harnesses,config.owner_uid,16*1024*1024,True); snaps.append(hs)
        ts=snapshot(config.attestations/f"{a['evidence_kind']}.json",config.attestations,config.owner_uid,65536); snaps.append(ts)
        if hs.digest!=a["harness_sha256"] or ts.digest!=a["target_attestation_sha256"]: raise ExecutionError("fixed target bytes do not match admission")
        target,attestation_expiry=check_attestation(load_json(ts.data,"target attestation",65536),a,kind,hs.digest,now); authority_expiry=min(authority_expiry,attestation_expiry)
        executable=sealed_harness(hs.data,hs.digest); snaps.append(executable); state=ensure_state(config.state,config.owner_uid)
        start={"schema":"org.trillionnium.external-evidence-execution-start.v1","status":"STARTED_NO_AUTOMATIC_RETRY","authorization_nonce":nonce,"admission_sha256":ads.digest,"harness_sha256":hs.digest,"target_attestation_sha256":ts.digest,"started_at":now.isoformat().replace("+00:00","Z"),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}; start_raw=_json_bytes(start); start_sha256=hashlib.sha256(start_raw).hexdigest(); start_path=state["started"]/f"{nonce}.json"; stage="start_persistence"
        try: write_raw_once(state["started"],f"{nonce}.json",start_raw); started=True
        except ReplayError:
            raise
        except Exception:
            try: started=start_path.exists()
            except OSError: started=True
            raise
        stage="work_directory"; work=state["work"]/nonce; os.mkdir(work,0o700); fsync_dir(state["work"]); cwd=work/"cwd"; bundle=work/"bundle"; os.mkdir(cwd,0o700); os.mkdir(bundle,0o700); fsync_dir(work); admission_copy=write_raw_once(work,"admission.json",ads.data); attestation_copy=write_raw_once(work,"target-attestation.json",ts.data)
        env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","LANG":"C.UTF-8","LC_ALL":"C.UTF-8","HOME":"/nonexistent","TMPDIR":str(cwd),"OWNER_OPEN_R5_ADMISSION":str(admission_copy),"OWNER_OPEN_R5_TARGET_ATTESTATION":str(attestation_copy),"OWNER_OPEN_R5_OUTPUT_DIR":str(bundle),"OWNER_OPEN_R5_EVIDENCE_KIND":a["evidence_kind"]}
        stage="harness_execution"; contact_may_have_occurred=True; run=run_harness(executable,cwd,env,kind,clock,authority_expiry); contact_may_have_occurred=run["target_contact_performed"]; failure=run["failure"] or (f"harness_exit_{run['exit_code']}" if run["exit_code"] else None); info=None
        if not failure:
            stage="bundle_inspection"
            try: info=inspect_bundle_bounded(bundle,config.owner_uid,p,a,target,clock,authority_expiry)
            except ExecutionError as e: failure=f"bundle_invalid:{e}"
        if not failure and clock()>=authority_expiry: failure="authorization_expired_before_result_acceptance"
        result=_result_record(a,target,ads,hs,ts,run,failure,clock,info); stage="result_persistence"; terminalization_attempted=True; location=persist_terminal_result(state,nonce,result,start_sha256,clock); terminalized=True
        if location!="results": raise ExecutionError("terminal result persistence failed; fallback no-retry receipt recorded")
        if failure: raise ExecutionError(failure)
        return result
    except Exception as error:
        if isinstance(error,ReplayError) and not started: raise
        if started and not terminalized and not terminalization_attempted and all(value is not None for value in (a,state,target,ads,hs,ts)):
            terminalization_attempted=True; failure=f"post_start_{stage}_failed"; fallback_run=run or {"exit_code":-1,"stdout":b"","stderr":b"","leader_reaped":False,"cleanup_confirmed":False,"target_contact_performed":contact_may_have_occurred}; result=_result_record(a,target,ads,hs,ts,fallback_run,failure,clock)
            try: location=persist_terminal_result(state,nonce,result,start_sha256,clock); terminalized=True
            except Exception as receipt_error: raise ExecutionError(f"{failure}; terminal receipt unavailable; durable STARTED_NO_AUTOMATIC_RETRY remains authoritative") from receipt_error
            suffix="fallback terminal receipt recorded" if location!="results" else "terminal failure receipt recorded"
            raise ExecutionError(f"{failure}; {suffix}") from error
        if isinstance(error,ExecutionError): raise
        if started: raise ExecutionError(f"post-start failure; durable STARTED_NO_AUTOMATIC_RETRY remains authoritative: {error}") from error
        raise ExecutionError(f"pre-start failure: {error}") from error
    finally:
        for snap in reversed(snaps): snap.close()

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--nonce",required=True); a=ap.parse_args(argv)
    if os.geteuid()!=0: print("trusted executor must run as root",file=sys.stderr); return 2
    cfg=Config(PROD_ADMISSIONS,PROD_HARNESSES,PROD_ATTESTATIONS,PROD_POLICY,PROD_STATE)
    try: result=execute(a.nonce,config=cfg)
    except ExecutionError as e: print(f"FAIL: {e}",file=sys.stderr); return 1
    print(json.dumps(result,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
