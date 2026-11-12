from pathlib import Path
import ast,difflib,hashlib,json,shutil
OLD=Path('/tmp/hepta-36fa-final-nonrust-review-snapshot-v1')
OUT=Path('/tmp/hepta-36fa-final-nonrust-review-snapshot-v2')
shutil.copytree(OLD,OUT)
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob_sha':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
qa='qa/b4-no-bypass/test_evaluated_published_read_source_closure.py'
p=OUT/qa;before=p.read_text();tree=ast.parse(before)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='EvaluatedOrdinaryRetainedClosureTests')
method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='test_new_typed_edges_and_old_boundary_inventory_are_exact')
old=ast.get_source_segment(before,method)
assert before.count(old)==1
added='\n        for path in ORDINARY_SCOPE_GUARDS:\n            with self.subTest(actual_root_scopes=path):\n                self.actual_scopes(path, (ROOT / path).read_text())'
new=old+added;after=before.replace(old,new,1);p.write_text(after);ast.parse(after)
new_tree=ast.parse(after);new_cls=next(n for n in new_tree.body if isinstance(n,ast.ClassDef) and n.name==cls.name);new_method=next(n for n in new_cls.body if isinstance(n,ast.FunctionDef) and n.name==method.name)
assert ast.dump(ast.Module(body=new_method.body[:-1],type_ignores=[]),include_attributes=False)==ast.dump(ast.Module(body=method.body,type_ignores=[]),include_attributes=False)
assert after.replace(new,old,1)==before
review=json.loads((OUT/'NEW_ORDINARY_QA_REVIEW.json').read_text());review['supersedes_without_deleting']={'qa_v1':pin(before.encode()),'reason':'21 of 34 supplemental actual root scopes were not reached by the original 18 methods.'};review['after']=pin(after.encode());review['scope_coverage_correction']={'method':method.name,'change':'Append one loop over every ORDINARY_SCOPE_GUARDS actual source path, preserving every original statement and all 18 methods.','calls':'actual_scopes on actual ROOT source bytes; no source or verdict cache','new_execution':'pending independent scoped diagnostic'}
(OUT/'NEW_ORDINARY_QA_REVIEW.json').write_text(json.dumps(review,indent=2,sort_keys=True)+'\n')
patch=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='v1/'+qa,tofile='v2/'+qa,n=4))
(OUT/'V1_TO_V2_SCOPE_COVERAGE.diff').write_text(patch)
proof={'format':'hepta-postformat-scope-coverage-correction-v2','qualification':False,'path':qa,'before':pin(before.encode()),'after':pin(after.encode()),'exact_delta':pin(patch.encode()),'changes':{'new_methods':0,'removed_methods':0,'changed_method':cls.name+'.'+method.name,'preserved_old_statements_ast':True,'whole_file_inverse_exact':True,'caller_manifest_changed':False,'original_verifier_changed':False,'fullcollector_changed':False,'budgets_changed':False},'previous_proposal_preserved':'/tmp/hepta-36fa-reviewed-final-nonrust-v1','new_runtime':'not_run'}
(OUT/'SCOPE_COVERAGE_CORRECTION.json').write_text(json.dumps(proof,indent=2,sort_keys=True)+'\n')
manifest=json.loads((OLD/'MANIFEST.json').read_text());manifest['format']='hepta-final-nonrust-review-snapshot-v2';manifest['supersedes_without_deleting']=pin((OLD/'MANIFEST.json').read_bytes());manifest['new18_tests_run']=False
manifest['files']=[{'path':x['path'],**pin((OUT/x['path']).read_bytes())} for x in manifest['files']]
(OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
print(json.dumps({'root':str(OUT),'qa_after':pin(after.encode()),'delta':patch,'manifest':pin((OUT/'MANIFEST.json').read_bytes())},sort_keys=True))
