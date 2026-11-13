#!/usr/bin/env python3
"""Pure frozen-evidence validation. Does not run source/gate/control programs."""
from pathlib import Path
from datetime import datetime, timezone
import base64
import gzip
import hashlib
import json
from prepare_initial_increment import OUT, SOURCE, PUBLICATION, BASE_PLAN, pins, read_stable, write_new, jbytes


def decode_tool_json(raw):
    envelope = json.loads(raw)
    assert envelope.get('isError') is not True
    if isinstance(envelope.get('structuredContent'), dict):
        return envelope['structuredContent']
    blocks = envelope['content']
    assert len(blocks) == 1 and blocks[0]['type'] == 'text'
    return json.loads(blocks[0]['text'])


def main():
    cutoff = json.loads((OUT / 'COLLECTION_CUTOFF.json').read_bytes())
    rows = []
    for name in cutoff['selected_lists']:
        rows.extend(json.loads((OUT / name).read_bytes()))
    assert len(rows) == cutoff['payload_paths'] == 118
    by_path = {r['path']: r for r in rows}
    assert len(by_path) == len(rows)
    by_local = {r['local']: r for r in rows}
    raw_plan = (OUT / 'BASE_3328_PLAN.original.json').read_bytes()
    assert pins(raw_plan) == BASE_PLAN
    plan = json.loads(raw_plan)
    base = plan['files']
    assert len(base) == 3328
    assert not set(base).intersection(by_path)

    def frozen_original(path):
        p = str(path)
        if p in by_local:
            return Path(by_local[p]['frozen_local']).read_bytes()
        allowed = {
            str(SOURCE / 'STDOUT_READ_01.original.json'): 'source-qualification-cc57-v2/initial-observation/STDOUT_READ_01.original.json',
            str(SOURCE / 'STDOUT.part-0000000000-0000000444.log'): 'source-qualification-cc57-v2/initial-observation/STDOUT.part-0000000000-0000000444.log',
            str(SOURCE / 'STDOUT.part-0000000444-0000003600.log'): 'source-qualification-cc57-v2/progress-through-verify-start/STDOUT.part-0000000444-0000003600.log',
            str(SOURCE / 'STDOUT_READ_03.original.json'): 'source-qualification-cc57-v2/progress-through-verify-start/STDOUT_READ_03.original.json',
        }
        assert p in allowed
        raw = read_stable(Path(p))
        assert pins(raw)['git_blob'] == base[allowed[p]]
        return raw

    for row in rows:
        raw = Path(row['frozen_local']).read_bytes()
        assert pins(raw) == {k: row[k] for k in ('bytes', 'sha256', 'git_blob')}
        assert len(raw) < 500000

    successes, failures, attempts = {}, [], []
    for p in sorted((OUT / 'readback-receipts').glob('BATCH_*.json')):
        attempts.extend(json.loads(p.read_bytes())['results'])
    retry = json.loads((OUT / 'readback-receipts/RETRY_001_SAME_BLOB_GET.json').read_bytes())
    attempts.append(retry['result'])
    for record in attempts:
        if record['full_readback_equal'] is True:
            assert record['path'] in by_path
            row = by_path[record['path']]
            assert all(record[k] == row[k] for k in ('bytes', 'sha256', 'git_blob'))
            successes[record['path']] = record
        else:
            failures.append(record)
    assert set(successes) == set(by_path)
    assert len(failures) == 1
    assert failures[0]['git_blob'] == '965090dbd1a43552bd6dfae00cbf1a8b9f7226bc'
    assert retry['result']['git_blob'] == failures[0]['git_blob']
    assert retry['no_recreated_blob'] is True

    transport_checks = []
    for row in rows:
        if row['kind'] != 'lossless_transport_manifest':
            continue
        m = json.loads(Path(row['frozen_local']).read_bytes())
        combined = bytearray()
        for part in m['parts']:
            encoded = Path(by_path[part['path']]['frozen_local']).read_bytes()
            assert pins(encoded) == part['encoded']
            assert encoded.endswith(b'\n') and b'\n' not in encoded[:-1]
            chunk = base64.b64decode(encoded[:-1], validate=True)
            assert pins(chunk) == part['decoded'] and part['offset'] == len(combined)
            combined.extend(chunk)
        assert pins(bytes(combined)) == m['gzip']
        raw = gzip.decompress(combined)
        assert pins(raw) == m['raw']
        original = read_stable(Path(m['original_local_path']))
        assert raw == original
        transport_checks.append({'manifest': row['path'], 'original': m['original_local_path'],
                                 'raw': m['raw'], 'parts': len(m['parts']), 'complete_equal': True})
    assert len(transport_checks) == 2

    read_checks = []

    def binary_read_check(local_path, sdk_path, version=None, original_path=None):
        original = frozen_original(local_path)
        data = decode_tool_json(frozen_original(sdk_path))
        raw = base64.b64decode(data['data_base64'], validate=True)
        assert data['offset'] == 0 and data['next_offset'] == len(raw)
        assert data['size'] == len(raw) and data['eof'] is True
        assert hashlib.sha256(raw).hexdigest() == data['chunk_sha256']
        assert raw == original
        if version is not None:
            assert data['version'] == version
        if original_path is not None:
            assert data['path'] == original_path
        read_checks.append({'original_local': str(local_path), 'sdk_local': str(sdk_path),
                            'original_path': data['path'], 'version': data['version'],
                            **pins(raw), 'whole_original_equal_to_complete_sdk_payload': True})

    first = json.loads(frozen_original(SOURCE / 'FIRST_TWO_GATE_ORIGINALS_READBACK.json'))
    for r in first['files']:
        binary_read_check(r['path'], r['sdk'], r['version'])
    core = json.loads(frozen_original(SOURCE / 'FINAL_SOURCE_CORE_READBACK.json'))
    for r in core['items']:
        if 'read_sdk' in r:
            binary_read_check(r['local_path'], SOURCE / r['read_sdk'], r['version'], r['original_path'])
    origin = json.loads(frozen_original(SOURCE / 'ORIGIN_AND_CLONE_SMALL_READBACK.json'))
    for r in origin['files']:
        binary_read_check(r['local_path'], r['sdk'], r['version'], r['original_path'])
    binary_read_check(SOURCE / 'stage-originals/self-test/self-test.log', SOURCE / 'SELF_TEST_RAW_01.original.json')
    assert len(read_checks) == 21

    stdout = bytearray()
    stdout_reads = []
    for name, part in [
        ('STDOUT_READ_01.original.json', 'STDOUT.part-0000000000-0000000444.log'),
        ('STDOUT_READ_03.original.json', 'STDOUT.part-0000000444-0000003600.log'),
        ('STDOUT_READ_05.original.json', 'STDOUT.part-0000003600-0000006169.log'),
    ]:
        record = decode_tool_json(frozen_original(SOURCE / name))
        assert record['job_id'] == '1a1d23c92f3-2564-1cb4'
        data = record['stdout']
        raw = bytes.fromhex(data['bytes_hex'])
        assert raw == data['text'].encode('utf-8') == frozen_original(SOURCE / part)
        assert data['offset'] == len(stdout) and data['next_offset'] == len(stdout) + len(raw)
        stdout.extend(raw)
        stdout_reads.append({'sdk': name, 'part': part, 'offset': data['offset'], 'next_offset': data['next_offset'], **pins(raw)})
    assert bytes(stdout) == frozen_original(SOURCE / 'STDOUT.complete.log')
    assert len(stdout) == 6169

    normal = decode_tool_json(frozen_original(SOURCE / 'STATUS_05.original.json'))
    assert normal['job_id'] == '1a1d23c92f3-2564-1cb4'
    assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
    assert normal['cancelled'] is False and normal['timed_out'] is False
    assert normal['output_complete'] is True and normal['output_durable'] is True
    assert normal['terminal_publication_confirmed'] is True
    assert normal['log_bytes']['stdout']['seen'] == normal['log_bytes']['stdout']['stored'] == 6169
    assert normal['log_synced']['stdout'] is True and normal['log_truncated']['stdout'] is False
    run = json.loads(frozen_original(SOURCE / 'ORIGINAL_RUN_RESULT.json'))
    handoff = json.loads(frozen_original(SOURCE / 'SOURCE_HANDOFF_RESULT.json'))
    assert run['source_sha'] == handoff['source'] == 'cc57c7198db6293ccca562253c42fffbe2a04633'
    assert run['source_tree'] == handoff['tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
    assert run['status'] == handoff['status'] == 'passed'
    assert handoff['driver_main_entered'] is True and handoff['driver_returncode'] == 0
    assert run['actual_A_B_C_qualification'] is False and handoff['qualification'] is False
    assert run['attempted'] == run['entrypoints_started'] == ['source-closure', 'self-test', 'verify']
    assert run['not_run'] == []
    for gate in run['gates']:
        assert gate['status'] == 'passed' and gate['source_changed'] is False
        assert gate['before_inventory_sha256'] == gate['after_inventory_sha256'] == 'f7db5e671a913b26a8798ec9e8ea5bdd265e6ace80ec85cdea7e6c22bb66387a'
        assert gate['lifecycle'] == {'attempted': True, 'entrypoint_started': True, 'package': 'completed', 'terminal_observed': True}
    before = frozen_original(SOURCE / 'origin-and-clone-originals/GIT_STATE.before.json')
    after = frozen_original(SOURCE / 'origin-and-clone-originals/GIT_STATE.after.json')
    assert before == after

    timeout_checks = []
    for name in ['SOURCE_CLOSURE_RAW_01.original.json', 'SOURCE_CLOSURE_RAW_02.original.json']:
        raw = frozen_original(SOURCE / name)
        response = json.loads(raw)
        assert response['isError'] is True
        assert 'MCP request timed out' in response['content'][0]['text']
        timeout_checks.append({'name': name, **pins(raw), 'transport_failure_preserved': True})

    report = {
        'format': 'hepta-post3328-frozen-evidence-consistency-review-v1',
        'reviewed_at_utc': datetime.now(timezone.utc).isoformat(),
        'cutoff': cutoff,
        'status': 'SELECTED_EVIDENCE_BYTES_AND_ORIGINAL_RECEIPTS_CONSISTENT',
        'base_evidence_head': '15673f01e5248efdecd00fcb06a58ae3dd45d2c0',
        'base_file_count': 3328, 'base_paths_overwritten': [], 'old_readme_unchanged': True,
        'new_payload_paths': len(rows), 'unique_payload_blobs': len({r['git_blob'] for r in rows}),
        'actual_successful_complete_git_readbacks': len(successes),
        'actual_failed_Git_GETs_retained': len(failures),
        'same_blob_reconciliation_complete': True,
        'maximum_new_payload_bytes': max(r['bytes'] for r in rows),
        'complete_transport_checks': transport_checks,
        'complete_original_binary_reads': read_checks,
        'stdout_reads': stdout_reads, 'complete_stdout': pins(bytes(stdout)),
        'actual_source_job': normal['job_id'], 'original_supervisor_exit_code': 0,
        'original_supervisor_complete_durable_non_timeout': True,
        'original_three_source_gate_receipts_passed': True,
        'original_origin_raw_Git_bytes_equal': True,
        'source_run_results_remain_qualification_false': True,
        'source_closure_raw_transport_failures': timeout_checks,
        'complete_gate_raw_payloads_in_this_collection': False,
        'complete_full_inventory_payloads_in_this_collection': False,
        'later_payload_handoffs_are_a_separate_window': True,
        'native_qualification_execution_or_pass_inferred': False,
        'real_qualified_task_chain_outcomes': 0,
        'H_calls': 0, 'source_writes': 0, 'tests_or_gates_run': 0,
        'tree_commit_ref_or_PR_mutations': False,
        'script_scope': 'Pure original-byte, saved-tool-payload and append-only mapping checks; does not rerun a source verifier, gate, or reviewed control module.',
    }
    write_new(OUT / 'EVIDENCE_CONSISTENCY_REVIEW.json', jbytes(report))
    ledger = {
        'format': 'hepta-post3328-complete-github-readback-ledger-v1',
        'scope': '118 payload paths only; later metadata uploads have separate receipts to avoid self-reference.',
        'entries': [{k: successes[path][k] for k in ('path', 'frozen_local', 'bytes', 'sha256', 'git_blob', 'full_readback_equal', 'readback_method', 'returned_chars')} for path in sorted(successes)],
        'first_failure': failures[0], 'same_blob_reconciliation': retry,
    }
    write_new(OUT / 'GITHUB_FULL_READBACK_LEDGER.json', jbytes(ledger))
    write_new(OUT / 'READBACK_FIRST_DISCONNECT.original.json', jbytes(failures[0]['fetch_error']))
    print(json.dumps({'payload_paths': len(rows), 'complete_original_binary_reads': len(read_checks),
                      'complete_stdout_bytes': len(stdout), 'transport_originals': len(transport_checks),
                      'all_actual_Git_readbacks': True, 'qualification': False}))


if __name__ == '__main__':
    main()
