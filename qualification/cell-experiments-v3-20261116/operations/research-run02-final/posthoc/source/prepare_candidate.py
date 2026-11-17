"""Prepare a create-only posthoc candidate; never run the diagnostic."""
import ast, difflib, hashlib, json
from pathlib import Path
ROOT=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a")
B=ROOT/"research-final-evidence-02"
O=ROOT/"operations/research02-diagnostic-order-fix-01"
S=B/"research-diagnostic-v1-source-02/qwen_research_diagnostic_v1.py"
original=S.read_text()
old_sha=hashlib.sha256(S.read_bytes()).hexdigest()
if old_sha!="28d82e170ab0720fb6b453275a80b4bf1eebc1e987ed1ae3bd935bb00a77a071": raise ValueError("original source mismatch")
old='''    context = contract.load_context(WORKSPACE, source, baseline)
    require(reader.read(freeze["inputs_path"], freeze["inputs_sha256"]) == context
            and freeze["parent_digest"] == digest(context["parent"])
            and freeze["parent_readiness_digest"] == digest(context["readiness"])
            and freeze["parent_successful_A_tasks"] == context["gate"]["successful_A_tasks"]
            and freeze["reference_admission_digest"] == digest(context["research_admission"])
            and freeze["runtime"] == context["runtime"],
            "operation INPUTS or measured baseline differs")
'''
new='''    context = contract.load_context(WORKSPACE, source, baseline)
    recorded_context = reader.read(freeze["inputs_path"], freeze["inputs_sha256"])
    require(recorded_context == context
            and freeze["parent_digest"] == digest(context["parent"])
            and freeze["parent_readiness_digest"] == digest(context["readiness"])
            and freeze["parent_successful_A_tasks"] == context["gate"]["successful_A_tasks"]
            and freeze["reference_admission_digest"] == digest(context["research_admission"])
            and freeze["runtime"] == context["runtime"],
            "operation INPUTS or measured baseline differs")
    context = recorded_context
'''
if original.count(old)!=1: raise ValueError("replacement not unique")
candidate=original.replace(old,new)
a,b=ast.parse(original),ast.parse(candidate)
unchanged=[]
for x,y in zip(a.body,b.body):
    if isinstance(x,ast.FunctionDef) and x.name=="diagnose": continue
    if ast.dump(x)!=ast.dump(y): raise ValueError("unexpected AST change")
    if isinstance(x,ast.FunctionDef): unchanged.append(x.name)
if len(a.body)!=len(b.body): raise ValueError("module layout changed")
paths={
 "original_diagnostic":"research-diagnostic-02/DIAGNOSTIC.json",
 "original_rules":"research-diagnostic-v1-source-02/QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json",
 "operation_freeze":"research-sft-02/FREEZE.json",
 "recorded_inputs":"research-sft-02/INPUTS.json"}
bindings={k:{"path":str(B/p),"sha256":hashlib.sha256((B/p).read_bytes()).hexdigest()} for k,p in paths.items()}
expected={"original_diagnostic":"662f575d3f01705fb13cb6e168ad5d7069a8ddcc81e484f0c515b63afd65236b",
 "original_rules":"f50ced9146611fc07c4638a35f204e94f1ebf0b5e6c4ab70ac9667095135c1bc",
 "recorded_inputs":"691945696e7dad9ee0f3023617edf5ca0f787850c16f2623c08d14bc6cfbeaf3"}
if any(bindings[k]["sha256"]!=v for k,v in expected.items()): raise ValueError("original input binding changed")
name="qwen_research_diagnostic_v1_order_fixed.py"
with (O/name).open("x") as f: f.write(candidate)
diff="".join(difflib.unified_diff(original.splitlines(True),candidate.splitlines(True),fromfile="original/qwen_research_diagnostic_v1.py",tofile="posthoc/"+name))
with (O/"ORDER_FIX.diff").open("x") as f: f.write(diff)
manifest={"schema":"hepta.diagnostic-order-fix-candidate.v1","posthoc":True,
 "original_source":{"path":str(S),"sha256":old_sha},
 "candidate_source":{"path":str(O/name),"sha256":hashlib.sha256(candidate.encode()).hexdigest()},
 "input_bindings":bindings,"unchanged_function_asts":unchanged,
 "replacement":{"old":old,"new":new},"diagnostic_rerun":False,"original_rules_modified":False,
 "main_cli_not_authorized":True,"root_binding_review_required_before_recompute":True,
 "scientific_confirmation_qualified":False,"native_cell_adoption":False,"circuit_qualified":False,
 "proof_of_useful_work_eligible":False,"candidate_selected":None}
with (O/"POSTHOC_FIX_MANIFEST.json").open("x") as f: json.dump(manifest,f,ensure_ascii=False,indent=2,sort_keys=True); f.write("\n")
print(json.dumps({"candidate_sha256":manifest["candidate_source"]["sha256"],"manifest_sha256":hashlib.sha256((O/"POSTHOC_FIX_MANIFEST.json").read_bytes()).hexdigest(),"diff_sha256":hashlib.sha256(diff.encode()).hexdigest(),"unchanged_functions":len(unchanged)}))
