from pathlib import Path
import hashlib,json,subprocess,shutil,tempfile
R=Path(__file__).parent;B=R/'base';C=R/'current'
for mf in ['docs_source_manifest.json','protocol_sources_manifest.json']:
 for row in json.loads((R/mf).read_text())['files']:
  b=(B/row['path']).read_bytes();assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==row['blob']
p='docs/lane-a-foundation/PROTOCOL_REGISTRY_V1.json';old=json.loads((B/p).read_text());new=json.loads((C/p).read_text())
old_ops=[x for x in old['protocols'] if x['module']=='kernel.operations'];new_ops=[x for x in new['protocols'] if x['module']=='kernel.operations'];assert len(old_ops)==2 and len(new_ops)==1
primary=dict(new_ops[0]);extra=primary.pop('additionalProtocols');assert primary==old_ops[0];assert extra==[old_ops[1]]
assert [x for x in old['protocols'] if x['module']!='kernel.operations']==[x for x in new['protocols'] if x['module']!='kernel.operations']
assert (B/'docs/modules/kernel.operations/IMPLEMENTATION_MAP.json').read_bytes()==(C/'docs/modules/kernel.operations/IMPLEMENTATION_MAP.json').read_bytes()
assert (B/'docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json').read_bytes()==(C/'docs/lane-a-foundation/MODULE_TRUTH_MATRIX.json').read_bytes()
assert (B/'docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json').read_bytes()==(C/'docs/lane-a-foundation/CAPABILITY_EVIDENCE_MAP.json').read_bytes()
test_root='qualification/module-execution-dossiers'
methods=['test_current_protocol_registry_is_closed_world_and_non_authorizing','test_operations_guide_matches_identity_metadata','test_protocol_registry_preserves_additional_operations_surface','test_protocol_registry_rejects_duplicate_ids_foreign_owners_and_nested_surfaces']
args=['python3','-m','unittest',*[f'test_lane_a_foundation.LaneAFoundationTruthTests.{m}' for m in methods]]
result=subprocess.run(args,cwd=C/test_root,text=True,capture_output=True);(R/'metadata-positive.log').write_text(result.stdout+result.stderr);assert result.returncode==0,result.stderr
negative=Path(tempfile.mkdtemp(prefix='operations-metadata-red-'))
# Test runner and its imports are real candidate files; only the guide is
# restored to its exact baseline to demonstrate the new drift assertion.
shutil.copytree(C,negative,dirs_exist_ok=True)
p='docs/modules/kernel.operations/TECHNICAL.md';(negative/p).write_bytes((B/p).read_bytes())
result=subprocess.run(['python3','-m','unittest',f'test_lane_a_foundation.LaneAFoundationTruthTests.{methods[1]}'],cwd=negative/test_root,text=True,capture_output=True);(R/'metadata-policy-negative.log').write_text(result.stdout+result.stderr);assert result.returncode==1 and 'AssertionError' in result.stderr,result.stderr
print('PASS: all original primary/product IDs, fields, sources and invariants preserved; all other module rows and claim maps unchanged;4 actual unittest methods passed; stale guide produces expected assertion failure.')
print('Full LaneA suite, source-observation/ancestry rebinding, native Rust and CI are NOT qualified by this scoped fixture.')
