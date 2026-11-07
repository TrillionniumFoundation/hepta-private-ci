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
PACKAGE = ROOT / 'round3_native/read_authority_evidence_20261107'
DESTINATION = ROOT / 'round3_root_restore_read_authority_0107'


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(raw):
    return {'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


publication = ROOT / 'round3_native/READ_AUTHORITY_CHECKPOINT_PUBLICATION_MANIFEST.json'
manifest = json.loads(publication.read_bytes())
require(len(manifest['files']) == 7, 'publication file count')
for row in manifest['files']:
    p = Path(row['local_path'])
    actual = identity(p.read_bytes())
    require(actual == {'bytes':row['bytes'], 'sha256':row['sha256'], 'git_blob':row['git_blob_sha']}, 'publication identity')
    require(row['mode'] == '100644' and stat.S_IMODE(p.stat().st_mode) == 0o644, 'publication mode')
index_raw = (PACKAGE/'INDEX.json').read_bytes()
index = json.loads(index_raw)
require(hashlib.sha256(index_raw).hexdigest() == manifest['index_sha256'] == 'b02e9c68d9d5e40b0d6283717d8fbda4e6fd8629f6a7ac0b7aadfc0a3ad21d02', 'fixed index')
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
require(restored['files'] == len(index['files']) == 84 and restored['bytes'] == 1287907 and restored['executed_sources'] is False, 'restored totals')
require({str(p.relative_to(DESTINATION)) for p in DESTINATION.rglob('*') if p.is_file()} == {x['path'] for x in index['files']}, 'exact membership')
for row in index['files']:
    local, recovered = ROOT/row['path'], DESTINATION/row['path']
    raw = recovered.read_bytes()
    require(raw == local.read_bytes() and len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'exact restored bytes')
    require(stat.S_ISREG(recovered.lstat().st_mode) and stat.S_IMODE(recovered.stat().st_mode) == 0o644, 'inert output mode')
    require(format(stat.S_IMODE(local.stat().st_mode), '04o') == row['source_permission_bits'] and format(local.stat().st_mode, '06o') == row['source_stat_mode'], 'original mode record')
status = json.loads((DESTINATION/'round3_native/read_authority_checkpoint_inputs/RUN_STATUS.json').read_bytes())
require(status['source']['head'] == 'a7b8ba921c9e34e13eac6c59658dc7088c4bad3d' and status['source']['tree'] == 'df3e4bf57f98b1dd33f4b748513d6ef8142a0d16', 'published probe source')
require(status['run_id'] == 42320716996 and status['run_attempt'] == 1 and status['new_F0_F4'] == 'NOT_OBSERVED' and status['product_p0_closed'] is False, 'queued snapshot boundary')
fmt = json.loads((DESTINATION/'round3_local_qualification/authority38_source/ROOT_REVIEW.json').read_bytes())
require(fmt['exit_code'] == 0 and len(fmt['before']) == 96 and len(fmt['after']) == 97 and fmt['owned_status_and_bytes_exact'] is True, 'original formatter evidence')
reviewed = json.loads((DESTINATION/'round3_native/windows_read_authority_probe_38/review1/manifest.reviewed.json').read_bytes())
require(reviewed['changed_lines'] == 748 and reviewed['owning_crate_compile'] is False and reviewed['native_windows_execution'] is False, 'source only scope')
require((DESTINATION/'round3_local_qualification/authority38_initial/ERROR.json').is_file() and (DESTINATION/'round3_native/windows_read_authority_probe_38/review1/METADATA_CHECK.json').is_file(), 'prior failure preservation')
receipt = {
    'observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'scope':'Exact selected source/review/queued-API custody. No owning compile, native probe or scanner execution.',
    'publication':identity(publication.read_bytes()), 'index':identity(index_raw),
    'reader':identity(reader), 'original_published_reader':identity(template),
    'reader_only_seal_changed':True, 'command':command, 'exit_code':process.returncode,
    'files':84, 'bytes':1287907, 'all_original_members_bytes_and_mode_records_verified':True,
    'all_restored_files_inert_0644':True, 'source_PR':5203, 'source_commit':status['source']['head'],
    'source_tree':status['source']['tree'], 'recorded_run':42320716996, 'recorded_attempt':1,
    'recorded_snapshot':'2026-11-07T00:56:21Z; no Windows jobs yet; newer observations must be separate.',
    'original_format_exit':0, 'original_owned_before':96, 'original_owned_after':97,
    'owning_compile':False, 'new_F0_F4':'NOT_OBSERVED_IN_THIS_PACKET', 'P0_closed':False,
    'metadata_projection_limit':'Four non-executable ACL stubs; initial import failure and corrected zero exit remain separate.',
    'limits':['Published source and earlier source bindings are preserved; this receipt is not a fresh full repository walk.',
              'Restoration verifies the selected bytes, not the external checkout, toolchains, package cache or Windows host.',
              'The original formatter helper needs its original source overlay and prior inventory; archival source is not automatically executable.']
}
with (OUT/'ROOT_REVIEW.json').open('x') as stream:
    stream.write(json.dumps(receipt, indent=2)+'\n')
print(json.dumps({'receipt':identity((OUT/'ROOT_REVIEW.json').read_bytes()),'files':84,'bytes':1287907}))
