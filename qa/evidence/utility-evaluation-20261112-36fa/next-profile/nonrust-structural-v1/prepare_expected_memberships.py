#!/usr/bin/env python3
"""Synchronize reviewed exact memberships; preserve every test body verbatim."""
import ast
import hashlib
import json
from pathlib import Path
import tomllib

ROOT = Path('/tmp/hepta-36fa-evaluated-ordinary-nonrust-v1')
old = tomllib.loads((ROOT/'baseline/CALLERS.toml').read_text())
new = tomllib.loads((ROOT/'structural-candidate/CALLERS.toml').read_text())
old_rows = {row['id']:row for row in old['boundary']}
new_rows = {row['id']:row for row in new['boundary']}
changed_ids = {key for key in old_rows if old_rows[key]['product_callers'] != new_rows[key]['product_callers']}

def evaluate(node, env):
    if isinstance(node, ast.Constant):return node.value
    if isinstance(node, ast.Name):return env[node.id]
    if isinstance(node, ast.Tuple):return tuple(evaluate(x,env) for x in node.elts)
    if isinstance(node, ast.List):return [evaluate(x,env) for x in node.elts]
    if isinstance(node, ast.Dict):
        value={}
        for key,item in zip(node.keys,node.values):
            if key is None:value.update(evaluate(item,env))
            else:value[evaluate(key,env)]=evaluate(item,env)
        return value
    if isinstance(node,ast.DictComp):
        assert len(node.generators)==1
        generator=node.generators[0]
        assert isinstance(generator.target,ast.Name) and not generator.ifs and not generator.is_async
        value={}
        for item in evaluate(generator.iter,env):
            nested={**env,generator.target.id:item}
            value[evaluate(node.key,nested)]=evaluate(node.value,nested)
        return value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):return evaluate(node.left,env)+evaluate(node.right,env)
    raise ValueError(type(node).__name__)

def functions(tree,text):
    return [(node.name,ast.dump(node,include_attributes=False),ast.get_source_segment(text,node))
            for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))]

def meta(text):
    b=text.encode()
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob_sha':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

results=[]
for path in sorted((ROOT/'baseline/qa/b4-no-bypass').glob('*source_closure.py')):
    text=path.read_text();tree=ast.parse(text);env={};expected=None
    for node in tree.body:
        if not isinstance(node,ast.Assign):continue
        names=[name.id for name in node.targets if isinstance(name,ast.Name)]
        if 'EXPECTED' in names:expected=node.value;break
        try:value=evaluate(node.value,env)
        except (ValueError,KeyError,TypeError):continue
        for name in names:env[name]=value
    if not isinstance(expected,ast.Dict):continue
    positions=[];rows=[];offsets=[];n=0
    for line in text.splitlines(True):offsets.append(n);n+=len(line)
    for key,value in zip(expected.keys,expected.values):
        if key is None:
            assert not set(evaluate(value,env)) & changed_ids,(path,'review unpacked changed entries')
            continue
        identifier=evaluate(key,env)
        if identifier not in changed_ids:continue
        previous=evaluate(value,env)
        assert isinstance(previous,(tuple,list)),(path,identifier,type(previous))
        assert set(previous)==set(old_rows[identifier]['product_callers']),(path,identifier,previous,old_rows[identifier]['product_callers'])
        after=new_rows[identifier]['product_callers']
        replacement=repr(tuple(after) if isinstance(previous,tuple) else after)
        start=offsets[value.lineno-1]+value.col_offset;end=offsets[value.end_lineno-1]+value.end_col_offset
        positions.append((start,end,replacement))
        rows.append({'boundary_id':identifier,'before':list(previous),'after':after})
    if not positions:continue
    updated=text
    for start,end,replacement in sorted(positions,reverse=True):updated=updated[:start]+replacement+updated[end:]
    assert functions(tree,text)==functions(ast.parse(updated),updated),path
    rel=path.relative_to(ROOT/'baseline');dest=ROOT/'candidate'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():assert dest.read_text()==updated,dest
    else:dest.write_text(updated)
    results.append({'path':str(rel),'before':meta(text),'after':meta(updated),'changed_expected_values':rows,
                    'all_function_ast_and_source_bytes_unchanged':True,'function_count':len(functions(tree,text))})
report={'status':'prepared_expected_only_all_test_functions_unchanged','tests_executed':False,
        'baseline_source_tree':'7d26396020a11227914948be902fb3721084630c','files':results,
        'limits':['Exact comparison remains equality, not subset.','All existing function bodies and assertions remain byte-identical in this preparatory layer.','Additional literal synchronization for actual formatted source remains pending and will be a separately auditable delta.']}
(ROOT/'EXPECTED_MEMBERSHIP_PREPARATION.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'files_changed':len(results),'expected_values_changed':sum(len(x['changed_expected_values']) for x in results),'unchanged_functions':sum(x['function_count'] for x in results),'tests_executed':False,'paths':[x['path'] for x in results]},indent=2))
