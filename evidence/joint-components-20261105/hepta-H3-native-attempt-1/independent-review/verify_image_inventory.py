#!/usr/bin/env python3
"""Cross-reference the H3 image inventory to retained evidence records only."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
EVIDENCE = ROOT / 'model_storage/h3-preparation/native/joint-h3-native-attempt-1'


def main():
    path = EVIDENCE / 'h3-actual-image-inventory.json'
    data = path.read_bytes()
    inventory = json.loads(data)
    assert hashlib.sha256(data).hexdigest() == '6a8ecb8b9160284baf91d13b61973e4ee3b64b5a740cde0908ccd7b4c03361b7'
    assert inventory['status'] == 'FAILED'
    assert len(inventory['images']) == 11
    assert sum(image['bytes'] for image in inventory['images']) == inventory['complete_image_unique_bytes'] == 1674575368
    assert sum(len(image['retained_aliases']) for image in inventory['images']) == inventory['complete_retained_alias_count'] == 30
    assert len({image['sha256'] for image in inventory['images']}) == 11
    aliases, source_files, count = {}, {}, 0
    for image in inventory['images']:
        assert len(set(image['retained_aliases'])) == len(image['retained_aliases'])
        for alias in image['retained_aliases']:
            assert alias not in aliases
            aliases[alias] = (image['sha256'], image['bytes'])
        observed_aliases = set()
        observed_paths = set()
        for observation in image['observations']:
            source_name = observation['evidence_file']
            if source_name not in source_files:
                source_files[source_name] = json.loads((EVIDENCE / source_name).read_bytes())
            source = source_files[source_name]
            if image['kind'] == 'ordinary-daemon':
                original = source[observation['generation_role'] + '_process']
                assert observation['method'] == original['capture_method']
                for key in ('spawn_generation', 'origin_capture_pid', 'origin_capture_start_ticks',
                            'full_hash_and_copy_this_capture', 'same_held_file_object_verified'):
                    assert observation[key] == original[key]
            else:
                matches = [record for record in source['records']
                           if record['pid'] == observation['pid'] and record['start_ticks'] == observation['start_ticks']]
                assert len(matches) == 1
                original = matches[0]
                selected = [original['exact_test']] if observation['method'] == 'pre-exec-fd' else original['observed_selected_tests']
                assert observation['selected'] == selected
                receipt = json.loads((EVIDENCE / (observation['gate'] + '.json')).read_bytes())
                assert observation['native_test_receipt_status'] == receipt['status']
                assert observation['external_binding_gate_passed'] is (observation['gate'] != 'final-use-profile-controls')
            for key in ('pid', 'start_ticks', 'retained_copy', 'device', 'inode'):
                assert observation[key] == original[key]
            assert observation['source_commit'] == original['source']['commit'] == inventory['source_commit']
            assert observation['source_tree'] == original['source']['tree'] == inventory['source_tree']
            assert original['sha256'] == image['sha256'] and original['bytes'] == image['bytes']
            observed_aliases.add(original['retained_copy'])
            observed_paths.add(original['actual_executable'])
            count += 1
        assert observed_aliases == set(image['retained_aliases'])
        assert observed_paths == set(image['actual_paths'])
    extra = inventory['unmatched_live_observations']
    assert len(extra) == 1 and extra[0]['matching_fd'] is None
    assert extra[0]['record']['pid'] == 1038111 and extra[0]['record']['start_ticks'] == '99368575'
    live = json.loads((EVIDENCE / 'final-use-profile-controls.live-polled-binaries.json').read_bytes())
    assert extra[0]['record'] == next(record for record in live['records'] if record['pid'] == 1038111)
    daemon = [image for image in inventory['images'] if image['kind'] == 'ordinary-daemon']
    assert len(daemon) == 1 and len(daemon[0]['retained_aliases']) == 1 and len(daemon[0]['observations']) == 2
    assert [item['full_hash_and_copy_this_capture'] for item in daemon[0]['observations']] == [True, False]
    assert [item['same_held_file_object_verified'] for item in daemon[0]['observations']] == [False, True]
    report = {
        'schema': 'h3-image-inventory-independent-review-v1',
        'inventory': {'path': str(path.relative_to(ROOT)), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
        'source_commit': inventory['source_commit'], 'source_tree': inventory['source_tree'],
        'status_preserved': 'FAILED', 'unique_images': 11, 'unique_bytes': 1674575368,
        'retained_aliases': 30, 'observations_cross_referenced': count,
        'input_evidence_files': [
            {'path': name, 'bytes': len((EVIDENCE / name).read_bytes()),
             'sha256': hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest()}
            for name in sorted(source_files)],
        'unmatched_live_pid': 1038111, 'unmatched_live_start_ticks': '99368575',
        'unmatched_live_not_relabelled_or_retroactively_attributed': True,
        'daemon_two_generations_one_retained_actual_image': True,
        'second_daemon_full_hash_and_copy': False,
        'maximum_single_image_bytes': max(image['bytes'] for image in inventory['images']),
        'scope': 'Metadata and original receipt/record cross-reference only. No remote ELF byte read, archive execution, or native rerun. Complete-image inventory does not prove absence of unrecorded partial files elsewhere. Export must preserve FAILED status, all alias provenance, and old unmatched-parent boundary.'}
    output = OUT / 'h3-image-inventory-review.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'path': str(output.relative_to(ROOT)), 'bytes': output.stat().st_size,
                      'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                      'observations': count, 'native_reruns': 0, 'remote_reads': 0}))


if __name__ == '__main__':
    main()
