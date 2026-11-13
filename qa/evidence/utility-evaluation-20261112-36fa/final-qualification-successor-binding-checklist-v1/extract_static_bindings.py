#!/usr/bin/env python3
"""Pure frozen-text/AST extraction; does not import or execute any runner."""
import ast
import hashlib
import json
from pathlib import Path
import textwrap
import tomllib

BASE = Path(__file__).resolve().parent
INPUT = BASE / "inputs"
PINS = {
 "SOURCE_GATES_5118.py":"51181866cbbb6e0176aab04117efffa8b6792b31",
 "PLAN_3AEF.json":"3aefbc71d69d8014eed9e5a18269bbcc866a7583",
 "NATIVE_WRAPPER_DE3.py":"de3e9dc5e7eb30f47929f9e1ba9f460035a94fae",
 "NATIVE_DRIVER_B92.py":"b92ddded4fce78aeb076d022471c62bf81ce2e4f",
 "SOURCE_WRAPPER_8607.py":"8607fa4bf00fc8cf535849de04d1eb6ff29429b3",
 "WORKFLOW_D256.yml":"c0012652889b0cca409b27f87bfdc74b234c0fbe",
 "NEXTEST_ORIGINAL.toml":"0904c42a41594d3ae4dc6f196e64f35f0b85bd2c",
 "RUN_NEXTEST_ORIGINAL.py":"1ed63abe84267b320cbfb0123a70aac5507f4595",
 "JUSTFILE.original":"a215a76cf407ace9715bca39c20497014e7dd4dc",
 "HISTORICAL_SOURCE_REQUEST.json":"eae8d46956ac3afd89bf18b30d69997cbe925788",
}
def identity(raw):
 return {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
         "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}
def read_pinned(path,expected):
 raw=path.read_bytes(); seen=identity(raw)
 assert seen["git_blob"]==expected,(str(path),seen)
 return raw.decode(),seen
text={}; input_pins={}
for name,expected in PINS.items():
 text[name],input_pins[name]=read_pinned(INPUT/name,expected)
plan=json.loads(text["PLAN_3AEF.json"])
phases={x["id"]:x for x in plan["phases"]}
order=["eval-lib","native-toolchain","helper-build","helper-verify-before","focused",
 "ordinary","root-setup","root","all-native-driver","helper-verify-after","root-cleanup",
 "source-closure","caller-self-test","caller-verify"]
assert list(phases)==order and len(phases)==14
budgets={"eval-lib":3600,"native-toolchain":120,"helper-build":3600,
 "helper-verify-before":120,"focused":7200,"ordinary":7200,"root-setup":60,"root":7200,
 "helper-verify-after":120,"root-cleanup":60,"source-closure":600,"caller-self-test":300,
 "caller-verify":4800}
assert all(phases[k]["timeout_seconds"]==v for k,v in budgets.items())
assert phases["focused"]["outer_driver_budget_seconds"]==12000
assert phases["all-native-driver"]["outer_driver_budget_seconds"]==21000
trees={name:ast.parse(raw) for name,raw in text.items() if name.endswith(".py")}
def assigned(tree,name):
 found=[]
 for n in ast.walk(tree):
  if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name:
   try: found.append(ast.literal_eval(n.value))
   except (ValueError,TypeError): pass
 assert len(found)==1,(name,len(found))
 return found[0]
def function(tree,name):
 found=[n for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name]
 assert len(found)==1
 return found[0]
def call(tree,func,first):
 found=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
  and n.func.id==func and n.args and isinstance(n.args[0],ast.Constant) and n.args[0].value==first]
 assert len(found)==1,(func,first,len(found))
 return found[0]
def dump(n): return ast.dump(n,include_attributes=False)
def require_fragment(raw,fragment): assert fragment in raw,fragment

marker='          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
workflow_driver=textwrap.dedent(text["WORKFLOW_D256.yml"].split(marker,1)[1].split("          PY\n",1)[0])
workflow_ast=ast.parse(workflow_driver)
parents=assigned(workflow_ast,"parents")
packages=assigned(workflow_ast,"packages")
expected_packages=["-p","codex-hepta-agentd","-p","codex-hepta-learning-ledger",
 "-p","codex-hepta-learning-artifacts","-p","codex-hepta-intelligence-eval","-p","codex-hepta-neuron"]
assert packages==expected_packages and len(parents)==len(set(parents))==48
assert parents[:33]==phases["root"]["prepared_parent_names"]
assert len([p for p in parents[39:] if "::root_initial_custody::" in p])==9
root_expression=" | ".join("test(="+name+")" for name in parents)
b92=trees["NATIVE_DRIVER_B92.py"]
filters=assigned(b92,"filters")
assert filters==phases["focused"]["filter_tokens_exact"]
focus_expression=" | ".join("test("+name+")" for name in filters)
assert focus_expression==phases["focused"]["command"][phases["focused"]["command"].index("-E")+1]
root_expr_ast=ast.parse("' | '.join('test(=' + name + ')' for name in parents)",mode="eval").body
focus_expr_ast=ast.parse("' | '.join('test(' + name + ')' for name in filters)",mode="eval").body
def value(n):
 if isinstance(n,ast.Constant): return n.value
 if isinstance(n,ast.Starred) and isinstance(n.value,ast.Name) and n.value.id=="packages": return packages
 if dump(n)==dump(root_expr_ast): return root_expression
 if dump(n)==dump(focus_expr_ast): return focus_expression
 raise AssertionError(ast.unparse(n))
def arguments(n):
 assert isinstance(n,ast.List)
 result=[]
 for item in n.elts:
  v=value(item)
  if isinstance(item,ast.Starred): result.extend(v)
  else: result.append(v)
 return result
root_args=arguments(call(b92,"test","root").args[1])
ordinary_args=arguments(call(b92,"test","ordinary").args[1])
focused_args=arguments(call(b92,"test","focused").args[1])
test_fn=function(b92,"test")
command=next(n.value for n in test_fn.body if isinstance(n,ast.Assign)
 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=="command")
split=next(i for i,n in enumerate(command.elts) if isinstance(n,ast.Constant) and n.value=="--")
timeout_index=next(i for i,n in enumerate(command.elts) if isinstance(n,ast.Constant) and n.value=="--timeout-seconds")
assert ast.literal_eval(command.elts[timeout_index+1])=="7200"
def expanded(args):
 out=[]
 for n in command.elts[split+1:]:
  if isinstance(n,ast.Starred):
   assert isinstance(n.value,ast.Name) and n.value.id=="arguments"
   out.extend(args)
  else: out.append(ast.literal_eval(n))
 return out
assert expanded(ordinary_args)==phases["ordinary"]["command"]
assert expanded(focused_args)==phases["focused"]["command"]
root_expected=[root_expression if x=="$"+"{EXACT_FINAL_WORKFLOW_PARENT_EXPRESSION}" else x for x in phases["root"]["command_payload"]]
assert expanded(root_args)==root_expected
assert root_args[root_args.index("--run-ignored")+1]=="only"
assert root_args[root_args.index("--test-threads")+1]=="1"
assert all(expanded(a)[expanded(a).index("--retries")+1]=="0" for a in (root_args,ordinary_args,focused_args))
eval_calls=[n for n in ast.walk(trees["NATIVE_WRAPPER_DE3.py"]) if isinstance(n,ast.Call)
 and isinstance(n.func,ast.Name) and n.func.id=="run" and len(n.args)>1 and isinstance(n.args[1],ast.List)]
assert len(eval_calls)==1
assert ast.literal_eval(eval_calls[0].args[1])==phases["eval-lib"]["command"]
assert {kw.arg:ast.literal_eval(kw.value) for kw in eval_calls[0].keywords}=={"minimum_tests":1,"timeout_seconds":3600}
assert assigned(trees["NATIVE_WRAPPER_DE3.py"],"frozen_four")==phases["eval-lib"]["required_coverage"]["required_four"]
suite_loop=next(n for n in ast.walk(trees["NATIVE_WRAPPER_DE3.py"]) if isinstance(n,ast.For) and isinstance(n.target,ast.Tuple)
 and [e.id for e in n.target.elts if isinstance(e,ast.Name)]==["suite","budget"])
assert ast.literal_eval(suite_loop.iter)==[("focused",12000),("all",21000)]
gates=assigned(trees["SOURCE_GATES_5118.py"],"GATES")
assert gates==(
 ("source-closure",600,["python3","-m","unittest","discover","-s","qa/b4-no-bypass","-p","*source_closure.py","-v"]),
 ("self-test",300,["python3","scripts/verify_hepta_callers.py","self-test"]),
 ("verify",4800,["python3","scripts/verify_hepta_callers.py","verify"]))
assert json.loads(text["HISTORICAL_SOURCE_REQUEST.json"])["timeout_seconds"]==7200
interfaces_path=Path("/tmp/hepta-36fa-complete-new-source-handoff-hold-v1/ORIGINAL_RUNNER_INTERFACES.json")
interfaces_raw=interfaces_path.read_bytes(); interfaces=json.loads(interfaces_raw)
assert interfaces["budgets_seconds"]["source_outer"]==7200
assert interfaces["budgets_seconds"]["native_outer"]==45000
assert interfaces["original_qualification_plan"]["git_blob"]==PINS["PLAN_3AEF.json"]
nextest=tomllib.loads(text["NEXTEST_ORIGINAL.toml"])
assert nextest["profile"]["default"]["slow-timeout"]=={"period":"30s","terminate-after":2}
assert nextest["profile"]["default"]["retries"]==1
ledger_overrides=[x for x in nextest["profile"]["default"]["overrides"] if "package(codex-hepta-learning-ledger)" in x["filter"]]
assert [x["slow-timeout"] for x in ledger_overrides]==[{"period":"30s","terminate-after":6},{"period":"30s","terminate-after":20}]
require_fragment(text["JUSTFILE.original"],'rust_min_stack := "8388608"')
require_fragment(text["JUSTFILE.original"],'RUST_MIN_STACK={{ rust_min_stack }} NEXTEST_PROFILE=local')
assert text["RUN_NEXTEST_ORIGINAL.py"].count('["cargo", "nextest", "run", "--no-fail-fast",')==2
assert nextest["profile"]["local"]["junit"]["path"]=="junit.xml"
fragments={
 "SOURCE_GATES_5118.py":['["git", "clone", "--shared", "--no-checkout", "--no-hardlinks",',
  'path.chmod(stat.S_IMODE(info.st_mode) & ~0o222)',
  'if name == "verify" and summaries[-1]["status"] != "passed":',
  'if summaries and summaries[-1]["source_changed"]:',
  '"actual_A_B_C_qualification": False','os.environ["GIT_OPTIONAL_LOCKS"] = "0"'],
 "SOURCE_WRAPPER_8607.py":["result['driver_returncode'] = guard.inventory.main()",
  "if result['driver_returncode'] == 0:",
  "result['status'] = 'unknown' if result['driver_returncode'] is None else 'failed'",
  "result['actual_origin_full_physical_observation'] = guard.finish()"],
 "NATIVE_DRIVER_B92.py":["original_constants[name] = ast.literal_eval(node.value)",
  "if sorted(observed) != sorted(parents):","if not coverage['exact_pass_coverage']:",
  "'--run-ignored', 'only'","'--test-threads', '1'","if root_setup_attempted:",
  "timeout_seconds=60","source bytes or identity changed during native observations"],
 "NATIVE_WRAPPER_DE3.py":['for suite,budget in [("focused",12000),("all",21000)]',
  'guard.before_native_stage("eval-lib")','all_fresh_junit_names','no historical-count gate',
  'unknown_missing_before','guard.m.set_alarm(300)']}
for name,items in fragments.items():
 for item in items: require_fragment(text[name],item)
prior_path=Path("/tmp/hepta-36fa-coordinator-f905-registration-independent-peer-v1/FROZEN_REGISTRATION_BYTE_AND_SCOPE_REVIEW.json")
prior_text,prior_pin=read_pinned(prior_path,"b84c6853a31996e21df55d2f9239e4e29387e0fd")
prior=json.loads(prior_text)
assert parents==prior["workflow_new_parents"] and parents[:39]==prior["workflow_old_parents"]
graph_path=Path("/tmp/hepta-36fa-coordinator-final-candidate-graph-v1/CANDIDATE_FILE_GRAPH.json")
graph_text,graph_pin=read_pinned(graph_path,"097282896b5881614498faf2231e4c8c0da393c3")
graph=json.loads(graph_text)
assert graph["tree"]=="a489b394666b8141840275128a780605b024cde0"
files={r["path"]:r for r in graph["files"]}
runtime_paths={
 "codex-rs/.config/nextest.toml":PINS["NEXTEST_ORIGINAL.toml"],
 "scripts/run-nextest.py":PINS["RUN_NEXTEST_ORIGINAL.py"],"justfile":PINS["JUSTFILE.original"],
 "scripts/hepta_ci_exec.py":"c9434b3a4afb31f80e323d543936386a2fa738de",
 "scripts/hepta_ci_junit.py":"683626df091bdfe160a8965fdc92bf40f5783cf8",
 "scripts/hepta_cell_test_helpers.py":"f5b702a55b44c081c6d8f5556da3a2152a33eec3",
 "scripts/hepta_c_observer_coverage.py":"49a99d7093dbabe467b2dc5053a597f4df320078",
 ".github/workflows/hepta-daemon-learning-native.yml":PINS["WORKFLOW_D256.yml"]}
assert all(files[p]["git_blob"]==sha for p,sha in runtime_paths.items())
fence_paths=[".github/blob-size-allowlist.txt",".github/workflows/hepta-daemon-learning-native.yml",
 "CALLERS.toml","qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json",
 "qa/b4-no-bypass/test_evaluated_published_read_source_closure.py",
 "qa/b4-no-bypass/test_resident_provider_local_read_source_closure.py",
 "qa/b4-no-bypass/test_resident_root_source_closure.py"]
definitions={n:{"top_level_functions":sum(isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) for x in t.body),
 "all_functions_including_nested":sum(isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) for x in ast.walk(t)),
 "top_level_classes":sum(isinstance(x,ast.ClassDef) for x in t.body)} for n,t in trees.items()}
out={
 "format":"hepta-final-qualification-successor-binding-static-extraction-v1",
 "status":"FROZEN_TEXT_AND_AST_RELATIONS_MATCH; ACTUAL_FINAL_SOURCE_NOT_BOUND",
 "scope":"Pure stdlib JSON/TOML/AST/hash inspection; no imported runner, subprocess, test, formatter, source/ref mutation or H.",
 "original_inputs":input_pins,"original_interfaces_reused":identity(interfaces_raw),
 "prior_registration_proof_reused":prior_pin,"prepared_graph":graph_pin,"prepared_tree":graph["tree"],
 "definitions":definitions,"fourteen_phase_ids":order,"phase_budgets_seconds":budgets,
 "outer_budgets_seconds":{"source":7200,"native":45000,"focused_driver":12000,"all_driver":21000},
 "phase_contracts_reused_from_original_plan":plan["phases"],"workflow_root_parent_count":48,
 "workflow_root_parents":parents,"original33_equal_prefix":True,"previous39_equal_prefix":True,
 "added9":parents[39:],"root_exact_expression":root_expression,"ordinary_packages_argv":packages,
 "actual_static_native_command_payloads":{"eval_lib":phases["eval-lib"]["command"],
 "focused":expanded(focused_args),"ordinary":expanded(ordinary_args),"root":expanded(root_args)},
 "source_gate_tuples":gates,
 "runtime":{"rust_min_stack_bytes":8388608,"nextest_profile":"local","no_fail_fast":True,
 "explicit_command_retries":0,"default_config_retries":1,
 "default_slow_timeout":nextest["profile"]["default"]["slow-timeout"],
 "ledger_existing_overrides":ledger_overrides,
 "note":"Unchanged config default retries=1 is overridden by exact --retries 0 on every selected test invocation."},
 "current_prepared_runtime_source_rows":{p:files[p] for p in runtime_paths},
 "reserved_nonrust_paths":{p:files[p] for p in fence_paths},
 "prepared_nonrust_counts":{"boundaries":633,"protected_rows":442,"original_boundary_prefix":621,
 "original_protected_rows":437,"unchanged_original_protected_rows":414,"changed_original_protected_rows":23,
 "changed_original_scope_spans":80,"provider_paths":45,"provider_scopes":288,"provider_original_paths":41,
 "provider_original_scopes":264,"ordinary_scopes":34,"ordinary_critical_literals":17,"qa_files":64,
 "old_qa_methods":604,"old_methods_identical":602,"explicit_old_method_migrations":2,"new_qa_methods":3,
 "prepared_qa_methods":607,"workflow_root_parents":48,
 "meaning":"Reused independently reviewed pre-maintenance reservation only, not final inventory or QA results."},
 "unknown_final_bindings":{"postmaintenance_source":None,"formatter_changed_paths":None,
 "post_final_nonrust_source":None,"canonical_commit":None,"canonical_tree":None,
 "clean_complete_inventory":None,"native_compact_inventory":None,"source_gate_results":None,"native_results":None},
 "project_execution_counts":{"H":0,"source_gates":0,"QA":0,"Rust":0,"formatter":0,"source_ref_writes":0}}
raw=(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
target=BASE/"STATIC_TEMPLATE_BINDINGS.json"
with target.open("xb") as f: f.write(raw)
print(json.dumps({"report":str(target),**identity(raw),"root_parents":48,"phases":14,"state":out["status"]}))
