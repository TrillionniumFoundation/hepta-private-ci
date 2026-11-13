"""Prior independently reviewed pure byte/AST helpers, with no original main or project import."""
from __future__ import annotations
import ast,hashlib,re

def identity(raw):
    return {'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def require_pin(raw, pin):
    actual = identity(raw)
    for key in ('bytes','sha256','git_blob'):
        assert actual[key] == pin[key], (key,actual,pin)
    return actual

def oid(kind, raw):
    return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def tree(leaves):
    root = {}
    for path,(mode,sha) in leaves.items():
        node = root
        parts = path.split('/')
        for part in parts[:-1]: node = node.setdefault(part,{})
        assert parts[-1] not in node
        node[parts[-1]] = (mode,sha)
    def visit(node):
        entries = []
        for name,value in node.items():
            if isinstance(value,dict): mode,sha='40000',visit(value); key=name.encode()+b'/'
            else: mode,sha=value;key=name.encode()
            entries.append((key,mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)))
        return oid('tree',b''.join(v for _,v in sorted(entries)))
    return visit(root)

def pure_namespace(raw, names, initial):
    """Compile definitions, not module statements; the explicit whitelist is audited."""
    text=raw.decode(); parsed=ast.parse(text)
    nodes=[node for node in parsed.body if isinstance(node,ast.FunctionDef) and node.name in names]
    assert {n.name for n in nodes} == set(names)
    for node in nodes:
        assert not node.decorator_list
        assert not any(isinstance(x,(ast.Import,ast.ImportFrom)) for x in ast.walk(node))
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+nodes,type_ignores=[])
    ast.fix_missing_locations(module)
    ns=dict(initial); exec(compile(module,'<explicit-pure-lexical-definitions>','exec'),ns)
    return ns

def changed_leaves(a,b,prefix=()):
    assert type(a) is type(b), prefix
    if isinstance(a,dict):
        assert a.keys()==b.keys(),prefix
        return [r for k in a for r in changed_leaves(a[k],b[k],prefix+(k,))]
    if isinstance(a,list):
        assert len(a)==len(b),prefix
        return [r for i,(x,y) in enumerate(zip(a,b)) for r in changed_leaves(x,y,prefix+(i,))]
    return [] if a==b else [(prefix,a,b)]

def constants(raw):
    out={}
    for node in ast.parse(raw).body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            try: out[node.targets[0].id]=ast.literal_eval(node.value)
            except (ValueError,TypeError): pass
    return out

def function_bytes(raw,node):
    lines=raw.splitlines(keepends=True)
    start=min([node.lineno]+[d.lineno for d in node.decorator_list])-1
    return b''.join(lines[start:node.end_lineno])

def methods(raw):
    parsed=ast.parse(raw); out={}; helpers={}
    for item in parsed.body:
        if isinstance(item,(ast.FunctionDef,ast.AsyncFunctionDef)):
            helpers[item.name]=function_bytes(raw,item)
        if isinstance(item,ast.ClassDef):
            for child in item.body:
                if isinstance(child,(ast.FunctionDef,ast.AsyncFunctionDef)) and child.name.startswith('test_'):
                    key=item.name+'.'+child.name
                    assert key not in out
                    out[key]=(function_bytes(raw,child),ast.dump(child,include_attributes=False))
    return out,helpers

