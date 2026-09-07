#!/usr/bin/env python3
from pathlib import Path

root=Path('.g1/trillionnium_os_external_evidence')
p=root/'trusted_executor.py'
s=p.read_text()
s=s.replace('import argparse, hashlib, json, os, re, selectors, signal, stat, subprocess, sys, time\n','import argparse, fcntl, hashlib, json, os, re, selectors, signal, stat, subprocess, sys, time\n')
s=s.replace('ATTEST_FIELDS={"schema","version","status","repository","source_commit","source_tree","evidence_kind","evidence_level","external_lane","authorization_nonce","target_id","environment_class","custodian","harness_sha256","issued_at","expires_at","automatic_redispatch","promotion_authorized","public_release"}\n','ATTEST_FIELDS={"schema","version","status","repository","source_commit","source_tree","evidence_kind","evidence_level","external_lane","authorization_nonce","target_id","environment_class","custodian","harness_sha256","issued_at","expires_at","automatic_redispatch","promotion_authorized","public_release"}\nBUNDLE_FIELDS={"schema","repository","source_commit","source_tree","evidence_kind","evidence_level","authorization_nonce","target_id","synthetic","automatic_redispatch","promotion_authorized","public_release"}\n')

def replace_func(text,name,next_name,new):
    start=text.index(f'def {name}(')
    end=text.index(f'def {next_name}(',start)
    return text[:start]+new.rstrip()+"\n\n"+text[end:]

snapshot='''def open_secure_dir(path:Path,uid:int):
    absolute=Path(os.path.abspath(path)); flags=os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0); current=-1
    try:
        current=os.open("/",flags)
        for component in absolute.parts[1:]:
            if component in {"",".",".."}: raise ExecutionError(f"unsafe directory component: {component}")
            child=os.open(component,flags,dir_fd=current); os.close(current); current=child
        info=os.fstat(current)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=uid or info.st_mode&0o022: raise ExecutionError(f"insecure directory: {absolute}")
        return current
    except Exception:
        if current>=0: os.close(current)
        raise

def snapshot(path:Path,root:Path,uid:int,limit:int,executable=False,deadline=None,timeout_reason="execution_timeout"):
    root=Path(os.path.abspath(root)); path=Path(os.path.abspath(path))
    try: rel=path.relative_to(root)
    except ValueError as e: raise ExecutionError(f"path escapes secure root: {path}") from e
    if not rel.parts or any(part in {"",".",".."} for part in rel.parts): raise ExecutionError(f"unsafe path: {path}")
    directory_fd=open_secure_dir(root,uid); fd=-1
    try:
        for part in rel.parts[:-1]:
            child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|getattr(os,"O_NOFOLLOW",0),dir_fd=directory_fd)
            info=os.fstat(child)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=uid or info.st_mode&0o022:
                os.close(child); raise ExecutionError(f"insecure directory component: {part}")
            os.close(directory_fd); directory_fd=child
        fd=os.open(rel.parts[-1],os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK|getattr(os,"O_NOFOLLOW",0),dir_fd=directory_fd)
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or before.st_uid!=uid or before.st_mode&0o022: raise ExecutionError(f"insecure file: {path}")
        if executable and not before.st_mode&stat.S_IXUSR: raise ExecutionError(f"harness is not executable: {path}")
        if not executable and before.st_mode&0o111: raise ExecutionError(f"data file is executable: {path}")
        parts=[]; total=0
        while True:
            if deadline is not None and time.monotonic()>=deadline: raise ExecutionError(timeout_reason)
            chunk=os.read(fd,min(65536,limit+1-total))
            if not chunk: break
            parts.append(chunk); total+=len(chunk)
            if total>limit: raise ExecutionError(f"file too large: {path}")
        if deadline is not None and time.monotonic()>=deadline: raise ExecutionError(timeout_reason)
        after=os.fstat(fd); named=os.stat(rel.parts[-1],dir_fd=directory_fd,follow_symlinks=False); key=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_mode,value.st_uid,value.st_nlink)
        if key(before)!=key(after) or key(after)!=key(named): raise ExecutionError(f"file changed while read: {path}")
        data=b"".join(parts); os.lseek(fd,0,os.SEEK_SET); result=Snap(fd,data,hashlib.sha256(data).hexdigest()); fd=-1; return result
    except OSError as e:
        raise ExecutionError(f"cannot open {path}: {e}") from e
    finally:
        if fd>=0: os.close(fd)
        os.close(directory_fd)
'''
s=replace_func(s,'snapshot','read_policy',snapshot)

read_policy='''def read_policy(cfg):
    snap=snapshot(cfg.policy,cfg.policy.parent,cfg.owner_uid,262144)
    try:
        p=load_json(snap.data,"execution policy",262144)
        fields={"schema","version","status","repository","required_uid","admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist","issuer_allowlist","allowed_subjects","max_bundle_files","max_bundle_bytes","evidence_kinds"}; exact(p,fields,"execution policy")
        if (p["schema"],p["version"],p["status"],p["required_uid"])!=(POLICY_SCHEMA,"1","ACTIVE",cfg.owner_uid): raise ExecutionError("execution policy is not active")
        for k in ("admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist","issuer_allowlist","allowed_subjects"):
            if not isinstance(p[k],list) or not p[k]: raise ExecutionError(f"empty policy allowlist: {k}")
        for k in ("admission_policy_sha256_allowlist","grant_public_key_sha256_allowlist"):
            if any(not isinstance(v,str) or not HEX64.fullmatch(v) for v in p[k]): raise ExecutionError(f"bad digest allowlist: {k}")
        for k in ("max_bundle_files","max_bundle_bytes"):
            if type(p[k]) is not int or not 0<p[k]<=2**31: raise ExecutionError(f"bad policy bound: {k}")
        if not isinstance(p["evidence_kinds"],dict): raise ExecutionError("missing evidence policy")
        return p,snap
    except Exception:
        snap.close()
        raise
'''
s=replace_func(s,'read_policy','check_admission',read_policy)

check_admission='''def check_admission(a,p,now,requested_nonce):
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
    if a["authorization_nonce"]!=requested_nonce: raise ExecutionError("admission filename nonce does not match its internal nonce")
    if not isinstance(a["roles"],dict) or set(a["roles"])!=set(kind["required_roles"]): raise ExecutionError("role set mismatch")
    identity(a["requester"],"requester"); identity(a["issuer"],"issuer"); identity(a["key_id"],"key id")
    if not isinstance(a["grant_id"],str) or not NONCE.fullmatch(a["grant_id"]): raise ExecutionError("bad grant id")
    roles={role:identity(value,f"role {role}") for role,value in a["roles"].items()}
    if roles.get("producer")!=a["requester"] or roles.get("admission_issuer")!=a["issuer"] or len({v.casefold() for v in roles.values()})!=len(roles): raise ExecutionError("admission roles are not separated")
    for k in ("request_sha256","grant_sha256","grant_signature_sha256","grant_public_key_sha256","admission_policy_sha256","harness_sha256","target_attestation_sha256"):
        if not isinstance(a[k],str) or not HEX64.fullmatch(a[k]): raise ExecutionError(f"bad digest: {k}")
    admitted=utc(a["admitted_at"],"admitted_at"); issued=utc(a["grant_issued_at"],"grant issued_at"); grant_expiry=utc(a["grant_expires_at"],"grant expiry"); route_expiry=utc(a["authorization_expires_at"],"route expiry")
    if admitted>now or issued>now or not issued<grant_expiry<=route_expiry or grant_expiry<=now or route_expiry<=now: raise ExecutionError("admission time bounds are invalid")
    for k in ("target_contact_performed","candidate_code_executed","capture_scheduled","automatic_redispatch","promotion_authorized","public_release"): false(a,k,"admission")
    return kind,min(grant_expiry,route_expiry)
'''
s=replace_func(s,'check_admission','check_attestation',check_admission)

check_attestation='''def check_attestation(t,a,kind,harness_digest,now):
    exact(t,ATTEST_FIELDS,"target attestation")
    if (t["schema"],t["version"],t["status"])!=(ATTEST_SCHEMA,"1","READY"): raise ExecutionError("unsupported target attestation")
    for k in ("repository","source_commit","source_tree","evidence_kind","evidence_level","external_lane","authorization_nonce"):
        if t[k]!=a[k]: raise ExecutionError(f"attestation cross-splice at {k}")
    if t["harness_sha256"]!=harness_digest or a["harness_sha256"]!=harness_digest: raise ExecutionError("harness digest mismatch")
    if t["environment_class"]!=kind["environment_class"] or t["custodian"]!=a["roles"][kind["custodian_role"]]: raise ExecutionError("target environment or custodian mismatch")
    target=identity(t["target_id"],"target id")
    issued=utc(t["issued_at"],"attestation issued_at"); expires=utc(t["expires_at"],"attestation expiry"); grant_expiry=utc(a["grant_expires_at"],"grant expiry")
    if issued>now or not issued<expires<=grant_expiry or expires<=now: raise ExecutionError("target attestation time bounds are invalid")
    for k in ("automatic_redispatch","promotion_authorized","public_release"): false(t,k,"target attestation")
    return target,expires
'''
s=replace_func(s,'check_attestation','fsync_dir',check_attestation)

marker='def run_harness(harness,cwd,env,kind):\n'
helper='''def sealed_memfd(data):
    if not hasattr(os,"memfd_create") or not Path("/proc/self/fd").is_dir(): raise ExecutionError("sealed executable memfd and procfs are required")
    fd=-1
    try:
        fd=os.memfd_create("owner-open-r5-harness",getattr(os,"MFD_CLOEXEC",1)|getattr(os,"MFD_ALLOW_SEALING",2)); os.fchmod(fd,0o500)
        off=0
        while off<len(data):
            written=os.write(fd,data[off:])
            if written<=0: raise ExecutionError("memfd write stalled")
            off+=written
        os.lseek(fd,0,os.SEEK_SET)
        seals=sum(getattr(fcntl,name,fallback) for name,fallback in (("F_SEAL_SEAL",1),("F_SEAL_SHRINK",2),("F_SEAL_GROW",4),("F_SEAL_WRITE",8)))
        fcntl.fcntl(fd,getattr(fcntl,"F_ADD_SEALS",1033),seals)
        if fcntl.fcntl(fd,getattr(fcntl,"F_GET_SEALS",1034))&seals!=seals: raise ExecutionError("memfd sealing failed")
        return fd
    except Exception:
        if fd>=0: os.close(fd)
        raise

'''
if marker not in s: raise SystemExit('run_harness marker missing')
s=s.replace(marker,helper+marker,1)

run_harness='''def run_harness(harness,cwd,env,kind,deadline,timeout_reason):
    harness_fd=sealed_memfd(harness.data); proc=None; data={"stdout":bytearray(),"stderr":bytearray()}; error=None; reaped=True; clean=True; contacted=False
    try:
        if time.monotonic()>=deadline: return {"exit_code":-1,"stdout":b"","stderr":b"","failure":timeout_reason,"leader_reaped":True,"cleanup_confirmed":True,"target_contact_performed":False}
        cmd=f"/proc/self/fd/{harness_fd}"; proc=subprocess.Popen([cmd],executable=cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=cwd,env=env,close_fds=True,pass_fds=(harness_fd,),start_new_session=True); contacted=True
        if proc.stdout is None or proc.stderr is None: raise ExecutionError("subprocess pipes were not created")
        for pipe in (proc.stdout,proc.stderr): os.set_blocking(pipe.fileno(),False)
        sel=selectors.DefaultSelector(); sel.register(proc.stdout,selectors.EVENT_READ,("stdout",kind["stdout_max_bytes"])); sel.register(proc.stderr,selectors.EVENT_READ,("stderr",kind["stderr_max_bytes"])); drain=None
        try:
            while sel.get_map():
                observed=time.monotonic()
                if observed>=deadline: error=timeout_reason; break
                if exited(proc.pid):
                    drain=drain or min(deadline,observed+1)
                    if observed>=drain: error="pipe_drain_timeout"; break
                for key,_ in sel.select(min(.1,max(0,deadline-observed))):
                    label,limit=key.data
                    try: chunk=os.read(key.fileobj.fileno(),min(65536,limit+1-len(data[label])))
                    except BlockingIOError: continue
                    if not chunk: sel.unregister(key.fileobj); continue
                    data[label]+=chunk
                    if len(data[label])>limit: error=f"{label}_limit_exceeded"; break
                if error: break
            if not error and not exited(proc.pid):
                while time.monotonic()<deadline and not exited(proc.pid): time.sleep(.02)
                if not exited(proc.pid): error=timeout_reason
        finally:
            reaped,clean=retire(proc); sel.close(); proc.stdout.close(); proc.stderr.close()
        if not clean and not error: error="process_group_cleanup_unconfirmed"
        return {"exit_code":proc.returncode if proc.returncode is not None else -9,"stdout":bytes(data["stdout"]),"stderr":bytes(data["stderr"]),"failure":error,"leader_reaped":reaped,"cleanup_confirmed":clean,"target_contact_performed":contacted}
    except OSError as exc:
        if proc is not None: reaped,clean=retire(proc)
        return {"exit_code":-1,"stdout":bytes(data["stdout"]),"stderr":bytes(data["stderr"]),"failure":f"harness_launch_failed:{exc.errno}","leader_reaped":reaped,"cleanup_confirmed":clean,"target_contact_performed":contacted}
    finally:
        os.close(harness_fd)
'''
s=replace_func(s,'run_harness','inspect_bundle',run_harness)

inspect_bundle='''def inspect_bundle(bundle,uid,p,a,target,deadline,timeout_reason):
    if time.monotonic()>=deadline: raise ExecutionError(timeout_reason)
    secure_dir(bundle,uid); entries=[]; total=0; manifest_raw=None
    for root_path,dirs,files in os.walk(bundle,followlinks=False):
        if time.monotonic()>=deadline: raise ExecutionError(timeout_reason)
        root_path=Path(root_path)
        for name in dirs: secure_dir(root_path/name,uid)
        for name in files:
            if time.monotonic()>=deadline: raise ExecutionError(timeout_reason)
            path=root_path/name; snap=snapshot(path,bundle,uid,p["max_bundle_bytes"],deadline=deadline,timeout_reason=timeout_reason)
            try:
                rel=path.relative_to(bundle).as_posix(); entries.append({"path":rel,"bytes":len(snap.data),"sha256":snap.digest}); total+=len(snap.data)
                if rel=="manifest.json": manifest_raw=snap.data
            finally: snap.close()
            if len(entries)>p["max_bundle_files"] or total>p["max_bundle_bytes"]: raise ExecutionError("bundle exceeds policy")
    if time.monotonic()>=deadline: raise ExecutionError(timeout_reason)
    manifest=next((item for item in entries if item["path"]=="manifest.json"),None)
    if not manifest or manifest_raw is None: raise ExecutionError("bundle manifest is missing")
    m=load_json(manifest_raw,"bundle manifest",1048576); exact(m,BUNDLE_FIELDS,"bundle manifest")
    required={"schema":BUNDLE_SCHEMA,"repository":a["repository"],"source_commit":a["source_commit"],"source_tree":a["source_tree"],"evidence_kind":a["evidence_kind"],"evidence_level":a["evidence_level"],"authorization_nonce":a["authorization_nonce"],"target_id":target}
    for k,v in required.items():
        if m[k]!=v or type(m[k]) is not type(v): raise ExecutionError(f"bundle manifest mismatch at {k}")
    for k in ("synthetic","automatic_redispatch","promotion_authorized","public_release"): false(m,k,"bundle manifest")
    entries.sort(key=lambda item:item["path"]); tree=hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if time.monotonic()>=deadline: raise ExecutionError(timeout_reason)
    return {"manifest_sha256":manifest["sha256"],"bundle_tree_sha256":tree,"bundle_file_count":len(entries),"bundle_total_bytes":total}
'''
s=replace_func(s,'inspect_bundle','execute',inspect_bundle)

execute='''def execute(nonce,*,config:Config,now=None):
    if sys.platform!="linux" or not NONCE.fullmatch(nonce): raise ExecutionError("Linux and a valid nonce are required")
    observed_now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc); snaps=[]; started=False; a=None
    try:
        p,ps=read_policy(config); snaps.append(ps)
        ads=snapshot(config.admissions/f"{nonce}.json",config.admissions,config.owner_uid,131072); snaps.append(ads)
        a=load_json(ads.data,"admission",131072); kind,admission_expiry=check_admission(a,p,observed_now,nonce)
        hs=snapshot(config.harnesses/a["evidence_kind"],config.harnesses,config.owner_uid,16*1024*1024,True); snaps.append(hs)
        ts=snapshot(config.attestations/f"{a['evidence_kind']}.json",config.attestations,config.owner_uid,65536); snaps.append(ts)
        if hs.digest!=a["harness_sha256"] or ts.digest!=a["target_attestation_sha256"]: raise ExecutionError("fixed target bytes do not match admission")
        target,attestation_expiry=check_attestation(load_json(ts.data,"target attestation",65536),a,kind,hs.digest,observed_now)
        remaining=(min(admission_expiry,attestation_expiry)-observed_now).total_seconds()
        if remaining<=0: raise ExecutionError("authority expired before execution")
        timeout_reason="authority_expired" if remaining<=kind["timeout_seconds"] else "execution_timeout"; deadline=time.monotonic()+min(remaining,kind["timeout_seconds"])
        state=ensure_state(config.state,config.owner_uid)
        start={"schema":"org.trillionnium.external-evidence-execution-start.v1","status":"STARTED_NO_AUTOMATIC_RETRY","authorization_nonce":nonce,"admission_sha256":ads.digest,"harness_sha256":hs.digest,"target_attestation_sha256":ts.digest,"started_at":observed_now.isoformat().replace("+00:00","Z"),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}; write_once(state["started"],f"{nonce}.json",start); started=True
        work=state["work"]/nonce; os.mkdir(work,0o700); fsync_dir(state["work"]); cwd=work/"cwd"; bundle=work/"bundle"; os.mkdir(cwd,0o700); os.mkdir(bundle,0o700); fsync_dir(work); admission_copy=write_raw_once(work,"admission.json",ads.data); attestation_copy=write_raw_once(work,"target-attestation.json",ts.data)
        env={"PATH":"/usr/sbin:/usr/bin:/sbin:/bin","LANG":"C.UTF-8","LC_ALL":"C.UTF-8","HOME":"/nonexistent","TMPDIR":str(cwd),"OWNER_OPEN_R5_ADMISSION":str(admission_copy),"OWNER_OPEN_R5_TARGET_ATTESTATION":str(attestation_copy),"OWNER_OPEN_R5_OUTPUT_DIR":str(bundle),"OWNER_OPEN_R5_EVIDENCE_KIND":a["evidence_kind"]}
        run=run_harness(hs,cwd,env,kind,deadline,timeout_reason); failure=run["failure"] or (f"harness_exit_{run['exit_code']}" if run["exit_code"] else None); info=None
        if not failure:
            try: info=inspect_bundle(bundle,config.owner_uid,p,a,target,deadline,timeout_reason)
            except ExecutionError as exc: failure=f"bundle_invalid:{exc}"
        if not failure and time.monotonic()>=deadline: failure=timeout_reason; info=None
        result={"schema":RESULT_SCHEMA,"version":"1","status":"CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW" if not failure else "CAPTURE_FAILED_NO_RETRY","repository":a["repository"],"source_commit":a["source_commit"],"source_tree":a["source_tree"],"evidence_kind":a["evidence_kind"],"evidence_level":a["evidence_level"],"authorization_nonce":nonce,"target_id":target,"admission_sha256":ads.digest,"harness_sha256":hs.digest,"target_attestation_sha256":ts.digest,"exit_code":run["exit_code"],"stdout_sha256":hashlib.sha256(run["stdout"]).hexdigest(),"stdout_bytes":len(run["stdout"]),"stderr_sha256":hashlib.sha256(run["stderr"]).hexdigest(),"stderr_bytes":len(run["stderr"]),"failure":failure,"leader_reaped":run["leader_reaped"],"cleanup_scope":"original_process_group_only","cleanup_confirmed":run["cleanup_confirmed"],"escaped_descendants_absence_proven":False,"target_contact_performed":run["target_contact_performed"],"candidate_code_executed":False,"capture_performed":run["target_contact_performed"],"evidence_reviewed":False,"gap_transition_authorized":False,"finished_at":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
        if info: result.update(info)
        write_once(state["results"],f"{nonce}.json",result)
        if failure: raise ExecutionError(failure)
        return result
    except ExecutionError: raise
    except Exception as exc:
        if started: raise ExecutionError(f"post-start failure; execution remains non-retryable: {exc}") from exc
        raise ExecutionError(f"pre-start failure: {exc}") from exc
    finally:
        for snap in reversed(snaps): snap.close()
'''
s=replace_func(s,'execute','main',execute)
p.write_text(s)

test=root/'tests/test_trusted_executor.py'
t=test.read_text()
t=t.replace('import hashlib, json, os\n','import hashlib, json, os, subprocess, sys, time\n')
t=t.replace('import tempfile, unittest\n','import tempfile, unittest\nfrom unittest import mock\nimport trusted_executor as executor\n')
helper='''
    def rewrite_harness(self, transform):
        kind="installed_root_linux_process_matrix"; harness=self.harnesses/kind; self.write(harness,transform(harness.read_bytes()),0o700); digest=hashlib.sha256(harness.read_bytes()).hexdigest()
        attestation_path=self.attestations/f"{kind}.json"; attestation=json.loads(attestation_path.read_text()); attestation["harness_sha256"]=digest; raw=(json.dumps(attestation,sort_keys=True)+"\\n").encode(); self.write(attestation_path,raw)
        admission_path=self.admissions/f"{NONCE}.json"; admission=json.loads(admission_path.read_text()); admission["harness_sha256"]=digest; admission["target_attestation_sha256"]=hashlib.sha256(raw).hexdigest(); self.write(admission_path,(json.dumps(admission,sort_keys=True,separators=(",",":"))+"\\n").encode())

    def set_short_expiry(self, seconds):
        kind="installed_root_linux_process_matrix"; attestation_path=self.attestations/f"{kind}.json"; attestation=json.loads(attestation_path.read_text()); attestation["expires_at"]=stamp(NOW+timedelta(seconds=seconds)); raw=(json.dumps(attestation,sort_keys=True)+"\\n").encode(); self.write(attestation_path,raw)
        admission_path=self.admissions/f"{NONCE}.json"; admission=json.loads(admission_path.read_text()); admission["grant_expires_at"]=stamp(NOW+timedelta(seconds=seconds+.05)); admission["authorization_expires_at"]=stamp(NOW+timedelta(seconds=seconds+.10)); admission["target_attestation_sha256"]=hashlib.sha256(raw).hexdigest(); self.write(admission_path,(json.dumps(admission,sort_keys=True,separators=(",",":"))+"\\n").encode())
'''
t=t.replace('\n    def test_success_is_one_shot_and_non_promoting',helper+'\n    def test_success_is_one_shot_and_non_promoting')
insert='''
    def test_review_same_inode_and_rename_mutation_execute_verified_bytes(self):
        for mode in ("rewrite","rename"):
            self.tearDown(); self.setUp(); self.prepare(); harness=self.harnesses/"installed_root_linux_process_matrix"; malicious=harness.read_bytes().replace(b"exit 0\\n",b"touch \\\"$OWNER_OPEN_R5_OUTPUT_DIR/MUTATED\\\"\\nexit 0\\n"); real=executor.sealed_memfd; changed=False
            def change_then_seal(data):
                nonlocal changed
                if not changed:
                    if mode=="rewrite": self.write(harness,malicious,0o700)
                    else:
                        replacement=self.harnesses/"replacement"; self.write(replacement,malicious,0o700); os.replace(replacement,harness)
                    changed=True
                return real(data)
            with mock.patch.object(executor,"sealed_memfd",side_effect=change_then_seal): execute(NONCE,config=self.config,now=NOW)
            self.assertFalse((self.state/"work"/NONCE/"bundle"/"MUTATED").exists())

    def test_review_bundle_fifo_is_bounded_and_manifest_is_closed(self):
        self.prepare(); self.rewrite_harness(lambda raw:raw.replace(b"exit 0\\n",b"mkfifo \\\"$OWNER_OPEN_R5_OUTPUT_DIR/blocked.fifo\\\"\\nexit 0\\n")); module=Path(__file__).resolve().parents[1]
        code="from datetime import datetime; from pathlib import Path; import sys; from trusted_executor import Config,ExecutionError,execute; cfg=Config(*(Path(x) for x in sys.argv[1:6]),owner_uid=int(sys.argv[6]));\ntry: execute(sys.argv[7],config=cfg,now=datetime.fromisoformat(sys.argv[8]))\nexcept ExecutionError as e: raise SystemExit(0 if 'bundle_invalid' in str(e) else 3)\nraise SystemExit(4)"
        done=subprocess.run([sys.executable,"-c",code,str(self.admissions),str(self.harnesses),str(self.attestations),str(self.policy_path),str(self.state),str(os.getuid()),NONCE,NOW.isoformat()],cwd=module,env={**os.environ,"PYTHONPATH":str(module)},timeout=2,check=False); self.assertEqual(done.returncode,0)
        self.tearDown(); self.setUp(); self.prepare(); self.rewrite_harness(lambda raw:raw.replace(b'"public_release": false}',b'"public_release": false, "evidence_reviewed": true}'))
        with self.assertRaisesRegex(ExecutionError,"bundle_invalid"): execute(NONCE,config=self.config,now=NOW)

    def test_review_nonce_and_expiry_are_enforced_through_completion(self):
        self.prepare(); alternate="e"*32; os.replace(self.admissions/f"{NONCE}.json",self.admissions/f"{alternate}.json")
        with self.assertRaisesRegex(ExecutionError,"filename nonce"): execute(alternate,config=self.config,now=NOW)
        self.assertFalse((self.state/"started").exists())
        self.tearDown(); self.setUp(); self.prepare(); self.rewrite_harness(lambda raw:raw.replace(b"exit 0\\n",b"sleep 1\\nexit 0\\n")); self.set_short_expiry(.20); begun=time.monotonic()
        with self.assertRaisesRegex(ExecutionError,"authority_expired"): execute(NONCE,config=self.config,now=NOW)
        self.assertLess(time.monotonic()-begun,2); result=json.loads((self.state/"results"/f"{NONCE}.json").read_text()); self.assertEqual(result["status"],"CAPTURE_FAILED_NO_RETRY")

    def test_review_partial_acquisition_closes_descriptors(self):
        if not Path("/proc/self/fd").is_dir(): self.skipTest("procfs required")
        for scenario in ("attestation","policy"):
            self.tearDown(); self.setUp(); self.prepare()
            if scenario=="attestation": (self.attestations/"installed_root_linux_process_matrix.json").unlink()
            else: self.write(self.policy_path,b"{")
            baseline=len(os.listdir("/proc/self/fd"))
            for _ in range(8):
                with self.assertRaises((ExecutionError,OSError)): execute(NONCE,config=self.config,now=NOW)
            self.assertEqual(len(os.listdir("/proc/self/fd")),baseline)
'''
marker='\nif __name__=="__main__": unittest.main()\n'
t=t.replace(marker,insert+marker)
test.write_text(t)

executor_doc=root/'EXECUTOR.md'
d=executor_doc.read_text().replace('`STARTED_NO_AUTOMATIC_RETRY` marker before invoking the descriptor-bound harness\nin a private empty working directory with a fixed environment.','`STARTED_NO_AUTOMATIC_RETRY` marker before copying the verified harness bytes to\na sealed executable memfd and invoking that immutable image in a private empty\nworking directory with a fixed environment. The filename nonce must equal the\nnonce inside the admission record.').replace('Stdout/stderr, runtime and bundle sizes are bounded. Timeout, output overflow,\nnonzero exit, invalid bundle or unconfirmed original-process-group cleanup are\nterminal failures.','Stdout/stderr, runtime and bundle sizes are bounded by the earliest policy or\nauthority deadline. Bundle inspection shares that deadline, rejects special\nfiles without blocking and requires an exact closed-world manifest. Timeout,\noutput overflow, nonzero exit, invalid bundle or unconfirmed process-group\ncleanup are terminal failures.')
executor_doc.write_text(d)

workflow=Path('.github/workflows/rust-ci-full.yml')
w=workflow.read_text()
needle='''      - name: Pre-warm dependency cache (cargo-chef)
        if: ${{ matrix.profile == 'release' }}
        shell: bash
        run: |
          set -euo pipefail
          RECIPE="${RUNNER_TEMP}/chef-recipe.json"
          cargo chef prepare --recipe-path "$RECIPE"
          cargo chef cook --recipe-path "$RECIPE" --target ${{ matrix.target }} --release

      - name: cargo clippy
'''
replacement='''      - name: Pre-warm dependency cache (cargo-chef)
        if: ${{ matrix.profile == 'release' }}
        shell: bash
        run: |
          set -euo pipefail
          RECIPE="${RUNNER_TEMP}/chef-recipe.json"
          cargo chef prepare --recipe-path "$RECIPE"
          cargo chef cook --recipe-path "$RECIPE" --target ${{ matrix.target }} --release

      - name: Restore and verify reviewed source after cargo-chef
        if: ${{ matrix.profile == 'release' }}
        shell: bash
        run: |
          set -euo pipefail
          reviewed_head="$(git rev-parse HEAD)"
          git restore --source="$reviewed_head" --staged --worktree -- .
          git diff --exit-code --no-ext-diff "$reviewed_head" -- .
          git diff --cached --exit-code --no-ext-diff
          if [[ -n "$(git status --porcelain --untracked-files=all -- . ':(exclude)target/**')" ]]; then
            echo 'cargo-chef left unreviewed source-tree files before release Clippy' >&2
            git status --short --untracked-files=all -- . ':(exclude)target/**' >&2
            exit 1
          fi
          test "$(git rev-parse HEAD^{tree})" = "$(git write-tree)"

      - name: cargo clippy
'''
if needle not in w: raise SystemExit('cargo-chef block not found')
workflow.write_text(w.replace(needle,replacement))
