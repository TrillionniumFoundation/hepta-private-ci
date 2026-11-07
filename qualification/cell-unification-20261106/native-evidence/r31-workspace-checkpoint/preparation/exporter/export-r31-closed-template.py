#!/usr/bin/env python3
"""Inert R31 closed default-workspace evidence exporter; no gate execution.

Only three future closure maps may be bound after the original job is terminal.
The archive preserves actual originals, including unsuccessful or incomplete
execution, and never fabricates the 18-file successful closure. Archive success is
not engineering qualification or evidence that diagnostic logging repaired a
behavior. The only subprocesses are explicitly allowlisted Git reads.
"""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tarfile

FROZEN = False
TERMINAL_PIN = None
CLOSED_ORIGINAL_PINS = None
CONTROLLER_ORIGINAL_PINS = None

T = Path('/home/alex/work/hepta-cell-unified-20261106-a')
S = T / 'source'
E = T / 'evidence'
PREFIX = 'native-workspace-r31'
COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
TREE = '440d4a8e09af4009e4d9ea067388826308da8803'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
JOB_ID = '1a1b275ba33-fc05-7e17'
JOB_KEY = 'cell-source53-workspace-r31-20261106-v1'
SOURCE_NAME = 'native-candidate-r30-source.json'
SOURCE_PIN = {'bytes': 56747, 'sha256': '9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda', 'git_blob': 'eea9da2308a920486e1bbfd613745d390cde61de'}
RUNNER_NAME = 'native-run-r31.py'
RUNNER_PIN = {'bytes': 128291, 'sha256': '2dc7b84b7dad0d6e150817e0dfc4105c4bb4d343103aacef0fb932eab698a6f9', 'git_blob': '632c55624bb974e939b0bbcf4ab174c948fd7455'}
INPUT_PIN = {'bytes': 23866, 'sha256': 'a07c097b1873b65bf86e8b445ceddebc4f994ca0c39bd7900f1a184a0259c81a', 'git_blob': '3e0f823bcd8986fb6b97a5b032b8042405fa221e'}
BASELINE_NAME = 'source53-app-server-r29-baseline.json'
BASELINE_SHA = '92e7ef41b0c2b08b81bb3ad9542f20ec820d86185f80369b4478cb5bd9c20cf1'
BASELINE_COUNT = 1345
PACKAGES = ['codex-app-server']
LOCKS = {'codex-rs/Cargo.lock': '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c', 'MODULE.bazel.lock': 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'}
R26_PRE_PIN = {'bytes': 7651, 'sha256': 'd1b604225a9162ffd3bfc1b4a372dac755f79ce63fe48e8614920d95682ee118', 'git_blob': '9e919e732f041571afe7b9e1c273d6a45b5ca682'}
R28_PRE_PIN = {'bytes': 9513, 'sha256': '741cd5aa598adecb7d2a2c3a4f976e672aac0b6b84697785bfffbdc6a5ed618e'}
NEW_LEAVES = ('codex-rs/app-server/src/request_processors/account_processor/bedrock_setup.rs', 'codex-rs/app-server/tests/suite/v2/bedrock_setup.rs')
COMMANDS = {'strict': ['just', 'clippy', '--locked', '-p', 'codex-app-server', '--', '-D', 'warnings'], 'tests': ['just', 'test', '--locked', '--retries', '0', '-p', 'codex-app-server']}
ANSI = re.compile(rb'\x1b\[[0-?]*[ -/]*[@-~]')
CONTROLLER_PREFIX = 'r31-controller-closed-'
OUT = E / 'checkpoint-r31-closed.tar.gz'
DERIVED = E / 'r31-closed-export'
RESULT = E / 'checkpoint-r31-export.json'
SUCCESS_SUFFIXES = set(['-source-pre-verification.json', '-environment.json', '-preconditions.json', '-metadata.json', '-metadata-stderr.log', '-metadata-raw-process-result.json', '-metadata-source-post-verification.json', '-metadata-receipt.json', '-scope.json', '-tests-source-pre-verification.json', '-tests.log', '-tests-resources.txt', '-tests-raw-process-result.json', '-source-post-test-verification.json', '-tests-receipt.json', '-test-results.json', '-result-review.json', '-complete.json'])
ALLOWED_SUFFIXES = SUCCESS_SUFFIXES | {'-incomplete.json', '-orchestration-error.json'}


EXPECTED_COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
EXPECTED_TREE = '440d4a8e09af4009e4d9ea067388826308da8803'
SOURCE52_COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
SOURCE52_TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'
SOURCE52_CHANGED_COUNT = 195
FRAMEWORK_PARENT = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
CARGO_LOCK_SHA256 = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
BAZEL_LOCK_SHA256 = 'e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb'
R30_PREFIX = 'native-source53-project-r30'
R30_JOB_ID = '1a1b25b399f-fc05-7daa'
R28_PREFIX = 'native-source52-project-r28'
R28_JOB_ID = '1a1b1e9bee0-fc05-7b7c'
HISTORICAL_FOUR_PACKAGES = ['codex-cli', 'codex-exec-server', 'codex-network-proxy', 'codex-external-agent-migration']
PYTHON_TEST_COUNT = 32
R29_WORKSPACE_BASELINE_INPUT_PINS = {'native-workspace-r29-tests.log': {'bytes': 2499408, 'sha256': '3a95dcc8f0c486594fe3ff41c50fcaaa363bf00533f3ab7d37330e1c757a8559'}, 'native-workspace-r29-test-results.json': {'bytes': 4586810, 'sha256': '2070a63e9b17a64f75f447c39bb3a7d00a91c0273810fdb86ded4656318b9930'}, 'native-workspace-r29-result-review.json': {'bytes': 1775, 'sha256': '6cd91d2003e8fcd5eb576b5db22559683dfa5a4f0259e7a545f07d4580cb9004'}, 'native-workspace-r29-metadata.json': {'bytes': 937659, 'sha256': 'b29d6b0c49c63d6345f50597873e3fa98c79ea0cbfe923ae3dd700b5cc08af8d'}}
METADATA_COMMAND = ['cargo', 'metadata', '--locked', '--no-deps', '--format-version', '1']
COMMAND = ['just', 'test', '--locked', '--retries', '0']

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


def natural_terminal(value):
    require(value['job_id']==JOB_ID and isinstance(value['exit_code'],int),'wrong original gate terminal')
    require(value['state']==('succeeded' if value['exit_code']==0 else 'failed'),'outer state/exit mismatch')
    for key in ('output_complete','output_durable','terminal_publication_confirmed'):require(value[key] is True,'incomplete outer publication')
    for key in ('timed_out','cancelled','automatic_retry'):require(value[key] is False,'not a natural closed gate')
    require(not any(value['log_truncated'].values()) and all(x is None for x in value['log_errors'].values()),'outer output truncated or unavailable')


def source_guard(source):
    require(source['source_commit']==COMMIT and source['source_tree']==TREE,'wrong source53 identity')
    require(source['diagnostic_only'] is True and source['behavior_repair_claimed'] is False,'source53 diagnostic classification changed')
    rows=source['changed_files'];files={row['path']:row for row in rows}
    require(len(files)==len(rows)==197,'wrong source53 changed count')
    require(git('rev-parse','HEAD').decode().strip()==HEAD,'native HEAD changed')
    require(git('write-tree').decode().strip()==TREE,'staged tree changed')
    require(not git('diff','--name-only') and not git('ls-files','--others','--exclude-standard'),'source is not clean/staged only')
    paths=git('diff','--cached','--no-renames','--name-only','-z',HEAD).decode().split('\0')[:-1]
    require(len(paths)==197 and set(paths)==set(files),'changed path set differs')
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
    return {'source_commit':COMMIT,'source_tree':TREE,'native_head':HEAD,'source_count':197,'all_raw_sha_gitblob_gitmode_verified':True,'no_unstaged_untracked_or_extra_paths':True,'cargo_lock_sha256':LOCKS['codex-rs/Cargo.lock'],'bazel_lock_sha256':LOCKS['MODULE.bazel.lock'],'pass':True}


def recorded_guard(value):
    require(value['pass'] is True and value['source_commit']==COMMIT and value['actual_tree']==value['expected_tree']==TREE,'original source guard failed')
    require(value['changed_file_count']==197 and value['native_head']==HEAD and value['changed_path_set_matches'] is True,'original source count/HEAD differs')
    require(value['file_mismatches']==value['unstaged_paths']==value['untracked_paths']==[],'original source guard mismatches')
    require(value['cargo_lock_sha256']==LOCKS['codex-rs/Cargo.lock'] and value['bazel_lock_sha256']==LOCKS['MODULE.bazel.lock'],'original guard dual locks differ')


def clean_lines(raw):
    offset = 0
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        yield number, offset, ANSI.sub(b"", line).decode("utf-8", "replace").rstrip("\r\n")
        offset += len(line)


def check_bindings():
    require(__debug__, 'do not run evidence validation with Python optimization')
    require(FROZEN is True, 'inert exporter: exact closure maps and explicit authorization required')
    require(isinstance(TERMINAL_PIN, dict) and isinstance(CLOSED_ORIGINAL_PINS, dict) and isinstance(CONTROLLER_ORIGINAL_PINS, dict), 'closure maps are not bound')
    for name, pin in CLOSED_ORIGINAL_PINS.items():
        safe_relative(name)
        require('/' not in name and name.startswith(PREFIX) and name[len(PREFIX):] in ALLOWED_SUFFIXES, 'unexpected original producer filename')
        require(isinstance(pin, dict) and isinstance(pin.get('bytes'), int) and pin['bytes'] >= 0 and re.fullmatch('[0-9a-f]{64}', pin.get('sha256', '')), 'invalid original pin')
    require(CLOSED_ORIGINAL_PINS, 'no original gate records supplied')
    for name, pin in CONTROLLER_ORIGINAL_PINS.items():
        safe_relative(name)
        require('/' not in name and name.startswith(CONTROLLER_PREFIX), 'unexpected controller filename')
        require(isinstance(pin, dict) and isinstance(pin.get('bytes'), int) and pin['bytes'] >= 0 and re.fullmatch('[0-9a-f]{64}', pin.get('sha256', '')), 'invalid controller pin')
    suffixes = {n[len(CONTROLLER_PREFIX):] for n in CONTROLLER_ORIGINAL_PINS}
    require({'launch.json', 'terminal-process-status.json'} <= suffixes, 'launch and terminal originals required')
    require(any(re.fullmatch(r'read-[0-9]+\.json', n) for n in suffixes), 'original controller ranges required')
    require(all(n in {'launch.json', 'terminal-process-status.json'} or re.fullmatch(r'read-[0-9]+\.json', n) for n in suffixes), 'unexpected controller member')


def write_new(path, raw):
    with path.open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


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
    additional = sorted(set(current) - baseline)
    unsuccessful = sorted(identity for identity in baseline & set(current) if current[identity]["status"] != "PASS")
    unexpected_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(PACKAGES))
    passed = (
        len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and bool(rows) and counts == expected_counts
        and counts["FAIL"] == counts["TIMEOUT"] == 0
        and not missing and not additional and not unsuccessful and not unexpected_packages
    )
    review = {
        "schema": "hepta.source53-app-server-closed-readback.v1",
        "log": data_pin(raw), "starting": {"line": start[0], "byte_offset": start[1], "text": start[2]},
        "summary": {"line": summary[0], "byte_offset": summary[1], "text": summary[2], "seconds": float(summary[3][1])},
        "unique_test_count": len(current), "execution_rows": len(rows), "counts": counts,
        "summary_counts": expected_counts, "reported_skipped": reported_skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer_rows, "baseline_count": len(baseline),
        "baseline_is_source52_r29_actual_app_server_population": True,
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "baseline_missing": [{"binary": b, "name": n} for b, n in missing],
        "baseline_not_pass": [{"binary": b, "name": n} for b, n in unsuccessful],
        "additional_test_ids": [{"binary": b, "name": n} for b, n in additional],
        "unexpected_packages": unexpected_packages,
        "per_package": {package: {status: sum(row["binary"].split("::", 1)[0] == package and row["status"] == status for row in rows)
                                 for status in ("PASS", "FAIL", "TIMEOUT")} for package in PACKAGES},
        "baseline_used_as_filter": False, "pass": passed,
    }
    return rows, review


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


def verify_inherited_guard(value, label):
    require(value["pass"] is True and value["actual_tree"] == SOURCE52_TREE
            and value["expected_tree"] == SOURCE52_TREE and value["source_commit"] == SOURCE52_COMMIT,
            "recorded source guard identity failed: " + label)
    require(value["native_head"] == FRAMEWORK_PARENT, "recorded native HEAD mismatch: " + label)
    require(value["changed_file_count"] == SOURCE52_CHANGED_COUNT
            and value["changed_path_set_matches"] is True, "recorded source scope mismatch: " + label)
    require(not value["unstaged_paths"] and not value["untracked_paths"] and not value["file_mismatches"],
            "recorded source guard is not clean: " + label)
    require(value["cargo_lock_sha256"] == CARGO_LOCK_SHA256
            and value["bazel_lock_sha256"] == BAZEL_LOCK_SHA256, "recorded dual-lock mismatch: " + label)


def review_inherited_tests(raw, baseline):
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
    unexpected_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(HISTORICAL_FOUR_PACKAGES))
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
                                 for status in ("PASS", "FAIL", "TIMEOUT")} for package in HISTORICAL_FOUR_PACKAGES},
        "baseline_used_as_filter": False, "pass": passed,
    }
    return rows, review


def review_original_workspace(raw, workspace_names):
    lines = list(clean_lines(raw))
    starts = [(n, o, text, re.match(r"^\s*Starting ([0-9]+) tests?\b", text)) for n, o, text in lines]
    starts = [item for item in starts if item[3]]
    summaries = [(n, o, text, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", text)) for n, o, text in lines]
    summaries = [item for item in summaries if item[3]]
    row_pattern = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
    rows, footer = [], []
    start = starts[0] if len(starts) == 1 else None
    summary = summaries[0] if len(summaries) == 1 else None
    for number, offset, text in lines:
        match = row_pattern.match(text)
        if not match:
            continue
        row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
               "line": number, "byte_offset": offset}
        if start and number > start[0] and (summary is None or number < summary[0]):
            rows.append(row)
        elif summary and number > summary[0]:
            footer.append(row)
    current = {(row["binary"], row["name"]): row for row in rows}
    observed_counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "TIMEOUT")}
    summary_counts, skipped, summary_record = None, None, None
    if summary:
        def count(label):
            match = re.search(r"\b([0-9]+) " + label + r"\b", summary[3][3])
            return int(match[1]) if match else 0
        summary_counts = {"PASS": count("passed"), "FAIL": count("failed"), "TIMEOUT": count("timed out")}
        skipped = count("skipped")
        summary_record = {"line": summary[0], "byte_offset": summary[1], "text": summary[2],
                          "seconds": float(summary[3][1]), "tests_run": int(summary[3][2])}
    unknown_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(workspace_names))
    complete = (
        len(starts) == len(summaries) == 1 and start[0] < summary[0]
        and bool(rows) and len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and observed_counts == summary_counts and not unknown_packages
    )
    passed = complete and observed_counts["FAIL"] == observed_counts["TIMEOUT"] == 0
    review = {
        "schema": "hepta.source52-workspace-closed-readback.v1",
        "source_tree": SOURCE52_TREE, "source_commit": SOURCE52_COMMIT, "log": data_pin(raw),
        "starting_lines": [{"line": n, "byte_offset": o, "text": text, "announced_tests": int(m[1])}
                           for n, o, text, m in starts],
        "summary": summary_record, "summary_line_count": len(summaries),
        "nextest_started": bool(starts), "complete_execution_accounting": complete,
        "execution_rows_observed": len(rows), "unique_binary_name_ids_observed": len(current),
        "terminal_unique_test_count": len(current) if complete else None,
        "terminal_counts": observed_counts if complete else None,
        "observed_counts_not_terminal_without_complete_summary": observed_counts,
        "summary_counts": summary_counts, "reported_skipped": skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer, "unknown_workspace_packages": unknown_packages,
        "no_execution_claim_from_compile_failure": True,
        "test_ids_used_as_filter": False, "pass": bool(passed),
    }
    return rows, review


def review_workspace(raw, workspace_names, baseline):
    lines = list(clean_lines(raw))
    starts = [(n, o, text, re.match(r"^\s*Starting ([0-9]+) tests?\b", text)) for n, o, text in lines]
    starts = [item for item in starts if item[3]]
    summaries = [(n, o, text, re.match(r"^\s*Summary\s+\[\s*([0-9.]+)s\]\s+([0-9]+) tests? run:\s*(.*)$", text)) for n, o, text in lines]
    summaries = [item for item in summaries if item[3]]
    row_pattern = re.compile(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$")
    rows, footer = [], []
    start = starts[0] if len(starts) == 1 else None
    summary = summaries[0] if len(summaries) == 1 else None
    for number, offset, text in lines:
        match = row_pattern.match(text)
        if not match:
            continue
        row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
               "line": number, "byte_offset": offset}
        if start and number > start[0] and (summary is None or number < summary[0]):
            rows.append(row)
        elif summary and number > summary[0]:
            footer.append(row)
    current = {(row["binary"], row["name"]): row for row in rows}
    observed_counts = {status: sum(row["status"] == status for row in rows) for status in ("PASS", "FAIL", "TIMEOUT")}
    summary_counts, skipped, summary_record = None, None, None
    if summary:
        def count(label):
            match = re.search(r"\b([0-9]+) " + label + r"\b", summary[3][3])
            return int(match[1]) if match else 0
        summary_counts = {"PASS": count("passed"), "FAIL": count("failed"), "TIMEOUT": count("timed out")}
        skipped = count("skipped")
        summary_record = {"line": summary[0], "byte_offset": summary[1], "text": summary[2],
                          "seconds": float(summary[3][1]), "tests_run": int(summary[3][2])}
    unknown_packages = sorted({row["binary"].split("::", 1)[0] for row in rows} - set(workspace_names))
    complete = (
        len(starts) == len(summaries) == 1 and start[0] < summary[0]
        and bool(rows) and len(rows) == len(current) == int(start[3][1]) == int(summary[3][2])
        and observed_counts == summary_counts and not unknown_packages
    )
    missing = sorted(baseline - set(current))
    additional = sorted(set(current) - baseline)
    unsuccessful = sorted(identity for identity in baseline & set(current) if current[identity]["status"] != "PASS")
    passed = (complete and observed_counts["FAIL"] == observed_counts["TIMEOUT"] == 0
              and not missing and not additional and not unsuccessful)
    review = {
        "schema": "hepta.source53-workspace-closed-readback.v1",
        "source_tree": EXPECTED_TREE, "source_commit": EXPECTED_COMMIT, "log": data_pin(raw),
        "starting_lines": [{"line": n, "byte_offset": o, "text": text, "announced_tests": int(m[1])}
                           for n, o, text, m in starts],
        "summary": summary_record, "summary_line_count": len(summaries),
        "nextest_started": bool(starts), "complete_execution_accounting": complete,
        "execution_rows_observed": len(rows), "unique_binary_name_ids_observed": len(current),
        "terminal_unique_test_count": len(current) if complete else None,
        "terminal_counts": observed_counts if complete else None,
        "observed_counts_not_terminal_without_complete_summary": observed_counts,
        "summary_counts": summary_counts, "reported_skipped": skipped,
        "skip_identities_inferred": False, "duplicate_execution_ids": len(rows) != len(current),
        "footer_rows_excluded": footer, "unknown_workspace_packages": unknown_packages,
        "no_execution_claim_from_compile_failure": True,
        "test_ids_used_as_filter": False, "pass": bool(passed),
        "original_r29_baseline_count": len(baseline),
        "original_r29_baseline_is_failed_population": True,
        "exact_old_test_id_set_required": True,
        "baseline_missing": [{"binary": b, "name": n} for b, n in missing],
        "additional_test_ids": [{"binary": b, "name": n} for b, n in additional],
        "baseline_not_pass": [{"binary": b, "name": n} for b, n in unsuccessful],
        "diagnostic_only": True, "behavior_repair_claimed": False,
    }
    return rows, review


def verify_prior_terminal(value, job_id, expected_exit):
    require(value['job_id'] == job_id and value['exit_code'] == expected_exit
            and value['state'] == ('succeeded' if expected_exit == 0 else 'failed'),
            'historical outer identity/result differs')
    for key in ('output_complete', 'output_durable', 'terminal_publication_confirmed'):
        require(value[key] is True, 'historical outer publication incomplete')
    for key in ('timed_out', 'cancelled', 'automatic_retry'):
        require(value[key] is False, 'historical outer was not natural')
    require(not any(value['log_truncated'].values()) and all(v is None for v in value['log_errors'].values()),
            'historical output was truncated or unavailable')


def preserve_r29_baseline(pre, pinned_input):
    proof = pre['original_r29_workspace_baseline']
    require(proof['schema'] == 'hepta.r31-original-r29-workspace-baseline.v1'
            and proof['source_commit'] == SOURCE52_COMMIT and proof['source_tree'] == SOURCE52_TREE,
            'R29 baseline source identity differs')
    require(proof['identity_key'] == ['binary', 'name'] and proof['count'] == 20228
            and proof['original_failed_100_preserved'] is True and proof['test_ids_used_as_filter'] is False
            and proof['old_metadata_reused_as_current'] is False, 'R29 baseline boundary differs')
    require(len(proof['originals']) == 4 and {p['path'] for p in proof['originals']} == set(R29_WORKSPACE_BASELINE_INPUT_PINS),
            'R29 original baseline files differ')
    originals = {}
    for pointer in proof['originals']:
        raw = pinned_input(pointer, 'input/r29-original-workspace-baseline')
        check_pin(raw, R29_WORKSPACE_BASELINE_INPUT_PINS[pointer['path']], pointer['path'])
        originals[pointer['path']] = raw
    old = 'native-workspace-r29'
    metadata = json.loads(originals[old + '-metadata.json'])
    members, defaults = metadata['workspace_members'], metadata['workspace_default_members']
    packages = {p['id']: p for p in metadata['packages']}
    require(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == 193
            and set(members) == set(defaults) and len(packages) == len(metadata['packages'])
            and set(members) <= set(packages), 'R29 original workspace member identities differ')
    rows, review = review_original_workspace(originals[old + '-tests.log'], {packages[p]['name'] for p in members})
    require(rows == json.loads(originals[old + '-test-results.json'])
            and review == json.loads(originals[old + '-result-review.json']), 'R29 original full-log rows/review differ')
    require(review['complete_execution_accounting'] is True and review['pass'] is False
            and review['terminal_unique_test_count'] == 20228
            and review['terminal_counts'] == {'PASS': 20227, 'FAIL': 1, 'TIMEOUT': 0}
            and review['reported_skipped'] == 130, 'R29 failure population was relabelled')
    require(proof['observed_original_counts'] == review['terminal_counts']
            and proof['original_reported_skipped'] == review['reported_skipped'], 'R29 proof results differ')
    failed = {p['path']: pinned_input(p, 'input/r29-failed-provenance') for p in pre['original_r29_failed_100_provenance']}
    receipt = json.loads(failed[old + '-tests-receipt.json'])
    raw_result = json.loads(failed[old + '-tests-raw-process-result.json'])
    terminal = json.loads(failed[old + '-terminal-process-status.json'])
    require(receipt['source_commit'] == raw_result['source_commit'] == SOURCE52_COMMIT
            and receipt['source_tree'] == raw_result['source_tree'] == SOURCE52_TREE
            and receipt['exit_code'] == raw_result['exit_code'] == receipt['effective_exit_code'] == 100,
            'R29 original raw/receipt failure differs')
    require(terminal['state'] == 'failed' and terminal['exit_code'] == 100, 'R29 outer failure differs')
    require(receipt['log_sha256'] == sha(originals[old + '-tests.log'])
            and receipt['acceptance_readback'] == {'path': old + '-result-review.json', **data_pin(originals[old + '-result-review.json'])},
            'R29 original failed receipt does not bind the full baseline log')
    ids = {(r['binary'], r['name']) for r in rows}
    require(len(ids) == len(rows) == 20228, 'R29 baseline has duplicate identities')
    return ids, {'source_commit': SOURCE52_COMMIT, 'source_tree': SOURCE52_TREE,
                 'count': len(ids), 'counts': review['terminal_counts'], 'reported_skipped': review['reported_skipped'],
                 'failed_100_preserved': True, 'used_as_filter': False}


def preserve_prior_project(pre, env, pinned_input, kind):
    historical = kind == 'r28'
    name = 'source52_r28_historical_project_gate' if historical else 'r30_closed_gate_readback'
    proof = pre[name]
    prefix = R28_PREFIX if historical else R30_PREFIX
    commit, tree, count = (SOURCE52_COMMIT, SOURCE52_TREE, 195) if historical else (COMMIT, TREE, 197)
    phases = ('python-runner', 'strict', 'tests') if historical else ('strict', 'tests')
    expected_count = 26 if historical else 19
    require(proof['source_commit'] == commit and proof['source_tree'] == tree, 'prior project source identity differs')
    expected_names = {prefix + suffix for suffix in ('-environment.json', '-preconditions.json',
        '-source-pre-verification.json', '-source-final-verification.json', '-complete.json',
        '-tests-test-results.json', '-tests-result-review.json')}
    for phase in phases:
        expected_names |= {prefix + '-' + phase + suffix for suffix in (
            '.log', '-resources.txt', '-raw-process-result.json', '-receipt.json',
            '-source-pre-verification.json', '-source-post-verification.json')}
    if historical:
        expected_names.add(prefix + '-python-runner-result-review.json')
    require(len(proof['originals']) == expected_count and {p['path'] for p in proof['originals']} == expected_names,
            'prior project original set differs')
    originals = {p['path']: pinned_input(p, 'input/' + kind + '-prerequisites') for p in proof['originals']}
    outer = json.loads(pinned_input(proof['outer_terminal'], 'input/' + kind + '-prerequisites'))
    verify_prior_terminal(outer, R28_JOB_ID if historical else R30_JOB_ID, 0)
    prior_env = json.loads(originals[prefix + '-environment.json'])
    require(prior_env['selection'] == env['selection']
            and prior_env['approved_prerequisite_env_pin'] == env['approved_prerequisite_env_pin'],
            'current and prior environment/prerequisite selection differs')
    previous_pre = json.loads(originals[prefix + '-preconditions.json'])
    baseline_raw = pinned_input(previous_pre['baseline'], 'input/' + kind + '-baseline')
    baseline_object = json.loads(baseline_raw)
    ids = {(row['binary'], row['name']) for row in baseline_object['test_ids']}
    expected_ids = 1564 if historical else 1345
    require(len(ids) == len(baseline_object['test_ids']) == expected_ids, 'prior project baseline identity count differs')
    if not historical:
        require(previous_pre['baseline']['path'] == BASELINE_NAME and sha(baseline_raw) == BASELINE_SHA,
                'R30 exact app-server baseline differs')
    else:
        require(proof['historical_source52_all_three_phases_and_outer_pass'] is True
                and proof['source53_execution_claimed'] is False and proof['substitutes_for_r30'] is False,
                'historical source52 project was relabelled as source53 qualification')
    def prior_guard(value):
        if historical:
            verify_inherited_guard(value, 'r28 prerequisite')
        else:
            recorded_guard(value)
    prior_guard(json.loads(originals[prefix + '-source-pre-verification.json']))
    prior_guard(json.loads(originals[prefix + '-source-final-verification.json']))
    package_names = HISTORICAL_FOUR_PACKAGES if historical else PACKAGES
    args = [value for package in package_names for value in ('-p', package)]
    commands = {
        'strict': ['just', 'clippy', '--locked', *args, '--', '-D', 'warnings'],
        'tests': (['just', 'test', '--locked', *args, '--retries', '0'] if historical
                  else ['just', 'test', '--locked', '--retries', '0', *args]),
        'python-runner': ['python3', '-m', 'unittest', 'discover', '-s', 'scripts', '-p', 'test_run_nextest*.py', '-v'],
    }
    receipt_pins = []
    end = None
    for phase in phases:
        stem = prefix + '-' + phase
        raw_bytes, rec_bytes = originals[stem + '-raw-process-result.json'], originals[stem + '-receipt.json']
        raw, rec = json.loads(raw_bytes), json.loads(rec_bytes)
        require(raw['source_commit'] == rec['source_commit'] == commit and raw['source_tree'] == rec['source_tree'] == tree,
                'prior phase source identity differs')
        require(raw['phase'] == phase and raw['command'] == commands[phase]
                and raw['cwd'] == str(S if phase == 'python-runner' else S / 'codex-rs'), 'prior phase command differs')
        require(raw['exit_code'] == rec['exit_code'] == rec['effective_exit_code'] == 0
                and rec['phase_pass'] is True and rec['issues'] == [], 'prior project phase is not actual PASS')
        for key in ('phase', 'command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
            require(raw[key] == rec[key], 'prior raw/receipt differs: ' + key)
        require(raw['end_unix'] >= raw['start_unix'] and (end is None or raw['start_unix'] >= end)
                and outer['at_unix_ms'] / 1000 >= raw['end_unix'], 'prior phase time order differs')
        end = raw['end_unix']
        require(rec['raw_process_result'] == {'path': stem + '-raw-process-result.json', **data_pin(raw_bytes)},
                'prior raw pointer differs')
        require(rec['log_sha256'] == sha(originals[stem + '.log'])
                and rec['resources_sha256'] == sha(originals[stem + '-resources.txt'])
                and re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$', originals[stem + '-resources.txt'], re.M) == [b'0'],
                'prior log/resources/result differ')
        prior_guard(json.loads(originals[stem + '-source-pre-verification.json']))
        post = json.loads(originals[stem + '-source-post-verification.json'])
        prior_guard(post)
        require(post['gate_exit_code'] == 0 and rec['source_guards_pass'] is True
                and rec['source_postguard'] == {'path': stem + '-source-post-verification.json', **data_pin(originals[stem + '-source-post-verification.json'])},
                'prior postguard pointer differs')
        if phase == 'python-runner':
            computed = review_python(originals[stem + '.log'])
            require(computed['pass'] is True and computed == json.loads(originals[stem + '-result-review.json']),
                    'historical Python32 complete log differs')
        if phase == 'tests':
            rows, computed = (review_inherited_tests if historical else review_tests)(originals[stem + '.log'], ids)
            require(computed['pass'] is True and len(rows) == expected_ids
                    and {(row['binary'], row['name']) for row in rows} == ids,
                    'prior full project exact identity population did not pass')
            require(rows == json.loads(originals[stem + '-test-results.json'])
                    and computed == json.loads(originals[stem + '-result-review.json']), 'prior complete rows/review differ')
        if rec['acceptance_readback'] is not None:
            acceptance = stem + '-result-review.json'
            require(rec['acceptance_readback'] == {'path': acceptance, **data_pin(originals[acceptance])},
                    'prior acceptance pointer differs')
        receipt_pins.append({'path': stem + '-receipt.json', **data_pin(rec_bytes)})
    complete = json.loads(originals[prefix + '-complete.json'])
    require(complete['source_commit'] == commit and complete['source_tree'] == tree
            and complete['source_guards_pass'] is True and complete['phase_receipts'] == receipt_pins
            and proof['phase_receipts'] == receipt_pins, 'prior complete identity/receipt binding differs')
    require(complete['strict_exit'] == complete['tests_exit'] == 0
            and complete['all_old_ids_observed_pass'] is True and complete['fix_fmt_executed'] is False,
            'prior complete result differs')
    if historical:
        require(complete['python_exit'] == 0 and proof['python_tests'] == 32 and proof['python_skipped'] == 0,
                'historical Python phase differs')
    else:
        require(proof['same_source_strict_full_tests_and_outer_pass'] is True and proof['exact_old_test_id_set'] is True
                and complete['diagnostic_only'] is True and complete['behavior_repair_claimed'] is False,
                'R30 source53 project classification differs')
        require(proof['source53_apply'] == pre['source53_apply'], 'R30 and R31 apply provenance differs')
    require(complete['cargo_lock_sha256'] == LOCKS['codex-rs/Cargo.lock']
            and complete['bazel_lock_sha256'] == LOCKS['MODULE.bazel.lock'], 'prior dual lock identity differs')
    return {'source_commit': commit, 'source_tree': tree, 'source_count': count,
            'original_count': expected_count, 'outer_exit': 0, 'baseline_count': expected_ids,
            'full_logs_reparsed': True, 'historical_only': historical,
            'qualifies_current_workspace': False, 'terminal_at_unix_ms': outer['at_unix_ms']}


def review_closed_workspace(closed, terminal, baseline, baseline_proof, prerequisites):
    """Preserve nonzero raw returns and absent originals; never fabricate success."""
    errors = []
    def attempt(label, operation, default=None):
        try:
            return operation()
        except Exception as error:
            errors.append({'stage': label, 'error': repr(error)})
            return default
    def get(suffix):
        return json.loads(closed[PREFIX + suffix])
    def identity(value):
        require(value['source_commit'] == COMMIT and value['source_tree'] == TREE, 'current original source differs')
    def classification(value):
        require(value['diagnostic_only'] is True and value['behavior_repair_claimed'] is False,
                'current diagnostic classification differs')
    def pointer(value, name):
        require(value == {'path': name, **data_pin(closed[name])}, 'original pointer differs: ' + name)
    for suffix in ('-environment.json', '-preconditions.json'):
        attempt(suffix + ':identity', lambda suffix=suffix: identity(get(suffix)))
        attempt(suffix + ':classification', lambda suffix=suffix: classification(get(suffix)))
    attempt('initial_guard', lambda: recorded_guard(get('-source-pre-verification.json')))
    metadata = scope = metadata_rec = None
    metadata_rc = attempt('metadata:raw', lambda: get('-metadata-raw-process-result.json'))
    metadata_receipt = attempt('metadata:receipt', lambda: get('-metadata-receipt.json'))
    def verify_metadata():
        raw_bytes = closed[PREFIX + '-metadata.json']
        value = json.loads(raw_bytes)
        raw, receipt = metadata_rc, metadata_receipt
        require(raw is not None and receipt is not None, 'metadata raw or receipt absent')
        for item in (raw, receipt):
            identity(item)
            require(item['command'] == METADATA_COMMAND and item['cwd'] == str(S / 'codex-rs')
                    and item['exit_code'] == 0, 'metadata invocation differs or failed')
        require(raw['schema'] == 'hepta.native-raw-process-result.v1' and raw['phase'] == 'workspace-metadata'
                and receipt['schema'] == 'hepta.native-metadata-receipt.v1', 'metadata schema/phase differs')
        for key in ('command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
            require(raw[key] == receipt[key], 'metadata raw/receipt differs: ' + key)
        require(raw['resources_not_collected_for_read_only_metadata'] is True
                and raw['end_unix'] >= raw['start_unix']
                and raw['start_unix'] * 1000 >= prerequisites['r30']['terminal_at_unix_ms'],
                'metadata prerequisite/time boundary differs')
        require(abs(receipt['elapsed_seconds'] - (raw['end_unix'] - raw['start_unix'])) < 1e-6,
                'metadata elapsed differs')
        pointer(receipt['raw_process_result'], PREFIX + '-metadata-raw-process-result.json')
        pointer(receipt['source_postguard'], PREFIX + '-metadata-source-post-verification.json')
        require(receipt['stdout'] == data_pin(raw_bytes)
                and receipt['stderr'] == data_pin(closed[PREFIX + '-metadata-stderr.log'])
                and receipt['source_guards_pass'] is True, 'metadata output/guard binding differs')
        recorded_guard(get('-metadata-source-post-verification.json'))
        require(value['workspace_root'] == str(S / 'codex-rs') and value['target_directory'] == str(T / 'target'),
                'metadata root/target differs')
        members, defaults = value['workspace_members'], value['workspace_default_members']
        packages = {p['id']: p for p in value['packages']}
        require(len(members) == len(set(members)) == len(defaults) == len(set(defaults)) == 193
                and set(members) == set(defaults) and len(packages) == len(value['packages'])
                and set(members) <= set(packages), 'actual fresh 193/default identities differ')
        expected_scope = {
            'schema': 'hepta.source53-current-default-workspace-scope.v1', 'source_tree': TREE, 'source_commit': COMMIT,
            'metadata_command': METADATA_COMMAND, 'metadata': {'path': PREFIX + '-metadata.json', **data_pin(raw_bytes)},
            'metadata_generated_on_current_source': True, 'old_metadata_reused_as_current': False,
            'workspace_root': value['workspace_root'], 'target_directory': value['target_directory'],
            'workspace_member_count': len(members), 'workspace_default_member_count': len(defaults),
            'workspace_members': [{'id': pid, 'name': packages[pid]['name'], 'manifest_path': packages[pid]['manifest_path']} for pid in members],
            'workspace_default_members': [{'id': pid, 'name': packages[pid]['name']} for pid in defaults],
            'command': COMMAND, 'features': 'unchanged_defaults', 'filters': 'no_additions',
            'all_platforms_features_external_services_qualified': False, 'diagnostic_only': True, 'behavior_repair_claimed': False,
        }
        actual_scope = get('-scope.json')
        require(actual_scope == expected_scope, 'scope does not reproduce current fresh metadata/original ordering')
        return value, actual_scope, receipt
    verified_metadata = attempt('metadata:full_readback', verify_metadata)
    if verified_metadata is not None:
        metadata, scope, metadata_rec = verified_metadata
    raw = attempt('workspace:raw_json', lambda: get('-tests-raw-process-result.json'))
    receipt = attempt('workspace:receipt_json', lambda: get('-tests-receipt.json'))
    rows, review, parse_error = [], None, None
    raw_exit = raw.get('exit_code') if isinstance(raw, dict) else None
    effective_exit = receipt.get('effective_exit_code') if isinstance(receipt, dict) else None
    def verify_raw():
        require(raw is not None, 'workspace raw return absent')
        identity(raw)
        require(raw['schema'] == 'hepta.native-raw-process-result.v1' and raw['phase'] == 'workspace-tests'
                and raw['command'] == COMMAND and raw['cwd'] == str(S / 'codex-rs'), 'workspace raw command/phase differs')
        require(isinstance(raw['exit_code'], int) and raw['end_unix'] >= raw['start_unix']
                and terminal['at_unix_ms'] / 1000 >= raw['end_unix'], 'workspace raw time/exit differs')
        require(metadata_rec is not None and raw['start_unix'] >= metadata_rec['end_unix'],
                'workspace began without verified current metadata')
    attempt('workspace:raw_identity', verify_raw)
    for suffix in ('-tests-source-pre-verification.json', '-source-post-test-verification.json'):
        attempt(suffix, lambda suffix=suffix: recorded_guard(get(suffix)))
    if PREFIX + '-tests.log' in closed and scope is not None:
        try:
            rows, review = review_workspace(closed[PREFIX + '-tests.log'], {p['name'] for p in scope['workspace_members']}, baseline)
        except Exception as error:
            parse_error = repr(error)
            errors.append({'stage': 'workspace:parser', 'error': parse_error})
    def verify_receipt():
        require(receipt is not None and raw is not None, 'workspace receipt/raw absent')
        identity(receipt); classification(receipt)
        require(receipt['schema'] == 'hepta.native-workspace-gate-receipt.v2', 'workspace receipt schema differs')
        for key in ('source_commit', 'source_tree', 'phase', 'command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
            require(raw[key] == receipt[key], 'workspace raw/receipt differs: ' + key)
        require(receipt['source_manifest'] == SOURCE_NAME and receipt['source_manifest_sha256'] == SOURCE_PIN['sha256']
                and receipt['environment_manifest'] == PREFIX + '-environment.json', 'workspace receipt source/environment differs')
        pointer(receipt['raw_process_result'], PREFIX + '-tests-raw-process-result.json')
        pointer(receipt['source_preguard'], PREFIX + '-tests-source-pre-verification.json')
        pointer(receipt['source_postguard'], PREFIX + '-source-post-test-verification.json')
        pointer(receipt['scope'], PREFIX + '-scope.json')
        require(receipt['log_sha256'] == sha(closed[PREFIX + '-tests.log'])
                and receipt['resources_sha256'] == sha(closed[PREFIX + '-tests-resources.txt']), 'workspace output hashes differ')
        require(re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$', closed[PREFIX + '-tests-resources.txt'], re.M) == [str(raw_exit).encode()],
                'workspace resource exit differs')
        post = get('-source-post-test-verification.json')
        require(post['phase'] == 'workspace-tests' and post['gate_exit_code'] == raw_exit
                and receipt['source_guards_pass'] is True, 'workspace postguard result differs')
        require(receipt['phase_pass'] is (effective_exit == 0) and terminal['exit_code'] == effective_exit
                and (raw_exit == 0 or effective_exit == raw_exit), 'workspace outer/effective/raw result differs')
        require(abs(receipt['elapsed_seconds'] - (raw['end_unix'] - raw['start_unix'])) < 1e-6,
                'workspace elapsed differs')
        require(receipt['test_scope'] == 'original_default_workspace' and receipt['packages_argument'] is None
                and receipt['workspace_member_count'] == receipt['workspace_default_member_count'] == 193
                and receipt['retries'] == 0 and receipt['filters'] == 'no_additions'
                and receipt['features'] == 'unchanged_defaults' and receipt['fix_fmt_executed'] is False
                and receipt['outer_timeout_seconds_contract'] == 9600,
                'workspace original no-p/default selection differs')
        require(receipt['original_r29_workspace_baseline'] == baseline_proof
                and receipt['test_ids_used_as_filter'] is False and receipt['exact_old_test_id_set_required'] is True,
                'workspace baseline proof/usage differs')
        if receipt['acceptance_readback'] is not None:
            pointer(receipt['acceptance_readback'], PREFIX + '-result-review.json')
        if effective_exit == 0:
            require(raw_exit == 0 and receipt['issues'] == [] and review is not None and review['pass'] is True,
                    'successful receipt lacks exact full PASS accounting')
    attempt('workspace:receipt_readback', verify_receipt)
    if review is not None:
        def verify_results():
            for name, value in ((PREFIX + '-test-results.json', rows), (PREFIX + '-result-review.json', review)):
                require(name in closed and json.loads(closed[name]) == value, 'original rows/review differs or absent: ' + name)
            if effective_exit == 0:
                require(review['complete_execution_accounting'] is True and review['pass'] is True
                        and review['terminal_unique_test_count'] == 20228, 'successful gate does not have exact20228 PASS')
        attempt('workspace:original_result_readback', verify_results)

    complete = attempt('complete:json', lambda: get('-complete.json')) if PREFIX + '-complete.json' in closed else None
    incomplete = attempt('incomplete:json', lambda: get('-incomplete.json')) if PREFIX + '-incomplete.json' in closed else None
    orchestration = attempt('orchestration:json', lambda: get('-orchestration-error.json')) if PREFIX + '-orchestration-error.json' in closed else None
    if complete is not None:
        def verify_complete():
            identity(complete); classification(complete)
            require(complete['schema'] == 'hepta.source53-default-workspace-complete.v1', 'complete schema differs')
            require(set(closed) == {PREFIX + suffix for suffix in SUCCESS_SUFFIXES}, 'successful closure is not exactly18 original files')
            require(terminal['exit_code'] == raw_exit == effective_exit == 0 and review is not None and review['pass'] is True,
                    'complete record without natural full PASS')
            require(complete['source_manifest'] == SOURCE_NAME and complete['source_manifest_sha256'] == SOURCE_PIN['sha256']
                    and complete['cargo_lock_sha256'] == LOCKS['codex-rs/Cargo.lock']
                    and complete['bazel_lock_sha256'] == LOCKS['MODULE.bazel.lock'], 'complete source/locks differ')
            require(complete['workspace_exit'] == complete['effective_exit_code'] == 0
                    and complete['command'] == COMMAND and complete['source_guards_pass'] is True
                    and complete['workspace_member_count'] == complete['workspace_default_member_count'] == 193,
                    'complete command/scope/exit differs')
            require(complete['unique_test_count'] == review['terminal_unique_test_count']
                    and complete['counts'] == review['terminal_counts'] and complete['reported_skipped'] == review['reported_skipped'],
                    'complete counts differ')
            pointer(complete['receipt'], PREFIX + '-tests-receipt.json')
            pointer(complete['readback'], PREFIX + '-result-review.json')
            pointer(complete['scope'], PREFIX + '-scope.json')
            require(complete['original_r29_workspace_baseline'] == baseline_proof
                    and complete['exact_old_test_id_set_observed_pass'] is True
                    and complete['test_ids_used_as_filter'] is False
                    and complete['original_r29_failure_relabelled_as_pass'] is False
                    and complete['fix_fmt_executed'] is False
                    and complete['all_platforms_features_external_services_qualified'] is False,
                    'complete historical/qualification boundary differs')
        attempt('complete:readback', verify_complete)
    if incomplete is not None:
        def verify_incomplete():
            identity(incomplete); classification(incomplete)
            require(complete is None and terminal['exit_code'] != 0
                    and incomplete['original_exit_code'] == raw_exit
                    and incomplete['effective_exit_code'] == effective_exit == terminal['exit_code'], 'incomplete result differs')
            pointer(incomplete['receipt'], PREFIX + '-tests-receipt.json')
            require(incomplete['terminal_counts'] == (review['terminal_counts'] if review is not None else None)
                    and incomplete['nextest_started'] == (review['nextest_started'] if review is not None else None),
                    'incomplete counts/started differs')
            require(incomplete['fix_fmt_executed'] is False and incomplete['no_automatic_retry'] is True
                    and incomplete['source_retained'] is True, 'incomplete retry/scope differs')
        attempt('incomplete:readback', verify_incomplete)
    if orchestration is not None:
        def verify_orchestration():
            identity(orchestration); classification(orchestration)
            require(orchestration['schema'] == 'hepta.source53-workspace-orchestration-error.v1'
                    and orchestration['no_automatic_retry'] is True and orchestration['source_retained'] is True
                    and orchestration['fix_fmt_executed'] is False and terminal['exit_code'] != 0,
                    'orchestration error identity/boundary differs')
        attempt('orchestration:readback', verify_orchestration)
    if terminal['exit_code'] == 0 and complete is None:
        errors.append({'stage': 'outer_success', 'error': 'original complete absent; no success inferred'})
    if terminal['exit_code'] != 0 and incomplete is None and orchestration is None:
        errors.append({'stage': 'outer_failure', 'error': 'no original incomplete/error; existing originals preserved'})
    passed = terminal['exit_code'] == 0 and complete is not None and review is not None and review['pass'] and not errors
    return {'rows': rows, 'review': review, 'parse_error': parse_error, 'readback_errors': errors,
            'metadata': None if metadata is None else data_pin(closed[PREFIX + '-metadata.json']),
            'metadata_raw_exit': None if metadata_rc is None else metadata_rc.get('exit_code'),
            'metadata_receipt_exit': None if metadata_receipt is None else metadata_receipt.get('exit_code'),
            'original_workspace_exit': raw_exit, 'effective_workspace_exit': effective_exit,
            'original_complete_present': complete is not None, 'original_incomplete_present': incomplete is not None,
            'original_orchestration_error_present': orchestration is not None,
            'engineering_gate': 'PASS' if passed else ('FAIL' if terminal['exit_code'] != 0 else 'READBACK_INCOMPLETE')}


def export_closed():
    require(not OUT.exists() and not DERIVED.exists() and not RESULT.exists(), 'create-only export output already exists')
    contents = {}; modes = {}; read_paths = {}
    def add(name, path, expected=None):
        safe_relative(name); raw, mode = stable_read(path)
        if expected is not None:
            check_pin(raw, expected, name)
        if name in contents:
            require(contents[name] == raw and modes[name] == mode, 'duplicate member differs: ' + name)
        else:
            contents[name] = raw; modes[name] = mode
        read_paths[str(path)] = {'raw': data_pin(raw), 'mode': mode}
        return raw
    def pinned_input(pin, directory):
        rel = str(safe_relative(pin['path']))
        return add(directory + '/' + rel, E / rel, pin)
    terminal_name = PREFIX + '-terminal-process-status.json'
    terminal_raw = add('evidence/' + terminal_name, E / terminal_name, TERMINAL_PIN)
    terminal = json.loads(terminal_raw); natural_terminal(terminal)
    source_raw = add('input/' + SOURCE_NAME, E / SOURCE_NAME, SOURCE_PIN)
    source = json.loads(source_raw); initial_source = source_guard(source)
    for row in source['changed_files']:
        add('source/' + row['path'], S / row['path'], row)
    for path, digest in LOCKS.items():
        require(sha(add('locks/' + path, S / path)) == digest, 'raw lock copy differs')
    actual_names = set()
    for path in E.glob(PREFIX + '-*'):
        require(path.is_file() and not path.is_symlink(), 'unexpected producer path type')
        if path.name != terminal_name:
            actual_names.add(path.name)
    require(actual_names == set(CLOSED_ORIGINAL_PINS), 'closure binding omits or invents producer originals')
    for name, pin in CLOSED_ORIGINAL_PINS.items():
        add('evidence/' + name, E / name, pin)
    closed = {n: contents['evidence/' + n] for n in CLOSED_ORIGINAL_PINS}
    # These inputs were already closed at the actual metadata/workspace start; if any becomes
    # unavailable, stop rather than produce an incomplete source-provenance pack.
    pre = json.loads(closed[PREFIX + '-preconditions.json'])
    env = json.loads(closed[PREFIX + '-environment.json'])
    for value in (pre, env):
        require(value['source_commit'] == COMMIT and value['source_tree'] == TREE and value['diagnostic_only'] is True and value['behavior_repair_claimed'] is False, 'original source/classification differs')
    require(pre['actual_changed_file_count'] == 197 and pre['source_manifest'] == {'path': SOURCE_NAME, **data_pin(source_raw)}, 'original full manifest not bound')
    require(pre['patch_application_performed'] is False and pre['lock_update_performed'] is False and pre['python_suite_reexecuted'] is False and pre['fix_fmt_executed'] is False and pre['workspace_test_command'] == COMMAND and pre['historical_project_pass_substitutes_for_r30'] is False, 'original workspace action scope differs')
    require(env['source_manifest'] == SOURCE_NAME and env['source_manifest_sha256'] == SOURCE_PIN['sha256'] and env['original_default_workspace_selection'] is True and env['fresh_current_source_metadata_required'] is True and env['outer_timeout_seconds_contract'] == 9600 and env['test_deadlines_features_filters_retries_unchanged'] is True and env['sandbox_or_network_protection_environment_overridden'] is False, 'original workspace environment differs')
    for key, value in {'RUSTUP_TOOLCHAIN': '1.96.0', 'CARGO_BUILD_JOBS': '2', 'NEXTEST_TEST_THREADS': '2', 'CARGO_TARGET_DIR': str(T / 'target'), 'CARGO_PROFILE_TEST_DEBUG': '0', 'CARGO_PROFILE_DEV_DEBUG': '0', 'NEXTEST_PROFILE': None, 'HEPTA_NEXTTEST_FULL_METADATA': None, 'CARGO_INCREMENTAL': None, 'CARGO_BUILD_TARGET': None, 'RUSTFLAGS': None, 'PYTHONOPTIMIZE': None}.items():
        require(env['selection'][key] == value, 'original selection environment differs: ' + key)
    baseline, baseline_readback = preserve_r29_baseline(pre, pinned_input)
    baseline_proof = pre['original_r29_workspace_baseline']
    prerequisites = {kind: preserve_prior_project(pre, env, pinned_input, kind) for kind in ('r30', 'r28')}
    source50 = json.loads(pinned_input(pre['source50_root_manifest'], 'input/ancestor-manifests'))
    source51 = json.loads(pinned_input(pre['source51_historical_manifest'], 'input/ancestor-manifests'))
    source52 = json.loads(pinned_input(pre['source52_parent_manifest'], 'input/ancestor-manifests'))
    old = {r['path']: r for r in source52['changed_files']}; new = {r['path']: r for r in source['changed_files']}
    require(len(old) == 195 and set(new) == set(old) | set(NEW_LEAVES) and not set(old).intersection(NEW_LEAVES), 'two pre-existing new changed-manifest leaves differ')
    require(all(new[p] == r for p, r in old.items()), 'original195 rows changed')
    require(source52['source_commit'] == '1e0910becc37383e6d17ecf861ea844fd07d8862' and source52['source_tree'] == '211f15baff19095e8c98bcea2b0ed99ca2270ade', 'wrong parent source52')
    require(source51['source_commit'] == 'e28b0f385ee882f842911044958b2810f62f6379' and source51['source_tree'] == '763c8d2b4089f6e9806c3bbb68fa247bc2f6af36', 'wrong source51 ancestor')
    require(source50['source_commit'] == '1fdd647b0ecb235530e8b88bbea45b3d3762906f' and source50['source_tree'] == 'ea48acf562499192a25e05ae28926a32632dee62', 'wrong source50 lock ancestor')
    for value in (pre, source50, source51, source52):
        require(value['cargo_lock_sha256'] == LOCKS['codex-rs/Cargo.lock'] and value['bazel_lock_sha256'] == LOCKS['MODULE.bazel.lock'], 'ancestor lock pins differ')
    for key, directory in (('source50_lock_originals_and_outer_terminal', 'source50-lock-prerequisites'), ('original_r24_failed_100_provenance', 'r24-failed-provenance'), ('original_r26_failed_100_provenance', 'r26-failed-provenance'), ('original_r29_failed_100_provenance', 'r29-failed-provenance')):
        for pin in pre[key]:
            pinned_input(pin, 'input/' + directory)
    add('input/environment/agentd-prerequisite-env.json', E / 'agentd-prerequisite-env.json', env['approved_prerequisite_env_pin'])
    for name, pin, key in (('native-source51-project-r26-preconditions.json', R26_PRE_PIN, 'source51_apply'), ('native-source52-project-r28-preconditions.json', R28_PRE_PIN, 'source52_apply')):
        ancestor = json.loads(add('input/ancestor-preconditions/' + name, E / name, pin))
        for field in ('complete', 'terminal', 'source_postguard', 'delta_manifest'):
            pinned_input(ancestor[key][field], 'input/' + key + '-prerequisites')
    for field in ('complete', 'terminal', 'source_postguard', 'delta_manifest'):
        pinned_input(pre['source53_apply'][field], 'input/source53-apply-pins')
    apply_dir = E / 'native-source53-apply'
    require(apply_dir.is_dir() and not apply_dir.is_symlink(), 'source53 apply originals missing')
    for path in sorted(apply_dir.rglob('*')):
        require(not path.is_symlink(), 'symlink in apply originals')
        if path.is_file():
            add('input/source53-apply-prerequisites/' + str(path.relative_to(apply_dir)), path)
    original_input = add('input/source53-apply-input.tar.gz', T / 'source53-apply-input.tar.gz', INPUT_PIN)
    with tarfile.open(fileobj=io.BytesIO(original_input), mode='r:gz') as tf:
        members = {}
        for m in tf.getmembers():
            safe_relative(m.name)
            require(m.isfile() and not m.issym() and not m.islnk() and m.name not in members, 'unsafe apply archive member')
            members[m.name] = tf.extractfile(m).read()
            require(len(members[m.name]) == m.size, 'apply member size differs')
        require(set(members) == {'candidate.patch', 'delta-manifest.json', 'source53-manifest.json'} | {side + '/' + path for path in NEW_LEAVES for side in ('before', 'after')}, 'wrong seven-member apply input')
        require(members['source53-manifest.json'] == source_raw, 'apply/fullmanifest differs')
        delta = json.loads(members['delta-manifest.json'])
        require(delta['diagnostic_only'] is True and delta['behavior_repair_claimed'] is False and {x['path'] for x in delta['files']} == set(NEW_LEAVES), 'apply diagnostic delta differs')
        check_pin(members['candidate.patch'], delta['patch'], 'candidate.patch')
        for row in delta['files']:
            for side in ('before', 'after'):
                check_pin(members[side + '/' + row['path']], row[side], side + '/' + row['path'])
            require(data_pin(members['after/' + row['path']]) == {k: new[row['path']][k] for k in ('bytes', 'sha256', 'git_blob')}, 'apply after source differs')
    add('input/' + RUNNER_NAME, T / RUNNER_NAME, RUNNER_PIN)
    controller = {}
    for name, pin in CONTROLLER_ORIGINAL_PINS.items():
        base = name[len(CONTROLLER_PREFIX):]
        raw = add('controller/' + base, E / name, pin)
        if base == 'terminal-process-status.json':
            require(raw == terminal_raw, 'controller/gate terminal raw bytes differ')
        controller[base] = json.loads(raw)
    launch = controller['launch.json']; job = launch['job']
    require(job['id'] == JOB_ID and job['launch_state'] == 'launched' and launch['launch']['ok'] is True and launch['reused'] is False, 'wrong original launch')
    require(job['host'] == 'pocket4' and job['executable'] == '/usr/bin/python3' and job['args'] == [str(T / RUNNER_NAME)] and job['cwd'] == str(T), 'original direct-file runner launch differs')
    require(job['idempotency_key'] == JOB_KEY and job['env_keys'] == [], 'original launch key/environment differs')
    for stream in ('stdout', 'stderr'):
        chunks = []
        for name, value in controller.items():
            if not name.startswith('read-'):
                continue
            require(value['job_id'] == JOB_ID, 'controller read job differs')
            v = value[stream]; raw = bytes.fromhex(v['bytes_hex'])
            require(len(raw) == v['next_offset'] - v['offset'] and v['size'] >= v['next_offset'] and v['text'].encode() == raw, 'controller range/text/hex differs')
            chunks.append((v['offset'], raw))
        end = 0; parts = []
        for offset, raw in sorted(chunks, key=lambda x: x[0]):
            if not raw:
                require(offset <= end, 'empty controller read beyond known output'); continue
            require(offset == end, 'controller output gap/overlap')
            parts.append(raw); end += len(raw)
        require(terminal['log_bytes'][stream]['seen'] == terminal['log_bytes'][stream]['stored'] == end, 'controller original output incomplete')
        contents['controller/original-' + stream + '.txt'] = b''.join(parts)
        modes['controller/original-' + stream + '.txt'] = 0o600
    readback = review_closed_workspace(closed, terminal, baseline, baseline_proof, prerequisites)
    rows = readback['rows']; review = readback['review']; derived = {}; failure_blocks = []
    if review is not None:
        log = closed[PREFIX + '-tests.log']
        for i, row in enumerate(rows):
            if row['status'] == 'PASS':
                continue
            end = rows[i + 1]['byte_offset'] if i + 1 < len(rows) else (review['summary']['byte_offset'] if review['summary'] is not None else len(log))
            require(row['byte_offset'] <= end <= len(log), 'failure block range differs')
            block = log[row['byte_offset']:end]
            name = 'failure-' + str(len(failure_blocks) + 1) + '.txt'
            derived['failure-blocks/' + name] = block
            failure_blocks.append({**row, 'end_byte_offset': end, 'file': name, **data_pin(block)})
        footer = review['footer_rows_excluded']
        ids = {(r['binary'], r['name'], r['status']) for r in rows if r['status'] != 'PASS'}
        if review['complete_execution_accounting'] and (len(footer) != len(ids) or {(r['binary'], r['name'], r['status']) for r in footer} != ids):
            readback['readback_errors'].append({'stage': 'footer', 'error': 'reported failure duplicates differ from execution IDs'})
            if readback['engineering_gate'] == 'PASS':
                readback['engineering_gate'] = 'READBACK_INCOMPLETE'
    guidance = set()
    for row in source['changed_files']:
        p = (S / row['path']).parent
        while True:
            if (p / 'AGENTS.md').is_file():
                guidance.add(p / 'AGENTS.md')
            if p == S:
                break
            p = p.parent
    for path in sorted(guidance):
        add('guidance/' + str(path.relative_to(S)), path)
    final_source = source_guard(source)
    require(final_source == initial_source, 'source changed during closed readback')
    for name, value in read_paths.items():
        raw, mode = stable_read(Path(name))
        require(data_pin(raw) == value['raw'] and mode == value['mode'], 'original changed before archive: ' + name)
    common = {'source_commit': COMMIT, 'source_tree': TREE, 'source_count': 197,
              'diagnostic_only': True, 'behavior_repair_claimed': False,
              'original_outer_exit': terminal['exit_code'], 'original_gate_result': readback['engineering_gate'],
              'original_workspace_exit': readback['original_workspace_exit'], 'effective_workspace_exit': readback['effective_workspace_exit'],
              'counts': None if review is None else review['terminal_counts'], 'reported_skipped': None if review is None else review['reported_skipped'],
              'complete_execution_accounting': None if review is None else review['complete_execution_accounting'],
              'nextest_started': None if review is None else review['nextest_started'],
              'readback_errors': readback['readback_errors'], 'all_platforms_features_external_services_qualified': False,
              'fresh_metadata_rerun_by_exporter': False, 'fix_fmt_executed_by_exporter': False,
              'archive_export_success_is_not_a_gate_pass': True}
    def derived_json(name, value):
        derived[name] = (json.dumps(value, indent=2) + '\n').encode()
    derived_json('failure-blocks/INDEX.json', {'schema': 'hepta.r31-closed-failure-blocks.v1', **common, 'failures': failure_blocks, 'parse_error': readback['parse_error'], 'skip_identities_inferred': False})
    derived_json('evidence/' + PREFIX + '-export-source-verification.json', {'schema': 'hepta.r31-export-source-verification.v1', **common, 'source_manifest': data_pin(source_raw), 'source_guard_before': initial_source, 'source_guard_after': final_source, 'all197_raw_sha_gitblob_gitmode_verified': True, 'source52_manifest_original195_preserved': True, 'source50_lock_inherited_not_new_invocation': True, 'source_modified_by_exporter': False, 'rust_or_formatter_executed': False, 'metadata_executed': False, 'current_R30_project_prerequisite': prerequisites['r30'], 'historical_source52_R28_project_prerequisite': prerequisites['r28'], 'original_failed_R29_baseline': baseline_readback, 'fresh_metadata': readback['metadata']})
    derived_json('evidence/' + PREFIX + '-closed-result-review.json', {'schema': 'hepta.r31-export-closed-results.v1', **common, 'actual_original_filenames': sorted(closed), 'missing_success_filenames': sorted({PREFIX + s for s in SUCCESS_SUFFIXES} - set(closed)), 'original_workspace_review': review, 'metadata_raw_exit': readback['metadata_raw_exit'], 'metadata_receipt_exit': readback['metadata_receipt_exit'], 'original_complete_present': readback['original_complete_present'], 'original_incomplete_present': readback['original_incomplete_present'], 'original_orchestration_error_present': readback['original_orchestration_error_present'], 'failure_blocks': failure_blocks, 'test_log_parse_error': readback['parse_error'], 'nextest_complete_summary_present': bool(review is not None and review['complete_execution_accounting']), 'archive_export_success_is_not_a_gate_pass': True, 'skip_identities_inferred': False})
    if review is not None:
        derived_json('evidence/' + PREFIX + '-closed-test-results.json', rows)
    DERIVED.mkdir(exist_ok=False)
    for name, raw in derived.items():
        path = DERIVED / name; path.parent.mkdir(parents=True, exist_ok=True)
        write_new(path, raw)
        require(name not in contents, 'derived member conflicts with original')
        contents[name] = raw; modes[name] = 0o600
    index = {'schema': 'hepta.source53-workspace-closed-index.v1', **common,
             'classification': 'DIAGNOSTIC_ONLY_ORIGINAL_DEFAULT_WORKSPACE_GATE',
             'files': [{'path': name, **data_pin(raw), 'mode': modes[name]} for name, raw in sorted(contents.items())]}
    contents['INDEX.json'] = (json.dumps(index, indent=2) + '\n').encode(); modes['INDEX.json'] = 0o600
    with OUT.open('xb') as f:
        with gzip.GzipFile(filename='', mode='wb', fileobj=f, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode='w') as tf:
                for name, raw in sorted(contents.items()):
                    info = tarfile.TarInfo(name); info.size = len(raw); info.mode = modes[name]; info.mtime = 0
                    tf.addfile(info, io.BytesIO(raw))
        f.flush(); os.fsync(f.fileno())
    with tarfile.open(OUT, mode='r:gz') as tf:
        packed = tf.getmembers()
        require(len(packed) == len(contents) and len({m.name for m in packed}) == len(packed), 'archive count/duplicates differ')
        for member in packed:
            require(member.isfile() and tf.extractfile(member).read() == contents[member.name] and member.mode == modes[member.name], 'archive raw readback differs')
    result = {'schema': 'hepta.r31-archive-export-result.v1', 'path': str(OUT), **data_pin(OUT.read_bytes()),
              **common, 'members': len(contents), 'actual_original_count': len(closed),
              'failure_blocks': len(failure_blocks), 'derived_directory': str(DERIVED),
              'rust_or_formatter_executed': False, 'archive_export_complete': True}
    write_new(RESULT, (json.dumps(result, indent=2) + '\n').encode())
    try:
        print(json.dumps(result), flush=True)
    except OSError:
        pass


def main():
    check_bindings()  # False/None rejects before any read, write or subprocess.
    export_closed()


if __name__ == '__main__':
    main()
