#!/usr/bin/env python3
"""Pure local closed-r29 archive reader and create-only formal attachment assembler.

No subprocess, network, Git, Cargo, metadata, Rust or formatter invocation.
Actual archive pins and closed supplemental originals must be supplied after
natural termination. An unbound input template cannot create formal evidence.
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
OUTPUT = FORMAL / 'r29-workspace-checkpoint'
ARCHIVE_NAME = 'checkpoint-r29-closed.tar.gz'
COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
PREFIX = 'native-workspace-r29'
JOB = '1a1b1f83e4b-fc05-7bcd'
SOURCE_SHA = '3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898'
SOURCE_NAME = 'native-candidate-r28-source.json'
RUNNER_SHA = '26bb2c31806895b19410f290e1f20232ee3be2dbe09321e081857dddefac1fa2'
R28_PREFIX = 'native-source52-project-r28'
R28_JOB = '1a1b1e9bee0-fc05-7b7c'
R28_RUNNER_SHA = 'a7b64eb8ff8ec2b5bc75ae836e3ff423ce31ee86d5c4daf64b7543a8fa7aae9e'
CARGO_SHA = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
BAZEL_SHA = 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'
RUNTIME = 'codex-rs/network-proxy/src/runtime.rs'
R28_BASELINE_SHA = '6feba9a285f77f16fc1d34710d2737eae78a4ba3be74affd40f5703bc8ce405e'
COMMAND = ['just','test','--locked','--retries','0']
METADATA_COMMAND = ['cargo','metadata','--locked','--no-deps','--format-version','1']
R28_PACKAGES = ['codex-cli','codex-exec-server','codex-network-proxy','codex-external-agent-migration']
ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
RESULT = re.compile(rb'^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+?)\s*$')
START = re.compile(rb'^\s*Starting ([0-9]+) tests?\b')
SUMMARY = re.compile(rb'^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$')


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


def parse_workspace(raw,workspace_names):
    """Independent byte-offset parser. No expected current test count is set."""
    starts,summaries,all_rows=[],[],[]
    for number,offset,line in original_lines(raw):
        if match:=START.match(line):
            starts.append({'line':number,'byte_offset':offset,'text':line.decode('utf-8','replace'),
                           'announced_tests':int(match[1])})
        if match:=SUMMARY.fullmatch(line):
            tail=match[3]
            values={label.decode():int(n) for n,label in re.findall(rb'\b([0-9]+) (passed|failed|timed out|skipped)\b',tail)}
            summaries.append({'line':number,'byte_offset':offset,'text':line.decode('utf-8','replace'),
                              'seconds':float(match[1]),'tests_run':int(match[2]),
                              'counts':{'PASS':values.get('passed',0),'FAIL':values.get('failed',0),'TIMEOUT':values.get('timed out',0)},
                              'reported_skipped':values.get('skipped',0)})
        if match:=RESULT.fullmatch(line):
            all_rows.append({'status':match[1].decode(),'seconds':float(match[2]),
                             'binary':match[3].decode('utf-8','replace'),'name':match[4].decode('utf-8','replace'),
                             'line':number,'byte_offset':offset})
    start=starts[0] if len(starts)==1 else None
    summary=summaries[0] if len(summaries)==1 else None
    rows=[r for r in all_rows if start and r['line']>start['line'] and (summary is None or r['line']<summary['line'])]
    footer=[r for r in all_rows if summary and r['line']>summary['line']]
    keyed={(r['binary'],r['name']):r for r in rows}
    observed={s:sum(r['status']==s for r in rows) for s in ('PASS','FAIL','TIMEOUT')}
    unknown=sorted({r['binary'].split('::',1)[0] for r in rows}-set(workspace_names))
    complete=bool(start and summary and start['line']<summary['line'] and rows
                  and len(rows)==len(keyed)==start['announced_tests']==summary['tests_run']
                  and observed==summary['counts'] and not unknown)
    summary_record=None if summary is None else {k:summary[k] for k in ('line','byte_offset','text','seconds','tests_run')}
    review={
        'schema':'hepta.source52-workspace-closed-readback.v1','source_tree':TREE,'source_commit':COMMIT,'log':pin(raw),
        'starting_lines':starts,'summary':summary_record,'summary_line_count':len(summaries),
        'nextest_started':bool(starts),'complete_execution_accounting':complete,
        'execution_rows_observed':len(rows),'unique_binary_name_ids_observed':len(keyed),
        'terminal_unique_test_count':len(keyed) if complete else None,
        'terminal_counts':observed if complete else None,
        'observed_counts_not_terminal_without_complete_summary':observed,
        'summary_counts':None if summary is None else summary['counts'],
        'reported_skipped':None if summary is None else summary['reported_skipped'],
        'skip_identities_inferred':False,'duplicate_execution_ids':len(rows)!=len(keyed),
        'footer_rows_excluded':footer,'unknown_workspace_packages':unknown,
        'no_execution_claim_from_compile_failure':True,'test_ids_used_as_filter':False,
        'pass':complete and observed['FAIL']==observed['TIMEOUT']==0}
    if complete:
        failures={(r['binary'],r['name'],r['status']) for r in rows if r['status']!='PASS'}
        assert len(footer)==len(failures)
        assert {(r['binary'],r['name'],r['status']) for r in footer}==failures
    if not starts:
        assert not rows and review['terminal_counts'] is None and review['terminal_unique_test_count'] is None
    return rows,review


def check_pin(raw,value):
    observed=pin(raw)
    assert {'bytes','sha256'}<=set(value)
    assert all(observed[k]==value[k] for k in ('bytes','sha256'))
    if 'git_blob' in value: assert observed['git_blob']==value['git_blob']
    return observed


def validate_inputs(config):
    assert config['schema']=='hepta.r29-local-attachment-inputs.v1'
    assert config['binding_state']=='ACTUAL_CLOSED_ARCHIVE_BOUND','Await real closed archive; do not assemble from the template.'
    assert config['source_commit']==COMMIT and config['source_tree']==TREE and config['gate_job_id']==JOB
    for key in ('archive','closed_directory','unpacked_directory','root_readbacks','supplemental_originals'):
        assert config[key] is not None,'Actual closed input remains unbound: '+key
    archive=config['archive']
    assert isinstance(archive['bytes'],int) and archive['bytes']>0
    assert re.fullmatch('[0-9a-f]{64}',archive['sha256']) and re.fullmatch('[0-9a-f]{40}',archive['git_blob'])
    assert isinstance(archive['members'],int) and archive['members']>195
    assert archive['indexed_members']==archive['members']-1
    assert config['root_readbacks'] and config['supplemental_originals']
    for row in config['root_readbacks']+config['supplemental_originals']:
        safe(row['destination'])
        assert {'path','bytes','sha256'}<=set(row)
    assert config['export_original_job_id'] and config['export_terminal_destination']


def read_archive(config):
    path=WORK/config['closed_directory']/ARCHIVE_NAME
    raw=path.read_bytes()
    check_pin(raw,config['archive'])
    unpacked=WORK/config['unpacked_directory']
    members,modes={},{}
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tar:
        for member in tar.getmembers():
            safe(member.name)
            assert member.isfile() and not member.issym() and not member.islnk() and member.name not in members
            data=tar.extractfile(member).read()
            assert len(data)==member.size
            local=unpacked/member.name
            assert local.is_file() and not local.is_symlink() and local.read_bytes()==data
            members[member.name],modes[member.name]=data,member.mode
    assert len(members)==config['archive']['members']
    assert {str(p.relative_to(unpacked)) for p in unpacked.rglob('*') if p.is_file()}==set(members)
    index=json.loads(members['INDEX.json'])
    assert index['schema']=='hepta.source52-workspace-closed-index.v1'
    assert index['source_commit']==COMMIT and index['source_tree']==TREE and index['source_count']==195
    rows={r['path']:r for r in index['files']}
    assert len(rows)==len(index['files'])==config['archive']['indexed_members']
    assert set(rows)==set(members)-{'INDEX.json'}
    for name,row in rows.items():
        assert pin(members[name])=={k:row[k] for k in ('bytes','sha256','git_blob')}
        assert modes[name]==row['mode']
    return raw,members,modes,index


def verify_metadata(members):
    e=lambda suffix:members['evidence/'+PREFIX+suffix]
    j=lambda suffix:json.loads(e(suffix))
    raw,metadata=e('-metadata.json'),j('-metadata.json')
    receipt,process=j('-metadata-receipt.json'),j('-metadata-raw-process-result.json')
    for value in (receipt,process):
        assert value['source_commit']==COMMIT and value['source_tree']==TREE and value['command']==METADATA_COMMAND
        assert value['exit_code']==0 and value['cwd']=='/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs'
    for key in ('source_commit','source_tree','command','cwd','start_unix','end_unix','exit_code'):
        assert receipt[key]==process[key]
    assert process['phase']=='workspace-metadata' and process['resources_not_collected_for_read_only_metadata'] is True
    assert abs(receipt['elapsed_seconds']-(receipt['end_unix']-receipt['start_unix']))<1e-6
    assert receipt['raw_process_result']=={'path':PREFIX+'-metadata-raw-process-result.json',**pin(e('-metadata-raw-process-result.json'))}
    assert receipt['stdout']==pin(raw) and receipt['stderr']==pin(e('-metadata-stderr.log'))
    assert receipt['source_postguard']=={'path':PREFIX+'-metadata-source-post-verification.json',**pin(e('-metadata-source-post-verification.json'))}
    assert receipt['source_guards_pass'] is True
    check_recorded_guard(j('-metadata-source-post-verification.json'))
    assert metadata['workspace_root']=='/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs'
    assert metadata['target_directory']=='/home/alex/work/hepta-cell-unified-20261106-a/target'
    ids,defaults=metadata['workspace_members'],metadata['workspace_default_members']
    packages={p['id']:p for p in metadata['packages']}
    assert len(ids)==len(set(ids))==len(defaults)==len(set(defaults))==193 and set(ids)==set(defaults)
    assert len(packages)==len(metadata['packages']) and set(ids)<=set(packages)
    scope=j('-scope.json')
    expected={'schema':'hepta.source52-current-default-workspace-scope.v1','source_tree':TREE,'source_commit':COMMIT,
              'metadata_command':METADATA_COMMAND,'metadata':{'path':PREFIX+'-metadata.json',**pin(raw)},
              'metadata_generated_on_current_source':True,'old_metadata_reused_as_current':False,
              'workspace_root':metadata['workspace_root'],'target_directory':metadata['target_directory'],
              'workspace_member_count':193,'workspace_default_member_count':193,
              'workspace_members':[{'id':v,'name':packages[v]['name'],'manifest_path':packages[v]['manifest_path']} for v in ids],
              'workspace_default_members':[{'id':v,'name':packages[v]['name']} for v in defaults],
              'command':COMMAND,'features':'unchanged_defaults','filters':'no_additions',
              'all_platforms_features_external_services_qualified':False}
    assert scope==expected
    return {'metadata':pin(raw),'scope':pin(e('-scope.json')),'receipt':pin(e('-metadata-receipt.json')),
            'raw':pin(e('-metadata-raw-process-result.json')),'exit_code':0,'elapsed_seconds':receipt['elapsed_seconds'],
            'workspace_member_count':193,'workspace_default_member_count':193,'exact_default_member_ids_verified':True},scope,receipt


def verify_controller(members,terminal):
    names=[name.removeprefix('controller/') for name in members if name.startswith('controller/')
           and name not in ('controller/original-stdout.txt','controller/original-stderr.txt')]
    assert {'launch.json','terminal-process-status.json'}<=set(names)
    assert all(name in ('launch.json','terminal-process-status.json') or re.fullmatch(r'read-[0-9]+\.json',name) for name in names)
    controller={name:json.loads(members['controller/'+name]) for name in names}
    assert members['controller/terminal-process-status.json']==members['evidence/'+PREFIX+'-terminal-process-status.json']
    launch=controller['launch.json']
    assert launch['job']['id']==JOB and launch['job']['launch_state']=='launched' and launch['launch']['ok'] is True
    assert RUNNER_SHA in launch['job']['args'][1]
    streams={}
    for stream in ('stdout','stderr'):
        chunks=[]
        for name,value in controller.items():
            if not name.startswith('read-'):continue
            assert value['job_id']==JOB
            item=value[stream];raw=bytes.fromhex(item['bytes_hex'])
            assert raw==item['text'].encode() and len(raw)==item['next_offset']-item['offset']
            assert item['size']>=item['next_offset']
            chunks.append((item['offset'],raw,name,item['next_offset'],item['size']))
        cursor,parts,details=0,[],[]
        for offset,raw,name,end,size in sorted(chunks,key=lambda v:(v[0],v[3],v[2])):
            if raw:
                assert offset==cursor,'Controller gap or overlap'
                cursor+=len(raw);parts.append(raw)
            else:assert offset<=cursor
            details.append({'path':'controller/'+name,'offset':offset,'next_offset':end,'total_stream_size_at_read':size,'chunk':pin(raw)})
        data=b''.join(parts)
        assert terminal['log_bytes'][stream]['seen']==terminal['log_bytes'][stream]['stored']==len(data)
        assert data==members['controller/original-'+stream+'.txt']
        streams[stream]={'joined':pin(data),'chunks':details}
    return {'original_count':len(names),'streams':streams,'all_offsets_text_hex_and_terminal_bytes_verified':True,
            'reported_size_is_total_stream_not_chunk_length':True}


def verify_workspace_phase(members,scope,metadata_receipt):
    e=lambda suffix:members['evidence/'+PREFIX+suffix]
    j=lambda suffix:json.loads(e(suffix))
    process,receipt=j('-tests-raw-process-result.json'),j('-tests-receipt.json')
    terminal=j('-terminal-process-status.json')
    raw_rc,effective=process['exit_code'],receipt['effective_exit_code']
    assert isinstance(raw_rc,int) and isinstance(effective,int)
    for value in (process,receipt):
        assert value['source_commit']==COMMIT and value['source_tree']==TREE and value['phase']=='workspace-tests'
        assert value['command']==COMMAND and value['cwd']=='/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs'
    for key in ('source_commit','source_tree','phase','command','cwd','start_unix','end_unix','exit_code'):
        assert process[key]==receipt[key]
    if raw_rc!=0:assert effective==raw_rc
    assert receipt['phase_pass'] is (effective==0)
    natural_terminal(terminal,JOB,effective)
    assert terminal['at_unix_ms']/1000>=receipt['end_unix']>=receipt['start_unix']>=metadata_receipt['end_unix']
    assert abs(receipt['elapsed_seconds']-(receipt['end_unix']-receipt['start_unix']))<1e-6
    def pointer(value,name):assert value=={'path':name,**pin(members['evidence/'+name])}
    pointer(receipt['raw_process_result'],PREFIX+'-tests-raw-process-result.json')
    assert receipt['log_sha256']==pin(e('-tests.log'))['sha256'] and receipt['resources_sha256']==pin(e('-tests-resources.txt'))['sha256']
    assert re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$',e('-tests-resources.txt'),re.M)==[str(raw_rc).encode()]
    assert receipt['source_manifest']==SOURCE_NAME and receipt['source_manifest_sha256']==SOURCE_SHA and receipt['source_guards_pass'] is True
    pointer(receipt['source_preguard'],PREFIX+'-tests-source-pre-verification.json')
    pointer(receipt['source_postguard'],PREFIX+'-source-post-test-verification.json')
    check_recorded_guard(j('-tests-source-pre-verification.json'))
    post=j('-source-post-test-verification.json');check_recorded_guard(post)
    assert post['phase']=='workspace-tests' and post['gate_exit_code']==raw_rc
    pointer(receipt['scope'],PREFIX+'-scope.json')
    assert receipt['test_scope']=='original_default_workspace' and receipt['packages_argument'] is None
    assert receipt['workspace_member_count']==receipt['workspace_default_member_count']==193
    assert receipt['retries']==0 and receipt['filters']=='no_additions' and receipt['features']=='unchanged_defaults'
    assert receipt['fix_fmt_executed'] is False and receipt['outer_timeout_seconds_contract']==9600
    rows,review=parse_workspace(e('-tests.log'),{p['name'] for p in scope['workspace_members']})
    if 'evidence/'+PREFIX+'-result-review.json' in members:
        assert review==j('-result-review.json')
    if 'evidence/'+PREFIX+'-test-results.json' in members:
        assert rows==j('-test-results.json')
    assert rows==j('-closed-test-results.json')
    if receipt['acceptance_readback'] is not None:pointer(receipt['acceptance_readback'],PREFIX+'-result-review.json')
    if effective==0:
        assert raw_rc==0 and review['pass'] is True and receipt['issues']==[]
        assert 'evidence/'+PREFIX+'-incomplete.json' not in members
        completion=j('-complete.json')
        assert completion['source_commit']==COMMIT and completion['source_tree']==TREE
        assert completion['source_manifest']==SOURCE_NAME and completion['source_manifest_sha256']==SOURCE_SHA
        assert completion['workspace_exit']==completion['effective_exit_code']==0 and completion['source_guards_pass'] is True
        assert completion['command']==COMMAND and completion['workspace_member_count']==completion['workspace_default_member_count']==193
        assert completion['cargo_lock_sha256']==CARGO_SHA and completion['bazel_lock_sha256']==BAZEL_SHA
        assert completion['unique_test_count']==review['terminal_unique_test_count'] and completion['counts']==review['terminal_counts']
        assert completion['reported_skipped']==review['reported_skipped'] and completion['fix_fmt_executed'] is False
        assert completion['all_platforms_features_external_services_qualified'] is False
        pointer(completion['receipt'],PREFIX+'-tests-receipt.json');pointer(completion['readback'],PREFIX+'-result-review.json')
        pointer(completion['scope'],PREFIX+'-scope.json')
    else:
        assert 'evidence/'+PREFIX+'-complete.json' not in members
        completion=j('-incomplete.json')
        assert completion['source_commit']==COMMIT and completion['source_tree']==TREE
        assert completion['original_exit_code']==raw_rc and completion['effective_exit_code']==effective
        assert completion['fix_fmt_executed'] is False and completion['no_automatic_retry'] is True and completion['source_retained'] is True
        assert completion['terminal_counts']==review['terminal_counts'] and completion['nextest_started']==review['nextest_started']
        pointer(completion['receipt'],PREFIX+'-tests-receipt.json')
    failures=json.loads(members['failure-blocks/INDEX.json'])
    assert failures['source_commit']==COMMIT and failures['source_tree']==TREE
    assert failures['original_outer_exit']==failures['effective_workspace_exit']==effective and failures['original_workspace_exit']==raw_rc
    assert failures['complete_execution_accounting']==review['complete_execution_accounting']
    assert failures['counts']==review['terminal_counts'] and failures['reported_skipped']==review['reported_skipped']
    assert failures['nextest_started']==review['nextest_started'] and failures['skip_identities_inferred'] is False
    bad=[r for r in rows if r['status']!='PASS']
    assert len(failures['failures'])==len(bad)
    positions={(r['binary'],r['name'],r['byte_offset']):i for i,r in enumerate(rows)}
    for row,block in zip(bad,failures['failures']):
        assert all(block[k]==v for k,v in row.items())
        at=positions[(row['binary'],row['name'],row['byte_offset'])]
        end=rows[at+1]['byte_offset'] if at+1<len(rows) else (review['summary']['byte_offset'] if review['summary'] else len(e('-tests.log')))
        raw=members['failure-blocks/'+block['file']]
        assert block['end_byte_offset']==end and raw==e('-tests.log')[row['byte_offset']:end]
        assert pin(raw)=={k:block[k] for k in ('bytes','sha256','git_blob')}
    assert {p for p in members if p.startswith('failure-blocks/')}=={'failure-blocks/INDEX.json'}|{'failure-blocks/'+f['file'] for f in failures['failures']}
    closed=j('-closed-result-review.json')
    assert closed['original_workspace_review']==review and closed['original_workspace_exit']==raw_rc
    assert closed['effective_workspace_exit']==closed['outer_original_exit']==effective
    assert closed['engineering_gate']==('PASS' if effective==0 else 'FAIL')
    assert closed['test_execution_counts']==review['terminal_counts'] and closed['reported_skipped']==review['reported_skipped']
    assert closed['failure_blocks']==failures['failures'] and closed['complete_execution_accounting']==review['complete_execution_accounting']
    assert closed['nextest_started']==review['nextest_started'] and closed['all_platforms_features_external_services_qualified'] is False
    proof=j('-export-source-verification.json')
    assert proof['source_commit']==COMMIT and proof['source_tree']==TREE and proof['source_count']==195
    assert proof['source_guard_before']==proof['source_guard_after'] and proof['all195_raw_sha_gitblob_gitmode_verified'] is True
    assert proof['workspace_raw_result']==pin(e('-tests-raw-process-result.json')) and proof['workspace_receipt']==pin(e('-tests-receipt.json'))
    assert proof['original_workspace_exit']==raw_rc and proof['effective_workspace_exit']==proof['original_outer_exit']==effective
    assert proof['original_test_counts']==review['terminal_counts'] and proof['original_reported_skipped']==review['reported_skipped']
    assert proof['fresh_metadata']==pin(e('-metadata.json')) and proof['workspace_scope']==pin(e('-scope.json'))
    for key in ('export_modifies_source','rust_rerun','metadata_rerun','fix_fmt_executed_by_exporter'):assert proof[key] is False
    return {'original_exit':raw_rc,'effective_exit':effective,'outer_exit':effective,'elapsed_seconds':receipt['elapsed_seconds'],
            'command':COMMAND,'raw':pin(e('-tests-raw-process-result.json')),'receipt':pin(e('-tests-receipt.json')),
            'log':pin(e('-tests.log')),'resources':pin(e('-tests-resources.txt')),'source_guards_pass':True},rows,review,failures,terminal


def verify_prerequisites(members):
    pre=json.loads(members['evidence/'+PREFIX+'-preconditions.json'])
    env=json.loads(members['evidence/'+PREFIX+'-environment.json'])
    assert pre['source_commit']==env['source_commit']==COMMIT and pre['source_tree']==env['source_tree']==TREE
    assert pre['actual_changed_file_count']==195 and pre['workspace_test_command']==COMMAND
    assert pre['source_manifest']=={'path':SOURCE_NAME,**pin(members['input/'+SOURCE_NAME])}
    for key in ('patch_application_performed','lock_update_performed','source52_bazel_lock_update_executed','fix_fmt_executed'):
        assert pre[key] is False
    check_recorded_guard(json.loads(members['evidence/'+PREFIX+'-source-pre-verification.json']))
    assert pre['initial_source_guard']=={'path':PREFIX+'-source-pre-verification.json',**pin(members['evidence/'+PREFIX+'-source-pre-verification.json'])}
    assert env['source_manifest']==SOURCE_NAME and env['source_manifest_sha256']==SOURCE_SHA
    for key in ('original_default_workspace_selection','fresh_current_source_metadata_required','test_deadlines_features_filters_retries_unchanged'):
        assert env[key] is True
    assert env['sandbox_or_network_protection_environment_overridden'] is False and env['outer_timeout_seconds_contract']==9600
    expected_selection={'RUSTUP_TOOLCHAIN':'1.96.0','CARGO_BUILD_JOBS':'2','CARGO_TARGET_DIR':'/home/alex/work/hepta-cell-unified-20261106-a/target',
                        'NEXTEST_TEST_THREADS':'2','CARGO_PROFILE_TEST_DEBUG':'0','CARGO_PROFILE_DEV_DEBUG':'0',
                        'NEXTEST_PROFILE':None,'HEPTA_NEXTTEST_FULL_METADATA':None,'CARGO_INCREMENTAL':None,
                        'CARGO_BUILD_TARGET':None,'RUSTFLAGS':None,'PYTHONOPTIMIZE':None}
    assert all(env['selection'][k]==value for k,value in expected_selection.items())
    proof=pre['r28_closed_gate_readback']
    assert proof['source_commit']==COMMIT and proof['source_tree']==TREE and proof['same_source_all_three_phases_and_outer_pass'] is True
    assert proof['python_tests']==32 and proof['python_skipped']==0 and proof['old_four_package_ids_recomputed_from_full_log']==1564
    assert len(proof['originals'])==len({r['path'] for r in proof['originals']})==26
    originals={}
    for row in proof['originals']:
        raw=members['input/r28-prerequisites/'+row['path']]
        check_pin(raw,row);originals[row['path']]=raw
    terminal_raw=members['input/r28-prerequisites/'+proof['outer_terminal']['path']]
    check_pin(terminal_raw,proof['outer_terminal'])
    terminal=json.loads(terminal_raw);natural_terminal(terminal,R28_JOB,0)
    j=lambda suffix:json.loads(originals[R28_PREFIX+suffix])
    e=lambda suffix:originals[R28_PREFIX+suffix]
    complete=j('-complete.json')
    assert complete['source_commit']==COMMIT and complete['source_tree']==TREE
    assert complete['python_exit']==complete['strict_exit']==complete['tests_exit']==0 and complete['source_guards_pass'] is True
    assert complete['all_old_ids_observed_pass'] is True and complete['required_old_ids']==1564
    project_pre=j('-preconditions.json')
    baseline_raw=members['input/baseline/'+project_pre['baseline']['path']]
    check_pin(baseline_raw,project_pre['baseline'])
    assert pin(baseline_raw)['sha256']==R28_BASELINE_SHA
    baseline=json.loads(baseline_raw)
    expected_ids={(r['binary'],r['name']) for r in baseline['test_ids']}
    assert len(expected_ids)==len(baseline['test_ids'])==1564
    package_args=[x for p in R28_PACKAGES for x in ('-p',p)]
    commands={'python-runner':['python3','-m','unittest','discover','-s','scripts','-p','test_run_nextest*.py','-v'],
              'strict':['just','clippy','--locked',*package_args,'--','-D','warnings'],
              'tests':['just','test','--locked',*package_args,'--retries','0']}
    receipts=[];phases={};last_end=None
    for phase,command in commands.items():
        process,receipt=j('-'+phase+'-raw-process-result.json'),j('-'+phase+'-receipt.json')
        for value in (process,receipt):
            assert value['source_commit']==COMMIT and value['source_tree']==TREE and value['phase']==phase
            assert value['command']==command and value['exit_code']==0
        for key in ('source_commit','source_tree','phase','command','cwd','start_unix','end_unix','exit_code'):
            assert process[key]==receipt[key]
        assert receipt['effective_exit_code']==0 and receipt['phase_pass'] is True and receipt['issues']==[]
        assert receipt['raw_process_result']=={'path':R28_PREFIX+'-'+phase+'-raw-process-result.json',**pin(e('-'+phase+'-raw-process-result.json'))}
        assert receipt['log_sha256']==pin(e('-'+phase+'.log'))['sha256']
        assert receipt['resources_sha256']==pin(e('-'+phase+'-resources.txt'))['sha256']
        assert re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$',e('-'+phase+'-resources.txt'),re.M)==[b'0']
        check_recorded_guard(j('-'+phase+'-source-pre-verification.json'))
        check_recorded_guard(j('-'+phase+'-source-post-verification.json'),phase)
        assert receipt['source_postguard']=={'path':R28_PREFIX+'-'+phase+'-source-post-verification.json',**pin(e('-'+phase+'-source-post-verification.json'))}
        assert receipt['source_manifest_sha256']==SOURCE_SHA and receipt['source_guards_pass'] is True
        assert receipt['baseline_used_as_filter'] is False and receipt['fix_fmt_executed'] is False
        assert last_end is None or receipt['start_unix']>=last_end
        assert receipt['end_unix']>=receipt['start_unix'] and abs(receipt['elapsed_seconds']-(receipt['end_unix']-receipt['start_unix']))<1e-6
        last_end=receipt['end_unix']
        receipts.append({'path':R28_PREFIX+'-'+phase+'-receipt.json',**pin(e('-'+phase+'-receipt.json'))})
        phases[phase]={'raw':pin(e('-'+phase+'-raw-process-result.json')),'receipt':pin(e('-'+phase+'-receipt.json')),
                       'log':pin(e('-'+phase+'.log')),'resources':pin(e('-'+phase+'-resources.txt')),'original_exit':0,'effective_exit':0}
    assert complete['phase_receipts']==receipts and terminal['at_unix_ms']/1000>=last_end
    py=parse_python(e('-python-runner.log'))
    rows,review=parse_workspace(e('-tests.log'),R28_PACKAGES)
    assert review['pass'] is True and review['terminal_unique_test_count']==1564 and review['reported_skipped']==3
    assert review['terminal_counts']=={'PASS':1564,'FAIL':0,'TIMEOUT':0}
    assert {(r['binary'],r['name']) for r in rows}==expected_ids
    assert rows==j('-tests-test-results.json')
    original_review=j('-tests-result-review.json')
    assert original_review['counts']==review['terminal_counts'] and original_review['pass'] is True
    assert original_review['log']==pin(e('-tests.log')) and original_review['reported_skipped']==3
    assert py['tests']==32 and py['skipped']==0 and j('-python-runner-result-review.json')['pass'] is True
    check_recorded_guard(j('-source-final-verification.json'))
    assert pin(members['input/native-run-r28.py'])['sha256']==R28_RUNNER_SHA
    assert pin(members['input/native-run-r29.py'])['sha256']==RUNNER_SHA

    checked=[]
    def original(value,directory):
        path=directory+'/'+value['path'];check_pin(members[path],value)
        checked.append({'archive_member':path,**pin(members[path])})
    for key in ('source50_root_manifest','source51_parent_manifest'):
        original(pre[key],'input/ancestor-manifests')
    for key,directory in [('source50_lock_originals_and_outer_terminal','input/source50-lock-prerequisites'),
                          ('original_r24_failed_100_provenance','input/r24-failed-provenance'),
                          ('original_r26_failed_100_provenance','input/r26-failed-provenance')]:
        for row in pre[key]:original(row,directory)
    ancestor=json.loads(members['input/source51-ancestor/native-source51-project-r26-preconditions.json'])
    for key in ('complete','terminal','source_postguard','delta_manifest'):
        original(ancestor['source51_apply'][key],'input/source51-apply-prerequisites')
        original(pre['source52_apply'][key],'input/source52-apply-pins')
    for stage,folder in [('r24','r24-failed-provenance'),('r26','r26-failed-provenance')]:
        prefix='native-source'+('50' if stage=='r24' else '51')+'-project-'+stage
        value=json.loads(members['input/'+folder+'/'+prefix+'-terminal-process-status.json'])
        assert value['exit_code']==100 and value['state']=='failed'
    input_raw=members['input/source52-apply-input.tar.gz']
    assert pin(input_raw)=={'bytes':43267,'sha256':'9c7a414899bd05d1e70b9a6cbac64eef9dda552f8e56c904ee9f8e21ab37d6cb','git_blob':'eefc9ec94d7c5a0074eaa35788b3fbe670314420'}
    with tarfile.open(fileobj=io.BytesIO(input_raw),mode='r:gz') as tf:
        nested={}
        for member in tf.getmembers():
            safe(member.name);assert member.isfile() and member.name not in nested
            nested[member.name]=tf.extractfile(member).read()
        assert set(nested)=={'before/'+RUNTIME,'after/'+RUNTIME,'candidate.patch','delta-manifest.json','source52-manifest.json'}
        assert nested['source52-manifest.json']==members['input/'+SOURCE_NAME]
        assert nested['after/'+RUNTIME]==members['source/'+RUNTIME]
    return {'same_source_project_gate':{'source_commit':COMMIT,'source_tree':TREE,'job_id':R28_JOB,
                                       'originals':26,'outer':pin(terminal_raw),'phases':phases,
                                       'python':{'tests':32,'skipped':0,'status':'OK'},
                                       'unique_tests':1564,'counts':review['terminal_counts'],'reported_skipped':3,
                                       'baseline_full_binary_name_set_verified':True},
            'historical_and_apply_pins':checked,'source50_lock_inherited_not_new_invocation':True,
            'old_failed_gate_records_retained':True,'counts_are_prerequisite_only_not_added_to_workspace_counts':True}


def verify_supplements(config,members,terminal,review):
    files={}
    for row in config['root_readbacks']+config['supplemental_originals']:
        path=WORK/row['path']
        assert path.is_file() and not path.is_symlink()
        raw=path.read_bytes();check_pin(raw,row)
        destination=row['destination']
        assert destination not in files
        files[destination]={'source':str(path),'raw':raw,'role':row.get('role')}
    required={'gate_binding','gate_authorization','export_template','export_binding','export_authorization','export_custody'}
    roles={r['role'] for r in files.values()}
    assert required<=roles,'Missing exact closed preparation/authorization evidence role.'
    export_terminal_raw=files[config['export_terminal_destination']]['raw']
    export_terminal=json.loads(export_terminal_raw)
    natural_terminal(export_terminal,config['export_original_job_id'],0)
    result=json.loads(files[config['export_result_destination']]['raw'])
    assert {k:result[k] for k in ('bytes','sha256','git_blob')}=={k:config['archive'][k] for k in ('bytes','sha256','git_blob')}
    assert result['members']==config['archive']['members'] and result['source_count']==195
    assert result['source_commit']==COMMIT and result['source_tree']==TREE
    assert result['original_outer_exit']==terminal['exit_code']
    assert result['counts']==review['terminal_counts'] and result['reported_skipped']==review['reported_skipped']
    assert result['complete_execution_accounting']==review['complete_execution_accounting'] and result['nextest_started']==review['nextest_started']
    bindings=config['actual_exporter_files']
    template=files[bindings['template']]['raw'];bound=files[bindings['bound']]['raw'];final=files[bindings['final']]['raw']
    values=json.loads(files[bindings['binding_values']]['raw'])
    inverse=inspect_literal_bindings(template,bound,values)
    assert set(values)=={'TERMINAL_PIN','CLOSED_ORIGINAL_PINS','CONTROLLER_ORIGINAL_PINS'}
    assert bound.replace(b'FROZEN = False',b'FROZEN = True',1)==final
    assert files[bindings['root_approved']]['raw']==final
    check_pin(members['evidence/'+PREFIX+'-terminal-process-status.json'],values['TERMINAL_PIN'])
    for name,value in values['CLOSED_ORIGINAL_PINS'].items():
        check_pin(members['evidence/'+name],value)
    for name,value in values['CONTROLLER_ORIGINAL_PINS'].items():
        assert name.startswith('r29-controller-closed-')
        check_pin(members['controller/'+name.removeprefix('r29-controller-closed-')],value)
    assert pin(members['input/native-run-r29.py'])['sha256']==RUNNER_SHA
    return files,{'actual_exporter':pin(final),'actual_template':pin(template),'binding_inverse':inverse,
                  'final_only_frozen_flip':True,'all_closed_original_and_controller_bindings_verified':True,
                  'export_job_id':config['export_original_job_id'],'export_original_exit':0,'export_not_a_new_gate':True,
                  'export_terminal':pin(export_terminal_raw)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,default=WORK/'r29-formal-preparation/ASSEMBLY-INPUTS.template.json')
    parser.add_argument('--output',type=Path,default=OUTPUT)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    if args.verify_only:
        verify_sealed(args.output);return
    config_raw=args.inputs.read_bytes();config=json.loads(config_raw)
    validate_inputs(config)
    archive_raw,members,modes,index=read_archive(config)
    source,source_rows=verify_sources(members,modes)
    metadata,scope,metadata_receipt=verify_metadata(members)
    phase,rows,review,failures,terminal=verify_workspace_phase(members,scope,metadata_receipt)
    controller=verify_controller(members,terminal)
    prerequisites=verify_prerequisites(members)
    supplements,export_review=verify_supplements(config,members,terminal,review)
    for key in ('original_workspace_exit','effective_workspace_exit','original_outer_exit'):
        expected={'original_workspace_exit':phase['original_exit'],'effective_workspace_exit':phase['effective_exit'],'original_outer_exit':phase['outer_exit']}[key]
        assert index[key]==expected
    assert index['original_counts']==review['terminal_counts'] and index['reported_skipped']==review['reported_skipped']
    assert index['classification']==('original_default_workspace_passed' if phase['effective_exit']==0 else 'original_default_workspace_failed')
    categories=dict(Counter(name.split('/',1)[0] for name in members if name!='INDEX.json'))
    per_package={}
    for row in rows:
        package=row['binary'].split('::',1)[0]
        per_package.setdefault(package,{s:0 for s in ('PASS','FAIL','TIMEOUT')})[row['status']]+=1
    # No formal path is created until real closed input and all checks above pass.
    output=args.output;output.mkdir(parents=True,exist_ok=True)
    mapping,gzip_records,dedup=[],[],{}
    def attach(origin,dest,raw,compress=True):
        value=pin(raw)
        if len(raw)>=32768 and value['sha256'] in dedup:
            prior=dedup[value['sha256']]
            assert prior['source_pin']==value
            mapping.append({'source':origin,'source_pin':value,**{k:prior[k] for k in ('destination','stored_pin','encoding')},'same_original_bytes_reused':True})
            return prior['destination']
        stored,encoding=raw,'identity'
        if compress and len(raw)>=65536 and not dest.endswith(('.gz','.tar')):
            raw.decode('utf-8');stored,dest,encoding=gz(raw),dest+'.gz','gzip-mtime-0'
            gzip_records.append({'path':dest,'stored':pin(stored),'uncompressed':value,'mtime':0,'roundtrip_exact':True})
        exact(output/dest,stored)
        item={'source':origin,'source_pin':value,'destination':dest,'stored_pin':pin(stored),'encoding':encoding}
        mapping.append(item)
        if len(raw)>=32768:dedup[value['sha256']]=item
        return dest
    archive_path=WORK/config['closed_directory']/ARCHIVE_NAME
    archive_pin={k:config['archive'][k] for k in ('bytes','sha256','git_blob')}
    attach(str(archive_path),ARCHIVE_NAME,archive_raw,False)
    member_mapping=[];destinations={}
    for name,raw in sorted(members.items()):
        item={'archive_member':name,**pin(raw),'archive_transport_mode':modes[name]}
        if name.startswith(('source/','locks/')):
            item.update({'storage':'unchanged_archive_member_only','archive':ARCHIVE_NAME})
        else:
            dest=attach(str(WORK/config['unpacked_directory']/name),'original/'+name,raw)
            destinations[name]=dest
            item.update({'storage':'archive_and_exact_attachment','destination':dest})
        member_mapping.append(item)
    for dest,item in sorted(supplements.items()):attach(item['source'],dest,item['raw'])
    attach(str(args.inputs),'ASSEMBLY-INPUTS.json',config_raw,False)
    attach(str(Path(__file__).resolve()),'verify_and_assemble.py',Path(__file__).read_bytes(),False)
    attach('derived:195-source-raw-and-git-mode-readback','readback/SOURCE-FILES.json',raw_json(source_rows))
    attach('derived:workspace-complete-log-unique-rows','readback/TEST-RESULTS.json',raw_json(rows))
    attach('derived:original-controller-output-concatenation','readback/CONTROLLER-OUTPUT.json',raw_json(controller))
    attach('derived:exact-r28-prerequisite-originals','readback/R28-PREREQUISITES.json',raw_json(prerequisites))
    attach('derived:workspace-package-result-counts','readback/PER-PACKAGE-RESULTS.json',raw_json(per_package))
    if phase['effective_exit']==0:
        classification='ENGINEERING_DEFAULT_WORKSPACE_PASS'
    elif not review['nextest_started']:
        classification='ENGINEERING_FAILED_BEFORE_NEXTEST_COUNTS_NULL'
    elif not review['complete_execution_accounting']:
        classification='ENGINEERING_FAILED_INCOMPLETE_EXECUTION_ACCOUNTING'
    else:
        classification='ENGINEERING_DEFAULT_WORKSPACE_FAILED'
    independent={
        'schema':'hepta.r29-independent-closed-readback.v1','classification':classification,
        'archive':archive_pin,'archive_members':len(members),'indexed_members':len(index['files']),'archive_categories':categories,
        'all_safe_regular_members_and_index_bytes_modes_verified':True,'all_unpacked_original_bytes_equal_archive':True,
        'source_commit':COMMIT,'source_tree':TREE,'native_head':HEAD,'changed_paths':195,'rust_paths':181,'other_paths':14,
        'all_source_raw_sha_gitblob_verified':True,'source51_original194_rows_preserved':True,
        'source_git_modes':'Original source manifest and original native staged-tree guards, independent of tar transport modes.',
        'offline_full_repository_tree_reconstructed_here':False,
        'source_tree_basis':'Original manifest, all195 raw source files and native pre/post/export full-source guards; no new checkout claim.',
        'cargo_lock_sha256':CARGO_SHA,'bazel_lock_sha256':BAZEL_SHA,
        'fresh_metadata':metadata,'original_workspace_phase':phase,'parsed_workspace_results':review,
        'per_package_observed_counts':per_package,'per_package_counts_are_terminal':review['complete_execution_accounting'],
        'original_results_reproduced_from_full_raw_log':True,'failure_blocks':failures['failures'],
        'raw_failure_blocks_match_exact_byte_offsets':True,'controller_full_output':controller,
        'r28_prerequisites':prerequisites,'r28_counts_not_added_to_workspace_counts':True,
        'export_only_custody':export_review,
        'default_workspace_gate_not_all_platforms_features_external_services':True,
        'old_failed_and_launch_null_snapshots_unchanged':True,'fix_fmt_executed_by_this_gate_or_reader':False,
        'rust_metadata_formatter_or_native_job_executed_by_reader':False,
        'whole_filesystem_free_space_not_attributed_to_one_task':True,
        'science':'HOLD','authority':'DENY_ALL','closure_gaps':[]}
    exact(output/'INDEPENDENT-READBACK.json',raw_json(independent))
    exact(output/'ORIGINAL-MEMBER-MAPPING.json',raw_json({'archive':{'path':ARCHIVE_NAME,**archive_pin},'members':member_mapping,'regular_member_count':len(members)}))
    closure={'schema':'hepta.r29-workspace-attachment-closure.v1','status':classification,
             'source_commit':COMMIT,'source_tree':TREE,'native_head':HEAD,'source_count':195,'original_gate_job':JOB,
             'metadata_original_exit':0,'workspace_members':193,'workspace_default_members':193,
             'original_command':COMMAND,'original_workspace_exit':phase['original_exit'],
             'effective_workspace_exit':phase['effective_exit'],'original_outer_exit':phase['outer_exit'],
             'nextest_started':review['nextest_started'],'complete_execution_accounting':review['complete_execution_accounting'],
             'terminal_unique_test_count':review['terminal_unique_test_count'],'terminal_counts':review['terminal_counts'],
             'reported_skipped':review['reported_skipped'],'skip_identities_inferred':False,
             'observed_rows_not_promoted_when_incomplete':review['execution_rows_observed'],
             'archive':{'path':ARCHIVE_NAME,**archive_pin},'archive_members':len(members),'indexed_members':len(index['files']),
             'independent_readback':{'path':'INDEPENDENT-READBACK.json',**pin((output/'INDEPENDENT-READBACK.json').read_bytes())},
             'original_r28_26_plus_terminal_preserved_and_verified':True,'prior_project_counts_not_accumulated':True,
             'source_and_raw_locks_archive_only':True,'export_exit_zero_is_artifact_success_only':True,
             'full_log_rows_raw_receipts_resources_guard_controller_and_failure_blocks_preserved':True,
             'all_platforms_features_external_services_qualified':False,'final_fix_fmt':'NOT_EXECUTED_BY_THIS_GATE_OR_READER',
             'science':'HOLD','authority':'DENY_ALL','closure_gaps':[],
             'limits':['A failed compile or missing complete Summary is not relabelled as a zero-test execution.',
                       'Execution rows are counted by binary/name before Summary; repeated footer rows are excluded.',
                       'Reported skip totals are retained without inventing per-ID skip identities.',
                       'Only source52 default-workspace coverage shown by this exact original command is qualified.',
                       'Mechanism tests and archive integrity do not grant scientific or real-model qualification.']}
    exact(output/'CLOSURE.json',raw_json(closure))
    if review['complete_execution_accounting']:
        counts_text=' / '.join(str(review['terminal_counts'][key])+' '+key for key in ('PASS','FAIL','TIMEOUT'))
        count_sentence=f"完整原日志有 {review['terminal_unique_test_count']} 个唯一 binary/name 结果：{counts_text}；另报 {review['reported_skipped']} skipped。"
    elif not review['nextest_started']:
        count_sentence='原日志没有 nextest Starting；终态测试计数和唯一测试总数保持 null，不能称为运行了 0 项测试。'
    else:
        count_sentence=f"已观察到 {review['execution_rows_observed']} 条执行结果，但缺少完整一致的终态统计；终态计数保持 null。"
    log_dest=destinations['evidence/'+PREFIX+'-tests.log']
    metadata_dest=destinations['evidence/'+PREFIX+'-metadata.json']
    readme=f'''# r29 原默认工作区门：闭合原件

**{classification}；科学 HOLD、权限 DENY_ALL。** 本组绑定 source52 commit `{COMMIT}`、staged tree `{TREE}`，195 个变更路径（181 Rust＋14 other）。原生 HEAD 仍为 framework `{HEAD}`；Git 对象身份不冒充 checkout。

原命令是 `just test --locked --retries 0`，没有 `-p` 或新增 filter。执行前的本轮 metadata 原进程退出 0，193 个 workspace members 与 193 个 default members 的实际 ID 集合一致。原 workspace 进程返回 `{phase['original_exit']}`，有效返回 `{phase['effective_exit']}`，外层自然返回 `{phase['outer_exit']}`。

{count_sentence}

原 gate 总时长 `{phase['elapsed_seconds']}` 秒。完整日志见 [workspace tests log]({log_dest})，本轮完整 metadata 见 [metadata]({metadata_dest})，每个原错误字节块见 [failure-blocks/INDEX.json](original/failure-blocks/INDEX.json)。结果由完整原日志独立解析，排除 Summary 后的重复失败摘要，没有将原 r28 数字与工作区结果相加。

## 原件与核验

- [CLOSURE.json](CLOSURE.json) 和 [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json) 是本次新读回结论。
- [{ARCHIVE_NAME}]({ARCHIVE_NAME}) 原样保留 {len(members)} 个 regular 成员、{len(index['files'])} 条 INDEX 和全部 195 份源码。每个源码的 raw SHA、Git blob、原 Git mode 与双锁均已核验；tar 的传输权限单独处理。
- 原 r28 的 26 件 gate 原件加自然终态保存在 input/r28-prerequisites；其 Python32、四包 strict 和四包1564 PASS 是本轮启动前置，独立于本轮统计。旧 r24/r26 失败和启动 null 快照没有被改写。
- 全部原 log、rows、metadata、raw rc、receipt、resources、source guards、controller 输出、runner 和闭合授权均保留。大 UTF-8 文件采用 mtime=0 gzip，逐项解压字节相等；同字节大文件通过映射去重。
- [ORIGINAL-MEMBER-MAPPING.json](ORIGINAL-MEMBER-MAPPING.json) 和 [SOURCE-DESTINATION-MAPPING.json](SOURCE-DESTINATION-MAPPING.json) 提供完整定位；源码和原双锁仅留在原 archive，不重复复制第二棵源码树。
- exporter 自然退出 0 仅证明归档成功，不改变原 gate 结果。所有当前计数来自本轮原件，没有硬编码当前测试数量、重跑测试或借用旧轮次资格。

本门保持原默认 features、ignored/platform/service 条件；不宣称全部 feature、平台或真实外部服务覆盖。最终 fix/fmt 的执行和归档需要后续独立证据。本地读回没有执行 Rust、Cargo metadata、format、Git 命令或 native 任务。

附件纯字节复核：`python3 verify_and_assemble.py --verify-only --output <本目录>`。
'''
    exact(output/'README.md',readme.encode())
    exact(output/'SOURCE-DESTINATION-MAPPING.json',raw_json({'schema':'hepta.r29-attachment-mapping.v1','files':mapping}))
    exact(output/'GZIP-ROUNDTRIP.json',raw_json({'schema':'hepta.deterministic-gzip-readback.v1','files':gzip_records}))
    binaries=[]
    for path in sorted(output.rglob('*')):
        if not path.is_file() or not path.name.endswith('.gz'):continue
        value={'path':str(path.relative_to(output)),**pin(path.read_bytes()),'original_bytes_unchanged':path.name.endswith('.tar.gz'),
               'git_upload_performed_here':False}
        value['reuse_known_git_blob']=value['git_blob'] in {archive_pin['git_blob'],'eefc9ec94d7c5a0074eaa35788b3fbe670314420'}
        binaries.append(value)
    exact(output/'BINARY-PLAN.json',raw_json({'schema':'hepta.r29-attachment-binary-plan.v1','files':binaries,'upload_owner':'root','git_upload_performed_here':False}))
    files=[{'path':str(p.relative_to(output)),**pin(p.read_bytes())} for p in sorted(output.rglob('*')) if p.is_file() and p.name!='ATTACHMENT-MANIFEST.json']
    exact(output/'ATTACHMENT-MANIFEST.json',raw_json({'schema':'hepta.r29-workspace-attachment-manifest.v1','source_commit':COMMIT,'source_tree':TREE,
         'classification':classification,'files':files,'file_count_excluding_manifest':len(files),'stored_bytes_excluding_manifest':sum(v['bytes'] for v in files)}))
    verify_sealed(output)
    print(json.dumps({'closure':pin((output/'CLOSURE.json').read_bytes()),'independent':pin((output/'INDEPENDENT-READBACK.json').read_bytes()),
                      'classification':classification,'terminal_counts':review['terminal_counts'],'reported_skipped':review['reported_skipped'],
                      'archive_members':len(members),'source_files':195,'binary_files':len(binaries),'rust_rerun':False},indent=2))


if __name__=='__main__':
    assert __debug__,'Verification assertions must remain enabled.'
    main()
