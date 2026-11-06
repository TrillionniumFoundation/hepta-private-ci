#!/usr/bin/env python3
"""Pure local r28 archive/result verification and create-only formal attachment.

This reader performs no subprocess, Git, network, Rust, metadata or formatter
operation. It only reads closed original files and writes the new attachment.
"""
from collections import Counter
import argparse
import ast
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

WORK = Path('/workspace/scratch/08f5efd48967')
FORMAL = WORK / 'hepta-cell/qualification/cell-unification-20261106/native-evidence'
OUTPUT = FORMAL / 'r28-project-checkpoint'
ARCHIVE_NAME = 'checkpoint-r28-closed.tar.gz'
ARCHIVE_PIN = {'bytes':1741088, 'sha256':'bfefe97ed55731dffdd944f784040bb00690df292447bd78c9b5098759476eb9', 'git_blob':'04f10a8274c45011b8602db17f1f79d8d1e9c766'}
COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
PREFIX = 'native-source52-project-r28'
JOB = '1a1b1e9bee0-fc05-7b7c'
EXPORT_JOB = '1a1b1ff192d-fc05-7bf0'
SOURCE_SHA = '3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898'
RUNNER_SHA = 'a7b64eb8ff8ec2b5bc75ae836e3ff423ce31ee86d5c4daf64b7543a8fa7aae9e'
EXPORTER_SHA = '044b8ab379b1eed3b4f1aa086285183b7423323d554b49e6955cffdeb0cfdebf'
PACKAGES = ['codex-cli','codex-exec-server','codex-network-proxy','codex-external-agent-migration']
CARGO_SHA = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
BAZEL_SHA = 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'
RUNTIME = 'codex-rs/network-proxy/src/runtime.rs'
BASELINE_SHA = '6feba9a285f77f16fc1d34710d2737eae78a4ba3be74affd40f5703bc8ce405e'
ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
RESULT = re.compile(rb'^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$')
START = re.compile(rb'^\s*Starting (\d+) tests across (\d+) binaries \((\d+) tests skipped\)\s*$')
SUMMARY = re.compile(rb'^\s*Summary\s+\[\s*([0-9.]+)s\]\s+(\d+) tests run:(.*)$')


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def raw_json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def exact(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, f"create-only mismatch: {path}"
    else:
        with path.open("xb") as stream:
            stream.write(raw)


def gz(raw):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", filename="", mtime=0, compresslevel=9) as stream:
        stream.write(raw)
    packed = buf.getvalue()
    assert packed[4:8] == b"\0\0\0\0" and gzip.decompress(packed) == raw
    return packed


def safe(path):
    value = PurePosixPath(path)
    assert path and not value.is_absolute() and ".." not in value.parts and "." not in value.parts
    return value


def natural_terminal(value, job, rc):
    assert value["job_id"] == job and value["exit_code"] == rc
    assert value["state"] == ("succeeded" if rc == 0 else "failed")
    assert all(value[k] is False for k in ("timed_out", "cancelled", "automatic_retry"))
    assert all(value[k] is True for k in ("output_complete", "output_durable", "terminal_publication_confirmed"))
    assert all(x is False for x in value["log_truncated"].values())
    assert all(x is None for x in value["log_errors"].values())


def verify_sealed(output):
    manifest = json.loads((output / "ATTACHMENT-MANIFEST.json").read_bytes())
    expected = {row["path"] for row in manifest["files"]} | {"ATTACHMENT-MANIFEST.json"}
    actual = {str(p.relative_to(output)) for p in output.rglob("*") if p.is_file()}
    assert actual == expected
    for row in manifest["files"]:
        assert pin((output / row["path"]).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    for row in json.loads((output / "GZIP-ROUNDTRIP.json").read_bytes())["files"]:
        packed = (output / row["path"]).read_bytes()
        assert packed[4:8] == b"\0\0\0\0" and pin(gzip.decompress(packed)) == row["uncompressed"]
    print(json.dumps({"status": "SEALED_BYTES_VERIFIED", "files": len(actual), "bytes": sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),
                      "manifest": pin((output / "ATTACHMENT-MANIFEST.json").read_bytes()), "rust_executed": False}, indent=2))


def original_lines(raw):
    offset = 0
    for number, part in enumerate(raw.splitlines(keepends=True), 1):
        yield number, offset, ANSI.sub(b'', part).rstrip(b'\r\n')
        offset += len(part)


def parse_log(raw):
    starts, summaries, records = [], [], []
    for number, offset, line in original_lines(raw):
        if m := START.fullmatch(line):
            starts.append({'line':number, 'byte_offset':offset, 'text':line.decode(),
                           'tests':int(m[1]), 'binaries':int(m[2]), 'reported_skipped':int(m[3])})
        if m := SUMMARY.fullmatch(line):
            counts = {label.decode():int(n) for n,label in re.findall(rb'(\d+) (passed|failed|timed out|skipped)',m[3])}
            assert 'skipped' in counts
            summaries.append({'line':number,'byte_offset':offset,'text':line.decode(),
                              'seconds':float(m[1]),'tests_run':int(m[2]),
                              'counts':{'PASS':counts.get('passed',0),'FAIL':counts.get('failed',0),'TIMEOUT':counts.get('timed out',0)},
                              'reported_skipped':counts['skipped']})
        if m := RESULT.fullmatch(line):
            records.append({'status':m[1].decode(),'seconds':float(m[2]),'binary':m[3].decode(),
                            'name':m[4].decode(),'line':number,'byte_offset':offset})
    assert len(starts) == len(summaries) == 1
    start, summary = starts[0], summaries[0]
    rows = [r for r in records if start['line'] < r['line'] < summary['line']]
    footer = [r for r in records if r['line'] > summary['line']]
    assert len(rows) + len(footer) == len(records)
    keyed = {(r['binary'],r['name']):r for r in rows}
    assert len(rows) == len(keyed) == start['tests'] == summary['tests_run'] == 1564
    counts = {s:sum(r['status'] == s for r in rows) for s in ('PASS','FAIL','TIMEOUT')}
    assert counts == summary['counts'] == {'PASS':1564,'FAIL':0,'TIMEOUT':0}
    assert start['reported_skipped'] == summary['reported_skipped'] == 3
    assert start['binaries'] == 49 and len({r['binary'] for r in rows}) <= start['binaries']
    assert footer == [] and {r['binary'].split('::',1)[0] for r in rows} == set(PACKAGES)
    return start, summary, rows, keyed, footer


def parse_python(raw):
    summaries, oks, skips = [], [], []
    for number, offset, line in original_lines(raw):
        if m := re.fullmatch(rb'Ran (\d+) tests in ([0-9.]+)s', line):
            summaries.append({'line':number,'byte_offset':offset,'text':line.decode(),
                              'tests':int(m[1]),'seconds':float(m[2])})
        if line == b'OK':
            oks.append({'line':number,'byte_offset':offset,'text':line.decode()})
        if re.search(rb'(^OK \(skipped=|\.\.\. skipped)',line):
            skips.append({'line':number,'byte_offset':offset,'text':line.decode()})
    assert len(summaries) == len(oks) == 1 and summaries[0]['tests'] == 32 and skips == []
    return {'tests':32,'skipped':0,'status':'OK','summary':summaries[0],'ok':oks[0],
            'log':pin(raw),'skip_lines':skips}


def check_recorded_guard(value, phase=None):
    assert value['source_commit'] == COMMIT and value['expected_tree'] == value['actual_tree'] == TREE
    assert value['pass'] is True and value['changed_file_count'] == 195 and value['native_head'] == HEAD
    assert value['unstaged_paths'] == value['untracked_paths'] == value['file_mismatches'] == []
    assert value['changed_path_set_matches'] is True
    assert value['cargo_lock_sha256'] == CARGO_SHA and value['bazel_lock_sha256'] == BAZEL_SHA
    if phase is not None:
        assert value['phase'] == phase and value['gate_exit_code'] == 0


def verify_controller(members, terminal):
    original_names = ['launch.json','terminal-process-status.json','read-000000.json','read-002995.json','read-005725.json']
    controller = {name:json.loads(members['controller/'+name]) for name in original_names}
    assert members['controller/terminal-process-status.json'] == members['evidence/'+PREFIX+'-terminal-process-status.json']
    launch = controller['launch.json']
    assert launch['job']['id'] == JOB and launch['job']['launch_state'] == 'launched' and launch['launch']['ok'] is True
    assert RUNNER_SHA in launch['job']['args'][1]
    observed = {}
    for stream in ('stdout','stderr'):
        chunks = []
        for name in original_names:
            if not name.startswith('read-'):
                continue
            value = controller[name]
            assert value['job_id'] == JOB
            item = value[stream]
            raw = bytes.fromhex(item['bytes_hex'])
            assert raw == item['text'].encode()
            assert len(raw) == item['next_offset']-item['offset']
            assert item['size'] >= item['next_offset']
            chunks.append({'name':name,'offset':item['offset'],'next_offset':item['next_offset'],
                           'reported_total_stream_size':item['size'],'raw':raw})
        cursor, joined, rows = 0, [], []
        for item in sorted(chunks, key=lambda x:(x['offset'],x['next_offset'],x['name'])):
            raw = item.pop('raw')
            if raw:
                assert item['offset'] == cursor
                cursor += len(raw)
                joined.append(raw)
            else:
                assert item['offset'] <= cursor
            rows.append({**item,'chunk':pin(raw)})
        output = b''.join(joined)
        assert terminal['log_bytes'][stream]['seen'] == terminal['log_bytes'][stream]['stored'] == len(output)
        assert output == members['controller/original-'+stream+'.txt']
        observed[stream] = {'chunks':rows,'joined':pin(output),'terminal_seen_stored':len(output)}
    assert observed['stdout']['joined']['bytes'] == 8309 and observed['stderr']['joined']['bytes'] == 0
    return {'originals':[{ 'path':'controller/'+name,**pin(members['controller/'+name])} for name in original_names],
            'streams':observed,'all_offsets_text_hex_and_terminal_complete':True,
            'size_semantics':'process_read.size is total stream length at read time; chunk length is next_offset minus offset.'}


def archive_members(archive_raw, unpacked):
    members, modes = {}, {}
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as tar:
        for member in tar.getmembers():
            safe(member.name)
            assert member.isfile() and not member.issym() and not member.islnk() and member.name not in members
            raw = tar.extractfile(member).read()
            assert len(raw) == member.size
            assert (unpacked/member.name).is_file() and not (unpacked/member.name).is_symlink()
            assert (unpacked/member.name).read_bytes() == raw
            members[member.name], modes[member.name] = raw, member.mode
    assert len(members) == 295
    actual = {str(p.relative_to(unpacked)) for p in unpacked.rglob('*') if p.is_file()}
    assert actual == set(members)
    index = json.loads(members['INDEX.json'])
    assert index['source_commit'] == COMMIT and index['source_tree'] == TREE and index['source_count'] == 195
    assert index['classification'] == 'original_four_package_gate_passed' and index['original_outer_exit'] == 0
    assert index['original_counts'] == {'PASS':1564,'FAIL':0,'TIMEOUT':0} and index['reported_skipped'] == 3
    indexed = {r['path']:r for r in index['files']}
    assert len(indexed) == len(index['files']) == 294 and set(indexed) == set(members)-{'INDEX.json'}
    for name,row in indexed.items():
        assert pin(members[name]) == {k:row[k] for k in ('bytes','sha256','git_blob')}
        assert modes[name] == row['mode']
    return members,modes,index


def verify_sources(members,modes):
    source_raw = members['input/native-candidate-r28-source.json']
    assert pin(source_raw)['sha256'] == SOURCE_SHA
    source = json.loads(source_raw)
    assert source['source_commit'] == COMMIT and source['source_tree'] == TREE
    files = {r['path']:r for r in source['changed_files']}
    assert len(files) == len(source['changed_files']) == 195
    assert {'source/'+p for p in files} == {p for p in members if p.startswith('source/')}
    rows = []
    for path,row in sorted(files.items()):
        assert row['mode'] in ('100644','100755')
        assert pin(members['source/'+path]) == {k:row[k] for k in ('bytes','sha256','git_blob')}
        rows.append({**row,'archive_member':'source/'+path,'archive_transport_mode':modes['source/'+path],
                     'raw_sha_and_git_blob_verified':True})
    assert sum(p.endswith('.rs') for p in files) == 181
    assert files[RUNTIME]['mode'] == '100644' and files[RUNTIME]['bytes'] == 76209
    assert files[RUNTIME]['sha256'] == '1d8523c4eda08408eb952a86d692f1e2cfb2975de934de6f1f325597fe9681c8'
    assert files[RUNTIME]['git_blob'] == '2c0b88642d1c079ee3991e9e1e418bbb01203694'
    assert pin(members['locks/codex-rs/Cargo.lock'])['sha256'] == CARGO_SHA
    assert pin(members['locks/MODULE.bazel.lock'])['sha256'] == BAZEL_SHA
    parent = json.loads(members['input/ancestor-manifests/native-candidate-r26-source.json'])
    old = {r['path']:r for r in parent['changed_files']}
    assert len(old) == 194 and RUNTIME not in old and set(files) == set(old)|{RUNTIME}
    assert all(files[path] == row for path,row in old.items())
    assert parent['source_commit'] == 'e28b0f385ee882f842911044958b2810f62f6379'
    assert parent['source_tree'] == '763c8d2b4089f6e9806c3bbb68fa247bc2f6af36'
    return source,rows


def verify_phases(members):
    evidence = lambda suffix:members['evidence/'+PREFIX+suffix]
    record = lambda suffix:json.loads(evidence(suffix))
    package_args = [x for p in PACKAGES for x in ('-p',p)]
    commands = {'python-runner':['python3','-m','unittest','discover','-s','scripts','-p','test_run_nextest*.py','-v'],
                'strict':['just','clippy','--locked',*package_args,'--','-D','warnings'],
                'tests':['just','test','--locked',*package_args,'--retries','0']}
    phase_data, receipts, previous_end = {}, [], None
    for phase in commands:
        raw,receipt = record('-'+phase+'-raw-process-result.json'),record('-'+phase+'-receipt.json')
        for value in (raw,receipt):
            assert value['source_commit'] == COMMIT and value['source_tree'] == TREE and value['phase'] == phase
            assert value['exit_code'] == 0 and value['command'] == commands[phase]
            assert value['cwd'] == '/home/alex/work/hepta-cell-unified-20261106-a/source'+('' if phase=='python-runner' else '/codex-rs')
        for key in ('source_commit','source_tree','phase','command','cwd','exit_code','start_unix','end_unix'):
            assert raw[key] == receipt[key]
        assert receipt['effective_exit_code'] == 0 and receipt['phase_pass'] is True and receipt['issues'] == []
        assert receipt['end_unix'] >= receipt['start_unix']
        assert abs(receipt['elapsed_seconds']-(receipt['end_unix']-receipt['start_unix'])) < 1e-6
        assert previous_end is None or receipt['start_unix'] >= previous_end
        previous_end = receipt['end_unix']
        assert receipt['source_manifest_sha256'] == SOURCE_SHA
        assert receipt['raw_process_result'] == {'path':PREFIX+'-'+phase+'-raw-process-result.json',**pin(evidence('-'+phase+'-raw-process-result.json'))}
        assert receipt['log_sha256'] == pin(evidence('-'+phase+'.log'))['sha256']
        assert receipt['resources_sha256'] == pin(evidence('-'+phase+'-resources.txt'))['sha256']
        assert re.findall(rb'^\s*Exit status: ([0-9]+)\s*$',evidence('-'+phase+'-resources.txt'),re.M) == [b'0']
        check_recorded_guard(record('-'+phase+'-source-pre-verification.json'))
        check_recorded_guard(record('-'+phase+'-source-post-verification.json'),phase)
        assert receipt['source_postguard'] == {'path':PREFIX+'-'+phase+'-source-post-verification.json',**pin(evidence('-'+phase+'-source-post-verification.json'))}
        assert receipt['source_guards_pass'] is True and receipt['fix_fmt_executed'] is False and receipt['baseline_used_as_filter'] is False
        assert receipt['features'] == 'unchanged_defaults' and receipt['filters'] == 'no_additions'
        assert receipt['packages'] == ([] if phase=='python-runner' else PACKAGES)
        if receipt['acceptance_readback'] is not None:
            assert receipt['acceptance_readback'] == {'path':PREFIX+'-'+phase+'-result-review.json',**pin(evidence('-'+phase+'-result-review.json'))}
        receipts.append({'path':PREFIX+'-'+phase+'-receipt.json',**pin(evidence('-'+phase+'-receipt.json'))})
        phase_data[phase] = {'original_exit':0,'effective_exit':0,'elapsed_seconds':receipt['elapsed_seconds'],
                             'command':commands[phase],'cwd':receipt['cwd'],'raw':receipt['raw_process_result'],
                             'receipt':receipts[-1],'log':pin(evidence('-'+phase+'.log')),
                             'resources':pin(evidence('-'+phase+'-resources.txt')),'source_guards_pass':True}
    py = parse_python(evidence('-python-runner.log'))
    py_original = record('-python-runner-result-review.json')
    assert py_original['reported_test_count'] == 32 and py_original['reported_skipped'] == 0 and py_original['pass'] is True
    assert py_original['log'] == py['log']
    assert py_original['summary_lines'] == [{k:py['summary'][k] for k in ('line','byte_offset','text')}]
    assert py_original['ok_lines'] == [py['ok']] and py_original['skip_lines'] == []
    # Preserve the inherited source51 label in the original Python-review schema.
    py['original_schema_retained'] = py_original['schema']
    start,summary,rows,keyed,footer = parse_log(evidence('-tests.log'))
    assert rows == record('-tests-test-results.json') == record('-closed-test-results.json')
    review = record('-tests-result-review.json')
    assert review['log'] == pin(evidence('-tests.log')) and review['counts'] == review['summary_counts'] == summary['counts']
    assert review['execution_rows'] == review['unique_test_count'] == 1564 and review['reported_skipped'] == 3 and review['pass'] is True
    assert review['footer_rows_excluded'] == footer == []
    assert review['starting'] == {k:start[k] for k in ('line','byte_offset','text')}
    assert review['summary'] == {k:summary[k] for k in ('line','byte_offset','text','seconds')}
    assert review['baseline_missing'] == review['baseline_not_pass'] == review['additional_test_ids'] == review['unexpected_packages'] == []
    assert review['duplicate_execution_ids'] is False and review['skip_identities_inferred'] is False and review['baseline_used_as_filter'] is False
    baseline_raw = members['input/baseline/source50-four-package-r23-baseline.json']
    assert pin(baseline_raw)['sha256'] == BASELINE_SHA
    baseline = json.loads(baseline_raw)
    ids = {(r['binary'],r['name']) for r in baseline['test_ids']}
    assert len(ids) == len(baseline['test_ids']) == 1564 and ids == set(keyed)
    per_package = {p:{s:sum(r['binary'].split('::',1)[0]==p and r['status']==s for r in rows) for s in ('PASS','FAIL','TIMEOUT')} for p in PACKAGES}
    assert per_package == review['per_package']
    fail = json.loads(members['failure-blocks/INDEX.json'])
    assert fail['source_commit'] == COMMIT and fail['source_tree'] == TREE and fail['original_outer_exit'] == 0
    assert fail['counts'] == summary['counts'] and fail['reported_skipped'] == 3 and fail['failures'] == [] and fail['test_log_parse_error'] is None
    assert {p for p in members if p.startswith('failure-blocks/')} == {'failure-blocks/INDEX.json'}
    terminal = record('-terminal-process-status.json')
    natural_terminal(terminal,JOB,0)
    assert terminal['at_unix_ms']/1000 >= previous_end
    complete = record('-complete.json')
    assert complete['source_commit'] == COMMIT and complete['source_tree'] == TREE and complete['source_manifest_sha256'] == SOURCE_SHA
    assert complete['phase_receipts'] == receipts and complete['source_guards_pass'] is True
    assert complete['python_exit'] == complete['strict_exit'] == complete['tests_exit'] == 0
    assert complete['python_tests'] == 32 and complete['python_skipped'] == 0 and complete['packages'] == PACKAGES
    assert complete['required_old_ids'] == 1564 and complete['all_old_ids_observed_pass'] is True
    assert complete['workspace_not_started_by_this_runner'] is True and complete['fix_fmt_executed'] is False
    assert complete['whole_workspace_qualification'] == 'PENDING_SEPARATE_ORIGINAL_GATE'
    assert 'evidence/'+PREFIX+'-incomplete.json' not in members
    check_recorded_guard(record('-source-pre-verification.json'))
    check_recorded_guard(record('-source-final-verification.json'))
    assert pin(members['input/native-run-r28.py'])['sha256'] == RUNNER_SHA
    derived = record('-closed-result-review.json')
    assert derived['original_test_review'] == review and derived['engineering_gate'] == 'PASS'
    assert derived['outer_original_exit'] == 0 and derived['test_execution_counts'] == summary['counts']
    assert derived['reported_skipped'] == 3 and derived['failure_blocks'] == [] and derived['parse_error'] is None
    proof = record('-export-source-verification.json')
    assert proof['source_commit'] == COMMIT and proof['source_tree'] == TREE and proof['source_count'] == 195
    assert proof['all195_raw_sha_gitblob_gitmode_verified'] is True and proof['source51_manifest_preserved_194'] is True
    assert proof['source_guard_before'] == proof['source_guard_after']
    assert proof['original_test_counts'] == summary['counts'] and proof['original_outer_exit'] == 0
    assert proof['export_modifies_source'] is False and proof['rust_rerun'] is False
    assert proof['workspace_started_by_exporter'] is False and proof['fix_fmt_executed_by_exporter'] is False
    return phase_data,py,start,summary,rows,keyed,per_package,terminal,complete


def verify_preconditions(members):
    pre = json.loads(members['evidence/'+PREFIX+'-preconditions.json'])
    assert pre['source_commit'] == COMMIT and pre['source_tree'] == TREE and pre['actual_changed_file_count'] == 195
    assert pre['source_manifest'] == {'path':'native-candidate-r28-source.json',**pin(members['input/native-candidate-r28-source.json'])}
    assert pre['patch_application_performed_by_this_runner'] is False and pre['lock_update_performed_by_this_runner'] is False
    assert pre['source52_bazel_lock_update_executed'] is False and pre['source50_lock_inherited_only_for_unchanged_dependency_inputs'] is True
    checked = []
    def verify(value,directory):
        member = directory+'/'+value['path']
        assert pin(members[member]) == {k:value[k] for k in ('bytes','sha256','git_blob')}
        checked.append({'member':member,**pin(members[member])})
    verify(pre['baseline'],'input/baseline')
    for key in ('source50_root_manifest','source51_parent_manifest'):
        verify(pre[key],'input/ancestor-manifests')
    for key,directory in [('source50_lock_originals_and_outer_terminal','input/source50-lock-prerequisites'),
                          ('original_r24_failed_100_provenance','input/r24-failed-provenance'),
                          ('original_r26_failed_100_provenance','input/r26-failed-provenance')]:
        for value in pre[key]:
            verify(value,directory)
    for key in ('complete','terminal','source_postguard','delta_manifest'):
        verify(pre['source52_apply'][key],'input/source52-apply-pins')
    ancestor = json.loads(members['input/source51-ancestor/native-source51-project-r26-preconditions.json'])
    for key in ('complete','terminal','source_postguard','delta_manifest'):
        verify(ancestor['source51_apply'][key],'input/source51-apply-prerequisites')
    for stage,folder in [('r24','r24-failed-provenance'),('r26','r26-failed-provenance')]:
        old_prefix = 'native-source'+('50' if stage=='r24' else '51')+'-project-'+stage
        old_terminal = json.loads(members['input/'+folder+'/'+old_prefix+'-terminal-process-status.json'])
        assert old_terminal['exit_code'] == 100 and old_terminal['state'] == 'failed'
    with tarfile.open(fileobj=io.BytesIO(members['input/source52-apply-input.tar.gz']),mode='r:gz') as tf:
        nested={}
        for member in tf.getmembers():
            safe(member.name)
            assert member.isfile() and member.name not in nested
            nested[member.name] = tf.extractfile(member).read()
        assert set(nested) == {'before/'+RUNTIME,'after/'+RUNTIME,'candidate.patch','delta-manifest.json','source52-manifest.json'}
        assert nested['source52-manifest.json'] == members['input/native-candidate-r28-source.json']
        assert nested['after/'+RUNTIME] == members['source/'+RUNTIME]
    assert pin(members['input/source52-apply-input.tar.gz']) == {'bytes':43267,'sha256':'9c7a414899bd05d1e70b9a6cbac64eef9dda552f8e56c904ee9f8e21ab37d6cb','git_blob':'eefc9ec94d7c5a0074eaa35788b3fbe670314420'}
    return checked


def inspect_literal_bindings(template, bound, values):
    """Undo only actual top-level literal values; do not import either runner."""
    source = bound.decode()
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1]+len(line))
    changes, seen = [], set()
    for node in ast.parse(source).body:
        if not isinstance(node,ast.Assign) or len(node.targets)!=1 or not isinstance(node.targets[0],ast.Name):
            continue
        key = node.targets[0].id
        if key not in values:
            continue
        assert ast.literal_eval(node.value) == values[key]
        begin = offsets[node.value.lineno-1]+node.value.col_offset
        end = offsets[node.value.end_lineno-1]+node.value.end_col_offset
        changes.append((begin,end))
        seen.add(key)
    assert seen == set(values)
    for begin,end in sorted(changes,reverse=True):
        source = source[:begin]+'None'+source[end:]
    assert source.encode() == template
    return {'literal_bindings':len(seen),'inverse_exact':True,'runner_imported_or_executed':False}


def supplemental_inputs(members):
    """Read exact reviewed preparations and closed export custody separately."""
    files = {}
    def take(path,destination):
        path = WORK/path
        assert path.is_file() and not path.is_symlink()
        files[destination] = (str(path),path.read_bytes())
        return files[destination][1]
    prep = WORK/'r28-export-preparation'
    handoff_raw = (prep/'HANDOFF-V2.json').read_bytes()
    handoff = json.loads(handoff_raw)
    assert pin(handoff_raw)['sha256'] == '5c691a566e9bde0d47bf6f9deb664c5bad5b585478ece6bd86dff4ef1ed81c10'
    assert len(handoff['files']) == handoff['file_count'] == 18
    for row in handoff['files']:
        raw = take(Path('r28-export-preparation')/row['path'],'export-preparation/'+row['path'])
        assert pin(raw) == {k:row[k] for k in ('bytes','sha256','git_blob')}
    take(Path('r28-export-preparation/HANDOFF-V2.json'),'export-preparation/HANDOFF-V2.json')
    bound_dirs = [('native-validation-results/r28-bound-input','gate-binding'),
                  ('native-validation-results/r28-export-bound-input','export-binding')]
    for source_dir,dest in bound_dirs:
        for path in sorted((WORK/source_dir).iterdir()):
            assert path.is_file()
            take(path.relative_to(WORK),dest+'/'+path.name)
    for name in ('ROOT-APPROVED-R28.py','ROOT-R28-LAUNCH-AUTHORIZATION.json'):
        take(Path('source52-preparation')/name,'root-gate-authorization/'+name)
    for path in sorted((WORK/'r28-export-root-review').iterdir()):
        assert path.is_file()
        take(path.relative_to(WORK),'root-export-authorization/'+path.name)
    for name in ('LOCAL-READBACK.json','CONTROLLER-REMOTE-PINS.json','CONTROLLER-PUBLICATION.json',
                 'local-readback-v1-key-mismatch.json','local-readback-v1-v2.patch','verify_and_bind_r29.py','verify_and_bind_r29-v2.py'):
        take(Path('native-validation-results/r28-closed-input')/name,'original-transfer-readback/'+name)
    gate_bound = files['gate-binding/native-run-r28-bound.py'][1]
    gate_final = files['gate-binding/native-run-r28.py'][1]
    gate_values = json.loads(files['gate-binding/ACTUAL-BINDINGS.json'][1])
    gate_template = files['export-preparation/references/native-run-r28-template.py'][1]
    gate_bind_readback = inspect_literal_bindings(gate_template,gate_bound,gate_values)
    assert gate_bound.replace(b'FROZEN = False',b'FROZEN = True',1) == gate_final
    assert gate_final == members['input/native-run-r28.py'] == files['root-gate-authorization/ROOT-APPROVED-R28.py'][1]
    gate_auth = json.loads(files['root-gate-authorization/ROOT-R28-LAUNCH-AUTHORIZATION.json'][1])
    assert gate_auth['source_tree'] == TREE and gate_auth['source_commit'] == COMMIT and gate_auth['full_source_paths'] == 195
    assert gate_auth['actual_binding_literals'] == gate_values and gate_auth['runner']['sha256'] == RUNNER_SHA
    export_bound = files['export-binding/export-r28-closed-bound.py'][1]
    export_final = files['export-binding/export-r28-closed.py'][1]
    export_values = json.loads(files['export-binding/ACTUAL-BINDINGS.json'][1])
    export_template = files['export-preparation/export-r28-closed-template-v2.py'][1]
    export_bind_readback = inspect_literal_bindings(export_template,export_bound,export_values)
    assert export_bound.replace(b'FROZEN = False',b'FROZEN = True',1) == export_final
    assert export_final == files['root-export-authorization/ROOT-APPROVED-EXPORT.py'][1]
    assert pin(export_final)['sha256'] == EXPORTER_SHA
    assert len(export_values['CLOSED_ORIGINAL_PINS']) == 26 and len(export_values['CONTROLLER_ORIGINAL_PINS']) == 5
    for name,value in export_values['CLOSED_ORIGINAL_PINS'].items():
        actual = pin(members['evidence/'+name])
        assert all(actual[k] == v for k,v in value.items())
    for name,value in export_values['CONTROLLER_ORIGINAL_PINS'].items():
        actual = pin(members['controller/'+name.removeprefix('r28-controller-closed-')])
        assert all(actual[k] == v for k,v in value.items())
    terminal_actual = pin(members['evidence/'+PREFIX+'-terminal-process-status.json'])
    assert all(terminal_actual[k] == v for k,v in export_values['TERMINAL_PIN'].items())
    v1 = files['export-preparation/export-r28-closed-template.py'][1]
    assert v1.replace(b"len(raw)==v['size']",b"len(raw)==v['next_offset']-v['offset'] and v['size']>=v['next_offset']",1) == export_template
    auth = json.loads(files['root-export-authorization/ROOT-LAUNCH-AUTHORIZATION.json'][1])
    assert auth['approved_exporter']['sha256'] == EXPORTER_SHA and auth['closed_gate_job'] == JOB
    assert auth['source_tree'] == TREE and auth['source_commit'] == COMMIT
    assert auth['unique_launch_key'] == 'cell-source52-r28-export-20261106-v1' and auth['outer_timeout_seconds'] == 180
    export_dir = WORK/'native-validation-results/r28-export-closed'
    local_raw = (export_dir/'LOCAL-READBACK.json').read_bytes()
    assert pin(local_raw)['sha256'] == 'ed9a2e9d816b758bd8703dac832764f2bf2efa22b35277bbb4045d2462e5d23d'
    local = json.loads(local_raw)
    assert len(local['files']) == 11
    for row in local['files']:
        raw = take(Path('native-validation-results/r28-export-closed')/row['path'],'export-custody/'+row['path'])
        assert pin(raw) == {k:row[k] for k in ('bytes','sha256','git_blob')}
    take(Path('native-validation-results/r28-export-closed/LOCAL-READBACK.json'),'export-custody/LOCAL-READBACK.json')
    export_terminal = json.loads(files['export-custody/controller/terminal-process-status.json'][1])
    natural_terminal(export_terminal,EXPORT_JOB,0)
    export_launch = json.loads(files['export-custody/controller/launch.json'][1])
    assert export_launch['job']['id'] == EXPORT_JOB and export_launch['job']['idempotency_key'] == auth['unique_launch_key']
    assert EXPORTER_SHA in export_launch['job']['args'][1]
    export_read = json.loads(files['export-custody/controller/process-read-000000.json'][1])
    for stream in ('stdout','stderr'):
        value = export_read[stream]
        raw = files['export-custody/controller/'+stream+'.log'][1]
        assert value['offset'] == 0 and value['next_offset'] == len(raw) and value['size'] >= len(raw)
        assert raw == bytes.fromhex(value['bytes_hex']) == value['text'].encode()
        assert export_terminal['log_bytes'][stream]['seen'] == export_terminal['log_bytes'][stream]['stored'] == len(raw)
    export_result = json.loads(files['export-custody/evidence/checkpoint-r28-export.json'][1])
    assert {k:export_result[k] for k in ('bytes','sha256','git_blob')} == ARCHIVE_PIN
    assert export_result['members'] == 295 and export_result['source_count'] == 195
    assert export_result['counts'] == {'PASS':1564,'FAIL':0,'TIMEOUT':0} and export_result['reported_skipped'] == 3
    assert export_result['source_commit'] == COMMIT and export_result['source_tree'] == TREE
    assert json.loads(files['export-custody/controller/stdout.log'][1]) == export_result
    for name in (PREFIX+'-closed-result-review.json',PREFIX+'-export-source-verification.json'):
        assert files['export-custody/evidence/'+name][1] == members['evidence/'+name]
    assert files['export-custody/evidence/failure-blocks-INDEX.json'][1] == members['failure-blocks/INDEX.json']
    return files,{'gate':gate_bind_readback,'exporter':export_bind_readback,'only_final_change_both':'FROZEN False to True',
                  'v1_to_v2_only_stream_size_semantics':True,'all26_original_pins_and5_controller_pins_verified':True,
                  'export_original_job':EXPORT_JOB,'export_original_exit':0,'export_not_a_new_rust_gate':True}


def prior_failure_transitions(keyed):
    transitions, originals = [], {}
    for stage,expected_count in [('r24',3),('r26',2)]:
        root = FORMAL/(stage+'-project-checkpoint')
        original = root/'original/failure-blocks'
        index_raw = (original/'INDEX.json').read_bytes()
        index = json.loads(index_raw)
        assert len(index['failures']) == expected_count and index['counts']['FAIL'] == expected_count
        prefix = 'native-source'+('50' if stage=='r24' else '51')+'-project-'+stage
        log_path = root/'original/evidence'/(prefix+'-tests.log.gz')
        log = gzip.decompress(log_path.read_bytes())
        assert pin(log) == index['log']
        originals[stage+'/INDEX.json'] = (str(original/'INDEX.json'),index_raw)
        for f in index['failures']:
            raw = (original/f['file']).read_bytes()
            assert raw == log[f['byte_offset']:f['end_byte_offset']]
            assert pin(raw) == {k:f[k] for k in ('bytes','sha256','git_blob')}
            now = keyed[(f['binary'],f['name'])]
            assert f['status'] == 'FAIL' and now['status'] == 'PASS'
            originals[stage+'/'+f['file']] = (str(original/f['file']),raw)
            transitions.append({'binary':f['binary'],'name':f['name'],
                                'before':{'stage':stage,'source_commit':index['source_commit'],'source_tree':index['source_tree'],
                                          'status':'FAIL','log':index['log'],'block':{'path':'prior-failures/'+stage+'/'+f['file'],**pin(raw)},
                                          'line':f['line'],'byte_offset':f['byte_offset'],'end_byte_offset':f['end_byte_offset']},
                                'r28':now})
    assert len(transitions) == 5
    return transitions,originals


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--closed',type=Path,default=WORK/'native-validation-results/r28-archive-closed')
    parser.add_argument('--unpacked',type=Path)
    parser.add_argument('--root-file',type=Path,action='append',default=[])
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    if args.verify_only:
        verify_sealed(args.output)
        return
    assert args.root_file, 'An actual root archive readback must exist before attachment closure.'
    unpacked=args.unpacked or args.closed/'original'
    archive_raw=(args.closed/ARCHIVE_NAME).read_bytes()
    assert pin(archive_raw)==ARCHIVE_PIN
    members,modes,index=archive_members(archive_raw,unpacked)
    source,source_rows=verify_sources(members,modes)
    phase_data,py,start,summary,rows,keyed,per_package,terminal,complete=verify_phases(members)
    controller_review=verify_controller(members,terminal)
    preconditions=verify_preconditions(members)
    supplements,binding_review=supplemental_inputs(members)
    transitions,prior_originals=prior_failure_transitions(keyed)
    root_originals={}
    for path in args.root_file:
        assert path.is_file() and not path.is_symlink() and path.name not in root_originals
        raw=path.read_bytes()
        json.loads(raw)
        root_originals[path.name]=(str(path),raw)
    categories=dict(Counter(p.split('/',1)[0] for p in members if p!='INDEX.json'))
    assert categories['source']==195 and categories['locks']==2 and categories['controller']==7 and categories['failure-blocks']==1

    # All substantive checks above finish before creating the new formal group.
    output=args.output
    output.mkdir(parents=True,exist_ok=True)
    mapping,gzip_records=[],[]
    dedup={}
    def attach(source_path,dest,raw,compress=True):
        raw_pin=pin(raw)
        if len(raw)>=32768 and raw_pin['sha256'] in dedup:
            old=dedup[raw_pin['sha256']]
            assert old['source_pin']==raw_pin
            mapping.append({'source':source_path,'source_pin':raw_pin,**{k:old[k] for k in ('destination','stored_pin','encoding')},
                            'same_original_bytes_reused':True})
            return old['destination']
        stored,encoding=raw,'identity'
        if compress and len(raw)>=65536 and not dest.endswith(('.gz','.tar')):
            raw.decode('utf-8')
            stored,dest,encoding=gz(raw),dest+'.gz','gzip-mtime-0'
            gzip_records.append({'path':dest,'stored':pin(stored),'uncompressed':raw_pin,'mtime':0,'roundtrip_exact':True})
        exact(output/dest,stored)
        row={'source':source_path,'source_pin':raw_pin,'destination':dest,'stored_pin':pin(stored),'encoding':encoding}
        mapping.append(row)
        if len(raw)>=32768:
            dedup[raw_pin['sha256']]=row
        return dest
    attach(str(args.closed/ARCHIVE_NAME),ARCHIVE_NAME,archive_raw,False)
    member_mapping=[]
    for name,raw in sorted(members.items()):
        record={'archive_member':name,**pin(raw),'archive_transport_mode':modes[name]}
        if name.startswith(('source/','locks/')):
            record.update({'storage':'unchanged_archive_member_only','archive':ARCHIVE_NAME})
        else:
            record.update({'storage':'archive_and_exact_attachment',
                           'destination':attach(str(unpacked/name),'original/'+name,raw)})
        member_mapping.append(record)
    for dest,(origin,raw) in sorted(supplements.items()):
        attach(origin,dest,raw)
    for dest,(origin,raw) in sorted(prior_originals.items()):
        attach(origin,'prior-failures/'+dest,raw)
    for name,(origin,raw) in sorted(root_originals.items()):
        attach(origin,'root-review/'+name,raw)
    reader_history=WORK/'r28-formal-preparation/reader-history'
    for path in sorted(reader_history.iterdir()):
        assert path.is_file()
        attach(str(path),'reader-preparation-history/'+path.name,path.read_bytes())
    attach(str(Path(__file__).resolve()),'verify_and_assemble.py',Path(__file__).read_bytes(),False)
    attach('derived:195-source-raw-sha-and-original-git-mode','readback/SOURCE-FILES.json',raw_json(source_rows))
    attach('derived:full-original-log-unique-ids','readback/UNIQUE-TEST-RESULTS.json',raw_json(rows))
    attach('derived:original-r24-r26-failure-blocks-to-source52-pass','readback/PRIOR-FAILURE-TRANSITIONS.json',raw_json({
        'schema':'hepta.r28-prior-failure-transitions.v1','source_commit':COMMIT,'source_tree':TREE,'transitions':transitions,
        'old_gate_failures_retained':True,'old_results_not_transferred_to_new_source':True}))
    attach('derived:full-controller-output-joining','readback/CONTROLLER-OUTPUT-READBACK.json',raw_json(controller_review))
    attach('derived:actual-bindings-and-v1-v2-inverse','readback/BOUND-AND-EXPORTER-READBACK.json',raw_json(binding_review))
    readback={
        'schema':'hepta.r28-independent-closed-readback.v1','classification':'ENGINEERING_FOUR_PACKAGE_GATE_PASS',
        'archive':ARCHIVE_PIN,'archive_members':295,'indexed_members':294,'archive_categories':categories,
        'all_regular_safe_members_and_all_index_hashes_modes_verified':True,'all_unpacked_bytes_equal_archive':True,
        'source_commit':COMMIT,'source_tree':TREE,'native_head':HEAD,'changed_paths':195,'rust_paths':181,'other_paths':14,
        'all_source_raw_sha_gitblob_verified':True,'source51_original194_rows_preserved':True,
        'source_git_modes':'Original manifest modes and native full guards retained separately from tar transport modes.',
        'offline_full_repository_tree_reconstructed_here':False,
        'source_tree_basis':'Actual manifest, all195 original raw files and native per-phase/export staged-tree guards; no new checkout claim.',
        'cargo_lock_sha256':CARGO_SHA,'bazel_lock_sha256':BAZEL_SHA,'precondition_pins_reverified':preconditions,
        'source50_lock_original_result_retained_not_rerun_for_source52':True,'original_runner':pin(members['input/native-run-r28.py']),
        'phases':phase_data,'python':py,'starting':start,'summary':summary,'unique_test_count':1564,
        'counts':summary['counts'],'per_package':per_package,'reported_skipped':3,'skip_identities_inferred':False,
        'reported_starting_binaries':start['binaries'],'unique_binaries_with_execution_rows':len({r['binary'] for r in rows}),
        'binary_count_boundary':'Starting roster count and binaries with actual result rows are distinct observations; no skipped identities inferred.',
        'all1564_original_binary_name_ids_exact_and_pass':True,'baseline_used_as_filter':False,
        'full_original_rows_exact_reproduction':True,'footer_rows_excluded':[],'failure_blocks':[],
        'prior_failure_transitions':transitions,'original_gate_terminal':{'job_id':JOB,'exit_code':0,'timed_out':False,'cancelled':False,
                                                                     'pin':pin(members['evidence/'+PREFIX+'-terminal-process-status.json'])},
        'controller_full_output_verified':controller_review,'binding_readback':binding_review,
        'export_only_terminal':{'job_id':EXPORT_JOB,'exit_code':0,'not_a_rust_gate':True},
        'whole_workspace_result':'SEPARATE_R29_NOT_REVIEWED_HERE','r29_activity_read':False,
        'fix_fmt_executed_by_r28_or_this_reader':False,'rust_rerun_by_reader':False,
        'historical_source52_launch_only_group_unchanged':True,'previous_r24_r26_failed_groups_unchanged':True,
        'free_bytes_after_boundary':'Original complete.json value is a shared filesystem sample; no task-specific resource consumption inferred.',
        'science':'HOLD','authority':'DENY_ALL','closure_gaps':[]}
    exact(output/'INDEPENDENT-READBACK.json',raw_json(readback))
    exact(output/'ORIGINAL-MEMBER-MAPPING.json',raw_json({'archive':{'path':ARCHIVE_NAME,**ARCHIVE_PIN},'total_regular_members':295,'members':member_mapping}))
    closure={'schema':'hepta.r28-project-attachment-closure.v1','status':'CLOSED_ORIGINAL_FOUR_PACKAGE_GATE_PASS',
        'source_commit':COMMIT,'source_tree':TREE,'native_head':HEAD,'source_count':195,'original_gate_job':JOB,
        'original_phase_exits':{'python-runner':0,'strict':0,'tests':0},'original_outer_exit':0,
        'python_tests':32,'python_reported_skipped':0,'counts':{'unique':1564,**summary['counts'],'reported_skipped':3},
        'per_package':per_package,'original_r26_two_failed_ids_now_pass':True,'original_r24_three_failed_ids_retained_pass':True,
        'archive':{'path':ARCHIVE_NAME,**ARCHIVE_PIN},'archive_members':295,'indexed_members':294,
        'independent_readback':{'path':'INDEPENDENT-READBACK.json',**pin((output/'INDEPENDENT-READBACK.json').read_bytes())},
        'root_readbacks':[{'path':'root-review/'+name,**pin(raw)} for name,(_,raw) in sorted(root_originals.items())],
        'source_storage':'All195 source files and raw dual locks remain in the exact archive, with complete per-member mapping; no duplicate source tree.',
        'full_logs_results_raw_receipts_resources_guards_terminal_preserved':True,
        'archive_export_exit_zero_is_separate_from_original_gate':True,'archive_export_job':EXPORT_JOB,
        'exporter_v1_never_executed_here':'Preserved preparation; only v2 actual bound/authorized exporter was executed by native.',
        'launch_only_historical_null_snapshots_unchanged':True,'failed_r24_r26_originals_unchanged':True,
        'whole_workspace':'PENDING_SEPARATE_R29_RESULT_NOT_INCLUDED','fix_fmt':'NOT_EXECUTED_BY_THIS_GATE_OR_READER',
        'science':'HOLD','authority':'DENY_ALL','closure_gaps':[],
        'limits':['Only the original four-package gate is qualified at this source identity.',
                  'Three reported skips are kept as a total; no skip IDs are invented.',
                  'Neither archive success nor mechanism tests establish scientific model efficacy.',
                  'Tar transport permissions are independent of Git file modes.',
                  'No new Rust, formatter, network query or Git subprocess was run by the local reader.']}
    exact(output/'CLOSURE.json',raw_json(closure))
    test_log_dest=next(r['destination'] for r in mapping if r['source']==str(unpacked/'evidence'/ (PREFIX+'-tests.log')))
    row_dest=next(r['destination'] for r in mapping if r['source']==str(unpacked/'evidence'/ (PREFIX+'-tests-test-results.json')))
    readme=f'''# r28 原四包门：完整闭合 PASS

**source52 的原 Python32、四包 strict、四包完整测试均自然退出 0；科学 HOLD、权限 DENY_ALL 不变。** 本组绑定 commit `{COMMIT}`、staged tree `{TREE}`、195 个变更路径（181 Rust＋14 other）。原生 HEAD 仍为 framework `{HEAD}`；已注册对象身份不冒充 checkout。

| 原阶段 | 原返回码 | 原进程总秒数 | 实际结果 |
| --- | ---: | ---: | --- |
| Python runner | 0 | {phase_data['python-runner']['elapsed_seconds']} | 32 项、0 skip、OK；unittest 自报 {py['summary']['seconds']} 秒 |
| 四包 strict | 0 | {phase_data['strict']['elapsed_seconds']} | 原 locked / -D warnings 命令及源码双锁守卫通过 |
| 四包完整测试 | 0 | {phase_data['tests']['elapsed_seconds']} | nextest {summary['seconds']} 秒；1564 unique 全 PASS，0 FAIL、0 TIMEOUT；另报 3 skipped |

| Package | PASS |
| --- | ---: |
| codex-cli | {per_package['codex-cli']['PASS']} |
| codex-exec-server | {per_package['codex-exec-server']['PASS']} |
| codex-network-proxy | {per_package['codex-network-proxy']['PASS']} |
| codex-external-agent-migration | {per_package['codex-external-agent-migration']['PASS']} |

完整原日志按 Summary 之前的 binary/name 唯一 ID 重解析，严格等于原 1564 个 baseline ID；baseline 仅在执行后验收，未作为 filter。完整日志见 [{PREFIX}-tests.log.gz]({test_log_dest})，原逐例结果见 [tests-test-results]({row_dest})。Starting 原报 49 binaries，实际结果行涉及 47 个 binary ID；两种统计分别保留，不据此推断哪些例被跳过。原 3 个 skip 仅保留原总口径，不构造逐例 SKIP 记录。

## 历史失败与本轮结果

原 r26 的两个 wildcard 测试，以及原 r24 的三个失败 ID，在本轮都有实际 PASS 行与耗时；[PRIOR-FAILURE-TRANSITIONS.json](readback/PRIOR-FAILURE-TRANSITIONS.json) 逐项绑定旧失败原块、旧源码和新结果。旧 r24/r26 的工程失败保留，source52 先前 apply/launch-only 快照中的 null 字段没有被追写。

## 原件和复算边界

- [CLOSURE.json](CLOSURE.json) 与 [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json) 是本组新读回。
- [{ARCHIVE_NAME}]({ARCHIVE_NAME}) 原样保留 295 regular 成员、294 条 INDEX，包括完整 195 源码、原双锁、26 gate 原件＋terminal、5 controller 原件、完整 runner、baseline、apply/lock 前置和原始错误历史。源码只保存在 archive，不另复制源码树。
- [ORIGINAL-MEMBER-MAPPING.json](ORIGINAL-MEMBER-MAPPING.json) 覆盖全部成员。大 UTF-8 文本用 mtime=0 gzip 精确保留，相同大原字节可映射到一份附件；所有源与目标 pins 在 [SOURCE-DESTINATION-MAPPING.json](SOURCE-DESTINATION-MAPPING.json)。
- gate controller 的 stdout 为 8309 B，stderr 为 0 B。原分块 size 是读取时总流长度，chunk 长度按 next_offset−offset 核验；[CONTROLLER-OUTPUT-READBACK.json](readback/CONTROLLER-OUTPUT-READBACK.json) 保存连续性、text/hex 和最终 seen/stored 证明。
- export-preparation/ 保留未执行的 v1、v2 和单点修正读回；root-gate-authorization/、gate-binding/、root-export-authorization/、export-binding/ 保留原授权和实际绑定。唯一 exporter `{EXPORT_JOB}` 的自然 0 只表示归档成功；原测试门为独立 `{JOB}`。
- 源码模式按原 manifest 的 Git mode 绑定；tar mode 是传输权限。完整 Git 仓库离线重建不属于这份新 reader 的声明范围，当前树身份来自原 manifest 和 native 多阶段完整守卫。

本组不读取 r29 活动内容、不提供默认工作区或最终 fix/fmt 的通过结论；没有新 Rust、format、metadata 或 native 执行。共享文件系统 free_bytes_after 原样保留，不折算成单任务资源消耗。测试机制通过不等于真实模型效果、retention 或科学资格通过。

纯本地附件复核：`python3 verify_and_assemble.py --verify-only --output <本目录>`。
'''
    exact(output/'README.md',readme.encode())
    exact(output/'SOURCE-DESTINATION-MAPPING.json',raw_json({'schema':'hepta.r28-attachment-mapping.v1','files':mapping}))
    exact(output/'GZIP-ROUNDTRIP.json',raw_json({'schema':'hepta.deterministic-gzip-readback.v1','files':gzip_records}))
    binaries=[]
    for path in sorted(output.rglob('*')):
        if not path.is_file() or not path.name.endswith('.gz'):
            continue
        raw=path.read_bytes()
        value={'path':str(path.relative_to(output)),**pin(raw),'original_bytes_unchanged':path.name.endswith('.tar.gz')}
        value['reuse_known_git_blob']=pin(raw)['git_blob'] in {ARCHIVE_PIN['git_blob'],'eefc9ec94d7c5a0074eaa35788b3fbe670314420'}
        value['git_upload_performed_here']=False
        binaries.append(value)
    exact(output/'BINARY-PLAN.json',raw_json({'schema':'hepta.r28-attachment-binary-plan.v1','files':binaries,'upload_owner':'root','git_upload_performed_here':False}))
    final_files=[{'path':str(p.relative_to(output)),**pin(p.read_bytes())} for p in sorted(output.rglob('*')) if p.is_file() and p.name!='ATTACHMENT-MANIFEST.json']
    exact(output/'ATTACHMENT-MANIFEST.json',raw_json({'schema':'hepta.r28-project-attachment-manifest.v1','source_commit':COMMIT,'source_tree':TREE,
         'classification':'ORIGINAL_FOUR_PACKAGE_GATE_PASS','files':final_files,'file_count_excluding_manifest':len(final_files),
         'stored_bytes_excluding_manifest':sum(v['bytes'] for v in final_files)}))
    verify_sealed(output)
    print(json.dumps({'closure':pin((output/'CLOSURE.json').read_bytes()),'independent':pin((output/'INDEPENDENT-READBACK.json').read_bytes()),
          'mapping_count':len(mapping),'binary_files':len(binaries),'archive_members':295,'source_files':195,
          'counts':summary['counts'],'reported_skipped':3,'rust_rerun':False},indent=2))


if __name__=='__main__':
    assert __debug__, 'Do not disable assertions in this verification reader.'
    main()
