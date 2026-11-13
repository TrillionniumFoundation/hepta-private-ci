"""Independent byte checks only; never imports or executes project source."""
from pathlib import Path
import hashlib
import json
import difflib

D = Path('/tmp/hepta-36fa-e2-ipc-independent-peer-v1')
P = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/ipc-layer-v1')
R = 'codex-rs/hepta-agentd/src/'

def pin(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(body)).encode()+b'\0'+body).hexdigest()}

def save(name, value):
    body = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode()
    path = D/name
    if path.exists():
        assert path.read_bytes() == body, name
    else:
        path.write_bytes(body)
    return pin(body)

def text(side, name):
    return (P/side/R/name).read_text()

def replace_once(body, old, new):
    assert body.count(old) == 1, ('replacement not unique', old[:120], body.count(old))
    return body.replace(old, new, 1)

packet_bytes = (P/'SOURCE_PACKET.json').read_bytes()
assert pin(packet_bytes) == {'bytes':467432, 'sha256':'58ceae69a092b65f1364c7ad44a6a86a12685dfaae963e091da6d416c0e5b8c6',
    'git_blob':'06dafdbdeb53eb5ccf6480993596bbb4d939f203'}
packet = json.loads(packet_bytes)
manifest = json.loads((P/'MANIFEST.json').read_bytes())
assert len(packet['entries']) == len(manifest['entries']) == 28
inventory = json.loads(Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json').read_bytes())
baseline = {row['path']: row for row in inventory['files']}
rows=[]
for entry, expected in zip(packet['entries'], manifest['entries']):
    assert entry['path'] == expected['path'] and entry['mode'] == expected['mode'] == '100644'
    row={'path':entry['path'], 'before':entry['before'], 'after':entry['after']}
    for side in ['before','after']:
        spec=entry[side]
        assert spec == expected[side]
        if spec is None:
            assert entry[side+'_utf8'] is None
            assert not (P/side/entry['path']).exists()
        else:
            body=(P/side/entry['path']).read_bytes()
            assert body == entry[side+'_utf8'].encode('utf-8')
            assert pin(body) == spec
    if entry['before']:
        original=baseline.get(entry['path'])
        row['before_matches_b608'] = bool(original and original['working_blob'] == entry['before']['git_blob'])
        before=entry['before_utf8'];after=entry['after_utf8']
        operations=[]
        for tag,a,b,c,d in difflib.SequenceMatcher(None,before,after,autojunk=False).get_opcodes():
            if tag!='equal': operations.append({'before_offset':a,'before_end':b,'after_offset':c,'after_end':d,
                                             'before_utf8':before[a:b],'after_utf8':after[c:d]})
        forward=before
        for op in reversed(operations):
            assert forward[op['before_offset']:op['before_end']]==op['before_utf8']
            forward=forward[:op['before_offset']]+op['after_utf8']+forward[op['before_end']:]
        reverse=after
        for op in reversed(operations):
            assert reverse[op['after_offset']:op['after_end']]==op['after_utf8']
            reverse=reverse[:op['after_offset']]+op['before_utf8']+reverse[op['after_end']:]
        assert forward==after and reverse==before
        row['exact_splices']=operations
    rows.append(row)

# Exact original local driver method/helper bytes, not merely a method count.
old=text('before','circuit_task_driver.rs');new=text('after','circuit_task_driver.rs')
start='    pub(super) async fn execute('
assert old[old.index(start):] == new[new.index(start):]
driver_tail=pin(old[old.index(start):].encode())

# Exact existing driver tests after undoing only imports and generic spelling.
old=text('before','circuit_task_driver_tests.rs');new=text('after','circuit_task_driver_tests.rs')
new=replace_once(new,'use codex_hepta_neuron::CellStateOwnerV1;\n','')
new=replace_once(new,'use crate::AgentdCircuitCellOwnerV1;\n','')
new=replace_once(new,'CircuitTaskDriverV1<AgentdCircuitCellOwnerV1<CellPartitionOwnerV1, Model, Encoder>, Inputs>',
                'CircuitTaskDriverV1<CellPartitionOwnerV1, Model, Encoder, Inputs>')
assert new==old

# The new remote Cell duplicates the original pipeline and adds only live-loan observations.
old=text('before','circuit_cell.rs')
old=old[old.index('        let dispatch = admission.dispatch();'):old.index('\n    }\n}\n',old.index('    pub fn execute('))]
remote=text('after','circuit_cell_remote.rs')
remote=remote[remote.index('        let dispatch = admission.dispatch();'):remote.index('\n    }\n}\n')]
remote=replace_once(remote,'admission.owner_agent_id() != input.scope.agent_id.as_str()',
                    'admission.owner_agent_id().as_str() != input.scope.agent_id.as_str()')
remote=replace_once(remote,'                        if loan_failed.get() {\n                            return Err(CircuitCellErrorV1::ReconciliationRequired);\n                        }\n                        admission.require_current().map_err(|_| CircuitCellErrorV1::ReconciliationRequired)?;\n','')
remote=replace_once(remote,'        if loan_failed.get() {\n            return Err(CircuitCellErrorV1::ReconciliationRequired);\n        }\n        admission.require_current().map_err(|_| CircuitCellErrorV1::ReconciliationRequired)?;\n','')
assert old==remote
cell_tail=pin(old.encode())

# Signed ingress/outbox original body is unchanged after removing one private loan retention.
old=text('before','state_circuit_task.rs');new=text('after','state_circuit_task.rs')
new=replace_once(new,'        #[cfg(target_os = "linux")]\n        let _original_remote_record = handle.retain_original_remote_record(record)?;\n','')
assert new==old

# This is the actual GET body, preserved from the tool response, not a second implementation.
sdk=json.loads((D/'HOST_AUTHORITY_PEER.GET.original.json').read_bytes())
q=sdk['structuredContent']
q=q.get('structuredContent',q)
hap=q['content'].encode()
assert pin(hap)['git_blob']=='36e4524baea04320b7610325579f0ff206690fab'
(D/'HOST_AUTHORITY_PEER.original.rs').write_bytes(hap)

checks={
 'packet_identity':pin(packet_bytes),'manifest_identity':pin((P/'MANIFEST.json').read_bytes()),
 'counts':{'paths':28,'new':sum(x['before'] is None for x in rows),'modified':sum(x['before'] is not None for x in rows)},
 'all_full_images_equal_packet_and_manifest':True,
 'all_changed_files_exact_forward_and_inverse':True,
 'original_driver_all_methods_and_trailing_helpers_equal':driver_tail,
 'original_driver_tests_exact_after_three_compatibility_inverse':True,
 'original_cell_pipeline_exact_after_three_named_remote_inverse':cell_tail,
 'original_state_signed_runstart_outbox_whole_file_exact_after_loan_hunk_inverse':True,
 'host_peer_actual_get_body':pin(hap),
 'execution':{'project_code':False,'rust':False,'formatter':False,'qa':False,'collector':False,'h':False},
 'rows':rows,
}
print(save('BYTE_AND_BODY_REVIEW.json',checks))
