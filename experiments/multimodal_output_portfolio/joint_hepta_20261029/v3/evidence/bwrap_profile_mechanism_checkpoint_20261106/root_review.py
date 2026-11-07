"""Verify source checkpoint custody without executing archived probe code."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PACKAGE = ROOT / 'round3_core_ci/bwrap28_evidence_checkpoint_v2'
DESTINATION = ROOT / 'round3_root_restore_bwrap28_0115'


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(raw):
    return {'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


publication = ROOT / 'round3_core_ci/BWRAP28_CHECKPOINT_PUBLICATION_MANIFEST_FINAL.json'
manifest = json.loads(publication.read_bytes())
require(len(manifest['files']) == 12, 'publication file count')
for row in manifest['files']:
    p = Path(row['local_path'])
    actual = identity(p.read_bytes())
    require(actual == {'bytes':row['bytes'], 'sha256':row['sha256'], 'git_blob':row['git_blob']}, 'publication identity')
    require(row['mode'] == '100644' and stat.S_IMODE(p.stat().st_mode) == 0o644, 'publication mode')
index_raw = (PACKAGE/'INDEX.json').read_bytes()
index = json.loads(index_raw)
require(hashlib.sha256(index_raw).hexdigest() == manifest['index_sha256'] == 'ed73e4263921ef02e759b0bc96134d81708a538fbef46bfd7509edeb8efea4ff', 'fixed index')
reader = (PACKAGE/'restore.py').read_bytes()
template = (ROOT/'round3_native/read_authority_checkpoint_inputs/reviewed_restore.py').read_bytes()
old_manifest = json.loads((ROOT/'round3_native/SDK_PRODUCT_CHECKPOINT_PUBLICATION_MANIFEST.json').read_bytes())
old = next(x for x in old_manifest['files'] if x['path'].endswith('/restore.py'))
remote = json.loads((OUT/'READER_SOURCE_API.json').read_bytes())['source'][old['path']]
require(identity(template) == {'bytes':old['bytes'], 'sha256':old['sha256'], 'git_blob':old['git_blob_sha']}, 'original template bytes')
require(remote['sha'] == old['git_blob_sha'] and remote['mode'] == old['mode'] and remote['size'] == old['bytes'], 'published template leaf')
pattern = rb'EXPECTED_INDEX_SHA256 = \(\n    "([a-f0-9]{64})"\n\)'
a, b = re.findall(pattern, template), re.findall(pattern, reader)
require(len(a) == len(b) == 1 and b[0].decode() == manifest['index_sha256'], 'single seal literal')
require(template.replace(a[0], b[0], 1) == reader, 'only index seal changed')
require(not DESTINATION.exists(), 'new restore destination')
command = [sys.executable, '-B', '-O', str(PACKAGE/'restore.py'), str(DESTINATION)]
process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
for name,data in [('restore.stdout',process.stdout), ('restore.stderr',process.stderr)]:
    with (OUT/name).open('xb') as stream:
        stream.write(data)
require(process.returncode == 0 and process.stderr == b'', 'actual optimized restore process')
restored = json.loads(process.stdout)
require(restored['files'] == len(index['files']) == 586 and restored['bytes'] == 6218948 and restored['executed_sources'] is False, 'restored totals')
require({str(p.relative_to(DESTINATION)) for p in DESTINATION.rglob('*') if p.is_file()} == {x['path'] for x in index['files']}, 'exact membership')
for row in index['files']:
    local, recovered = ROOT/row['path'], DESTINATION/row['path']
    raw = recovered.read_bytes()
    require(raw == local.read_bytes() and len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'exact restored bytes')
    require(stat.S_ISREG(recovered.lstat().st_mode) and stat.S_IMODE(recovered.stat().st_mode) == 0o644, 'inert output mode')
    require(format(stat.S_IMODE(local.stat().st_mode), '04o') == row['source_permission_bits'] and format(local.stat().st_mode, '06o') == row['source_stat_mode'], 'original mode record')
status = json.loads((DESTINATION/'round3_core_ci/bwrap28_checkpoint_inputs_v2/RUN_STATUS.json').read_bytes())
observed = status['setup_5201']
require(observed['head'] == '25d940b9b768b9117a020fe350fd134198a2efcf' and observed['run'] == 42319745250 and observed['job'] == 128241131839 and observed['attempt'] == 1, 'fixed native identity')
require(observed['accepted_originals'] == 91 and observed['missing_slots'] == 43 and observed['slot_total'] == 134 and observed['profile_add_status'] == 'NOT_STARTED' and observed['mechanism_verified'] is False, 'failed mechanism boundary')
require(observed['extra_include_contents'] == 'NOT_CAPTURED_UNKNOWN' and observed['product_qualification'] is False, 'unknown source boundary')
require(status['readonly_5184']['namespace_exit'] == 1 and status['readonly_5184']['six_sysctl_read_errno12_values_remain_unknown'] is True, 'old failure retained')
root_audit = DESTINATION/'round3_local_qualification/bwrap5201_root/ROOT_REVIEW.json'
require(identity(root_audit.read_bytes())['sha256'] == 'ebc3df12ba68b833c68b2c73835b17c132e11f06bb6af5ee026989fff25706b9', 'root original native audit preserved')
paths = {x['path'] for x in index['files']}
for row in index['excluded']:
    require(row['path'] not in paths and not (DESTINATION/row['path']).exists(), 'excluded raw remains excluded')
required = {
    'round3_core_ci/bwrap_profile_setup_28/MODEL_PROCESS_LIMITATION.md',
    'round3_core_ci/bwrap_profile_setup_28/source_environment_followup/CHECKS.json',
    'round3_local_qualification/bwrap5201_root/INITIAL_REVIEW_ERROR.json',
}
require(required <= paths, 'known process and review failures retained')
receipt = {
    'observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'scope':'Independent complete selected-byte checkpoint restoration, no native or policy execution.',
    'publication':identity(publication.read_bytes()), 'index':identity(index_raw),
    'reader':identity(reader), 'original_published_reader':identity(template),
    'reader_only_seal_changed':True, 'command':command, 'exit_code':process.returncode,
    'files':586, 'bytes':6218948, 'all_original_members_bytes_and_mode_records_verified':True,
    'all_restored_files_inert_0644':True, 'source_PR':5201,
    'source_commit':observed['head'], 'recorded_run':42319745250, 'recorded_job':128241131839, 'recorded_attempt':1,
    'accepted_originals':91, 'missing_originals':43, 'required_slots':134,
    'profile_add_status':'NOT_STARTED', 'mechanism_verified':False, 'product_qualification':False,
    'original_HOME_model_process_defect_retained':True,
    'eleven_later_Git_checks_not_relabelled_as_original_27':True,
    'prior_failed_lint_source_audit_and_packet_attempts_retained':True,
    'excluded_private_console_not_reconstructed':True,
    'limits':['This reproduces selected inert bytes, not an independently executed Windows/Linux native suite.',
              'Unknown extra include contents remain absent. The unsafe-parent observation is not waived.',
              'Original source review/formatting requires its original external checkout and tools; the packet is not a self-contained native runner.',
              'The prior 5184 and current 5201 observations are from different hosted VMs and do not retroactively qualify one another.']
}
with (OUT/'ROOT_REVIEW.json').open('x') as stream:
    stream.write(json.dumps(receipt, indent=2)+'\n')
print(json.dumps({'receipt':identity((OUT/'ROOT_REVIEW.json').read_bytes()),'files':586,'bytes':6218948}))
