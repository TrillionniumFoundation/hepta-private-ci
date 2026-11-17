"""Read only JSON and source text; do not import experiment modules."""
import ast, hashlib, json
from pathlib import Path
B=Path("/Users/qianqi/work/hepta-cell-experiments-v3-20261116-0c078a/research-final-evidence-02")
O=B.parent/"operations/research02-diagnostic-interface-review-01"
files={}
def read(p):
    p=B/p
    if p.resolve()!=p or not p.is_file() or any(x in ("C","confirmation") for x in p.parts): raise ValueError("path")
    raw=p.read_bytes(); files[str(p.relative_to(B))]={"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)}
    return json.loads(raw) if p.suffix==".json" else raw.decode()
def digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
D="research-diagnostic-v1-source-02/"
diag=read("research-diagnostic-02/DIAGNOSTIC.json")
read(D+"qwen_research_diagnostic_v1.py")
rules=read(D+"QWEN_RESEARCH_DIAGNOSTIC_FREEZE_02.json")
freeze=read("research-sft-02/FREEZE.json"); inp=read("research-sft-02/INPUTS.json")
for n,s in freeze["research_inventory"].items():
    read("research-sft-v1-source/"+n)
    if files["research-sft-v1-source/"+n]["sha256"]!=s: raise ValueError("producer hash")
helper=read("e1e2-operation-helpers-04/qwen_development_inputs_v3.py")
read("e1e2-operation-helpers-04/qwen_development_io_v3.py")
nodes=[n for n in ast.walk(ast.parse(helper)) if isinstance(n,ast.Assign) and isinstance(n.value,ast.Dict) and any(isinstance(t,ast.Name) and t.id=="panels" for t in n.targets)]
order=[ast.literal_eval(k) for k in nodes[0].value.keys]; panels=inp["panels"]; rebuilt={k:panels[k] for k in order}
keys=lambda p:[(k,x["task_id"]) for k,v in p.items() for x in v]
result={"literal_panel_order":order,"literal_line":nodes[0].lineno,"saved_panel_order":list(panels),"dict_equal":panels==rebuilt,"canonical_digest_equal":digest(panels)==digest(rebuilt),"binding_errors":diag["binding_errors"],"arms":{}}
for arm in ("parent","retrieval","final_answer","trajectory","shadow_correction","controlled_correction"):
    obs={"diagnostic":diag["fixed_expert_slots"].get(arm) or diag["frozen_baselines"].get(arm) or diag["separate_shadow_arm"]}
    for phase in ("primary","cold"):
        prefix="research-sft-02/workers/"+arm+"-"+phase
        e=read(prefix+"/evaluation/EVALUATION.json"); w=read(prefix+"/RESULT.json"); p=read(prefix+"/evaluation/ORIGINAL_PANELS.json")
        ex=read("research-sft-02/processes/"+arm+"-"+phase+"/EXIT.json")
        got=[(x["panel"],x["task_id"]) for x in e["rows"]]
        obs[phase]={"evaluation_identity":files[prefix+"/evaluation/EVALUATION.json"],"row_keys":got,"saved_order_matches":got==keys(panels),"rebuilt_order_matches":got==keys(rebuilt),"coverage_equal":sorted(got)==sorted(keys(rebuilt)),"keys_unique":len(got)==len(set(got)),"panels_equal":p==panels==rebuilt,"digest_matches":digest(p)==e["original_panels_digest"],"embedded_equal":w["evaluation"]==e,"exit_zero":ex["exit_code"]==0 and ex["timed_out"] is False,"by_panel":e["by_panel"]}
    result["arms"][arm]=obs
result.update(files=files,scope="stdlib JSON/AST inspection; no model/test/verifier/C or diagnostic rerun",later_gates_not_revalidated=True)
with (O/"INTERFACE_EVIDENCE.json").open("x") as f: json.dump(result,f,ensure_ascii=False,indent=2,sort_keys=True); f.write("\n")
print(json.dumps({"files_read":len(files),"output":str(O/"INTERFACE_EVIDENCE.json"),"sha256":hashlib.sha256((O/"INTERFACE_EVIDENCE.json").read_bytes()).hexdigest(),"panel_orders":[order,list(panels)]}))
