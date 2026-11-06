from pathlib import Path
import json,hashlib,re
B=Path("/workspace/scratch/08f5efd48967")
D=B/"hepta-cell/qualification/cell-unification-20261106"
def pin(p,raw=None):
 p=Path(p);raw=p.read_bytes() if raw is None else raw
 try:n=p.relative_to(D).as_posix()
 except ValueError:n=str(p)
 return dict(path=n,bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),git_blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest())
def create(p,raw):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():assert p.read_bytes()==raw,str(p)
 else:
  with p.open("xb") as f:f.write(raw)
 return pin(p,raw)
def jd(o):return (json.dumps(o,ensure_ascii=False,indent=2)+"\n").encode()
def load(p):return json.loads(Path(p).read_bytes())
def group(name,mapping,notes):
 root=D/"history"/name;rows=[]
 for src,rel in mapping:
  rows.append(dict(source_workspace_path=src.relative_to(B).as_posix(),snapshot=create(root/rel,src.read_bytes())))
 return create(root/"MANIFEST.json",jd(dict(schema="hepta.exact-history-input-snapshot.v1",name=name,files=rows,original_bytes_unchanged=True,notes=notes,new_rust_or_training_execution=False)))
reg=B/"source51-preparation"
regmap=[(reg/"native-candidate-r26-source.json","source-manifest.json"),(reg/"source51-delta-manifest.json","delta-manifest.json"),(reg/"CREATED-COMMIT-API-ORIGINAL.json","CREATED-COMMIT-API-ORIGINAL.json"),(reg/"ROOT-APPLY-INPUT-FREEZE.json","ROOT-APPLY-INPUT-FREEZE.json"),(reg/"ROOT-APPLY-LAUNCH-AUTHORIZATION.json","ROOT-APPLY-LAUNCH-AUTHORIZATION.json"),(reg/"input/exec-server-probe-independent-readback.json","launcher-comparison-readback.json"),(B/"source51-apply-input-independent-review/BOUND-INDEPENDENT-READBACK.json","BOUND-INDEPENDENT-READBACK.json"),(B/"source51-apply-input-independent-review/FINAL-INDEPENDENT-READBACK.json","FINAL-INDEPENDENT-READBACK.json")]
registration=group("source51-registration",regmap,["Exact registered GitData identity and static/apply authorization snapshots; no branch or PR was created.","Original pending fields in the frozen source manifest are historical. Actual staged application is separately recorded.","Launcher comparison is bounded, not all-backend or Rust qualification. Its context references retain the original workspace meaning; this snapshot does not duplicate all probe inputs."])
ar=B/"native-validation-results/source51-apply-closed";files=sorted(p for p in ar.rglob("*") if p.is_file());assert len(files)==34
ap=group("source51-apply-checkpoint",[(p,p.relative_to(ar)) for p in files],["Closed apply-only originals. No Rust, lock update, fix/fmt or remote reference action.","Native HEAD remains the framework base. The created commit names the verified staged tree, not a checkout.","Original native source guards are preserved; documentation work does not repeat native execution."])
a=D/"history/source51-apply-checkpoint"
m=load(a/"original/native-candidate-r26-source.json");complete=load(a/"original/native-source51-apply/complete.json");post=load(a/"original/native-source51-apply/post-apply-source-guard.json");term=load(a/"controller/terminal-process-status.json")
assert m["source_commit"]==complete["source_commit"]==post["source_commit"]=="e28b0f385ee882f842911044958b2810f62f6379"
assert m["source_tree"]==complete["source_tree"]==post["actual_tree"]=="763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
assert term["state"]=="succeeded" and term["exit_code"]==0 and term["output_durable"] and term["output_complete"]
assert not term["timed_out"] and not term["cancelled"] and not term["automatic_retry"]
assert complete["source_guards_pass"] and post["pass"] and post["file_mismatches"]==post["unstaged_paths"]==post["untracked_paths"]==[]
assert not complete["rust_executed"] and not complete["bazel_lock_update_executed"] and not complete["fix_fmt_executed"]
row=next(x for x in m["changed_files"] if x["path"]==".github/workflows/hepta-cell-framework-native.yml")
wf=B/"native-validation-results/r24-archive-closed/original/source"/row["path"];raw=wf.read_bytes()
assert pin(wf,raw)["sha256"]==row["sha256"] and pin(wf,raw)["git_blob"]==row["git_blob"] and len(raw)==row["bytes"]
selectors=re.findall(r"-p ([A-Za-z0-9_-]+)",raw.decode().split("    steps:",1)[0]);assert len(selectors)==len(set(selectors))==27
old=load(D/"history/source49-r23-checkpoint/STATUS.json")
prefixes={
"codex-app-server":"codex-rs/app-server","codex-app-server-client":"codex-rs/app-server-client","codex-core":"codex-rs/core","codex-exec-server":"codex-rs/exec-server","codex-hepta-agent-protocol":"codex-rs/hepta-agent-protocol","codex-hepta-agentd":"codex-rs/hepta-agentd","codex-hepta-automation":"codex-rs/hepta-automation","codex-hepta-context-compiler":"codex-rs/hepta-context-compiler","codex-hepta-infer-worker-host":"codex-rs/hepta-infer-worker-host","codex-hepta-intelligence":"codex-rs/hepta-intelligence","codex-hepta-learning-artifacts":"codex-rs/hepta-learning-artifacts","codex-hepta-memory":"codex-rs/hepta-memory","codex-hepta-memory-extension":"codex-rs/ext/hepta-memory","codex-hepta-neuron":"codex-rs/hepta-neuron","codex-hepta-plasticity":"codex-rs/hepta-plasticity","codex-hepta-runtime":"codex-rs/hepta-runtime","codex-hepta-supervisor":"codex-rs/hepta-supervisor","codex-linux-sandbox":"codex-rs/linux-sandbox","codex-mcp":"codex-rs/codex-mcp","codex-model-provider-info":"codex-rs/model-provider-info","codex-shell-escalation":"codex-rs/shell-escalation","codex-utils-pty":"codex-rs/utils/pty","core_test_support":"codex-rs/core/tests/common","codex-cli":"codex-rs/cli","codex-network-proxy":"codex-rs/network-proxy","codex-external-agent-migration":"codex-rs/external-agent-migration"}
r24p=D/"native-evidence/r24-project-checkpoint/INDEPENDENT-READBACK.json";r24=load(r24p)
added=set(prefixes)-set(old["current_source"]["scope"]["owner_packages"])
assert added=={"codex-cli","codex-network-proxy","codex-external-agent-migration"} and added<=set(r24["rust_tests"]["per_package"])
owners={p:[] for p in prefixes};rust=[x for x in m["changed_files"] if x["path"].endswith(".rs")];other=[x["path"] for x in m["changed_files"] if not x["path"].endswith(".rs")]
assert len(m["changed_files"])==194 and len(rust)==180 and len(other)==14
for x in rust:
 matches=[(len(pre),p) for p,pre in prefixes.items() if x["path"].startswith(pre+"/")];assert matches,x["path"];owners[max(matches)[1]].append(x["path"])
assert all(owners.values()) and set(selectors)-set(owners)=={"codex-hepta-control-plane"}
sd=D/"history/source51-scope-preparation";wfp=create(sd/"hepta-cell-framework-native.yml",raw)
scope=dict(changed_source_paths=194,rust_paths=180,other_paths=14,source_counts_are_regular_files=True,owner_package_count=26,owner_packages=sorted(owners),ci_package_selector_count=27,ci_package_selectors=selectors,retained_ci_owner_without_changed_rust_path=["codex-hepta-control-plane"],counts_exclude_evidence_attachments=True,actual_source_manifest=pin(a/"original/native-candidate-r26-source.json"),native_apply_complete=pin(a/"original/native-source51-apply/complete.json"),native_apply_postguard=pin(a/"original/native-source51-apply/post-apply-source-guard.json"),derivation="All 180 source51 Rust paths assigned by longest known Cargo package-directory prefix. The exact source49 scope retains 23 package identities; the three added names appear in original r24 complete results. The unchanged actual workflow supplies 27 selectors. No Cargo or Rust ran for this derivation.",prior_package_identity_scope=pin(D/"history/source49-r23-checkpoint/STATUS.json"),added_owner_execution_evidence=pin(r24p),historical_cargo_metadata=old["current_source"]["scope"]["cargo_metadata"],current_cargo_metadata_executed_by_report_editor=False,fresh_default_workspace_metadata_required_before_r27=True,workflow={**row,"immutable_url":"https://github.com/TrillionniumFoundation/hepta-private-ci/blob/"+m["source_commit"]+"/"+row["path"],"exact_local_snapshot":wfp},final_fix_fmt_executed=False)
sp=create(sd/"SCOPE.json",jd(dict(schema="hepta.source51-owner-scope-preparation.v1",status="NOT_EXECUTED_PREPARATION_ONLY",source_commit=m["source_commit"],source_tree=m["source_tree"],scope=scope,owners=[dict(package=k,package_directory=prefixes[k],rust_path_count=len(owners[k]),rust_paths=owners[k]) for k in sorted(owners)],non_rust_paths=other,source50_to_source51_delta_does_not_change_package_or_CI_inputs=True)))
print(json.dumps(dict(registration=registration,apply=ap,scope=sp),ensure_ascii=False))

