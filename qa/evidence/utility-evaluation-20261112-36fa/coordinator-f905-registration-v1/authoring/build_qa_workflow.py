#!/usr/bin/env python3
"""Prepare QA constants and exact Root parent registration; do not run them."""
from pathlib import Path
import ast, copy, hashlib, importlib.util, json, pprint, re, sys, textwrap, tomllib
sys.dont_write_bytecode=True
R=Path(__file__).resolve().parent;QA='qa/b4-no-bypass/';AGENT='codex-rs/hepta-agentd/src/'
def pin(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def save(path,raw):
 raw=raw.encode() if isinstance(raw,str) else raw;p=R/'after'/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);return pin(raw)
def report(name,value):(R/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
def assign(text,name):
 matches=[node for node in ast.parse(text).body if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id==name]
 assert len(matches)==1,name
 return matches[0]
def offsets(text,node):
 lines=text.splitlines(keepends=True)
 return sum(len(x) for x in lines[:node.lineno-1])+len(lines[node.lineno-1].encode()[:node.col_offset].decode()),sum(len(x) for x in lines[:node.end_lineno-1])+len(lines[node.end_lineno-1].encode()[:node.end_col_offset].decode())
def replace_value(text,name,value):
 node=assign(text,name).value;a,b=offsets(text,node);return text[:a]+pprint.pformat(value,width=100,sort_dicts=False)+text[b:]
spec=importlib.util.spec_from_file_location('qa_original_lexical_only',R/'before/scripts/verify_hepta_callers.py')
P=importlib.util.module_from_spec(spec);sys.modules[spec.name]=P;spec.loader.exec_module(P)
scope_path=QA+'test_evaluated_published_read_source_closure.py';scope_text=(R/'before'/scope_path).read_text()
defs=[n for n in ast.parse(scope_text).body if isinstance(n,ast.FunctionDef) and n.name.startswith('ordinary_')]
ns={'PROOF':P,'re':re};exec(compile(ast.Module(body=defs,type_ignores=[]),'original_ordinary_helpers_only','exec'),ns)
contract_raw=(R/'after'/QA/'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json').read_bytes();contract=json.loads(contract_raw)
manifest=tomllib.loads((R/'after/CALLERS.toml').read_text())
coverage=json.loads(Path('/tmp/hepta-36fa-coordinator-f905-preparation-v1/ROOT_PHASE_COVERAGE_PREPARATION.json').read_text())
root_cases=coverage['proposed_append'];assert len(root_cases)==9

# Existing ordinary selector data is independently checked against its precise
# pre-format body before replacing only the actual new masked hash values.
old_scopes=ast.literal_eval(assign(scope_text,'ORDINARY_SCOPE_GUARDS').value)
new_scopes=copy.deepcopy(old_scopes);scope_updates=[]
for path,guards in new_scopes.items():
 before_path=R/'pre-format'/path
 old_raw=before_path.read_text() if before_path.exists() else (R/'before'/path).read_text()
 new_raw=(R/'view'/path).read_text()
 old_code=P._strip_cfg_test_items(P._strip_rust_non_code(old_raw));new_code=P._strip_cfg_test_items(P._strip_rust_non_code(new_raw))
 for guard in guards:
  previous=ns['ordinary_select_scope'](P,old_code,guard['selector'])
  original_hash=hashlib.sha256(old_code[previous['start']:previous['end']].encode()).hexdigest()
  assert original_hash==guard['masked_sha256'],(path,guard['selector'])
  current=ns['ordinary_select_scope'](P,new_code,guard['selector'])
  observed=hashlib.sha256(new_code[current['start']:current['end']].encode()).hexdigest()
  if observed!=original_hash:scope_updates.append({'path':path,'selector':guard['selector'],'before':original_hash,'after':observed})
  guard['masked_sha256']=observed
ordinary=scope_text
node=assign(ordinary,'ORDINARY_SCOPE_GUARDS').value;a,b=offsets(ordinary,node);value=ordinary[a:b]
for item in scope_updates:
 assert value.count(item['before'])==1,item
 value=value.replace(item['before'],item['after'])
ordinary=ordinary[:a]+value+ordinary[b:]
ordinary=replace_value(ordinary,'ORDINARY_COMPLETE_BOUNDARY_SHA256',contract['complete_boundary_sha256'])
assert ast.literal_eval(assign(ordinary,'ORDINARY_NEW_BOUNDARIES').value)==manifest['boundary'][541:569]
old_count='self.assertEqual(len(boundaries), 621)';assert ordinary.count(old_count)==1
ordinary=ordinary.replace(old_count,'self.assertEqual(len(boundaries), 633)')
assert 'self.manifest["boundary"][541:569]' in ordinary
save(scope_path,ordinary)

# Provider's existing 13 methods and all original attack data remain untouched.
provider_path=QA+'test_resident_provider_local_read_source_closure.py'
provider=(R/'before'/provider_path).read_text()
old_contract=(R/'before'/QA/'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json').read_bytes()
old_hash=hashlib.sha256(old_contract).hexdigest();new_hash=hashlib.sha256(contract_raw).hexdigest()
assert provider.count(old_hash)==1;provider=provider.replace(old_hash,new_hash)
new_tests='''
    def test_root_custody_consumes_original_values_and_requires_real_root(self):
        self.attack_group("root_custody_consumption")

    def test_root_cold_entry_rechecks_original_publication_without_reprepare(self):
        self.attack_group("root_cold_original_recovery")

    def test_root_task_factory_keeps_original_task_cell_and_drain_custody(self):
        self.attack_group("root_task_same_cell")
'''
class_node=next(n for n in ast.parse(provider).body if isinstance(n,ast.ClassDef))
_,end=offsets(provider,class_node);provider=provider[:end]+'\n'+new_tests+provider[end:]
save(provider_path,provider)

# Preserve the original 39 parents byte-for-byte and append the nine complete
# FQNs. The unmodified native driver extracts this final list from workflow AST.
workflow_path='.github/workflows/hepta-daemon-learning-native.yml'
workflow=(R/'before'/workflow_path).read_text()
match=re.search(r'parents = (\[[\s\S]*?\n          \])',workflow);assert match
parents=ast.literal_eval(match.group(1));assert parents==coverage['original_parents'] and len(parents)==39
closing='          ]';before_list=match.group(1);assert before_list.endswith(closing)
indent=re.search(r'\n([ ]+)"',before_list).group(1)
after_list=before_list[:-len(closing)]+''.join(indent+json.dumps(name)+',\n' for name in root_cases)+closing
assert ast.literal_eval(after_list)==parents+root_cases
workflow=workflow[:match.start(1)]+after_list+workflow[match.end(1):]
save(workflow_path,workflow)

# Extend the exact old inventory assertion, without changing any of the prior
# Root cases, their source-selection branches, ignore counts or assertions.
root_path=QA+'test_resident_root_source_closure.py'
roots=(R/'before'/root_path).read_text();issuer=assign(roots,'ROOT_ISSUER_CASES');_,end=offsets(roots,issuer)
roots=roots[:end]+'\nROOT_CUSTODY_CASES = '+pprint.pformat(root_cases,width=100,sort_dicts=False)+roots[end:]
needle='        self.assertTrue(set(ROOT_ISSUER_CASES).issubset(parents))\n'
assert roots.count(needle)==1;roots=roots.replace(needle,needle+'        self.assertTrue(set(ROOT_CUSTODY_CASES).issubset(parents))\n')
old='self.assertEqual(len(parents), 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES))'
new='self.assertEqual(len(parents), 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES) + len(ROOT_CUSTODY_CASES))'
assert roots.count(old)==1;roots=roots.replace(old,new)
addition='''        task_support = (ROOT / (AGENT + "circuit_q24_task_test_support.rs")).read_text()
        custody_support = (ROOT / (AGENT + "neuron_generation_initial_root_custody_support_tests.rs")).read_text()
        custody = (ROOT / (AGENT + "neuron_generation_initial_root_custody_tests.rs")).read_text()
        cold = (ROOT / (AGENT + "neuron_generation_initial_root_cold_tests.rs")).read_text()
        self.assertIn(
            '#[path = "neuron_generation_initial_root_custody_support_tests.rs"]\\nmod root_initial_custody;',
            task_support,
        )
        self.assertIn(
            '#[path = "neuron_generation_initial_root_custody_tests.rs"]\\nmod tests;',
            custody_support,
        )
        self.assertIn(
            '#[path = "neuron_generation_initial_root_cold_tests.rs"]\\nmod cold_tests;',
            custody_support,
        )
        self.assertEqual(len(ROOT_CUSTODY_CASES), len(set(ROOT_CUSTODY_CASES)))
        self.assertTrue(set(ROOT_CUSTODY_CASES).isdisjoint(ROOT_CASES + ROOT_ISSUER_CASES))
        for name in ROOT_CUSTODY_CASES:
            source = cold if "::cold_tests::" in name else custody
            self.assertIn("async fn " + name.rsplit("::", 1)[-1] + "(", source)
        self.assertEqual(
            custody.count('#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]')
            + cold.count('#[ignore = "requires actual RootAuthorityDirectory and original signed owner fixtures"]'),
            len(ROOT_CUSTODY_CASES),
        )
'''
needle='        for marker in (\n            \'"codex-rs/hepta-neuron/**"\''
assert roots.count(needle)==1;roots=roots.replace(needle,addition+needle)
save(root_path,roots)

# Preserve every historical allowlist entry; append only the precise new blob.
allow_path='.github/blob-size-allowlist.txt';allow=(R/'before'/allow_path).read_text()
callers=(R/'after/CALLERS.toml').read_bytes();line='sha256:'+hashlib.sha256(callers).hexdigest()+' CALLERS.toml\n'
assert line not in allow
assert allow.endswith('\n')
save(allow_path,allow+'# Exact actual-format and original Root custody source guards; no wildcard.\n'+line)

def methods(text):
 return {(c.name,m.name):ast.get_source_segment(text,m) for c in ast.parse(text).body if isinstance(c,ast.ClassDef) for m in c.body if isinstance(m,ast.FunctionDef) and m.name.startswith('test_')}
changed=[];old_total=new_total=unchanged=0
for path in sorted((R/'before'/QA).glob('*.py')):
 relative=path.relative_to(R/'before').as_posix();before=path.read_text();target=R/'after'/relative;after=target.read_text() if target.exists() else before
 ast.parse(after);bm,am=methods(before),methods(after);assert bm.keys()<=am.keys(),relative
 old_total+=len(bm);new_total+=len(am);unchanged+=sum(bm[k]==am[k] for k in bm)
 if before!=after:changed.append({'path':relative,'before':pin(before.encode()),'after':pin(after.encode()),
   'old_methods_changed':[{'class':k[0],'method':k[1],'before':bm[k],'after':am[k]} for k in bm if bm[k]!=am[k]],
   'added_methods':[{'class':k[0],'method':k[1]} for k in am if k not in bm],'removed_methods':[]})
report('QA_WORKFLOW_CONSTRUCTION_REVIEW.draft.json',{'status':'STATIC_PREPARATION_NOT_QUALIFICATION','before_qa_files':64,
 'original_test_methods':old_total,'new_total_test_methods':new_total,'old_methods_byte_equal':unchanged,'deleted_methods':0,
 'ordinary_scope_updates':scope_updates,'old_28_boundary_slice_541_569_equal':True,'provider_extended_slice_569_end_exact':True,
 'all_83_original_provider_attack_specs_unchanged':True,'new_attack_specs':24,'new_qa_methods':3,'changed_files':changed,
 'workflow_original_parents':parents,'workflow_proposed_parents':parents+root_cases,'original39_order_and_bytes_preserved':True,
 'new_root_parents':root_cases,'root_phase_timeout_seconds':7200,'root_test_threads':1,'run_ignored':'only','retries':0,
 'driver_phase_count_or_filters_semantics_changed':False,'actual_test_executions':0,
 'ordinary_observer_coverage_module':'scripts/hepta_c_observer_coverage.py / 49a99d7093dbabe467b2dc5053a597f4df320078 has ordinary owner requirements, no Root parent registry. It remains unchanged; the original b92 separate Root exact-JUnit comparison consumes the final workflow list.',
 'lifecycle_limit':'RootSession finish timeout or outer cancellation is Unknown; an elapsed 5s await is not proof the worker joined. Nine mechanism cases are not a real deployment or independent task chain.'})
print(json.dumps({'old_test_methods':old_total,'new_total':new_total,'old_unchanged':unchanged,'changed_qa_files':len(changed),'ordinary_changed_scopes':len(scope_updates),'workflow_root_count':len(parents+root_cases),'callers_allowlist':line.strip()},indent=2))
