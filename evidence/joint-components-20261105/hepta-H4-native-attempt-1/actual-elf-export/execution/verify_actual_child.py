"""Verify the actual downloaded H4 child; do not claim missing H3 closure."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parent
CODE=ROOT.parent/'h4-content-reference-draft/archive_reference.py'
CODE_SHA='ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425'
COMPLETE_SHA='d3bda29c2ff27a18895e04ca672109298ca78bc9a9fd290d28a5d3db62930018'
ARCHIVE_SHA='47d3c5efa6b9aa4b2f97ef06a606f2931d8065f068311303f8d079c18a7bbaa5'
INDEX_SHA='3c4355fbd6293e631092c432557289ee770e34ae818c2ec68a590b7388d0041e'
PLAN_SHA='c917633ed8b22fa7a97455ea06c4a96fecc4a208375899bd3afededebf007619'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path,expected):
    raw=path.read_bytes()
    assert sha(raw)==expected,(str(path),'SHA differs')
    return raw


code_raw=read(CODE,CODE_SHA)
spec=importlib.util.spec_from_file_location('approved_ce96',CODE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
completion_raw=read(ROOT/'H4-export-completion.json',COMPLETE_SHA)
completion=json.loads(completion_raw)
assert completion['status']=='COMPLETE_WITH_REFERENCED_PARENT'
assert completion['standalone_archive'] is False
assert completion['archive_sha256']==ARCHIVE_SHA and completion['archive_bytes']==100964
assert completion['archive_index_sha256']==INDEX_SHA
assert completion['parent_identity']==m.PINNED_PARENT
archive=ROOT/'H4-actual-retained-image-references.tar.xz'
parts=m.verify_transport_parts(completion,ROOT/'H4-child-parts')
actual=m.read_verified_archive(str(archive),100964,ARCHIVE_SHA,INDEX_SHA)
index=actual['index']
assert index['phase']=='H4' and index['plan_sha256']==PLAN_SHA and index['exporter_sha256']==CODE_SHA
assert index['parent_identity']==m.PINNED_PARENT and index['standalone_archive'] is False
assert index['native_reexecution'] is False
assert len(index['files'])==11 and index['referenced_elf_bytes']==index['total_actual_elf_bytes']==1674575368
assert index['embedded_elf_bytes']==0 and len(actual['members'])==8
expected=dict(index['embedded_metadata_files'])
expected['export-index.json']={'bytes':len(actual['small']['export-index.json']),'sha256':INDEX_SHA}
m.verify_member_inventory(actual['members'],expected)
extracted=ROOT/'H4-child-extracted'
extracted.mkdir(mode=0o700)
originals={}
with tarfile.open(archive,'r:xz') as opened:
    for member in opened:
        assert member.isfile() and member.name in actual['members']
        raw=opened.extractfile(member).read()
        assert len(raw)==actual['members'][member.name]['bytes'] and sha(raw)==actual['members'][member.name]['sha256']
        target=extracted/member.name
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write(raw)
        originals[member.name]=raw
assert set(originals)==set(actual['members'])
plan_raw=read(ROOT/'H4-reference-export-plan.json',PLAN_SHA)
assert originals['export-plan.json']==plan_raw and originals['exporter.py']==code_raw
assert originals['owned-release-proof.json']==(ROOT.parent/'H4-owned-release-probe/proof.json').read_bytes()
assert originals['H4/referenced-H3-index.json']==(ROOT.parent/'h3-elf-export/H3-actual-export-index.json').read_bytes()
assert originals['H4/referenced-H3-completion.json']==(ROOT.parent/'h3-elf-export/H3-export-completion.json').read_bytes()
parent_index=json.loads(originals['H4/referenced-H3-index.json'])
parent_by_sha={row['sha256']:row for row in parent_index['files']}
plan,map_raw=m.validate_plan(plan_raw,{'by_hash':parent_by_sha})
assert originals['H4/original-source-map.json']==map_raw
assert index['original_run_outcome']==plan['original_run_outcome']==completion['original_run_outcome']
assert index['capture_limits']==plan['capture_limits']==completion['capture_limits']
for row,planned in zip(index['files'],plan['files']):
    assert all(row[key]==value for key,value in planned.items())
    assert row['representation']=='referenced-complete-image'
    assert row['first_read_metadata']==row['second_read_metadata']
    assert row['second_read_metadata']['bytes']==row['bytes']
    assert row['second_read_sha256']==row['sha256']
    assert row['other_aliases_reopened_by_this_export'] is False
assert sum(len(row['original_observations']) for row in index['files'])==597
assert len({alias for row in index['files'] for alias in row['aliases']})==32
parent_report=json.loads(originals['H4/parent-archive-verification.json'])
assert parent_report['archive_sha256']==m.PINNED_PARENT['archive_sha256']
assert parent_report['archive_bytes']==m.PINNED_PARENT['archive_bytes']
assert parent_report['index_sha256']==m.PINNED_PARENT['index_sha256']
assert parent_report['complete_parent_actually_rehashed'] is True
assert parent_report['no_parent_native_credit_transferred'] is True
assert len(parent_report['all_actual_members'])==16
parent_expected=dict(parent_index['embedded_metadata_files'])
parent_expected['export-index.json']={'bytes':m.PINNED_PARENT['index_bytes'],'sha256':m.PINNED_PARENT['index_sha256']}
for row in parent_index['files']:
    parent_expected[row['name']]={'bytes':row['bytes'],'sha256':row['sha256']}
# Compare the exported remote receipt to the exact parent inventory. These are
# preserved reported hashes, not actual local reads of missing parent bytes.
assert set(parent_expected)==set(parent_report['all_actual_members'])
for name,row in parent_expected.items():
    assert all(parent_report['all_actual_members'][name][key]==value for key,value in row.items())
with (ROOT/'H4-actual-export-index.json').open('xb') as stream:stream.write(originals['export-index.json'])
result={'schema':'H4-actual-child-local-byte-verification-v1',
    'status':'CHILD_ARCHIVE_AND_ORIGINAL_PART_VERIFIED_PARENT_DOWNLOAD_PENDING',
    'archive_bytes':100964,'archive_sha256':ARCHIVE_SHA,
    'actual_index_bytes':len(originals['export-index.json']),'actual_index_sha256':INDEX_SHA,
    'actual_part_verification':parts,'actual_members':actual['members'],
    'actual_uncompressed_member_bytes':sum(row['bytes'] for row in actual['members'].values()),
    'all_original_map_and_597_observations_preserved':True,'original_aliases':32,
    'recorded_H4_two_read_provenance_bound_to_each_original_image':True,
    'remote_parent_verification_receipt_bound':True,
    'actual_parent_whole_archive_locally_read_here':False,
    'complete_dependent_consumer_executed':False,
    'parent_and_all_parent_parts_still_required':m.PINNED_PARENT,
    'native_qualification_awarded':False,'originals_deleted_or_replaced':False,
    'pre_dispatch_plan_note':'The unchanged capture_limits.actual_remote_reads_pending field belongs to the original frozen pre-execution plan; actual execution fields and recorded two-read provenance describe the completed archive operation.'}
raw=m.encoded(result)
with (ROOT/'H4-child-local-verification.json').open('xb') as stream:stream.write(raw)
print(json.dumps({'status':result['status'],'archive_bytes':100964,'actual_index_bytes':result['actual_index_bytes'],
    'actual_index_sha256':INDEX_SHA,'members':len(actual['members']),'member_bytes':result['actual_uncompressed_member_bytes'],
    'verification_sha256':sha(raw)},sort_keys=True))
