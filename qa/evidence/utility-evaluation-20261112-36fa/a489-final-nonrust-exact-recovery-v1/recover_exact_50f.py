"""Pure offline recovery from immutable pre-held source bytes and actual50f pins.

No project/native module is imported, no H request is made, and no source or Git
repository is opened. This reproduces the original serializers and raw/gzip/part
identities; it is not a second native full read or a qualification execution.
"""
from pathlib import Path
import ast
import base64
import copy
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parent
BASE = Path('/tmp/hepta-36fa-a489-maintenance-actual-inventory-recovery-v1/final.inventory.exact_recovered.json')
STRICT = Path('/tmp/hepta-36fa-a489-maintenance-nonrust-apply-packet-v1/NONRUST_PACKET.json')
PROPOSAL = Path('/tmp/hepta-36fa-a489-maintenance-registration-frozen-v1/SOURCE_PACKET.json')
EXPECTED = Path('/tmp/hepta-36fa-a489-maintenance-registration-frozen-v1/EXPECTED_AFTER_INVENTORY.json')
ORIGINALS = Path('/tmp/hepta-36fa-final-qualification-admission-successor-hold-v1/inputs')
KEYS = ('bytes', 'sha256', 'git_blob')


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': oid('blob', raw)}


def pin3(row):
    return {key: row[key] for key in KEYS}


def jbytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def inventory_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def write(name, raw):
    path = ROOT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, name
    else:
        path.write_bytes(raw)
    return {'name': name, **identity(raw)}


def tree(rows):
    root = {}
    for row in rows:
        assert row['stable'] is True and row['kind'] in ('file', 'symlink')
        node = root
        names = row['path'].split('/')
        for name in names[:-1]:
            node = node.setdefault(name, {})
        assert names[-1] not in node
        mode = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
        node[names[-1]] = (mode, row['working_blob'])
    def visit(node):
        parts = []
        for name, value in sorted(node.items(), key=lambda pair: pair[0].encode() + (b'/' if isinstance(pair[1], dict) else b'')):
            mode, sha = ('40000', visit(value)) if isinstance(value, dict) else value
            parts.append(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha))
        return oid('tree', b''.join(parts))
    return visit(root)


def functions(path, wanted):
    raw = path.read_bytes()
    lines = raw.decode().splitlines(keepends=True)
    result = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            body = ''.join(lines[node.lineno-1:node.end_lineno]).encode()
            result[node.name] = {'source': identity(body), 'body': body.decode()}
    assert set(result) == set(wanted)
    return result


def main():
    result_raw = (ROOT/'inputs/RESULT.original.json').read_bytes()
    artifacts_raw = (ROOT/'inputs/ARTIFACTS.original.json').read_bytes()
    normal_raw = (ROOT/'inputs/NORMAL.original.json').read_bytes()
    assert oid('blob', result_raw) == '800869ed57256984964dd3c8b9f29e09c496438a'
    assert oid('blob', artifacts_raw) == '0119bbc670ec82b93b5235d9e512f61f58baf409'
    assert oid('blob', normal_raw) == '0f7aee8fb7c354f234732b5791e78d63671cd894'
    result = json.loads(result_raw)
    outer = json.loads(normal_raw)
    terminal = json.loads(outer['content'][0]['text'])
    assert outer.get('isError') is False and len(outer['content']) == 1
    assert terminal['job_id'] == '1a1d4a979d9-392-50f' and terminal['state'] == 'succeeded'
    assert terminal['exit_code'] == 0 and terminal['timed_out'] is False and terminal['cancelled'] is False
    assert terminal['automatic_retry'] is False and terminal['output_complete'] is True and terminal['output_durable'] is True
    assert terminal['terminal_publication_confirmed'] is True and not any(terminal.get('log_truncated', {}).values())
    assert result['status'] == 'APPLIED_AND_FORMATTED_REVIEW_REQUIRED'
    assert result['format'] == 'hepta-reviewed-nonrust-final-format-result-v1'
    assert result['formatter_changed_paths'] == [] and result['attempted_commands'] == ['fmt']
    assert result['qualification'] is False and result['test_commands_dispatched'] == 0
    assert {row['check']:row['status'] for row in result['final_audits']} == {'actual_complete_source_and_git':'verified','original_inputs':'verified','same_source_coordination_lock':'verified'}
    artifacts = json.loads(artifacts_raw)['files']
    indexed = {row['name']:row for row in artifacts}
    assert len(artifacts) == len(indexed) == 210

    base_raw = BASE.read_bytes()
    strict_raw = STRICT.read_bytes()
    proposal_raw = PROPOSAL.read_bytes()
    assert oid('blob', base_raw) == '4a77b645fd76a980ef746997efbd09fcd8f233ba'
    assert oid('blob', strict_raw) == 'ab032ffdfd8b540a0d3a82558d8a07e70ab0c548'
    assert oid('blob', proposal_raw) == 'b3490071b2b109aa1854afd3353952890b8e0eab'
    before = json.loads(base_raw)
    strict = json.loads(strict_raw)
    proposal = json.loads(proposal_raw)
    assert result['baseline_inventory'] == identity(base_raw) == strict['base_inventory'] == proposal['base_inventory']
    assert result['baseline_physical_tree'] == strict['base_physical_tree'] == tree(before['files'])
    assert strict['source_identity'] == before['source']
    assert [row['path'] for row in strict['changes']] == result['applied_paths']
    assert len(strict['changes']) == 4
    after = copy.deepcopy(before)
    rows_before = {row['path']:row for row in before['files']}
    rows_after = {row['path']:row for row in after['files']}
    proposed = {row['path']:row for row in proposal['changes']}
    contents = {}
    for change in strict['changes']:
        path = change['path']
        old_row = rows_before[path]
        old = base64.b64decode(proposed[path]['before_raw_base64'], validate=True)
        new = base64.b64decode(change['after_base64'], validate=True)
        assert identity(old) == change['before']
        assert proposed[path]['before'] == old_row
        assert identity(new) == change['after']
        assert new == base64.b64decode(proposed[path]['after_raw_base64'], validate=True)
        assert {'bytes':old_row['bytes'],'sha256':old_row['sha256'],'git_blob':old_row['working_blob']} == identity(old)
        assert old_row['kind'] == 'file' and old_row['permissions'] == 0o644 and change['mode'] == '100644'
        rows_after[path].update(bytes=len(new),sha256=identity(new)['sha256'],working_blob=oid('blob',new),matches_index=oid('blob',new)==old_row['index_blob'])
        assert proposed[path]['after'] == rows_after[path]
        contents[path] = (old, new)
    dirty = sorted(row['path'] for row in after['files'] if row['matches_index'] is not True)
    assert len(dirty) == 21
    after['source']['status'] = ''.join(' M '+path+'\n' for path in dirty).strip()
    after_raw = inventory_bytes(after)
    assert after_raw == EXPECTED.read_bytes()
    assert identity(after_raw) == result['actual_final_source']['inventory']
    assert after['source']['head'] == result['source_commit'] and after['source']['tree'] == result['source_tree']
    assert after['tracked_entries'] == after['filesystem_entries'] == len(after['files']) == 15243
    physical = tree(after['files'])
    assert physical == result['actual_final_source']['postimages']['all_actual_physical_tree'] == '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'
    assert physical == strict['expected_after_physical_tree']
    assert len(after['files']) == strict['expected_after_leaf_count']
    assert [path for path in sorted(rows_before) if rows_before[path] != rows_after[path]] == result['applied_paths']
    inventory_record = write('final.inventory.exact_recovered.json', after_raw)

    changes = [{'path':path,'before':rows_before[path],'after':rows_after[path],
                'before_raw_base64':base64.b64encode(contents[path][0]).decode('ascii'),
                'after_raw_base64':base64.b64encode(contents[path][1]).decode('ascii')} for path in sorted(contents)]
    reconstructed = {}
    for stage in ('apply.after','final'):
        packet = {'format':'hepta-maintenance-actual-source-transition-v1','stage':stage,
                  'source_commit_unchanged':result['source_commit'],
                  'base_inventory_sha256':identity(base_raw)['sha256'],
                  'after_inventory_sha256':identity(after_raw)['sha256'],'changes':changes,
                  'all_physical_changes_including_untracked_or_ignored_are_recorded':True,'qualification':False}
        raw = jbytes(packet)
        name = stage+'.postimages.json.gz'
        assert identity(raw) == {key:indexed[name]['raw_'+key] for key in KEYS}, stage
        write(stage+'.postimages.exact_recovered.json',raw)
        reconstructed[name] = raw
    for name in ('apply.after.inventory.json.gz','fmt.after.inventory.json.gz','final.inventory.json.gz'):
        reconstructed[name] = after_raw

    proofs = []
    bounded = {}
    for name, raw in reconstructed.items():
        record = indexed[name]
        assert identity(raw) == {key:record['raw_'+key] for key in KEYS}
        compressed = gzip.compress(raw,mtime=0)
        assert gzip.decompress(compressed) == raw
        assert identity(compressed) == pin3(record), name
        write(name, compressed)
        parts = []
        for number, offset in enumerate(range(0,len(compressed),262144),1):
            block = compressed[offset:offset+262144]
            body = base64.b64encode(block)+b'\n'
            original = record['parts'][number-1]
            assert original['name'] == name+'.part-%03d.b64'%number
            assert identity(body) == pin3(original)
            assert original['decoded_offset'] == offset and original['decoded_bytes'] == len(block)
            assert original['decoded_sha256'] == hashlib.sha256(block).hexdigest()
            assert base64.b64decode(body[:-1],validate=True) == block
            assert pin3(indexed[original['name']]) == identity(body)
            write(original['name'],body)
            parts.append(original)
            bounded.setdefault(identity(body)['git_blob'], {'name':original['name'],**identity(body),'aliases':[]})['aliases'].append(original['name'])
        assert len(parts) == len(record['parts'])
        proofs.append({'name':name,'raw':identity(raw),'gzip':identity(compressed),'parts':parts,'all_actual_ARTIFACTS_pins_equal':True})

    serializers = {'inventory':functions(ORIGINALS/'SOURCE_GATES_5118.py',{'inventory'}),
                   'transition_and_gzip':functions(ORIGINALS/'MAINTENANCE_41E.original.py',{'jbytes','gzrecord','archive_transition'})}
    write('ORIGINAL_SERIALIZER_SOURCES.json',(json.dumps(serializers,sort_keys=True,indent=2)+'\n').encode())
    review = {'format':'hepta-final50f-exact-offline-recovery-v1','status':'ALL_ORIGINAL_RAW_GZIP_PART_PINS_EXACT',
        'actual_job':terminal['job_id'],'actual_result':identity(result_raw),'actual_normal':identity(normal_raw),'actual_artifacts':identity(artifacts_raw),
        'provenance':'Exact deterministic recovery from pre-held complete4a77/ab032/b349 source bytes against actual50f producer identities. Not a second H whole-file or full source read.',
        'base_inventory':identity(base_raw),'strict_reviewed_packet':identity(strict_raw),'complete_before_after_proposal':identity(proposal_raw),
        'same_preheld_expected_inventory_bytes_now_equal_actual_pin':identity(after_raw),'full_physical_tree':physical,
        'leaf_count':15243,'actual_changed_source_paths':result['applied_paths'],'actual_final_dirty_paths_count':len(dirty),
        'source_status_provenance':'Unique original5118 strip() serialization from complete actual transitions and all original indexed rows, accepted only after whole raw/gzip/allpart identity equality; not an independent native status capture.',
        'all_unchanged_rows_exact':True,'changed_rows':len(changes),'actual_formatter_changes':[],
        'alias_records':proofs,'distinct_bounded_parts':list(bounded.values()),
        'original_serializer_sources':identity((ROOT/'ORIGINAL_SERIALIZER_SOURCES.json').read_bytes()),
        'full_raw_artifacts_retained_locally':[inventory_record,identity(reconstructed['apply.after.postimages.json.gz']),identity(reconstructed['final.postimages.json.gz'])],
        'H_calls':0,'project_gate_commands':0,'source_or_ref_mutations':0,'qualification':False,
        'canonical_alignment_actual':None,'future_clean_source_identity':None}
    write('REVIEW.json',(json.dumps(review,sort_keys=True,indent=2)+'\n').encode())
    manifest={'format':'hepta-final50f-recovery-bounded-manifest-v1','actual_job':terminal['job_id'],
        'raws':[{'name':'final.inventory.exact_recovered.json',**identity(after_raw)},
                {'name':'apply.after.postimages.exact_recovered.json',**identity(reconstructed['apply.after.postimages.json.gz'])},
                {'name':'final.postimages.exact_recovered.json',**identity(reconstructed['final.postimages.json.gz'])}],
        'bounded_parts':list(bounded.values()),'all_alias_record_proofs':proofs,
        'direct_raw_Git_upload_claimed':False,'maximum_evidence_leaf_bytes':512000,
        'review':identity((ROOT/'REVIEW.json').read_bytes()),'script':identity(Path(__file__).read_bytes())}
    write('MANIFEST.json',(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode())
    print(json.dumps({'status':review['status'],'actual_job':terminal['job_id'],'inventory':identity(after_raw),
        'physical_tree':physical,'review':identity((ROOT/'REVIEW.json').read_bytes()),'manifest':identity((ROOT/'MANIFEST.json').read_bytes()),
        'distinct_parts':len(bounded),'original_alias_parts_checked':sum(len(row['parts']) for row in proofs),'H_calls':0},indent=2))


if __name__ == '__main__':
    main()
