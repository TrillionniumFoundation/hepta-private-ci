#!/usr/bin/env python3
"""Closed r28 evidence exporter. Bind exact originals and review before enabling.

This program never executes a gate, Cargo, metadata, formatter, patch or source
mutation. The only subprocesses are explicit Git reads of the frozen checkout.
All new derived files and the archive are create-only; original bytes stay intact.
"""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json
import re
import stat
import subprocess
import sys
import tarfile

FROZEN = False
TERMINAL_PIN = {'bytes': 731, 'sha256': '897df3ad774667b7fab516e0d93fc3c68c43eb4c6c91e713207326feb9cd1458'}
CLOSED_ORIGINAL_PINS = {'native-source52-project-r28-complete.json': {'bytes': 2152, 'sha256': '993d9a48333d093218a42cb8943f02b88d0e4a151354e8522dc1b51cbfea0b4d'}, 'native-source52-project-r28-environment.json': {'bytes': 1341, 'sha256': 'c892f430fe66420367fd086c9cb2f39158520872ef55409dd222b00adc6825ee'}, 'native-source52-project-r28-preconditions.json': {'bytes': 9513, 'sha256': '741cd5aa598adecb7d2a2c3a4f976e672aac0b6b84697785bfffbdc6a5ed618e'}, 'native-source52-project-r28-python-runner-raw-process-result.json': {'bytes': 551, 'sha256': '51d4478678c3776377e3cc9874e858319f41ad9bf091f36549b5324dc176cc94'}, 'native-source52-project-r28-python-runner-receipt.json': {'bytes': 2018, 'sha256': '132959ea0f647cdfc6bebf2ad1c6df1932cabaaf478df6766a9efe1b5cc1214c'}, 'native-source52-project-r28-python-runner-resources.txt': {'bytes': 799, 'sha256': 'b8f3cadb21631aa89ed6461c53c6578185e61201efe71d236849f77b33c11d36'}, 'native-source52-project-r28-python-runner-result-review.json': {'bytes': 573, 'sha256': '5ea50ce13ede9ded54defce0016eb9cfe02dba91e85bb8ade97639d14ec0e56d'}, 'native-source52-project-r28-python-runner-source-post-verification.json': {'bytes': 639, 'sha256': '4c3e8e822a1607b0b0073b9f09cfc07b20161997db7783d3c907c3a56666cb8c'}, 'native-source52-project-r28-python-runner-source-pre-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-python-runner.log': {'bytes': 8449, 'sha256': '2eb07b7f4af98d408131099bf8980c3ac298d4447b4b5a6334634696c5f78d78'}, 'native-source52-project-r28-source-final-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-source-pre-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-strict-raw-process-result.json': {'bytes': 648, 'sha256': 'ba9571183c1718b35852a662348685b649df801ca7a8d81b997b1eabf8ee65f0'}, 'native-source52-project-r28-strict-receipt.json': {'bytes': 1974, 'sha256': '72c3fc2b3eb14f24f921b00126b3cd0f97fb25001c3d2b7f616f5d0b9807dc33'}, 'native-source52-project-r28-strict-resources.txt': {'bytes': 875, 'sha256': '86a4a7cd6a1d6c0f1256c3f1b08673c7a2007a2b7d79517040e05f61e7324399'}, 'native-source52-project-r28-strict-source-post-verification.json': {'bytes': 632, 'sha256': 'fccf765f216c237050d82ac572f35d4820ba9c0b053280daf03e7c6b160b8288'}, 'native-source52-project-r28-strict-source-pre-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-strict.log': {'bytes': 13645, 'sha256': 'a0ee362bdfc5f2811b26ee60bc0f4310003a786a27cd3190a48bdf064c656231'}, 'native-source52-project-r28-tests-raw-process-result.json': {'bytes': 634, 'sha256': 'cf8237de117ec35091a76f9aa19616bfbddf565902cf260b00a3c67c7b8942b5'}, 'native-source52-project-r28-tests-receipt.json': {'bytes': 2185, 'sha256': '5c9e23a6af959cb85cc6fb51ac64c9007598a0fc6e5249cc08317fc32eab94c9'}, 'native-source52-project-r28-tests-resources.txt': {'bytes': 874, 'sha256': '3bc47b2c37fba391808302569702b55882256cd22b31cdbc88fdd780f604b774'}, 'native-source52-project-r28-tests-result-review.json': {'bytes': 1530, 'sha256': '17be2fef913175a3a52d17d71a9a1d7d98006727c6e8531afbf9e7b1fd1ac314'}, 'native-source52-project-r28-tests-source-post-verification.json': {'bytes': 631, 'sha256': '2ef89440340e634d1e74643eb0b73091af88570fec8e6e7c3a6a3a1c3fafa023'}, 'native-source52-project-r28-tests-source-pre-verification.json': {'bytes': 588, 'sha256': '4c4767a8f0d137eacd98c7115efe687bda3e6b87b8809442a11d6f78bf7278b1'}, 'native-source52-project-r28-tests-test-results.json': {'bytes': 345527, 'sha256': '2963674ed389a0ba770355c56ba6eaeecc85c253a9c80b73e98b20f709d721c6'}, 'native-source52-project-r28-tests.log': {'bytes': 216247, 'sha256': '1af36d6404dff5026eca008da904354e4346523cb7cdca4d1231a59036d18347'}}
CONTROLLER_ORIGINAL_PINS = {'r28-controller-closed-launch.json': {'bytes': 1400, 'sha256': '5647f53aa506ff376103219f91a5de8358f8f04e6d300768a6daf9d633cbf2ac'}, 'r28-controller-closed-terminal-process-status.json': {'bytes': 731, 'sha256': '897df3ad774667b7fab516e0d93fc3c68c43eb4c6c91e713207326feb9cd1458'}, 'r28-controller-closed-read-000000.json': {'bytes': 9578, 'sha256': 'a92f2c53e81d034b7bea1180f100e9f90b20365b9c10ed93815eb4c788ace67b'}, 'r28-controller-closed-read-002995.json': {'bytes': 8765, 'sha256': 'b91044ff0da74b426083d68c3b916ba2578959131c4477e72c1d915b2044674f'}, 'r28-controller-closed-read-005725.json': {'bytes': 8296, 'sha256': 'e67880ad03764e7cabac3c30299f71dff5ba02008e71aa83a4ecde74f0df05bd'}}

T = Path('/home/alex/work/hepta-cell-unified-20261106-a')
S = T / 'source'
E = T / 'evidence'
PREFIX = 'native-source52-project-r28'
COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
JOB_ID = '1a1b1e9bee0-fc05-7b7c'
SOURCE_NAME = 'native-candidate-r28-source.json'
SOURCE_PIN = {'bytes':55209,'sha256':'3ff99b41bab572666b424fdbf9a508b33be13e6487d9effa7dd6a0e14b4ec898','git_blob':'f057b526bf2ba492d6bb5810222f69ac0cc3bdd2'}
RUNNER_PIN = {'bytes':54455,'sha256':'a7b64eb8ff8ec2b5bc75ae836e3ff423ce31ee86d5c4daf64b7543a8fa7aae9e','git_blob':'9f1a10e6eb0998b9c5e297a2d0a5382f0a289f0d'}
INPUT_PIN = {'bytes':43267,'sha256':'9c7a414899bd05d1e70b9a6cbac64eef9dda552f8e56c904ee9f8e21ab37d6cb','git_blob':'eefc9ec94d7c5a0074eaa35788b3fbe670314420'}
BASELINE_NAME = 'source50-four-package-r23-baseline.json'
BASELINE_SHA = '6feba9a285f77f16fc1d34710d2737eae78a4ba3be74affd40f5703bc8ce405e'
R26_PRE_PIN = {'bytes':7651,'sha256':'d1b604225a9162ffd3bfc1b4a372dac755f79ce63fe48e8614920d95682ee118','git_blob':'9e919e732f041571afe7b9e1c273d6a45b5ca682'}
LOCKS = {'codex-rs/Cargo.lock':'4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c','MODULE.bazel.lock':'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'}
PACKAGES = ['codex-cli','codex-exec-server','codex-network-proxy','codex-external-agent-migration']
PYTHON_TEST_COUNT = 32
BASELINE_COUNT = 1564
ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
CONTROLLER_PREFIX = 'r28-controller-closed-'
OUT = E / 'checkpoint-r28-closed.tar.gz'
DERIVED = E / 'r28-closed-export'
RESULT = E / 'checkpoint-r28-export.json'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def data_pin(raw):
    return {'bytes':len(raw),'sha256':sha(raw),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def safe_relative(value):
    p=PurePosixPath(value)
    require(isinstance(value,str) and value and not p.is_absolute() and '..' not in p.parts and '.' not in p.parts,'unsafe relative path')
    return p


def check_pin(raw,pin,label):
    require(isinstance(pin,dict) and 'bytes' in pin and 'sha256' in pin,'missing pin: '+label)
    actual=data_pin(raw)
    require(actual['bytes']==pin['bytes'] and actual['sha256']==pin['sha256'],'byte/SHA mismatch: '+label)
    if 'git_blob' in pin:require(actual['git_blob']==pin['git_blob'],'Git blob mismatch: '+label)


def check_bindings():
    require(__debug__,'do not run evidence validation with Python optimization')
    require(FROZEN is True,'inert exporter: FROZEN must be explicitly reviewed and bound')
    require(isinstance(TERMINAL_PIN,dict) and isinstance(CLOSED_ORIGINAL_PINS,dict) and isinstance(CONTROLLER_ORIGINAL_PINS,dict),'closed binding maps are not set')
    for name,pin in CLOSED_ORIGINAL_PINS.items():
        safe_relative(name);require('/' not in name and name.startswith(PREFIX+'-'),'unexpected closed gate path')
        require(isinstance(pin,dict) and isinstance(pin.get('bytes'),int) and re.fullmatch('[0-9a-f]{64}',pin.get('sha256','')) is not None,'invalid closed gate pin')
    for name,pin in CONTROLLER_ORIGINAL_PINS.items():
        safe_relative(name);require('/' not in name and name.startswith(CONTROLLER_PREFIX),'unexpected controller path')
        require(isinstance(pin,dict) and isinstance(pin.get('bytes'),int) and re.fullmatch('[0-9a-f]{64}',pin.get('sha256','')) is not None,'invalid controller pin')
    suffixes={name[len(CONTROLLER_PREFIX):] for name in CONTROLLER_ORIGINAL_PINS}
    require({'launch.json','terminal-process-status.json'}<=suffixes,'controller launch/terminal required')
    require(any(re.fullmatch(r'read-[0-9]+\.json',name) for name in suffixes),'closed controller read records required')
    require(all(name in {'launch.json','terminal-process-status.json'} or re.fullmatch(r'read-[0-9]+\.json',name) for name in suffixes),'unexpected controller input')


def stable_read(path):
    first=path.lstat()
    require(stat.S_ISREG(first.st_mode) and first.st_nlink==1,'not an owned regular file: '+str(path))
    raw=path.read_bytes();last=path.lstat()
    fields=('st_dev','st_ino','st_mode','st_nlink','st_size','st_mtime_ns','st_ctime_ns')
    require(all(getattr(first,k)==getattr(last,k) for k in fields) and len(raw)==last.st_size,'file changed during read: '+str(path))
    return raw,stat.S_IMODE(last.st_mode)


def git(*args):
    require(args[0] in {'write-tree','rev-parse','diff','ls-files','ls-tree'},'export Git allowlist violation')
    return subprocess.check_output(['git','--no-optional-locks',*args],cwd=S)


def source_guard(source):
    require(source['source_commit']==COMMIT and source['source_tree']==TREE,'wrong source52 identity')
    rows=source['changed_files'];files={row['path']:row for row in rows}
    require(len(files)==len(rows)==195,'wrong source52 changed count')
    require(git('rev-parse','HEAD').decode().strip()==HEAD,'native HEAD changed')
    require(git('write-tree').decode().strip()==TREE,'staged tree changed')
    require(not git('diff','--name-only') and not git('ls-files','--others','--exclude-standard'),'source is not clean/staged only')
    paths=git('diff','--cached','--no-renames','--name-only','-z',HEAD).decode().split('\0')[:-1]
    require(len(paths)==195 and set(paths)==set(files),'changed path set differs')
    index={}
    for entry in git('ls-files','--stage','-z').split(b'\0'):
        if not entry:continue
        left,path=entry.split(b'\t',1);mode,blob,stage=left.decode().split()
        require(stage=='0','unmerged index entry')
        index[path.decode()]=(mode,blob)
    for path,row in files.items():
        safe_relative(path);raw,mode=stable_read(S/path)
        require(data_pin(raw)=={k:row[k] for k in ('bytes','sha256','git_blob')},'source byte mismatch: '+path)
        require(index[path]==(row['mode'],row['git_blob']),'source index mode/blob mismatch: '+path)
        require(('100755' if mode&0o111 else '100644')==row['mode'],'source execute-bit mismatch: '+path)
    for path,digest in LOCKS.items():require(sha(stable_read(S/path)[0])==digest,'raw lock changed: '+path)
    return {'source_commit':COMMIT,'source_tree':TREE,'native_head':HEAD,'source_count':195,'all_raw_sha_gitblob_gitmode_verified':True,'no_unstaged_untracked_or_extra_paths':True,'cargo_lock_sha256':LOCKS['codex-rs/Cargo.lock'],'bazel_lock_sha256':LOCKS['MODULE.bazel.lock'],'pass':True}


def recorded_guard(value):
    require(value['pass'] is True and value['source_commit']==COMMIT and value['actual_tree']==value['expected_tree']==TREE,'original source guard failed')
    require(value['changed_file_count']==195 and value['native_head']==HEAD and value['changed_path_set_matches'] is True,'original source count/HEAD differs')
    require(value['file_mismatches']==value['unstaged_paths']==value['untracked_paths']==[],'original source guard mismatches')
    require(value['cargo_lock_sha256']==LOCKS['codex-rs/Cargo.lock'] and value['bazel_lock_sha256']==LOCKS['MODULE.bazel.lock'],'original guard dual locks differ')


def natural_terminal(value):
    require(value['job_id']==JOB_ID and isinstance(value['exit_code'],int),'wrong original gate terminal')
    require(value['state']==('succeeded' if value['exit_code']==0 else 'failed'),'outer state/exit mismatch')
    for key in ('output_complete','output_durable','terminal_publication_confirmed'):require(value[key] is True,'incomplete outer publication')
    for key in ('timed_out','cancelled','automatic_retry'):require(value[key] is False,'not a natural closed gate')
    require(not any(value['log_truncated'].values()) and all(x is None for x in value['log_errors'].values()),'outer output truncated or unavailable')


def clean_lines(raw):
    offset = 0
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        yield number, offset, ANSI.sub(b"", line).decode("utf-8", "replace").rstrip("\r\n")
        offset += len(line)


def review_python(raw):
    lines = list(clean_lines(raw))
    summaries = [(n, o, text, re.fullmatch(r"\s*Ran ([0-9]+) tests? in ([0-9.]+)s\s*", text)) for n, o, text in lines]
    summaries = [(n, o, text, match) for n, o, text, match in summaries if match]
    ok = [(n, o, text) for n, o, text in lines if text.strip() == "OK"]
    skipped = [(n, o, text) for n, o, text in lines if re.search(r"\.\.\. skipped\b|^OK \(.*skipped=", text)]
    passed = len(summaries) == 1 and int(summaries[0][3][1]) == PYTHON_TEST_COUNT and len(ok) == 1 and not skipped
    return {
        "schema": "hepta.source51-python-runner-readback.v1",
        "log": data_pin(raw), "expected_test_count": PYTHON_TEST_COUNT,
        "reported_test_count": int(summaries[0][3][1]) if len(summaries) == 1 else None,
        "summary_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text, _ in summaries],
        "ok_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text in ok],
        "skip_lines": [{"line": n, "byte_offset": o, "text": text} for n, o, text in skipped],
        "reported_skipped": 0 if passed else None, "pass": passed,
    }


def review_tests(raw, baseline):
    lines = list(clean_lines(raw))
    starts = [(n, o, text, re.match(r"^\s*Starting ([0-9]+) tests?\b", text)) for n, o, text in lines]
    starts = [(n, o, text, m) for n, o, text, m in starts if m]
    summaries = [(n, o, text, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", text)) for n, o, text in lines]
    summaries = [(n, o, text, m) for n, o, text, m in summaries if m]
    require(len(starts) == len(summaries) == 1, "complete nextest Starting/Summary required")
    start, summary = starts[0], summaries[0]
    require(start[0] < summary[0], "invalid nextest event order")
    row_pattern = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
    rows = []
    footer_rows = []
    for number, offset, text in lines:
        match = row_pattern.match(text)
        if not match:
            continue
        row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
               "line": number, "byte_offset": offset}
        if start[0] < number < summary[0]:
            rows.append(row)
        elif number > summary[0]:
            footer_rows.append(row)
    current = {(row["binary"], row["name"]): row for row in rows}
    counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "TIMEOUT")}
    tail = summary[3][3]
    def summary_count(label):
        match = re.search(r"\b([0-9]+) " + label + r"\b", tail)
        return int(match[1]) if match else 0
    expected_counts = {"PASS": summary_count("passed"), "FAIL": summary_count("failed"), "TIMEOUT": summary_count("timed out")}
    reported_skipped = summary_count("skipped")
    missing = sorted(baseline - set(current))
    unsuccessful = sorted(identity for identity in baseline & set(current) if current[identity]["status"] != "PASS")
    unexpected_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(PACKAGES))
    passed = (
        len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and bool(rows) and counts == expected_counts
        and counts["FAIL"] == counts["TIMEOUT"] == 0
        and not missing and not unsuccessful and not unexpected_packages
    )
    review = {
        "schema": "hepta.source52-four-package-closed-readback.v1",
        "log": data_pin(raw), "starting": {"line": start[0], "byte_offset": start[1], "text": start[2]},
        "summary": {"line": summary[0], "byte_offset": summary[1], "text": summary[2], "seconds": float(summary[3][1])},
        "unique_test_count": len(current), "execution_rows": len(rows), "counts": counts,
        "summary_counts": expected_counts, "reported_skipped": reported_skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer_rows, "baseline_count": len(baseline),
        "baseline_is_source49_previous_failure_population_not_previous_pass": True,
        "baseline_missing": [{"binary": b, "name": n} for b, n in missing],
        "baseline_not_pass": [{"binary": b, "name": n} for b, n in unsuccessful],
        "additional_test_ids": [{"binary": b, "name": n} for b, n in sorted(set(current) - baseline)],
        "unexpected_packages": unexpected_packages,
        "per_package": {package: {status: sum(row["binary"].split("::", 1)[0] == package and row["status"] == status for row in rows)
                                 for status in ("PASS", "FAIL", "TIMEOUT")} for package in PACKAGES},
        "baseline_used_as_filter": False, "pass": passed,
    }
    return rows, review

def export_closed():
    require(not OUT.exists() and not DERIVED.exists() and not RESULT.exists(),'create-only export output already exists')
    contents={};modes={};read_paths={}
    def add(name,path,expected=None):
        safe_relative(name);raw,mode=stable_read(path)
        if expected is not None:check_pin(raw,expected,name)
        if name in contents:require(contents[name]==raw and modes[name]==mode,'duplicate archive member differs: '+name)
        else:contents[name]=raw;modes[name]=mode
        read_paths[str(path)]={'raw':data_pin(raw),'mode':mode}
        return raw
    def pinned_input(pin,directory):
        rel=str(safe_relative(pin['path']));return add(directory+'/'+rel,E/rel,pin)
    terminal_raw=add('evidence/'+PREFIX+'-terminal-process-status.json',E/(PREFIX+'-terminal-process-status.json'),TERMINAL_PIN)
    terminal=json.loads(terminal_raw);natural_terminal(terminal)
    source_raw=add('input/'+SOURCE_NAME,E/SOURCE_NAME,SOURCE_PIN);source=json.loads(source_raw)
    initial_source=source_guard(source)
    for row in source['changed_files']:add('source/'+row['path'],S/row['path'],row)
    for path,digest in LOCKS.items():require(sha(add('locks/'+path,S/path))==digest,'lock copy mismatch')
    for name,pin in CLOSED_ORIGINAL_PINS.items():add('evidence/'+name,E/name,pin)
    closed={name:contents['evidence/'+name] for name in CLOSED_ORIGINAL_PINS}
    get=lambda suffix:json.loads(closed[PREFIX+suffix])
    pre=get('-preconditions.json');env=get('-environment.json')
    for value in (pre,env):require(value['source_commit']==COMMIT and value['source_tree']==TREE,'original gate source identity differs')
    require(pre['actual_changed_file_count']==195 and pre['source_manifest']=={'path':SOURCE_NAME,**data_pin(source_raw)},'gate full manifest not bound')
    require(pre['patch_application_performed_by_this_runner'] is False and pre['lock_update_performed_by_this_runner'] is False,'gate scope differs')
    recorded_guard(get('-source-pre-verification.json'))
    baseline_raw=pinned_input(pre['baseline'],'input/baseline')
    require(sha(baseline_raw)==BASELINE_SHA,'wrong original baseline')
    baseline_value=json.loads(baseline_raw);baseline={(r['binary'],r['name']) for r in baseline_value['test_ids']}
    require(len(baseline)==len(baseline_value['test_ids'])==BASELINE_COUNT,'invalid baseline identities')
    source50=json.loads(pinned_input(pre['source50_root_manifest'],'input/ancestor-manifests'))
    source51=json.loads(pinned_input(pre['source51_parent_manifest'],'input/ancestor-manifests'))
    old={r['path']:r for r in source51['changed_files']};new={r['path']:r for r in source['changed_files']}
    require(len(old)==194 and set(new)==set(old)|{'codex-rs/network-proxy/src/runtime.rs'},'source51→52 path set differs')
    require(all(new[p]==r for p,r in old.items()),'original source51 manifest rows changed')
    require(source51['source_commit']=='e28b0f385ee882f842911044958b2810f62f6379' and source51['source_tree']=='763c8d2b4089f6e9806c3bbb68fa247bc2f6af36','wrong source51 ancestor')
    require(source50['source_commit']=='1fdd647b0ecb235530e8b88bbea45b3d3762906f' and source50['source_tree']=='ea48acf562499192a25e05ae28926a32632dee62','wrong source50 ancestor')
    for value in (pre,source50,source51):require(value['cargo_lock_sha256']==LOCKS['codex-rs/Cargo.lock'] and value['bazel_lock_sha256']==LOCKS['MODULE.bazel.lock'],'ancestor raw lock pins changed')
    for p in pre['source50_lock_originals_and_outer_terminal']:pinned_input(p,'input/source50-lock-prerequisites')
    for p in pre['original_r24_failed_100_provenance']:pinned_input(p,'input/r24-failed-provenance')
    for p in pre['original_r26_failed_100_provenance']:pinned_input(p,'input/r26-failed-provenance')
    r26pre=json.loads(add('input/source51-ancestor/native-source51-project-r26-preconditions.json',E/'native-source51-project-r26-preconditions.json',R26_PRE_PIN))
    for key in ('complete','terminal','source_postguard','delta_manifest'):pinned_input(r26pre['source51_apply'][key],'input/source51-apply-prerequisites')
    apply=pre['source52_apply']
    for key in ('complete','terminal','source_postguard','delta_manifest'):pinned_input(apply[key],'input/source52-apply-pins')
    apply_dir=E/'native-source52-apply'
    require(apply_dir.is_dir() and not apply_dir.is_symlink(),'source52 apply original directory missing')
    for path in sorted(apply_dir.rglob('*')):
        require(not path.is_symlink(),'symlink in apply originals')
        if path.is_file():add('input/source52-apply-prerequisites/'+str(path.relative_to(apply_dir)),path)
    original_input=add('input/source52-apply-input.tar.gz',T/'source52-apply-input.tar.gz',INPUT_PIN)
    with tarfile.open(fileobj=io.BytesIO(original_input),mode='r:gz') as tf:
        mems={}
        for m in tf.getmembers():
            safe_relative(m.name);require(m.isfile() and not m.issym() and not m.islnk() and m.name not in mems,'unsafe apply archive member')
            mems[m.name]=tf.extractfile(m).read();require(len(mems[m.name])==m.size,'apply archive member size mismatch')
        require(set(mems)=={'before/codex-rs/network-proxy/src/runtime.rs','after/codex-rs/network-proxy/src/runtime.rs','candidate.patch','delta-manifest.json','source52-manifest.json'},'wrong five-member apply input')
        require(mems['source52-manifest.json']==source_raw,'apply/full manifest differs')
        require(data_pin(mems['after/codex-rs/network-proxy/src/runtime.rs'])=={k:new['codex-rs/network-proxy/src/runtime.rs'][k] for k in ('bytes','sha256','git_blob')},'apply after bytes differ')
    add('input/native-run-r28.py',T/'native-run-r28.py',RUNNER_PIN)
    controller={}
    for name,pin in CONTROLLER_ORIGINAL_PINS.items():
        base=name[len(CONTROLLER_PREFIX):];controller[base]=json.loads(add('controller/'+base,E/name,pin))
    require(controller['terminal-process-status.json']==terminal,'controller/gate terminal bytes differ')
    launch=controller['launch.json'];require(launch['job']['id']==JOB_ID and launch['job']['launch_state']=='launched' and launch['launch']['ok'] is True,'wrong original controller launch')
    require(RUNNER_PIN['sha256'] in launch['job']['args'][1],'controller launch runner digest differs')
    for stream in ('stdout','stderr'):
        chunks=[]
        for name,value in controller.items():
            if not name.startswith('read-'):continue
            require(value['job_id']==JOB_ID,'controller read job differs')
            v=value[stream];raw=bytes.fromhex(v['bytes_hex'])
            require(len(raw)==v['next_offset']-v['offset'] and v['size']>=v['next_offset'] and v['text'].encode()==raw,'controller text/hex differs')
            require(v['next_offset']==v['offset']+len(raw),'controller chunk offsets differ')
            chunks.append((v['offset'],raw))
        end=0;parts=[]
        for offset,raw in sorted(chunks,key=lambda x:x[0]):
            if not raw:require(offset<=end,'empty controller read beyond known end');continue
            require(offset==end,'controller output gap/overlap');parts.append(raw);end+=len(raw)
        require(terminal['log_bytes'][stream]['seen']==terminal['log_bytes'][stream]['stored']==end,'controller original output incomplete')
        contents['controller/original-'+stream+'.txt']=b''.join(parts);modes['controller/original-'+stream+'.txt']=0o600
    args=[x for p in PACKAGES for x in ('-p',p)]
    commands={'python-runner':['python3','-m','unittest','discover','-s','scripts','-p','test_run_nextest*.py','-v'],'strict':['just','clippy','--locked',*args,'--','-D','warnings'],'tests':['just','test','--locked',*args,'--retries','0']}
    phases={};receipts=[];rows=[];test_review=None;parse_error=None;last_rc=0;last_end=None;stopped=False
    for phase,command in commands.items():
        stem=PREFIX+'-'+phase
        available=stem+'-raw-process-result.json' in closed
        if not available:
            require(stopped,'phase absent before a recorded failure');continue
        require(not stopped,'later phase ran after a failure')
        raw=json.loads(closed[stem+'-raw-process-result.json']);rec=json.loads(closed[stem+'-receipt.json'])
        log=closed[stem+'.log'];resources=closed[stem+'-resources.txt']
        for v in (raw,rec):require(v['source_commit']==COMMIT and v['source_tree']==TREE and v['phase']==phase and v['command']==command,'original phase identity/command differs')
        for k in ('phase','source_commit','source_tree','command','cwd','start_unix','end_unix','exit_code'):require(raw[k]==rec[k],'raw/receipt mismatch: '+k)
        require(rec['cwd']==str(S if phase=='python-runner' else S/'codex-rs'),'phase cwd differs')
        require(rec['raw_process_result']=={'path':stem+'-raw-process-result.json',**data_pin(closed[stem+'-raw-process-result.json'])},'raw receipt pin differs')
        require(rec['log_sha256']==sha(log) and rec['resources_sha256']==sha(resources),'phase log/resource pin differs')
        require(re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$',resources,re.M)==[str(raw['exit_code']).encode()],'resource exit differs')
        require(rec['source_manifest_sha256']==SOURCE_PIN['sha256'] and rec['source_manifest']==SOURCE_NAME,'phase full manifest differs')
        require(rec['source_guards_pass'] is True,'phase source guard failed')
        for side in ('pre','post'):recorded_guard(json.loads(closed[stem+'-source-'+side+'-verification.json']))
        post=json.loads(closed[stem+'-source-post-verification.json']);require(post['gate_exit_code']==raw['exit_code'],'postguard original exit differs')
        require(rec['source_postguard']=={'path':stem+'-source-post-verification.json',**data_pin(closed[stem+'-source-post-verification.json'])},'postguard receipt pin differs')
        require(rec['end_unix']>=rec['start_unix'] and (last_end is None or rec['start_unix']>=last_end),'phase time order differs')
        last_end=rec['end_unix'];require(abs(rec['elapsed_seconds']-(rec['end_unix']-rec['start_unix']))<1e-6,'phase elapsed differs')
        require(rec['filters']=='no_additions' and rec['features']=='unchanged_defaults' and rec['baseline_used_as_filter'] is False and rec['fix_fmt_executed'] is False,'phase scope changed')
        require(rec['phase_pass'] is (rec['effective_exit_code']==0),'phase effective result differs')
        if raw['exit_code']!=0:require(rec['effective_exit_code']==raw['exit_code'],'original nonzero process result was changed')
        if phase=='python-runner':
            computed=review_python(log)
            if stem+'-result-review.json' in closed:require(computed==json.loads(closed[stem+'-result-review.json']),'Python original review differs')
            if rec['effective_exit_code']==0:require(computed['pass'],'successful Python gate did not report32/0skip')
        if phase=='tests':
            try:rows,test_review=review_tests(log,baseline)
            except RuntimeError as error:
                parse_error=str(error);require(rec['effective_exit_code']!=0,'successful test gate lacks complete results')
            if test_review is not None:
                require(not test_review['duplicate_execution_ids'] and test_review['counts']==test_review['summary_counts'],'test result rows/summary inconsistent')
                require(test_review['execution_rows']==test_review['unique_test_count'],'duplicate execution IDs')
                if stem+'-test-results.json' in closed:require(rows==json.loads(closed[stem+'-test-results.json']),'original rows differ')
                if stem+'-result-review.json' in closed:require(test_review==json.loads(closed[stem+'-result-review.json']),'original test review differs')
                if rec['effective_exit_code']==0:require(test_review['pass'],'successful test gate did not satisfy original coverage')
        if rec['acceptance_readback'] is not None:
            v=rec['acceptance_readback'];require(v=={'path':stem+'-result-review.json',**data_pin(closed[stem+'-result-review.json'])},'acceptance receipt pin differs')
        receipts.append({'path':stem+'-receipt.json',**data_pin(closed[stem+'-receipt.json'])})
        phases[phase]={'original_exit':raw['exit_code'],'effective_exit':rec['effective_exit_code'],'elapsed_seconds':rec['elapsed_seconds'],'raw':data_pin(closed[stem+'-raw-process-result.json']),'receipt':data_pin(closed[stem+'-receipt.json']),'log':data_pin(log),'resources':data_pin(resources)}
        last_rc=rec['effective_exit_code'];stopped=last_rc!=0
    require(phases and terminal['exit_code']==last_rc and terminal['at_unix_ms']/1000>=last_end,'original outer/phase result differs')
    if last_rc==0:
        require(set(phases)==set(commands),'success lacks all3 phases')
        complete=get('-complete.json');recorded_guard(get('-source-final-verification.json'))
        require(complete['source_tree']==TREE and complete['source_commit']==COMMIT and complete['phase_receipts']==receipts and complete['source_guards_pass'] is True,'original complete phase/source mismatch')
        require(complete['python_exit']==complete['strict_exit']==complete['tests_exit']==0 and complete['python_tests']==32 and complete['python_skipped']==0,'complete counts/results mismatch')
        require(complete['all_old_ids_observed_pass'] is True and complete['required_old_ids']==BASELINE_COUNT,'complete baseline claim mismatch')
        require(PREFIX+'-incomplete.json' not in closed,'complete and incomplete originals conflict')
    else:
        incomplete=get('-incomplete.json');require(incomplete['effective_exit_code']==last_rc and incomplete['completed_phase_receipts']==receipts,'incomplete raw results mismatch')
        require(incomplete['subsequent_phases_started'] is False and incomplete['workspace_started'] is False and incomplete['fix_fmt_executed'] is False,'failed gate continued')
        require(PREFIX+'-complete.json' not in closed,'failed original has complete record')
    failure_blocks=[];derived={}
    if test_review is not None:
        log=closed[PREFIX+'-tests.log'];summary_offset=test_review['summary']['byte_offset']
        for i,row in enumerate(rows):
            if row['status']=='PASS':continue
            end=rows[i+1]['byte_offset'] if i+1<len(rows) else summary_offset
            block=log[row['byte_offset']:end];name='failure-'+str(len(failure_blocks)+1)+'.txt'
            derived['failure-blocks/'+name]=block
            failure_blocks.append({**row,'end_byte_offset':end,'file':name,**data_pin(block)})
        require(len(failure_blocks)==test_review['counts']['FAIL']+test_review['counts']['TIMEOUT'],'failure block count differs')
        bad_ids={(r['binary'],r['name'],r['status']) for r in rows if r['status']!='PASS'}
        footer=test_review['footer_rows_excluded'];require(len(footer)==len(bad_ids) and {(r['binary'],r['name'],r['status']) for r in footer}==bad_ids,'footer failed duplicates differ')
    fail_report={'schema':'hepta.r28-closed-failure-blocks.v1','source_commit':COMMIT,'source_tree':TREE,'original_outer_exit':terminal['exit_code'],'counts':None if test_review is None else test_review['counts'],'reported_skipped':None if test_review is None else test_review['reported_skipped'],'failures':failure_blocks,'test_log_parse_error':parse_error,'skip_identities_inferred':False}
    derived['failure-blocks/INDEX.json']=(json.dumps(fail_report,indent=2)+'\n').encode()
    guidance=set()
    for row in source['changed_files']:
        p=(S/row['path']).parent
        while True:
            if (p/'AGENTS.md').is_file():guidance.add(p/'AGENTS.md')
            if p==S:break
            p=p.parent
    for path in sorted(guidance):add('guidance/'+str(path.relative_to(S)),path)
    final_source=source_guard(source)
    require(final_source==initial_source,'source changed across closed export readback')
    # Re-read every input after collection; the archive cannot mix mutable phases.
    for name,value in read_paths.items():
        raw,mode=stable_read(Path(name));require(data_pin(raw)==value['raw'] and mode==value['mode'],'an original changed before archive: '+name)
    proof={'schema':'hepta.r28-export-source-verification.v1','source_commit':COMMIT,'source_tree':TREE,'source_count':195,'source_manifest':data_pin(source_raw),'source_guard_before':initial_source,'source_guard_after':final_source,'original_phase_results':phases,'original_outer_exit':terminal['exit_code'],'original_test_counts':None if test_review is None else test_review['counts'],'original_reported_skipped':None if test_review is None else test_review['reported_skipped'],'all195_raw_sha_gitblob_gitmode_verified':True,'source50_lock_inherited_not_new_invocation':True,'source51_manifest_preserved_194':True,'export_modifies_source':False,'rust_rerun':False,'workspace_started_by_exporter':False,'fix_fmt_executed_by_exporter':False,'shared_filesystem_free_space_not_measured_or_attributed':True}
    derived['evidence/'+PREFIX+'-export-source-verification.json']=(json.dumps(proof,indent=2)+'\n').encode()
    derived['evidence/'+PREFIX+'-closed-result-review.json']=(json.dumps({'schema':'hepta.r28-export-closed-results.v1','original_test_review':test_review,'phase_results':phases,'outer_original_exit':terminal['exit_code'],'engineering_gate':'PASS' if last_rc==0 else 'FAIL','test_execution_counts':None if test_review is None else test_review['counts'],'reported_skipped':None if test_review is None else test_review['reported_skipped'],'failure_blocks':failure_blocks,'nextest_complete_summary_present':test_review is not None,'parse_error':parse_error,'skip_identities_inferred':False,'archive_export_success_is_not_a_new_gate':True},indent=2)+'\n').encode()
    if test_review is not None:derived['evidence/'+PREFIX+'-closed-test-results.json']=(json.dumps(rows,indent=2)+'\n').encode()
    DERIVED.mkdir(exist_ok=False)
    for name,raw in derived.items():
        path=DERIVED/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as f:f.write(raw)
        require(name not in contents,'derived archive member conflicts with original');contents[name]=raw;modes[name]=0o600
    index={'schema':'hepta.source52-project-closed-index.v1','source_commit':COMMIT,'source_tree':TREE,'source_count':195,'classification':'original_four_package_gate_passed' if last_rc==0 else 'original_four_package_gate_failed','original_outer_exit':terminal['exit_code'],'original_counts':None if test_review is None else test_review['counts'],'reported_skipped':None if test_review is None else test_review['reported_skipped'],'files':[{'path':name,**data_pin(raw),'mode':modes[name]} for name,raw in sorted(contents.items())]}
    contents['INDEX.json']=(json.dumps(index,indent=2)+'\n').encode();modes['INDEX.json']=0o600
    with OUT.open('xb') as f:
        with gzip.GzipFile(filename='',mode='wb',fileobj=f,mtime=0) as gz:
            with tarfile.open(fileobj=gz,mode='w') as tf:
                for name,raw in sorted(contents.items()):
                    info=tarfile.TarInfo(name);info.size=len(raw);info.mode=modes[name];info.mtime=0;tf.addfile(info,io.BytesIO(raw))
    with tarfile.open(OUT,mode='r:gz') as tf:
        packed=tf.getmembers();require(len(packed)==len(contents),'archive member count differs after write')
        for m in packed:require(m.isfile() and tf.extractfile(m).read()==contents[m.name] and m.mode==modes[m.name],'archive readback mismatch')
    result={'path':str(OUT),**data_pin(OUT.read_bytes()),'members':len(contents),'source_count':195,'source_commit':COMMIT,'source_tree':TREE,'original_outer_exit':terminal['exit_code'],'counts':None if test_review is None else test_review['counts'],'reported_skipped':None if test_review is None else test_review['reported_skipped'],'failure_blocks':len(failure_blocks),'derived_directory':str(DERIVED),'rust_or_formatter_executed':False}
    with RESULT.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result),flush=True)


def main():
    check_bindings()  # False/None rejects before any evidence read, write or Git process.
    export_closed()


if __name__=='__main__':
    main()
