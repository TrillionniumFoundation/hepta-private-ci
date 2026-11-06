#!/usr/bin/env python3
"""Offline source52 repair/apply/launch evidence attachment; no runner execution."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

HERE = Path(__file__).resolve().parent
WORK = HERE.parent if HERE.name == "source52-formal-preparation" else HERE.parents[4]
FORMAL = "hepta-cell/qualification/cell-unification-20261106/native-evidence/source52-repair-apply-checkpoint"
PARENT_COMMIT = "e28b0f385ee882f842911044958b2810f62f6379"
PARENT_TREE = "763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
COMMIT = "1e0910becc37383e6d17ecf861ea844fd07d8862"
TREE = "211f15baff19095e8c98bcea2b0ed99ca2270ade"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
RUNTIME = "codex-rs/network-proxy/src/runtime.rs"
APPLY_JOB = "1a1b1e474a3-fc05-7b5b"
R28_JOB = "1a1b1e9bee0-fc05-7b7c"
ARCHIVE_PIN = {"bytes":43267,"sha256":"9c7a414899bd05d1e70b9a6cbac64eef9dda552f8e56c904ee9f8e21ab37d6cb","git_blob":"eefc9ec94d7c5a0074eaa35788b3fbe670314420"}
LOCKS = {"cargo_lock_sha256":"4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c","bazel_lock_sha256":"e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"}


def pin(b):
    return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}


def jbytes(x):
    return (json.dumps(x,ensure_ascii=False,indent=2)+"\n").encode()


def safe(p):
    v=PurePosixPath(p)
    assert p and not v.is_absolute() and ".." not in v.parts and "." not in v.parts


def write_exact(p,b):
    p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists(): assert p.read_bytes()==b, str(p)
    else:
        with p.open("xb") as f: f.write(b)


def tree_hash(entries):
    ordered=sorted(entries,key=lambda e:(e["path"]+("/" if e["type"]=="tree" else "")).encode())
    body=b"".join(e["mode"].lstrip("0").encode()+b" "+e["path"].encode()+b"\0"+bytes.fromhex(e["sha"]) for e in ordered)
    return hashlib.sha1(b"tree "+str(len(body)).encode()+b"\0"+body).hexdigest()


def canonical(entries):
    return {e["path"]:{k:e[k] for k in ("path","mode","type","sha")} for e in entries}


def patch_apply(original,patch,reverse=False):
    lines=original.splitlines(keepends=True);out=[];pos=0
    p=patch.decode().splitlines(keepends=True);i=0;hunks=0
    while i<len(p):
        if not p[i].startswith("@@ "): i+=1;continue
        m=re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",p[i]);assert m
        old_start=int(m[3] if reverse else m[1])-1
        assert old_start>=pos
        out.extend(lines[pos:old_start]);pos=old_start;i+=1;hunks+=1
        while i<len(p) and not p[i].startswith("@@ "):
            text=p[i];i+=1
            if text.startswith(("--- ","+++ ")):break
            assert text[0] in " +-"
            prefix=text[0]
            if reverse:prefix={"+":"-","-":"+"," ":" "}[prefix]
            b=text[1:].encode()
            if prefix in " -":assert pos<len(lines) and lines[pos]==b;pos+=1
            if prefix in " +":out.append(b)
    out.extend(lines[pos:]);assert hunks==4
    return b"".join(out)


def literals(raw):
    result={}
    for n in ast.parse(raw).body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            try: result[n.targets[0].id]=ast.literal_eval(n.value)
            except (ValueError,TypeError):pass
    return result


def unbind(raw,keys):
    lines=raw.decode().splitlines(keepends=True);spans={}
    for n in ast.parse(raw).body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in keys:
            spans[n.targets[0].id]=(n.lineno-1,n.end_lineno)
    assert set(spans)==set(keys)
    for name,(first,last) in sorted(spans.items(),key=lambda x:x[1][0],reverse=True):
        lines[first:last]=[name+" = None\n"]
    return "".join(lines).encode()


def sealed(out):
    manifest=json.loads((out/"ATTACHMENT-MANIFEST.json").read_bytes())
    found={str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()}
    assert found=={x["path"] for x in manifest["files"]}|{"ATTACHMENT-MANIFEST.json"}
    for row in manifest["files"]:assert pin((out/row["path"]).read_bytes())=={k:row[k] for k in ("bytes","sha256","git_blob")}
    mapping=json.loads((out/"SOURCE-DESTINATION-MAPPING.json").read_bytes())
    for row in mapping["files"]:assert pin((out/row["destination"]).read_bytes())==row["original"]
    print(json.dumps({"status":"SEALED_BYTES_VERIFIED","file_count":len(found),"total_bytes":sum((out/p).stat().st_size for p in found),"manifest":pin((out/"ATTACHMENT-MANIFEST.json").read_bytes()),"source_originals_mapped":len(mapping["files"]),"native_execution_performed_by_this_readback":False},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work",type=Path,default=WORK);parser.add_argument("--output",type=Path,default=WORK/FORMAL);parser.add_argument("--verify-only",action="store_true")
    args=parser.parse_args();w=args.work;o=args.output
    if args.verify_only:sealed(o);return
    def read(path):return (w/path).read_bytes()
    def obj(path):return json.loads(read(path))
    selected={};handoffs=[]
    def add(src,dst,kind,protected=False):
        safe(src);safe(dst);b=read(src);assert src not in selected
        selected[src]={"destination":dst,"kind":kind,"raw":b,"protected":protected}
    def directory(src,dst,kind,protected=False):
        for p in sorted((w/src).rglob("*")):
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
                rel=str(p.relative_to(w/src));add(src+"/"+rel,dst+"/"+rel,kind,protected)
        h=w/src/"HANDOFF-MANIFEST.json"
        if h.exists():
            v=json.loads(h.read_bytes())
            for row in v["files"]:
                b=(w/src/row["path"]).read_bytes();actual=pin(b)
                assert all(actual[k]==row[k] for k in ("bytes","sha256"))
                if "git_blob" in row:assert actual["git_blob"]==row["git_blob"]
            assert len(v["files"])==v["file_count"]
            handoffs.append({"source":str(h.relative_to(w)),**pin(h.read_bytes()),"listed_files_verified":len(v["files"]),"historical_fields_preserved":True})
    # The complete root preparation directory is retained, including historical
    # provisional fields and later actual registration/authorization additions.
    directory("source52-preparation","source52-preparation","root_registration_or_historical_preparation",True)
    for src,dst,kind in [
        ("network-runtime-wildcard-r26-repair","candidate","frozen_fixture_candidate"),
        ("network-runtime-wildcard-r26-independent-review","reviews/candidate","independent_static_review"),
        ("source52-root-review","reviews/root","root_static_review"),
        ("source52-apply-preparation","apply-preparation","inert_preparation"),
        ("native-validation-results/source52-apply-bound-input","apply-binding","bound_preparation"),
        ("source52-apply-input-independent-review","reviews/apply","independent_static_review"),
        ("source52-native-gates-preparation","r28-preparation","inert_preparation"),
        ("source52-r28-independent-review","reviews/r28-template","independent_static_review"),
        ("native-validation-results/r28-bound-input","r28-binding","bound_preparation"),
        ("source52-r28-binding-independent-review","reviews/r28-binding","independent_static_review")]:directory(src,dst,kind)
    directory("native-validation-results/source52-apply-closed","native-apply","actual_apply_closed_originals",True)
    start="native-validation-results/r28-start-and-python-closed"
    for name in ("controller/launch.json","controller/runner-upload.json","controller/runner-file-info.json","native-run-r28.py"):
        add(start+"/"+name,"r28-launch/"+name,"actual_launch_only",True)
    assert all("python-runner" not in s and "r28-strict" not in s for s in selected)
    prior=obj("source52-preparation/input/source51-actual-manifest.json")
    provisional=obj("source52-preparation/candidate-source-manifest.json")
    current=obj("source52-preparation/native-candidate-r28-source.json")
    assert prior["source_commit"]==PARENT_COMMIT and prior["source_tree"]==PARENT_TREE
    assert provisional["source_commit"] is None and current["source_commit"]==COMMIT and current["source_tree"]==TREE
    assert current["source_parent_commit"]==PARENT_COMMIT and current["source_before_tree"]==PARENT_TREE
    old={r["path"]:r for r in prior["changed_files"]};new={r["path"]:r for r in current["changed_files"]}
    assert len(old)==194 and len(new)==195 and set(new)==set(old)|{RUNTIME} and RUNTIME not in old
    assert all(new[k]==v for k,v in old.items())
    assert provisional["changed_files"]==current["changed_files"]
    assert sum(p.endswith(".rs") for p in new)==181
    for k,v in LOCKS.items():assert current[k]==prior[k]==v
    before=read("source52-preparation/original/"+RUNTIME);after=read("source52-preparation/source/"+RUNTIME);patch=read("source52-preparation/candidate.patch")
    assert pin(after)=={k:new[RUNTIME][k] for k in ("bytes","sha256","git_blob")}
    assert pin(before)["sha256"]=="3214446d85796e5d1c4a308ba53aab3bf7098fc18cd38cfc6f97a1cbb14d2e4f"
    assert patch_apply(before,patch)==after and patch_apply(after,patch,True)==before
    assertions=lambda b:re.findall(rb"\b(?:assert|assert_eq|assert_ne)!",b)
    assert assertions(before)==assertions(after) and len(assertions(before))==101
    plan=obj("source52-preparation/PLAN.json")
    assert len(set(plan["owners"]))==26 and len(set(plan["ci_selectors"]))==27
    assert set(plan["ci_selectors"])-set(plan["owners"])=={"codex-hepta-control-plane"}
    rebuilt=[];original={};derived={}
    for name in ("root","codex","network","network_src"):
        a=obj("source52-preparation/input/original-trees/"+name+".json");b=obj("source52-preparation/derived-trees/"+name+".json")
        assert a["truncated"] is False and tree_hash(a["tree"])==a["sha"]==b["original_git_tree"]
        assert tree_hash(b["entries"])==b["expected_git_tree"]
        aa=canonical(a["tree"]);bb=canonical(b["entries"]);assert aa.keys()==bb.keys()
        changes=[k for k in aa if aa[k]!=bb[k]];assert len(changes)==1
        original[name]=aa;derived[name]=bb
        rebuilt.append({"name":name,"original":a["sha"],"derived":b["expected_git_tree"],"only_changed_child":changes[0]})
    assert rebuilt[0]["original"]==PARENT_TREE and rebuilt[0]["derived"]==TREE
    for parent,child,key in (("root","codex","codex-rs"),("codex","network","network-proxy"),("network","network_src","src")):
        ci=next(x for x in rebuilt if x["name"]==child)
        assert original[parent][key]["sha"]==ci["original"] and derived[parent][key]["sha"]==ci["derived"]
    assert original["network_src"]["runtime.rs"]["sha"]==pin(before)["git_blob"] and derived["network_src"]["runtime.rs"]["sha"]==pin(after)["git_blob"]
    api=obj("source52-preparation/CREATED-COMMIT-API-ORIGINAL.json");registration=obj("source52-preparation/ROOT-ACTUAL-IDENTITY.json")
    assert api["sha"]==registration["commit"]==COMMIT and api["tree"]["sha"]==registration["tree"]==TREE and [p["sha"] for p in api["parents"]]==[PARENT_COMMIT]
    assert registration["native_applied"] is False  # Original registration-time snapshot retained.
    ar=read("source52-preparation/source52-apply-input.tar.gz");assert pin(ar)==ARCHIVE_PIN
    freeze=obj("source52-preparation/ROOT-APPLY-INPUT-FREEZE.json");members={};member_modes={}
    with tarfile.open(fileobj=io.BytesIO(ar),mode="r:gz") as tf:
        for m in tf.getmembers():
            safe(m.name);assert m.isfile() and not m.issym() and not m.islnk() and m.name not in members
            members[m.name]=tf.extractfile(m).read();member_modes[m.name]=m.mode;assert len(members[m.name])==m.size
    assert len(members)==5 and set(members)=={r["path"] for r in freeze["members"]}
    for row in freeze["members"]:assert pin(members[row["path"]])=={k:row[k] for k in ("bytes","sha256","git_blob")}
    expected={"before/"+RUNTIME:before,"after/"+RUNTIME:after,"candidate.patch":patch,"source52-manifest.json":read("source52-preparation/native-candidate-r28-source.json"),"delta-manifest.json":read("source52-preparation/source52-actual-delta-manifest.json")}
    assert members==expected
    binding_proofs=[]
    for prefix,template,bound,final,bindings in [
        ("apply","source52-apply-preparation/native-source52-apply-template.py","native-validation-results/source52-apply-bound-input/native-source52-apply-bound.py","source52-preparation/ROOT-APPROVED-APPLY.py",obj("source52-preparation/ROOT-APPLY-BINDINGS.json")),
        ("r28","source52-native-gates-preparation/native-run-r28-template.py","native-validation-results/r28-bound-input/native-run-r28-bound.py","source52-preparation/ROOT-APPROVED-R28.py",obj("native-validation-results/r28-bound-input/ACTUAL-BINDINGS.json"))]:
        tr,br,fr=read(template),read(bound),read(final);bv=literals(br);fv=literals(fr)
        assert bv["FROZEN"] is False and fv["FROZEN"] is True and all(bv[k]==v for k,v in bindings.items())
        assert unbind(br,bindings)==tr and br.replace(b"FROZEN = False",b"FROZEN = True",1)==fr
        assert len(bindings)==(8 if prefix=="apply" else 15)
        binding_proofs.append({"stage":prefix,"template":pin(tr),"bound":pin(br),"final":pin(fr),"literal_count":len(bindings),"whole_template_inverse_exact":True,"final_only_frozen_flip":True})
    native="native-validation-results/source52-apply-closed/";ev=native+"evidence/native-source52-apply/"
    nr=obj(native+"LOCAL-READBACK.json");assert nr["source_commit"]==COMMIT and nr["source_tree"]==TREE and nr["outer_exit_code"]==0
    assert len(nr["raw_originals"])==25 and len(nr["controller_originals"])==6
    for row in nr["raw_originals"]:assert pin(read(native+"evidence/"+row["path"]))=={k:row[k] for k in ("bytes","sha256","git_blob")}
    for row in nr["controller_originals"]:assert pin(read(native+row["path"]))=={k:row[k] for k in ("bytes","sha256","git_blob")}
    complete=obj(ev+"complete.json");post=obj(ev+"post-apply-source-guard.json");terminal=obj(native+"controller/terminal-process-status.json")
    assert terminal==obj(native+"evidence/native-source52-apply-terminal-process-status.json")
    assert terminal["job_id"]==APPLY_JOB and terminal["state"]=="succeeded" and terminal["exit_code"]==0
    assert all(terminal[k] is False for k in ("timed_out","cancelled","automatic_retry"))
    assert all(terminal[k] is True for k in ("output_complete","output_durable","terminal_publication_confirmed"))
    assert all(v is False for v in terminal["log_truncated"].values()) and all(v is None for v in terminal["log_errors"].values())
    assert complete["source_commit"]==post["source_commit"]==COMMIT and complete["source_tree"]==post["actual_tree"]==post["expected_tree"]==TREE
    assert complete["actual_changed_file_count"]==post["actual_changed_file_count"]==post["expected_count"]==195
    assert complete["native_git_head"]==post["native_head"]==HEAD
    assert post["pass"] and post["changed_path_set_matches"] and post["native_head_unchanged"]
    assert post["file_mismatches"]==post["untracked_paths"]==post["unstaged_paths"]==[] and set(post["changed_paths"])==set(new)
    assert post["changed_from_source51_paths"]==complete["changed_from_source51_paths"]==[RUNTIME]
    assert complete["source51_original_changed_manifest_rows_unchanged"] and post["source51_original_changed_manifest_rows_unchanged"]
    for k,v in LOCKS.items():assert complete[k]==post[k]==v
    assert complete["dependency_inputs_changed_paths"]==[] and not complete["rust_executed"] and not complete["bazel_lock_update_executed"] and not complete["fix_fmt_executed"]
    assert read(native+"evidence/native-candidate-r28-source.json")==members["source52-manifest.json"]
    assert read(native+"native-source52-apply.py")==read("source52-preparation/ROOT-APPROVED-APPLY.py")
    for side in ("pre-apply","immediately-before-apply"):
        v=obj(ev+side+"-source-guard.json");assert v["pass"] and v["actual_tree"]==PARENT_TREE and v["actual_changed_file_count"]==194 and v["native_head"]==HEAD
    command_proofs=[]
    expected_cmds={"apply-check":["git","apply","--check","/home/alex/work/hepta-cell-unified-20261106-a/evidence/native-source52-apply/input/candidate.patch"],"apply":["git","apply","/home/alex/work/hepta-cell-unified-20261106-a/evidence/native-source52-apply/input/candidate.patch"],"stage-exact-paths":["git","add","--",RUNTIME]}
    for phase,command in expected_cmds.items():
        raw=obj(ev+phase+"-raw-process-result.json");receipt=obj(ev+phase+"-receipt.json");started=obj(ev+phase+"-started.json")
        assert all(receipt[k]==v for k,v in raw.items()) and raw["exit_code"]==0 and raw["wait_exception"] is None and raw["command"]==command
        assert raw["cwd"]=="/home/alex/work/hepta-cell-unified-20261106-a/source" and raw["ended_unix"]>=raw["started_unix"]
        assert started["command"]==command and started["cwd"]==raw["cwd"]
        for stream in ("stdout","stderr"):assert receipt[stream]==pin(read(ev+phase+"-"+stream+".log"))
        command_proofs.append({"phase":phase,"command":command,"exit_code":0,"elapsed_seconds":raw["elapsed_seconds"],"raw":pin(read(ev+phase+"-raw-process-result.json")),"receipt":pin(read(ev+phase+"-receipt.json"))})
    assert patch_apply(before,read(ev+"actual-source51-to-source52.patch"))==after
    r28_authorization=obj("source52-preparation/ROOT-R28-LAUNCH-AUTHORIZATION.json");apply_authorization=obj("source52-preparation/ROOT-APPLY-LAUNCH-AUTHORIZATION.json")
    for auth,file in ((r28_authorization,"ROOT-APPROVED-R28.py"),(apply_authorization,"ROOT-APPROVED-APPLY.py")):
        assert auth["source_commit"]==COMMIT and auth["source_tree"]==TREE
        assert all(pin(read("source52-preparation/"+file))[k]==auth["runner"][k] for k in ("bytes","sha256"))
    launch=obj(start+"/controller/launch.json");info=obj(start+"/controller/runner-file-info.json");runner=read(start+"/native-run-r28.py")
    assert runner==read("source52-preparation/ROOT-APPROVED-R28.py")
    assert info["sha256"]==pin(runner)["sha256"] and info["size"]==len(runner)==54455
    assert launch["job"]["id"]==R28_JOB and launch["job"]["launch_state"]=="launched" and launch["job"]["launch_error"] is None and launch["launch"]["ok"] is True and launch["reused"] is False
    assert pin(runner)["sha256"] in launch["job"]["args"][1]
    # Every selected original is copied unchanged. Identical large preparation
    # duplicates may share a destination; all source locations stay in the map.
    mappings=[];dedup={};written={}
    for src,v in selected.items():
        b=v["raw"];p=pin(b);dst=v["destination"];key=(p["sha256"],len(b));reused=False
        if not v["protected"] and len(b)>=16384 and key in dedup:dst=dedup[key];reused=True
        else:
            write_exact(o/dst,b);written[dst]=b;dedup.setdefault(key,dst)
        mappings.append({"source":src,"destination":dst,"kind":v["kind"],"original":p,"encoding":"unchanged_raw_bytes","deduplicated_to_equal_bytes":reused})
    write_exact(o/"assemble_attachment.py",Path(__file__).read_bytes())
    mapping={"schema":"hepta.source52-attachment-source-mapping.v1","files":mappings,"original_count":len(mappings),"stored_original_destinations":len(set(x["destination"] for x in mappings)),"all_original_bytes_verified":True}
    write_exact(o/"SOURCE-DESTINATION-MAPPING.json",jbytes(mapping))
    write_exact(o/"HANDOFF-VERIFICATION.json",jbytes({"schema":"hepta.source52-attachment-handoff-verification.v1","handoffs":handoffs,"listed_originals_verified":True,"historical_fields_rewritten":False}))
    input_members=[{"path":p,**pin(b),"tar_mode":member_modes[p]} for p,b in members.items()]
    write_exact(o/"INPUT-ARCHIVE-MEMBERS.json",jbytes({"schema":"hepta.source52-original-input-members.v1","archive":ARCHIVE_PIN,"member_count":5,"members":input_members,"all_exact_against_frozen_files":True}))
    report={"schema":"hepta.source52-repair-apply-attachment-readback.v1","status":"REGISTERED_AND_APPLIED_LAUNCH_ONLY_SNAPSHOT","source_commit":COMMIT,"source_tree":TREE,"source_parent_commit":PARENT_COMMIT,"source_before_tree":PARENT_TREE,"native_head":HEAD,"source_count":195,"rust_paths":181,"other_paths":14,"previous194_rows_unchanged":True,"only_changed_from_parent":RUNTIME,"owners":26,"ci_selectors":27,"ci_extra_owner":"codex-hepta-control-plane","owner_scope_boundary":"Recorded prepared scope retained; final owner binding still requires future fresh workspace metadata.","four_level_offline_git_reconstruction":rebuilt,"original_and_derived_tree_sha_verified":True,"actual_commit_api":pin(read("source52-preparation/CREATED-COMMIT-API-ORIGINAL.json")),"candidate_before":pin(before),"candidate_after":pin(after),"candidate_patch":pin(patch),"patch_forward_inverse_exact":True,"original_assertion_tokens_preserved":101,"fixture_config_literals_changed":4,"production_default_or_shared_helper_changed":False,"input_archive":ARCHIVE_PIN,"safe_regular_input_members":5,"reviewed_binding_proofs":binding_proofs,"actual_apply":{"job_id":APPLY_JOB,"outer_exit_code":0,"native_originals":25,"controller_originals":6,"complete":pin(read(ev+"complete.json")),"terminal":pin(read(native+"controller/terminal-process-status.json")),"commands":command_proofs,"source195_and_dual_locks_guard_pass":True,"source51_head_retained":HEAD,"source50_lock_inherited_not_new_invocation":True},"r28":{"job_id":R28_JOB,"scope":"LAUNCH_ONLY","runner":pin(runner),"launch":pin(read(start+"/controller/launch.json")),"phase_results":None,"test_counts":None,"terminal_status":None,"later_closed_or_active_gate_results_included":False},"r26_original_result":"FAILED100:1562PASS/2FAIL/0TIMEOUT,3reportedskip","r26_not_reclassified":True,"new_rust_or_native_execution_by_this_readback":False,"git_upload_by_this_readback":False,"source_or_original_bytes_modified":False,"science":"HOLD","authority":"DENY_ALL","limits":["Original NotAllowedLocal mismatches do not identify a specific DNS answer, error or delay.","Preparation and registration originals retain their historical native_applied=false fields; actual apply evidence is a later, separate stage.","Static reviews and actual apply/launch do not constitute Rust gate qualification.","Source52 does not inherit source51 project qualification; r26 remains failed.","The only binary payload is the exact registered five-member apply archive."]}
    write_exact(o/"INDEPENDENT-READBACK.json",jbytes(report))
    references=[
        ("r26_original_failure","r26-project-checkpoint/CLOSURE.json"),
        ("source51_original_apply","source51-repair-apply-checkpoint/CLOSURE.json")]
    refs=[]
    for label,rel in references:
        p=o.parent/rel;refs.append({"kind":label,"relative_to_native_evidence":rel,**pin(p.read_bytes()),"copied_archive":False})
    closure={"schema":"hepta.source52-repair-apply-closure.v1","status":"CLOSED_REGISTERED_APPLY_PASS_R28_LAUNCH_ONLY","source_commit":COMMIT,"source_tree":TREE,"source_parent_commit":PARENT_COMMIT,"source_before_tree":PARENT_TREE,"native_head":HEAD,"changed_paths":195,"rust_paths":181,"other_paths":14,"owners_prepared":26,"ci_selectors":27,"source51_original194_retained":True,"single_delta_path":RUNTIME,"actual_apply":{"job_id":APPLY_JOB,"original_git_command_exit_codes":[0,0,0],"natural_outer_exit":0,"source_guards":"PASS","new_lock_or_rust_or_fix_fmt":False},"r28":{"job_id":R28_JOB,"snapshot":"LAUNCHED","python_result":None,"strict_result":None,"tests_result":None,"terminal":None,"counts":None},"history_fields_preserved":True,"original_archive":{"path":"source52-preparation/source52-apply-input.tar.gz",**ARCHIVE_PIN},"independent_readback":{"path":"INDEPENDENT-READBACK.json",**pin(jbytes(report))},"references":refs,"closure_gaps":[],"science":"HOLD","authority":"DENY_ALL","formal_group_later_gate_results_included":False,"source_or_report_edits_outside_new_group":False}
    write_exact(o/"CLOSURE.json",jbytes(closure))
    readme=f"""# source52：单叶 fixture 修复、实际 apply 与 r28 启动快照

本组封存 source52 commit `{COMMIT}`、tree `{TREE}`。source51 的原 194 条清单逐行保留，新增既有仓库叶 `{RUNTIME}`，共 **195 路径＝181 Rust＋14 其他**；准备范围仍为 26 Rust owners、27 CI selectors。

## 分开的事实层

| 层 | 本组记录 |
| --- | --- |
| 修复与静态审阅 | 仅四个 hostname pattern/list-update fixture 显式启用原有 allow_local_binding；101 个原 assertion token、独立默认配置循环及真实地址保护测试保留。没有改生产默认或公共 helper。 |
| 原 r26 结果 | source51 原门仍 FAILED100：1562 PASS、2 FAIL、0 TIMEOUT，3 reported skip。实际 NotAllowedLocal 断言不证明具体 DNS 回答或耗时原因。 |
| Git 注册 | 四层原 direct-tree 和派生对象均独立重算，实际 Git commit API 与预测 tree 完全对应；不是 native checkout HEAD 声明。 |
| 原实际 apply | job `{APPLY_JOB}`；三个原 Git 命令和自然外层均退出 0，195/双锁/HEAD 守卫通过。native HEAD 仍为 `{HEAD}`。 |
| r28 启动 | job `{R28_JOB}`；只保留启动授权、冻结 runner、上传和 launch 原件。阶段结果、测试计数和终态全部为 null，后续闭合结果不回填此快照。 |

历史 PLAN、provisional manifest、registration 和 static review 内的 `native_applied=false` 等字段按原字节保留。较晚的真实 apply 由 [CLOSURE.json](CLOSURE.json) 与 [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json) 单独绑定。

## 原件入口

- [五成员原输入包](source52-preparation/source52-apply-input.tar.gz)：43,267 B，SHA256 `{ARCHIVE_PIN['sha256']}`，已登记 Git blob `{ARCHIVE_PIN['git_blob']}`。逐成员原字节、原 tar modes 与 Git source modes 分开核对。
- source52-preparation/：预计计划、原四层 trees、实际注册 API、195 清单、两份 root 授权与 approved scripts。
- native-apply/：25 份原 native evidence＋6 份 controller 原件，以及完整原读回/传输准备材料。
- r28-launch/：仅四份启动输入；没有收取 initial-process-status、process-read、Python/strict/tests 的结果或日志。
- reviews/、apply-preparation/、apply-binding/、r28-preparation/、r28-binding/：原静态与 bound 审阅，不作为执行通过证据。
- [SOURCE-DESTINATION-MAPPING.json](SOURCE-DESTINATION-MAPPING.json) 覆盖所有来源；大块相同准备副本可共用原字节目的地，根授权及实际 apply 原目录完整保留。没有重新包装 source51 或 r26 archive。

`python3 assemble_attachment.py --verify-only` 仅核本组 manifest 和映射字节，不执行任何附带 runner、Rust、Git、metadata 或 formatter。**science HOLD / authority DENY_ALL 不变；apply 与 launch 不授予工程测试资格。**
"""
    write_exact(o/"README.md",readme.encode())
    binary={"schema":"hepta.binary-attachment-plan.v1","git_upload_performed":False,"files":[{"path":"source52-preparation/source52-apply-input.tar.gz","repository_path":"qualification/cell-unification-20261106/native-evidence/source52-repair-apply-checkpoint/source52-preparation/source52-apply-input.tar.gz",**ARCHIVE_PIN,"action":"reuse_registered_git_blob","uploaded_by_this_task":False}],"count":1}
    write_exact(o/"BINARY-PLAN.json",jbytes(binary))
    final_files=[]
    for p in sorted(o.rglob("*")):
        if p.is_file() and p.name!="ATTACHMENT-MANIFEST.json":final_files.append({"path":str(p.relative_to(o)),**pin(p.read_bytes())})
    manifest={"schema":"hepta.formal-attachment-manifest.v1","group":"source52-repair-apply-checkpoint","files":final_files,"listed_file_count":len(final_files),"listed_total_bytes":sum(x["bytes"] for x in final_files),"source_commit":COMMIT,"source_tree":TREE,"status":"APPLY_PASS_LAUNCH_ONLY_NOT_RUST_QUALIFICATION"}
    write_exact(o/"ATTACHMENT-MANIFEST.json",jbytes(manifest));sealed(o)
    print(json.dumps({"closure":pin((o/"CLOSURE.json").read_bytes()),"independent":pin((o/"INDEPENDENT-READBACK.json").read_bytes()),"binary_count":1,"apply_originals":31,"r28_scope":"LAUNCH_ONLY"},indent=2))


if __name__=="__main__":main()
