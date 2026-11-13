#!/usr/bin/env python3
"""Hash, diff and statically inspect an isolated proposal; no Rust/toolchain."""
from pathlib import Path
import datetime
import difflib
import hashlib
import importlib.util
import json
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
PREVIOUS = Path('/tmp/hepta-36fa-version-next-use-seam-v1')
SCANNER = Path('/tmp/hepta-36fa-provider-registration-protection-candidate-v1/inputs/before/scripts/verify_hepta_callers.py')
spec = importlib.util.spec_from_file_location('original_next_use_scope_reader', SCANNER)
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)

def pin(raw):
    return {'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def save(name, value):
    raw=(json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode()
    (ROOT/name).write_bytes(raw)
    return pin(raw)

def functions(raw):
    code=proof._strip_rust_non_code(raw)
    rows={}
    for match in re.finditer(r'\bfn\s+([A-Za-z_]\w*)\s*(?=[(<])', code):
        end=proof._rust_item_end(code, match.start())
        assert end is not None and code[end] == '}'
        assert match[1] not in rows
        rows[match[1]]=raw[match.start():end+1]
    return rows

def main():
    original=json.loads((PREVIOUS/'SOURCE_PACKET.json').read_text())
    expected={row['path']:row['after'] for row in original['changes']}
    changes=[]
    patch=[]
    comparisons=[]
    for after in sorted((ROOT/'after').rglob('*.rs')):
        relative=after.relative_to(ROOT/'after').as_posix()
        old=(ROOT/'before'/relative).read_bytes()
        new=after.read_bytes()
        assert pin(old)==expected[relative]
        before_functions=functions(old.decode())
        after_functions=functions(new.decode())
        same=sorted(name for name in before_functions.keys() & after_functions.keys()
                    if before_functions[name] == after_functions[name])
        altered=sorted(name for name in before_functions.keys() & after_functions.keys()
                       if before_functions[name] != after_functions[name])
        comparisons.append({'path':relative, 'unchanged_function_bodies':same,
                            'changed_function_bodies':altered,
                            'removed_functions':sorted(before_functions.keys()-after_functions.keys()),
                            'added_functions':sorted(after_functions.keys()-before_functions.keys())})
        changes.append({'path':relative, 'mode':'100644','before':pin(old),'after':pin(new),
                        'before_text':old.decode(),'after_text':new.decode()})
        patch.extend(difflib.unified_diff(old.decode().splitlines(keepends=True),
                     new.decode().splitlines(keepends=True),fromfile='a/'+relative,tofile='b/'+relative))
    assert len(changes)==5
    by_name={Path(row['path']).name:row for row in changes}
    read=by_name['circuit_learning_read_service.rs']
    start=read['after_text'].index('    /// One readonly response for the original Version')
    end=read['after_text'].index('    pub(super) fn response(',start)
    restored=read['after_text'][:start]+read['after_text'][end:]
    mount='\n#[cfg(test)]\n#[path = "circuit_evaluated_next_use_read_channel_support_tests.rs"]\nmod evaluated_next_use_fixture;\n'
    assert restored.count(mount)==1
    restored=restored.replace(mount,'',1)
    canonical=(PREVIOUS/'before'/read['path']).read_text()
    assert restored==canonical
    read_review=next(row for row in comparisons if row['path']==read['path'])
    assert read_review['changed_function_bodies']==[]
    version=by_name['circuit_retained_version_next_use_readback.rs']
    oldf=functions(version['before_text']); newf=functions(version['after_text'])
    assert [name for name in oldf if oldf[name]!=newf[name]]==['serve_original_evaluated_next_use_channel']
    loop=newf['serve_original_evaluated_next_use_loop']
    handler=newf['original_evaluated_next_use_response']
    assert loop.count('for request_id in 1..=128')==1
    assert loop.count('Instant::now() >= end')==2
    assert loop.index('Instant::now() >= end') < loop.index('self.original_evaluated_next_use_response(') < loop.rindex('Instant::now() >= end')
    assert 'failure.unwrap_or(Error::Transport(error))' in loop
    assert handler.index('self.state.try_lock()') < handler.index('let before = self.read_original(&state)?;')
    response_start=handler.index('let original = match purpose')
    after_read=handler.index('let after = self.read_original(&state)?;')
    assert handler.index('let before = self.read_original(&state)?;') < response_start < after_read
    assert handler.count('self.read_original(&state)?')==2
    assert handler.count('selection.original_receipt_predecessors')==2
    assert handler.count('RetainedVersionFinalUseOutcomeV1::Published')==2
    assert 'drop(state)' not in handler
    assert 'FnMut' not in version['after_text'] and 'FnOnce' not in version['after_text']
    assert 'FnMut' not in read['after_text']
    assert version['after_text'].count('original_owner_command_channel_v1(')==1
    assert all(token not in version['after_text'] for token in ['tokio::try_join!','sleep(','from_original_stream('])
    tests=by_name['circuit_evaluated_version_next_use_readback_tests.rs']
    assert tests['after_text'].startswith(tests['before_text'])
    old_names=re.findall(r'#\[tokio::test\([^\n]*\)\]\nasync fn (\w+)',tests['before_text'])
    names=re.findall(r'#\[tokio::test\([^\n]*\)\]\nasync fn (\w+)',tests['after_text'])
    assert len(old_names)==6 and len(names)==8 and names[:6]==old_names
    new_test=functions(tests['after_text'])['b_withdrawal_after_admission_case']
    assert new_test.index('.read_current().await?.is_none()') < new_test.index('.withdraw_target()?')
    assert new_test.index('let first = case.live') < new_test.index('.withdraw_target()?')
    assert new_test.index('.withdraw_target()?') < new_test.index('let (refused, fenced)')
    assert 'Err(ReadError::Unavailable)' in new_test and 'OriginalCellEvaluationCommandErrorV1::CommitUncertain' in new_test
    assert 'case.servers.pop()' in new_test and 'finish_case(result, case).await' in new_test
    packet={'format':'hepta-source-proposal-v1','identity':'version-next-use-per-handler-current-v1',
        'base_commit':'cc57c7198db6293ccca562253c42fffbe2a04633',
        'base_tree':'b7b357c07b5539769a068c6b9b009629f5612d1e',
        'dependencies':['2b331b488fd789421f9731e3637d882bb57d7f0a',
                        '90f0623289c99ecce60d68d9dad348d27e0bd7fa',
                        'a965a2106c38be86ab0670c7ba090404c3dbc51d'],
        'status':'PREPARATION_NOT_FORMATTED_COMPILED_OR_EXECUTED','changes':changes}
    packet_pin=save('SOURCE_PACKET.json',packet)
    (ROOT/'SOURCE_DELTA.patch').write_text(''.join(patch))
    report={'format':'hepta-next-use-current-increment-static-review-v1',
        'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'verdict':'STATIC_SOURCE_REVIEW_ONLY_RUNTIME_UNVERIFIED', 'source_packet':packet_pin,
        'finding':{'prior_packet':'2b331b488fd789421f9731e3637d882bb57d7f0a',
            'scope':'source-reachable ordering gap; not an executed counterexample',
            'old_behavior':'Full live T/E/Version admission followed by a C-only channel loop; the old B-withdrawal test withdrew B before admission.',
            'old_report_correction':'An opaque S/full signature is not proof of current T/B after channel admission. The prior per-response wording did not establish this property.'},
        'same_state_lock':'concrete Version try_lock spans full live before read, actual C response/readiness, full live after read, equal publication and final cut/S freshness; unavailable on contention without queue',
        'actual_current_scope':'original D/T/E, Artifact/CURRENT and held C through unchanged read_original; same shared original T/E clients, no additional channel',
        'selection_scope':'same opaque S/T/E context and complete S signatures before/after; original C response also checks actual stored selection. No claim of a separate live Selector journal read inside Version; original C Sources retain their own live S owner check.',
        'public_api':'both public Version entrypoints unchanged; only new crate-private response adapters replace the previous new crate-private channel loops',
        'deadlines':'original absolute Version end before/after each actual handler; unchanged original channel 500ms, lifetime <=300s, four Version permits and 128 request limit',
        'request_budget_scope':'More actual predecessor reads use their unchanged shared 128-request budgets; this does not guarantee 128 successful C responses if an original predecessor budget expires first.',
        'legacy_preservation':{'original_read_service_inverse_full_bytes':True,'Contracts_changed':False,'old_selection_and_legacy_serving_changed':False},
        'test_observation':'cfg(test)-only purpose variant narrows the end and observes an actual generated C readiness response, then yields within the existing 250ms/500ms probe envelope. No checker/receipt/clock injection.',
        'existing_six_test_bodies_unchanged':True,'new_methods':names[6:],
        'new_test_scope':'Actual same-process cold Version/held original T/B/C fixtures; positive first original response, then real B withdrawal, second request refused, next request unavailable, original server Evaluation CommitUncertain, unchanged journal bytes and C revision. Not Fresh/public-cross-UID or real utility.',
        'function_comparison':comparisons,
        'executed':{'Rust_compile':False,'rustfmt':False,'tests':False,'full_source_collector':False,'H':False,'active_source_change':False,'refs':False}}
    save('STATIC_REVIEW.json',report)
    registration={'status':'proposal_after_exact_increment_not_formatted',
        'rename_pending_boundaries':[
            {'id':'learning_original_evaluated_next_use_retained_channel','symbol_before':'OriginalCircuitLearningReadOwnerV1::serve_original_evaluated_next_use_channel','symbol_after':'OriginalCircuitLearningReadOwnerV1::original_evaluated_next_use_response'},
            {'id':'learning_original_evaluated_next_use_readiness_retained_channel','symbol_before':'OriginalCircuitLearningReadOwnerV1::serve_original_evaluated_next_use_readiness_channel','symbol_after':'OriginalCircuitLearningReadOwnerV1::original_evaluated_next_use_readiness_response'}],
        'preserve_callers':['codex-rs/hepta-agentd/src/circuit_retained_version_next_use_readback.rs'],
        'new_or_replaced_protected_scopes':['Version::serve_original_evaluated_next_use_loop','Version::original_evaluated_next_use_response','ReadOwner::original_evaluated_next_use_response','ReadOwner::original_evaluated_next_use_readiness_response','ReadOwner::require_original_evaluated_next_use_profile','NextUseReadPurpose'],
        'test_parent_mount':'existing next_use_readback_tests child already includes both added tests; no new mount or ignored rule'}
    save('REGISTRATION_DELTA.json',registration)
    artifacts=[]
    for name in ('SOURCE_PACKET.json','SOURCE_DELTA.patch','STATIC_REVIEW.json','REGISTRATION_DELTA.json','prepare_source.py','build_package.py','README.md'):
        artifacts.append({'name':name,**pin((ROOT/name).read_bytes())})
    save('MANIFEST.json',{'format':'hepta-isolated-source-manifest-v1','identity':packet['identity'],
        'status':packet['status'],'source_packet':packet_pin,'dependencies':packet['dependencies'],
        'changes':[{k:v for k,v in row.items() if k not in ('before_text','after_text')} for row in changes],
        'artifacts':artifacts,'paths_relative_to':'qa/evidence/utility-evaluation-20261112-36fa/',
        'publication':'Actual blob creation/full GET recorded separately; these fields are computed identities.'})
    print(json.dumps({'packet':packet_pin,'manifest':pin((ROOT/'MANIFEST.json').read_bytes()),'new_tests':names[6:]},indent=2))

if __name__=='__main__':
    main()
