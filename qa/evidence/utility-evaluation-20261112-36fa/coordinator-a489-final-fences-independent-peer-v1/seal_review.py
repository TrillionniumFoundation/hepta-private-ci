"""Create-only final static-review evidence; no project code execution."""
from pathlib import Path
import base64,gzip,json,sys,tomllib
from review_primitives import identity,changed_leaves

D=Path(__file__).resolve().parent
F=Path('/tmp/hepta-36fa-a489-maintenance-registration-frozen-v1')
def save(name,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    p=D/name
    if p.exists():assert p.read_bytes()==raw
    else:
        with p.open('xb') as f:f.write(raw)
    return identity(raw)

proofraw=(D/'FROZEN_BYTE_AND_SCOPE_REVIEW.json').read_bytes();proof=json.loads(proofraw)
manifest=json.loads((D/'inputs/MANIFEST.json').read_bytes())
sdkobs=[]
for name,git in [('MANIFEST.json','4bc60fab145563469f1cbb992feeaf216d58dfb5'),('AUTHOR_REVIEW.json','67cd58d0eb04f9b820dade2e24e2f8869450a2c5')]+[(x['name'],x['git_blob']) for x in manifest['source_packet']['parts']]:
    raw=(D/'inputs'/name).read_bytes();assert identity(raw)['git_blob']==git
    sdkpath=D/'github'/(name+'.GET.original.json');sdkraw=sdkpath.read_bytes();sdk=json.loads(sdkraw)
    assert sdk['structuredContent']['content'].encode()==raw
    sdkobs.append({'name':name,'body':identity(raw),'SDK':identity(sdkraw),'SDK_local_path':str(sdkpath),'full_GET_equal':True})
save('INDEPENDENT_INPUT_FULL_GET.json',{'format':'hepta-independent-full-get-input-proof-v1','inputs':sdkobs,'source_packet_raw':proof['source_packet'],'reconstruction':'Strict canonical base64 with one LF; decoded offsets, piece SHA/Git, complete gzip and raw SHA/Git equal; raw bytes also equal the fixed author packet.','raw_large_packet_standalone_GET_claimed':False})

# Independently reverse only the nine serialized full-scope strings, not a
# whole file supplied by the author. This captures even nonsemantic TOML text.
a=(F/'before/CALLERS.toml').read_bytes();b=(F/'after/CALLERS.toml').read_bytes()
old=tomllib.loads(a.decode());new=tomllib.loads(b.decode());restored=b;inverse=[]
for i,(x,y) in enumerate(zip(old['protected_file'],new['protected_file'])):
    for field,before,after in changed_leaves(x,y):
        av=json.dumps(before,ensure_ascii=False).encode();bv=json.dumps(after,ensure_ascii=False).encode()
        assert restored.count(bv)==1
        restored=restored.replace(bv,av,1)
        inverse.append({'row':i,'field':list(field),'before_json_string':identity(av),'after_json_string':identity(bv)})
assert restored==a
cp='qa/b4-no-bypass/PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'
ca=(F/'before'/cp).read_bytes();cb=(F/'after'/cp).read_bytes();oa=json.loads(ca);ob=json.loads(cb)
assert (json.dumps(oa,indent=2,sort_keys=True)+'\n').encode()==ca
ob.pop('actual_maintenance_refresh');ob['scopes']=oa['scopes']
assert (json.dumps(ob,indent=2,sort_keys=True)+'\n').encode()==ca
inversepin=save('EXACT_TEXT_INVERSE.json',{'format':'hepta-final-fences-exact-text-inverse-v1','CALLERS_changes':inverse,'CALLERS_all_bytes_recovered_by_nine_only_json_string_reversals':True,'contract_all_bytes_recovered_by_removing_one_provenance_field_and_restoring_five_scope_hash_pairs':True,'project_execution':False})

gz=gzip.compress(proofraw,mtime=0);part=base64.b64encode(gz)+b'\n'
partname='FROZEN_BYTE_AND_SCOPE_REVIEW.json.gz.b64'
assert len(part)<512000
if (D/partname).exists():assert (D/partname).read_bytes()==part
else:
    with (D/partname).open('xb') as f:f.write(part)
assert gzip.decompress(base64.b64decode(part[:-1],validate=True))==proofraw
encodingpin=save('SCOPE_PROOF_ENCODING.json',{'format':'hepta-lossless-static-scope-proof-v1','raw':identity(proofraw),'gzip':identity(gz),'parts':[{'name':partname,'decoded_offset':0,'encoded':identity(part),'decoded':identity(gz)}],'raw_is_content_identity_not_direct_Git_upload':True,'max_evidence_leaf_bytes':512000})
observationpin=save('LOCAL_AUDIT_OBSERVATIONS.json',{
 'format':'hepta-independent-review-helper-observations-v1',
 'scope':'Only this peer scratch scripts; no source/H/gate invocation or author file mutation.',
 'observations':[
  {'stage':'initial scratch packet image extraction before this frozen script','observation':'A local assertion expected compact git_blob metadata but actual changes use native working_blob inventory rows.','resolution':'Explicit bytes/sha256/working_blob projection used; complete original metadata separately checked.','native_or_source_failure':False},
  {'stage':'verify_final_fences.py','observation':'A pure review assertion assumed Rust_source_changes was an empty list; actual schema records integer 0.','resolution':'v2 requires exact int zero and preserves canonical_source_deletions as an empty list.','native_or_source_failure':False},
  {'stage':'verify_final_fences_v2.py','observation':'A pure expected-inventory comparison used indented JSON rather than original compact serializer; hash mismatch was local formatting only.','resolution':'v3 first proves original inventory is sorted compact JSON plus LF, then uses that identical serializer for the four-write projection.','native_or_source_failure':False}],
 'final_script':'verify_final_fences_v3.py','final_observations':identity(proofraw),
 'original_scripts_retained':True,'false_runtime_verdicts':False})

findings=[
 {'id':'F01','result':'No concrete static blocker','finding':'Independent full GET of manifest, author review and all four bounded packet leaves exactly reproduces the complete 5,999,431-byte proposal. All four before/after bodies match their three identities and actual inventory before rows; the three unchanged reference bodies match actual inventory as well.'},
 {'id':'F02','result':'Four-write projection exact','finding':'The actual 15,243-leaf inventory recomputes c026a8d7e93c958b39a36c666debecb3dba4be14. Updating exactly the four specified files yields 8ebb37e523ad3932a58cf016af0a9f4e0eeb6638 and complete expected inventory e3ce3d7bba028e29efca751c6f43fde124b05ea0. All other 15,239 entries are identical. This is an offline projection, not an applied result; actual HEAD/index remain d256/a489.'},
 {'id':'F03','result':'633 boundaries and 442 protection obligations preserved','finding':'Every CALLERS top-level field other than protected_file is semantically identical, including all boundary objects, required IDs, source roots, ignored fragments, rules and false authority fields. Protection row order and duplicate paths are preserved. All 442 forbidden arrays and every nonmarker field are identical; rows 411 and 422 are entirely unchanged.'},
 {'id':'F04','result':'Nine complete scope strings refreshed without widening','finding':'Only rows 429, 438 and 440 change, in nine existing required_order/required_function_order string values. Every old value exactly covers its complete real pre-maintenance function or root item; every replacement exactly covers the corresponding complete actual postimage scope. Prefixes, names, selectors and container depth are unchanged. Reversing these nine JSON-quoted values restores the complete original CALLERS file byte for byte.','scopes':[{k:v for k,v in x.items() if k in ('row','path','field','scope')} for x in proof['full_scope_marker_values']]},
 {'id':'F05','result':'All 45 modules / 288 scopes bound','finding':'Both original and refreshed contracts locate all 288 scopes in their exact original/actual files and match masked and literal-preserving hashes. Only five existing scope hash pairs change; all selectors, root module declarations/imports/attributes/final tails, mounts, exports, decoy/protocol items and prior historical provenance are identical. One actual_maintenance_refresh field accurately adds the 41e/c026 observation while qualification remains false.','changed_scopes':[{k:v for k,v in x.items() if k in ('path','index','selector')} for x in proof['changed_scope_digests']]},
 {'id':'F06','result':'Original attack targets retained','finding':'All 107 attack definitions are byte-semantically unchanged. The unchanged exact marker algorithm statically locates 123 nonempty real-function targets before and after, with identical count per attack. No mutant was generated or executed, so this result does not assert runtime rejection.'},
 {'id':'F07','result':'Ordinary guards retained','finding':'The ordinary QA file is byte-identical. All 34 scope hashes, 17 strict literal spans and 10 module mount spans locate in the actual files. Its original 541:569 boundary slice and provider 569:633 slice remain exact; no collector/parser/ignored-path rule was modified.'},
 {'id':'F08','result':'64 QA files / 607 methods preserved','finding':'Every one of the 607 existing test methods has identical bytes and AST. All 27 top-level helpers, and all remaining class/helper code, are unchanged. The only provider QA edit replaces its one expected contract SHA; reversing that literal restores its entire original file. There are zero added/deleted test methods and no weakened assertions.'},
 {'id':'F09','result':'48 Root parents / workflow unchanged','finding':'The complete workflow and Root QA are byte-identical, including all 48 distinct Root parent names, prior 39 plus nine custody cases. All nine new original methods remain explicitly ignored for their actual Root fixture requirement. Existing ignored-only/single-thread/retries/JUnit/timeout and stage ordering bytes are unchanged; no workflow was dispatched.'},
 {'id':'F10','result':'Exact allowlist addition only','finding':'The existing allowlist is an exact prefix. The sole new entry is sha256:62fc6814e2f24ecbf37a83583f526d215870cf2ab5202f524f34de46b77273fa CALLERS.toml, preceded by its descriptive comment. There is no wildcard or rule change.'},
 {'id':'F11','result':'Execution and utility limits retained','finding':'This review does not approve or perform an apply, format, source gate, full caller scan, Rust build/test, native gate, source publication or ref movement. Earlier actual fix0/fmt0 and the separately reviewed 17 Rust postimages are maintenance evidence only. Normal host wiring, actual original owner materials, independent B and useful end-to-end results are not established by these source fences.'}
]
review={
 'format':'hepta-c026-final-fences-independent-peer-review-v1',
 'decision':'NO_CONCRETE_STATIC_BLOCKER_WITHIN_FROZEN_FOUR_MODIFICATION_SEVEN_BINDING_SCOPE',
 'execution_authorized':False,'qualification':False,
 'source_packet':manifest['source_packet']['raw'],'source_packet_manifest':identity((D/'inputs/MANIFEST.json').read_bytes()),
 'independent_actual_Rust_semantic_peer':'d3bccc02d7be04d5d5fec510aa73f1447109d5df',
 'actual_base':{'head':'d25675445c39f76db69a7bd8e71a1a72e1cd5b9f','index_tree':'a489b394666b8141840275128a780605b024cde0','physical_tree':proof['base_physical_tree'],'inventory':proof['actual_inventory']},
 'expected_unapplied_after':{'physical_tree':proof['expected_after_physical_tree'],'inventory':proof['expected_inventory'],'leaves':15243},
 'findings':findings,'full_static_observations':identity(proofraw),'bounded_observation_encoding':encodingpin,
 'exact_text_inverse':inversepin,'local_helper_observations':observationpin,
 'scope_count_summary':{'boundaries_unchanged':633,'protected_rows':442,'unchanged_protected_rows':439,'changed_rows':[429,438,440],'full_scope_marker_values':9,'provider_paths':45,'provider_scopes':288,'changed_scope_hash_pairs':5,'ordinary_scopes':34,'ordinary_literals':17,'ordinary_mounts':10,'provider_mounts':len(proof['provider_mounts']),'provider_exports':len(proof['all_public_export_strings_root_and_unique']),'attack_specs':107,'attack_target_occurrences':123,'QA_files':64,'QA_methods_byte_and_AST_equal':607,'top_level_helpers_byte_equal':27,'Root_parents':48},
 'pure_lexical_method':'Only the exact named FunctionDefs in FROZEN_BYTE_AND_SCOPE_REVIEW were extracted from inventory-pinned original scanner/QA bytes. No whole project module/global statements, test method, collector or verifier entry point executed.',
 'expected_next_boundary':'Any later exact apply/format and qualification successor requires its own concrete actual input/permission review. This review conveys no H or source write authorization.',
 'H_calls':0,'QA_or_Rust_or_full_collector_executions':0,'source_or_ref_mutations':0}
reviewpin=save('REVIEW.json',review)
print(json.dumps({'review':reviewpin,'scope_proof_raw':identity(proofraw),'scope_encoding':encodingpin,'part':identity(part),'inverse':inversepin,'observations':observationpin}))
