"""Frozen stdlib-only qualification. Execute ONLY through reviewed run_once.py."""
import copy
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time

ROOT = Path(__file__).absolute().parent
sys.path.insert(0, str(ROOT))
import materialize as m

NEGATIVE_CASES = [
    'duplicate_json_key', 'unsupported_schema', 'extra_schema_key',
    'bool_original_size', 'negative_original_size', 'wrong_original_size',
    'wrong_original_hash', 'malformed_hash', 'unsafe_destination',
    'absolute_destination', 'duplicate_destination', 'missing_destination',
    'extra_destination', 'wrong_capsule_mapping', 'target_RUN_ONCE_mapping',
    'missing_record', 'duplicate_record', 'extra_record', 'wrong_record_order',
    'record_offset_gap', 'record_offset_overlap', 'negative_record_offset',
    'bool_record_index', 'oversize_record', 'wrong_record_digest',
    'wrong_terminal_length', 'wrong_whole_archive_digest', 'unknown_storage_kind',
    'malformed_storage_path', 'oversize_manifest', 'missing_part',
    'bit_corrupt_part', 'truncated_part', 'oversize_part', 'symlink_part',
    'symlink_source_file', 'symlink_source_ancestor', 'symlink_package_root',
    'symlink_output_parent', 'existing_empty_output', 'partial_prior_directory',
    'existing_output_symlink', 'injected_write_failure', 'written_output_drift',
    'corrupt_source_file', 'extra_stored_object'
]


def main():
    if len(sys.argv) != 2:
        raise ValueError('reviewed runner output path required')
    out = m.checked_path(sys.argv[1])
    if not out.is_dir(): raise ValueError('qualification output root')
    started = time.monotonic(); cpu = time.process_time()
    counters = {'consumer_read_calls': 0, 'consumer_read_bytes': 0,
                'consumer_hash_calls': 0, 'consumer_hash_bytes': 0,
                'consumer_hash_CPU_seconds': 0.0, 'consumer_write_calls': 0,
                'consumer_write_bytes': 0, 'fixture_write_calls': 0,
                'fixture_write_bytes_cumulative': 0}
    original_read, original_hash, original_write = m.read_regular, m.H, m._write_file
    def tracked_read(path, size):
        value = original_read(path, size)
        counters['consumer_read_calls'] += 1; counters['consumer_read_bytes'] += len(value)
        return value
    def tracked_hash(value):
        start = time.process_time(); result = original_hash(value)
        counters['consumer_hash_CPU_seconds'] += time.process_time() - start
        counters['consumer_hash_calls'] += 1; counters['consumer_hash_bytes'] += len(value)
        return result
    def tracked_write(path, value):
        original_write(path, value)
        counters['consumer_write_calls'] += 1; counters['consumer_write_bytes'] += len(value)
    m.read_regular, m.H, m._write_file = tracked_read, tracked_hash, tracked_write
    cases=[];positive=[]
    def fixture_write(path, value):
        path.write_bytes(value)
        counters['fixture_write_calls'] += 1; counters['fixture_write_bytes_cumulative'] += len(value)
    def negative(name, call, target=None, partial=False):
        if name != NEGATIVE_CASES[len(cases)]: raise AssertionError('negative case schedule drift')
        try: call()
        except (ValueError, OSError) as error:
            cases.append({'name': name, 'exception': type(error).__name__, 'message': str(error)[:240]})
        else: raise AssertionError('unexpected negative acceptance: ' + name)
        if target is not None:
            if not partial and os.path.lexists(target): raise AssertionError('preflight created output: '+name)
            if partial and (target/m.RECEIPT).exists(): raise AssertionError('failed output has completion receipt')
    workspaces=out/'workspaces';workspaces.mkdir()
    for name in sorted(m.CAPSULES):
        target=workspaces/name
        a=time.process_time(); result=m.materialize(ROOT,name,target)
        result['consumer_CPU_seconds']=time.process_time()-a
        c=m.CAPSULES[name]
        expected=set(c['source_files']+c['input_files'])|{m.RECEIPT}
        if m.tree_paths(target)!=expected or (target/name/'RUN_ONCE').exists():raise AssertionError('fresh workspace closure')
        for path in expected-{m.RECEIPT}:
            b=(target/path).read_bytes()
            if (len(b),hashlib.sha256(b).hexdigest())!=tuple(m.EXPECTED_FILES[path]):raise AssertionError('original byte identity')
        if (target/m.RECEIPT).read_bytes()!=m.receipt_for(name):raise AssertionError('completion receipt identity')
        # The five later capsules contain selected delivery-v2 RUN_ONCE inputs as
        # data; none includes a runnable delivery-v2 runner or its complete tree.
        positive.append(result)
    fixture=out/'fixture-package';fixture.mkdir()
    for folder in ('files','objects'):
        for path in sorted((ROOT/folder).rglob('*')):
            if path.is_file():
                target=fixture/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
                fixture_write(target,path.read_bytes())
    manifest_raw=(ROOT/'capsule-manifest.json').read_bytes()
    manifest=json.loads(manifest_raw)
    manifest_path=fixture/'capsule-manifest.json';fixture_write(manifest_path,manifest_raw)
    negative_root=out/'negative';negative_root.mkdir()
    selected='joint-policy-delivery-candidate-v2'
    content_index=next(i for i,x in enumerate(manifest['files']) if x['path']==m.CONTENT_PATH)
    def changed(name, fn):
        data=copy.deepcopy(manifest);fn(data)
        fixture_write(manifest_path,json.dumps(data,separators=(',',':')).encode('ascii'))
        target=negative_root/name
        negative(name,lambda:m.materialize(fixture,selected,target),target)
        fixture_write(manifest_path,manifest_raw)
    def record(data):return data['files'][content_index]['storage']['records']
    # No fixture repins the consumer's immutable spec. All malformed schemas or
    # identities must refuse; even structurally valid alterations fail the pin.
    fixture_write(manifest_path,b'{"schema":"x","schema":"x"}')
    target=negative_root/'duplicate_json_key'
    negative('duplicate_json_key',lambda:m.materialize(fixture,selected,target),target)
    fixture_write(manifest_path,manifest_raw)
    mutations=[
        ('unsupported_schema',lambda d:d.update(schema='unsupported')),
        ('extra_schema_key',lambda d:d.update(extra=1)),
        ('bool_original_size',lambda d:d['files'][0].update(bytes=True)),
        ('negative_original_size',lambda d:d['files'][0].update(bytes=-1)),
        ('wrong_original_size',lambda d:d['files'][0].update(bytes=d['files'][0]['bytes']+1)),
        ('wrong_original_hash',lambda d:d['files'][0].update(sha256='0'*64)),
        ('malformed_hash',lambda d:d['files'][0].update(sha256='invalid')),
        ('unsafe_destination',lambda d:d['files'][0].update(path='../escape')),
        ('absolute_destination',lambda d:d['files'][0].update(path='/escape')),
        ('duplicate_destination',lambda d:d['files'].__setitem__(1,copy.deepcopy(d['files'][0]))),
        ('missing_destination',lambda d:d['files'].pop()),
        ('extra_destination',lambda d:d['files'].append(copy.deepcopy(d['files'][0]))),
        ('wrong_capsule_mapping',lambda d:d['capsules'][selected]['source_files'].__setitem__(0,'arbitrary.py')),
        ('target_RUN_ONCE_mapping',lambda d:d['capsules'][selected]['source_files'].__setitem__(0,selected+'/RUN_ONCE/replayed')),
        ('missing_record',lambda d:record(d).pop()),
        ('duplicate_record',lambda d:record(d).__setitem__(1,copy.deepcopy(record(d)[0]))),
        ('extra_record',lambda d:record(d).append(copy.deepcopy(record(d)[0]))),
        ('wrong_record_order',lambda d:record(d).__setitem__(slice(0,2),list(reversed(record(d)[:2])))),
        ('record_offset_gap',lambda d:record(d)[1].update(offset=record(d)[1]['offset']+1)),
        ('record_offset_overlap',lambda d:record(d)[1].update(offset=record(d)[1]['offset']-1)),
        ('negative_record_offset',lambda d:record(d)[0].update(offset=-1)),
        ('bool_record_index',lambda d:record(d)[0].update(index=False)),
        ('oversize_record',lambda d:record(d)[0].update(bytes=512000)),
        ('wrong_record_digest',lambda d:record(d)[0].update(sha256='0'*64)),
        ('wrong_terminal_length',lambda d:record(d)[-1].update(bytes=4938)),
        ('wrong_whole_archive_digest',lambda d:d['files'][content_index].update(sha256='0'*64)),
        ('unknown_storage_kind',lambda d:d['files'][0]['storage'].update(kind='extract-archive')),
        ('malformed_storage_path',lambda d:d['files'][0]['storage'].update(path='../escape'))]
    for name,fn in mutations:changed(name,fn)
    fixture_write(manifest_path,b'x'*(m.MANIFEST_BYTES+1))
    target=negative_root/'oversize_manifest'
    negative('oversize_manifest',lambda:m.materialize(fixture,selected,target),target)
    fixture_write(manifest_path,manifest_raw)
    part=fixture/'objects'/(m.EXPECTED_RECORDS[0]['sha256']+'.bin');part_raw=part.read_bytes()
    part.unlink();target=negative_root/'missing_part'
    negative('missing_part',lambda:m.materialize(fixture,selected,target),target)
    fixture_write(part,part_raw)
    for name,raw in [('bit_corrupt_part',bytes([part_raw[0]^1])+part_raw[1:]),('truncated_part',part_raw[:-1]),('oversize_part',part_raw+b'x')]:
        fixture_write(part,raw);target=negative_root/name
        negative(name,lambda:m.materialize(fixture,selected,target),target)
        fixture_write(part,part_raw)
    links=out/'link-fixtures';links.mkdir()
    def symlink_file_case(name,path):
        backup=links/(name+'.backup');path.rename(backup);path.symlink_to(backup)
        target=negative_root/name
        try:negative(name,lambda:m.materialize(fixture,selected,target),target)
        finally:path.unlink();backup.rename(path)
    symlink_file_case('symlink_part',part)
    source=fixture/'files'/m.CAPSULES[selected]['source_files'][0]
    source_raw=source.read_bytes()
    symlink_file_case('symlink_source_file',source)
    symlink_file_case('symlink_source_ancestor',fixture/'files'/selected)
    linked_root=links/'package';linked_root.symlink_to(fixture,target_is_directory=True)
    target=negative_root/'symlink_package_root'
    try:negative('symlink_package_root',lambda:m.materialize(linked_root,selected,target),target)
    finally:linked_root.unlink()
    parent=links/'parent';parent.symlink_to(negative_root,target_is_directory=True)
    target=parent/'symlink_output_parent'
    try:negative('symlink_output_parent',lambda:m.materialize(fixture,selected,target),target)
    finally:parent.unlink()
    target=negative_root/'existing_empty_output';target.mkdir()
    negative('existing_empty_output',lambda:m.materialize(fixture,selected,target),target,True)
    if list(target.iterdir()):raise AssertionError('existing output changed')
    target=negative_root/'partial_prior_directory';target.mkdir();fixture_write(target/'SENTINEL',b'keep')
    negative('partial_prior_directory',lambda:m.materialize(fixture,selected,target),target,True)
    if (target/'SENTINEL').read_bytes()!=b'keep':raise AssertionError('partial prior changed')
    target=negative_root/'existing_output_symlink';target.symlink_to(negative_root/'existing_empty_output',target_is_directory=True)
    try:negative('existing_output_symlink',lambda:m.materialize(fixture,selected,target),target,True)
    finally:target.unlink()
    writes=0
    def fail_second(path,raw):
        nonlocal writes
        writes+=1
        if writes==2:raise OSError('injected write failure')
        tracked_write(path,raw)
    m._write_file=fail_second;target=negative_root/'injected_write_failure'
    try:negative('injected_write_failure',lambda:m.materialize(fixture,selected,target),target,True)
    finally:m._write_file=tracked_write
    writes=0
    def drift_first(path,raw):
        nonlocal writes
        writes+=1
        if writes==1:raw=bytes([raw[0]^1])+raw[1:]
        tracked_write(path,raw)
    m._write_file=drift_first;target=negative_root/'written_output_drift'
    try:negative('written_output_drift',lambda:m.materialize(fixture,selected,target),target,True)
    finally:m._write_file=tracked_write
    fixture_write(source,bytes([source_raw[0]^1])+source_raw[1:]);target=negative_root/'corrupt_source_file'
    negative('corrupt_source_file',lambda:m.materialize(fixture,selected,target),target)
    fixture_write(source,source_raw)
    extra=fixture/'objects'/('f'*64+'.bin');fixture_write(extra,b'x');target=negative_root/'extra_stored_object'
    negative('extra_stored_object',lambda:m.materialize(fixture,selected,target),target)
    extra.unlink()
    # A source changed after validation must never become output. The consumer
    # retains validated bytes, and final output comparison precedes completion.
    changed_after_validation=False
    def alter_source_then_write(path,raw):
        nonlocal changed_after_validation
        if not changed_after_validation:
            changed_after_validation=True
            fixture_write(source,bytes([source_raw[0]^1])+source_raw[1:])
        tracked_write(path,raw)
    m._write_file=alter_source_then_write
    try:
        cache_out=out/'validated-byte-cache'
        result=m.materialize(fixture,selected,cache_out)
        if (cache_out/m.CAPSULES[selected]['source_files'][0]).read_bytes()!=source_raw:raise AssertionError('unchecked reread')
        positive.append(dict(result,case='retained_validated_bytes_after_source_drift'))
    finally:
        m._write_file=tracked_write;fixture_write(source,source_raw)
    if [c['name'] for c in cases]!=NEGATIVE_CASES or len(positive)!=7:raise AssertionError('exact fixture counts')
    forbidden={'numpy','policy_backend','fashion_research','torch','qualify','supervise','worker'}
    if any(k.split('.')[0] in forbidden for k in sys.modules):raise AssertionError('scientific module imported')
    capacity=json.loads((ROOT/'CAPACITY.json').read_bytes())
    paths=m.tree_paths(out)-{'tests.log'}
    actual_bytes=sum((out/p).stat().st_size for p in paths)
    if len(paths)!=capacity['retained_fixture_and_workspace_files'] or actual_bytes!=capacity['retained_fixture_and_workspace_bytes']:
        raise AssertionError('exact retained output accounting')
    report={'status':'PASS_PACKAGING_ONLY_NOT_SCIENTIFIC_OR_COMBINED_RUNTIME',
            'manifest_sha256':m.MANIFEST_SHA256,'positive_cases':positive,'negative_cases':cases,
            'positive_count':len(positive),'negative_count':len(cases),
            'retained_fixture_and_workspace_files':len(paths),'retained_fixture_and_workspace_bytes':actual_bytes,
            'CPU_prefix_seconds':time.process_time()-cpu,'wall_prefix_seconds':time.monotonic()-started,
            'self_rusage_prefix':list(resource.getrusage(resource.RUSAGE_SELF)),
            'I_O_and_hash_scope':counters,
            'counter_limits':'read counters cover successful materializer read_regular calls; hash counters cover materializer H; writes cover successful materializer _write_file and explicit fixture writes. Independent test reads, metadata, copy-source reads, failure partial writes, report/log and outer runner work are not included, not zero.',
            'compression':'none; raw stored ZIP concatenation only',
            'CPU_tail':'unknown_not_zero','models_executed':False,'candidate_runners_executed':False,'shared_lock_created':False}
    raw=m.canonical(report)
    if len(raw)>capacity['test_report_max_bytes']:raise AssertionError('report bytes')
    original_write(out/'TEST_REPORT.json',raw)
    print(json.dumps({'status':report['status'],'positives':len(positive),'negatives':len(cases),'retained_bytes_before_report':actual_bytes},sort_keys=True))


if __name__=='__main__':main()
