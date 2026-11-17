"""Targeted stdlib regression using extracted unchanged guards, not a diagnostic rerun."""
import ast, copy, hashlib, json, re, sys, unittest
from pathlib import Path
from types import SimpleNamespace
O=Path(__file__).resolve().parent
M=json.loads((O/"POSTHOC_FIX_MANIFEST.json").read_text())
def read_bound(item):
    raw=Path(item["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=item["sha256"]: raise ValueError("bound bytes changed")
    return raw.decode()
old=read_bound(M["original_source"]); new=read_bound(M["candidate_source"])
for v in M["input_bindings"].values(): read_bound(v)
trees=[ast.parse(old),ast.parse(new)]
def fn(tree,name):
    return next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
def bind_function(tree):
    body=fn(tree,"diagnose").body
    start=next(i for i,n in enumerate(body) if isinstance(n,ast.Assign)
        and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=="load_context")
    end=next(i for i,n in enumerate(body[start:],start) if isinstance(n,ast.Assign)
        and any(isinstance(t,ast.Name) and t.id=="parent_outcomes" for t in n.targets))
    f=ast.parse("def bind_context(contract, reader, freeze, WORKSPACE, source, baseline):\n pass").body[0]
    f.body=copy.deepcopy(body[start:end])+[ast.Return(ast.Name(id="context",ctx=ast.Load()))]
    return f
scope=next(ast.literal_eval(n.value) for n in trees[0].body if isinstance(n,ast.Assign)
    and any(isinstance(t,ast.Name) and t.id=="SCOPE" for t in n.targets))
def namespace(tree):
    names=("require","canonical","digest","sealed","scope","cold_identity")
    functions=[copy.deepcopy(fn(tree,n)) for n in names]
    evaluation=copy.deepcopy(fn(tree,"evaluation"))
    end=next(i for i,n in enumerate(evaluation.body) if any(isinstance(x,ast.Constant)
        and x.value=="evaluation task order or coverage differs" for x in ast.walk(n)))
    evaluation.name="evaluation_prefix"; evaluation.body=evaluation.body[:end+1]+[ast.Return(ast.Constant(True))]
    module=ast.fix_missing_locations(ast.Module(body=functions+[evaluation,bind_function(tree)],type_ignores=[]))
    ns={"json":json,"hashlib":hashlib,"re":re,"SCOPE":scope}
    exec(compile(module,"<extracted-frozen-guards>","exec"),ns)
    return ns
N0,N1=namespace(trees[0]),namespace(trees[1])
helper=Path(M["input_bindings"]["recorded_inputs"]["path"]).parents[1]/"e1e2-operation-helpers-04/qwen_development_io_v3.py"
if hashlib.sha256(helper.read_bytes()).hexdigest()!="4116cfc058cfbec9bdca4845e409d0c1c2071d9da9faa4b56f9d8aa6df5a2060": raise ValueError("helper hash")
H={"json":json}
exec(compile(ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(fn(ast.parse(helper.read_text()),"canonical"))],type_ignores=[])),"<producer-canonical>","exec"),H)
class Reader:
    def __init__(self,items): self.items=items
    def read(self,p,expected=None):
        raw=self.items[str(p)]
        if expected is not None and hashlib.sha256(raw).hexdigest()!=expected: raise ValueError("frozen input hash mismatch")
        return json.loads(raw)
def fixture():
    p={"B_exposed":[{"task_id":"B1"}],"A_retention":[{"task_id":"A1"},{"task_id":"A2"}]}
    generation={"max_new_tokens":384}; parent={"fixture":"parent"}
    c={"panels":p,"retrieval_panels":copy.deepcopy(p),"parent":parent,"readiness":{"fixture":"readiness"},
       "gate":{"successful_A_tasks":0},"research_admission":{"fixture":"admission"},
       "runtime":{"fixture":"runtime"},"generation_digest":N1["digest"](generation)}
    raw=H["canonical"](c)
    f={"inputs_path":"INPUTS.json","inputs_sha256":hashlib.sha256(raw).hexdigest(),
       "parent_digest":N1["digest"](parent),"parent_readiness_digest":N1["digest"](c["readiness"]),
       "parent_successful_A_tasks":0,"reference_admission_digest":N1["digest"](c["research_admission"]),"runtime":c["runtime"]}
    saved=json.loads(raw)
    r={"schema":"hepta.research-sft-evaluation.v1","status":"COMPLETE","arm":"final_answer","phase":"primary",
       "model_digest":N1["digest"](parent),"generation_digest":c["generation_digest"],"maximum_attempts":2,
       "max_new_tokens":384,"original_panels_digest":N1["digest"](p),"shown_panels_digest":N1["digest"](p),
       "pid":71,"rows":[{"panel":k,"task_id":t["task_id"]} for k,rs in saved["panels"].items() for t in rs],**scope}
    return c,saved,raw,f,r,generation
def seal(r):
    r={k:v for k,v in r.items() if k!="receipt_sha256"}
    return {**r,"receipt_sha256":N1["digest"](r)}
def evaluate(c,r,generation,manifest=None):
    r=seal(r); p=json.loads(H["canonical"](c["panels"]))
    reader=Reader({"eval/EVALUATION.json":H["canonical"](r),
        "eval/ORIGINAL_PANELS.json":H["canonical"](p),"eval/SHOWN_PANELS.json":H["canonical"](p),
        "eval/MODEL_LOADED.json":H["canonical"]({"model_digest":r["model_digest"],
            "generation_digest":r["generation_digest"],"generation":generation,"pid":r["pid"]})})
    return N1["evaluation_prefix"](reader,Path("eval"),r,c,manifest or c["parent"],"final_answer","primary",None,None)
class Regression(unittest.TestCase):
    def test_producer_roundtrip_original_rejects_fixed_accepts(self):
        c,s,raw,f,r,g=fixture(); contract=SimpleNamespace(load_context=lambda *a:copy.deepcopy(c))
        before=N0["bind_context"](contract,Reader({"INPUTS.json":raw}),f,None,None,None)
        after=N1["bind_context"](contract,Reader({"INPUTS.json":raw}),f,None,None,None)
        self.assertEqual(before,after); self.assertEqual(N1["digest"](before),N1["digest"](after))
        self.assertEqual(list(before["panels"]),["B_exposed","A_retention"])
        self.assertEqual(list(after["panels"]),["A_retention","B_exposed"])
        with self.assertRaisesRegex(ValueError,"evaluation task order or coverage differs"): evaluate(before,r,g)
        self.assertTrue(evaluate(after,r,g))
    def test_missing_extra_duplicate_and_same_panel_reorder_reject(self):
        c,s,raw,f,r,g=fixture(); rows=r["rows"]
        variants={"missing":rows[:-1],"extra":rows+[{"panel":"B_exposed","task_id":"B2"}],
            "duplicate_added":rows+[rows[0]],"duplicate_replacement":[rows[0],rows[0],rows[2]],
            "same_panel_swapped":[rows[1],rows[0],rows[2]]}
        for name,changed in variants.items():
            with self.subTest(case=name):
                rr=copy.deepcopy(r); rr["rows"]=changed
                with self.assertRaisesRegex(ValueError,"evaluation task order or coverage differs"): evaluate(s,rr,g)
    def test_candidate_and_budget_gates_reject(self):
        c,s,raw,f,r,g=fixture()
        with self.assertRaisesRegex(ValueError,"evaluation identity or budget differs"): evaluate(s,r,g,{"wrong":"candidate"})
        for key,value in (("maximum_attempts",3),("max_new_tokens",385)):
            with self.subTest(field=key):
                rr=copy.deepcopy(r); rr[key]=value
                with self.assertRaisesRegex(ValueError,"evaluation identity or budget differs"): evaluate(s,rr,g)
    def test_original_hash_and_reconstruction_equality_still_required(self):
        c,s,raw,f,r,g=fixture(); contract=SimpleNamespace(load_context=lambda *a:copy.deepcopy(c))
        with self.assertRaisesRegex(ValueError,"frozen input hash mismatch"):
            N1["bind_context"](contract,Reader({"INPUTS.json":raw+b" "}),f,None,None,None)
        changed=copy.deepcopy(c); changed["parent"]={"wrong":"parent"}
        with self.assertRaisesRegex(ValueError,"operation INPUTS or measured baseline differs"):
            N1["bind_context"](SimpleNamespace(load_context=lambda *a:changed),Reader({"INPUTS.json":raw}),f,None,None,None)
    def test_cold_identity_original_guard_rejects(self):
        p={"manifest":{"model":"fixture"},"pid":1}
        c={"manifest":p["manifest"],"pid":2,"cold_manifest_exactly_matches_primary":True}
        j={"primary_manifest":p["manifest"],"primary_pid":1,"primary_result_sha256":"a"*64}
        N1["cold_identity"](p,c,j,"a"*64)
        variants=[("manifest",{"model":"other"}),("pid",1),("cold_manifest_exactly_matches_primary",False)]
        for k,v in variants:
            cc=copy.deepcopy(c); cc[k]=v
            with self.assertRaisesRegex(ValueError,"cold identity chain differs"): N1["cold_identity"](p,cc,j,"a"*64)
        for k,v in (("primary_manifest",{"model":"other"}),("primary_pid",3),("primary_result_sha256","b"*64)):
            jj=copy.deepcopy(j); jj[k]=v
            with self.assertRaisesRegex(ValueError,"cold identity chain differs"): N1["cold_identity"](p,c,jj,"a"*64)
    def test_every_non_diagnose_module_node_unchanged(self):
        self.assertEqual(len(trees[0].body),len(trees[1].body))
        for a,b in zip(trees[0].body,trees[1].body):
            if isinstance(a,ast.FunctionDef) and a.name=="diagnose": continue
            self.assertEqual(ast.dump(a),ast.dump(b))
        self.assertEqual(new,old.replace(M["replacement"]["old"],M["replacement"]["new"]))
suite=unittest.defaultTestLoader.loadTestsFromTestCase(Regression)
result=unittest.TextTestRunner(verbosity=2).run(suite)
for item in M["input_bindings"].values(): read_bound(item)
read_bound(M["original_source"]); read_bound(M["candidate_source"])
if any(n in sys.modules for n in ("torch","transformers","peft")): raise ValueError("model module imported")
report={"schema":"hepta.diagnostic-order-fix-regression.v1","tests_run":result.testsRun,
 "failures":[str(t) for t,_ in result.failures],"errors":[str(t) for t,_ in result.errors],
 "passed":result.wasSuccessful(),"original_bytes_still_bound":True,
 "scope":"actual extracted context binding, evaluation prefix and cold guards with in-memory fixtures; no full diagnostic or semantic verifier",
 "candidate_sha256":M["candidate_source"]["sha256"],"model_calls":0,"verifier_calls":0,"C_access":False}
with (O/"REGRESSION.json").open("x") as f: json.dump(report,f,indent=2,sort_keys=True); f.write("\n")
print(json.dumps({"regression_sha256":hashlib.sha256((O/"REGRESSION.json").read_bytes()).hexdigest(),**report}))
sys.exit(0 if result.wasSuccessful() else 1)
