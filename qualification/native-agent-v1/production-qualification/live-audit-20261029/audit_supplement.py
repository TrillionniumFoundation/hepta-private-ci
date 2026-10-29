#!/usr/bin/env python3
"""Derive identity, input-alignment, and timing evidence from retained local bytes.

This script reads existing evidence only. It makes no network or subprocess calls
and writes only derived/ files. Run audit_live.py first.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'raw'
OUT = ROOT / 'derived'


def read(path):
    return json.loads(path.read_bytes())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def utc(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def retained_pty_json(name):
    path = ROOT / name
    outer = read(path)
    assert not outer.get('isError')
    values = [json.loads(block['text']) for block in outer['content'] if block['type'] == 'text']
    assert len(values) == 1
    envelope = values[0]
    captured = bytes.fromhex(envelope['bytes_hex'])
    assert digest(captured) == envelope['chunk_sha256']
    assert envelope['offset'] == 0 and len(captured) == envelope['next_offset'] == envelope['available_end']
    assert envelope['output_complete'] and not envelope['text_is_lossy']
    assert not envelope['truncated_before_offset'] and not envelope['utf8_pending']
    assert envelope['status']['exit_code'] == 0 and envelope['status']['capture_error'] is None
    assert envelope['status']['bytes_seen'] == envelope['status']['bytes_stored'] == len(captured)
    assert captured.decode() == envelope['text']
    documents = [json.loads(line) for line in captured.decode().splitlines() if line.startswith('{')]
    assert len(documents) == 1
    return documents[0], {'path': name, 'sha256': digest(path.read_bytes()),
                          'capture_sha256': digest(captured), 'capture_bytes': len(captured),
                          'session_id': envelope['session_id'], 'host': envelope['host'],
                          'exit_code': 0, 'output_complete': True}


def main():
    audit = read(OUT / 'AUDIT.json')
    cases = audit['cases']
    live = [c for c in cases if c['cost']['mode'] == 'live']
    assert len(live) == 24
    before = read(RAW / 'runs/live-model-identity-v1/MODEL_IDENTITY_EVIDENCE.json')
    identity = read(RAW / 'runs/live-model-identity-v1/MODEL_IDENTITY.json')
    assert digest((RAW / 'runs/live-model-identity-v1/MODEL_IDENTITY_EVIDENCE.json').read_bytes()) == identity['evidence_sha256']
    after_ai, ai_receipt = retained_pty_json('post-live-ai395-final-read.json')
    after_main, main_receipt = retained_pty_json('post-live-main-read.json')
    old_binding = {k: v for k, v in before['ai395']['refresh'].items() if k != 'utc_epoch'}
    assert after_ai['binding_before'] == after_ai['binding_after'] == old_binding
    assert after_ai['same_as_before_live'] is True
    assert after_ai['full_model_sha256'] == identity['model_sha256']
    old_libraries = {x['path']: x for x in before['ai395']['SERVING_IMPLEMENTATION.json']['mapped_libraries']}
    new_libraries = {x['path']: x for x in after_ai['mapped_libraries']}
    assert old_libraries == new_libraries and len(new_libraries) == 8
    for name, record in after_main['sources'].items():
        old = before['main']['sources'][name]
        assert old['sha256'] == record['sha256'] and old['size'] == record['bytes']
    assert after_main['18083/routing']['config_sha256'] == before['routing']['response']['config_sha256']
    assert after_main['18083/routing']['active'] == 'llamacpp'
    assert after_main['18083/routing']['connect_only_failover'] is False
    assert after_main['18081/health']['cloud_fallback'] is False
    assert after_main['18081/health']['adapter_version'] == before['main']['18081/health']['adapter_version']
    assert all(r['model'] == identity['response_model'] for c in live for r in c['responses'])
    save('POST_LIVE_IDENTITY.json', {'schema': 'hepta.p1.identity-audit.v1',
         'raw_receipts': [ai_receipt, main_receipt], 'before_evidence_sha256': identity['evidence_sha256'],
         'model_identity': identity, 'post_live_ai395': after_ai, 'post_live_main': after_main,
         'verified': {'full_weight_hash_equal': True, 'process_boot_start_inode_equal_at_observation_endpoints': True,
                      'eight_mapped_library_hashes_equal': True, 'two_provider_source_hashes_equal': True,
                      'all_107_live_response_models_match_alias': True},
         'limits': ['Endpoint observations and a second full file hash are not a continuous inode lease.',
                    'The service was shared; the post-live health/routing snapshot had one active request.',
                    'Gateway adapter revision and mapped library hashes identify the observed implementation; no exclusive inference reservation was measured.']})

    source_verification = []
    for group in sorted({c['group'] for c in cases}):
        frozen = read(RAW / 'runs' / group / 'FROZEN.json')
        verified, unavailable = [], []
        for original, expected in frozen['sha256'].items():
            if '/qualification/' in original:
                candidate = RAW / 'source' / ('qualification/' + original.split('/qualification/', 1)[1])
            elif '/live-model-identity-v1/' in original:
                candidate = RAW / 'runs/live-model-identity-v1' / original.rsplit('/', 1)[-1]
            else:
                candidate = None
            if candidate and candidate.is_file():
                assert digest(candidate.read_bytes()) == expected
                verified.append({'original_path': original, 'collected_path': str(candidate.relative_to(RAW)), 'sha256': expected})
            else:
                unavailable.append({'original_path': original, 'recorded_sha256': expected,
                                    'reason': 'binary not copied into the audit archive'})
        source_verification.append({'group': group, 'verified': verified, 'unavailable': unavailable})
    save('SOURCE_VERIFICATION.json', {'groups': source_verification,
                                    'native_binary_metadata': read(RAW / 'build/BINARY.json'),
                                    'limit': 'This local audit verified collected source/config bytes; binary hashes are the original recorded measurements.'})

    alignment = []
    for case_name in ('edit', 'repair', 'multi_tool', 'mcp_readonly'):
        chosen = [c for c in live if c['case'] == case_name]
        entries = [{'group': c['group'], 'lane': c['lane'], **c['initial_input'],
                    'effective_initial_sha256': c['requests'][0]['effective_sha256'],
                    'effective_initial_bytes': c['requests'][0]['effective_bytes']} for c in chosen]
        native = [e for e in entries if e['lane'] == 'native']
        assert len(native) == 2 and native[0]['sha256'] == native[1]['sha256']
        assert len({e['tools_without_strict_sha256'] for e in entries}) == 1
        alignment.append({'case': case_name, 'native_between_groups_initial_raw_equal': True,
                          'native_between_groups_initial_effective_equal': native[0]['effective_initial_sha256'] == native[1]['effective_initial_sha256'],
                          'all_lanes_initial_effective_equal': len({e['effective_initial_sha256'] for e in entries}) == 1,
                          'tool_parameters_descriptions_names_equal_after_removing_strict': True, 'entries': entries})
    save('INPUT_ALIGNMENT.json', {'schema': 'hepta.p1.actual-input-alignment.v1', 'cases': alignment,
         'headers': {'incoming_headers_captured': False,
                     'forwarder_explicit_headers_from_source': {'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
                     'source': 'source/qualification/native-agent-v1/model_gateway.py',
                     'limit': 'Explicit forwarder construction is source evidence, not a retained complete wire-header capture.'}})

    long_rows = []
    for case in cases:
        if case['case'] != 'long_output':
            continue
        assert case['cost']['mode'] == 'replay' and len(case['runtime_jobs']) == 1
        job = case['runtime_jobs'][0]
        terminal = job['terminal']
        assert terminal['exit_code'] == 0 and terminal['cancelled'] is False and terminal['timed_out'] is False
        assert terminal['output_complete'] is True and terminal['output_durable'] is True
        assert terminal['terminal_publication_protocol'] == 1
        for stream in ('stdout', 'stderr'):
            assert terminal['log_bytes'][stream]['seen'] == terminal['log_bytes'][stream]['stored'] == job[stream + '_bytes']
            assert terminal['log_errors'][stream] is None and terminal['log_synced'][stream] is True and terminal['log_truncated'][stream] is False
        assert job['stdout_bytes'] == 1179648 and job['stderr_bytes'] == 0
        assert job['stdout_sha256'] == 'f70ff820f5588c15fd6bad61636b765bcdd8fa1e36c9e05e48dce455010babfd'
        reply = case['backend_results'][-1]
        started = job['started.json']['at_unix_ms']
        exit_ms = terminal['at_unix_ms']
        assert type(started) is int
        long_rows.append({'lane': case['lane'], 'case_result': case['reported_result']['status'],
                          'job_id': terminal['job_id'], 'stdout_bytes': job['stdout_bytes'],
                          'stdout_sha256': job['stdout_sha256'], 'terminal_exit_code': 0,
                          'terminal_cancelled': False, 'terminal_timed_out': False,
                          'output_complete': True, 'output_durable': True,
                          'started_ms': started, 'terminal_ms': exit_ms, 'reply_ns': reply['received_ns'],
                          'physical_started_to_exit_seconds': (exit_ms - started) / 1000,
                          'exit_to_backend_reply_seconds': reply['received_ns'] / 1e9 - exit_ms / 1000,
                          'backend_elapsed_ms': reply['message'].get('elapsed_ms'),
                          'backend_status': reply['message'].get('status'),
                          'backend_error': reply['message'].get('error'),
                          'backend_last_error': reply['message'].get('last_error'),
                          'backend_cancel_requested': reply['message'].get('cancel_requested')})
    windows = []
    for group in sorted({c['group'] for c in cases}):
        selected = [c for c in cases if c['group'] == group]
        start = min(r['started_ns'] for c in selected for r in c['requests']) / 1e9
        end = max(r['finished_ns'] for c in selected for r in c['requests']) / 1e9
        windows.append({'group': group, 'model_gateway_start': utc(start), 'model_gateway_end': utc(end),
                        'start_unix_seconds': start, 'end_unix_seconds': end})
    save('LONG_OUTPUT_TIMELINE.json', {'schema': 'hepta.p1.long-output-timeline.v1', 'mode': 'replay', 'lanes': long_rows,
         'model_gateway_windows': windows, 'minimum_sequential_16_kib_page_reads': 72,
         'limits': ['Per-page duration was not captured, so page-read latency is a mechanism hypothesis, not a measured isolated cause.',
                    'Backend elapsed time includes owner opening and admission before the internal tool deadline starts.',
                    'Cancellation cleanup budgets differ between native engine and external tool helper.',
                    'Long-output observation overlapped the matched live group on the main host; no exclusive host-load control was measured.']})
    print(json.dumps({'identity': 'verified_endpoint_observations_and_second_full_hash',
                      'libraries': len(new_libraries), 'source_groups': len(source_verification),
                      'input_cases': len(alignment), 'long_output_physical_jobs_completed': len(long_rows),
                      'long_output_harness_passed': sum(x['case_result'] == 'passed' for x in long_rows)}, indent=2))


if __name__ == '__main__':
    main()
