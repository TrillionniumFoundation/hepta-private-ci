#!/usr/bin/env python3
"""Pure frozen packet/byte checks. No candidate, Rust, QA, Git or H execution."""
from pathlib import Path
import difflib
import hashlib
import json
import re

D=Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
OUT=Path(__file__).parent
INV=Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')

def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def js(path):return json.loads(path.read_text())
def pin(raw,expected):
    observed=identity(raw)
    assert observed=={k:expected[k] for k in observed},(observed,expected)
    return observed

def rows_and_images(directory):
    manifest=js(directory/'MANIFEST.json')
    rows=manifest.get('entries',manifest.get('files'))
    packet_path=directory/'SOURCE_PACKET.json'
    if packet_path.is_file():
        packet=js(packet_path)
        assert packet['manifest']==manifest
        images={r['path']:r for r in packet['images']}
    else:
        images={r['path']:{'path':r['path'],
                    'before':(directory/'before'/r['path']).read_text() if r['before'] is not None else None,
                    'after':(directory/'after'/r['path']).read_text()} for r in rows}
    assert len(images)==len(rows) and set(images)=={r['path'] for r in rows}
    for row in rows:
        image=images[row['path']]
        if row['before'] is None:
            assert image['before'] is None
        else:pin(image['before'].encode(),row['before'])
        pin(image['after'].encode(),row['after'])
    expected=''.join(''.join(difflib.unified_diff(
        (images[r['path']]['before'] or '').splitlines(keepends=True),
        images[r['path']]['after'].splitlines(keepends=True),
        fromfile='a/'+r['path'] if r['before'] is not None else '/dev/null',
        tofile='b/'+r['path'])) for r in rows)
    actual=(directory/'SOURCE_DELTA.patch').read_text()
    assert expected==actual,('complete generated diff differs',directory)
    return manifest,rows,images

assert identity(INV.read_bytes())['git_blob']=='457adb9bf9ba3a844e9dfa149be49460bb306998'
inventory=js(INV);leaves={r['path']:r for r in inventory['files']}
assert len(leaves)==15243
layers=['publication-layer-v1','lease-observation-increment-v1','task-factory-layer-v1',
        'protected-host-tests-layer-v1','binding-request-increment-v1']
current,originals,proof={}, {}, []
layer_images={}
for layer in layers:
    p=D/layer;m,rows,images=rows_and_images(p)
    layer_images[layer]=images
    operations=[]
    for row in rows:
        path=row['path'];im=images[path]
        if path in current:
            assert current[path]==im['before'],('wrong complete predecessor',layer,path)
        else:
            originals[path]=im['before']
            if im['before'] is None:
                assert path not in leaves
            else:
                row0=leaves[path]
                assert row0['working_blob']==row['before']['git_blob']
                assert row0['bytes']==row['before']['bytes'] and row0['sha256']==row['before']['sha256']
        current[path]=im['after']
        operations.append({'path':path,'before':row['before'],'after':row['after'],
                           'exact_predecessor_and_packet_bytes':True})
    proof.append({'layer':layer,'manifest':identity((p/'MANIFEST.json').read_bytes()),
                  'packet':identity((p/'SOURCE_PACKET.json').read_bytes()) if (p/'SOURCE_PACKET.json').is_file() else None,
                  'complete_diff':identity((p/'SOURCE_DELTA.patch').read_bytes()),'operations':operations})

A=D/'assembled-source-v1'
am,ar,ai=rows_and_images(A)
assert identity((A/'SOURCE_PACKET.json').read_bytes())['git_blob']=='1ca7a06948fcae69bf7c8e4c7823627a872c0c62'
assert len(current)==len(ar)==13
assert {r['path']:r['after'] for r in ai.values()}==current
assert {r['path']:r['before'] for r in ai.values()}==originals
assert sum(x is None for x in originals.values())==7
existing=[]
for path,before in originals.items():
    if before is None:continue
    after=current[path]
    before_lines=before.splitlines(keepends=True)
    after_lines=after.splitlines(keepends=True)
    matcher=difflib.SequenceMatcher(None,before_lines,after_lines,autojunk=False)
    changes=[(tag,a,b,c,d) for tag,a,b,c,d in matcher.get_opcodes() if tag!='equal']
    assert all(tag=='insert' for tag,*_ in changes),(path,changes)
    inverse=list(after_lines)
    for tag,a,b,c,d in reversed(changes):inverse=inverse[:c]+inverse[d:]
    assert ''.join(inverse)==before
    existing.append({'path':path,'before':identity(before.encode()),'after':identity(after.encode()),
                     'insertions':[{'after_line':c+1,'bytes':len(''.join(after_lines[c:d]).encode()),'text':''.join(after_lines[c:d])}
                                   for tag,a,b,c,d in changes],
                     'full_original_byte_inverse':True})

prefix='codex-rs/hepta-agentd/src/'
task=current[prefix+'authority_host_session_generation_task.rs']
request=current[prefix+'authority_host_generation_request.rs']
session=current[prefix+'authority_host_session_generation.rs']
core=current[prefix+'authority_host_generation.rs']
tests=current[prefix+'authority_host_generation_tests.rs']
test_old=layer_images['protected-host-tests-layer-v1'][prefix+'authority_host_generation_tests.rs']['after']

# The later binding increment adds one test but preserves every old test/helper byte.
test_old_lines=test_old.splitlines(keepends=True)
test_new_lines=tests.splitlines(keepends=True)
sm=difflib.SequenceMatcher(None,test_old_lines,test_new_lines,autojunk=False)
test_changes=[(tag,a,b,c,d) for tag,a,b,c,d in sm.get_opcodes() if tag!='equal']
assert all(tag=='insert' for tag,*_ in test_changes)
inverse=list(test_new_lines)
for tag,a,b,c,d in reversed(test_changes):inverse=inverse[:c]+inverse[d:]
assert ''.join(inverse)==test_old
test_names=re.findall(r'#\[tokio::test\]\s*#\[ignore = "requires original Root host bind and actual signed owner fixtures"\]\s*async fn (\w+)',tests)
assert len(test_names)==6
assert tests.count('#[tokio::test]')==len(test_names)
assert test_old.count('#[tokio::test]')==5

I=D/'request-type-import-increment-v1'
im,ir,ii=rows_and_images(I)
assert len(ir)==1
row=ir[0];path=row['path'];image=ii[path]
assert image['before']==session and row['before']['git_blob']=='75d56de2aa85e0e512585a18de7f8bb8526586d3'
line='use crate::neuron_generation_update::AgentdGenerationUpdateRequestV1;\n'
assert line not in image['before'] and image['after'].count(line)==1
assert image['after'].replace(line,'',1)==image['before']
assert len(image['after'].encode())-len(image['before'].encode())==len(line.encode())
current[path]=image['after']

# Explicit implementation anchors; these do not substitute for a Rust type check.
assert 'pub fn into_original_q24_task' in task
assert 'OriginalRootInitialGenerationCustodyV1::into_q24_task(custody, config, inputs)' in task
assert 'OriginalHostInitialOperation::require_observed' in task
assert 'runtime.custody' in task and 'Ok((session, runtime))' in task
assert 'Source/Cell installation may already have had effects' in task
assert 'fn read_original_generation_after_installation_failure' in task
assert 'validate_initial_target(selected, target)?' in request
assert 'NeuronGenerationCurrentOwnerV1::original_initial_publication_binding' in request
for disallowed in ['.issue(', '::initialize(', '::prepare(', 'CurrentOwnerV1::open(', 'prepare_agentd_generation_initial_v1(']:
    assert disallowed not in request,disallowed
assert 'self.issuer.with_live_lease' in request and 'registry.verifier().read_lease' in request
assert 'self.clock.now_unix_ms().map_err(invalid)? >= lease.expires_at_unix_ms' in request
assert 'pub(crate) fn read_original_initial_request' in request
assert 'pub struct OriginalHostInitialOperation' not in core and 'pub(crate) struct OriginalHostInitialOperation' in core
for newsource in [task,request,session,core]:
    assert '#[derive(Clone' not in newsource or newsource is core

references=[]
reference_names=[
 'neuron_generation_initial_root_task.rs','neuron_generation_initial_root_cold.rs',
 'neuron_generation_initial_root_custody.rs','neuron_generation_initial.rs','neuron_generation_initial_bootstrap.rs',
 'neuron_generation_current.rs','neuron_generation_current_store.rs','neuron_generation_current_initial.rs',
 'circuit_q24_task_profile.rs','config_q24_circuit_task.rs','config_circuit_task.rs',
 'authority_host_runtime.rs','authority_host_session.rs','authority_host_service.rs','authority_host_config.rs',
 'deployment_signed_grant.rs','deployment_issuer.rs','deployment_issuer_root.rs',
 'neuron_generation_update_test_support.rs','neuron_generation_initial_root_custody_support_tests.rs',
 'bin/hepta-authority-host.rs']
for name in reference_names:
    path=prefix+name;local=D/'references'/path;raw=local.read_bytes();identity0=identity(raw);row0=leaves[path]
    assert identity0['git_blob']==row0['working_blob'] and identity0['bytes']==row0['bytes'] and identity0['sha256']==row0['sha256']
    references.append({'path':path,'local':str(local),**identity0,'exact_b608_physical_row':True})
for name in ['final_use.rs','final_use_live_owner.rs','final_use_retained.rs']:
    path='codex-rs/hepta-contracts/src/'+name;local=D/'references'/path;raw=local.read_bytes();id0=identity(raw);row0=leaves[path]
    assert id0['git_blob']==row0['working_blob'] and id0['bytes']==row0['bytes'] and id0['sha256']==row0['sha256']
    references.append({'path':path,'local':str(local),**id0,'exact_b608_physical_row':True})

result={'format':'hepta-e1-independent-layer-byte-review-v1',
 'source_git_writes':0,'H_calls':0,'Rust_or_QA_executed':0,
 'baseline_inventory':{'path':str(INV),**identity(INV.read_bytes())},
 'assembled_packet':identity((A/'SOURCE_PACKET.json').read_bytes()),
 'assembled_manifest':identity((A/'MANIFEST.json').read_bytes()),
 'assembled_patch':identity((A/'SOURCE_DELTA.patch').read_bytes()),
 'covered_rust_paths':13,'existing_exact_b608_preimages':6,'new_paths':7,
 'layers':proof,'all_assembled_images_equal_layer_composition':True,'existing_sources_exact_inverse':existing,
 'new_ignored_tests':test_names,'old_five_test_methods_and_helpers_byte_preserved':True,
 'missing_import_finding':{'file':path,'assembled_missing_import':True,
    'correct_file':prefix+'authority_host_session_generation.rs',
    'before':row['before'],'after':row['after'],'exact_added_line':line,
    'successor_packet':identity((I/'SOURCE_PACKET.json').read_bytes()),
    'successor_manifest':identity((I/'MANIFEST.json').read_bytes()),
    'whole_file_inverse_equal':True,'compiler_executed':False},
 'reviewed_final_local_images':[{'path':p,**identity(raw.encode())} for p,raw in sorted(current.items())],
 'original_source_references':references,
 'limitations':['Byte/shape checks do not establish successful compilation or execution.',
                'No source ref/worktree or currently qualifying b608 bytes changed.',
                'The six methods are mechanism proposals, not independently useful task evidence.']}
# Do not let the temporary loop path appear as the issue file.
result['missing_import_finding']['file']=prefix+'authority_host_session_generation.rs'
with (OUT/'BYTE_PROOF.json').open('x') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
print(json.dumps({'output':str(OUT/'BYTE_PROOF.json'),**identity((OUT/'BYTE_PROOF.json').read_bytes()),
                  'paths':len(current),'references':len(references),'tests':test_names,
                  'fixed_session_image':identity(current[prefix+'authority_host_session_generation.rs'].encode())},indent=2))
