#!/usr/bin/env python3
"""Build source52 report candidates only; canonical reports are never written."""
import copy,gzip,hashlib,json
from pathlib import Path
B=Path("/workspace/scratch/08f5efd48967");P=B/"source52-report-update-preparation"
R=B/"hepta-cell/qualification/cell-unification-20261106";N=P/"new-files"
C52="1e0910becc37383e6d17ecf861ea844fd07d8862";T52="211f15baff19095e8c98bcea2b0ed99ca2270ade"
C51="e28b0f385ee882f842911044958b2810f62f6379";T51="763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
F=json.loads((P/"FACTS.candidate.json").read_bytes())
def enc(o):return (json.dumps(o,indent=2,ensure_ascii=False)+"\n").encode()
def pin(d):return {"bytes":len(d),"sha256":hashlib.sha256(d).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(d)).encode()+b"\0"+d).hexdigest()}
def load(p):return json.loads(p.read_bytes())
def out(p,o):p.parent.mkdir(parents=True,exist_ok=True);d=enc(o);p.write_bytes(d);return pin(d)
def report_ref(rel):
 p=N/rel
 if not p.exists():p=R/rel
 return {"path":rel,**pin(p.read_bytes())}
groups={}
pending=[]
def formal_ref(local,group):
 raw=local.read_bytes();want=pin(raw);root=R/"native-evidence"/group
 if group not in groups:
  items=[]
  if root.is_dir():
   for path in sorted(root.rglob("*")):
    if not path.is_file():continue
    data=path.read_bytes();items.append((path,pin(data),None))
    if path.suffix==".gz":
     try:decoded=gzip.decompress(data)
     except (OSError,EOFError):continue
     items.append((path,pin(decoded),pin(data)))
  groups[group]=items
 matches=[v for v in groups[group] if v[1]==want]
 if matches:
  path,original,stored=sorted(matches,key=lambda v:(v[2] is not None,len(v[0].parts),str(v[0])))[0]
  obj={"path":str(path.relative_to(R)),**(stored or original)}
  if stored:obj.update(compression="gzip",original_uncompressed=original)
  return obj
 pending.append({"original":str(local.relative_to(B)),"expected_group":"native-evidence/"+group,**want})
 return {"path":None,**want,"formal_attachment_pending":True,"original_local_path":str(local.relative_to(B))}
def r26_member(local):
 return formal_ref(local,"r26-project-checkpoint")
def source52_member(local):
 return formal_ref(local,"source52-repair-apply-checkpoint")

S=load(P/"references/STATUS.json");I=load(P/"references/SOURCE_IDENTITY.json")
OLD_S=copy.deepcopy(S);OLD_I=copy.deepcopy(I)
ledger=load(N/"history/source52-ledger-snapshot/publication-ledger.json")
assert ledger["current_source_commit"]==C52 and len(ledger["commits"])==52
source_path=B/"native-validation-results/source52-apply-closed/evidence/native-candidate-r28-source.json"
source=load(source_path);rows={r["path"]:r for r in source["changed_files"]}
assert len(rows)==195 and sum(x.endswith(".rs") for x in rows)==181
A=B/"native-validation-results/source52-apply-closed/evidence"
complete_path=A/"native-source52-apply/complete.json";post_path=A/"native-source52-apply/post-apply-source-guard.json"
terminal_path=A/"native-source52-apply-terminal-process-status.json"
complete=load(complete_path);post=load(post_path);terminal=load(terminal_path)
assert complete["source_tree"]==post["actual_tree"]==T52 and post["pass"] and terminal["exit_code"]==0
apply52={
 "source_stage":52,"source_commit":C52,"source_tree":T52,"state":"APPLIED_STAGED_TREE_NO_RUST_QUALIFICATION",
 "native_apply_job":terminal["job_id"],"original_outer_exit_code":0,"natural_outer_state":"succeeded",
 "output_complete":terminal["output_complete"],"output_durable":terminal["output_durable"],"source_guards_pass":True,
 "actual_changed_file_count":195,"prior_changed_file_count":194,
 "changed_from_source51_paths":complete["changed_from_source51_paths"],
 "before_existing_repo_leaf_not_in_prior_changed_manifest":True,
 "source51_original_changed_manifest_rows_unchanged":True,"dependency_inputs_changed_paths":[],
 "source_before_commit":C51,"source_before_tree":T51,"native_git_head":complete["native_git_head"],
 "created_commit_checkout_claimed":False,"rust_executed":False,"bazel_lock_update_executed":False,"fix_fmt_executed":False,
 "three_original_git_exit_codes":[0,0,0],"complete":source52_member(complete_path),
 "source_postguard":source52_member(post_path),"terminal":source52_member(terminal_path)}
actual_manifest=source52_member(source_path)
registration=source52_member(B/"source52-preparation/ROOT-APPLY-INPUT-FREEZE.json")

old_scope_doc=load(R/"history/source51-scope-preparation/SCOPE.json")
scope=copy.deepcopy(S["current_source"]["scope"])
scope.update(changed_source_paths=195,rust_paths=181,other_paths=14,actual_source_manifest=actual_manifest,
 native_apply_complete=apply52["complete"],native_apply_postguard=apply52["source_postguard"],
 derivation="All source51 194 manifest rows are unchanged; runtime.rs newly enters the changed manifest under existing codex-network-proxy. Fresh original r29 Cargo metadata has193members=193defaults; longest actual manifest directory prefix maps all181 Rust files to the same26 owners. No Cargo metadata or Rust was run by the report editor.",
 fresh_default_workspace_metadata_required_before_r29=False,current_cargo_metadata_executed_by_report_editor=False,
 fresh_source52_r29_metadata_independently_verified=True,fresh_metadata=F["r29"]["fresh_metadata"],
 fresh_scope=F["r29"]["fresh_scope"],fresh_owner_scope_audit=F["fresh_final_scope"]["audit"])
scope.pop("fresh_default_workspace_metadata_required_before_r27",None)
scope["workflow"]["immutable_url"]=scope["workflow"]["immutable_url"].replace(C51,C52)
owners=[]
for original in old_scope_doc["owners"]:
 paths=sorted(p for p in rows if p.endswith(".rs") and p.startswith(original["package_directory"]+"/")
              and not any(p.startswith(other["package_directory"]+"/") and len(other["package_directory"])>len(original["package_directory"]) for other in old_scope_doc["owners"]))
 owners.append({"package":original["package"],"package_directory":original["package_directory"],"rust_path_count":len(paths),"rust_paths":paths})
assert len(owners)==26 and sum(x["rust_path_count"] for x in owners)==181
assert {p for x in owners for p in x["rust_paths"]}=={p for p in rows if p.endswith(".rs")}
scope_doc={"schema":"hepta.source52-owner-scope-preparation.v1","status":"NOT_EXECUTED_PREPARATION_ONLY",
 "source_commit":C52,"source_tree":T52,"scope":scope,"owners":owners,
 "non_rust_paths":sorted(p for p in rows if not p.endswith(".rs")),
 "source51_to_source52_changes_dependency_or_ci_inputs":False,"expected_default_HEAD_formatter_selection":{"rust_files":181,"python_files":["scripts/run-nextest.py","scripts/test_run_nextest_helpers.py"]},
 "fresh_r29_metadata_members_and_owners_independently_verified":True,"fresh_final_scope":F["fresh_final_scope"],"fix_fmt_executed":False}
scope_rel="history/source52-scope-preparation/SCOPE.json"
out(N/scope_rel,scope_doc);scope_pin=report_ref(scope_rel)

r26dir=B/"native-validation-results/r26-failure-closed";strictdir=B/"native-validation-results/r26-strict-closed"
r26=copy.deepcopy(F["r26"])
r26.update(source_stage=51,packages=S["validation"]["gates"]["r24"]["packages"],test_execution_started=True,
 counts={"unique_test_results":1564,"passed":1562,"failed":2,"timed_out":0,"reported_skipped":3},
 python_counts={"executed":32,"passed":32,"reported_skipped":0},python_exit_code=0,strict_exit_code=0,
 tests_raw_exit_code=100,original_outer_exit_code=100,gate_pass=False,
 formal_closure=report_ref("native-evidence/r26-project-checkpoint/CLOSURE.json"),
 independent_readback=report_ref("native-evidence/r26-project-checkpoint/INDEPENDENT-READBACK.json"),
 original_member_mapping=report_ref("native-evidence/r26-project-checkpoint/ORIGINAL-MEMBER-MAPPING.json"),
 original_r24_three_nonpassing_now_pass=F["r26"]["old_r24_three_failures_now_pass"],
 current_source52_qualification_transferred=False,baseline_identity_set_used_as_filter=False)
for key,file in [("tests_receipt","native-source51-project-r26-tests-receipt.json"),("raw_process_result","native-source51-project-r26-tests-raw-process-result.json"),("tests_postguard","native-source51-project-r26-tests-source-post-verification.json")]:
 r26[key]=r26_member(r26dir/file)
r26["outer_terminal"]=r26_member(r26dir/"terminal-process-status.json")
r26["strict_receipt"]=r26_member(strictdir/"native-source51-project-r26-strict-receipt.json")
r26["full_log"]={"original_uncompressed":{k:F["r26"]["full_log"][k] for k in ("bytes","sha256","git_blob")},
 "artifact":r26_member(r26dir/"native-source51-project-r26-tests.log")}
r26["earlier_progress_snapshot"]=OLD_S["validation"]["gates"]["r26"]["closed_python_snapshot"]
r26["python_elapsed_seconds_including_fixtures"]=OLD_S["validation"]["gates"]["r26"]["python_elapsed_seconds_including_fixtures"]
r26["python_unittest_seconds"]=OLD_S["validation"]["gates"]["r26"]["python_unittest_seconds"]
r26["python_receipt"]=OLD_S["validation"]["gates"]["r26"]["python_receipt"]

unknown_counts={k:None for k in ("unique_test_results","passed","failed","timed_out","reported_skipped")}
f28=F["r28"]
r28={"source_stage":52,"source_commit":C52,"source_tree":T52,"state":f28["state"],
 "job_id":f28["job_id"],"idempotency_key":"cell-source52-project-r28-20261106-v1","outer_timeout_seconds":9600,
 "runner_sha256":"a7b64eb8ff8ec2b5bc75ae836e3ff423ce31ee86d5c4daf64b7543a8fa7aae9e",
 "last_observed_job_state":"succeeded","python_counts":{"executed":32,"passed":32,"reported_skipped":0},
 "python_exit_code":0,"python_effective_exit_code":0,"python_elapsed_seconds_including_fixtures":f28["elapsed_seconds_including_fixtures"],
 "python_unittest_seconds":f28["unittest_seconds"],"python_source_and_dual_lock_guards_pass":True,
 "strict_exit_code":f28["strict_exit_code"],"strict_effective_exit_code":f28.get("strict_effective_exit_code"),
 "strict_elapsed_seconds":f28.get("strict_elapsed_seconds"),"strict_source_and_dual_lock_guards_pass":f28.get("strict_source_and_dual_lock_postguard_pass"),
 "test_execution_started":True,"tests_raw_exit_code":0,"tests_effective_exit_code":0,"original_outer_exit_code":0,
 "counts":copy.deepcopy(f28["counts"]),"new_complete_project_gate_pass_claimed":True,"no_execution_restart":True,
 "tests_elapsed_seconds":f28["tests_elapsed_seconds"],"nextest_execution_seconds":f28["nextest_execution_seconds"],
 "natural_outer_durable_complete":True,"source_and_dual_lock_postguards_pass":True,
 "closed_complete_snapshot":f28["complete_snapshot"],"closed_originals":copy.deepcopy(f28["closed_originals"]),
 "independent_closed_gate_readback":f28["independent_readback"],
 "old_r26_two_failures_now_pass":copy.deepcopy(f28["old_r26_two_failures_now_pass"]),
 "original_r24_three_failures_remain_pass":copy.deepcopy(f28["old_r24_three_failures_still_pass"]),
 "baseline_identity_set_used_as_filter":False,"whole_workspace_qualification_transferred":False,
 "closed_python_snapshot":f28["snapshot"],"closed_strict_snapshot":f28.get("strict_snapshot"),
 "observed_prefix_not_a_full_tests_log":False}
r29=copy.deepcopy(F["r29"])
reconstruction={"identity":"NEW_SOURCE52_REPORTS_FROM_EXACT_CHECKPOINT5_SOURCE51_BYTES",
 "exact_previous_current_report_snapshot":F["prior_reports"],"exact_previous_current_report_commit":F["historical_artifact_commit"],
 "previous_report_bytes_preserved":True,"previous_current_fields_are_historical":True,
 "prior_recovery_history_preserved_in_previous_snapshot":True,"rust_or_training_rerun_for_document_update":False}
S["record_state"]="DRAFT_SOURCE52_R28_COMPLETE_PROJECT_PASS_R29_WORKSPACE_STARTED_NO_TERMINAL"
S["snapshot_boundary"]="Source52 apply-only closed0. Original r28 Python32/0skip, four-package strict and complete1564-test gate all closed raw/effective0 with natural outer0,195-path and dual-lock guards. Original full tests:1564PASS/0FAIL/0TIMEOUT/3reportedskip. Same-source r29 launched once; fresh metadata193members=193defaults and original no-p workspace command start are bound. This snapshot has no nextest-start or tests/outer terminal result; counts remain null. Source51 r26 failed100:1562PASS/2FAIL/0TIMEOUT/3reportedskip remains historical. No workspace/fixfmt/final CI or scientific adoption pass is transferred."
S["report_reconstruction"]=reconstruction
S["current_source"]={"stage":52,"commit":C52,"tree":T52,"parent_commit":C51,"state":"REGISTERED_GITDATA_AND_APPLIED_NATIVE_STAGED_TREE",
 "source_commit_mapping_is_tree_identity_not_checkout_claim":True,"source_identity":"SOURCE_IDENTITY.json",
 "scope":scope,"scope_preparation":scope_pin,"native_apply":apply52,"last_closed_native_applied_tree":T52,
 "last_closed_rust_gate_tree":T52,"last_closed_rust_gate_scope":"complete_four_owner_project_gate_not_workspace"}
S["publication"]["source52_created"]=True
g=S["validation"]["gates"]
g["r26"]=r26;g["r27"]["state"]="BLOCKED_NOT_STARTED_AFTER_R26_FAILURE"
g["r27"]["inert_template_is_historical_preparation"]=True
g["source52_apply"]=apply52;g["r28"]=r28;g["r29"]=r29
g["source50_bazel_lock_update"]["source52_inheritance_boundary"]="Only three reviewed non-build Rust leaves since source50 and unchanged dependency inputs/raw locks; source52 did not rerun lock update."
S["current_failures"]={"latest_complete_rust_gate":"r28","source_stage":52,"source_commit":C52,"source_tree":T52,
 "result":"NO_FAILURE_IN_COMPLETED_FOUR_OWNER_GATE_WORKSPACE_PENDING","ids":[],"original_full_log_readback":f28["complete_snapshot"],
 "historical_source51_r26_failures":{"source_commit":C51,"source_tree":T51,"original_exit":100,"ids":F["r26"]["actual_failures"],"readback":F["r26_facts"]},
 "original_r26_two_nonpassing_now_pass":copy.deepcopy(f28["old_r26_two_failures_now_pass"]),
 "previous_r24_three_nonpassing_all_pass_in_r26":F["r26"]["old_r24_three_failures_now_pass"],
 "registered_repair_stage":52,"repair_applied_but_rust_qualification_pending":False,"full_workspace_qualification_pending":True,
 "repair_paths":["codex-rs/network-proxy/src/runtime.rs"],
 "four_fixture_previous_results":F["r26"]["source52_four_fixture_original_r26_results"],
 "fixture_change":"Only four per-test initial NetworkProxyConfig values set the existing allow_local_binding=true; two actual r26 FAIL and two related r26 PASS fixtures.",
 "production_default_or_dns_guards_changed":False,"assertions_changed":False,"timeouts_changed":False,
 "dedicated_default_private_localhost_and_injected_dns_guard_tests_unchanged":True,
 "runtime_dns_answer_or_duration_or_timeout_measured":False,
 "source51_bwrap_probe_scope_retained":OLD_S["current_failures"]["bwrap_fixture"],
 "source52_complete_four_owner_gate_pass_claimed":True,"source52_complete_workspace_pass_claimed":False}
S["final_fix_fmt"].update(state="NOT_EXECUTED_PENDING_SOURCE52_COMPLETE_WORKSPACE",
 scope={"source_stage":52,"source_commit":C52,"source_tree":T52,"rust_owner_packages":26,"rust_paths":181,"other_paths":14,
 "default_HEAD_expected_python_paths":["scripts/run-nextest.py","scripts/test_run_nextest_helpers.py"],"prepared_scope":scope_pin},
 old_source51_finalizer_is_not_current_executable_authorization=True,
 prerequisites=["Retain source52 original Python32 and four-owner strict/full1564-test0/outer0 closure.","Pass same-source original default complete workspace with fresh metadata.","Bind final executor to actual native HEAD/tree, both locks and nonempty 181-Rust plus2-Python default formatter selection."])
S["adoption_blockers"][0]["requirement"]="Complete the same-source original default workspace. Source52 r28 original Python32 and four-owner strict/full1564 tests have passed; this narrower result does not establish workspace or scientific adoption qualification."
S["next_source_preparation"]={"state":"SOURCE52_APPLIED_R28_PROJECT_PASS_R29_WORKSPACE_STARTED_NO_TERMINAL",
 "source_stage":52,"source_commit":C52,"source_tree":T52,"parent_source_commit":C51,"parent_source_tree":T51,
 "delta_paths":["codex-rs/network-proxy/src/runtime.rs"],"dependency_inputs_changed_paths":[],
 "source_registration_snapshot":registration,"native_apply":apply52,
 "source50_lock_inherited_only_for_unchanged_dependency_inputs":True,"new_lock_update_executed":False,
 "r28":r28,"r29":r29,"r25_and_r27_not_executed":True,
 "historical_source51_report":F["prior_reports"],"historical_pending_fields_are_not_current":True}

I["state"]="SOURCE52_APPLIED_R28_COMPLETE_PROJECT_PASS_R29_STARTED_PRE_FINAL_FIX_FMT"
I["report_reconstruction"]=reconstruction
I["created_source_commits"]=copy.deepcopy(ledger["commits"]);I["created_source_commit_count"]=52
I["creation_records_exact_from_publication_ledger"]={**F["fixed_ledger"],
 "selection":["parents","merge_tree","commits","current_source_commit","current_source_tree"],
 "copied_without_reordering_or_invented_entries":True,"ledger_not_modified_by_report_editor":True,
 "created_blob_path_count_at_observation":185,"artifact_checkpoint_count_at_observation":5,
 "blob_count_is_snapshot_not_permanent_current_total":True,
 "snapshot_origin":"publication-recovery-prep/checkpoint5-publication-ledger-ready.json",
 "snapshot_scope":"Fixed exact52 source/185 binary-path/5 artifact-checkpoint observation; later registrations are not followed.",
 "current_attachment_total_claimed":False}
I.update(current_source_stage=52,current_source_commit=C52,current_source_tree=T52,current_source_parent_commit=C51,
 source_scope=scope,scope_preparation=scope_pin,current_source_native_apply=apply52,last_closed_native_tree=T52,
 last_closed_rust_gate_tree=T52,last_closed_rust_gate_scope="complete_four_owner_project_gate_not_workspace",
 current_source_validation_status="APPLY0_R28_PYTHON32_STRICT0_FULL1564PASS_OUTER0_R29_WORKSPACE_STARTED_NO_TERMINAL",
 closed_current_native_gates={"r28":r28},pending_native_gates={"r29":r29},historical_blocked_workspace_preparations=["r25","r27"],
 source52_registration_snapshot=registration)
I["checkpoint_bindings"].extend([
 {"gate":"r26","stage":51,"commit":C51,"tree":T51,"state":"TEST_EXECUTION_FAILED_TERMINAL","original_exit":100,
  "evidence":r26["formal_closure"],"independent_readback":r26["independent_readback"],"qualification_transferred":False},
 {"gate":"source52_apply","stage":52,"commit":C52,"tree":T52,"state":"APPLIED_STAGED_TREE_NO_RUST_QUALIFICATION","original_exit":0,
  "evidence":apply52["complete"],"terminal":apply52["terminal"],"qualification_transferred":False},
 {"gate":"r28","stage":52,"commit":C52,"tree":T52,"state":"COMPLETE_FOUR_OWNER_PROJECT_PASS","original_exit":0,
  "evidence":f28["complete_snapshot"],"independent_readback":f28["independent_readback"],"workspace_qualification_transferred":False}])
# Semantic/scientific sections are copied unchanged rather than rewritten.
for key in ["overall","taxonomy","source_inputs","implementation","science","historical_assets","source_compatibility","upstream_ci_history"]:
 assert S[key]==OLD_S[key],key
assert I["scientific_reference_source"]==OLD_I["scientific_reference_source"]
assert I["scientific_disposition"]==S["overall"]["scientific_disposition"]=="HOLD"
assert I["authority"]==S["overall"]["authority"]=="DENY_ALL"
for name,obj in [("STATUS.candidate.json",S),("SOURCE_IDENTITY.candidate.json",I)]:out(P/name,obj)
plan={"schema":"hepta.source52-report-candidate-plan.v1","state":"CANDIDATE_ONLY_NOT_ADOPTED",
 "historical_anchor":F["historical_artifact_commit"],"current_source_commit":C52,"current_source_tree":T52,
 "pending_formal_attachments":pending,"main_files_unchanged":True,"scientific_and_contract_blocks_unchanged":True,
 "source52_scoped_fix_not_executed":True,"r28_tests_and_outer_terminal":0,
 "outputs":[{"path":n,**pin((P/n).read_bytes())} for n in ["STATUS.candidate.json","SOURCE_IDENTITY.candidate.json"]]}
out(P/"JSON-CANDIDATE-READBACK.json",plan)
for name in ["README.md","STATUS.json","SOURCE_IDENTITY.json"]:assert (R/name).read_bytes()==(P/"references"/name).read_bytes()
print(json.dumps({"outputs":plan["outputs"],"pending_formal_attachment_references":len(pending),"main_unchanged":True}))

