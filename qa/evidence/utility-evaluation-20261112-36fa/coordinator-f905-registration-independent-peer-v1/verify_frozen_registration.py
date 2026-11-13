#!/usr/bin/env python3
"""Offline byte/AST/span audit; never imports or runs a QA/collector module.

Only explicitly listed, source-pinned, pure lexical helper FunctionDefs are
extracted. No test method, verifier, main, subprocess, source write, or H call.
The sole output is a new JSON review in this script's scratch directory.
"""
from __future__ import annotations
import ast
import base64
import copy
import hashlib
import json
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
FROZEN = Path('/tmp/hepta-36fa-coordinator-f905-registration-frozen-v1')
PREP = Path('/tmp/hepta-36fa-coordinator-f905-registration-v1')
INVENTORY = Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1/final.inventory.exact_recovered.json')
FMT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1/fmt.after.postimages.json')
RUST_LAYERS = [
    (Path('/tmp/hepta-36fa-coordinator-f905-preparation-v1/SOURCE_PACKET.json'), '773d67128190fd2e1c3271c372f72e2a5537d1e8'),
    (Path('/tmp/hepta-36fa-coordinator-original-metadata-getters-v1/SOURCE_PACKET.json'), '5279a43b99aa7031343578a21dba895f5eac3188'),
]
AGENT = 'codex-rs/hepta-agentd/src/'
QA = 'qa/b4-no-bypass/'

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

def load_packet(path, expected):
    raw = path.read_bytes(); assert identity(raw)['git_blob'] == expected
    return json.loads(raw),identity(raw)

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

def main():
    invraw=INVENTORY.read_bytes()
    assert len(invraw)==5634549
    assert hashlib.sha256(invraw).hexdigest()=='bc6b9d59143004236665bb9446e2c45d1ac77cd7aaba14ba7cee8f4ea76d003f'
    inv=json.loads(invraw); rows={r['path']:r for r in inv['files']};assert len(rows)==15237
    leaves={p:(str(r['index_mode']),r['working_blob']) for p,r in rows.items()}
    assert tree(leaves)=='f905b18e6b05de1582024548179725a05d932536'
    packet,packetpin=load_packet(HERE/'inputs/SOURCE_PACKET.exact_from_full_get.json','e01b6c1689e1d834701a0d4565c5da662936ea80')
    material={}; rust_layers=[]
    for path,expected in RUST_LAYERS:
        layer,pin=load_packet(path,expected)
        for change in layer['source_changes']:
            name=change['path']; before=base64.b64decode(change['before_base64'],validate=True) if change['before_base64'] is not None else None
            after=base64.b64decode(change['after_base64'],validate=True)
            if before is None: assert name not in leaves and change['before'] is None
            else:
                require_pin(before,change['before']); assert leaves[name][1]==change['before']['git_blob']
                if name in material: assert material[name]==before
            require_pin(after,change['after']); material[name]=after
            leaves[name]=(change['mode'],change['after']['git_blob'])
        rust_layers.append({'packet':pin,'changes':len(layer['source_changes'])})
    prepared_tree=tree(leaves); assert prepared_tree=='2b423171ef3f1057ebaa081daf3ce42b78f467d7';assert len(leaves)==15243
    changed={}; sourcepins=[]
    for change in packet['source_changes']:
        name=change['path']; before=base64.b64decode(change['before_base64'],validate=True); after=base64.b64decode(change['after_base64'],validate=True)
        require_pin(before,change['before']); require_pin(after,change['after'])
        assert leaves[name][1]==change['before']['git_blob']==rows[name]['working_blob']
        assert (FROZEN/'before'/name).read_bytes()==before
        assert (FROZEN/'after'/name).read_bytes()==after
        leaves[name]=(change['mode'],change['after']['git_blob']);changed[name]=(before,after)
        sourcepins.append({k:v for k,v in change.items() if 'base64' not in k})
    final_tree=tree(leaves);assert final_tree=='a489b394666b8141840275128a780605b024cde0';assert len(changed)==7
    bound_sources={}
    def source(path):
        if path in material: raw=material[path];basis='exact required Rust packet chain'
        else:
            candidate=PREP/'view'/path
            if not candidate.exists():candidate=HERE/'inputs/additional-source'/path
            raw=candidate.read_bytes();row=rows[path]
            require_pin(raw,{'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['working_blob']});basis='actual f905 complete inventory'
        bound_sources[path]={'path':path,**identity(raw),'basis':basis}
        return raw.decode()
    scannerraw=(PREP/'before/scripts/verify_hepta_callers.py').read_bytes();row=rows['scripts/verify_hepta_callers.py']
    require_pin(scannerraw,{'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['working_blob']})
    class LexicalError(Exception): pass
    scanner_names=['_strip_rust_non_code','_looks_like_char_literal','_strip_cfg_test_items','_matching_delimiter','_cfg_without_test','_skip_space','_rust_item_end']
    scanner=pure_namespace(scannerraw,scanner_names,{'re':re,'RAW_STRING_START':re.compile(r'r(#{0,255})"'),'VerificationFailure':LexicalError})
    proof=SimpleNamespace(**{n:scanner[n] for n in scanner_names},VerificationFailure=LexicalError)
    scopesraw=changed[QA+'test_evaluated_published_read_source_closure.py'][0]
    scope_names=['ordinary_require','ordinary_depth_at','ordinary_body_open','ordinary_item_end','ordinary_root_containers','ordinary_function_location','ordinary_select_scope','ordinary_without_nested_functions','ordinary_literal_span','ordinary_mount_span']
    scopes=pure_namespace(scopesraw,scope_names,{'re':re,'PROOF':proof})
    scopes_obj=SimpleNamespace(**{n:scopes[n] for n in scope_names})
    providerraw=changed[QA+'test_resident_provider_local_read_source_closure.py'][0]
    provider_names=['require','active_source','actual_scope','module_shape']
    provider=pure_namespace(providerraw,provider_names,{'re':re,'PROOF':proof,'SCOPES':scopes_obj})
    def active(raw): return provider['active_source'](raw)
    old=tomllib.loads(changed['CALLERS.toml'][0].decode());new=tomllib.loads(changed['CALLERS.toml'][1].decode())
    assert len(old['boundary'])==621 and len(new['boundary'])==633
    assert old['boundary']==new['boundary'][:621]
    for key in old:
        if key not in ('boundary','privileged_inventory','protected_file'): assert old[key]==new[key],key
    assert len(set(r['id'] for r in new['boundary']))==633
    assert old['privileged_inventory']['required_boundary_ids']==new['privileged_inventory']['required_boundary_ids'][:621]
    required_ids=new['privileged_inventory']['required_boundary_ids']
    assert len(required_ids)==len(set(required_ids))==633
    assert set(required_ids)=={r['id'] for r in new['boundary']}
    assert required_ids[621:]==[r['id'] for r in new['boundary'][621:]]
    assert all(x is False for x in new['authority'].values())
    assert len(old['protected_file'])==437 and len(new['protected_file'])==442
    assert old['protected_file'][411]==new['protected_file'][411]
    fmtraw=FMT.read_bytes();assert len(fmtraw)==2175219 and hashlib.sha256(fmtraw).hexdigest()=='3309f2099b3545737f390f16928d5d085177e72a6e8194aa018fe5039121dc22'
    fmtchanges={c['path']:c for c in json.loads(fmtraw)['changes']}
    refresh=[];changed_rows=[]
    for i,(a,b) in enumerate(zip(old['protected_file'],new['protected_file'])):
        assert a['forbidden']==b['forbidden']
        delta=changed_leaves(a,b)
        if not delta: continue
        changed_rows.append(i); path=a['path'];assert path in fmtchanges
        fmt=fmtchanges[path]
        before=base64.b64decode(fmt['before_raw_base64'],validate=True).decode()
        after=base64.b64decode(fmt['after_raw_base64'],validate=True).decode();assert after==source(path)
        before_code,_=active(before);after_code,_=active(after)
        for field,x,y in delta:
            assert isinstance(x,str) and isinstance(y,str)
            assert field[0] in ('required_function_order','required_order'),field
            if field[0]=='required_function_order':
                assert field[2:] == ('sequence',1),field
                ga=a[field[0]][field[1]];gb=b[field[0]][field[1]]
                assert {k:v for k,v in ga.items() if k!='sequence'}=={k:v for k,v in gb.items() if k!='sequence'}
                assert len(ga['sequence'])==len(gb['sequence'])==2 and ga['sequence'][0]==gb['sequence'][0]=='fn '
                marker=ga['function'];assert before_code.count(marker)==after_code.count(marker)==1
                lo=before_code.index(marker);hi=proof._rust_item_end(before_code,lo)+1
                la=after_code.index(marker);ha=proof._rust_item_end(after_code,la)+1
                assert ''.join(ga['sequence'])==before_code[lo:hi]
                assert ''.join(gb['sequence'])==after_code[la:ha]
                scope={'kind':'complete original function','name':marker,'before_range':[lo,hi],'after_range':[la,ha]}
            else:
                assert field[2:]==(1,),field
                sa=a[field[0]][field[1]];sb=b[field[0]][field[1]]
                # field is required_order / sequence index / marker index.
                assert len(sa)==len(sb)==2 and sa[0]==sb[0]
                fulla=''.join(sa);fullb=''.join(sb)
                assert before_code.count(fulla)==after_code.count(fullb)==1
                lo=before_code.index(fulla);hi=proof._rust_item_end(before_code,lo)+1
                la=after_code.index(fullb);ha=proof._rust_item_end(after_code,la)+1
                assert before_code[lo:hi]==fulla and after_code[la:ha]==fullb
                assert scopes['ordinary_depth_at'](before_code,lo)==scopes['ordinary_depth_at'](after_code,la)==(0,0,0)
                scope={'kind':'complete original root item','prefix':sa[0],'before_range':[lo,hi],'after_range':[la,ha]}
            refresh.append({'row':i,'path':path,'field':list(field),'before':identity(x.encode()),'after':identity(y.encode()),'scope':scope})
    assert len(changed_rows)==23 and len(refresh)==80
    assert sum(x['field'][0]=='required_function_order' for x in refresh)==58
    newrowobs=[]
    for i,row in enumerate(new['protected_file'][437:],437):
        raw=source(row['path']);code,_=active(raw)
        for marker in row['required']: assert marker in raw
        for sequence in row.get('required_order',[]):
            joined=''.join(sequence);assert code.count(joined)==1,(row['path'],sequence[0])
            if len(sequence)==2 and sequence[0] in ('fn ','pub struct ','struct ','impl<W: ','impl '):
                lo=code.index(joined);end=proof._rust_item_end(code,lo)+1;assert code[lo:end]==joined
        for guard in row.get('required_function_order',[]):
            marker=guard['function'];assert code.count(marker)==1,(row['path'],marker)
            lo=code.index(marker);end=proof._rust_item_end(code,lo)+1
            assert ''.join(guard['sequence'])==code[lo:end]
        for marker in row['forbidden']:
            pattern=re.escape(marker)
            if marker[0].isalnum() or marker[0]=='_':pattern=r'(?<!\w)'+pattern
            if marker[-1].isalnum() or marker[-1]=='_':pattern+=r'(?!\w)'
            assert not re.search(pattern,code),(row['path'],marker)
        newrowobs.append({'index':i,'path':row['path'],'required':len(row['required']),'whole_root_items':len(row.get('required_order',[])),'whole_functions':len(row.get('required_function_order',[])),'forbidden':row['forbidden']})
    ac=json.loads(changed[QA+'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'][0]);bc=json.loads(changed[QA+'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'][1])
    allowed={'attacks','boundary_count','complete_boundary_sha256','exports','module_shapes','mounts','new_boundaries','scopes','source_refresh_basis'}
    for key in ac:
        if key not in allowed: assert ac[key]==bc[key],key
    assert bc['boundary_count']==633
    checked={k:new[k] for k in ('boundary','privileged_inventory','authority','source_roots','ignored_path_fragments')}
    digest=hashlib.sha256(json.dumps(checked,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert digest==bc['complete_boundary_sha256']
    assert bc['new_boundaries']==new['boundary'][569:]
    assert ac['new_boundaries']==bc['new_boundaries'][:52]
    assert ac['exports']==bc['exports'][:len(ac['exports'])]
    for group,cases in ac['attacks'].items():assert cases==bc['attacks'][group]
    assert sum(map(len,ac['attacks'].values()))==83
    extra_groups=set(bc['attacks'])-set(ac['attacks']);assert len(extra_groups)==3
    assert sum(len(bc['attacks'][x]) for x in extra_groups)==24
    scopeobs=[];scope_changes=[]
    for path,guards in bc['scopes'].items():
        text=source(path);code,original=active(text)
        shape=provider['module_shape'](code,original);assert shape==bc['module_shapes'][path],path
        if path in ac['scopes']:
            assert len(guards)==len(ac['scopes'][path])
        for index,guard in enumerate(guards):
            lo,hi=provider['actual_scope'](code,guard['selector'])
            assert hashlib.sha256(code[lo:hi].encode()).hexdigest()==guard['masked_sha256'],(path,index)
            assert hashlib.sha256(original[lo:hi].encode()).hexdigest()==guard['literal_source_sha256'],(path,index)
            is_new=path not in ac['scopes']
            if not is_new:
                old_guard=ac['scopes'][path][index]
                assert {k:v for k,v in old_guard.items() if k not in ('masked_sha256','literal_source_sha256')}=={k:v for k,v in guard.items() if k not in ('masked_sha256','literal_source_sha256')}
                if old_guard!=guard:scope_changes.append({'path':path,'index':index,'selector':guard['selector']})
            scopeobs.append({'path':path,'index':index,'selector':guard['selector'],'range':[lo,hi],'masked_sha256':guard['masked_sha256'],'literal_source_sha256':guard['literal_source_sha256'],'new':is_new})
    assert len(ac['scopes'])==41 and sum(map(len,ac['scopes'].values()))==264
    assert len(bc['scopes'])==45 and len(scopeobs)==288 and len(scope_changes)==39
    for path,values in ac['mounts'].items():assert values==bc['mounts'][path]
    mountobs=[]
    for path,values in bc['mounts'].items():
        text=source(path);code,_=active(text)
        for spec in values:
            span=scopes['ordinary_mount_span'](proof,code,text,spec);mountobs.append({'path':path,**span})
    lib=source(AGENT+'lib.rs');libcode,_=active(lib)
    for export in bc['exports']:
        assert lib.count(export)==1
        assert libcode.count(export)==1
        assert scopes['ordinary_depth_at'](libcode,libcode.index(export))==(0,0,0)
    attacks=[]
    for group,cases in bc['attacks'].items():
        for case in cases:
            text=source(case['path']);code,_=active(text)
            scope=scopes['ordinary_select_scope'](proof,code,{'kind':'unique_function','name':case['function']})
            marker=case['marker'];pattern=r'\s*'.join(re.escape(t) for t in re.findall(r'\w+|[^\w\s]',marker))
            if marker[0].isalnum() or marker[0]=='_':pattern=r'(?<!\w)'+pattern
            if marker[-1].isalnum() or marker[-1]=='_':pattern+=r'(?!\w)'
            matches=list(re.finditer(pattern,code[scope['start']:scope['end']]))
            assert matches,(group,case)
            attacks.append({'group':group,'path':case['path'],'function':case['function'],'marker':marker,'real_scope':scope,'matched_ranges':[[scope['start']+m.start(),scope['start']+m.end()] for m in matches],'new_group':group in extra_groups})
    # Exact ordinary contract, selectors, mount and literal data are unchanged.
    ordinaryold=constants(changed[QA+'test_evaluated_published_read_source_closure.py'][0]);ordinarynew=constants(changed[QA+'test_evaluated_published_read_source_closure.py'][1])
    assert ordinaryold.keys()==ordinarynew.keys()
    for key in ordinaryold:
        if key!='ORDINARY_COMPLETE_BOUNDARY_SHA256':assert ordinaryold[key]==ordinarynew[key],key
    assert ordinarynew['ORDINARY_COMPLETE_BOUNDARY_SHA256']==digest
    assert new['boundary'][541:569]==ordinarynew['ORDINARY_NEW_BOUNDARIES']
    ordinary_scope_count=sum(len(x) for x in ordinarynew['ORDINARY_SCOPE_GUARDS'].values());assert ordinary_scope_count==34
    ordinary_scopeobs=[]
    for path,guards in ordinarynew['ORDINARY_SCOPE_GUARDS'].items():
        text=source(path);code=proof._strip_cfg_test_items(proof._strip_rust_non_code(text))
        for guard in guards:
            span=scopes['ordinary_select_scope'](proof,code,guard['selector'])
            # Fields use the original contract's digest names, inspected below.
            actual=hashlib.sha256(code[span['start']:span['end']].encode()).hexdigest()
            expected=guard.get('masked_sha256',guard.get('sha256'))
            assert actual==expected,(path,guard.keys())
            ordinary_scopeobs.append({'path':path,'selector':guard['selector'],'range':[span['start'],span['end']],'sha256':actual})
    literalobs=[]
    for spec in ordinarynew['ORDINARY_LITERAL_SPECS']:
        text=source(spec['path']);code=proof._strip_cfg_test_items(proof._strip_rust_non_code(text))
        literalobs.append({'path':spec['path'],**scopes['ordinary_literal_span'](proof,code,text,spec)})
    assert len(literalobs)==17
    beforeqas=sorted((PREP/'before/qa/b4-no-bypass').glob('*.py'));assert len(beforeqas)==64
    methodobs=[];oldtotal=same=ast_same=0;method_changes=[];new_methods=[]
    for path in beforeqas:
        relative=QA+path.name;before=path.read_bytes();row=rows[relative]
        require_pin(before,{'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['working_blob']})
        after=changed.get(relative,(before,before))[1]
        om,oh=methods(before);nm,nh=methods(after);assert oh==nh,relative
        assert om.keys()<=nm.keys();oldtotal+=len(om)
        for key,(oldbytes,oldast) in om.items():
            newbytes,newast=nm[key]
            if oldbytes==newbytes:same+=1
            else:method_changes.append({'path':relative,'method':key,'before':identity(oldbytes),'after':identity(newbytes)})
            if oldast==newast:ast_same+=1
        for key in sorted(nm.keys()-om.keys()):new_methods.append({'path':relative,'method':key,'body':nm[key][0].decode()})
        methodobs.append({'path':relative,'before':identity(before),'after':identity(after),'old_methods':len(om),'new_methods':len(nm)-len(om),'helpers_unchanged':len(oh)})
    assert oldtotal==604 and same==ast_same==602 and len(method_changes)==2 and len(new_methods)==3
    # Prove both existing test bodies recover exactly by reversing only the
    # documented additions/count adjustment, rather than trusting a count.
    oldeval,_=methods(changed[QA+'test_evaluated_published_read_source_closure.py'][0])
    neweval,_=methods(changed[QA+'test_evaluated_published_read_source_closure.py'][1])
    evalkey=next(k for k in oldeval if k.endswith('.test_new_typed_edges_and_old_boundary_inventory_are_exact'))
    assert neweval[evalkey][0].replace(b'self.assertEqual(len(boundaries), 633)',b'self.assertEqual(len(boundaries), 621)',1)==oldeval[evalkey][0]
    oldroot,_=methods(changed[QA+'test_resident_root_source_closure.py'][0]);newroot,_=methods(changed[QA+'test_resident_root_source_closure.py'][1])
    rootkey=next(k for k in oldroot if k.endswith('.test_existing_ci_really_selects_root_cases_neuron_and_full_caller_proof'))
    restored=newroot[rootkey][0]
    restored=restored.replace(b'        self.assertTrue(set(ROOT_CUSTODY_CASES).issubset(parents))\n',b'',1)
    restored=restored.replace(b' + len(ROOT_CUSTODY_CASES)',b'',1)
    cut=restored.index(b'        task_support = (ROOT / (AGENT + "circuit_q24_task_test_support.rs")).read_text()\n')
    stop=restored.index(b'        for marker in (\n',cut)
    restored=restored[:cut]+restored[stop:]
    assert restored==oldroot[rootkey][0]
    assert {m['path'] for m in new_methods}=={QA+'test_resident_provider_local_read_source_closure.py'}
    for m in new_methods:
        parsed=ast.parse(m['body'].lstrip());body=parsed.body[0].body
        assert len(body)==1 and isinstance(body[0],ast.Expr) and isinstance(body[0].value,ast.Call)
        call=body[0].value;assert isinstance(call.func,ast.Attribute) and call.func.attr=='attack_group' and len(call.args)==1
        assert ast.literal_eval(call.args[0]) in extra_groups
    providerconstants=constants(changed[QA+'test_resident_provider_local_read_source_closure.py'][1])
    contract_sha=identity(changed[QA+'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'][1])['sha256']
    assert "!= '"+contract_sha+"'" in changed[QA+'test_resident_provider_local_read_source_closure.py'][1].decode()
    wfpath='.github/workflows/hepta-daemon-learning-native.yml';wb,wa=[x.decode() for x in changed[wfpath]]
    pattern=r'parents\s*=\s*(\[.*?\])';mb=re.search(pattern,wb,re.DOTALL);ma=re.search(pattern,wa,re.DOTALL);assert mb and ma
    oldparents=ast.literal_eval(mb.group(1));newparents=ast.literal_eval(ma.group(1));assert len(oldparents)==39 and len(newparents)==48 and len(set(newparents))==48
    assert newparents[:39]==oldparents
    assert wa[:ma.start(1)]+mb.group(1)+wa[ma.end(1):]==wb
    rootconstants=constants(changed[QA+'test_resident_root_source_closure.py'][1]);assert rootconstants['ROOT_CUSTODY_CASES']==newparents[39:]
    newtestsource=source(AGENT+'neuron_generation_initial_root_custody_tests.rs');newcoldsource=source(AGENT+'neuron_generation_initial_root_cold_tests.rs')
    ignored='#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]'
    assert newtestsource.count(ignored)==5 and newcoldsource.count(ignored)==4
    for fqn in newparents[39:]:
        raw=newcoldsource if '::cold_tests::' in fqn else newtestsource
        name=fqn.rsplit('::',1)[-1]
        assert raw.count('async fn '+name+'(')==1
        attributes=re.search(r'((?:#\[[^\]]+\]\s*)+)async\s+fn\s+'+re.escape(name)+r'\(',raw)
        assert attributes and ignored in attributes.group(1),(fqn,'direct ignored attribute')
    mount_checks=[('circuit_q24_task_test_support.rs','neuron_generation_initial_root_custody_support_tests.rs','root_initial_custody'),('neuron_generation_initial_root_custody_support_tests.rs','neuron_generation_initial_root_custody_tests.rs','tests'),('neuron_generation_initial_root_custody_support_tests.rs','neuron_generation_initial_root_cold_tests.rs','cold_tests')]
    for parent,child,name in mount_checks:
        assert '#[path = "'+child+'"]\nmod '+name+';' in source(AGENT+parent)
    albefore,alafter=changed['.github/blob-size-allowlist.txt'];assert alafter.startswith(albefore)
    addition=alafter[len(albefore):].decode();assert addition=='# Exact actual-format and original Root custody source guards; no wildcard.\nsha256:'+identity(changed['CALLERS.toml'][1])['sha256']+' CALLERS.toml\n'
    publicobs=[]
    for row in new['boundary'][621:]:
        assert row['product_callers']==[] and row['caller_markers']==[]
        code,_=active(source(row['definition_path']))
        method=row['symbol'].rsplit('::',1)[-1]
        assert re.search(r'\bpub\s+fn\s+'+re.escape(method)+r'\s*[<(]',code),(row['symbol'])
        publicobs.append(row)
    out={
      'format':'hepta-coordinator-registration-independent-static-observations-v1',
      'scope':'pure offline byte, AST, lexical span and Git Merkle observations; no QA/verifier/collector main or test method executed',
      'status':'OBSERVATIONS_COMPLETE_NO_RUNTIME_OR_QUALIFICATION_VERDICT',
      'packet':packetpin,'actual_inventory':identity(invraw),'required_rust_layers':rust_layers,
      'source_changes':sourcepins,'actual_f905_tree':'f905b18e6b05de1582024548179725a05d932536','prepared_tree':prepared_tree,'expected_after_tree':final_tree,'expected_leaves':len(leaves),
      'old_boundaries_exact':621,'new_boundary_count':633,'required_boundary_ids_exact':633,'old_protected_rows':437,'old_protected_rows_identical':437-len(changed_rows),'changed_old_rows':changed_rows,'all_437_forbidden_arrays_equal':True,'row411_schema_equal':True,
      'unchanged_source_roots_ignore_authority_and_other_top_level_fields':True,'refreshed_full_scope_values':refresh,'new_protected_rows':newrowobs,
      'provider_old_paths':41,'provider_old_scopes':264,'provider_paths':45,'provider_scopes':288,'old_scope_hash_changes':scope_changes,'scope_observations':scopeobs,'module_shapes_all_match_bound_sources':True,'mount_observations':mountobs,'all_original_attack_specs_equal':83,'new_attack_specs':24,'attack_span_observations':attacks,
      'ordinary_original_slice':[541,569],'provider_extended_slice':[569,633],'ordinary_scopes_unchanged':ordinary_scopeobs,'ordinary_literals_unchanged':literalobs,
      'qa_files':64,'old_test_methods':604,'old_methods_byte_and_ast_equal':602,'changed_old_methods':method_changes,'new_test_methods':new_methods,'removed_methods':0,'all_top_level_helpers_unchanged':True,'qa_file_observations':methodobs,
      'workflow_old_parents':oldparents,'workflow_new_parents':newparents,'workflow_only_parent_list_append':True,'root_budget_seconds_unchanged':7200,'root_test_threads_unchanged':1,'ignored_root_tests_not_run':9,
      'new_boundaries_with_no_registered_product_callers':publicobs,'allowlist_exact_sha_only':addition,
      'lexical_helpers':{'scanner':identity(scannerraw),'ordinary_scope_source':identity(scopesraw),'provider_scope_source':identity(providerraw),'function_def_whitelists':[scanner_names,scope_names,provider_names],'whole_modules_imported':False,'verifier_or_test_methods_executed':False},
      'bound_source_files':list(bound_sources.values()),
      'limitations':['No full source caller scan, QA, Rust parsing/compiler/formatter, native gate, source activation or H call.','Attack entries are statically located in exact active function ranges; mutants and their expected rejections were not executed.','Expected Git trees are pure projections, not native inventory observations or source publication.','The twelve new Root APIs have empty registered product caller sets; this review does not establish normal host integration.']}
    target=HERE/'FROZEN_REGISTRATION_BYTE_AND_SCOPE_REVIEW.json'
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'output':str(target),'identity':identity(target.read_bytes()),'changed_rows':len(changed_rows),'full_span_values':len(refresh),'scope_count':len(scopeobs),'attacks':len(attacks),'old_methods':oldtotal,'equal_methods':same,'new_methods':len(new_methods),'expected_after_tree':final_tree},ensure_ascii=False))

if __name__=='__main__':main()
