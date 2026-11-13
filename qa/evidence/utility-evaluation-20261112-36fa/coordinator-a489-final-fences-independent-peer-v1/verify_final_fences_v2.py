"""Independent pure byte/AST/lexical review of the frozen c026 fence proposal.

No project module, test method, collector, verifier entry point, native command,
preflight or source file is executed/modified. Only explicitly listed lexical
FunctionDefs are compiled into an isolated namespace. Writes are this peer's
derived observations in its own directory.
"""
from __future__ import annotations
import ast
import base64
import copy
import gzip
import hashlib
import json
from pathlib import Path
import re
import tomllib
from types import SimpleNamespace
from review_primitives import identity, require_pin, tree, pure_namespace, changed_leaves, constants, methods

HERE=Path(__file__).resolve().parent
FROZEN=Path('/tmp/hepta-36fa-a489-maintenance-registration-frozen-v1')
PREP=Path('/tmp/hepta-36fa-a489-maintenance-registration-refresh-v1')
RUNTIME=Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')
INVENTORY=Path('/tmp/hepta-36fa-a489-actual-maintenance-source-review-v1/final.inventory.exact_recovered.json')
AGENT='codex-rs/hepta-agentd/src/'
QA='qa/b4-no-bypass/'

def pinrow(row):
    return {'bytes':row['bytes'],'sha256':row['sha256'],'git_blob':row['working_blob']}

def save(name,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    path=HERE/name
    if path.exists():
        assert path.read_bytes()==raw,('create-only derived evidence changed',str(path))
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(raw)
    return identity(raw)

def main():
    manifestraw=(HERE/'inputs/MANIFEST.json').read_bytes()
    assert identity(manifestraw)['git_blob']=='4bc60fab145563469f1cbb992feeaf216d58dfb5'
    manifest=json.loads(manifestraw)
    require_pin((HERE/'inputs/AUTHOR_REVIEW.json').read_bytes(),manifest['review'])
    # Repeat decoding over the complete independently GET-returned UTF8 leaves.
    decoded=[];offset=0;input_gets=[]
    for part in manifest['source_packet']['parts']:
        raw=(HERE/'inputs'/part['name']).read_bytes();require_pin(raw,part)
        sdkraw=(HERE/'github'/(part['name']+'.GET.original.json')).read_bytes()
        sdk=json.loads(sdkraw);assert sdk['structuredContent']['content'].encode()==raw
        assert raw.endswith(b'\n') and raw.count(b'\n')==1
        payload=base64.b64decode(raw[:-1],validate=True)
        assert base64.b64encode(payload)+b'\n'==raw
        require_pin(payload,part['decoded']);assert part['decoded_offset']==offset
        offset+=len(payload);decoded.append(payload)
        input_gets.append({'name':part['name'],'body':identity(raw),'sdk':identity(sdkraw),'full_readback_equal':True})
    compressed=b''.join(decoded);require_pin(compressed,manifest['source_packet']['gzip'])
    packetraw=gzip.decompress(compressed);require_pin(packetraw,manifest['source_packet']['raw'])
    assert packetraw==(HERE/'inputs/SOURCE_PACKET.exact_from_full_get.json').read_bytes()==(FROZEN/'SOURCE_PACKET.json').read_bytes()
    packet=json.loads(packetraw)
    assert packet['qualification'] is False and packet['execution_approval'] is False
    assert packet['H_calls']==packet['qa_or_project_gate_executions']==0
    assert type(packet['Rust_source_changes']) is int and packet['Rust_source_changes']==0 and packet['canonical_source_deletions']==[]
    assert packet['all_seven_fence_bindings']==manifest['fence_bindings']
    invraw=INVENTORY.read_bytes();require_pin(invraw,packet['base_inventory'])
    inventory=json.loads(invraw);rows={r['path']:r for r in inventory['files']}
    assert len(rows)==len(inventory['files'])==inventory['filesystem_entries']==inventory['tracked_entries']==15243
    assert inventory['source']['head']=='d25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
    assert inventory['source']['tree']=='a489b394666b8141840275128a780605b024cde0'
    leaves={p:(r['index_mode'],r['working_blob']) for p,r in rows.items()}
    assert tree(leaves)==packet['base_physical_tree']=='c026a8d7e93c958b39a36c666debecb3dba4be14'
    changed={};bindings={};sourcepins=[]
    for row in packet['changes']:
        path=row['path'];assert path not in changed
        bodies=[]
        for side in ('before','after'):
            raw=base64.b64decode(row[side+'_raw_base64'],validate=True)
            require_pin(raw,pinrow(row[side]));assert raw==(FROZEN/side/path).read_bytes()
            bodies.append(raw)
        assert row['before']==rows[path]
        samefields=set(row['before'])-{'bytes','sha256','working_blob','matches_index'}
        assert all(row['before'][k]==row['after'][k] for k in samefields)
        assert row['before']['matches_index'] is True and row['after']['matches_index'] is False
        assert row['before']['index_mode']=='100644' and row['before']['kind']=='file'
        assert row['after']['permissions']==420 and row['after']['stable'] is True
        changed[path]=tuple(bodies)
        leaves[path]=(row['after']['index_mode'],row['after']['working_blob'])
        sourcepins.append({k:v for k,v in row.items() if 'base64' not in k})
    assert len(changed)==4
    for binding in manifest['fence_bindings']:
        path=binding['path'];before,after=changed.get(path,((FROZEN/'before'/path).read_bytes(),(FROZEN/'after'/path).read_bytes()))
        require_pin(before,binding['before']);require_pin(after,binding['after']);require_pin(before,pinrow(rows[path]))
        if binding['operation']=='unchanged':assert before==after and path not in changed
        else:assert binding['operation']=='modify' and path in changed
        bindings[path]=(before,after)
    assert len(bindings)==7 and sum(x['operation']=='unchanged' for x in manifest['fence_bindings'])==3
    final_tree=tree(leaves);assert final_tree==packet['expected_after_physical_tree']=='8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
    assert packet['expected_after_leaf_count']==15243
    projection=copy.deepcopy(inventory)
    newrows={r['path']:r['after'] for r in packet['changes']}
    projection['files']=[newrows.get(r['path'],r) for r in inventory['files']]
    projection['source']['status']='\n'.join(' M '+r['path'] for r in projection['files'] if not r['matches_index']).strip()
    projectedraw=(json.dumps(projection,sort_keys=True,indent=2)+'\n').encode()
    require_pin(projectedraw,packet['expected_after_inventory'])
    assert sum(a!=b for a,b in zip(inventory['files'],projection['files']))==4
    # All Rust source material is bound to the original actual final transition.
    transitionraw=(RUNTIME/'final.postimages.json').read_bytes()
    require_pin(transitionraw,{'bytes':665433,'git_blob':'88b9299120113937610da4a84b344eda76011674','sha256':'732c48099edc5a704f3aab74d91f997b98f92fdd122adbf49d31b750b77e28a8'})
    transition=json.loads(transitionraw);actual={}
    for change in transition['changes']:
        values=[]
        for side in ('before','after'):
            raw=base64.b64decode(change[side+'_raw_base64'],validate=True);require_pin(raw,pinrow(change[side]));values.append(raw)
        assert change['after']==rows[change['path']]
        actual[change['path']]=tuple(values)
    assert len(actual)==17
    source_observations={}
    def source(path,side='after'):
        if path in actual:
            raw=actual[path][0 if side=='before' else 1];basis='actual maintenance final transition '+side
        else:
            raw=(PREP/'before'/path).read_bytes();require_pin(raw,pinrow(rows[path]));basis='unchanged file bound to exact actual full inventory'
        if side=='after':require_pin(raw,pinrow(rows[path]))
        source_observations[(path,side)]={'path':path,'side':side,'identity':identity(raw),'basis':basis}
        return raw.decode()
    scannerraw=(PREP/'before/scripts/verify_hepta_callers.py').read_bytes()
    require_pin(scannerraw,pinrow(rows['scripts/verify_hepta_callers.py']))
    class LexicalError(Exception):pass
    scanner_names=['_strip_rust_non_code','_looks_like_char_literal','_strip_cfg_test_items','_matching_delimiter','_cfg_without_test','_skip_space','_rust_item_end']
    scanner=pure_namespace(scannerraw,scanner_names,{'re':re,'RAW_STRING_START':re.compile(r'r(#{0,255})"'),'VerificationFailure':LexicalError})
    proof=SimpleNamespace(**{n:scanner[n] for n in scanner_names},VerificationFailure=LexicalError)
    ordinaryraw=bindings[QA+'test_evaluated_published_read_source_closure.py'][0]
    scope_names=['ordinary_require','ordinary_depth_at','ordinary_body_open','ordinary_item_end','ordinary_root_containers','ordinary_function_location','ordinary_select_scope','ordinary_without_nested_functions','ordinary_literal_span','ordinary_mount_span']
    scopes=pure_namespace(ordinaryraw,scope_names,{'re':re,'PROOF':proof})
    scopes_obj=SimpleNamespace(**{n:scopes[n] for n in scope_names})
    providerraw=bindings[QA+'test_resident_provider_local_read_source_closure.py'][0]
    provider_names=['require','active_source','actual_scope','module_shape']
    provider=pure_namespace(providerraw,provider_names,{'re':re,'PROOF':proof,'SCOPES':scopes_obj})
    active=provider['active_source']
    old,new=[tomllib.loads(raw.decode()) for raw in bindings['CALLERS.toml']]
    assert old.keys()==new.keys()
    for k in old:
        if k!='protected_file':assert old[k]==new[k],k
    assert len(new['boundary'])==len({r['id'] for r in new['boundary']})==633
    required=new['privileged_inventory']['required_boundary_ids']
    assert len(required)==len(set(required))==633 and set(required)=={r['id'] for r in new['boundary']}
    assert all(v is False for v in new['authority'].values())
    assert new['source_roots']==['codex-rs']
    assert new['ignored_path_fragments']==['/tests/','/examples/','_tests.rs']
    assert len(old['protected_file'])==len(new['protected_file'])==442
    assert old['protected_file'][411]==new['protected_file'][411]
    assert old['protected_file'][422]==new['protected_file'][422]
    changed_rows=[];markerobs=[]
    for i,(a,b) in enumerate(zip(old['protected_file'],new['protected_file'])):
        assert a['forbidden']==b['forbidden']
        delta=changed_leaves(a,b)
        if not delta:continue
        changed_rows.append(i);path=a['path'];assert path in actual
        acode,_=active(source(path,'before'));bcode,_=active(source(path))
        for field,x,y in delta:
            assert isinstance(x,str) and isinstance(y,str)
            assert field[0] in ('required_function_order','required_order'),field
            if field[0]=='required_function_order':
                assert field[2:]==('sequence',1),field
                ga=a[field[0]][field[1]];gb=b[field[0]][field[1]]
                assert {k:v for k,v in ga.items() if k!='sequence'}=={k:v for k,v in gb.items() if k!='sequence'}
                assert len(ga['sequence'])==len(gb['sequence'])==2 and ga['sequence'][0]==gb['sequence'][0]=='fn '
                marker=ga['function'];assert acode.count(marker)==bcode.count(marker)==1
                lo=acode.index(marker);hi=proof._rust_item_end(acode,lo)+1
                la=bcode.index(marker);ha=proof._rust_item_end(bcode,la)+1
                assert ''.join(ga['sequence'])==acode[lo:hi]
                assert ''.join(gb['sequence'])==bcode[la:ha]
                selected={'kind':'full original function','name':marker}
            else:
                assert field[2:]==(1,),field
                sa=a[field[0]][field[1]];sb=b[field[0]][field[1]]
                assert len(sa)==len(sb)==2 and sa[0]==sb[0]
                fa=''.join(sa);fb=''.join(sb)
                assert acode.count(fa)==bcode.count(fb)==1
                lo=acode.index(fa);hi=proof._rust_item_end(acode,lo)+1
                la=bcode.index(fb);ha=proof._rust_item_end(bcode,la)+1
                assert acode[lo:hi]==fa and bcode[la:ha]==fb
                assert scopes['ordinary_depth_at'](acode,lo)==scopes['ordinary_depth_at'](bcode,la)==(0,0,0)
                selected={'kind':'full original root item','prefix':sa[0]}
            markerobs.append({'row':i,'path':path,'field':list(field),'before':identity(x.encode()),'after':identity(y.encode()),'scope':selected,'before_range':[lo,hi],'after_range':[la,ha]})
    assert changed_rows==[429,438,440] and len(markerobs)==9
    ac,bc=[json.loads(raw) for raw in bindings[QA+'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json']]
    assert set(bc)-set(ac)=={'actual_maintenance_refresh'} and set(ac)<=set(bc)
    for k in ac:
        if k!='scopes':assert ac[k]==bc[k],k
    assert bc['actual_maintenance_refresh']=={
        'actual_final_physical_tree':'c026a8d7e93c958b39a36c666debecb3dba4be14',
        'actual_final_postimages':'88b9299120113937610da4a84b344eda76011674',
        'actual_result':'b87aed7647ac34e3db0e381110bf685438aee0ee',
        'base_physical_tree':'a489b394666b8141840275128a780605b024cde0',
        'no_new_scope_selector_boundary_or_attack':True,'qualification':False,
        'source_commit':'d25675445c39f76db69a7bd8e71a1a72e1cd5b9f'}
    assert ac['scopes'].keys()==bc['scopes'].keys() and len(bc['scopes'])==45
    checked={k:new[k] for k in ('boundary','privileged_inventory','authority','source_roots','ignored_path_fragments')}
    boundarysha=hashlib.sha256(json.dumps(checked,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert bc['boundary_count']==633 and bc['complete_boundary_sha256']==boundarysha
    assert new['boundary'][569:]==bc['new_boundaries']
    scopeobs=[];changed_scopes=[];shapeobs=[]
    for path,guards in bc['scopes'].items():
        beforetext=source(path,'before');aftertext=source(path)
        acode,aliteral=active(beforetext);bcode,bliteral=active(aftertext)
        assert provider['module_shape'](acode,aliteral)==ac['module_shapes'][path]
        assert provider['module_shape'](bcode,bliteral)==bc['module_shapes'][path]
        assert len(guards)==len(ac['scopes'][path])
        shapeobs.append({'path':path,'before_and_after_shape_equal':True,'declarations_and_final_tail':len(bc['module_shapes'][path])})
        for i,(ga,gb) in enumerate(zip(ac['scopes'][path],guards)):
            assert {k:v for k,v in ga.items() if k not in ('masked_sha256','literal_source_sha256')}=={k:v for k,v in gb.items() if k not in ('masked_sha256','literal_source_sha256')}
            ranges={}
            for side,guard,code,literal in [('before',ga,acode,aliteral),('after',gb,bcode,bliteral)]:
                lo,hi=provider['actual_scope'](code,guard['selector'])
                assert hashlib.sha256(code[lo:hi].encode()).hexdigest()==guard['masked_sha256'],(path,i,side,'masked')
                assert hashlib.sha256(literal[lo:hi].encode()).hexdigest()==guard['literal_source_sha256'],(path,i,side,'literal')
                ranges[side]={'range':[lo,hi],'masked_sha256':guard['masked_sha256'],'literal_source_sha256':guard['literal_source_sha256']}
            item={'path':path,'index':i,'selector':gb['selector'],**ranges,'changed':ga!=gb};scopeobs.append(item)
            if ga!=gb:changed_scopes.append(item)
    assert len(scopeobs)==288 and len(changed_scopes)==5
    mountobs=[]
    for path,values in bc['mounts'].items():
        for spec in values:
            before=scopes['ordinary_mount_span'](proof,active(source(path,'before'))[0],source(path,'before'),spec)
            after=scopes['ordinary_mount_span'](proof,active(source(path))[0],source(path),spec)
            mountobs.append({'path':path,'spec':spec,'before':before,'after':after})
    lib=source(AGENT+'lib.rs');libcode,_=active(lib)
    for export in bc['exports']:
        assert lib.count(export)==libcode.count(export)==1
        assert scopes['ordinary_depth_at'](libcode,libcode.index(export))==(0,0,0)
    attacks=[]
    assert ac['attacks']==bc['attacks']
    for group,cases in bc['attacks'].items():
        for case in cases:
            marker=case['marker'];pattern=r'\s*'.join(re.escape(t) for t in re.findall(r'\w+|[^\w\s]',marker))
            if marker[0].isalnum() or marker[0]=='_':pattern=r'(?<!\w)'+pattern
            if marker[-1].isalnum() or marker[-1]=='_':pattern+=r'(?!\w)'
            targets={}
            for side in ('before','after'):
                code,_=active(source(case['path'],side))
                span=scopes['ordinary_select_scope'](proof,code,{'kind':'unique_function','name':case['function']})
                matches=list(re.finditer(pattern,code[span['start']:span['end']]))
                assert matches,(group,case,side)
                targets[side]={'real_scope':span,'ranges':[[span['start']+m.start(),span['start']+m.end()] for m in matches]}
            assert len(targets['before']['ranges'])==len(targets['after']['ranges'])
            attacks.append({'group':group,'case':case,**targets,'target_count':len(targets['after']['ranges'])})
    assert len(attacks)==107
    ordinary=constants(ordinaryraw)
    assert ordinary==constants(bindings[QA+'test_evaluated_published_read_source_closure.py'][1])
    assert ordinary['ORDINARY_COMPLETE_BOUNDARY_SHA256']==boundarysha
    assert ordinary['ORDINARY_NEW_BOUNDARIES']==new['boundary'][541:569]
    ordinaryscopes=[]
    for path,guards in ordinary['ORDINARY_SCOPE_GUARDS'].items():
        for guard in guards:
            found={}
            for side in ('before','after'):
                code,_=active(source(path,side));span=scopes['ordinary_select_scope'](proof,code,guard['selector'])
                actualsha=hashlib.sha256(code[span['start']:span['end']].encode()).hexdigest()
                assert actualsha==guard['masked_sha256'];found[side]=span
            ordinaryscopes.append({'path':path,'guard':guard,**found})
    assert len(ordinaryscopes)==34
    literals=[]
    for spec in ordinary['ORDINARY_LITERAL_SPECS']:
        found={}
        for side in ('before','after'):
            text=source(spec['path'],side);code,_=active(text)
            found[side]=scopes['ordinary_literal_span'](proof,code,text,spec)
        literals.append({'spec':spec,**found})
    assert len(literals)==17
    ordinarymounts=[]
    for spec in ordinary['ORDINARY_MODULE_MOUNTS']:
        text=source(spec['parent']);code,_=active(text)
        ordinarymounts.append({'spec':spec,**scopes['ordinary_mount_span'](proof,code,text,spec)})
    assert len(ordinarymounts)==10
    qaobs=[];methodcount=helpercount=0
    qapaths=sorted((PREP/'before/qa/b4-no-bypass').glob('*.py'));assert len(qapaths)==64
    for path in qapaths:
        name=QA+path.name;before=path.read_bytes();require_pin(before,pinrow(rows[name]))
        after=bindings[name][1] if name in bindings else before
        om,oh=methods(before);nm,nh=methods(after)
        assert om==nm and oh==nh,name
        methodcount+=len(om);helpercount+=len(oh)
        qaobs.append({'path':name,'before':identity(before),'after':identity(after),'methods_byte_and_ast_equal':len(om),'top_level_helpers_byte_equal':len(oh)})
    assert methodcount==607
    providerbefore,providerafter=bindings[QA+'test_resident_provider_local_read_source_closure.py']
    oldsha=identity(bindings[QA+'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'][0])['sha256'].encode()
    newsha=identity(bindings[QA+'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'][1])['sha256'].encode()
    assert providerbefore.count(oldsha)==1 and providerafter.count(newsha)==1
    assert providerafter.replace(newsha,oldsha,1)==providerbefore
    # Whole workflow and ordinary/Root QA remain byte-identical; all budgets,
    # flags, caller collectors and method statements therefore remain in place.
    wfpath='.github/workflows/hepta-daemon-learning-native.yml';wb,wa=bindings[wfpath];assert wb==wa
    match=re.search(r'parents\s*=\s*(\[.*?\])',wa.decode(),re.DOTALL);assert match
    parents=ast.literal_eval(match.group(1));assert len(parents)==len(set(parents))==48
    rootconstants=constants(bindings[QA+'test_resident_root_source_closure.py'][0])
    assert rootconstants['ROOT_CUSTODY_CASES']==parents[39:]
    ignored='#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]'
    rootcaseobs=[]
    for fqn in parents[39:]:
        path=AGENT+('neuron_generation_initial_root_cold_tests.rs' if '::cold_tests::' in fqn else 'neuron_generation_initial_root_custody_tests.rs')
        text=source(path);name=fqn.rsplit('::',1)[-1]
        assert text.count('async fn '+name+'(')==1
        attributes=re.search(r'((?:#\[[^\]]+\]\s*)+)async\s+fn\s+'+re.escape(name)+r'\(',text)
        assert attributes and ignored in attributes.group(1)
        rootcaseobs.append({'fqn':fqn,'path':path,'ignored_attribute_preserved':True})
    alb,ala=bindings['.github/blob-size-allowlist.txt'];assert ala.startswith(alb)
    addition=ala[len(alb):]
    assert addition==b'# Exact actual a489 scoped-fix and format source guard refresh; no wildcard.\nsha256:'+identity(bindings['CALLERS.toml'][1])['sha256'].encode()+b' CALLERS.toml\n'
    # Full scanner/helper bytes bind to actual inventory, not an edited parser.
    original_scanners=[]
    for name in ['verify_hepta_callers.py','hepta_typed_callers.py','hepta_main_protection.py','hepta_source_registry_closure.py','hepta_c_observer_coverage.py']:
        path='scripts/'+name;raw=(PREP/'before'/path).read_bytes();require_pin(raw,pinrow(rows[path]));original_scanners.append({'path':path,**identity(raw)})
    observations={
      'format':'hepta-c026-final-nonrust-fences-independent-byte-scope-review-v1',
      'status':'OFFLINE_STATIC_REVIEW_COMPLETE_NO_PROJECT_GATE_EXECUTION',
      'manifest':identity(manifestraw),'source_packet':identity(packetraw),'packet_full_get_parts':input_gets,
      'actual_inventory':identity(invraw),'actual_transition':identity(transitionraw),
      'base_physical_tree':packet['base_physical_tree'],'expected_after_physical_tree':final_tree,
      'expected_inventory':identity(projectedraw),'expected_leaves':len(leaves),'source_changes':sourcepins,
      'seven_bindings':manifest['fence_bindings'],'unchanged_non_update_entries':15239,
      'all_633_boundaries_and_required_ids_exact':True,'all_nonprotected_manifest_fields_equal':True,
      'protected_rows':442,'unchanged_protected_rows':439,'changed_protected_rows':changed_rows,
      'all_forbidden_arrays_and_nonmarker_extra_constraints_unchanged':True,
      'duplicate_paths_and_order_preserved':True,'rows_411_and_422_byte_semantics_unchanged':True,
      'full_scope_marker_values':markerobs,
      'provider_paths':45,'provider_scope_count':288,'scope_observations':scopeobs,'changed_scope_digests':changed_scopes,
      'provider_module_shapes_unchanged_and_bound_to_both_sources':shapeobs,
      'provider_mounts':mountobs,'all_public_export_strings_root_and_unique':bc['exports'],
      'actual_maintenance_refresh_added':bc['actual_maintenance_refresh'],'prior_source_refresh_basis_preserved':bc['source_refresh_basis'],
      'attack_specs_unchanged':107,'attack_target_observations':attacks,'total_attack_target_occurrences':sum(x['target_count'] for x in attacks),
      'ordinary_scopes':ordinaryscopes,'ordinary_literals':literals,'ordinary_mounts':ordinarymounts,
      'qa_files':64,'qa_methods':methodcount,'qa_methods_byte_and_ast_equal':True,'top_level_helpers_byte_equal':helpercount,'qa_observations':qaobs,
      'provider_qa_only_exact_contract_sha_replacement':True,'workflow_bytes_unchanged':True,'root_parents':parents,'nine_root_methods_still_explicitly_ignored':rootcaseobs,
      'allowlist_exact_append':addition.decode(),'scanner_inputs':original_scanners,
      'lexical_helper_source_pins':{'scanner':identity(scannerraw),'ordinary':identity(ordinaryraw),'provider':identity(providerraw)},
      'lexical_function_whitelists':[scanner_names,scope_names,provider_names],
      'all_bound_source_inputs':sorted(source_observations.values(),key=lambda x:(x['path'],x['side'])),
      'H_calls':0,'project_module_imports':0,'QA_test_methods_executed':0,'mutants_executed':0,
      'full_collector_executions':0,'Rust_compiler_or_formatter_executions':0,'source_or_ref_mutations':0,'qualification':False,
      'limitations':['Exact static marker target counts do not establish mutant rejection at runtime.','No full repository collector, source gate, native gate, Rust build or test was executed.','Expected tree/inventory is a pure four-write projection; no apply/format/source publication approval is conveyed.','The actual maintenance final inventory is exact original-byte recovery, not a second native full read.','Existing Root product integration and external original owner material requirements remain outside this fence refresh.']}
    result=save('FROZEN_BYTE_AND_SCOPE_REVIEW.json',observations)
    print(json.dumps({'report':str(HERE/'FROZEN_BYTE_AND_SCOPE_REVIEW.json'),**result,'boundaries':633,'protected':442,'changed_rows':changed_rows,'marker_values':9,'provider_scopes':288,'attack_specs':107,'attack_occurrences':observations['total_attack_target_occurrences'],'QA_methods_equal':methodcount,'root_parents':len(parents),'expected_tree':final_tree}))

if __name__=='__main__':main()
