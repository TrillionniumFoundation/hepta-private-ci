"""Append the six already frozen public handoff/lifecycle parent cases."""
from pathlib import Path
import ast, difflib, hashlib, json, re

ROOT=Path(__file__).resolve().parent
proposal=json.loads((ROOT/'before/ROOT_INVENTORY_PROPOSAL.json').read_text())
qa_proposal=json.loads((ROOT/'before/ROOT_QA_PROPOSAL.json').read_text())
workflow_path=Path('.github/workflows/hepta-daemon-learning-native.yml')
qa_path=Path('qa/b4-no-bypass/test_resident_root_source_closure.py')
old_workflow=(ROOT/'before'/workflow_path).read_text()
old_qa=(ROOT/'before'/qa_path).read_text()
match=re.search(r'parents = (\[[\s\S]*?\n          \])',old_workflow)
assert match and ast.literal_eval(match.group(1))==proposal['original_parents']
addition=''.join('              '+json.dumps(name)+',\n' for name in proposal['new_parents'])
new_parents=match.group(1)[:-len('          ]')]+addition+'          ]'
workflow=old_workflow[:match.start(1)]+new_parents+old_workflow[match.end(1):]
assert ast.literal_eval(new_parents)==proposal['candidate_parents']
assert workflow.replace(addition,'',1)==old_workflow

qa=old_qa
tree=ast.parse(qa)
assignment=next(n for n in tree.body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='ROOT_CASES' for t in n.targets))
original_cases=ast.get_source_segment(qa,assignment)
assert ast.literal_eval(assignment.value)==qa_proposal['root_cases_before']
case_addition=''.join('    '+json.dumps(name)+',\n' for name in qa_proposal['root_cases_append'])
new_cases=original_cases[:-1]+case_addition+']'
assert qa.count(original_cases)==1
qa=qa.replace(original_cases,new_cases,1)
old_loop='        for name in ROOT_CASES:\n'
provider_setup='''        provider = (ROOT / (AGENT + "authority_host_learning_resident_provider_transport_tests.rs")).read_text()
        lifecycle = (ROOT / (AGENT + "authority_host_learning_resident_provider_lifecycle_tests.rs")).read_text()
        self.assertIn(
            '#[path = "authority_host_learning_resident_provider_transport_tests.rs"]\\nmod provider_transport;',
            roots,
        )
        self.assertIn(
            '#[path = "authority_host_learning_resident_provider_lifecycle_tests.rs"]\\nmod lifecycle;',
            provider,
        )
'''
assert qa.count(old_loop)==1
qa=qa.replace(old_loop,provider_setup+old_loop,1)
old_source='            source = retention if "::retention_auth::" in name else model if "::original_model::" in name else evaluation if "::evaluation::" in name else roots\n'
new_source='''            source = (
                lifecycle if "::provider_transport::lifecycle::" in name
                else provider if "::provider_transport::" in name
                else retention if "::retention_auth::" in name
                else model if "::original_model::" in name
                else evaluation if "::evaluation::" in name
                else roots
            )
'''
assert qa.count(old_source)==1
qa=qa.replace(old_source,new_source,1)
old_count='            + retention.count(\'#[ignore = "explicit actual Root\'),\n'
new_count='''            + retention.count('#[ignore = "explicit actual Root')
            + provider.count('#[ignore = "explicit actual Root')
            + lifecycle.count('#[ignore = "explicit actual Root'),
'''
assert qa.count(old_count)==1
qa=qa.replace(old_count,new_count,1)
reverse=qa.replace(new_count,old_count,1).replace(new_source,old_source,1).replace(provider_setup,'',1).replace(new_cases,original_cases,1)
assert reverse==old_qa
ast.parse(qa)
assert all(marker in qa for marker in [
    'self.assertEqual(len(parents), len(set(parents)))',
    'self.assertTrue(set(ROOT_CASES).issubset(parents))',
    'self.assertTrue(set(ROOT_ISSUER_CASES).issubset(parents))',
    'self.assertEqual(len(parents), 7 + len(ROOT_CASES) + len(ROOT_ISSUER_CASES))',
])

def identity(data):
    return {'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()}

changes=[]
patch=[]
for path,old,new in [(workflow_path,old_workflow,workflow),(qa_path,old_qa,qa)]:
    target=ROOT/'candidate'/path
    assert target.read_text()==old
    target.write_text(new)
    changes.append({'path':str(path),'before':identity(old.encode()),'after':identity(new.encode()),
                    'before_text':old,'after_text':new,'mode':'100644'})
    patch.extend(difflib.unified_diff(old.splitlines(keepends=True),new.splitlines(keepends=True),
                                    fromfile='a/'+str(path),tofile='b/'+str(path)))
out=ROOT/'root-test-registration-v1'
out.mkdir(exist_ok=False)
packet={'format':'hepta-root-test-registration-preparation-v1','status':'UNEXECUTED_FINAL_CANDIDATE_REGISTRATION_STILL_REQUIRED',
        'source_commit':'cc57c7198db6293ccca562253c42fffbe2a04633','changes':changes,
        'old_parent_count':33,'new_parent_count':39,'old_parent_order_exactly_retained':True,
        'original_qa_inverse_byte_equal':True,'all_old_qa_assertions_retained':True,
        'child_entry_point_not_registered_as_parent':True,'native_driver_changed':False,
        'original_filters_budgets_stack_retained':True,'full_fresh_parents_not_yet_added':True,
        'tests_executed':False,'qualification':False}
(out/'SOURCE_PACKET.json').write_text(json.dumps(packet,indent=2,sort_keys=True)+'\n')
(out/'changes.patch').write_text(''.join(patch))
print(json.dumps({'changes':[{k:v for k,v in c.items() if not k.endswith('_text')} for c in changes],
                  'packet':identity((out/'SOURCE_PACKET.json').read_bytes()),
                  'original_qa_inverse_byte_equal':True,'old_parents':33,'candidate_parents':39,
                  'native_execution_or_qualification':False},indent=2))
