#!/usr/bin/env python3
"""Independently reconcile saved H4 receipts and process/image records.

This script reads already produced evidence. It starts no native job, rebuild,
archive, provider operation, or learning trial. Binary bytes have a separate
archive closure; reported image hashes are not a substitute for that closure.
"""
from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys

SOURCE = '6db78eca53a5acdda0d96873d3f4cd65863426f0'
TREE = 'e91f5994017fc5d2cfe58d405a20ee6ad9376772'
ENVIRONMENT = '40341fe44840b6de0ca3cff68785116e5cfbca81c9a77124a82ca72b63234039'
RUNNER = '9679cc6e11762c29b4c0ee92dd7715d3fce0555a6f8e0e10ed9d0b007951381a'
CORRESPONDENCE = 'fc8fc5cfc7c084a3a5884449cd683f94fbd6ee377455ba5a0df6033a6ceed0a4'
DELIVERY = 'bda6c7127e6b4a84db3256898668cb664d933836e6332275cd9dfaa624f51fba'
INVENTORY = 'a1e42612d6a89337144b00335da2fa690dc7f503b46532ff795f0c92198bdd9c'
COORDINATOR = {'pid': 1122369, 'start_ticks': '99633930'}
JOB = '1a1ade2970f-fc05-5b5c'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def unwrap(path):
    obj = read(path)
    return json.loads(obj['content'][0]['text'])


def main():
    native, output = map(Path, sys.argv[1:])
    run = native / 'joint-h4-native-attempt-1'
    manifest_raw = (native / 'h4-native-attempt1-delivery.json').read_bytes()
    assert digest(manifest_raw) == DELIVERY
    manifest = json.loads(manifest_raw)
    assert manifest['source_commit'] == SOURCE and manifest['source_tree'] == TREE
    assert manifest['job_id'] == JOB
    terminal = unwrap(run / 'terminal-status.raw.json')
    assert terminal == unwrap(run / 'status-8.raw.json') == manifest['authoritative_status']
    assert terminal['job_id'] == JOB and terminal['state'] == 'succeeded' and terminal['exit_code'] == 0
    assert terminal['at_unix_ms'] == 1793919910435 and not terminal['timed_out']
    assert terminal['output_complete'] and terminal['output_durable'] and terminal['terminal_publication_confirmed']
    assert not terminal['automatic_retry'] and not terminal['cancelled']
    assert terminal['log_truncated'] == {'stdout': False, 'stderr': False}
    assert len(manifest['files']) == manifest['file_count'] == 131
    assert sum(f['bytes'] for f in manifest['files']) == manifest['total_bytes'] == 5522990
    for entry in manifest['files']:
        relative = Path(entry['relative_path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        assert Path(entry['path']).resolve() == (run / relative).resolve()
        raw = (run / relative).read_bytes()
        assert len(raw) == entry['bytes'] and digest(raw) == entry['sha256'], str(relative)
    streams = {'stdout': b'', 'stderr': b''}
    for name in [f'process-read-{i}.raw.json' for i in range(1, 8)] + ['final-process-read.raw.json']:
        part = unwrap(run / name)
        assert part['job_id'] == JOB
        for stream in streams:
            chunk = part[stream]
            raw = bytes.fromhex(chunk['bytes_hex'])
            assert raw == chunk['text'].encode()
            assert chunk['offset'] == len(streams[stream])
            assert chunk['next_offset'] == chunk['offset'] + len(raw)
            streams[stream] += raw
    for stream, raw in streams.items():
        assert raw == (run / ('coordinator.' + stream + '.log')).read_bytes()
        assert len(raw) == terminal['log_bytes'][stream]['stored'] == terminal['log_bytes'][stream]['seen']
    assert len(streams['stdout']) == 24664 and len(streams['stderr']) == 0

    pipeline = read(run / 'pipeline-status.json')
    assert pipeline['status'] == 'passed-one-source-desktop-gates-only'
    assert pipeline['phase'] == 'final-source-recorded' and 'error' not in pipeline
    before = read(run / 'full-source-before.json')
    assert before == read(run / 'full-source-after.json') == pipeline['source_before'] == pipeline['source_after']
    assert before['identity']['commit'] == SOURCE and before['identity']['tree'] == TREE
    assert not before['identity']['dirty'] and before['raw_git_blob_bytes_match']
    assert before['tracked_count'] == before['index_count'] == 11840
    assert before['tracked_bytes'] == 183410043 and not before['missing'] and not before['hidden']
    configuration = read(run / 'configuration-after.json')
    assert configuration['before'] == configuration['after'] == pipeline['configuration_before']
    assert len(configuration['before']) == 5 and configuration['unchanged'] and pipeline['configuration_unchanged']
    assert digest((run / 'native-environment.json').read_bytes()) == ENVIRONMENT
    runtime_before, runtime_after = (read(run / n) for n in ('runtime-inputs-before.json', 'runtime-inputs-after.json'))
    external = runtime_after['external_configuration_sha256']
    assert external == runtime_before['external_configuration_sha256'] and len(external) == 12
    for name, sha in external.items():
        assert digest((native / name).read_bytes()) == sha, name
    assert runtime_before['ignored_paths'] == runtime_after['ignored_paths']
    for side, observed in [('before', runtime_before), ('after', runtime_after)]:
        bytecode = observed['bytecode']
        assert len(bytecode) == 1 and bytecode[0]['bytes'] == 6094
        assert bytecode[0]['mtime_ns'] == bytecode[0]['ctime_ns'] == 1793914887932050494
        assert bytecode[0]['sha256'] == 'fff1e8ab9c6a33148ad58505d634919b4c7963e345b022c5b7ac1a926b769872'
        assert digest((run / ('observed-bytecode-' + side) / (bytecode[0]['sha256'] + '.pyc')).read_bytes()) == bytecode[0]['sha256']
    assert digest((native / 'live_fd_correspondence.py').read_bytes()) == CORRESPONDENCE
    spec = importlib.util.spec_from_file_location('h4_correspondence_verified', native / 'live_fd_correspondence.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    plan = read(native / 'h4-native-plan.json')
    assert plan['selected_total'] == 74 and plan['original_job_timeout_seconds'] == 5400
    steps = {x['name']: x for x in plan['steps']}
    extra = read(native / 'h4-extra-controls.json')
    expected_order = ['dependencies', 'execution-source-controls', 'diverse-source-controls'] + [x['name'] for x in plan['steps'] if x['name'] not in ('dependencies', 'fix')] + ['original-six-effect-controls', 'provider-effect-existing-and-pq', 'final-use-profile-controls', 'full-evidence-library', 'fix', 'format']
    assert list(pipeline['gates']) == expected_order and len(expected_order) == 20
    selected_count, identities, reviews, all_cases = 0, set(), [], []
    actual_records = {}
    live_count, direct_count, auxiliary = 0, 0, []
    previous_finish = 0
    for name, gate in pipeline['gates'].items():
        receipt_raw = (run / gate['receipt']).read_bytes()
        receipt = json.loads(receipt_raw)
        raw = (run / receipt['log_file']).read_bytes()
        assert digest(receipt_raw) == gate['receipt_sha256']
        assert digest(raw) == receipt['log_sha256'] and len(raw) == receipt['log_bytes']
        assert receipt['before'] == receipt['after']
        assert receipt['before']['commit'] == SOURCE and receipt['before']['tree'] == TREE
        assert not receipt['before']['dirty'] and not receipt['timed_out'] and not receipt['output_limit_exceeded']
        assert receipt['status'] == 'passed' and receipt['command_exit_code'] == receipt['exit_code'] == gate['wrapper_exit'] == 0
        assert receipt['elapsed_seconds'] <= gate['command_budget_seconds']
        start, finish = [datetime.fromisoformat(receipt[k]).timestamp() for k in ('started_at', 'finished_at')]
        assert previous_finish <= start <= finish
        previous_finish = finish
        text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw.decode())
        if name in steps:
            assert receipt['command'] == steps[name]['command']
            assert gate['command_budget_seconds'] == steps[name]['timeout_seconds']
        if name in ('dependencies', 'execution-source-controls', 'diverse-source-controls', 'fix', 'format'):
            assert gate['actual_binary_evidence'] is None
            if name in ('execution-source-controls', 'diverse-source-controls'):
                count = 135 if name == 'execution-source-controls' else 32
                assert re.search(r'Ran ' + str(count) + r' tests? in ', text)
                assert receipt['observed_passed_tests'] == count and gate['command_budget_seconds'] == 3600
            if name == 'format':
                assert receipt['command'] == ['just', 'fmt', '--base', '1556a4df6e279055fd8196f81a4ca2fe0f19384a']
                assert gate['command_budget_seconds'] == 300 and raw == b''
            continue
        cases = re.findall(r'^test (\S+) \.\.\. (ok|FAILED|ignored)\s*$', text, re.M)
        assert cases and all(outcome == 'ok' for _, outcome in cases)
        assert len(cases) == receipt['observed_passed_tests'] and receipt['observed_failed_tests'] == 0
        if name in steps:
            assert Counter(cases) == Counter((n, 'ok') for n in steps[name]['expected_names'])
            selected_count += len(cases)
        elif name == 'original-six-effect-controls':
            assert Counter(cases) == Counter((n, 'ok') for n in extra['original_six_effect_controls'])
        elif name == 'provider-effect-existing-and-pq':
            assert len(cases) == 10 and all(n.startswith('provider_effect::') for n, _ in cases)
        elif name == 'final-use-profile-controls':
            assert len(cases) == 50 and all('final_use' in n and '::' in n for n, _ in cases)
        else:
            assert name == 'full-evidence-library' and len(cases) == 161
            full = extra['full_evidence_library']
            assert receipt['command'] == full['command'] and receipt['minimum_tests'] == full['minimum'] == 22
            assert Counter(cases) == Counter((n, 'ok') for n in full['expected_names'])
        if name not in steps:
            assert gate['command_budget_seconds'] == 600
        fd_name, live_name = name + '.fd-executed-binaries.json', name + '.live-polled-binaries.json'
        evidence = read(run / fd_name)
        config_path = run / (name + '.fd-capture-config.json')
        config = read(config_path)
        assert evidence == gate['actual_binary_evidence'] and not evidence['errors']
        assert [list(x) for x in cases] == evidence['actual_cases'] == gate['observed_cases']
        assert evidence['per_case_bijection_verified'] and evidence['runner_sha256'] == RUNNER
        assert evidence['config_sha256'] == digest(config_path.read_bytes())
        records = evidence['records']
        assert Counter(r['exact_test'] for r in records) == Counter(n for n, _ in cases)
        assert len(records) == len(cases) == len({n for n, _ in cases})
        expected_images = 2 if name == 'neural-runtime-input' else 1
        assert evidence['runner_declared_binary_counts'] == [expected_images]
        assert len(evidence['unique_actual_elf_sha256']) == expected_images
        for index, record in enumerate(records):
            assert record['source'] == config['source'] == gate['source']
            assert record['source']['commit'] == SOURCE and record['source']['tree'] == TREE
            assert record['source']['environment_sha256'] == ENVIRONMENT
            assert record['coordinator'] == config['coordinator'] == COORDINATOR
            assert record['phase'] == 'run' and record['status'] == 'pre_exec_fd_bound'
            assert record['coordinator_descendant_verified'] and record['pre_exec_fd_identity_verified']
            assert record['gate'] == name and record['runner_sha256'] == RUNNER
            assert record['capture_config_sha256'] == evidence['config_sha256']
            assert record['observed_selected_tests'] == [record['exact_test']]
            assert record['argv'][0] == record['actual_executable']
            assert record['argv'].count('--exact') == 1 and '--list' not in record['argv']
            assert record['argv'][record['argv'].index('--exact') + 1] == record['exact_test']
            assert record['sha256'] in evidence['unique_actual_elf_sha256']
            identity = record['pid'], record['start_ticks']
            assert identity not in identities
            identities.add(identity)
            assert start <= record['captured_unix'] <= finish
            actual_records[(fd_name, index)] = record
            all_cases.append({'gate': name, 'target': record['expected_binary_target'], 'test': record['exact_test'], 'outcome': 'ok'})
        live_raw = (run / live_name).read_bytes()
        live = json.loads(live_raw)
        assert digest(live_raw) == evidence['live_polling_corroboration']['sha256'] and not live['errors']
        correspondence = verifier.verify(name, evidence, live)
        assert correspondence == evidence['live_process_correspondence'] and not correspondence['errors']
        for index, record in enumerate(live['records']):
            assert start <= record['captured_unix'] <= finish
            actual_records[(live_name, index)] = record
        live_count += len(live['records'])
        direct_count += len(correspondence['direct_fd_matches'])
        auxiliary.extend(correspondence['auxiliary_processes'])
        reviews.append({'gate': name, 'passed_outcomes': len(cases), 'raw_sha256': digest(raw), 'raw_bytes': len(raw), 'fd_config_sha256': evidence['config_sha256'], 'fd_records': len(records), 'live_records': len(live['records']), 'auxiliary_records': len(correspondence['auxiliary_processes'])})
    assert selected_count == 74 and len(reviews) == 15 and len(identities) == len(all_cases) == 301
    assert len({(c['target'], c['test']) for c in all_cases}) == 276
    assert live_count == 294 and direct_count == 293 and len(auxiliary) == 1
    assert auxiliary[0]['pid'] == 1159872 and auxiliary[0]['start_ticks'] == '99685414'
    assert auxiliary[0]['parent_pid'] == 1159870 and auxiliary[0]['parent_start_ticks'] == '99685394'
    assert auxiliary[0]['test_outcome_credit'] is False
    assert manifest['unexecuted'] == []
    assert manifest['coordinator_elapsed_seconds'] == pipeline['timed_coordinator_elapsed_seconds'] < 5400
    ignored = read(run / 'full-evidence-ignored-list.json')
    assert ignored['exit_code'] == 0 and ignored['same_image']
    assert ignored['expected_ignored'] == ignored['actual_ignored'] == ['authbus_outbox_tests::crash_delivery_child']
    assert ignored['command'][1:] == ['--list', '--ignored', '--format', 'terse']
    assert ignored['sha256'] in read(run / 'full-evidence-library.fd-executed-binaries.json')['unique_actual_elf_sha256']
    assert digest((run / 'full-evidence-ignored-list.log').read_bytes()) == ignored['log_sha256']
    for name, count in [('collector-controls', 3), ('fd-runner-controls', 3), ('fd-target-controls', 4), ('live-parent-correspondence-controls', 3)]:
        receipt, raw = read(run / (name + '.json')), (run / (name + '.log')).read_bytes()
        assert receipt['exit_code'] == 0 and digest(raw) == receipt['sha256']
        assert re.search(r'Ran ' + str(count) + r' tests in ', raw.decode())
        assert re.search(r'\nOK\s*$', raw.decode())

    proof_path = run / 'effect-pq-product-process/1153922-1793919086819941674/completed.json'
    proof_raw = proof_path.read_bytes()
    proof = json.loads(proof_raw)
    assert (proof['post_count'], proof['physical_apply_count'], proof['lookup_count'], proof['used_nonces']) == (1, 1, 2, 1)
    for ack, record in [('provider_operation_id_sha256', 'provider_operation_id_sha256'), ('payload_sha256', 'payload_sha256'), ('key', 'effect_key')]:
        assert proof['provider_ack'][ack] == proof['provider_record'][record]
    assert proof['terminal']['observation'] == 'succeeded'
    first, second = proof['first_process'], proof['second_process']
    for key in ('sha256', 'bytes', 'device', 'inode', 'retained_copy', 'source'):
        assert first[key] == second[key]
    assert first['source']['commit'] == SOURCE and first['source']['tree'] == TREE
    assert first['full_hash_and_copy_this_capture'] and not second['full_hash_and_copy_this_capture']
    assert second['same_held_file_object_verified'] and second['capture_method'] == 'same-held-file-object-reuse'
    assert (first['pid'], first['start_ticks'], first['spawn_generation']) == (1154142, '99675455', 1)
    assert (second['pid'], second['start_ticks'], second['spawn_generation']) == (1155773, '99678906', 5)
    inventory_raw = (run / 'h4-actual-image-inventory.json').read_bytes()
    assert digest(inventory_raw) == INVENTORY
    inventory = json.loads(inventory_raw)
    assert inventory['job_id'] == JOB and inventory['source_commit'] == SOURCE and inventory['source_tree'] == TREE
    images = inventory['images']
    assert len(images) == len({i['sha256'] for i in images}) == 11
    assert sum(i['bytes'] for i in images) == inventory['complete_image_unique_bytes'] == 1674575368
    assert sum(len(i['retained_aliases']) for i in images) == inventory['complete_retained_alias_count'] == 32
    assert inventory['partial_artifacts'] == []
    seen_observations = set()
    for image in images:
        observed_aliases, observed_paths = set(), set()
        for observation in image['observations']:
            artifact = observation['evidence_file']
            assert digest((run / artifact).read_bytes()) == observation['evidence_sha256']
            if 'generation_role' in observation:
                role = observation['generation_role']
                assert role in ('first', 'second')
                key = (artifact, role)
                original = proof[role + '_process']
                assert observation['test_outcome_credit'] is False
            else:
                key = (artifact, observation['evidence_record_index'])
                original = actual_records[key]
                assert observation['selected'] == original['observed_selected_tests']
                assert observation['test_outcome_credit'] == (observation['method'] == 'pre-exec-fd')
            assert key not in seen_observations
            seen_observations.add(key)
            assert original['sha256'] == image['sha256'] and original['bytes'] == image['bytes']
            for field in ('pid', 'start_ticks', 'device', 'inode', 'retained_copy'):
                assert original[field] == observation[field]
            assert observation['source_commit'] == SOURCE and observation['source_tree'] == TREE
            observed_aliases.add(original['retained_copy'])
            observed_paths.add(original['actual_executable'])
        assert observed_aliases == set(image['retained_aliases'])
        assert observed_paths == set(image['actual_paths'])
    assert len(seen_observations) == 597 and len(actual_records) == 595
    assert set(actual_records).issubset(seen_observations)

    output.mkdir(parents=True, exist_ok=True)
    copied = output / 'complete-raw'
    for entry in manifest['files']:
        target = copied / entry['relative_path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(run / entry['relative_path'], target)
    shutil.copyfile(native / 'h4-native-attempt1-delivery.json', copied / 'h4-native-attempt1-delivery.json')
    for name in external:
        shutil.copyfile(native / name, copied / name)
    report = {
        'schema': 'root-H4-complete-raw-review-v1', 'source_commit': SOURCE, 'source_tree': TREE,
        'delivery_sha256': DELIVERY, 'verified_delivered_files': 131, 'delivered_bytes': 5522990,
        'job_id': JOB, 'native_result': 'SUCCEEDED exit0; one-source desktop/x64 original sequence only',
        'actual_coordinator_seconds': manifest['coordinator_elapsed_seconds'], 'outer_budget_seconds': 5400,
        'original_gate_logs_checked': 20, 'selected_passed_outcomes': 74,
        'additional_passed_outcomes': {'compatibility': 6, 'provider': 10, 'final_use': 50, 'full_library': 161},
        'actual_rust_case_executions': 301, 'distinct_target_case_pairs': 276,
        'source_controls': [135, 32], 'utility_controls': [3, 3, 4, 3],
        'fix_exit_code': 0, 'format_exit_code': 0, 'ignored': ignored['actual_ignored'],
        'actual_live_records': 294, 'direct_live_records': 293, 'auxiliary_live_records': auxiliary,
        'gate_reviews': reviews, 'actual_cases': all_cases,
        'tracked_source_and_5_git_configurations_unchanged': True,
        '12_external_configuration_files_verified_before_and_after': True,
        'all_15_per_gate_fd_configs_verified': True, 'source_tracked_files': 11840, 'source_tracked_bytes': 183410043,
        'retained_before_and_after_bytecode_bytes': [6094, 6094],
        'runtime_scope': 'Bounded post-run inputs; no complete import/runtime closure claim.',
        'controlled_process_proof_sha256': digest(proof_raw),
        'process_counts': {'post': 1, 'physical_apply': 1, 'lookup': 2, 'nonce': 1},
        'process_scope': 'Controlled supervisor pre-fencing then SIGKILL; second image observation reuses a held file object. No whole-host restore or independent custody qualification.',
        'actual_inventory_sha256': INVENTORY, 'inventory_observations_verified_against_originals': 597,
        'unique_complete_images': 11, 'logical_image_bytes': 1674575368, 'retained_aliases': 32,
        'actual_ELF_byte_closure': 'Separate reviewed archive and full-byte readback still required; image hashes alone do not complete delivery.',
        'historical_failures': 'H1/H2/H3 unchanged; H4 helper observations cannot be backfilled into H3.',
        'whole_joint_gates': 'HOLD',
    }
    target = output / 'root-complete-raw-review.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'path': str(target), 'sha256': digest(target.read_bytes()), 'verified_files': 131, 'actual_rust_executions': 301, 'unique_target_cases': 276, 'live_records': 294, 'inventory_observations': 597, 'native': 'SUCCEEDED', 'whole_joint_gates': 'HOLD'}))


if __name__ == '__main__':
    main()
