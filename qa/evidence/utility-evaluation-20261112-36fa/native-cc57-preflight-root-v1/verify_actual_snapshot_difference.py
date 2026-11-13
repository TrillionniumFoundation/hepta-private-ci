"""Offline Root review of completed originals; no H or workspace mutation."""
from pathlib import Path
import base64
import datetime
import gzip
import hashlib
import json
import os

OUT = Path('/tmp/hepta-36fa-native-cc57-preflight-investigation-v1')
OBS = Path('/tmp/hepta-36fa-native-precondition-snapshot-diagnostic-v1')
NATIVE = Path('/tmp/hepta-36fa-native-gates-cc57-v1')
CANONICAL = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def main():
    origin_raw = CANONICAL.read_bytes()
    assert identity(origin_raw)['sha256'] == '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'
    origin = json.loads(origin_raw)
    assert origin['tracked_entries'] == origin['filesystem_entries'] == 15188
    original_stdout = (OBS / 'STDOUT.complete.log').read_bytes()
    observed = json.loads(original_stdout)
    assert observed['status'] == 'completed_readonly_diagnostic'
    assert observed['native_job_id'] == '1a1d26326ac-2564-1cd4'
    assert observed['source_job_id'] == '1a1d23c92f3-2564-1cb4'
    assert observed['source_or_record_writes'] is False
    assert observed['cargo_formatter_or_gate_commands'] is False
    assert observed['qualification'] is False
    assert observed['origin_complete_identity'] == identity(origin_raw)
    assert observed['row_counts'] == {'added': 0, 'changed': 7, 'removed': 0, 'unchanged': 15181}
    diff_packed = base64.b64decode(observed['diff_gzip_base64'], validate=True)
    assert identity(diff_packed) == observed['diff_gzip_identity']
    diff_raw = gzip.decompress(diff_packed)
    assert diff_raw == (OBS / 'SNAPSHOT_DIFF.original.json').read_bytes()
    assert identity(diff_raw) == observed['diff_raw_identity']
    diff = json.loads(diff_raw)
    assert len(diff) == 7 and len({r['path'] for r in diff}) == 7
    projected = []
    for row in sorted(origin['files'], key=lambda r: os.fsencode(r['path'])):
        assert row['matches_index'] and row['stable'] and row['kind'] in ('file', 'symlink')
        assert row['index_blob'] == row['working_blob']
        projected.append({'path': row['path'], 'bytes': row['bytes'], 'mode': row['index_mode'],
                          'blob': row['working_blob'], 'sha256': row['sha256']})
    expected_raw = compact(projected)
    assert identity(expected_raw) == observed['expected_native_identity']
    assert identity(expected_raw)['sha256'] == '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9'
    by_path = {r['path']: r for r in projected}
    for row in diff:
        assert row['kind'] == 'changed'
        assert row['before'] == by_path[row['path']]
        assert row['before']['mode'] == '100644'
        assert row['path'].startswith('qualification/')
        assert row['after'] == {'path': row['path'], 'missing': True}
        by_path[row['path']] = row['after']
    recovered = compact([by_path[r['path']] for r in projected])
    assert identity(recovered) == observed['actual_native_identity']
    assert recovered == (OBS / 'source-after.files.EXACT_RECOVERED.json').read_bytes()
    recovered_gzip = gzip.compress(recovered, mtime=0)
    assert recovered_gzip == (OBS / 'source-after.files.EXACT_RECOVERED.json.gz').read_bytes()
    original_gzip = next(r for r in observed['observations'] if r['label'] == 'native_gzip')
    assert original_gzip['full_bounded_read'] is True
    assert identity(recovered_gzip) == original_gzip['identity']
    refs = observed['refs_command']
    assert refs['returncode'] == 0 and refs['timed_out'] is False and refs['actual_terminal'] == 'observed'
    refs_stdout = base64.b64decode(refs['stdout_base64'], validate=True)
    refs_stderr = base64.b64decode(refs['stderr_base64'], validate=True)
    assert identity(refs_stdout) == refs['stdout'] and identity(refs_stderr) == refs['stderr']
    assert refs_stdout == (OBS / 'REFS.stdout.original').read_bytes()
    assert refs_stdout == b'refs/retired-artifacts/20261112-r71/3b03227b9431ee012e6b cc57c7198db6293ccca562253c42fffbe2a04633\n'
    assert refs_stderr == b''
    wrapper_raw = (NATIVE / 'RESULT.json').read_bytes()
    wrapper = json.loads(wrapper_raw)
    assert wrapper['status'] == 'failed' and wrapper['behavioral_tests_started'] is False
    assert wrapper['stages'] == [] and wrapper['source_before'] is None
    assert wrapper['source_comparison'] == 'unknown_missing_before'
    assert wrapper['error'] == 'ValueError: unchanged detached HEAD/no refs'
    report = {
        'format': 'hepta-root-actual-native-precondition-difference-review-v1',
        'reviewed_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status': 'COMPLETE_RETAINED_SNAPSHOT_DIFFERENCE_VERIFIED_NO_REPAIR',
        'source': 'cc57c7198db6293ccca562253c42fffbe2a04633',
        'tree': 'b7b357c07b5539769a068c6b9b009629f5612d1e',
        'original_source_job': observed['source_job_id'],
        'original_native_job': observed['native_job_id'],
        'actual_readonly_observer': '1a1d27152aa-2564-1ce4',
        'original_wrapper_result': identity(wrapper_raw),
        'original_wrapper_status': wrapper['status'],
        'original_source_comparison': wrapper['source_comparison'],
        'behavioral_test_outcomes_observed': 0,
        'real_qualified_task_chain_outcomes': 0,
        'source_full_inventory': identity(origin_raw),
        'expected_native_compact': identity(expected_raw),
        'failed_native_compact': identity(recovered),
        'failed_native_original_gzip': identity(recovered_gzip),
        'actual_observer_stdout': identity(original_stdout),
        'complete_original_difference': identity(diff_raw),
        'rows': observed['row_counts'],
        'missing_original_bytes_total': sum(r['before']['bytes'] for r in diff),
        'missing_rows': diff,
        'current_ref_observed_by_readonly_command': refs_stdout.decode().rstrip('\n'),
        'index_body_read_or_parsed': False,
        'writer_or_cause': 'Unknown',
        'scope': 'All seven differences are missing tracked historical qualification archives. The 15181 remaining five-field rows are equal. This is not a serializer difference. Reconstructed complete failed raw and gzip bytes match the actual bounded original read; reconstruction is not another physical observation.',
        'timing_scope': 'The current refs enumeration was observed at 1ce4. The two file inventories describe the retained 1cb4 and 1cd4 execution snapshots, not the live workspace at Root review time.',
        'classification': 'Precondition rejection before any behavioral test. Neither complete NoUpdate/Ineligible nor evidence of Objective Fraud. Do not replace Unknown with an invented writer or mechanism.',
        'recovery_direction': 'Preserve the drifted old directory and its ref/index. Independently verify exact source objects, then separately review fresh isolated materialization and its actual proof before any successor native admission.',
        'recovery_or_new_native_execution_authorized_by_this_report': False,
        'source_refs_index_or_original_records_modified': False,
    }
    assert report['missing_original_bytes_total'] == 18176884
    destination = OUT / 'ROOT_ACTUAL_SNAPSHOT_DIFFERENCE_REVIEW.json'
    with destination.open('xb') as f:
        f.write((json.dumps(report, sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps({'report': str(destination), 'identity': identity(destination.read_bytes()),
                      'missing': len(diff), 'unchanged': 15181, 'original_missing_bytes': 18176884}))


if __name__ == '__main__':
    main()
