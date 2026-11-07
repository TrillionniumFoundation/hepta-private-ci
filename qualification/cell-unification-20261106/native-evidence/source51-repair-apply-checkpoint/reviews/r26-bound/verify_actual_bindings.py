"""Read-only local validation of closed apply and r26 binding; do not import runners."""
from pathlib import Path
import ast, hashlib, json
ROOT=Path("/workspace/scratch/08f5efd48967")
OUT=ROOT/"r26-bound-independent-review"
TEMPLATE=ROOT/"source51-native-gates-preparation/native-run-r26-template-v2.py"
BOUND=ROOT/"native-validation-results/r26-source51-bound-input/native-run-r26-bound.py"
BINDING=ROOT/"native-validation-results/r26-source51-bound-input/ACTUAL-BINDINGS.json"
CLOSED=ROOT/"native-validation-results/source51-apply-closed"
def pin(b):
    return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}
def named(p):
    return {"path":str(p.relative_to(ROOT)),**pin(p.read_bytes())}
def j(p):return json.loads(p.read_bytes())
def assignments(text):
    out={}
    lines=text.splitlines(keepends=True)
    for n in ast.parse(text).body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            try:v=ast.literal_eval(n.value)
            except ValueError:continue
            out[n.targets[0].id]=(v,n,"".join(lines[n.lineno-1:n.end_lineno]))
    return out
def funcs(text):
    lines=text.splitlines(keepends=True)
    return {n.name:"".join(lines[n.lineno-1:n.end_lineno]) for n in ast.parse(text).body if isinstance(n,ast.FunctionDef)}
tb,bb=TEMPLATE.read_bytes(),BOUND.read_bytes()
assert pin(tb)["sha256"]=="f89ecbf2fe8585b739c3ecc5cb5057b762473ba73a7fea9dd6483213d3f8a6a0"
assert pin(bb)["sha256"]=="ade5e1a827e36b821f4fb562aa175ad58147811419255732e0c62c27743802a6"
bindings=j(BINDING);assert len(bindings)==15
ta,ba=assignments(tb.decode()),assignments(bb.decode())
assert ta["FROZEN"][0] is False and ba["FROZEN"][0] is False
inverse=bb.decode()
for name,value in bindings.items():
    assert ta[name][0] is None and ba[name][0]==value
    old=ba[name][2];new=ta[name][2]
    assert inverse.count(old)==1
    inverse=inverse.replace(old,new,1)
assert inverse.encode()==tb
tf,bf=funcs(tb.decode()),funcs(bb.decode())
assert tf==bf
assert bb.count(b"FROZEN = False\n")==1
final=bb.replace(b"FROZEN = False\n",b"FROZEN = True\n",1)
assert pin(final)["sha256"]=="c46f22be2c4b71004dc086870eaf5a69efed0ee32cde47cf33a2ef818f168396"
assert funcs(final.decode())==bf
ast.parse(final)
closed_index=j(CLOSED/"LOCAL-READBACK.json")
assert pin((CLOSED/"LOCAL-READBACK.json").read_bytes())["sha256"]=="befe323d6068f855f654dceb49b5e51be0d6a0f1f38a5fbbe48be4f94d70468d"
assert len(closed_index["files"])==23
for row in closed_index["files"]:
    assert pin((CLOSED/row["path"]).read_bytes())=={k:row[k] for k in ("bytes","sha256","git_blob")}
orig=CLOSED/"original"
comp_path=orig/bindings["APPLY_COMPLETE_NAME"]
delta_path=orig/bindings["DELTA_MANIFEST_NAME"]
term_path=CLOSED/"controller/terminal-process-status.json"
for prefix,path in (("APPLY_COMPLETE",comp_path),("APPLY_TERMINAL",term_path),("DELTA_MANIFEST",delta_path)):
    p=pin(path.read_bytes());assert p["bytes"]==bindings[prefix+"_BYTES"] and p["sha256"]==bindings[prefix+"_SHA256"]
complete,delta,terminal=j(comp_path),j(delta_path),j(term_path)
source_path=orig/bindings["SOURCE_MANIFEST_NAME"]
source=j(source_path)
assert pin(source_path.read_bytes())["sha256"]==bindings["SOURCE_MANIFEST_SHA256"]
assert complete["source_manifest"]=={"path":bindings["SOURCE_MANIFEST_NAME"],**pin(source_path.read_bytes())}
assert complete["delta_manifest"]=={"path":bindings["DELTA_MANIFEST_NAME"],**pin(delta_path.read_bytes())}
post_path=orig/complete["source_postguard"]["path"]
post=j(post_path)
assert complete["source_postguard"]=={"path":complete["source_postguard"]["path"],**pin(post_path.read_bytes())}
assert source["schema"]=="hepta.root-bound-source51.v1"
for d in (source,complete,delta,post):
    assert d["source_commit"]==bindings["EXPECTED_COMMIT"]
assert source["source_tree"]==complete["source_tree"]==delta["source_tree"]==post["actual_tree"]==bindings["EXPECTED_TREE"]
assert source["source_parent_commit"]==complete["source_before_commit"]==delta["source_before_commit"]==ta["LOCK_SOURCE50_COMMIT"][0]
assert complete["source_before_tree"]==delta["source_before_tree"]==ta["LOCK_SOURCE50_TREE"][0]
assert len(source["changed_files"])==len({x["path"] for x in source["changed_files"]})==complete["actual_changed_file_count"]==post["actual_changed_file_count"]==bindings["EXPECTED_CHANGED_COUNT"]==194
for key,constant in (("cargo_lock_sha256","CARGO_LOCK_SHA256"),("bazel_lock_sha256","BAZEL_LOCK_SHA256")):
    assert source[key]==complete[key]==post[key]==ta[constant][0]
assert complete["schema"]=="hepta.source51-apply-complete.v1"
assert complete["source_guards_pass"] is True and complete["dependency_inputs_changed_paths"]==[]
for k in ("bazel_lock_update_executed","rust_executed","fix_fmt_executed"):assert complete[k] is False
assert post["schema"]=="hepta.source51-apply-postguard.v1" and post["pass"] is True and post["changed_path_set_matches"] is True
assert set(post["changed_paths"])=={r["path"] for r in source["changed_files"]}
assert len(post["changed_paths"])==194
assert post["native_head"]==complete["native_git_head"]==ta["FRAMEWORK_PARENT"][0] and post["native_head_unchanged"] is True
for k in ("unstaged_paths","untracked_paths","file_mismatches","dependency_inputs_changed_paths"):assert post[k]==[]
assert complete["root_commit_mapping_is_tree_identity_not_checkout_claim"] is True
allowed=list(ta["ALLOWED_SOURCE51_DELTA"][0])
assert complete["changed_from_source50_paths"]==post["changed_from_source50_paths"]==allowed
assert [r["path"] for r in delta["files"]]==allowed and delta["schema"]=="hepta.source51-apply-delta.v1"
assert terminal["job_id"]==bindings["APPLY_JOB_ID"] and terminal["state"]=="succeeded" and terminal["exit_code"]==0
for k in ("timed_out","cancelled","automatic_retry"):assert terminal[k] is False
for k in ("output_complete","output_durable","terminal_publication_confirmed"):assert terminal[k] is True
assert all(x is False for x in terminal["log_truncated"].values())
assert all(x is None for x in terminal["log_errors"].values())
commands=[]
for phase,cmd in (
    ("apply-check",["git","apply","--check","/home/alex/work/hepta-cell-unified-20261106-a/evidence/native-source51-apply/input/candidate.patch"]),
    ("apply",["git","apply","/home/alex/work/hepta-cell-unified-20261106-a/evidence/native-source51-apply/input/candidate.patch"]),
    ("stage-exact-paths",["git","add","--",*allowed]),
):
    rp=orig/"native-source51-apply"/(phase+"-raw-process-result.json")
    cp=orig/"native-source51-apply"/(phase+"-receipt.json")
    r,c=j(rp),j(cp)
    for k,v in r.items():assert c[k]==v
    assert r["command"]==cmd and r["cwd"]=="/home/alex/work/hepta-cell-unified-20261106-a/source"
    assert r["exit_code"]==0 and r["wait_exception"] is None
    assert r["started_unix"]<=r["ended_unix"]<=terminal["at_unix_ms"]/1000
    assert r["elapsed_seconds"]>=0
    assert c["stdout"]==c["stderr"]==pin(b"")
    commands.append({"phase":phase,"command":cmd,"exit_code":0,"raw":named(rp),"receipt":named(cp)})
    if len(commands)>1:assert previous_end<=r["started_unix"]
    previous_end=r["ended_unix"]
binding_report_path=ROOT/"native-validation-results/r26-source51-bound-input/BINDING-READBACK.json"
binding_report=j(binding_report_path)
assert binding_report["template"]==pin(tb) and binding_report["bound"]==pin(bb) and binding_report["anticipated_final"]==pin(final)
assert binding_report["bindings"]==bindings
assert binding_report["apply_complete"]=={"path":bindings["APPLY_COMPLETE_NAME"],**pin(comp_path.read_bytes())}
assert binding_report["apply_terminal"]=={"path":bindings["APPLY_TERMINAL_NAME"],**pin(term_path.read_bytes())}
OUT.mkdir(exist_ok=False)
report={
    "schema":"hepta.r26-bound-independent-static-review.v1",
    "status":"STATIC_CLEAR_NO_EXECUTION",
    "template":named(TEMPLATE),"bound":named(BOUND),
    "binding_original":named(BINDING),"native_binding_readback":named(binding_report_path),
    "exact_fifteen_constant_replacements":True,"whole_file_inverse_equals_reviewed_template":True,
    "all_function_texts_equal":True,"function_count":len(tf),"commands_environment_acceptance_and_source_guards_unchanged":True,
    "anticipated_final_only_frozen_flip":pin(final),
    "anticipated_final_written_or_executed_by_this_review":False,
    "local_ast_parse_pass":True,"runners_imported_or_executed":False,
    "closed_apply":{"local_readback":named(CLOSED/"LOCAL-READBACK.json"),"all23listed_original_pins_verified":True,
       "complete":named(comp_path),"terminal":named(term_path),"source_manifest":named(source_path),"postguard":named(post_path),"delta":named(delta_path),
       "original_git_commands":commands,"outer_natural_exit":0,"source_commit":bindings["EXPECTED_COMMIT"],"source_tree":bindings["EXPECTED_TREE"],
       "manifest_paths":194,"exact_two_changed_paths":allowed,"raw_locks_unchanged_as_bound_in_original_guard":True,
       "native_HEAD":"bef6fa7645df9df12b69fda499e97eed25de6c75","GitData_commit_is_not_native_checkout_claim":True},
    "static_contract":{
       "source50_lock_inherited_not_reexecuted":True,"r24_failed100_retained":True,
       "original_order":["python32","four_package_strict","four_package_full_tests"],
       "raw_rc_durable_first":True,"natural_wait_no_kill_or_retry":True,
       "all1564baseline_IDs_are_acceptance_not_filters":True,"Python32_zero_skip_required":True,
       "source_guard_failure_blocks_later_phases":True,"workspace_not_started_by_r26":True,
       "FROZEN_false_bound_requires_root_final_authorization":True},
    "limits":["No Rust, metadata, native job, formatter or live log was read/executed.",
              "This review validates local originals and static interface; it does not claim a new remote194-source read or r26 success.",
              "Expected final hash is computed from the unique False-to-True change; this reviewer neither writes nor runs that final script."],
}
raw=(json.dumps(report,indent=2,ensure_ascii=False)+"\n").encode()
(OUT/"INDEPENDENT-REVIEW.json").write_bytes(raw)
print(json.dumps({"report":pin(raw),"function_count":len(tf),"apply_originals":23,"bound":pin(bb),"anticipated_final":pin(final),"status":"STATIC_CLEAR_NO_EXECUTION"},indent=2))

