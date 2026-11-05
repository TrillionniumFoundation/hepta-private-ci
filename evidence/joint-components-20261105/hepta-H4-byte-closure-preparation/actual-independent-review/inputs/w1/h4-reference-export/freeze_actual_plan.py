"""Cloud-only binding of already captured H4 records to the reviewed protocol."""
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent.parent
CODE = ROOT.parent / 'h4-content-reference-draft/archive_reference.py'
CODE_SHA = 'ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425'
MAP = WORK / 'model_storage/h4-capture-repair/native/joint-h4-native-attempt-1/h4-actual-image-inventory.json'
MAP_SHA = 'a1e42612d6a89337144b00335da2fa690dc7f503b46532ff795f0c92198bdd9c'
PARENT_INDEX = ROOT.parent / 'h3-elf-export/H3-actual-export-index.json'
PARENT_COMPLETION = ROOT.parent / 'h3-elf-export/H3-export-completion.json'
RELEASE = ROOT.parent / 'H4-owned-release-probe/proof.json'
RELEASE_SHA = 'dcdd164eb680465a440bf9dc4e11ab68c5598d8cb86a4d99320784d0a5b68107'
SOURCE_COMMIT = '6db78eca53a5acdda0d96873d3f4cd65863426f0'
SOURCE_TREE = 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
JOB = '1a1ade2970f-fc05-5b5c'
REMOTE_ROOT = '/home/qian-qi/work/hepta-pq-effect-v4-20261105-93bfcf/evidence/joint-h4-native-attempt-1'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned(path, expected):
    raw = path.read_bytes()
    if sha(raw) != expected:
        raise ValueError('frozen cloud input differs: ' + str(path))
    return raw


def fresh(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path':str(path), 'bytes':len(raw), 'sha256':sha(raw)}


def encoded(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


code = pinned(CODE, CODE_SHA)
spec = importlib.util.spec_from_file_location('h4_reference_approved', CODE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
mapping_raw = pinned(MAP, MAP_SHA)
assert len(mapping_raw) == 525002 <= module.MAX_MAP_BYTES
mapping = json.loads(mapping_raw)
assert (mapping['source_commit'],mapping['source_tree']) == (SOURCE_COMMIT,SOURCE_TREE)
assert mapping['job_id'] == JOB and mapping['terminal_unix_ms'] == 1793919910435
assert mapping['status'] == 'PASSED_ONE_SOURCE_DESKTOP_GATES_ONLY'
assert mapping['partial_artifacts'] == []
assert mapping['actual_fd_records'] == 301 and mapping['actual_live_records'] == 294
assert mapping['complete_retained_alias_count'] == 32
assert sum(len(image['observations']) for image in mapping['images']) == 597

parent_index_raw = pinned(PARENT_INDEX, module.PINNED_PARENT['index_sha256'])
assert len(parent_index_raw) == module.PINNED_PARENT['index_bytes']
parent_index = json.loads(parent_index_raw)
parent_completion_raw = pinned(PARENT_COMPLETION, module.PINNED_PARENT['completion_sha256'])
parent_completion = json.loads(parent_completion_raw)
assert parent_completion['status'] == 'COMPLETE'
assert parent_completion['archive_bytes'] == module.PINNED_PARENT['archive_bytes']
assert parent_completion['archive_sha256'] == module.PINNED_PARENT['archive_sha256']
parent_by_sha = {row['sha256']:row for row in parent_index['files']}
assert len(parent_by_sha) == 11
release_raw = pinned(RELEASE, RELEASE_SHA)
release = json.loads(release_raw)
assert release['job_id'] == JOB and release['owned_processes_clear'] is True
assert release['failures'] == [] and release['processes_killed'] is False
assert release['original_authoritative_terminal'] == {
    'at_unix_ms':1793919910435, 'exit_code':0, 'state':'succeeded', 'timed_out':False}

files = []
for image in mapping['images']:
    row = {'name':'H4/elf/'+image['sha256']+'.elf', 'sha256':image['sha256'],
        'bytes':image['bytes'], 'source_path':image['retained_aliases'][0],
        'aliases':image['retained_aliases'], 'original_actual_paths':image['actual_paths'],
        'original_observations':image['observations']}
    parent = parent_by_sha.get(image['sha256'])
    if parent is not None:
        assert parent['bytes'] == image['bytes']
        row['representation'] = 'referenced-complete-image'
        row['parent_reference'] = {
            'archive_sha256':module.PINNED_PARENT['archive_sha256'],
            'archive_bytes':module.PINNED_PARENT['archive_bytes'],
            'index_sha256':module.PINNED_PARENT['index_sha256'],
            'member':parent['name'], 'bytes':image['bytes'], 'sha256':image['sha256']}
    else:
        row['representation'] = 'embedded-complete-image'
    files.append(row)
total = sum(row['bytes'] for row in files)
embedded = sum(row['bytes'] for row in files if row['representation']=='embedded-complete-image')
assert total == 1674575368 == mapping['complete_image_unique_bytes']
outcome = {key:value for key,value in mapping.items() if key not in ('images','source_commit','source_tree')}
outcome.update(result=mapping['status'],native_job_id=JOB)
plan = {
    'schema':'hepta-H4-reference-archive-plan-v1', 'phase':'H4',
    'native_reexecution':False, 'part_bytes':module.PART_BYTES,
    'transport_budget_seconds':900, 'source_commit':SOURCE_COMMIT,'source_tree':SOURCE_TREE,
    'source_root':REMOTE_ROOT,
    'source_map':{'bytes':len(mapping_raw),'sha256':MAP_SHA,'data_base64':base64.b64encode(mapping_raw).decode()},
    'files':files,
    'parent':{**module.PINNED_PARENT,
        'archive_path':parent_completion['archive_path'],
        'completion_path':'/home/qian-qi/work/hepta-h3-actual-elf-export-20261105-93bfc-01/completion.json'},
    'total_actual_elf_bytes':total,'embedded_elf_bytes':embedded,'referenced_elf_bytes':total-embedded,
    'max_archive_bytes':embedded+64*module.BLOCK,
    'archive_name':'H4-actual-retained-image-references.tar.xz',
    'output_directory':'/home/qian-qi/work/hepta-h4-actual-reference-export-20261105-93bfc-01',
    'release_prerequisite':{'job_id':JOB,
        'path':'/home/qian-qi/work/hepta-joint-h4-owned-release-20261105-93bfc-01.json',
        'sha256':RELEASE_SHA},
    'original_run_outcome':outcome,
    'capture_limits':{
        'selected_complete_images':len(files), 'original_retained_aliases':32,
        'original_observations':597, 'selection_rule':'first explicit actual retained alias of each inventory image',
        'actual_remote_reads_pending':True,
        'only_selected_11_paths_will_be_reopened':True,
        'other_21_alias_paths_are_preserved_as_observations_not_rehashed':True,
        'ordinary_second_generation':'One held actual file object reused, not a second full image copy or second full SHA computation.',
        'auxiliary_live_child':'Original auxiliary observation is preserved; it adds no passed-case credit.',
        'partial_scope':mapping['partial_artifact_scope'],
        'source_and_case_attribution':'Only this H4 inventory and original per-gate FD/live/process records; no H3 execution credit transferred.',
        'parent_dependency':'One exact complete H3 archive; no transitive references; both packages and all parts/members must be verified by the final consumer.',
        'completion_status_required':'COMPLETE_WITH_REFERENCED_PARENT',
        'publication_failure':'Failure grants no completion credit and may leave the published archive or some parts; cross-file publication is not atomic.',
        'qualification_scope':'Byte preservation of recorded complete images only; no hosted matrix, WAN, new learning, release qualification, or capture repair.'
    }
}
raw=(json.dumps(plan,sort_keys=True,separators=(',',':'))+'\n').encode()
assert len(raw) <= module.MAX_PLAN_BYTES
checked, checked_map = module.validate_plan(raw, {'by_hash':parent_by_sha})
assert checked == plan and checked_map == mapping_raw
plan_record=fresh(ROOT/'H4-reference-export-plan.json',raw)
verification={
    'schema':'H4-actual-plan-cloud-binding-verification-v1',
    'status':'METADATA_BOUND_REMOTE_BYTE_READS_PENDING', 'remote_calls':0,
    'original_inventory':{'path':str(MAP),'bytes':len(mapping_raw),'sha256':MAP_SHA},
    'actual_H4_release':{'path':str(RELEASE),'bytes':len(release_raw),'sha256':RELEASE_SHA},
    'approved_exporter':{'path':str(CODE),'bytes':len(code),'sha256':CODE_SHA},
    'parent_actual_index':{'path':str(PARENT_INDEX),'bytes':len(parent_index_raw),'sha256':sha(parent_index_raw)},
    'parent_actual_completion':{'path':str(PARENT_COMPLETION),'bytes':len(parent_completion_raw),'sha256':sha(parent_completion_raw)},
    'plan':plan_record, 'unique_complete_images':len(files),'original_aliases':32,'original_observations':597,
    'recorded_parent_hash_overlap':sum(row['representation']=='referenced-complete-image' for row in files),
    'referenced_elf_bytes':total-embedded,'embedded_elf_bytes':embedded,
    'all_original_map_bytes_preserved':True,'all_original_observations_preserved':True,
    'all_original_outcome_fields_preserved':True,
    'cloud_validate_plan_with_exact_actual_index_passed':True,
    'actual_parent_whole_archive_reverified_here':False,
    'actual_H4_retained_bytes_read_here':False,
    'launch_authorized':False,'launch_dispatched':False,
    'bulk_transfers':'PAUSED0', 'requested_outer_seconds':900
}
fresh(ROOT/'H4-plan-cloud-binding-verification.json',encoded(verification))
print(json.dumps(verification,sort_keys=True,indent=2))
