"""Independent local archive, source and complete original-log verification."""
from pathlib import Path, PurePosixPath
import collections
import hashlib
import json
import os
import re
import tarfile

P = Path('native-validation-results/r31-archive-closed')
C = Path('native-validation-results/r31-closed-input')
PREFIX = 'native-workspace-r31'
COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
TREE = '440d4a8e09af4009e4d9ea067388826308da8803'

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def check(b, p):
    q = pin(b)
    assert all(q[k] == p[k] for k in q if k in p), p
    return q

archive = P/'checkpoint-r31-closed.tar.gz'
expected_archive = json.loads((P/'ARCHIVE-EXPECTED-PIN.json').read_bytes())
archive_pin = check(archive.read_bytes(), expected_archive)
data, members = {}, {}
with tarfile.open(archive,'r:gz') as tf:
    for item in tf.getmembers():
        path = PurePosixPath(item.name)
        assert item.isfile() and not item.issym() and not item.islnk()
        assert not path.is_absolute() and '..' not in path.parts and path.as_posix() == item.name
        assert item.name not in data
        raw = tf.extractfile(item).read()
        assert len(raw) == item.size
        data[item.name], members[item.name] = raw, item
index = json.loads(data['INDEX.json'])
assert len(index['files']) + 1 == len(data)
assert {r['path'] for r in index['files']} == set(data)-{'INDEX.json'}
for row in index['files']:
    check(data[row['path']],row)
    assert members[row['path']].mode == row['mode']

manifest_raw = Path('source53-apply-preparation/derived/native-candidate-r30-source.json').read_bytes()
assert data['input/native-candidate-r30-source.json'] == manifest_raw
manifest = json.loads(manifest_raw)
assert manifest['source_commit'] == COMMIT and manifest['source_tree'] == TREE
assert len(manifest['changed_files']) == 197
source_paths = {n for n in data if n.startswith('source/')}
assert source_paths == {'source/'+r['path'] for r in manifest['changed_files']}
for row in manifest['changed_files']:
    name = 'source/'+row['path']
    check(data[name],row)
    assert ('100755' if members[name].mode & 0o111 else '100644') == row['mode']
    prior = Path('native-validation-results/r30-archive-closed/original')/name
    assert prior.read_bytes() == data[name]
for name,sha in [('codex-rs/Cargo.lock','4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'),('MODULE.bazel.lock','e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb')]:
    assert hashlib.sha256(data['locks/'+name]).hexdigest() == sha

pins = json.loads((C/'R31-INPUT-PINS.json').read_bytes())
assert len(pins) == 18
for name,p in pins.items():
    check(data['evidence/'+name],p)
    if (C/'evidence'/name).exists():
        assert (C/'evidence'/name).read_bytes() == data['evidence/'+name]
def obj(suffix):
    return json.loads(data['evidence/'+PREFIX+suffix])
terminal = obj('-terminal-process-status.json')
assert terminal['job_id'] == '1a1b275ba33-fc05-7e17'
assert terminal['state'] == 'succeeded' and terminal['exit_code'] == 0
for k in ['output_complete','output_durable','terminal_publication_confirmed']:
    assert terminal[k] is True
for k in ['timed_out','cancelled','automatic_retry']:
    assert terminal[k] is False
assert not any(terminal['log_truncated'].values()) and all(v is None for v in terminal['log_errors'].values())
for stream in ['stdout','stderr']:
    parts = []
    for name,b in data.items():
        if re.fullmatch(r'controller/read-[0-9]+\.json',name):
            rec = json.loads(b); assert rec['job_id'] == terminal['job_id']
            rec = rec[stream]; raw = bytes.fromhex(rec['bytes_hex'])
            assert rec['text'].encode() == raw and rec['next_offset']-rec['offset'] == len(raw)
            assert rec['size'] >= rec['next_offset']
            parts.append((rec['offset'],raw))
    end = 0; out = b''
    for offset,part in sorted(parts,key=lambda row:row[0]):
        if not part:
            assert offset <= end
            continue
        assert offset == end
        out += part; end += len(part)
    assert end == terminal['log_bytes'][stream]['seen'] == terminal['log_bytes'][stream]['stored']
    assert terminal['log_synced'][stream] is True
    assert out == data['controller/original-'+stream+'.txt']
assert len(data['controller/original-stdout.txt']) == 4875 and data['controller/original-stderr.txt'] == b''

raw = obj('-tests-raw-process-result.json')
receipt = obj('-tests-receipt.json')
complete = obj('-complete.json')
review = obj('-result-review.json')
for x in [raw,receipt,complete,review]:
    assert x['source_commit'] == COMMIT and x['source_tree'] == TREE
assert raw['command'] == receipt['command'] == complete['command'] == ['just','test','--locked','--retries','0']
assert raw['exit_code'] == receipt['exit_code'] == receipt['effective_exit_code'] == complete['workspace_exit'] == 0
assert receipt['issues'] == [] and receipt['phase_pass'] is True
for value,key in [(receipt,'raw_process_result'),(receipt,'source_preguard'),(receipt,'source_postguard'),(receipt,'scope'),(receipt,'acceptance_readback'),(complete,'receipt'),(complete,'readback'),(complete,'scope')]:
    pointer=value[key]; check(data['evidence/'+pointer['path']],pointer)
assert raw['end_unix'] == receipt['end_unix'] and raw['start_unix'] == receipt['start_unix']
assert receipt['end_unix'] <= terminal['at_unix_ms']/1000
assert receipt['end_unix']-receipt['start_unix'] == receipt['elapsed_seconds']
assert re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$', data['evidence/'+PREFIX+'-tests-resources.txt'],re.M) == [b'0']
for suffix in ['-source-pre-verification.json','-metadata-source-post-verification.json','-tests-source-pre-verification.json','-source-post-test-verification.json']:
    g=obj(suffix)
    assert g['pass'] is True and g['source_commit'] == COMMIT and g['actual_tree'] == g['expected_tree'] == TREE
    assert g['native_head'] == 'bef6fa7645df9df12b69fda499e97eed25de6c75' and g['changed_file_count'] == 197
    assert g['file_mismatches'] == g['unstaged_paths'] == g['untracked_paths'] == []
    assert g['cargo_lock_sha256'] == manifest['cargo_lock_sha256'] and g['bazel_lock_sha256'] == manifest['bazel_lock_sha256']

metadata = obj('-metadata.json'); meta_raw = obj('-metadata-raw-process-result.json'); meta_rec = obj('-metadata-receipt.json')
assert meta_raw['exit_code'] == meta_rec['exit_code'] == 0
assert meta_raw['command'] == ['cargo','metadata','--locked','--no-deps','--format-version','1']
assert meta_raw['start_unix'] == 1793995431.0169575 and meta_raw['end_unix'] <= raw['start_unix']
assert len(metadata['workspace_members']) == len(set(metadata['workspace_members'])) == 193
assert set(metadata['workspace_members']) == set(metadata['workspace_default_members'])
assert data['evidence/'+PREFIX+'-scope.json'] == Path('source53-final-scope-preparation/input/native-workspace-r31-scope.json').read_bytes()

log = data['evidence/'+PREFIX+'-tests.log']
check(log,review['log'])
ansi = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
terminal_row = re.compile(r'^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9]+(?:\.[0-9]+)?)s\]\s+(\S+)\s+(.+?)\s*$')
rows=[]; summary=[]; start=[]; footer=[]; byte=0; finished=False
for line_number, line in enumerate(log.splitlines(keepends=True),1):
    text=ansi.sub(b'',line).decode('utf-8').rstrip('\r\n')
    if re.match(r'^\s*Starting \d+ tests across \d+ binaries',text):
        start.append((line_number,byte,text))
    if re.match(r'^\s*Summary \[',text):
        summary.append((line_number,byte,text)); finished=True
    match=terminal_row.fullmatch(text)
    if match:
        status,seconds,binary,name=match.groups()
        row={'status':status,'seconds':float(seconds),'binary':binary,'name':name,'line':line_number,'byte_offset':byte}
        (footer if finished else rows).append(row)
    byte+=len(line)
assert len(start)==len(summary)==1
assert rows == obj('-test-results.json')
assert len(rows)==len({(r['binary'],r['name']) for r in rows})==20228
assert collections.Counter(r['status'] for r in rows)=={'PASS':20228} and footer == []
assert '20228 tests across 366 binaries (130 tests skipped)' in start[0][2]
assert '20228 tests run: 20228 passed (5 slow), 130 skipped' in summary[0][2]
assert summary[0][0]==review['summary']['line'] and summary[0][1]==review['summary']['byte_offset']
prior_rows=json.loads(Path('native-validation-results/r29-archive-closed/original/evidence/native-workspace-r29-test-results.json').read_bytes())
assert {(r['binary'],r['name']) for r in rows}=={(r['binary'],r['name']) for r in prior_rows}
assert collections.Counter(r['status'] for r in prior_rows)=={'PASS':20227,'FAIL':1}
assert review['terminal_counts']==complete['counts']=={'PASS':20228,'FAIL':0,'TIMEOUT':0}
assert review['reported_skipped']==complete['reported_skipped']==130
assert receipt['packages_argument'] is None and receipt['retries']==0 and receipt['filters']=='no_additions'
assert receipt['test_ids_used_as_filter'] is False and complete['fix_fmt_executed'] is False
bedrock=[r for r in rows if r['binary']=='codex-app-server::all' and r['name']=='suite::v2::bedrock_setup::setup_bedrock_profile_and_environment']
assert len(bedrock)==1 and bedrock[0]['status']=='PASS'

out=P/'original';out.mkdir(exist_ok=False)
for name,b in data.items():
    f=out/name;f.parent.mkdir(parents=True,exist_ok=True)
    with f.open('xb') as stream:stream.write(b)
report={'schema':'hepta.root-r31-full-original-archive-readback.v1','result':'ORIGINAL_SOURCE53_R31_PASS',
        'archive':archive_pin,'members':len(data),'index_rows':len(index['files']),
        'all_archive_raw_hash_Git_mode_pins_verified':True,'all197_source_bytes_equal_closed_R30':True,
        'full_repository_tree_reconstruction_claimed':False,'original_files':18,'outer_exit':0,'raw_exit':0,'effective_exit':0,
        'original_command':raw['command'],'workspace_members':193,'unique_test_ids':20228,
        'counts':{'PASS':20228,'FAIL':0,'TIMEOUT':0},'reported_skipped':130,'footer_duplicates':0,
        'exact_baseline_set_independently_rebuilt':True,'all20228_derived_rows_equal_original_log':True,
        'original_test_log':pin(log),'original_test_rows':pin(data['evidence/'+PREFIX+'-test-results.json']),
        'wall_seconds':receipt['elapsed_seconds'],'nextest_summary_seconds':1643.187,
        'controller_bytes':{'stdout':4875,'stderr':0},'source_guards_rechecked':4,'source_count':197,
        'source_commit':COMMIT,'source_tree':TREE,'bedrock_observation':bedrock[0],
        'original_R29_failure_retained':True,'diagnostic_only':True,'behavior_repair_claimed':False,
        'post_fix_fmt_qualification_claimed':False,'science':'HOLD','authority':'DENY_ALL'}
dest=P/'ROOT-ARCHIVE-READBACK.json'
with dest.open('xb') as stream:
    stream.write((json.dumps(report,indent=2)+'\n').encode());stream.flush();os.fsync(stream.fileno())
print(json.dumps({'path':str(dest),**pin(dest.read_bytes()),'members':len(data),'counts':report['counts']}))
