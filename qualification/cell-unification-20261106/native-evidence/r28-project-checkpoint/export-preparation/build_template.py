#!/usr/bin/env python3
"""Build an inert exporter using exact reviewed r28 log-reader functions."""
from pathlib import Path
import ast
import hashlib
import json

ROOT=Path(__file__).resolve().parent
WORK=ROOT.parent


def pin(b):
    return {"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"git_blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()}


def write(name,b):
    p=ROOT/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==b
    else:p.write_bytes(b)


def main():
    old=(WORK/'native-validation-results/r26-export-preparation/export-r26-closed.py').read_bytes()
    reviewed=(WORK/'source52-native-gates-preparation/native-run-r28-template.py').read_bytes()
    assert pin(old)['sha256']=='8eb8bb18f81c8188e161c678f85202abb1ce005a054b4227a7304aa4c33ff973'
    assert pin(reviewed)['sha256']=='2b8eb323a6072e37892802bf62d1ed4ddb38d07d4829a562093ac27a68c9edcb'
    write('references/export-r26-closed.py',old);write('references/native-run-r28-template.py',reviewed)
    functions={n.name:ast.get_source_segment(reviewed.decode(),n) for n in ast.parse(reviewed).body if isinstance(n,ast.FunctionDef)}
    readers='\n\n\n'.join(functions[n] for n in ('clean_lines','review_python','review_tests'))+'\n\n'
    before=(ROOT/'template-head.py.txt').read_bytes();after=(ROOT/'template-tail.py.txt').read_bytes()
    template=before+readers.encode()+after
    tree=ast.parse(template)
    literals={}
    for n in tree.body:
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name):
            try:literals[n.targets[0].id]=ast.literal_eval(n.value)
            except (ValueError,TypeError):pass
    assert literals['FROZEN'] is False
    assert {k for k,v in literals.items() if v is None}=={'TERMINAL_PIN','CLOSED_ORIGINAL_PINS','CONTROLLER_ORIGINAL_PINS'}
    outfunctions={n.name:ast.get_source_segment(template.decode(),n) for n in tree.body if isinstance(n,ast.FunctionDef)}
    assert all(outfunctions[n]==functions[n] for n in ('clean_lines','review_python','review_tests'))
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) and any(x.name in {'cargo','runpy','importlib'} for x in n.names) for n in tree.body)
    write('export-r28-closed-template.py',template)
    audit={'schema':'hepta.r28-export-inert-template-preparation.v1','state':'STATIC_PREPARATION_NOT_EXECUTED','template':pin(template),'original_exporter':pin(old),'reviewed_r28_runner_template':pin(reviewed),'copied_exact_functions':['clean_lines','review_python','review_tests'],'ast_parsed':True,'template_imported_or_executed':False,'FROZEN':False,'unknown_bindings':['TERMINAL_PIN','CLOSED_ORIGINAL_PINS','CONTROLLER_ORIGINAL_PINS'],'known_source_commit':literals['COMMIT'],'known_source_tree':literals['TREE'],'known_changed_count':195,'result_counts_hardcoded':False,'terminal_and_closed_inputs_must_be_bound_before_execution':True,'archive_creation': 'create-only new output; all original source/evidence read only','rust_or_native_or_formatter_run':False,'parent_r26_exporter_modified':False}
    write('MECHANICAL-READBACK.json',(json.dumps(audit,indent=2)+'\n').encode())
    print(json.dumps({'template':pin(template),'FROZEN':False,'None_bindings':3,'exact_reader_functions':3,'AST_ONLY':True},indent=2))


if __name__=='__main__':main()
