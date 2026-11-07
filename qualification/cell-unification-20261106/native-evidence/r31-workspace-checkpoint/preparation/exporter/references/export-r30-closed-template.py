#!/usr/bin/env python3
"""Inert R30 closed app-server evidence exporter; no gate execution.

Only three future closure maps may be bound after the original job is terminal.
The archive preserves actual originals, including unsuccessful or incomplete
phases, and never fabricates the 19-file successful closure. Archive success is
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
PREFIX = 'native-source53-project-r30'
COMMIT = 'f74be175de66a4b351cd239d39d98cd34fe9cc1b'
TREE = '440d4a8e09af4009e4d9ea067388826308da8803'
HEAD = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
JOB_ID = '1a1b25b399f-fc05-7daa'
JOB_KEY = 'cell-source53-project-r30-20261106-v1'
SOURCE_NAME = 'native-candidate-r30-source.json'
SOURCE_PIN = {'bytes': 56747, 'sha256': '9292bd9002716a0bec35ecea294f9dfef3dbb1e9c1d8fe66660e502aecc5cdda', 'git_blob': 'eea9da2308a920486e1bbfd613745d390cde61de'}
RUNNER_NAME = 'native-run-r30.py'
RUNNER_PIN = {'bytes': 61214, 'sha256': 'b72407252efdaf81d8e3bc5280c3fa7ad9afb36fa398869e8023daaa392ff3c8', 'git_blob': '3c41e24997e2113f0028a58b70f8e646b76ac47e'}
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
CONTROLLER_PREFIX = 'r30-controller-closed-'
OUT = E / 'checkpoint-r30-closed.tar.gz'
DERIVED = E / 'r30-closed-export'
RESULT = E / 'checkpoint-r30-export.json'
SUCCESS_SUFFIXES = {'-environment.json', '-preconditions.json', '-source-pre-verification.json', '-source-final-verification.json', '-complete.json', '-tests-test-results.json', '-tests-result-review.json'} | {f'-{phase}{suffix}' for phase in COMMANDS for suffix in ('-source-pre-verification.json', '.log', '-resources.txt', '-raw-process-result.json', '-source-post-verification.json', '-receipt.json')}
ALLOWED_SUFFIXES = SUCCESS_SUFFIXES | {'-incomplete.json', '-orchestration-error.json'}


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


def review_closed_originals(closed, terminal, baseline):
    """Pure readback. Missing/invalid originals stay missing and are reported.

    Output preservation is separate from qualification. An orchestration failure
    can leave a raw return without a later receipt; that original return remains
    visible. A compile failure has null test counts when no complete summary exists.
    """
    errors = []
    def attempt(label, fn, default=None):
        try:
            return fn()
        except Exception as error:
            errors.append({'stage': label, 'error': repr(error)})
            return default
    def get(suffix):
        return json.loads(closed[PREFIX + suffix])
    def identity(value):
        require(value['source_commit'] == COMMIT and value['source_tree'] == TREE, 'original source identity differs')
    def classification(value):
        require(value['diagnostic_only'] is True and value['behavior_repair_claimed'] is False, 'diagnostic classification differs')
    for suffix in ('-environment.json', '-preconditions.json'):
        if PREFIX + suffix in closed:
            attempt(suffix + ':identity', lambda s=suffix: identity(get(s)))
            attempt(suffix + ':classification', lambda s=suffix: classification(get(s)))
        else:
            errors.append({'stage': suffix, 'error': 'original absent; no replacement created'})
    if PREFIX + '-source-pre-verification.json' in closed:
        attempt('initial_source_guard', lambda: recorded_guard(get('-source-pre-verification.json')))
    else:
        errors.append({'stage': 'initial_source_guard', 'error': 'original absent'})

    phases = {}
    receipt_pins = []
    rows = []
    review = None
    parse_error = None
    last_end = None
    last_effective = None
    for phase, command in COMMANDS.items():
        stem = PREFIX + '-' + phase
        names = {suffix: stem + suffix for suffix in ('-raw-process-result.json', '-receipt.json', '.log', '-resources.txt', '-source-pre-verification.json', '-source-post-verification.json')}
        present = {suffix: name in closed for suffix, name in names.items()}
        if not any(present.values()):
            phases[phase] = {'observed_original_files': [], 'original_exit': None, 'effective_exit': None, 'execution_started_from_raw_return': None}
            continue
        raw = attempt(phase + ':raw_json', lambda: json.loads(closed[names['-raw-process-result.json']])) if present['-raw-process-result.json'] else None
        rec = attempt(phase + ':receipt_json', lambda: json.loads(closed[names['-receipt.json']])) if present['-receipt.json'] else None
        entry = {'observed_original_files': [n for n in names.values() if n in closed],
                 'missing_expected_phase_files': [n for n in names.values() if n not in closed],
                 'original_exit': raw.get('exit_code') if isinstance(raw, dict) else None,
                 'effective_exit': rec.get('effective_exit_code') if isinstance(rec, dict) else None,
                 'execution_started_from_raw_return': raw is not None,
                 'original_receipt_issues': rec.get('issues') if isinstance(rec, dict) else None,
                 'pins': {n: data_pin(closed[n]) for n in names.values() if n in closed}}
        phases[phase] = entry
        if raw is None:
            errors.append({'stage': phase + ':raw_return', 'error': 'no decodable original raw return; not inferred from outer state'})
        else:
            def verify_raw():
                identity(raw)
                require(raw['schema'] == 'hepta.native-raw-process-result.v1' and raw['phase'] == phase and raw['command'] == command and raw['cwd'] == str(S / 'codex-rs'), 'raw command/schema differs')
                require(isinstance(raw['exit_code'], int) and raw['end_unix'] >= raw['start_unix'], 'invalid raw exit/time')
                require(last_end is None or raw['start_unix'] >= last_end, 'phase time order differs')
                require(terminal['at_unix_ms'] / 1000 >= raw['end_unix'], 'terminal predates raw return')
                if phase == 'tests':
                    prior = phases.get('strict', {})
                    require(prior.get('original_exit') == prior.get('effective_exit') == 0, 'tests started without original strict PASS')
            attempt(phase + ':raw_identity', verify_raw)
            last_end = raw.get('end_unix')
        for side in ('pre', 'post'):
            name = names['-source-' + side + '-verification.json']
            if name in closed:
                attempt(phase + ':' + side + '_guard', lambda n=name: recorded_guard(json.loads(closed[n])))
            else:
                errors.append({'stage': phase + ':' + side + '_guard', 'error': 'original absent'})
        if rec is None:
            errors.append({'stage': phase + ':receipt', 'error': 'original absent or undecodable; raw return retained'})
        else:
            receipt_pins.append({'path': names['-receipt.json'], **data_pin(closed[names['-receipt.json']])})
            def verify_receipt():
                identity(rec); classification(rec)
                require(rec['schema'] == 'hepta.native-gate-receipt.v2', 'receipt schema differs')
                require(raw is not None, 'receipt has no original raw return')
                for key in ('phase', 'source_commit', 'source_tree', 'command', 'cwd', 'start_unix', 'end_unix', 'exit_code'):
                    require(raw[key] == rec[key], 'raw/receipt differs: ' + key)
                require(rec['raw_process_result'] == {'path': names['-raw-process-result.json'], **data_pin(closed[names['-raw-process-result.json']])}, 'raw receipt pin differs')
                require(rec['source_manifest'] == SOURCE_NAME and rec['source_manifest_sha256'] == SOURCE_PIN['sha256'], 'receipt manifest differs')
                require(rec['environment_manifest'] == PREFIX + '-environment.json', 'receipt environment differs')
                require(rec['log_sha256'] == sha(closed[names['.log']]) and rec['resources_sha256'] == sha(closed[names['-resources.txt']]), 'log/resources differ')
                require(re.findall(rb'^\s*Exit status: (-?[0-9]+)\s*$', closed[names['-resources.txt']], re.M) == [str(raw['exit_code']).encode()], 'resource return differs')
                post = json.loads(closed[names['-source-post-verification.json']])
                require(post['gate_exit_code'] == raw['exit_code'], 'postguard return differs')
                require(rec['source_postguard'] == {'path': names['-source-post-verification.json'], **data_pin(closed[names['-source-post-verification.json']])}, 'postguard receipt pin differs')
                require(rec['source_guards_pass'] is True, 'original source guard failed')
                require(abs(rec['elapsed_seconds'] - (raw['end_unix'] - raw['start_unix'])) < 1e-6, 'phase elapsed differs')
                require(rec['packages'] == PACKAGES and rec['retries'] == (0 if phase == 'tests' else None), 'scope/retry differs')
                require(rec['filters'] == 'no_additions' and rec['features'] == 'unchanged_defaults' and rec['baseline_used_as_filter'] is False and rec['fix_fmt_executed'] is False, 'phase settings differ')
                require(rec['phase_pass'] is (rec['effective_exit_code'] == 0), 'effective receipt inconsistent')
                if raw['exit_code'] != 0:
                    require(rec['effective_exit_code'] == raw['exit_code'], 'original nonzero return changed')
                if rec['effective_exit_code'] == 0:
                    require(rec['issues'] == [], 'successful receipt has issues')
                if rec['acceptance_readback'] is not None:
                    rn = stem + '-result-review.json'
                    require(rec['acceptance_readback'] == {'path': rn, **data_pin(closed[rn])}, 'original acceptance pin differs')
            attempt(phase + ':receipt_readback', verify_receipt)
            last_effective = rec.get('effective_exit_code')
        if phase == 'tests' and names['.log'] in closed:
            try:
                rows, review = review_tests(closed[names['.log']], baseline)
            except Exception as error:
                parse_error = repr(error)
                if entry['effective_exit'] == 0:
                    errors.append({'stage': 'tests:parse', 'error': parse_error})
            if review is not None:
                def verify_test_records():
                    require(not review['duplicate_execution_ids'] and review['execution_rows'] == review['unique_test_count'] and review['counts'] == review['summary_counts'], 'execution/summary accounting differs')
                    for suffix, value in (('-test-results.json', rows), ('-result-review.json', review)):
                        name = stem + suffix
                        require(name in closed, 'original test result absent: ' + name)
                        require(json.loads(closed[name]) == value, 'original test result differs: ' + name)
                    if entry['effective_exit'] == 0:
                        require(review['pass'] is True, 'successful raw log does not satisfy exact1345 original IDs')
                attempt('tests:complete_result_readback', verify_test_records)

    complete = None
    incomplete = None
    error_record = None
    if PREFIX + '-complete.json' in closed:
        complete = attempt('complete:json', lambda: get('-complete.json'))
    if PREFIX + '-incomplete.json' in closed:
        incomplete = attempt('incomplete:json', lambda: get('-incomplete.json'))
    if PREFIX + '-orchestration-error.json' in closed:
        error_record = attempt('orchestration_error:json', lambda: get('-orchestration-error.json'))
    if complete is not None:
        def verify_complete():
            identity(complete); classification(complete)
            require(complete['schema'] == 'hepta.source53-project-gates-complete.v1', 'complete schema differs')
            require(set(closed) == {PREFIX + s for s in SUCCESS_SUFFIXES}, 'successful closure is not exactly19 original files')
            require(terminal['exit_code'] == 0 and all(phases[p]['original_exit'] == phases[p]['effective_exit'] == 0 for p in COMMANDS), 'complete original returns are not all0')
            require(complete['phase_receipts'] == receipt_pins and complete['source_guards_pass'] is True, 'complete phase pins differ')
            require(complete['strict_exit'] == complete['tests_exit'] == 0 and complete['packages'] == PACKAGES, 'complete scope differs')
            require(complete['source_manifest'] == SOURCE_NAME and complete['source_manifest_sha256'] == SOURCE_PIN['sha256'], 'complete source manifest differs')
            require(complete['cargo_lock_sha256'] == LOCKS['codex-rs/Cargo.lock'] and complete['bazel_lock_sha256'] == LOCKS['MODULE.bazel.lock'], 'complete locks differ')
            require(complete['required_old_ids'] == BASELINE_COUNT and complete['all_old_ids_observed_pass'] is True and review is not None and review['pass'] is True, 'complete exact baseline not met')
            require(complete['workspace_not_started_by_this_runner'] is True and complete['fix_fmt_executed'] is False and complete['python_suite_reexecuted'] is False and complete['source53_bazel_lock_update_executed'] is False, 'complete actions differ')
            require(complete['source50_lock_inherited_for_unchanged_dependency_inputs'] is True and complete['source53_apply_complete'] == get('-preconditions.json')['source53_apply']['complete'], 'complete provenance differs')
            require(complete['original_r29_failure_relabelled_as_pass'] is False and complete['whole_workspace_qualification'] == 'PENDING_SEPARATE_ORIGINAL_GATE', 'diagnostic or workspace scope differs')
            recorded_guard(get('-source-final-verification.json'))
        attempt('complete:readback', verify_complete)
    if incomplete is not None:
        def verify_incomplete():
            identity(incomplete); classification(incomplete)
            require(complete is None and terminal['exit_code'] != 0, 'incomplete conflicts with success')
            require(incomplete['effective_exit_code'] == terminal['exit_code'] == last_effective and incomplete['completed_phase_receipts'] == receipt_pins, 'incomplete returns/pins differ')
            require(incomplete['failed_phase'] in COMMANDS and phases[incomplete['failed_phase']]['effective_exit'] != 0, 'incomplete failed phase differs')
            require(incomplete['subsequent_phases_started'] is False and incomplete['source_retained'] is True and incomplete['workspace_started'] is False and incomplete['fix_fmt_executed'] is False, 'incomplete continuation differs')
        attempt('incomplete:readback', verify_incomplete)
    if error_record is not None:
        def verify_error():
            identity(error_record); classification(error_record)
            require(error_record['schema'] == 'hepta.source53-project-orchestration-error.v1' and error_record['no_automatic_retry'] is True and error_record['source_retained'] is True, 'orchestration error provenance differs')
            require(error_record['workspace_started'] is False and error_record['fix_fmt_executed'] is False and terminal['exit_code'] != 0, 'orchestration error scope differs')
        attempt('orchestration_error:readback', verify_error)
    if terminal['exit_code'] == 0 and complete is None:
        errors.append({'stage': 'outer_success', 'error': 'original complete absent; no success inferred'})
    if terminal['exit_code'] != 0 and incomplete is None and error_record is None:
        errors.append({'stage': 'outer_failure', 'error': 'original incomplete/error absent; actual existing originals retained'})
    passed = terminal['exit_code'] == 0 and complete is not None and review is not None and review['pass'] and not errors
    return {'phases': phases, 'rows': rows, 'review': review, 'parse_error': parse_error,
            'readback_errors': errors, 'original_complete_present': complete is not None,
            'original_incomplete_present': incomplete is not None, 'original_orchestration_error_present': error_record is not None,
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
    # These three inputs were already closed at strict-start; if any becomes
    # unavailable, stop rather than produce an incomplete source-provenance pack.
    pre = json.loads(closed[PREFIX + '-preconditions.json'])
    env = json.loads(closed[PREFIX + '-environment.json'])
    for value in (pre, env):
        require(value['source_commit'] == COMMIT and value['source_tree'] == TREE and value['diagnostic_only'] is True and value['behavior_repair_claimed'] is False, 'original source/classification differs')
    require(pre['actual_changed_file_count'] == 197 and pre['source_manifest'] == {'path': SOURCE_NAME, **data_pin(source_raw)}, 'original full manifest not bound')
    require(pre['patch_application_performed_by_this_runner'] is False and pre['lock_update_performed_by_this_runner'] is False and pre['python_suite_reexecuted'] is False, 'original gate action scope differs')
    baseline_raw = pinned_input(pre['baseline'], 'input/baseline')
    require(pre['baseline']['path'] == BASELINE_NAME and sha(baseline_raw) == BASELINE_SHA, 'wrong original app-server baseline')
    baseline_value = json.loads(baseline_raw)
    baseline = {(r['binary'], r['name']) for r in baseline_value['test_ids']}
    require(len(baseline) == len(baseline_value['test_ids']) == BASELINE_COUNT, 'invalid exact app-server baseline')
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
    readback = review_closed_originals(closed, terminal, baseline)
    rows = readback['rows']; review = readback['review']; derived = {}; failure_blocks = []
    if review is not None:
        log = closed[PREFIX + '-tests.log']
        for i, row in enumerate(rows):
            if row['status'] == 'PASS':
                continue
            end = rows[i + 1]['byte_offset'] if i + 1 < len(rows) else review['summary']['byte_offset']
            block = log[row['byte_offset']:end]
            name = 'failure-' + str(len(failure_blocks) + 1) + '.txt'
            derived['failure-blocks/' + name] = block
            failure_blocks.append({**row, 'end_byte_offset': end, 'file': name, **data_pin(block)})
        footer = review['footer_rows_excluded']
        ids = {(r['binary'], r['name'], r['status']) for r in rows if r['status'] != 'PASS'}
        if len(footer) != len(ids) or {(r['binary'], r['name'], r['status']) for r in footer} != ids:
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
              'counts': None if review is None else review['counts'], 'reported_skipped': None if review is None else review['reported_skipped'],
              'readback_errors': readback['readback_errors'], 'workspace_qualification': 'NOT_ESTABLISHED_BY_THIS_PROJECT_EXPORT'}
    def derived_json(name, value):
        derived[name] = (json.dumps(value, indent=2) + '\n').encode()
    derived_json('failure-blocks/INDEX.json', {'schema': 'hepta.r30-closed-failure-blocks.v1', **common, 'failures': failure_blocks, 'parse_error': readback['parse_error'], 'skip_identities_inferred': False})
    derived_json('evidence/' + PREFIX + '-export-source-verification.json', {'schema': 'hepta.r30-export-source-verification.v1', **common, 'source_manifest': data_pin(source_raw), 'source_guard_before': initial_source, 'source_guard_after': final_source, 'all197_raw_sha_gitblob_gitmode_verified': True, 'source52_manifest_original195_preserved': True, 'source50_lock_inherited_not_new_invocation': True, 'source_modified_by_exporter': False, 'rust_or_formatter_executed': False})
    derived_json('evidence/' + PREFIX + '-closed-result-review.json', {'schema': 'hepta.r30-export-closed-results.v1', **common, 'actual_original_filenames': sorted(closed), 'missing_success_filenames': sorted({PREFIX + s for s in SUCCESS_SUFFIXES} - set(closed)), 'original_test_review': review, 'phase_results': readback['phases'], 'original_complete_present': readback['original_complete_present'], 'original_incomplete_present': readback['original_incomplete_present'], 'original_orchestration_error_present': readback['original_orchestration_error_present'], 'failure_blocks': failure_blocks, 'test_log_parse_error': readback['parse_error'], 'nextest_complete_summary_present': review is not None, 'archive_export_success_is_not_a_gate_pass': True, 'skip_identities_inferred': False})
    if review is not None:
        derived_json('evidence/' + PREFIX + '-closed-test-results.json', rows)
    DERIVED.mkdir(exist_ok=False)
    for name, raw in derived.items():
        path = DERIVED / name; path.parent.mkdir(parents=True, exist_ok=True)
        write_new(path, raw)
        require(name not in contents, 'derived member conflicts with original')
        contents[name] = raw; modes[name] = 0o600
    index = {'schema': 'hepta.source53-project-closed-index.v1', **common,
             'classification': 'DIAGNOSTIC_ONLY_ORIGINAL_APP_SERVER_GATE',
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
    result = {'schema': 'hepta.r30-archive-export-result.v1', 'path': str(OUT), **data_pin(OUT.read_bytes()),
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
