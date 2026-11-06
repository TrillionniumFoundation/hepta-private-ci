"""Root's local, read-only review of the frozen archival transport request."""
from pathlib import Path
import argparse
import ast
import base64
import hashlib
import importlib.util
import json
import sys
import zlib

sys.dont_write_bytecode = True


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def review(root, manifest_sha, plan_sha, request_sha):
    manifest_raw = (root / 'delivery-manifest.json').read_bytes()
    require(sha(manifest_raw) == manifest_sha, 'frozen delivery changed')
    manifest = json.loads(manifest_raw)
    seen = set()
    for row in manifest['files']:
        require(Path(row['path']).name == row['path'] and row['path'] not in seen, 'package path set')
        seen.add(row['path'])
        raw = (root / row['path']).read_bytes()
        require(len(raw) == row['bytes'] and sha(raw) == row['sha256'], 'package actual bytes: ' + row['path'])
    require(len(seen) == 13, 'thirteen package files including actual controls')
    plan_raw = (root / 'transport-plan.json').read_bytes()
    require(sha(plan_raw) == plan_sha, 'frozen plan changed')
    plan = json.loads(plan_raw)
    request_raw = (root / 'launch-request.json').read_bytes()
    require(sha(request_raw) == request_sha, 'frozen request changed')
    request = json.loads(request_raw)
    bootstrap = (root / 'bootstrap.py').read_bytes()
    require(request == dict(host='desktop', executable='/usr/bin/python3', args=['-B','-'],
        cwd='/home/qian-qi/work', env={'PYTHONDONTWRITEBYTECODE':'1','PYTHONOPTIMIZE':'0'},
        stdin=bootstrap.decode(), timeout_seconds=1200,
        idempotency_key='93bfc-hepta-h1-h2-h3-orphan-archive-git-transport-02'), 'exact process request')
    constants = {}
    for node in ast.parse(bootstrap).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0],ast.Name):
            name = node.targets[0].id
            if name in {'EXPECTED','BUNDLE_SHA256','BUNDLE_BYTES','ENCODED'}:
                constants[name] = ast.literal_eval(node.value)
    compressed = base64.b64decode(constants['ENCODED'], validate=True)
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, constants['BUNDLE_BYTES'] + 1)
    require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, 'one complete compressed bundle')
    require(raw == (root / 'transport-bundle.json').read_bytes() and
        sha(raw) == constants['BUNDLE_SHA256'] and len(raw) == constants['BUNDLE_BYTES'], 'actual embedded bundle')
    bundle = json.loads(raw)
    require(set(bundle['files']) == set(constants['EXPECTED']) ==
        {'run_archive_transport.py','credential_get_only.py','transport-plan.json'}, 'exact three staged files')
    for name, content in bundle['files'].items():
        actual = base64.b64decode(content, validate=True)
        require(actual == (root/name).read_bytes() and sha(actual) == constants['EXPECTED'][name], 'staged original: '+name)
    require(plan['repository'] == 'TrillionniumFoundation/hepta-private-ci' and
        plan['repository_visibility']['repository_id'] == '1320694176' and
        plan['repository_visibility']['observed'] == plan['repository_visibility']['required'] == 'public', 'fixed existing public repository')
    require(plan['destination_ref'] == 'refs/heads/evidence/actual-elf-transport-20261105-93bfc-01' and
        plan['expected_ref_before'] is None and plan['orphan_data_only'] and
        plan['transport_tree_blob_count'] == 166, 'one new orphan data ref')
    require(plan['limits'] == dict(outer_seconds=1200,push_seconds=900,ls_remote_seconds=60,
        max_parts=162,max_part_raw_bytes=4194304,total_raw_bytes=670306272,total_envelope_bytes=893742124), 'original archival budget and data bounds')
    require(len(plan['protected_configurations']) == 5, 'five configuration pins')
    originals = []
    for row in plan['archives']:
        phase = row['phase']
        path = root.parent.parent / 'w1' / (phase.lower()+'-elf-export') / (phase+'-export-completion.json')
        original = path.read_bytes()
        completion = json.loads(original)
        require(len(original) == row['completion_bytes'] and sha(original) == row['completion_sha256'], 'original completion '+phase)
        require(row['parts'] == completion['parts'] and row['archive_sha256'] == completion['archive_sha256'] and
            row['archive_bytes'] == completion['archive_bytes'] and row['archive_index_sha256'] == completion['archive_index_sha256'], 'unchanged archive and parts '+phase)
        require(row['completion_path'] == row['source_root'] + '/completion.json' and
            row['part_root'] == row['source_root'], 'actual remote original paths '+phase)
        originals.append({'phase':phase,'parts':len(row['parts']),'bytes':row['archive_bytes'],'sha256':row['archive_sha256']})
    require([r['phase'] for r in originals] == ['H1','H2','H3'] and [r['parts'] for r in originals] == [32,62,68], 'original phases and part counts')
    # Independently re-run the pure builder with every write intercepted in memory.
    spec = importlib.util.spec_from_file_location('root_review_builder',root/'build_transport_package.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    rebuilt = {}
    def capture(name, value):
        data = value if isinstance(value,bytes) else (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()
        require(name not in rebuilt, 'duplicate builder write')
        rebuilt[name] = data
        return dict(path=name,bytes=len(data),sha256=sha(data))
    builder.write = capture
    builder.main()
    for name, actual in rebuilt.items():
        require(actual == (root/name).read_bytes(), 'pure builder byte equality '+name)
    return dict(schema='root-frozen-archive-route-review-v2',status='PASS_EXACT_FROZEN_PACKAGE',
        delivery_manifest_sha256=manifest_sha,plan_sha256=plan_sha,request_sha256=request_sha,
        runner_sha256=sha((root/'run_archive_transport.py').read_bytes()),
        exact_package_files_verified=len(seen),bundle_members_verified=len(bundle['files']),
        pure_builder_outputs_byte_equal=sorted(rebuilt),original_archives=originals,
        original_parts=162,raw_archive_bytes=670306272,transport_envelope_bytes=893742124,
        destination=plan['repository'],repository_visibility='public',repository_id='1320694176',
        destination_ref=plan['destination_ref'],new_orphan_data_only=True,
        process_request_exact=True,outer_seconds=1200,push_seconds=900,
        remote_execution_by_this_review=False,publication_by_this_review=False,
        public_read_is_not_credential_or_write_authority_proof=True,
        new_native_or_capture_or_learning_credit=False)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    for name in ('package','manifest-sha','plan-sha','request-sha','output'):
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    result=review(Path(args.package).absolute(),args.manifest_sha,args.plan_sha,args.request_sha)
    raw=(json.dumps(result,sort_keys=True,indent=2)+'\n').encode()
    with Path(args.output).open('xb') as output:
        output.write(raw)
    print(json.dumps({'status':result['status'],'report_bytes':len(raw),'report_sha256':sha(raw)}))
