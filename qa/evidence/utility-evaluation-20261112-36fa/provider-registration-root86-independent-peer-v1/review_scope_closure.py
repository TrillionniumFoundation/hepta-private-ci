"""Static projections on the fixed partial overlay; no candidate or QA execution."""
import ast, hashlib, json, re, types
from pathlib import Path

BASE=Path('/tmp/hepta-36fa-provider-registration-rebuilt-v3')
FROZEN=Path('/tmp/hepta-36fa-provider-registration-root86-frozen-v3')
OUT=Path('/tmp/hepta-36fa-provider-registration-root86-native-peer-v1')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def verify_pin(b,p):assert pin(b)=={k:p[k]for k in ('bytes','sha256','git_blob')}
packet_raw=(FROZEN/'SOURCE_PACKET.json').read_bytes();assert pin(packet_raw)['git_blob']=='fab488b846bb1b1ef7a42b9b30be5773054e1a6a'
packet=json.loads(packet_raw);changes={r['path']:r for r in packet['source_changes']}
contract=json.loads(changes['qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json']['after_content'])
original_path=BASE/'before/scripts/verify_hepta_callers.py'
original=original_path.read_text();assert pin(original.encode())['git_blob']=='c66fb1f90a61deaa6461f0c7155209ed32903e62'
lex_names={'_strip_rust_non_code','_cfg_without_test','_strip_cfg_test_items','_matching_delimiter','_skip_space','_rust_item_end','_looks_like_char_literal'}
nodes=[n for n in ast.parse(original).body if isinstance(n,ast.FunctionDef)and n.name in lex_names]
assert len(nodes)==7
class VerificationFailure(Exception):pass
ns={'re':re,'RAW_STRING_START':re.compile(r'r(#{0,255})"'),'VerificationFailure':VerificationFailure}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'unchanged_original_lexical_definitions_only','exec'),ns)
proof=types.SimpleNamespace(**{name:ns[name]for name in lex_names},VerificationFailure=VerificationFailure)
old_scope=changes['qa/b4-no-bypass/test_evaluated_published_read_source_closure.py']['before_content']
pure_nodes=[n for n in ast.parse(old_scope).body if isinstance(n,ast.FunctionDef)and n.name.startswith('ordinary_')]
scope_ns={'PROOF':proof,'re':re};exec(compile(ast.Module(body=pure_nodes,type_ignores=[]),'unchanged_original_scope_definitions_only','exec'),scope_ns)

def lexical_view(raw):
    masked=proof._strip_rust_non_code(raw);code=proof._strip_cfg_test_items(masked)
    kept=list(raw);removed=[];cursor=0
    for m in re.finditer(r'#\[',masked):
        if m.start()<cursor:continue
        end=proof._matching_delimiter(masked,m.start()+1,'[',']');assert end is not None
        cfg=re.fullmatch(r'#\[\s*cfg\s*\((.*)\)\s*\]',masked[m.start():end+1],re.S)
        if cfg is None or proof._cfg_without_test(cfg.group(1)) is not False:continue
        start_item=end+1
        while True:
            start_item=proof._skip_space(masked,start_item)
            if not masked.startswith('#[',start_item):break
            end_attr=proof._matching_delimiter(masked,start_item+1,'[',']');assert end_attr is not None
            start_item=end_attr+1
        finish=proof._rust_item_end(masked,start_item);assert finish is not None
        for i in range(m.start(),finish+1):
            if kept[i]!='\n':kept[i]=' '
        cursor=finish+1;removed.append([m.start(),cursor])
    kept=''.join(kept);assert proof._strip_rust_non_code(kept)==code
    depths=[];brace=paren=bracket=0
    for ch in code:
        depths.append((brace,paren,bracket))
        if ch=='{':brace+=1
        elif ch=='}':brace-=1
        elif ch=='(':paren+=1
        elif ch==')':paren-=1
        elif ch=='[':bracket+=1
        elif ch==']':bracket-=1
        assert min(brace,paren,bracket)>=0
    assert (brace,paren,bracket)==(0,0,0)
    return code,kept,depths,removed

def root_start(code,offset):
    i=code.rfind('\n',0,offset)+1
    while code[i].isspace():i+=1
    return i

def select(code,depths,s):
    k=s['kind']
    if k=='root_type':
        span=scope_ns['ordinary_select_scope'](proof,code,s);return span['start'],span['end']
    if k=='root_container':
        candidates=[x for x in scope_ns['ordinary_root_containers'](proof,code)if x['header']==s['header']]
        if s.get('anchor'):
            pat=r'\bfn\s+'+re.escape(s['anchor'])+r'\s*(?=[(<])'
            candidates=[x for x in candidates if len(re.findall(pat,code[x['opening']+1:x['end']-1]))==1]
        assert len(candidates)==1,s
        return candidates[0]['start'],candidates[0]['end']
    if k=='root_function':
        matches=[m for m in re.finditer(r'\bfn\s+'+re.escape(s['name'])+r'\s*(?=[(<])',code)if depths[m.start()]==(0,0,0)]
        assert len(matches)==1,s;start=root_start(code,matches[0].start());end=proof._rust_item_end(code,matches[0].start())
        assert end is not None and code[end]=='}';return start,end+1
    if k=='root_named_item':
        pat=r'(?m)^[ \t]*(?:pub(?:\([^)]*\))?\s+)?'+re.escape(s['item_kind'])+r'\s+'+re.escape(s['name'])+r'\b'
        matches=[m for m in re.finditer(pat,code)if depths[root_start(code,m.start())]==(0,0,0)]
        assert len(matches)==1,s;start=root_start(code,matches[0].start());end=proof._rust_item_end(code,start);assert end is not None
        return start,end+1
    raise AssertionError(s)

path_rows=[];gaps=[];all_spans={};attack_rows=[]
for path,guards in contract['scopes'].items():
    raw=(BASE/'view-root86'/path).read_text();code,kept,depths,removed=lexical_view(raw);spans=[]
    for guard in guards:
        a,b=select(code,depths,guard['selector'])
        assert hashlib.sha256(code[a:b].encode()).hexdigest()==guard['masked_sha256'],(path,guard)
        assert hashlib.sha256(kept[a:b].encode()).hexdigest()==guard['literal_source_sha256'],(path,guard)
        spans.append({'start':a,'end':b,'selector':guard['selector']})
    all_spans[path]=spans
    root_items=[];cursor=0;shape=[]
    for m in re.finditer(r'\b(?:use|mod|type|const|static|struct|enum|trait|impl|fn|extern|macro_rules)\b',code):
        if m.start()<cursor or depths[m.start()]!=(0,0,0):continue
        end=proof._rust_item_end(code,m.start());assert end is not None
        prefix=code[cursor:m.start()];attributes=[]
        for a in re.finditer(r'#\[',prefix):
            start=cursor+a.start();stop=proof._matching_delimiter(code,start+1,'[',']');assert stop is not None and stop<m.start()
            attributes.append(kept[start:stop+1])
        full=code[end]!='}' or m.group() in ('use','mod','type','const','static','extern','macro_rules')
        opening=None if full else scope_ns['ordinary_body_open'](code,m.start(),end)
        identity=' '.join(code[m.start():end+1 if full else opening].split())
        shape.append({'prefix':' '.join(prefix.split()),'attributes':attributes,'identity':identity})
        owners=[s for s in spans if s['start']<=m.start() and end+1<=s['end']]
        # Every root body omitted from module shape must be covered by a full
        # masked+literal scope. Every constant/static must also retain literals.
        needs_scope=not full or m.group() in ('const','static','macro_rules','extern')
        if needs_scope and not owners:gaps.append({'path':path,'kind':m.group(),'identity':identity,'start':m.start(),'end':end+1})
        root_items.append({'kind':m.group(),'identity':identity,'body_fixed_by_scope':bool(owners),'whole_masked_identity':full})
        cursor=end+1
    shape.append({'tail':' '.join(code[cursor:].split())})
    assert shape==contract['module_shapes'][path],path
    path_rows.append({'path':path,'source':pin(raw.encode()),'scopes':spans,'root_items':root_items,'removed_test_items':removed,'module_shape_matches':True})
    for group,cases in contract['attacks'].items():
        for case in cases:
            if case['path']!=path:continue
            span=scope_ns['ordinary_select_scope'](proof,code,{'kind':'unique_function','name':case['function']})
            tokens=re.findall(r'\w+|[^\w\s]',case['marker']);pat=r'\s*'.join(map(re.escape,tokens))
            if case['marker'][0].isalnum()or case['marker'][0]=='_':pat=r'(?<!\w)'+pat
            if case['marker'][-1].isalnum()or case['marker'][-1]=='_':pat+=r'(?!\w)'
            matches=list(re.finditer(pat,code[span['start']:span['end']]))
            assert matches,(path,case)
            containers=[s for s in spans if s['start']<=span['start'] and span['end']<=s['end']]
            assert containers,(path,case)
            attack_rows.append({'group':group,**case,'matches':len(matches),'full_scope_covers_function':True})

result={'status':'STATIC_ORIGINAL_LEXICAL_PROJECTIONS_ONLY_NOT_QA_EXECUTION','packet':pin(packet_raw),'original_lexer':pin(original.encode()),'loaded_original_pure_lexical_functions':sorted(lex_names),'loaded_original_pure_scope_functions':[n.name for n in pure_nodes],
 'candidate_functions_executed':0,'candidate_imports':0,'qa_methods_executed':0,'full_source_scan_executed':False,'paths':path_rows,'all_scope_hashes_verified':sum(len(r['scopes'])for r in path_rows),'all_module_shapes_verified':len(path_rows),'uncovered_root_body_or_literal_items':gaps,'attack_specs':attack_rows,'counterexample_execution':0}
target=OUT/'STATIC_SCOPE_CLOSURE_REVIEW.json';target.open('x').write(json.dumps(result,indent=2)+'\n')
print(json.dumps({'output':str(target),'pin':pin(target.read_bytes()),'scopes':result['all_scope_hashes_verified'],'module_shapes':len(path_rows),'attacks':len(attack_rows),'gaps':gaps,'candidate_executions':0}))
