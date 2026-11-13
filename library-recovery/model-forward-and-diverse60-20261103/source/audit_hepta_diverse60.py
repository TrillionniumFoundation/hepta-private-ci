"""Independent byte and lineage audit of the original 94904213 CI archive."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import zipfile

ROOT = Path(__file__).parent
ARCHIVE = ROOT / 'hepta-diverse60-94904213-original.zip'
EXPECTED = '8a602cd2a6f0cdaf3833479f838fb792f55a35882894356a810469916e7a05fe'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'duplicate key {key}')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def truth(prompt):
    match = re.fullmatch(r'Answer with only yes or no\. Is (\d+) greater than (\d+)\?', prompt)
    if match:
        return 'yes' if int(match[1]) > int(match[2]) else 'no'
    match = re.fullmatch(r'Answer with only yes or no\. Does the first character of ([A-Za-z]+) use uppercase\? Item (\d+)\.', prompt)
    if match:
        return 'yes' if match[1][0].isupper() else 'no'
    raise ValueError(f'unknown task grammar: {prompt!r}')

with ARCHIVE.open('rb') as handle:
    assert hashlib.file_digest(handle, 'sha256').hexdigest() == EXPECTED
with zipfile.ZipFile(ARCHIVE) as z:
    names = [info.filename for info in z.infolist()]
    assert len(names) == len(set(names))
    for name in names:
        assert not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts
    read = lambda name: strict_json(z.read(name))
    manifest = read('archive-manifest.json')
    assert manifest['complete_regular_files'] and not manifest['errors'] and not manifest['nonregular_entries']
    entries = {item['path']: item for item in manifest['files']}
    assert len(entries) == len(manifest['files'])
    assert set(names) == set(entries) | {'archive-manifest.json'}
    original = {item['original_path']: item for item in manifest['files']}
    assert len(original) == len(entries)
    hashes = {}
    total = 0
    for name, entry in entries.items():
        digest = hashlib.sha256()
        count = 0
        with z.open(name) as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
                count += len(block)
        assert count == entry['bytes'], name
        assert digest.hexdigest() == entry['sha256'], name
        hashes[name] = digest.hexdigest()
        total += count

    def pinned(pin):
        entry = original[pin['path']]
        assert pin['sha256'] == hashes[entry['path']]
        return read(entry['path'])

    before, after = read('raw/source-before.json'), read('raw/source-after.json')
    assert before['valid'] and after['valid'] and not before['errors'] and not after['errors']
    assert before['repositories'] == after['repositories']
    summary = read('raw/qualification-summary.json')
    assert summary['passed'] and all(item['passed'] for item in summary['checks'].values())
    assert summary['run']['SOURCE_SHA'] == '94904213e2533c0d40a8ecf536c3f22594a7cc06'
    loop = read('raw/n/n/positive-loop-result.json')
    assert loop['installed_children'] == loop['ordinary_child_reads'] == 1
    assert loop['actual_model_training'] and loop['same_artifact_owner']
    assert not loop['public_network_ready'] and loop['controlled_role_keys']
    trained = read('raw/n/n/trained/training-result.json')
    training = pinned(trained['training'])
    pinned(trained['training_consumption'])
    data = pinned(trained['training_data'])
    child, parent = pinned(trained['child']), pinned(trained['parent'])
    assert len(data['consumed_training_rows']) == 60
    assert training['outcome'] == 'success' and len(training['training']['loss']) == 30
    assert training['training']['objective']['actual_input_tokens'] == 15600
    assert training['candidate']['file_sha256'] == child['file_sha256'] != parent['file_sha256']
    assert training['parent']['file_sha256'] == parent['file_sha256']
    for item in [child, parent]:
        original_file = item['directory'] + '/artifact.safetensors'
        assert hashes[original[original_file]['path']] == item['file_sha256']
    transport = read('raw/n/n/cell/transport-result.json')
    publication = read('raw/n/n/actual-child-publication.json')
    assert transport['outcome'] == 'success' and transport['independent_nodes'] == 2
    assert transport['same_host'] is True and transport['installation_authority'] is False
    assert transport['child'] == child
    for name, member in transport['members'].items():
        assert member['cached_chunks'] == 0
        assert member['downloaded_bytes'] == member['bytes']
        raw = z.read('raw/n/n/cell/downloaded/' + name)
        assert len(raw) == member['bytes'] and sha(raw) == member['payload_sha256']
        assert raw == z.read('raw/n/n/trained/candidate/' + name)
    assert publication['child_file_sha256'] == child['file_sha256']
    assert publication['exact_retry_equal'] and publication['same_writer_lease']
    descriptor = pinned(publication['descriptor'])
    assert hashes[original[descriptor['payload_path']]['path']] == child['file_sha256']
    assert descriptor['profile'] == 'published_neural_product_qualification_v1'
    nxt = read('raw/n/n/next-use/ordinary-child-session-result.json')
    assert nxt == loop['next']
    assert nxt['child']['parameter_sha256'] == nxt['neural_execution_v1']['parameter_file_digest'] == child['file_sha256']
    assert nxt['neural_execution_v1']['source'] == 'evaluated_child'
    assert nxt['neural_execution_v1']['model_generation'] == 2
    assert nxt['model_terminal_unload_observed']
    assert nxt['readback']['current_before'] == nxt['readback']['current_after'] == publication['after'] == loop['current_after']
    journal = nxt['readback']['original_journal']
    assert journal['exact_cold_reopen'] and len(journal['completed']) == 2
    assert hashes[original[journal['path']]['path']] == journal['sha256']
    assert all(event['state'] == 'Completed' for event in journal['completed'])
    assert journal['completed'][1]['output'] == nxt['neural_execution_v1']['response_digest']
    actual_exe = pinned(loop['actual_test_executable']['before'])
    assert actual_exe == pinned(loop['actual_test_executable']['after'])
    assert hashes['executables/actual-positive-test.elf'] == actual_exe['executable']['sha256']
    scores = {}
    phases = {}
    study = read('raw/n/n/study.json')
    prompt_union = set()
    for window in range(2):
        tasks = read(f'raw/n/n/future-{window}-inputs.json')
        assert len(tasks) == 512
        for task in tasks:
            digest = sha(task['prompt'].encode())
            assert digest not in prompt_union
            prompt_union.add(digest)
        for model, material in [('parent', parent), ('child', child)]:
            name = f'{model}-{window}'
            phase = read(f'raw/n/n/{name}/phase-result.json')
            forward = pinned(phase['actual'])
            supervisor = pinned(phase['supervisor'])
            assert forward['forwards'] == len(forward['rows']) == 512
            assert supervisor['exit_code'] == 0 and supervisor['outcome'] == 'success'
            assert supervisor['waited_child_reaped'] and supervisor['owned_child_exit_observed']
            assert supervisor['owned_child_reap_resolved']
            actions = {item['action_id']: item['completion'] for item in forward['last_ready']['observation']['actions']}
            correct = 0
            families = {'integer': {'correct': 0, 'rows': 0}, 'uppercase': {'correct': 0, 'rows': 0}}
            for row, task in zip(forward['rows'], tasks, strict=True):
                request_raw = bytes.fromhex(row['request_bytes_hex'])
                response_raw = bytes.fromhex(row['response_bytes_hex'])
                request, response = strict_json(request_raw), strict_json(response_raw)
                assert row['task'] == request['request_id'] == response['request_id'] == task['id']
                assert request['prompt'] == task['prompt']
                assert row['query_sha256'] == sha(task['prompt'].encode())
                assert sha(request_raw) == response['input_sha256']
                assert sha(response_raw) == row['response_sha256'] and response == row['response']
                assert response['file_sha256'] == material['file_sha256']
                assert study['frozen_unix_micros'] < row['decision_at'] <= row['observed_at']
                best = max(range(len(response['scores_q32'])), key=lambda index: response['scores_q32'][index])
                observed = actions[response['action_ids'][best]]
                ok = int(observed == truth(task['prompt']))
                family = 'integer' if ' greater than ' in task['prompt'] else 'uppercase'
                correct += ok
                families[family]['correct'] += ok
                families[family]['rows'] += 1
            scores[name] = {'correct': correct, 'rows': 512, 'families': families}
            phases[name] = {key: supervisor[key] for key in ['child_cpu_ns', 'observed_wall_ns', 'waited_child_peak_rss_bytes']}
    qualification = read('raw/n/n/qualification-result.json')
    assert qualification['eligible'] and qualification['decision'] == 'EligibleForIndependentSelection'
    metric = qualification['metrics'][0]
    margin = metric['candidate']['lower'] - metric['baseline']['upper']
    assert margin > 0
    report = {
        'schema': 'independent-diverse60-archive-lineage-audit-v1',
        'source': summary['run'], 'archive_bytes': ARCHIVE.stat().st_size,
        'archive_sha256': EXPECTED, 'manifest_members_verified': len(entries),
        'manifest_bytes_verified': total, 'exact_source_before_after_equal': True,
        'all_raw_forward_bindings_checked': 2048, 'direct_greedy_counts': scores,
        'raw_future_prompt_union_size': len(prompt_union),
        'original_qualification': qualification, 'confidence_margin_q32': margin,
        'parent_sha256': parent['file_sha256'], 'child_sha256': child['file_sha256'],
        'transport': {'nodes': 2, 'same_host': True, 'fresh_members': len(transport['members']),
                      'payload_bytes': sum(x['bytes'] for x in transport['members'].values())},
        'installed_children': 1, 'ordinary_child_reads': 1, 'next_actual_parameter_hash_matches': True,
        'next_control_journal_cold_reopened': True, 'terminal_settlements': 2,
        'training_work': summary['checks']['actual_positive_loop']['result']['actual_training_work'],
        'supervised_costs': summary['checks']['actual_positive_loop']['result']['supervised_costs'],
        'measured_next_forward_ns': nxt['neural_execution_v1']['execution_ns'],
        'controlled_role_keys': True, 'external_administrative_independence': False,
        'public_network_ready': False, 'new_independent_execution': False,
        'scope': 'Independent archive byte/lineage and raw-count audit; original controlled same-host execution, not new training or WAN qualification.',
        'passed': True,
    }
    target = ROOT / 'hepta-diverse60-independent-audit.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ['passed', 'manifest_members_verified', 'manifest_bytes_verified', 'direct_greedy_counts', 'confidence_margin_q32', 'installed_children', 'ordinary_child_reads']}))
