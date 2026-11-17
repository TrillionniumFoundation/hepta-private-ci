"""Freeze posthoc runner inputs without importing or running that runner."""
import ast, hashlib, json, time
from pathlib import Path
O=Path(__file__).resolve().parent
ROOT=O.parents[1]
B=ROOT/"research-final-evidence-02"
runner=O/"run_posthoc_readonly.py"
tree=ast.parse(runner.read_text())
def literal(name):
    return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
paths,pins,qualification=literal("PATHS"),literal("PINS"),literal("QUALIFICATION")
bindings={}
for name,rel in paths.items():
    path=ROOT/rel if rel.startswith("operations/") else B/rel
    if path.resolve()!=path or not path.is_file() or path.is_symlink(): raise ValueError("regular input required")
    raw=path.read_bytes(); sha=hashlib.sha256(raw).hexdigest()
    if name in pins and sha!=pins[name]: raise ValueError("input identity differs: "+name)
    bindings[name]={"path":rel,"sha256":sha,"bytes":len(raw)}
original=(B/paths["original_source"]).read_text()
candidate=(ROOT/paths["candidate_source"]).read_text()
fix=json.loads((O/"POSTHOC_FIX_MANIFEST.json").read_text())
if candidate!=original.replace(fix["replacement"]["old"],fix["replacement"]["new"]): raise ValueError("patch differs")
regression=json.loads((O/"REGRESSION.json").read_text())
if not regression["passed"] or regression["tests_run"]!=6: raise ValueError("targeted regressions not passed")
manifest={"schema":"hepta.diagnostic-order-posthoc-manifest.v1","status":"PREPARED_NOT_EXECUTED",
 "posthoc":True,"created_at_ns":time.time_ns(),
 "workspace":"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a",
 "output":"/dev/shm/hepta-cell-experiments-v3-20261116-0c078a/research-diagnostic-posthoc-02",
 "bindings":bindings,"rules_validation_source":"actual original source SHA, not derived candidate SHA",
 "original_main_called":False,"original_rules_modified":False,
 "new_source_does_not_inherit_prefit_freeze":True,"model_calls_authorized":0,"verifier_calls_authorized":0,
 "requires_root_review_before_full_readout":True,"outer_runner_validation":"AST parse and immutable binding check only; not executed",
 **qualification}
target=O/"POSTHOC_RUN_MANIFEST.json"
with target.open("x") as f: json.dump(manifest,f,ensure_ascii=False,sort_keys=True,indent=2); f.write("\n")
summary={"manifest_sha256":hashlib.sha256(target.read_bytes()).hexdigest(),
 "runner_sha256":bindings["runner"]["sha256"],
 "review_sha256":hashlib.sha256((ROOT/"operations/research02-diagnostic-interface-review-01/REVIEW.md").read_bytes()).hexdigest(),
 "fix_source_sha256":bindings["candidate_source"]["sha256"],"status":"PREPARED_NOT_EXECUTED"}
print(json.dumps(summary))
