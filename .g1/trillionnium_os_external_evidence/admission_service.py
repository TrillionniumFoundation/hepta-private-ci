#!/usr/bin/env python3
"""Independent, fail-closed admission for Trillionnium OS target evidence."""
from __future__ import annotations
import argparse, fcntl, hashlib, json, os, re, stat, subprocess, sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

REQ_SCHEMA="org.trillionnium.target-evidence-admission-request.v2"
GRANT_SCHEMA="org.trillionnium.external-evidence-execution-grant.v1"
POLICY_SCHEMA="org.trillionnium.external-evidence-admission-policy.v1"
ADMISSION_SCHEMA="org.trillionnium.external-evidence-admission.v1"
PROD_POLICY=Path("/etc/owner-open-r5/admission-policy.v1.json")
PROD_KEY=Path("/etc/owner-open-r5/grant-authority.pem")
PROD_STATE=Path("/var/lib/owner-open-r5/admission")
HEX40=re.compile(r"[0-9a-f]{40}"); HEX64=re.compile(r"[0-9a-f]{64}")
NONCE=re.compile(r"[0-9a-f]{32,64}"); IDENT=re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}")
TICKET=re.compile(r"[A-Z0-9][A-Z0-9._:/-]{7,127}")
REQ_FIELDS={"schema","status","repository","evidence_kind","evidence_level","source_commit","source_tree","protected_main_tip_observed","promotion_pr_number","promotion_pr_head","independent_approvals","authorization_ticket","authorization_expires_at","authorization_nonce","requested_by","external_lane","candidate_checkout_performed","candidate_code_executed","external_runner_allocated","capture_scheduled","synthetic","automatic_redispatch","promotion_authorized","public_release"}
GRANT_FIELDS={"schema","version","status","grant_id","request_sha256","repository","source_commit","source_tree","promotion_pr_number","promotion_pr_head","evidence_kind","evidence_level","external_lane","authorization_nonce","authorization_ticket","authorization_expires_at","requester","roles","issuer","key_id","issued_at","expires_at","authorization_class","harness_sha256","target_attestation_sha256","automatic_redispatch","promotion_authorized","public_release"}

class AdmissionError(RuntimeError): pass
class ReplayError(AdmissionError): pass

@dataclass(frozen=True)
class Config:
    policy: Path; public_key: Path; state: Path; owner_uid: int=0
    openssl: Path=Path("/usr/bin/openssl")

@dataclass
class Snap:
    fd:int; data:bytes; digest:str
    def close(self):
        if self.fd>=0: os.close(self.fd); self.fd=-1

def _pairs(items):
    out={}
    for k,v in items:
        if k in out: raise AdmissionError(f"duplicate JSON member: {k}")
        out[k]=v
    return out

def load_json(raw:bytes,label:str,limit:int):
    if len(raw)>limit: raise AdmissionError(f"{label} exceeds {limit} bytes")
    try: value=json.loads(raw.decode("utf-8"),object_pairs_hook=_pairs,parse_constant=lambda x:(_ for _ in ()).throw(AdmissionError(f"non-finite number: {x}")))
    except (UnicodeDecodeError,json.JSONDecodeError,ValueError) as e: raise AdmissionError(f"invalid {label}: {e}") from e
    if not isinstance(value,dict): raise AdmissionError(f"{label} must be an object")
    return value

def utc(value,label):
    if not isinstance(value,str) or not value.endswith("Z"): raise AdmissionError(f"invalid {label}")
    try: return datetime.fromisoformat(value[:-1]+"+00:00").astimezone(timezone.utc)
    except ValueError as e: raise AdmissionError(f"invalid {label}") from e

def exact(value:Mapping[str,Any],fields:set[str],label:str):
    if set(value)!=fields: raise AdmissionError(f"{label} fields differ: missing={sorted(fields-set(value))}, extra={sorted(set(value)-fields)}")

def false(value,key,label):
    if type(value.get(key)) is not bool or value[key]: raise AdmissionError(f"{label}.{key} must be false")

def identity(value,label):
    if not isinstance(value,str) or not IDENT.fullmatch(value): raise AdmissionError(f"invalid {label}")
    return value

def secure_dir(path:Path,uid:int):
    try: st=os.lstat(path)
    except OSError as e: raise AdmissionError(f"cannot stat directory {path}: {e}") from e
    if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_uid!=uid or st.st_mode&0o022: raise AdmissionError(f"insecure directory: {path}")

def snapshot(path:Path,root:Path,uid:int,limit:int):
    secure_dir(root,uid)
    try: rel=path.relative_to(root)
    except ValueError as e: raise AdmissionError(f"path escapes secure root: {path}") from e
    if not rel.parts or any(p in {"",".",".."} for p in rel.parts): raise AdmissionError(f"unsafe path: {path}")
    cur=root
    for part in rel.parts[:-1]: cur/=part; secure_dir(cur,uid)
    try: fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0))
    except OSError as e: raise AdmissionError(f"cannot open {path}: {e}") from e
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=uid or before.st_mode&0o133: raise AdmissionError(f"insecure data file: {path}")
        chunks=[]; total=0
        while True:
            part=os.read(fd,min(65536,limit+1-total))
            if not part: break
            chunks.append(part); total+=len(part)
            if total>limit: raise AdmissionError(f"file too large: {path}")
        after=os.fstat(fd); named=os.stat(path,follow_symlinks=False)
        key=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_mode,s.st_uid,s.st_nlink)
        if key(before)!=key(after) or key(after)!=key(named): raise AdmissionError(f"file changed while read: {path}")
        data=b"".join(chunks); os.lseek(fd,0,os.SEEK_SET)
        return Snap(fd,data,hashlib.sha256(data).hexdigest())
    except Exception: os.close(fd); raise

def read_policy(cfg:Config):
    snap=snapshot(cfg.policy,cfg.policy.parent,cfg.owner_uid,262144)
    try:
        p=load_json(snap.data,"policy",262144)
        exact(p,{"schema","version","status","repository","required_uid","grant_public_key_sha256","issuer_allowlist","allowed_subjects","max_request_future_seconds","max_grant_lifetime_seconds","max_clock_skew_seconds","evidence_kinds"},"policy")
        if (p["schema"],p["version"],p["status"],p["required_uid"])!=(POLICY_SCHEMA,"1","ACTIVE",cfg.owner_uid): raise AdmissionError("policy is not active for this owner")
        d=p["grant_public_key_sha256"]
        if not isinstance(d,str) or not HEX64.fullmatch(d) or set(d)=={"0"}: raise AdmissionError("grant key is unprovisioned")
        if not all(isinstance(p[k],list) and p[k] for k in ("issuer_allowlist","allowed_subjects")) or not isinstance(p["evidence_kinds"],dict): raise AdmissionError("policy allowlists are empty")
        for k in ("max_request_future_seconds","max_grant_lifetime_seconds","max_clock_skew_seconds"):
            if type(p[k]) is not int or not 0<p[k]<=2**31: raise AdmissionError(f"bad policy bound: {k}")
        for name,kind in p["evidence_kinds"].items():
            exact(kind,{"level","lane","authorization_class","required_roles","minimum_independent_approvals"},f"evidence policy {name}")
            if type(kind["minimum_independent_approvals"]) is not int or not 1<=kind["minimum_independent_approvals"]<=16: raise AdmissionError(f"bad approval minimum: {name}")
        return p,snap
    except Exception:
        snap.close(); raise

def check_request(r,p,now):
    exact(r,REQ_FIELDS,"request")
    if r["schema"]!=REQ_SCHEMA or r["status"]!="ROUTE_ONLY_PENDING_EXTERNAL_ADMISSION" or r["repository"]!=p["repository"]: raise AdmissionError("unsupported route request")
    kp=p["evidence_kinds"].get(r["evidence_kind"])
    if not isinstance(kp,dict): raise AdmissionError("unknown evidence kind")
    if (r["evidence_level"],r["external_lane"])!=(kp["level"],kp["lane"]): raise AdmissionError("request route mismatch")
    for k in ("source_commit","source_tree","protected_main_tip_observed","promotion_pr_head"):
        if not isinstance(r[k],str) or not HEX40.fullmatch(r[k]): raise AdmissionError(f"bad {k}")
    if type(r["promotion_pr_number"]) is not int or r["promotion_pr_number"]<=0: raise AdmissionError("bad promotion PR")
    subject={k:r[k] for k in ("source_commit","source_tree","promotion_pr_number","promotion_pr_head")}
    if subject not in p["allowed_subjects"]: raise AdmissionError("subject is not admitted")
    approvals=r["independent_approvals"]
    if not isinstance(approvals,list) or len(approvals)<kp["minimum_independent_approvals"]: raise AdmissionError("missing independent approval")
    checked=[identity(x,"approval") for x in approvals]
    folded=[x.casefold() for x in checked]
    if len(set(folded))!=len(folded) or any(x.endswith("[bot]") for x in folded): raise AdmissionError("bad approval set")
    if not isinstance(r["authorization_nonce"],str) or not NONCE.fullmatch(r["authorization_nonce"]): raise AdmissionError("bad nonce")
    ticket=r["authorization_ticket"]
    if not isinstance(ticket,str) or not TICKET.fullmatch(ticket): raise AdmissionError("bad ticket")
    if r["evidence_kind"]=="destructive_fault_matrix" and not ticket.startswith("DESTRUCTIVE-"): raise AdmissionError("missing destructive authorization")
    if r["evidence_kind"]=="signed_public_release" and not ticket.startswith("RELEASE-"): raise AdmissionError("missing release authorization")
    identity(r["requested_by"],"requester")
    if not 0<(utc(r["authorization_expires_at"],"route expiry")-now).total_seconds()<=p["max_request_future_seconds"]: raise AdmissionError("route expiry is invalid")
    for k in ("candidate_checkout_performed","candidate_code_executed","external_runner_allocated","capture_scheduled","synthetic","automatic_redispatch","promotion_authorized","public_release"): false(r,k,"request")
    return kp,checked,utc(r["authorization_expires_at"],"route expiry")

def verify_signature(grant:Snap,sig:Snap,key:Snap,p,cfg):
    if key.digest!=p["grant_public_key_sha256"]: raise AdmissionError("public key digest mismatch")
    if not hasattr(os,"memfd_create") or not Path("/proc/self/fd").is_dir(): raise AdmissionError("sealed Linux memfds are required")
    fds=[]
    try:
        for name,data in (("grant",grant.data),("signature",sig.data),("key",key.data)):
            fd=os.memfd_create(name,getattr(os,"MFD_CLOEXEC",1)|getattr(os,"MFD_ALLOW_SEALING",2)); fds.append(fd)
            off=0
            while off<len(data):
                n=os.write(fd,data[off:])
                if n<=0: raise AdmissionError("memfd write stalled")
                off+=n
            os.lseek(fd,0,os.SEEK_SET)
            seals=sum(getattr(fcntl,n,d) for n,d in (("F_SEAL_SEAL",1),("F_SEAL_SHRINK",2),("F_SEAL_GROW",4),("F_SEAL_WRITE",8)))
            fcntl.fcntl(fd,getattr(fcntl,"F_ADD_SEALS",1033),seals)
        g,s,k=fds
        done=subprocess.run([str(cfg.openssl),"dgst","-sha256","-verify",f"/proc/self/fd/{k}","-signature",f"/proc/self/fd/{s}",f"/proc/self/fd/{g}"],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd="/",env={"PATH":"/usr/bin:/bin","LANG":"C","LC_ALL":"C"},pass_fds=tuple(fds),timeout=10,check=False)
        if done.returncode: raise AdmissionError("detached grant signature is invalid")
    except (OSError,subprocess.SubprocessError) as e: raise AdmissionError(f"signature verification failed: {e}") from e
    finally:
        for fd in fds:
            try: os.close(fd)
            except OSError: pass

def check_grant(g,r,request_digest,p,kp,approvals,route_expiry,now):
    exact(g,GRANT_FIELDS,"grant")
    if (g["schema"],g["version"],g["status"])!=(GRANT_SCHEMA,"1","AUTHORIZED") or not isinstance(g["grant_id"],str) or not NONCE.fullmatch(g["grant_id"]): raise AdmissionError("unsupported grant")
    if g["request_sha256"]!=request_digest: raise AdmissionError("grant does not bind request bytes")
    for k in ("repository","source_commit","source_tree","promotion_pr_number","promotion_pr_head","evidence_kind","evidence_level","external_lane","authorization_nonce","authorization_ticket","authorization_expires_at"):
        if g[k]!=r[k]: raise AdmissionError(f"grant/request cross-splice at {k}")
    if g["requester"]!=r["requested_by"]: raise AdmissionError("requester mismatch")
    issuer=identity(g["issuer"],"issuer"); identity(g["key_id"],"key id")
    if issuer not in p["issuer_allowlist"]: raise AdmissionError("issuer not allowlisted")
    roles=g["roles"]
    if not isinstance(roles,dict) or set(roles)!=set(kp["required_roles"]): raise AdmissionError("role set mismatch")
    roles={k:identity(v,f"role {k}") for k,v in roles.items()}
    folded_roles=[v.casefold() for v in roles.values()]
    if roles.get("admission_issuer")!=issuer or roles.get("producer")!=r["requested_by"] or len(set(folded_roles))!=len(folded_roles): raise AdmissionError("external roles are not separated")
    excluded={r["requested_by"].casefold(),issuer.casefold(),*folded_roles}
    if any(value.casefold() in excluded for value in approvals): raise AdmissionError("independent approval overlaps an operational role")
    if g["authorization_class"]!=kp["authorization_class"]: raise AdmissionError("authorization class mismatch")
    for k in ("harness_sha256","target_attestation_sha256"):
        if not isinstance(g[k],str) or not HEX64.fullmatch(g[k]): raise AdmissionError(f"bad digest: {k}")
    issued=utc(g["issued_at"],"issued_at"); expires=utc(g["expires_at"],"expires_at")
    lifetime=expires-issued
    if issued>now+timedelta(seconds=p["max_clock_skew_seconds"]) or expires<=now or expires>route_expiry or lifetime<=timedelta(0) or lifetime>timedelta(seconds=p["max_grant_lifetime_seconds"]): raise AdmissionError("grant time bounds are invalid")
    for k in ("automatic_redispatch","promotion_authorized","public_release"): false(g,k,"grant")

def admitted_dir(root:Path,uid:int):
    secure_dir(root,uid); out=root/"admitted"
    try:
        os.mkdir(out,0o700); fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC); os.fsync(fd); os.close(fd)
    except FileExistsError: pass
    secure_dir(out,uid); return out

def write_once(directory:Path,nonce:str,value):
    raw=(json.dumps(value,sort_keys=True,separators=(",",":"))+"\n").encode(); path=directory/f"{nonce}.json"
    try: fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0),0o600)
    except FileExistsError as e: raise ReplayError(f"nonce already consumed: {nonce}") from e
    try:
        off=0
        while off<len(raw):
            n=os.write(fd,raw[off:])
            if n<=0: raise AdmissionError("admission write stalled")
            off+=n
        os.fsync(fd)
    finally: os.close(fd)
    dfd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC); os.fsync(dfd); os.close(dfd)

def admit(request_path:Path,grant_path:Path,signature_path:Path,*,config:Config,now=None):
    if sys.platform!="linux": raise AdmissionError("Linux is required")
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); snaps=[]
    try:
        p,ps=read_policy(config); snaps.append(ps)
        rs=snapshot(request_path,request_path.parent,config.owner_uid,65536); snaps.append(rs)
        gs=snapshot(grant_path,grant_path.parent,config.owner_uid,65536); snaps.append(gs)
        ss=snapshot(signature_path,signature_path.parent,config.owner_uid,16384); snaps.append(ss)
        ks=snapshot(config.public_key,config.public_key.parent,config.owner_uid,16384); snaps.append(ks)
        r=load_json(rs.data,"request",65536); g=load_json(gs.data,"grant",65536); kp,approvals,route_expiry=check_request(r,p,now); verify_signature(gs,ss,ks,p,config); check_grant(g,r,rs.digest,p,kp,approvals,route_expiry,now)
        admission={"schema":ADMISSION_SCHEMA,"version":"1","status":"ADMITTED_PENDING_FIXED_TARGET_EXECUTION","repository":r["repository"],"source_commit":r["source_commit"],"source_tree":r["source_tree"],"promotion_pr_number":r["promotion_pr_number"],"promotion_pr_head":r["promotion_pr_head"],"evidence_kind":r["evidence_kind"],"evidence_level":r["evidence_level"],"external_lane":r["external_lane"],"authorization_nonce":r["authorization_nonce"],"authorization_ticket":r["authorization_ticket"],"authorization_expires_at":r["authorization_expires_at"],"requester":r["requested_by"],"roles":g["roles"],"grant_id":g["grant_id"],"issuer":g["issuer"],"key_id":g["key_id"],"request_sha256":rs.digest,"grant_sha256":gs.digest,"grant_signature_sha256":ss.digest,"grant_public_key_sha256":ks.digest,"admission_policy_sha256":ps.digest,"authorization_class":g["authorization_class"],"grant_issued_at":g["issued_at"],"grant_expires_at":g["expires_at"],"harness_sha256":g["harness_sha256"],"target_attestation_sha256":g["target_attestation_sha256"],"admitted_at":now.isoformat().replace("+00:00","Z"),"target_contact_performed":False,"candidate_code_executed":False,"capture_scheduled":False,"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
        write_once(admitted_dir(config.state,config.owner_uid),r["authorization_nonce"],admission); return admission
    finally:
        for s in reversed(snaps): s.close()

def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--request",type=Path,required=True); ap.add_argument("--grant",type=Path,required=True); ap.add_argument("--signature",type=Path,required=True); a=ap.parse_args(argv)
    if os.geteuid()!=0: print("admission service must run as root",file=sys.stderr); return 2
    try: result=admit(a.request,a.grant,a.signature,config=Config(PROD_POLICY,PROD_KEY,PROD_STATE))
    except AdmissionError as e: print(f"FAIL: {e}",file=sys.stderr); return 1
    print(json.dumps(result,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
