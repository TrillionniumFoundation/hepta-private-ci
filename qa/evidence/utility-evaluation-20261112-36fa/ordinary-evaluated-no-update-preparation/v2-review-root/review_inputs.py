import ast
import base64
import gzip
import hashlib
import json
import pathlib
import tomllib

ROOT = pathlib.Path('/tmp')
inputs = json.loads((ROOT / 'hepta-36fa-next-preparation-root-input.json').read_text())
v22 = json.loads((ROOT / 'hepta-36fa-root-version22-review-input.json').read_text())
a96 = {e['path']: e for e in json.loads((ROOT / 'hepta-36fa-fixed-a96d1-complete-leaf-map.json').read_text())['entries']}
c0f = {e['path']: e for e in json.loads((ROOT / 'hepta-36fa-final-formatted-source/expected-leaf-map.json').read_text())['entries']}
source_delta = json.loads((ROOT / 'hepta-36fa-fixed-a96d1-tree-delta.json').read_text())['source_changes']
delta_by_path = {e['path']: e for e in source_delta}

def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def verify(data, meta, git_key='git_blob'):
    assert len(data) == meta['bytes'], (len(data), meta)
    assert hashlib.sha256(data).hexdigest() == meta['sha256'], meta
    assert blob(data) == meta[git_key], meta

known = {p: {'git_blob': e['sha']} for p, e in a96.items()}
packets = []
for stem, bundle in [('version_readiness_v2_stable', v22), ('cold_admission_v1', inputs), ('cold_invalidation_v1', inputs)]:
    prefix = '' if bundle is v22 else stem + '_'
    manifest = json.loads(bundle[prefix + 'manifest']['content'])
    b64 = bundle[prefix + 'packet']['content'].encode()
    verify(b64, manifest['gzip_base64_packet'])
    raw = gzip.decompress(base64.b64decode(b64))
    verify(raw, manifest['packet'])
    packet = json.loads(raw)
    assert len(packet['files']) == len(manifest['files'])
    for item, declared in zip(packet['files'], manifest['files']):
        path = item['path']
        assert path == declared['path'] and item['before'] == declared['before'] and item['after'] == declared['after']
        before = item['before']
        if before is None:
            assert path not in known, (stem, path, 'unexpected prior file')
        else:
            assert before['git_blob'] == known[path]['git_blob'], (stem, path, 'preimage')
            if 'bytes' in known[path]:
                assert before == known[path], (stem, path, 'preimage bytes')
        data = base64.b64decode(item['postimage_base64'])
        verify(data, item['after'])
        known[path] = item['after']
    packets.append({'manifest': bundle[prefix + 'manifest']['sha'], 'packet': bundle[prefix + 'packet']['sha'], 'paths': len(packet['files']), 'all_preimages_and_postimages_verified': True, 'scope': 'isolated source preparation only; no formatting, compilation or runtime execution'})

merge = json.loads(gzip.decompress(base64.b64decode(inputs['eleven_merge_packet']['content'])))
manifest = json.loads(inputs['eleven_merge_manifest']['content'])
assert merge['manifest'] == manifest
merge_local = pathlib.Path('/tmp/hepta-c0f-a96d1-merge-36fa-_dmp6swh')
qa_function_counts = {}
for change, declared in zip(merge['changes'], manifest['files']):
    path = change['path']
    assert all(change[k] == v for k, v in declared.items())
    verify(change['content'].encode(), change, 'candidate_blob')
    assert a96[path]['sha'] == change['fixed_a96_blob']
    assert c0f[path]['sha'] == change['c0f_blob']
    assert delta_by_path[path]['old']['sha'] == change['base_b298_blob']
    for parent, field in [('base', 'base_b298_blob'), ('c0f', 'c0f_blob'), ('a96d1', 'fixed_a96_blob')]:
        data = (merge_local / parent / path).read_bytes()
        assert blob(data) == change[field], (parent, path)
    if path.startswith('qa/'):
        old = ast.parse((merge_local / 'a96d1' / path).read_text())
        new = ast.parse(change['content'])
        funcs = lambda tree: {n.name: ast.dump(n, include_attributes=False) for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert funcs(old) == funcs(new), path
        qa_function_counts[path] = len(funcs(new))

callers = next(x['content'] for x in merge['changes'] if x['path'] == 'CALLERS.toml')
toml = tomllib.loads(callers)
result = {'schema': 'hepta.next-preparation-root-review.v1', 'current_source': 'c0f78493f815780f68b9bf5e390a21314d79311f', 'fixed_upstream': 'a96d1b821d10ed3d9e99dd06c5141f9f242ae318', 'version_readiness_cold_packet_chain': packets, 'dual_modified_paths': len(merge['changes']), 'dual_modified_parent_blob_checks': 33, 'dual_modified_postimages_verified': True, 'qa_functions_identical_to_fixed_upstream_ast': qa_function_counts, 'callers_toml_parsed': True, 'scope': 'Content identity and static review only. Full current c0f gates are not inherited by these preparations. Final unified formatting, source markers, caller protection, original runtime tests and real ordinary A/B/C/Root qualification are not established.', 'cold_reader_findings': [{'finding': 'Recovered Version used to expose a selection reader before its full original recovery read completed.', 'prepared_fix': 'Build locally and install only after two matching original reads, original cut freshness and lifetime checks.', 'runtime_counterexample': 'not_run'}, {'finding': 'After a successful cold read, subsequent failed bind/current validation could bypass reader invalidation.', 'prepared_fix': 'The actual command_response bind failure clears only Recovered reader under the original state lock; original wire request helper avoids fixture prebinding.', 'runtime_counterexample': 'not_run'}], 'limits': ['This is not the complete next source projection.', 'Already handed-out read-only Arcs are not claimed revoked.', 'Initial material clock and final response failures remain under source review; no blanket closure claim.', 'Fresh late FinalUse failure requires original UID 0 issuer fixture and has not run.', 'Provider scenario partition and setup topology change are explicit; no timeout cause or behavior pass inferred.']}
(ROOT / 'hepta-36fa-next-preparation-ROOT_REVIEW.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
