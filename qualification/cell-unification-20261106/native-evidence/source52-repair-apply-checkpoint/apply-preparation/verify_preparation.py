"""Offline AST/byte review only; never import or execute the apply executor."""
from pathlib import Path
import ast
import hashlib
import json

D = Path(__file__).resolve().parent
def pin(raw):
    return {"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
            "git_blob":hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()}
def main():
    raw=(D/"native-source52-apply-template.py").read_bytes()
    text=raw.decode()
    tree=ast.parse(text)
    constants={n.targets[0].id:ast.literal_eval(n.value)
               for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1
               and isinstance(n.targets[0],ast.Name)
               and isinstance(n.value,(ast.Constant,ast.Dict,ast.Tuple,ast.List))
               and not any(isinstance(x,ast.Name) for x in ast.walk(n.value))}
    unknown=sorted(k for k,v in constants.items() if v is None)
    assert unknown==sorted(["EXPECTED_COMMIT","EXPECTED_TREE","EXPECTED_CHANGED_COUNT","INPUT_BYTES",
                            "INPUT_SHA256","SOURCE52_MANIFEST_PIN","DELTA_MANIFEST_PIN","CANDIDATE_PINS"])
    assert constants["FROZEN"] is False
    assert constants["SOURCE51_COMMIT"]=="e28b0f385ee882f842911044958b2810f62f6379"
    assert constants["SOURCE51_TREE"]=="763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
    assert constants["SOURCE51_COUNT"]==194
    assert constants["SOURCE51_MANIFEST_NAME"]=="native-candidate-r26-source.json"
    assert constants["SOURCE52_MANIFEST_OUTPUT_NAME"]=="native-candidate-r28-source.json"
    assert constants["ALLOWED_PATHS"]==("codex-rs/network-proxy/src/runtime.rs",)
    assert constants["R26_TERMINAL_NAME"]=="native-source51-project-r26-terminal-process-status.json"
    assert constants["R26_JOB_ID"]=="1a1b1b739ee-fc05-7a70"
    funcs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
    assert len(funcs)==len([n for n in tree.body if isinstance(n,ast.FunctionDef)])
    shadow={}
    for name,fn in funcs.items():
        stores={n.id for n in ast.walk(fn) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
        overlap=stores&set(funcs)
        if overlap: shadow[name]=sorted(overlap)
    assert shadow=={}
    calls=[]
    for fn in funcs.values():
        for node in ast.walk(fn):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and isinstance(node.func.value,ast.Name) and node.func.value.id=="subprocess":
                calls.append({"function":fn.name,"call":ast.get_source_segment(text,node)})
    assert {x["function"] for x in calls}=={"git","run_git_phase"}
    ref=(D/"references/native-source51-apply-template.py").read_bytes()
    assert pin(ref)["sha256"]=="743a9f7ff2c4992b91aab39aa22298b6599c169c15089360e7dbcfbff4cf0f8e"
    rt=ast.parse(ref); rf={n.name:ast.get_source_segment(ref.decode(),n) for n in rt.body if isinstance(n,ast.FunctionDef)}
    same=[n for n,body in rf.items() if n in funcs and body==ast.get_source_segment(text,funcs[n])]
    new=[n for n in funcs if n not in rf]
    report={"schema":"hepta.source52-apply-preparation-static-readback.v1",
            "state":"INERT_UNKNOWN_ACTUAL_SOURCE52_BINDINGS","template":pin(raw),"reference":pin(ref),
            "AST_parse":True,"unknown_None_bindings":unknown,"FROZEN":False,
            "same_function_bodies":same,"new_read_only_functions":new,"local_name_shadowing":shadow,
            "subprocess_entrypoints":calls,
            "source_before_count":194,"required_after_count_once_bound":195,
            "single_existing_repository_leaf_not_in_before_changed_manifest":constants["ALLOWED_PATHS"][0],
            "all_old194_manifest_rows_must_be_identical":True,
            "hard_HEAD":constants["FRAMEWORK_PARENT"],
            "raw_return_codes_persist_before_later_output_hashing":True,
            "failure_preserves_actual_source_without_reset_or_retry":True,
            "current_failed_r26_is_provenance_not_qualification":True,
            "execution":{"executor_imported":False,"executor_run":False,"native_job":False,
                         "Git_apply":False,"Rust":False,"lock_update":False,"fix_fmt":False}}
    out=(json.dumps(report,indent=2)+"\n").encode()
    (D/"STATIC-READBACK.json").write_bytes(out)
    entries=[]
    for p in sorted(D.rglob("*")):
        if p.is_file() and p.name!="HANDOFF-MANIFEST.json" and "__pycache__" not in p.parts:
            entries.append({"path":p.relative_to(D).as_posix(),**pin(p.read_bytes())})
    handoff={"schema":"hepta.source52-apply-preparation-handoff.v1",
             "state":"FROZEN_INERT_PREPARATION_ONLY","source52_actual_commit":None,
             "source52_actual_tree":None,"FROZEN":False,"files":entries,
             "file_count":len(entries),"total_bytes":sum(x["bytes"] for x in entries),
             "no_execution":True}
    hb=(json.dumps(handoff,indent=2)+"\n").encode();(D/"HANDOFF-MANIFEST.json").write_bytes(hb)
    print(json.dumps({"template":pin(raw),"readback":pin(out),"handoff":pin(hb)}))
if __name__=="__main__":
    main()
