"""Pure recovery from pre-held bytes matched to complete actual 5a9 pins.

No H, native source read, Git mutation, project gate, or producer invocation.
"""
from pathlib import Path
import ast
import base64
import collections
import gzip
import hashlib
import json
import os

BASE = Path(__file__).resolve().parent
INPUT = BASE / 'inputs'
BEFORE = Path('/tmp/hepta-36fa-a489-final-nonrust-exact-recovery-v1/final.inventory.exact_recovered.json')
AFTER = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1/EXPECTED_AFTER_INVENTORY.json')
ORIGINAL = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1/inputs/CANONICAL_TEMPLATE_E8D606.HOLD.py')
NATIVE_PROJECTION_SOURCE = Path('/tmp/hepta-36fa-final-qualification-admission-code-hold-v1/inputs/MATERIALIZER_3BB.original.py')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def pin(raw, expected):
    got = identity(raw)
    assert all(expected[key] == value for key, value in got.items()), (got, expected)
    return got


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def write_exact(name, raw):
    target = BASE / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == raw, name
    else:
        target.write_bytes(raw)
    assert target.read_bytes() == raw
    return {'name': name, 'local_path': str(target), **identity(raw)}


def physical(value):
    assert value['tracked_entries'] == value['filesystem_entries'] == len(value['files']) == 15243
    result = {}
    for row in value['files']:
        name = row['path']
        assert isinstance(name, str) and '\0' not in name and not name.startswith('/')
        assert all(part not in ('', '.', '..', '.git') for part in name.split('/'))
        assert name not in result and row['kind'] in ('file', 'symlink') and row['stable'] is True
        result[name] = {key: item for key, item in row.items() if key not in ('index_mode','index_blob','matches_index')}
    return result


def merkle(value):
    directories = {'': {}}
    modes = collections.Counter()
    for row in value['files']:
        mode = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
        modes[mode] += 1
        path = row['path']; parts = path.split('/')
        for index in range(1, len(parts)):
            directory = '/'.join(parts[:index])
            parent = '/'.join(parts[:index-1])
            directories.setdefault(directory, {})
            old = directories[parent].get(parts[index-1])
            assert old is None or old == ('40000', directory)
            directories[parent][parts[index-1]] = ('40000', directory)
        parent = '/'.join(parts[:-1])
        assert parts[-1] not in directories[parent]
        directories[parent][parts[-1]] = (mode, row['working_blob'])
    tree_hashes = {}
    def descend(directory):
        rows = []
        for name, (mode, target) in directories[directory].items():
            sha = descend(target) if mode == '40000' else target
            rows.append((os.fsencode(name) + (b'/' if mode == '40000' else b''),
                         mode.encode() + b' ' + os.fsencode(name) + b'\0' + bytes.fromhex(sha)))
        raw = b''.join(item[1] for item in sorted(rows))
        digest = hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        tree_hashes[directory] = digest
        return digest
    root = descend('')
    return {'root':root,'directory_trees':len(tree_hashes),'leaves':len(value['files']),
            'modes':dict(sorted(modes.items())),
            'all_repository_rust_files':sum(row['path'].endswith('.rs') for row in value['files']),
            'codex_rs_rust_files':sum(row['path'].startswith('codex-rs/') and row['path'].endswith('.rs') for row in value['files'])}


def main():
    result_raw = (INPUT/'RESULT.original.json').read_bytes()
    artifacts_raw = (INPUT/'ARTIFACTS.original.json').read_bytes()
    normal_raw = (INPUT/'NORMAL.original.json').read_bytes()
    assert identity(result_raw)['git_blob'] == '5aa9590a7b68504bd58ad0d0b889605c7e8ad71d'
    assert identity(artifacts_raw)['git_blob'] == '84efb7055e5f8d4bbb5d37e1fa93769d36e69ded'
    assert identity(normal_raw)['git_blob'] == '2deafbe4bfc7ad2c84d9e6315c12aaa6493adab2'
    result, artifacts, outer = json.loads(result_raw), json.loads(artifacts_raw), json.loads(normal_raw)
    assert outer.get('isError') is False and len(outer['content']) == 1 and outer['content'][0]['type'] == 'text'
    normal = json.loads(outer['content'][0]['text'])
    assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
    assert all(normal[key] is False for key in ('timed_out','cancelled','automatic_retry'))
    assert all(normal[key] is True for key in ('output_complete','output_durable','terminal_publication_confirmed'))
    assert not any(normal.get('log_truncated',{}).values())
    assert result['format'] == 'hepta-final-canonical-alignment-result-v1'
    assert result['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
    assert result['physical_source_writes_dispatched'] == 0 and result['test_commands_dispatched'] == 0
    assert {r['check']:r['status'] for r in result['final_audits']} == {'source':'verified','git':'verified','inputs':'verified'}
    catalog = {row['name']: row for row in artifacts}
    assert len(catalog) == len(artifacts)
    recovered, archive_rows = [], []
    recovered_values = {}
    for label, source, artifact_name in [('before', BEFORE, 'SOURCE.before.inventory.json.gz'),
                                         ('final', AFTER, 'SOURCE.final.inventory.json.gz')]:
        raw = source.read_bytes(); observed = catalog[artifact_name]
        expected = {key: observed['raw_'+key] for key in ('bytes','sha256','git_blob')}
        raw_identity = pin(raw, expected)
        endpoint = result['before' if label == 'before' else 'after']
        pin(raw, endpoint['inventory'])
        value = json.loads(raw); physical(value)
        assert value['source']['head'] == endpoint['commit'] and value['source']['tree'] == endpoint['tree']
        raw_row = write_exact('SOURCE.'+label+'.inventory.exact_recovered.json', raw)
        compressed = gzip.compress(raw, mtime=0)
        pin(compressed, observed)
        assert gzip.decompress(compressed) == raw
        gzip_row = write_exact(artifact_name, compressed)
        part_rows, decoded = [], []
        for index, offset in enumerate(range(0,len(compressed),262144),1):
            chunk = compressed[offset:offset+262144]
            encoded = base64.b64encode(chunk) + b'\n'
            name = artifact_name+'.part-%03d.b64'%index
            nested = observed['parts'][index-1]
            assert nested['name'] == name and nested == catalog[name]
            pin(encoded, nested)
            assert nested['decoded_offset'] == offset and nested['decoded_bytes'] == len(chunk)
            assert nested['decoded_sha256'] == hashlib.sha256(chunk).hexdigest()
            assert base64.b64decode(encoded, validate=False) == chunk
            assert base64.b64encode(base64.b64decode(encoded[:-1], validate=True))+b'\n' == encoded
            row=write_exact(name,encoded);row['chars']=len(encoded.decode('ascii'))
            part_rows.append(row);archive_rows.append(row);decoded.append(chunk)
        assert len(part_rows) == len(observed['parts']) == 5 and b''.join(decoded) == compressed
        recovered_values[label]=value
        recovered.append({'endpoint':label,'preheld_source_path':str(source),
            'provenance':'Existing pre-held bytes, independently matched to all actual producer raw/gzip/part identities; not a second H source read.',
            'raw':raw_row,'gzip':gzip_row,'original_artifact':observed,'original_parts':part_rows,
            'all_original_raw_gzip_part_identities_equal':True,'tree':merkle(value)})
    before, after = recovered_values['before'], recovered_values['final']
    assert physical(before) == physical(after)
    assert after['source'] == {'head':'b6084394a4a38ab495c16eaba09e879f04a96f8e',
                              'tree':'8ebb37e523ad3932a58cf016af0a9f4e0eeb6638','status':''}
    assert result['after']['parents'] == ['d25675445c39f76db69a7bd8e71a1a72e1cd5b9f']
    assert all(row['matches_index'] is True and row['index_blob'] == row['working_blob'] for row in after['files'])
    assert all(row['tree']['root'] == after['source']['tree'] for row in recovered)
    native = [{'path':row['path'],'mode':row['index_mode'],'bytes':row['bytes'],
               'sha256':row['sha256'],'blob':row['working_blob']} for row in after['files']]
    native.sort(key=lambda row:os.fsencode(row['path']))
    native_raw=json.dumps(native,sort_keys=True,separators=(',',':')).encode()
    native_row=write_exact('NATIVE.expected_from_actual_clean_inventory.json',native_raw)
    source_raw=ORIGINAL.read_bytes();source_text=source_raw.decode();lines=source_text.splitlines(True)
    assert identity(source_raw)['git_blob']=='e8d606b801b54ab949c5f215c49cdf47ed0ea89a'
    methods={node.name:''.join(lines[node.lineno-1:node.end_lineno]) for node in ast.parse(source_text).body
             if isinstance(node,ast.FunctionDef) and node.name in ('gzrecord','inventory_summary','physical_projection')}
    assert set(methods)=={'gzrecord','inventory_summary','physical_projection'}
    fragment='\n\n'.join(methods.values())+'\n'
    archive_rows.append(dict(write_exact('ORIGINAL_CANONICAL_SERIALIZER_AND_PROJECTION.py.txt',fragment.encode()),chars=len(fragment)))
    native_source=NATIVE_PROJECTION_SOURCE.read_bytes();s=native_source.decode();lines=s.splitlines(True)
    n=next(node for node in ast.parse(s).body if isinstance(node,ast.FunctionDef) and node.name=='native_projection')
    text=''.join(lines[n.lineno-1:n.end_lineno])+'\n'
    archive_rows.append(dict(write_exact('ORIGINAL_NATIVE_PROJECTION.py.txt',text.encode()),chars=len(text)))
    report={'format':'hepta-5a9-complete-inventory-exact-recovery-v1','status':'ALL_ACTUAL_RAW_GZIP_AND_TEN_PART_PINS_MATCH',
        'actual_job_id':normal['job_id'],'actual_result':identity(result_raw),'actual_artifacts':identity(artifacts_raw),
        'actual_normal':identity(normal_raw),'original_serializer':identity(source_raw),
        'H_calls':0,'native_source_read_calls':0,'source_or_ref_writes':False,'qualification':False,
        'source_gates_executed':False,'native_test_execution_observed':False,
        'recovered':recovered,'all_physical_rows_unchanged':True,
        'actual_canonical_subject':{'commit':result['after']['commit'],'tree':result['after']['tree'],'parents':result['after']['parents']},
        'derived_native_projection':{**native_row,'scope':'Pure expected original five-field projection from exact actual full inventory. No b92 snapshot or native qualification has run.'},
        'no_oversized_raw_Git_upload_claimed':True,
        'metadata_and_index_scope':'Actual complete metadata/index extraction and review remain native/Root responsibilities; this recovery does not replace them.',
        'original_artifact_rows':len(artifacts),'bounded_original_parts':10}
    review_raw=json_bytes(report);archive_rows.append(dict(write_exact('EXACT_RECOVERY_REVIEW.json',review_raw),chars=len(review_raw.decode())))
    manifest={'format':'hepta-original-raw-gzip-part-reconstruction-manifest-v1','producer':identity(result_raw),
              'catalog':identity(artifacts_raw),'recovered':[{key:row[key] for key in ('endpoint','raw','gzip','original_parts')} for row in recovered],
              'representation':'Each original gzip is the concatenation of five strict-base64 leaves; decode once then decompress losslessly.',
              'provenance':'No new H inventory read. Pre-held raw content is accepted only after all actual full identities agree.',
              'derived_native_projection_expected_only':native_row}
    manifest_raw=json_bytes(manifest);archive_rows.append(dict(write_exact('LOSSLESS_MANIFEST.json',manifest_raw),chars=len(manifest_raw.decode())))
    script_raw=Path(__file__).read_bytes()
    archive_rows.append({'name':Path(__file__).name,'local_path':str(Path(__file__)),'chars':len(script_raw.decode()),**identity(script_raw)})
    for name in ['RESULT.original.json','ARTIFACTS.original.json','NORMAL.original.json']:
        raw=(INPUT/name).read_bytes();archive_rows.append({'name':'inputs/'+name,'local_path':str(INPUT/name),'chars':len(raw.decode()),**identity(raw)})
    assert all(row['bytes']<=512000 for row in archive_rows)
    (BASE/'ARCHIVE_PAYLOAD_INDEX.json').write_bytes(json_bytes(archive_rows))
    print(json.dumps({'review':identity(review_raw),'raw':[row['raw'] for row in recovered],
                      'gzip':[row['gzip'] for row in recovered],'derived_native_expected':native_row,
                      'physical':recovered[1]['tree'],'bounded_payloads':len(archive_rows)}))


if __name__=='__main__':main()
