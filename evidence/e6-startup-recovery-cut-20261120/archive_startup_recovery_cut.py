"""Freeze/pack/recover an explicit cloud cut. No host, network, Git or tests.

Content-addressed original bytes and old repository/archive reuse follow the
previous 22-file finite evidence package. No changing directory is enumerated.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import time

sys.dont_write_bytecode = True

ROOT = Path('/workspace/scratch/e9e051ab0825')
HERE = Path(__file__).resolve().parent
INTAKE = ROOT / 'metrics_integration/execution-readout-intake-diagnostic-6'
PREFIX = 'evidence/e6-startup-recovery-cut-20261120'
SOURCE = '1a9799686243c2be0ee393ba364e091029cfb944'
BASE = ROOT / 'metrics_integration/final_evidence_publication_work/FROZEN_557_FILES.json'
BASE_SHA = 'a740c2f0d1ccd1d7e78d506db436778d230cc984de1aefc4f86c71eae3367a44'
LEGACY_SHA = '80c53a02379f918057d94d6adbccc558a83c13f5bb114bbe6f68e9d575343b00'
LEGACY = HERE / 'legacy_archive_helpers.py'
if not LEGACY.exists():
    LEGACY = ROOT / 'e6_c_generation_cloud_archive_1/archive_finite_readback_v2.py'
spec = importlib.util.spec_from_file_location('legacy_archive_helpers', LEGACY)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
assert h.digest(LEGACY.read_bytes())['sha256'] == LEGACY_SHA
MAX_PART = 480000
INDEXES = [
    ('input-index-preparation-1/CURRENT_INPUT_INDEX.json', 'c63b33d3bfea4343a21c802ac3b4ac9d1f299296e14a54933656dbe12dddd306'),
    ('input-index-preparation-2/ADDITIONAL_INPUT_INDEX.json', 'fd424591a434aa8baaefe405bcd45f38e3176234fa58ef6f28dbf2310edfc27d'),
    ('input-index-preparation-3/ADDITIONAL_STATIC_INPUT_INDEX.json', 'bbcbbd6308cf8d14299b6b11a0d29b76120ba2c000b5c105b8f48c3a44dd82c5'),
    ('input-index-preparation-4/ADDITIONAL_START_INPUT_INDEX.json', '19344a992aec8818453e4352b44140e9de76991339f212e8105ab937149d6286'),
]
SUPPORT = [
    ('INPUT1_READBACK.json', 'input-index-preparation-1/LOCAL_PREPARATION_READBACK.json'),
    ('MATERIAL_ATTEMPT1_READOUT.json', 'input-index-preparation-1/MATERIAL_ATTEMPT1_READOUT.json'),
    ('INPUT1_SCOPE.json', 'input-index-preparation-1/SCOPE_AND_FUTURE_SLOTS.json'),
    ('INPUT2_READBACK.json', 'input-index-preparation-2/LOCAL_INCREMENT_READBACK.json'),
    ('RESUME1_SCOPE.json', 'input-index-preparation-2/RESUME1_AND_SUCCESSOR_SCOPE.json'),
    ('ADOPT_HELPER_SOURCE_REVIEW.json', 'input-index-preparation-2/ADOPT_HELPER_READ_REVIEW.json'),
    ('ROOT_PR_READOUT.json', 'input-index-preparation-2/ROOT_PR_REFRESH_READOUT.json'),
    ('STATIC_SUCCESSOR_RECEIPT.json', 'input-index-preparation-3/STATIC_SUCCESSOR_RECEIPT.json'),
    ('RUNNING_STATE_INTAKE.json', 'input-index-preparation-4/RUNNING_STATE_INTAKE.json'),
    ('prepare_input_index.py', 'prepare_input_index.py'),
    ('prepare_incremental_index.py', 'prepare_incremental_index.py'),
    ('prepare_resume2_static_intake.py', 'prepare_resume2_static_intake.py'),
    ('prepare_running_intake.py', 'prepare_running_intake.py'),
    ('INDEX_PREPARATION_FAILURE.json', 'input-index-preparation-2-incomplete-1/PREPARATION_FAILURE.json'),
    ('INDEX_PREPARATION_FAILED_CONTROLLER.py', 'input-index-preparation-2-incomplete-1/prepare_incremental_index.failed.py'),
]


def key(pin):
    return pin['bytes'], pin['sha256'], pin['git_blob']


def pin(path):
    data, identity = h.read(path)
    return data, {'local_path': str(path), **identity}


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(data)


def baseline():
    rows = h.load(BASE, {'sha256': BASE_SHA})
    assert len(rows) == 557 and len({x['path'] for x in rows}) == 557
    by_key = defaultdict(list)
    for row in rows:
        h.safe(row['path'])
        assert row['server_sha'] == row['git_blob']
        h.read(row['local_path'], row)
        by_key[key(row)].append(row)
    return rows, by_key


def repo_row(row):
    return {k: row[k] for k in ('path', 'bytes', 'sha256', 'git_blob')}


def old_archives(by_key):
    root = ROOT / 'e6_c_generation_cloud_archive_1/publication'
    descriptions = h.load(root / 'DEPENDENCIES.json')['archives']
    archives = {x['id']: x for x in descriptions}
    parts = h.load(root / 'archive-parts.json')
    part_index_pin = h.digest((root / 'archive-parts.json').read_bytes())
    assert key(part_index_pin) in by_key
    translated = []
    for row in parts['parts']:
        body, actual = h.read(root / row['path'], row)
        assert key(actual) in by_key
        translated.append({'name': row['path'], **actual,
                           'repository_file': repo_row(by_key[key(actual)][0])})
    archives['1a979-finite'] = {
        'id': '1a979-finite', **{k: parts[k] for k in ('bytes','sha256','git_blob')},
        'part_index_repository_file': repo_row(by_key[key(part_index_pin)][0]),
        'parts': translated,
    }
    candidates = defaultdict(list)
    members = h.load(root / 'ARCHIVE_MEMBERS.json')['members']
    for row in members:
        candidates[row['sha256']].append({'archive_id':'1a979-finite','member':row['path'],
                                          **{k:row[k] for k in ('bytes','sha256','git_blob')}})
    # These exact old members were physically restored in the previous package.
    # No new search over unknown archive paths or host directories occurs.
    known = h.load(root / 'DEPENDENCIES.json')['selected_existing_archive_members_actual_readback']
    for row in known:
        candidates[row['sha256']].append({k:row[k] for k in ('archive_id','member','bytes','sha256')})
    return archives, candidates


def repository_resolver(rows=None, repository_root=None):
    by_path = {row['path']: row for row in (rows or [])}
    def get(reference):
        h.safe(reference['path'])
        if repository_root is not None:
            path = Path(repository_root) / reference['path']
        else:
            saved = by_path[reference['path']]
            assert key(saved) == key(reference)
            path = Path(saved['local_path'])
        return h.read(path, reference)[0]
    return get


def reconstruct_old_archive(info, get_repo):
    chunks = []
    for part in info['parts']:
        data = get_repo(part['repository_file'])
        assert h.digest(data) == {k:part[k] for k in ('bytes','sha256','git_blob')}
        chunks.append(data)
    body = b''.join(chunks)
    assert h.digest(body) == {k:info[k] for k in ('bytes','sha256','git_blob')}
    return body


def selected_old_members(dependencies, required, get_repo):
    result = {}
    for info in dependencies['archives']:
        wanted = required.get(info['id'], {})
        if not wanted:
            continue
        body = reconstruct_old_archive(info, get_repo)
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(body), mode='r|xz') as archive:
            for member in archive:
                h.safe(member.name)
                if member.name not in wanted:
                    continue
                assert member.isfile() and member.name not in seen
                data = archive.extractfile(member).read()
                expected = wanted[member.name]
                assert h.digest(data) == {k:expected[k] for k in ('bytes','sha256','git_blob')}
                result[(info['id'],member.name)] = data
                seen.add(member.name)
        assert seen == set(wanted)
    assert len(result) == sum(len(x) for x in required.values())
    return result


def prepare():
    out = HERE / 'frozen-cut-1'
    out.mkdir(exist_ok=False)
    existing, by_key = baseline()
    archives, archived = old_archives(by_key)
    files = []
    metadata = {}
    support_map = []
    for number, (name, expected_sha) in enumerate(INDEXES, 1):
        data, identity = h.read(INTAKE / name, {'sha256': expected_sha})
        source = json.loads(data)
        metadata[f'INPUT_INDEX_{number}.json'] = data
        support_map.append({'metadata_name':f'INPUT_INDEX_{number}.json',
                            'workspace_path':str((INTAKE/name).relative_to(ROOT)), **identity})
        for original in source['files']:
            path = ROOT / h.safe(original['workspace_path'])
            _, actual = h.read(path, original)
            files.append({'workspace_path':original['workspace_path'],'local_path':str(path),
                          **actual,'source_index':number,
                          'roles':original.get('roles',[]),'groups':original.get('groups',[])})
    assert len(files) == 572 and len({x['workspace_path'] for x in files}) == 572
    for name, relative in SUPPORT:
        data, identity = h.read(INTAKE / relative)
        metadata[name] = data
        support_map.append({'metadata_name':name,'workspace_path':str((INTAKE/relative).relative_to(ROOT)), **identity})
    needed = defaultdict(dict)
    used_repo = {}
    for row in files:
        if key(row) in by_key:
            ref = sorted(by_key[key(row)], key=lambda x:x['path'])[0]
            row['storage'] = {'kind':'existing_repository_file','repository_file':repo_row(ref)}
            used_repo[ref['path']] = repo_row(ref)
        else:
            possibilities = [x for x in archived.get(row['sha256'],[]) if x['bytes'] == row['bytes']]
            if possibilities:
                chosen = sorted(possibilities,key=lambda x:(x['archive_id'],x['member']))[0]
                row['storage'] = {'kind':'existing_archive_member',**chosen}
                needed[chosen['archive_id']][chosen['member']] = row
            else:
                row['storage'] = {'kind':'new_archive_object','member':'objects/'+row['sha256']+'.bin'}
    dependencies = {'baseline_manifest':{'workspace_path':str(BASE.relative_to(ROOT)),**h.digest(BASE.read_bytes())},
                    'archives':[archives[k] for k in sorted(needed)],
                    'direct_repository_files':sorted(used_repo.values(),key=lambda x:x['path'])}
    selected_old_members(dependencies,needed,repository_resolver(existing))
    counts = dict(Counter(row['storage']['kind'] for row in files))
    unique = {row['sha256']:row for row in files if row['storage']['kind']=='new_archive_object'}
    scope = {
        'status':'FINITE_STARTUP_RECOVERY_CUT_NOT_NEW_RUNTIME_QUALIFICATION',
        'base_source':SOURCE,'source_tree':'931a344b1ea3e2ddf45e917ea4b3ae37c504ed05',
        'source_inventory':'1c7782e85a9b79fad6e82c0c5022964299451629d2cb96e55b442f96f0059a7a',
        'source_and_policy_candidates_not_deployed_by_this_pack':True,
        'original_NoUpdate13':'FAIL','new_C_drain_reached_by_NoUpdate13':False,
        'material_attempt1':'FAIL;98.305439721s;172GET/168complete;source_after=null;0retry',
        'resume1':'c9/de887 static blocked and never launched; retained with peer',
        'resume2':'e4ec/c94 static fixes and exact start receipt included; no terminal RESULT in this cut',
        'latest_included_owner':'dpty-1ff0aada969cb9ec4ef726e177ebab6aa31af70f59c70ed2ce1676e68cd0814c',
        'latest_included_observation':'saved OWNER_START: running, output_complete=false, reused=false',
        'current_live_owner_state_not_requeried':True,
        'material_success':None,'actual_fmt':None,'actual_compile':None,'actual_new_native':None,
        'later_results_separate_addenda':True,'ordinary_Adopt_runs':0,
        'conditional_Adopt74_vs_hard64_unchanged':True,
        'uploaded_repository_baseline_paths':557,'logical_inputs_this_cut':572,
        'not_full_host_or_cache_or_business_physical_closure':True,
        'synthetic_fixture_links':'literal target/stat only in input indexes; targets never opened as links',
        'mutable_formal_reports_not_inputs':True,'host_network_model_native_git_actions':0,
    }
    inputs = {'schema':'hepta.e6.startup-recovery-finite-inputs.v1','files':sorted(files,key=lambda x:x['workspace_path']),
              'logical_saved_files':len(files),'logical_bytes':sum(x['bytes'] for x in files),
              'storage_counts':counts,'new_unique_objects':len(unique),'new_unique_bytes':sum(x['bytes'] for x in unique.values())}
    metadata.update({'INPUT_MANIFEST.json':h.encoded(inputs),'DEPENDENCIES.json':h.encoded(dependencies),
                     'EXPLICIT_SCOPE.json':h.encoded(scope),'SUPPORT_SOURCE_MAP.json':h.encoded({'files':support_map})})
    for name, data in metadata.items():
        write_new(out/name,data)
    freeze = {'status':'FROZEN_EXPLICIT_CUT_BEFORE_PACK','source':SOURCE,
              'files':[{'path':name,**h.digest(data)} for name,data in sorted(metadata.items())],
              'controller':{'path':str(Path(__file__)),**h.digest(Path(__file__).read_bytes())},
              'legacy_helper':{'path':str(LEGACY),**h.digest(LEGACY.read_bytes())},
              'baseline':{'path':str(BASE),**h.digest(BASE.read_bytes())},
              'no_directory_scan_or_new_host_read':True}
    write_new(out/'FREEZE.json',h.encoded(freeze))
    print(json.dumps({'freeze':str(out/'FREEZE.json'),**h.digest((out/'FREEZE.json').read_bytes()),
                      'inputs':572,'storage_counts':counts,'new_objects':len(unique),'new_bytes':inputs['new_unique_bytes']}))


def metadata_bytes(publication,name):
    storage = h.load(publication/'METADATA_STORAGE.json')['files']
    row = next(x for x in storage if x['name']==name)
    if row['kind']=='whole':
        data = h.read(publication/h.safe(row['name']),row)[0]
    else:
        desc = h.load(publication/h.safe(row['index']))
        parts=[]; offset=0
        for part in desc['parts']:
            assert part['offset']==offset and part['bytes']<=MAX_PART
            body=h.read(publication/h.safe(part['path']),part)[0]
            parts.append(body);offset+=len(body)
        data=b''.join(parts)
        assert h.digest(data)=={k:desc[k] for k in ('bytes','sha256','git_blob')}
    assert h.digest(data)=={k:row[k] for k in ('bytes','sha256','git_blob')}
    return data


def restore(publication,repository_map,output,repository_root=None):
    publication=Path(publication);output=Path(output)
    output.mkdir(exist_ok=False)
    baseline_rows=h.load(repository_map) if repository_map else []
    get_repo=repository_resolver(baseline_rows,repository_root)
    index=h.load(publication/'archive-parts.json')
    pieces=[];offset=0
    for part in index['parts']:
        assert part['offset']==offset and 0<part['bytes']<=MAX_PART
        data=h.read(publication/h.safe(part['path']),part)[0]
        pieces.append(data);offset+=len(data)
    archive_bytes=b''.join(pieces)
    assert h.digest(archive_bytes)=={k:index[k] for k in ('bytes','sha256','git_blob')}
    members=json.loads(metadata_bytes(publication,'ARCHIVE_MEMBERS.json'))['members']
    expected={x['path']:x for x in members}
    assert len(expected)==len(members)
    seen=set(); actual_members={}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes),mode='r|xz') as archive:
        for member in archive:
            h.safe(member.name)
            assert member.isfile() and member.name not in seen and member.name in expected
            assert member.size==expected[member.name]['bytes']
            data=archive.extractfile(member).read()
            assert h.digest(data)=={k:expected[member.name][k] for k in ('bytes','sha256','git_blob')}
            actual_members[member.name]=data;seen.add(member.name)
    assert seen==set(expected)
    inputs=json.loads(metadata_bytes(publication,'INPUT_MANIFEST.json'))
    dependencies=json.loads(metadata_bytes(publication,'DEPENDENCIES.json'))
    assert actual_members['metadata/INPUT_MANIFEST.json']==metadata_bytes(publication,'INPUT_MANIFEST.json')
    assert actual_members['metadata/DEPENDENCIES.json']==metadata_bytes(publication,'DEPENDENCIES.json')
    storage=h.load(publication/'METADATA_STORAGE.json')['files']
    for item in storage:
        data=metadata_bytes(publication,item['name'])
        member='metadata/'+item['name']
        if member in actual_members: assert actual_members[member]==data
    needed=defaultdict(dict)
    for row in inputs['files']:
        s=row['storage']
        if s['kind']=='existing_archive_member':needed[s['archive_id']][s['member']]=row
    old_members=selected_old_members(dependencies,needed,get_repo)
    readback=[]
    for row in inputs['files']:
        s=row['storage'];kind=s['kind']
        if kind=='new_archive_object':data=actual_members[s['member']]
        elif kind=='existing_repository_file':data=get_repo(s['repository_file'])
        elif kind=='existing_archive_member':data=old_members[(s['archive_id'],s['member'])]
        else:raise ValueError(kind)
        assert h.digest(data)=={k:row[k] for k in ('bytes','sha256','git_blob')}
        target=output/'originals'/h.safe(row['workspace_path'])
        write_new(target,data)
        assert h.read(target,row)[0]==data
        readback.append({'workspace_path':row['workspace_path'],**h.digest(data),'storage_kind':kind})
    result={'status':'ALL_LOGICAL_ORIGINALS_RESTORED_EXACTLY','logical_files':len(readback),
            'logical_bytes':sum(x['bytes'] for x in readback),'archive_members':len(seen),
            'archive':h.digest(archive_bytes),'files':readback,'no_host_network_git_native_model_actions':True}
    write_new(output/'RESTORE_READBACK.json',h.encoded(result))
    return result


def pack():
    freeze_dir=HERE/'frozen-cut-1';freeze=h.load(freeze_dir/'FREEZE.json')
    h.read(__file__,freeze['controller']);h.read(LEGACY,freeze['legacy_helper'])
    for row in freeze['files']:h.read(freeze_dir/row['path'],row)
    inputs=h.load(freeze_dir/'INPUT_MANIFEST.json')
    assert len(inputs['files'])==572
    out=HERE/'pack-1';publication=HERE/'publication'
    out.mkdir(exist_ok=False);publication.mkdir(exist_ok=False)
    started=time.monotonic();complete=False
    try:
        existing,_=baseline()
        unique={}
        for row in inputs['files']:
            h.read(row['local_path'],row)
            if row['storage']['kind']=='new_archive_object':
                old=unique.setdefault(row['sha256'],row)
                assert key(old)==key(row)
        metadata={r['path']:h.read(freeze_dir/r['path'],r)[0] for r in freeze['files']}
        metadata['FREEZE.json']=(freeze_dir/'FREEZE.json').read_bytes()
        metadata['archive_startup_recovery_cut.py']=h.read(__file__,freeze['controller'])[0]
        metadata['legacy_archive_helpers.py']=h.read(LEGACY,freeze['legacy_helper'])[0]
        tar_path=out/'startup-recovery-cut-originals.tar.xz'
        expected={}
        with tarfile.open(tar_path,'w:xz',format=tarfile.USTAR_FORMAT,preset=6) as archive:
            for name,data in sorted(metadata.items()):
                member='metadata/'+name;h.add_tar(archive,member,data);expected[member]=h.digest(data)
            for sha,row in sorted(unique.items()):
                data=h.read(row['local_path'],row)[0]
                member=row['storage']['member'];h.add_tar(archive,member,data);expected[member]=h.digest(data)
        data=tar_path.read_bytes();archive_pin=h.digest(data)
        parts=[];offset=0
        while offset<len(data):
            end=min(offset+MAX_PART,len(data))
            if end<len(data):
                nul=data.rfind(b'\0',offset+1,end+1)
                if nul>offset:end=nul
            assert offset<end<=offset+MAX_PART
            body=data[offset:end]
            assert b'\0' in body[:1024]
            name=f'startup-recovery-cut-originals.tar.xz.part-{len(parts):03d}'
            write_new(publication/name,body)
            parts.append({'path':name,'offset':offset,**h.digest(body),
                          'first_NUL_offset':body.find(b'\0'),'first1024_contains_NUL':True})
            offset=end
        assert b''.join(h.read(publication/p['path'],p)[0] for p in parts)==data
        part_index={'archive_name':tar_path.name,**archive_pin,'max_part_bytes':MAX_PART,
                    'parts':parts,'exact_reassembly_verified':True,
                    'split_policy':'Existing NUL boundary only; original bytes never padded or changed.'}
        write_new(publication/'archive-parts.json',h.encoded(part_index))
        metadata['ARCHIVE_MEMBERS.json']=h.encoded({'archive':archive_pin,
            'members':[{'path':name,**pin} for name,pin in sorted(expected.items())],
            'member_count':len(expected)})
        stores=[h.write_publication_value(publication,name,body) for name,body in sorted(metadata.items())]
        write_new(publication/'METADATA_STORAGE.json',h.encoded({'files':stores}))
        for item in stores:
            assert metadata_bytes(publication,item['name'])==metadata[item['name']]
        restored=restore(publication,BASE,out/'independent-restoration-1')
        assert restored['logical_files']==572 and restored['archive_members']==len(expected)
        # Every recovered byte is independently compared to its original, not
        # just to a stored digest or a synthetic copy of the manifest.
        for row in inputs['files']:
            original=h.read(row['local_path'],row)[0]
            recovered=h.read(out/'independent-restoration-1/originals'/row['workspace_path'],row)[0]
            assert original==recovered
        readback_data=h.encoded(restored)
        restore_store=h.write_publication_value(publication,'RESTORE_READBACK.json',readback_data)
        stores.append(restore_store)
        # Replace only this newly generated storage descriptor before success;
        # it was never an input or a published/frozen old artifact.
        (publication/'METADATA_STORAGE.json').write_bytes(h.encoded({'files':stores}))
        assert metadata_bytes(publication,'RESTORE_READBACK.json')==readback_data
        readme=(
            '# Startup recovery evidence cut\n\n'
            'This package retains 572 explicitly indexed original files, their complete bytes, '
            'and separately named cloud preparation metadata. It performs no host, network, '
            'Git, model, compilation or native test action.\n\n'
            'The first material attempt failed; its complete actual receipts and partial-cost metadata remain. '
            'Resume1 is a blocked, never-launched static revision. Resume2 has reviewed changes and an actual '
            'saved owner-start record showing running, not a terminal successful material result. '
            'This is a historical evidence cut, not a fresh query of the current process. '
            'Later material/fmt/compile/native results require separate addenda. Original NoUpdate13 remains FAIL.\n\n'
            'The original source is 1a9799686243c2be0ee393ba364e091029cfb944. The new startup '
            'product/QA candidates and format/compile templates in the inputs have no runtime qualification '
            'from this archive. Conditional Adopt74/hard64 is unchanged.\n\n'
            'Complete raw RPC fields are preserved as content-addressed original bytes, without redaction '
            'or lossy serialization. Old uploaded557 repository files and exact old archive members are '
            'reused by byte identity. A storage reuse never transfers experimental qualification. '
            'No whole-host/cache/business provenance closure is asserted. Synthetic fixture links are '
            'retained as literal-target metadata in the input indexes; archive/restoration creates regular files only.\n\n'
            'All publication files are at most480000 bytes. Large metadata is reassembled from original-byte '
            'parts using METADATA_STORAGE.json. Archive pieces are split only at existing byte boundaries; '
            'the full archive is retained in cloud and is not duplicated as a large Git blob.\n\n'
            'Replay: python archive_startup_recovery_cut.py restore --publication-dir THIS_DIRECTORY '
            '--repository-root CHECKOUT_WITH_OLD_557_FILES --output NEW_EMPTY_DIRECTORY\n'
        ).encode()
        write_new(publication/'README.md',readme)
        # Recheck every frozen source/metadata and old baseline before any final
        # success receipt. Publication path/size checks also precede that receipt.
        baseline()
        for row in freeze['files']:h.read(freeze_dir/row['path'],row)
        h.read(__file__,freeze['controller']);h.read(LEGACY,freeze['legacy_helper'])
        base_paths={row['path'] for row in existing}
        actual_files=[]
        for path in sorted(publication.rglob('*')):
            if path.is_file():
                assert not path.is_symlink()
                rel=h.safe(str(path.relative_to(publication)))
                body,pin=h.read(path);assert len(body)<=MAX_PART
                repo_path=PREFIX+'/'+rel;assert repo_path not in base_paths
                actual_files.append({'local_path':str(path),'path':repo_path,**pin,'mode':'100644'})
        result={'status':'CLOUD_EVIDENCE_PACKAGE_AND_ALL_ORIGINAL_RESTORATION_VERIFIED',
                'package_successful':True,'logical_originals':572,'archive':archive_pin,
                'archive_members':len(expected),'archive_parts':len(parts),
                'storage_counts':inputs['storage_counts'],
                'full_raw_RPC_bytes_preserved':True,'all_originals_byte_equal_after_restore':True,
                'source':SOURCE,'NoUpdate13':'FAIL',
                'latest_material_observation':'saved resume2 OWNER_START running; no terminal RESULT included',
                'material_success':None,'fmt_compile_native_qualification':False,
                'host_network_git_native_model_test_actions':0,
                'preparation_and_pack_new_git_refs':0,'max_publication_file_bytes':MAX_PART,
                'wall_seconds_before_final_receipt':time.monotonic()-started}
        result_data=h.encoded(result);assert len(result_data)<=MAX_PART
        result_row={'local_path':str(publication/'RESULT.json'),'path':PREFIX+'/RESULT.json',
                    **h.digest(result_data),'mode':'100644'}
        expected_rows=actual_files+[result_row]
        manifest_data=h.encoded({'files':expected_rows,'result_written_last':True,
                                'this_manifest_self_excluded':True})
        assert len(manifest_data)<=MAX_PART
        write_new(publication/'FILE_MANIFEST.json',manifest_data)
        expected_rows.append({'local_path':str(publication/'FILE_MANIFEST.json'),
                              'path':PREFIX+'/FILE_MANIFEST.json',**h.digest(manifest_data),'mode':'100644'})
        assert all(row['bytes']<=MAX_PART and row['path'] not in base_paths for row in expected_rows)
        assert len({r['path'] for r in expected_rows})==len(expected_rows)
        for row in expected_rows:
            if row!=result_row:h.read(row['local_path'],row)
        public_manifest={'status':'PREPARED_FOR_ROOT_PUBLICATION_NO_GIT_ACTION',
                         'prefix':PREFIX,'files':sorted(expected_rows,key=lambda x:x['path']),
                         'file_count':len(expected_rows),'total_bytes':sum(r['bytes'] for r in expected_rows),
                         'max_file_bytes':max(r['bytes'] for r in expected_rows),
                         'baseline_uploaded557_sha256':BASE_SHA,'archive':archive_pin,
                         'logical_originals':572,'material_success':None,'git_actions':0}
        write_new(HERE/'PUBLICATION_FILES.json',h.encoded(public_manifest))
        # Verify receipt bytes before a single create-only link exposes the
        # final success marker. There are no pending validation writes afterward.
        pending=out/'VERIFIED_FINAL_RESULT.pending.json'
        write_new(pending,result_data);assert h.read(pending,result_row)[0]==result_data
        os.link(pending,publication/'RESULT.json')
        complete=True
        print(json.dumps({'result':result,'publication_manifest':str(HERE/'PUBLICATION_FILES.json')}))
    except BaseException as error:
        if not complete:
            write_new(out/'FAILURE.json',h.encoded({'status':'INCOMPLETE_CLOUD_PACK',
                'package_successful':False,'error_class':type(error).__name__,'error':str(error),
                'wall_seconds':time.monotonic()-started,'host_network_git_native_model_actions':0}))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','pack','restore'])
    parser.add_argument('--publication-dir')
    parser.add_argument('--repository-map')
    parser.add_argument('--repository-root')
    parser.add_argument('--output')
    args=parser.parse_args()
    if args.action=='prepare':prepare()
    elif args.action=='pack':pack()
    else:
        r=restore(Path(args.publication_dir),args.repository_map,args.output,args.repository_root)
        print(json.dumps({k:v for k,v in r.items() if k!='files'}))
