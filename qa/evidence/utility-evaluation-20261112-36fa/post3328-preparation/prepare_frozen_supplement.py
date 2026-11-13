#!/usr/bin/env python3
"""Append only explicitly completed handoffs to an offline evidence selection."""
from pathlib import Path
from datetime import datetime, timezone
import json
from prepare_initial_increment import OUT, SOURCE, pins, read_stable, write_new, jbytes, normalized

ROOT_REVIEW = Path('/tmp/hepta-36fa-cc57-final-source-root-review-v1')


def main():
    base = json.loads((OUT / 'BASE_3328_FILEMAP.json').read_bytes())
    old = json.loads((OUT / 'SELECTED_ROWS_INITIAL.json').read_bytes())
    selected = {r['path']: r for r in old}
    rows = []

    def add(path, evidence_path, kind, expected=None, known_remote=False):
        raw = read_stable(path)
        identity = pins(raw)
        if expected is not None:
            assert identity == expected, (path, identity, expected)
        evidence_path = normalized(evidence_path)
        assert evidence_path not in base and evidence_path not in selected
        assert len(raw) < 500000
        raw.decode('utf-8')
        frozen = OUT / 'frozen' / evidence_path
        write_new(frozen, raw)
        row = {'path': evidence_path, 'local': str(path), 'frozen_local': str(frozen), **identity,
               'kind': kind, 'known_remote': known_remote or identity['git_blob'] in base.values(),
               'full_readback_equal': None}
        selected[evidence_path] = row
        rows.append(row)

    core = json.loads(read_stable(SOURCE / 'FINAL_SOURCE_CORE_READBACK.json'))
    core_by_name = {Path(r['local_path']).name: r for r in core['items']}
    for name in ['SOURCE_HANDOFF_RESULT.json', 'ORIGINAL_RUN_RESULT.json', 'STATUS_05.original.json', 'STDOUT.complete.log']:
        r = core_by_name[name]
        add(SOURCE / name, 'source-qualification-cc57-v2/completed-originals/' + name,
            'complete_original_source_result',
            {'bytes': r['bytes'], 'sha256': r['sha256'], 'git_blob': r['git_blob_sha']}, True)
    add(SOURCE / 'FINAL_SOURCE_CORE_READBACK.json',
        'source-qualification-cc57-v2/completed-originals/FINAL_SOURCE_CORE_READBACK.json',
        'complete_original_source_readback_index', known_remote=True)

    origin_index = SOURCE / 'ORIGIN_AND_CLONE_SMALL_READBACK.json'
    origin = json.loads(read_stable(origin_index))
    assert len(origin['files']) == 8
    for r in origin['files']:
        p = Path(r['local_path'])
        add(p, 'source-qualification-cc57-v2/completed-originals/' + str(p.relative_to(SOURCE)),
            'complete_origin_or_clone_small_original',
            {'bytes': r['bytes'], 'sha256': r['sha256'], 'git_blob': r['git_blob']})
        sdk = Path(r['sdk'])
        add(sdk, 'source-qualification-cc57-v2/completed-originals/' + sdk.name,
            'origin_or_clone_original_read_sdk')
    add(origin_index, 'source-qualification-cc57-v2/completed-originals/ORIGIN_AND_CLONE_SMALL_READBACK.json',
        'origin_and_clone_small_readback_index')

    root_names = ['ROOT_SOURCE_CORE_REVIEW.json', 'ROOT_SOURCE_CORE_REVIEW.GITHUB.original.json',
                  'source-ref.GET.original.json', 'check-runs.GET.original.json',
                  'check-suites.GET.original.json', 'status.GET.original.json',
                  'workflow-runs.GET.original.json']
    for name in root_names:
        add(ROOT_REVIEW / name, 'cc57-final-source-root-core-review-v1/' + name,
            'root_core_review_or_original_hosted_observation',
            known_remote=name == 'ROOT_SOURCE_CORE_REVIEW.json')

    source = 'cc57c7198db6293ccca562253c42fffbe2a04633'
    observations = []
    payload = {}
    for name in root_names[2:]:
        path = ROOT_REVIEW / name
        raw = read_stable(path)
        response = json.loads(raw)
        assert response.get('isError') is False
        actual = response['structuredContent']
        data = json.loads(actual['content'])
        payload[name] = data
        observations.append({'name': name, 'original': pins(raw), 'url': actual['url'],
                             'server_modified_date': actual.get('modified_date'),
                             'local_file_mtime_utc': datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()})
        assert source in actual['url'] or name == 'source-ref.GET.original.json'
    assert payload['source-ref.GET.original.json']['object']['sha'] == source
    assert payload['check-runs.GET.original.json'] == {'total_count': 0, 'check_runs': []}
    assert payload['check-suites.GET.original.json'] == {'total_count': 0, 'check_suites': []}
    assert payload['workflow-runs.GET.original.json'] == {'total_count': 0, 'workflow_runs': []}
    status = payload['status.GET.original.json']
    assert status['sha'] == source and status['state'] == 'pending'
    assert status['total_count'] == 0 and status['statuses'] == []
    times = [o['local_file_mtime_utc'] for o in observations]
    review = {
        'format': 'hepta-offline-review-of-original-hosted-ci-observations-v1',
        'reviewed_at_utc': datetime.now(timezone.utc).isoformat(),
        'source': source,
        'originals': observations,
        'original_GET_count': 5, 'hosted_CI_GET_count': 4, 'source_ref_GET_count': 1,
        'all_server_modified_dates_absent': all(o['server_modified_date'] is None for o in observations),
        'local_original_archive_mtime_window_utc': [min(times), max(times)],
        'time_scope': 'Local file archive timestamps and this offline review time are recorded separately. No exact server response time is inferred from null modified_date fields.',
        'actual_source_ref_matches': True,
        'check_runs': 0, 'check_suites': 0, 'status_contexts': 0, 'workflow_runs': 0,
        'combined_status': 'pending',
        'trigger_or_permission_cause': 'Unknown',
        'hosted_CI_pass': False,
        'native_qualification_result_inferred': False,
        'prior_2026_11_12_23_53_observation_unchanged': True,
        'new_service_GETs_by_this_reviewer': 0, 'H_calls': 0, 'tests': 0,
        'read_only_original_responses_reviewed': True,
    }
    review_path = OUT / 'DATED_HOSTED_CI_REVIEW.json'
    write_new(review_path, jbytes(review))
    add(review_path, 'cc57-final-source-root-core-review-v1/DATED_HOSTED_CI_REVIEW.json',
        'offline_dated_review_of_original_hosted_observations')
    write_new(OUT / 'SELECTED_ROWS_SUPPLEMENT_001.json', jbytes(rows))
    print(json.dumps({'supplement_new_paths': len(rows), 'total_selected_paths': len(old) + len(rows),
                      'maximum_bytes': max(r['bytes'] for r in rows)}))


if __name__ == '__main__':
    main()
