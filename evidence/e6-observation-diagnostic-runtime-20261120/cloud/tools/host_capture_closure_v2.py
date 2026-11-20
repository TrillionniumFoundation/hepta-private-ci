"""Validate a separately reviewed, actual, finite host-capture closure.

This is a local receipt/bytes checker, not a host crawl. The closure supplies
explicit JSON locations in pinned original inventory/capture documents. Its
finite scope and original-path set must be reviewed independently; successful
metadata enumeration alone does not prove capture, privacy, or experiment pass.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from archive_common import ROOT, excluded_name, safe_member, sha256, stable_read

SOURCE = 'dbd6a00992b60f4b33e8f10c2defda031d123bcb'
TREE = 'fe037f5b6617fb647d416e0523685fa4ce08ef2f'
INVENTORY = '20fe46de4b63f5a2bcce469113ebe27b7514f942c7f960a71e4dabaa4f643d0f'


def location(document: object, path: list) -> object:
    value = document
    for key in path:
        assert isinstance(key, (str, int)) and not isinstance(key, bool)
        value = value[key]
    return value


def validate_closure(path: Path, expected_sha256: str) -> tuple[dict, list[str]]:
    raw, unused = stable_read(path)
    assert sha256(raw) == expected_sha256
    closure = json.loads(raw)
    assert closure['schema'] == 'hepta.e6.dbd6.host-capture-closure.v1'
    assert closure['source'] == SOURCE and closure['tree'] == TREE
    assert closure['source_inventory_sha256'] == INVENTORY
    assert closure['status'] == 'ACTUAL_CAPTURE_COMPLETE_WITHIN_REVIEWED_PATH_SET'
    assert closure['whole_host_filesystem_claimed'] is False
    assert closure['complete_native_provenance_claimed'] is False
    assert isinstance(closure['unavailable_originals'], list)
    assert isinstance(closure['unexpanded_metadata_roots'], list)
    assert isinstance(closure['scope_description'], str) and closure['scope_description'].strip()
    assert closure['original_runtime_roots'] and all(
        PurePosixPath(p).is_absolute() for p in closure['original_runtime_roots']
    )

    pins = {}
    documents = {}
    extra_paths = {str(path.relative_to(ROOT))}
    for pin in closure['evidence_pins']:
        relative = pin['workspace_relative_path']
        assert safe_member(relative) and relative not in pins
        local = ROOT / relative
        assert excluded_name(local) is None
        data, unused = stable_read(local)
        assert len(data) == pin['bytes'] and sha256(data) == pin['sha256'], relative
        pins[relative] = pin
        extra_paths.add(relative)
        documents[relative] = data

    def selected(spec):
        relative = spec['evidence_path']
        assert relative in pins
        return location(json.loads(documents[relative]), spec['location'])

    # At least one original successful capture RESULT and one independent Root
    # readback/review must be pinned. Their meaning is not inferred from filenames.
    assert closure['capture_result_checks'] and closure['root_readback_paths']
    for check in closure['capture_result_checks']:
        assert check['location'] == ['successful']
        assert selected(check) is True
        result = json.loads(documents[check['evidence_path']])
        assert result['source'] == SOURCE and result['command_exit'] == 0
        manifest_pin = pins[check['manifest_evidence_path']]
        assert location(result, check['manifest_sha256_location']) == manifest_pin['sha256']
    for relative in closure['root_readback_paths']:
        assert relative in pins
    assert closure['key_nonread_result_checks']
    for check in closure['key_nonread_result_checks']:
        assert selected(check) is False

    expected = closure['expected_original_paths']
    assert expected and len(expected) == len(set(expected))
    expected_set = set(expected)
    roots = [PurePosixPath(p) for p in closure['original_runtime_roots']]
    for original in expected:
        p = PurePosixPath(original)
        assert p.is_absolute() and '..' not in p.parts
        assert any(p.is_relative_to(root) for root in roots)
        assert excluded_name(Path(original)) is None

    excluded_keys = closure['excluded_key_paths']
    assert len(excluded_keys) == len(set(excluded_keys))
    assert expected_set.isdisjoint(excluded_keys)
    assert closure['key_metadata_checks']
    observed_keys = set()
    for spec in closure['key_metadata_checks']:
        for row in selected(spec):
            original = location(row, spec['path_location'])
            assert original in excluded_keys
            assert location(row, spec['sha256_location']) is None
            assert location(row, spec['body_exported_location']) is False
            observed_keys.add(original)
    assert observed_keys == set(excluded_keys)

    # Inventory schemas may differ between the bounded collection stages. The
    # mapping is explicit and pinned, and every expected path needs an actual row.
    inventory_rows = {}
    for spec in closure['inventory_checks']:
        for row in selected(spec):
            original = location(row, spec['path_location'])
            if original not in expected_set:
                continue
            assert location(row, spec['kind_location']) == 'regular'
            size = location(row, spec['bytes_location'])
            assert isinstance(size, int) and not isinstance(size, bool) and size >= 0
            if original in inventory_rows:
                assert inventory_rows[original] == size
            inventory_rows[original] = size
    assert set(inventory_rows) == expected_set

    manifest_rows = {}
    for spec in closure['capture_manifest_checks']:
        for row in selected(spec):
            original = location(row, spec['path_location'])
            assert original in expected_set and original not in manifest_rows
            assert original not in excluded_keys and excluded_name(Path(original)) is None
            manifest_rows[original] = {
                'bytes': location(row, spec['bytes_location']),
                'sha256': location(row, spec['sha256_location']),
                'remote_captured_path': location(row, spec['captured_path_location']),
            }
    assert set(manifest_rows) == expected_set

    local_paths = set()
    captured = {}
    for row in closure['captured_files']:
        original = row['original_path']
        relative = row['workspace_relative_path']
        assert original in expected_set and original not in captured
        assert safe_member(relative) and relative not in local_paths
        assert original not in excluded_keys
        # Both names are checked before opening the local captured body.
        assert excluded_name(Path(original)) is None and excluded_name(ROOT / relative) is None
        assert manifest_rows[original] == {
            'bytes': row['bytes'], 'sha256': row['sha256'],
            'remote_captured_path': row['remote_captured_path'],
        }
        assert excluded_name(Path(row['remote_captured_path'])) is None
        assert inventory_rows[original] == row['bytes']
        data, unused = stable_read(ROOT / relative)
        assert len(data) == row['bytes'] and sha256(data) == row['sha256'], original
        captured[original] = row
        local_paths.add(relative)
        extra_paths.add(relative)
    assert set(captured) == expected_set
    return {
        'closure_path': str(path), 'closure_sha256': expected_sha256,
        'scope_description': closure['scope_description'],
        'original_runtime_roots': closure['original_runtime_roots'],
        'reviewed_expected_path_count': len(expected_set),
        'captured_path_count': len(captured),
        'captured_bytes': sum(row['bytes'] for row in captured.values()),
        'excluded_distinct_key_paths': len(excluded_keys),
        'actual_result_inventory_capture_and_local_bytes_bound': True,
        'whole_host_filesystem_claimed': False,
        'complete_native_provenance_claimed': False,
        'unavailable_originals': closure['unavailable_originals'],
        'unexpanded_metadata_roots': closure['unexpanded_metadata_roots'],
        'meaning_of_scope_requires_pinned_independent_review': True,
        'evidence_pins': closure['evidence_pins'],
        'root_readback_paths': closure['root_readback_paths'],
    }, sorted(extra_paths)
