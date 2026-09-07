#!/usr/bin/env python3
from pathlib import Path
import json

root=Path('.g1/trillionnium_os_external_evidence')
p=root/'admission_service.py'
s=p.read_text()

def replace_func(text,name,next_name,new):
    start=text.index(f'def {name}(')
    end=text.index(f'def {next_name}(',start)
    return text[:start]+new.rstrip()+"\n\n"+text[end:]

snapshot='''def open_secure_dir(path:Path,uid:int):
    absolute=Path(os.path.abspath(path)); flags=os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0); current=-1
    try:
        current=os.open("/",flags)
        for component in absolute.parts[1:]:
            if component in {"",".",".."}: raise AdmissionError(f"unsafe directory component: {component}")
            child=os.open(component,flags,dir_fd=current); os.close(current); current=child
        info=os.fstat(current)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=uid or info.st_mode&0o022: raise AdmissionError(f"insecure directory: {absolute}")
        return current
    except Exception:
        if current>=0: os.close(current)
        raise

def snapshot(path:Path,root:Path,uid:int,limit:int):
    root=Path(os.path.abspath(root)); path=Path(os.path.abspath(path))
    try: rel=path.relative_to(root)
    except ValueError as e: raise AdmissionError(f"path escapes secure root: {path}") from e
    if not rel.parts or any(part in {"",".",".."} for part in rel.parts): raise AdmissionError(f"unsafe path: {path}")
    directory_fd=open_secure_dir(root,uid); fd=-1
    try:
        for part in rel.parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0),dir_fd=directory_fd)
            info=os.fstat(child)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=uid or info.st_mode&0o022:
                os.close(child); raise AdmissionError(f"insecure directory component: {part}")
            os.close(directory_fd); directory_fd=child
        fd=os.open(rel.parts[-1],os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK|getattr(os,"O_NOFOLLOW",0),dir_fd=directory_fd)
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=uid or before.st_mode&0o133: raise AdmissionError(f"insecure data file: {path}")
        chunks=[]; total=0
        while True:
            part=os.read(fd,min(65536,limit+1-total))
            if not part: break
            chunks.append(part); total+=len(part)
            if total>limit: raise AdmissionError(f"file too large: {path}")
        after=os.fstat(fd); named=os.stat(rel.parts[-1],dir_fd=directory_fd,follow_symlinks=False)
        key=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_mode,value.st_uid,value.st_nlink)
        if key(before)!=key(after) or key(after)!=key(named): raise AdmissionError(f"file changed while read: {path}")
        data=b"".join(chunks); os.lseek(fd,0,os.SEEK_SET); result=Snap(fd,data,hashlib.sha256(data).hexdigest()); fd=-1; return result
    except OSError as e:
        raise AdmissionError(f"cannot open {path}: {e}") from e
    finally:
        if fd>=0: os.close(fd)
        os.close(directory_fd)
'''
s=replace_func(s,'snapshot','read_policy',snapshot)

read_policy='''def read_policy(cfg:Config):
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
        for name,kp in p["evidence_kinds"].items():
            identity(name,"evidence kind")
            if not isinstance(kp,dict): raise AdmissionError("evidence policy must be an object")
            exact(kp,{"level","lane","authorization_class","required_roles","minimum_independent_approvals","approval_excluded_roles"},"evidence policy")
            if not isinstance(kp["required_roles"],list) or not isinstance(kp["approval_excluded_roles"],list): raise AdmissionError("invalid approval role policy")
            roles=[identity(role,"required role") for role in kp["required_roles"]]
            excluded=[identity(role,"approval-excluded role") for role in kp["approval_excluded_roles"]]
            if not roles or len(set(roles))!=len(roles): raise AdmissionError("invalid required roles")
            if set(excluded)!=set(roles) or len(excluded)!=len(roles): raise AdmissionError("approval exclusions must cover every required role")
            if type(kp["minimum_independent_approvals"]) is not int or not 0<kp["minimum_independent_approvals"]<=16: raise AdmissionError("invalid approval minimum")
        return p,snap
    except Exception:
        snap.close()
        raise
'''
s=replace_func(s,'read_policy','check_request',read_policy)

check_request='''def check_request(r,p,now):
    exact(r,REQ_FIELDS,"request")
    if r["schema"]!=REQ_SCHEMA or r["status"]!="ROUTE_ONLY_PENDING_EXTERNAL_ADMISSION" or r["repository"]!=p["repository"]: raise AdmissionError("unsupported route request")
    kp=p["evidence_kinds"].get(r["evidence_kind"])
    if not isinstance(kp,dict): raise AdmissionError("unknown evidence kind")
    exact(kp,{"level","lane","authorization_class","required_roles","minimum_independent_approvals","approval_excluded_roles"},"evidence policy")
    if (r["evidence_level"],r["external_lane"])!=(kp["level"],kp["lane"]): raise AdmissionError("request route mismatch")
    for k in ("source_commit","source_tree","protected_main_tip_observed","promotion_pr_head"):
        if not isinstance(r[k],str) or not HEX40.fullmatch(r[k]): raise AdmissionError(f"bad {k}")
    if r["protected_main_tip_observed"]!=r["source_commit"]: raise AdmissionError("route does not bind protected main")
    if type(r["promotion_pr_number"]) is not int or r["promotion_pr_number"]<=0: raise AdmissionError("bad promotion PR")
    subject={k:r[k] for k in ("source_commit","source_tree","promotion_pr_number","promotion_pr_head")}
    if subject not in p["allowed_subjects"]: raise AdmissionError("subject is not admitted")
    approvals=r["independent_approvals"]
    if not isinstance(approvals,list) or not approvals: raise AdmissionError("missing independent approval")
    checked=[identity(x,"approval") for x in approvals]; folded=[x.casefold() for x in checked]
    if len(set(folded))!=len(folded) or any(x.endswith("[bot]") for x in folded) or len(checked)<kp["minimum_independent_approvals"]: raise AdmissionError("bad approval set")
    if not isinstance(r["authorization_nonce"],str) or not NONCE.fullmatch(r["authorization_nonce"]): raise AdmissionError("bad nonce")
    ticket=r["authorization_ticket"]
    if not isinstance(ticket,str) or not TICKET.fullmatch(ticket): raise AdmissionError("bad ticket")
    if r["evidence_kind"]=="destructive_fault_matrix" and not ticket.startswith("DESTRUCTIVE-"): raise AdmissionError("missing destructive authorization")
    if r["evidence_kind"]=="signed_public_release" and not ticket.startswith("RELEASE-"): raise AdmissionError("missing release authorization")
    identity(r["requested_by"],"requester")
    if not 0<(utc(r["authorization_expires_at"],"route expiry")-now).total_seconds()<=p["max_request_future_seconds"]: raise AdmissionError("route expiry is invalid")
    for k in ("candidate_checkout_performed","candidate_code_executed","external_runner_allocated","capture_scheduled","synthetic","automatic_redispatch","promotion_authorized","public_release"): false(r,k,"request")
    return kp
'''
s=replace_func(s,'check_request','verify_signature',check_request)

check_grant='''def check_grant(g,r,request_digest,p,kp,now):
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
    if roles.get("admission_issuer")!=issuer or roles.get("producer")!=r["requested_by"] or len({v.casefold() for v in roles.values()})!=len(roles): raise AdmissionError("external roles are not separated")
    approvals={identity(v,"approval").casefold() for v in r["independent_approvals"]}
    excluded={r["requested_by"].casefold(),issuer.casefold()}|{roles[name].casefold() for name in kp["approval_excluded_roles"]}
    if approvals&excluded: raise AdmissionError("independent approvals overlap an operational authority")
    if g["authorization_class"]!=kp["authorization_class"]: raise AdmissionError("authorization class mismatch")
    for k in ("harness_sha256","target_attestation_sha256"):
        if not isinstance(g[k],str) or not HEX64.fullmatch(g[k]): raise AdmissionError(f"bad digest: {k}")
    issued=utc(g["issued_at"],"issued_at"); expires=utc(g["expires_at"],"expires_at")
    if issued>now+timedelta(seconds=p["max_clock_skew_seconds"]) or expires<=issued or expires<=now or expires>utc(r["authorization_expires_at"],"route expiry") or expires-issued>timedelta(seconds=p["max_grant_lifetime_seconds"]): raise AdmissionError("grant time bounds are invalid")
    for k in ("automatic_redispatch","promotion_authorized","public_release"): false(g,k,"grant")
'''
s=replace_func(s,'check_grant','admitted_dir',check_grant)

start=s.index('def admit('); end=s.index('def main(',start)
old=s[start:end]
body=old[old.index('        admission='):]
body=body[:body.rfind('    finally:')]
admit='''def admit(request_path:Path,grant_path:Path,signature_path:Path,*,config:Config,now=None):
    if sys.platform!="linux": raise AdmissionError("Linux is required")
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); snaps=[]
    try:
        p,ps=read_policy(config); snaps.append(ps)
        rs=snapshot(request_path,request_path.parent,config.owner_uid,65536); snaps.append(rs)
        gs=snapshot(grant_path,grant_path.parent,config.owner_uid,65536); snaps.append(gs)
        ss=snapshot(signature_path,signature_path.parent,config.owner_uid,16384); snaps.append(ss)
        ks=snapshot(config.public_key,config.public_key.parent,config.owner_uid,16384); snaps.append(ks)
        r=load_json(rs.data,"request",65536); g=load_json(gs.data,"grant",65536); kp=check_request(r,p,now); verify_signature(gs,ss,ks,p,config); check_grant(g,r,rs.digest,p,kp,now)
'''+body+'''    finally:
        for snap in reversed(snaps): snap.close()

'''
s=s[:start]+admit+s[end:]
p.write_text(s)

policy_path=root/'policy.template.json'
data=json.loads(policy_path.read_text())
for name,kp in data['evidence_kinds'].items():
    kp['minimum_independent_approvals']=2 if name in {'destructive_fault_matrix','signed_public_release'} else 1
    kp['approval_excluded_roles']=list(kp['required_roles'])
policy_path.write_text(json.dumps(data,indent=2)+'\n')

test=root/'tests/test_admission_service.py'
t=test.read_text()
t=t.replace('import subprocess\nimport tempfile\n','import subprocess\nimport sys\nimport tempfile\n')
t=t.replace('''                    "required_roles": ["producer", "target_operator", "admission_issuer"],
''','''                    "required_roles": ["producer", "target_operator", "admission_issuer"],
                    "minimum_independent_approvals": 1,
                    "approval_excluded_roles": ["producer", "target_operator", "admission_issuer"],
''')
t=t.replace('''                    "required_roles": ["producer", "fault_operator", "destructive_authorizer", "admission_issuer"],
''','''                    "required_roles": ["producer", "fault_operator", "destructive_authorizer", "admission_issuer"],
                    "minimum_independent_approvals": 2,
                    "approval_excluded_roles": ["producer", "fault_operator", "destructive_authorizer", "admission_issuer"],
''')
insert='''
    def test_review_fifo_input_is_bounded(self):
        self.prepare(); self.request_path.unlink(); os.mkfifo(self.request_path,0o600)
        module=Path(__file__).resolve().parents[1]
        code="from pathlib import Path; import os,sys; from admission_service import snapshot,AdmissionError; p=Path(sys.argv[1]);\ntry: snapshot(p,p.parent,int(sys.argv[2]),65536)\nexcept AdmissionError: raise SystemExit(0)\nraise SystemExit(3)"
        done=subprocess.run([sys.executable,"-c",code,str(self.request_path),str(os.getuid())],cwd=module,env={**os.environ,"PYTHONPATH":str(module)},timeout=2,check=False)
        self.assertEqual(done.returncode,0)

    def test_review_grant_interval_and_approval_independence(self):
        for issued,expires in ((NOW+timedelta(minutes=4),NOW+timedelta(minutes=1)),(NOW+timedelta(minutes=1),NOW+timedelta(minutes=1))):
            self.tearDown(); self.setUp(); self.prepare(mutate_grant=lambda g,i=issued,e=expires:g.update({"issued_at":self.stamp(i),"expires_at":self.stamp(e)}))
            with self.assertRaisesRegex(AdmissionError,"time bounds"): admit(self.request_path,self.grant_path,self.signature_path,config=self.config,now=NOW)
        for approval in ("capture-producer","external-admission","target-operator"):
            self.tearDown(); self.setUp(); request=self.request(); request["independent_approvals"]=[approval]; self.prepare(request=request)
            with self.assertRaisesRegex(AdmissionError,"operational authority"): admit(self.request_path,self.grant_path,self.signature_path,config=self.config,now=NOW)
        self.tearDown(); self.setUp(); request=self.request(); request["independent_approvals"]=["Reviewer","reviewer"]; self.prepare(request=request)
        with self.assertRaisesRegex(AdmissionError,"approval set"): admit(self.request_path,self.grant_path,self.signature_path,config=self.config,now=NOW)

    def test_review_high_authority_approval_minimum(self):
        request=self.request("destructive_fault_matrix"); self.prepare(request=request)
        with self.assertRaisesRegex(AdmissionError,"approval set"): admit(self.request_path,self.grant_path,self.signature_path,config=self.config,now=NOW)
        self.tearDown(); self.setUp(); request=self.request("destructive_fault_matrix"); request["independent_approvals"]=["reviewer-one","reviewer-two"]; self.prepare(request=request)
        self.assertEqual(admit(self.request_path,self.grant_path,self.signature_path,config=self.config,now=NOW)["evidence_level"],"L5")

    def test_review_partial_acquisition_closes_descriptors(self):
        if not Path("/proc/self/fd").is_dir(): self.skipTest("procfs required")
        for scenario in ("grant","signature","public_key","policy"):
            self.tearDown(); self.setUp(); self.prepare(); target={"grant":self.grant_path,"signature":self.signature_path,"public_key":self.pub}.get(scenario)
            if target is None: self.write(self.policy_path,b"{")
            else: target.unlink()
            baseline=len(os.listdir("/proc/self/fd"))
            for _ in range(8):
                with self.assertRaises((AdmissionError,OSError)): admit(self.request_path,self.grant_path,self.signature_path,config=self.config,now=NOW)
            self.assertEqual(len(os.listdir("/proc/self/fd")),baseline)
'''
marker='\n\nif __name__ == "__main__":\n'
t=t.replace(marker,insert+marker)
test.write_text(t)

readme=root/'README.md'
r=readme.read_text().replace('checks role separation and bounded UTC authorization, verifies RSA-SHA256 over\nthe retained grant bytes through sealed Linux memfds, and atomically writes one\nnonce-consumption record before any target contact.','checks policy-defined approval cardinality and separation from every operational\nauthority, rejects non-positive grant intervals and non-regular inputs without\nblocking, verifies RSA-SHA256 over retained grant bytes through sealed Linux\nmemfds, and atomically writes one nonce-consumption record before target contact.')
readme.write_text(r)
