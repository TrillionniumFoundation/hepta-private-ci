import hashlib
import json
import lzma
from pathlib import Path


def require(condition, message):
    if not condition:
        raise SystemExit(message)


here = Path(__file__).resolve().parent
repo = here.parents[1]
manifest = json.loads((here / 'manifest.json').read_text())
for entry in manifest['files']:
    raw = (here / entry['file']).read_bytes()
    require(len(raw) == entry['bytes'], f"size mismatch: {entry['file']}")
    require(hashlib.sha256(raw).hexdigest() == entry['sha256'], f"hash mismatch: {entry['file']}")

for path, expected in manifest['tested_source'].items():
    raw = (repo / path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, f'source mismatch: {path}')

logs = {}
for label in ('positive-102217208', 'negative-cleanup-disabled-102217208'):
    receipt = json.loads((here / f'{label}.json').read_text())
    record = receipt['raw_log']
    packed = (here / record['file']).read_bytes()
    raw = lzma.decompress(packed)
    require(len(packed) == record['compressed_bytes'], f'packed size: {label}')
    require(hashlib.sha256(packed).hexdigest() == record['compressed_sha256'], f'packed hash: {label}')
    require(len(raw) == record['bytes'], f'raw size: {label}')
    require(hashlib.sha256(raw).hexdigest() == record['sha256'], f'raw hash: {label}')
    require(receipt['source_hashes_before'] == receipt['source_hashes_after'], f'source changed: {label}')
    before = dict(line.split() for line in receipt['memory_events_before'].splitlines())
    after = dict(line.split() for line in receipt['memory_events_after'].splitlines())
    require(all(before[key] == after[key] for key in ('oom', 'oom_kill', 'oom_group_kill')), f'OOM increment: {label}')
    logs[label] = (receipt, raw.decode('utf-8'))

positive, positive_log = logs['positive-102217208']
negative, negative_log = logs['negative-cleanup-disabled-102217208']
require(positive['exit_code'] == 0, 'positive command did not pass')
require('42 tests run: 42 passed, 0 skipped' in positive_log, 'positive test summary missing')
require(negative['exit_code'] == 100, 'negative command did not return assertion failure')
require('2 tests run: 0 passed, 2 failed, 40 skipped' in negative_log, 'negative test summary missing')
for suffix in ('timed_out_test_binary_git_wrapper_does_not_leave_child_process_running', 'timed_out_exited_test_binary_git_wrapper_does_not_leave_child_process_running'):
    require(f'test git_process::tests::{suffix} ... FAILED' in negative_log, f'negative did not execute: {suffix}')
require(negative_log.count('survived timeout cleanup') >= 2, 'runtime cleanup assertions missing')
require('could not compile' not in negative_log, 'negative compilation failure is not a runtime control')

mutation = json.loads((here / 'negative-cleanup-mutation.json').read_text())
require(mutation['restored_exactly'], 'mutation was not restored')
require(mutation['original_sha256'] == mutation['restored_sha256'], 'restored bytes differ')
require(mutation['original_sha256'] == manifest['tested_source']['codex-rs/git-utils/src/git_process.rs'], 'restored production file is not the tested source')
require(json.loads((here / 'just-fmt.json').read_text())['exit_code'] == 0, 'format did not pass')
print('Verified exact source, bounded original failures, 42 passing tests, two runtime negative controls, restoration and all artifact hashes.')
