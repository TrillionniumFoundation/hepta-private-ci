#!/usr/bin/env python3
"""One-shot fixed-harness executor for admitted Trillionnium OS evidence capture."""
from __future__ import annotations
import argparse, hashlib, json, os, re, selectors, signal, stat, subprocess, sys, time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

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
    try: fd=os.open(path,os.O_RDONLY|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0))
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
    s=snapshot(cfg.policy,cfg.policy.parent,cfg.owner_uid,262144); p=load_json(s.data,"execution policy",262144)
    fields={"schema","version","status","repository","required_uid","admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist","issuer_allowlist","allowed_subjects","max_bundle_files","max_bundle_bytes","evidence_kinds"}; exact(p,fields,"execution policy")
    if (p["schema"],p["version"],p["status"],p["required_uid"])!=(POLICY_SCHEMA,"1","ACTIVE",cfg.owner_uid): raise ExecutionError("execution policy is not active")
    for k in ("admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist","issuer_allowlist","allowed_subjects"):
        if not isinstance(p[k],list) or not p[k]: raise ExecutionError(f"empty policy allowlist: {k}")
    for k in ("admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist"):
        if any(not isinstance(v,str) or not HEX64.fullmatch(v) for v in p[k]): raise ExecutionError(f"bad digest allowlist: {k}")
    for k in ("max_bundle_files","max_bundle_bytes"):
        if type(p[k]) is not int or not 0<p[k]<=2**31: raise ExecutionError(f"bad policy bound: {k}")
    if not isinstance(p["evidence_kinds"],dict): raise ExecutionError("missing evidence policy")
    return p,s

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
    if roles.get("producer")!=a["requester"] or roles.get("admission_issuer")!=a["issuer"] or len(set(roles.values()))!=len(roles): raise ExecutionError("admission roles are not separated")
    for k in ("request_sha256","grant_sha256","grant_signature_sha256","grant_public_key_sha256","admission_policy_sha256","harness_sha256","target_attestation_sha256"):
        if not isinstance(a[k],str) or not HEX64.fullmatch(a[k]): raise ExecutionError(f"bad digest: {k}")
    if utc(a["admitted_at"],"admitted_at")>now or utc(a["grant_expires_at"],"grant expiry")<=now or utc(a["authorization_expires_at"],"route expiry")<=now: raise ExecutionError("admission time bounds are invalid")
    for k in ("target_contact_performed","candidate_code_executed","capture_scheduled","automatic_redispatch","promotion_authorized","public_release"): false(a,k,"admission")
    return kind

def check_attestation(t,a,kind,harness_digest,now):
    exact(t,ATTEST_FIELDS,"target attestation")
    if (t["schema"],t["version"],t["status"])!=(ATTEST_SCHEMA,"1","READY"): raise ExecutionError("unsupported target attestation")
    for k in ("repository","source_commit","source_tree","evidence_kind","evidence_level","external_lane","authorization_nonce"):
        if t[k]!=a[k]: raise ExecutionError(f"attestation cross-splice at {k}")
    if t["harness_sha256"]!=harness_digest or a["harness_sha256"]!=harness_digest: raise ExecutionError("harness digest mismatch")
    if t["environment_class"]!=kind["environment_class"] or t["custodian"]!=a["roles"][kind["custodian_role"]]: raise ExecutionError("target environment or custodian mismatch")
    target=identity(t["target_id"],"target id")
    if utc(t["issued_at"],"attestation issued_at")>now or utc(t["expires_at"],"attestation expiry")<=now or utc(t["expires_at"],"attestation expiry")>utc(a["grant_expires_at"],"grant expiry"): raise ExecutionError("target attestation time bounds are invalid")
    for k in ("automatic_redispatch","promotion_authorized","public_release"): false(t,k,"target attestation")
    return target

def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC); os.fsync(fd); os.close(fd)

def ensure_state(root,uid):
    secure_dir(root,uid); out={}
    for name in ("started","results","work"):
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
    for sig,grace in ((signal.SIGTERM,.25),(signal.SIGKILL,1.0)):
        try: os.killpg(proc.pid,sig)
        except ProcessLookupError: pass
        deadline=time.monotonic()+grace
        while time.monotonic()<deadline and (not exited(proc.pid) or group_members(proc.pid)): time.sleep(.02)
    clean1=not group_members(proc.pid); time.sleep(.02); clean2=not group_members(proc.pid)
    try: proc.wait(timeout=1); reaped=True
    except subprocess.TimeoutExpired: reaped=False
    return reaped,reaped and clean1 and clean2

def run_harness(harness,cwd,env,kind):
    cmd=f"/proc/self/fd/{harness.fd}"; proc=subprocess.Popen([cmd],executable=cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=cwd,env=env,close_fds=True,pass_fds=(harness.fd,),start_new_session=True)
    assert proc.stdout and proc.stderr
    for pipe in (proc.stdout,proc.stderr): os.set_blocking(pipe.fileno(),False)
    sel=selectors.DefaultSelector(); sel.register(proc.stdout,selectors.EVENT_READ,("stdout",kind["stdout_max_bytes"])); sel.register(proc.stderr,selectors.EVENT_READ,("stderr",kind["stderr_max_bytes"])); data={"stdout":bytearray(),"stderr":bytearray()}; deadline=time.monotonic()+kind["timeout_seconds"]; drain=None; error=None
    try:
        while sel.get_map():
            now=time.monotonic()
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
            while time.monotonic()<deadline and not exited(proc.pid): time.sleep(.02)
            if not exited(proc.pid): error="execution_timeout"
    finally:
        reaped,clean=retire(proc); sel.close(); proc.stdout.close(); proc.stderr.close()
    if not clean and not error: error="process_group_cleanup_unconfirmed"
    return {"exit_code":proc.returncode if proc.returncode is not None else -9,"stdout":bytes(data["stdout"]),"stderr":bytes(data["stderr"]),"failure":error,"leader_reaped":reaped,"cleanup_confirmed":clean}

def inspect_bundle(bundle,uid,p,a,target):
    secure_dir(bundle,uid); entries=[]; total=0; manifest_raw=None
    for root,dirs,files in os.walk(bundle,followlinks=False):
        root=Path(root)
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
    m=load_json(manifest_raw,"bundle manifest",1048576)
    required={"schema":BUNDLE_SCHEMA,"repository":a["repository"],"source_commit":a["source_commit"],"source_tree":a["source_tree"],"evidence_kind":a["evidence_kind"],"evidence_level":a["evidence_level"],"authorization_nonce":a["authorization_nonce"],"target_id":target,"synthetic":False,"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
    for k,v in required.items():
        if m.get(k)!=v: raise ExecutionError(f"bundle manifest mismatch at {k}")
    entries.sort(key=lambda x:x["path"]); tree=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"manifest_sha256":manifest["sha256"],"bundle_tree_sha256":tree,"bundle_file_count":len(entries),"bundle_total_bytes":total}

def execute(nonce,*,config:Config,now=None):
    if sys.platform!="linux" or not NONCE.fullmatch(nonce): raise ExecutionError("Linux and a valid nonce are required")
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); p,ps=read_policy(config); snaps=[ps]; started=False; a=None; state=None
    try:
        ads=snapshot(config.admissions/f"{nonce}.json",config.admissions,config.owner_uid,131072); snaps.append(ads); a=load_json(ads.data,"admission",131072); kind=check_admission(a,p,now)
        hs=snapshot(config.harnesses/a["evidence_kind"],config.harnesses,config.owner_uid,16*1024*1024,True); ts=snapshot(config.attestations/f"{a['evidence_kind']}.json",config.attestations,config.owner_uid,65536); snaps += [hs,ts]
        if hs.digest!=a["harness_sha256"] or ts.digest!=a["target_attestation_sha256"]: raise ExecutionError("fixed target bytes do not match admission")
        target=check_attestation(load_json(ts.data,"target attestation",65536),a,kind,hs.digest,now); state=ensure_state(config.state,config.owner_uid)
        start={"schema":"org.trillionnium.external-evidence-execution-start.v1","status":"STARTED_NO_AUTOMATIC_RETRY","authorization_nonce":nonce,"admission_sha256":ads.digest,"harness_sha256":hs.digest,"target_attestation_sha256":ts.digest,"started_at":now.isoformat().replace("+00:00","Z"),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}; write_once(state["started"],f"{nonce}.json",start); started=True
        work=state["work"]/nonce; os.mkdir(work,0o700); fsync_dir(state["work"]); cwd=work/"cwd"; bundle=work/"bundle"; os.mkdir(cwd,0o700); os.mkdir(bundle,0o700); fsync_dir(work); admission_copy=write_raw_once(work,"admission.json",ads.data)
        attestation_copy=write_raw_once(work,"target-attestation.json",ts.data)
        env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","LANG":"C.UTF-8","LC_ALL":"C.UTF-8","HOME":"/nonexistent","TMPDIR":str(cwd),"OWNER_OPEN_R5_ADMISSION":str(admission_copy),"OWNER_OPEN_R5_TARGET_ATTESTATION":str(attestation_copy),"OWNER_OPEN_R5_OUTPUT_DIR":str(bundle),"OWNER_OPEN_R5_EVIDENCE_KIND":a["evidence_kind"]}
        run=run_harness(hs,cwd,env,kind); failure=run["failure"] or (f"harness_exit_{run['exit_code']}" if run["exit_code"] else None); info=None
        if not failure:
            try: info=inspect_bundle(bundle,config.owner_uid,p,a,target)
            except ExecutionError as e: failure=f"bundle_invalid:{e}"
        result={"schema":RESULT_SCHEMA,"version":"1","status":"CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW" if not failure else "CAPTURE_FAILED_NO_RETRY","repository":a["repository"],"source_commit":a["source_commit"],"source_tree":a["source_tree"],"evidence_kind":a["evidence_kind"],"evidence_level":a["evidence_level"],"authorization_nonce":nonce,"target_id":target,"admission_sha256":ads.digest,"harness_sha256":hs.digest,"target_attestation_sha256":ts.digest,"exit_code":run["exit_code"],"stdout_sha256":hashlib.sha256(run["stdout"]).hexdigest(),"stdout_bytes":len(run["stdout"]),"stderr_sha256":hashlib.sha256(run["stderr"]).hexdigest(),"stderr_bytes":len(run["stderr"]),"failure":failure,"leader_reaped":run["leader_reaped"],"cleanup_scope":"original_process_group_only","cleanup_confirmed":run["cleanup_confirmed"],"escaped_descendants_absence_proven":False,"target_contact_performed":True,"candidate_code_executed":False,"capture_performed":True,"evidence_reviewed":False,"gap_transition_authorized":False,"finished_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
        if info: result.update(info)
        write_once(state["results"],f"{nonce}.json",result)
        if failure: raise ExecutionError(failure)
        return result
    except ExecutionError: raise
    except Exception as e:
        if started: raise ExecutionError(f"post-start failure; execution remains non-retryable: {e}") from e
        raise ExecutionError(f"pre-start failure: {e}") from e
    finally:
        for s in reversed(snaps): s.close()

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--nonce",required=True); a=ap.parse_args(argv)
    if os.geteuid()!=0: print("trusted executor must run as root",file=sys.stderr); return 2
    cfg=Config(PROD_ADMISSIONS,PROD_HARNESSES,PROD_ATTESTATIONS,PROD_POLICY,PROD_STATE)
    try: result=execute(a.nonce,config=cfg)
    except ExecutionError as e: print(f"FAIL: {e}",file=sys.stderr); return 1
    print(json.dumps(result,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
