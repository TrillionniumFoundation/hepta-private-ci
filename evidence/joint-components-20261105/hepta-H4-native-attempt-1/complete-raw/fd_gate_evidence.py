"""Require one opened-image record for every actual libtest result.

Pre-exec metadata alone receives no execution credit. Discovery is excluded.
This external verifier is paired with the original nextest outcome log.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re

from nextest_fd_runner import declared_binary_target
from nextest_fd_runner import fixed_case_targets


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def verify(config_path, runner_path, cases, declared_binary_counts):
    config_path = Path(config_path)
    config = json.loads(config_path.read_text())
    directory = Path(config['directory'])
    result = {'binding_method': 'opened ELF fd then same-PID exec, matched to actual libtest outcome',
              'config_file': str(config_path), 'config_sha256': digest(config_path),
              'runner_sha256': digest(runner_path), 'records': [], 'errors': [],
              'unique_actual_elf_sha256': [], 'runner_declared_binary_counts': declared_binary_counts,
              'actual_cases': cases, 'per_case_bijection_verified': False,
              'scope': 'exact test images only; no retrospective H1 credit or complete dynamic runtime closure'}
    try:
        mapping = fixed_case_targets(config)
        expected_targets = set(mapping.values()) if mapping is not None else {config['crate']}
        result['expected_case_targets'] = mapping
        result['expected_binary_targets'] = sorted(expected_targets)
        assert not list(directory.glob('*.exec-error.json')), 'an fd-exec failure was recorded'
        assert not list(directory.glob('*.pending')), 'an incomplete opened-image record or copy remains'
        records = [json.loads(path.read_text()) for path in sorted(directory.glob('*.json'))]
        result['records'] = records
        assert records, 'no exact run image records'
        assert declared_binary_counts == [len(expected_targets)], 'nextest binary count differs from the exact declared target set'
        assert cases and all(outcome in ('ok', 'FAILED') for _, outcome in cases), 'no actual run outcomes or selected skip'
        observed = Counter(name for name, _ in cases)
        if mapping is not None:
            assert observed == Counter(mapping.keys()), 'the multi-target gate did not run its exact case set once'
        recorded = Counter(record['exact_test'] for record in records)
        assert observed == recorded and all(count == 1 for count in observed.values()), 'actual outcome and opened-image records are not one-to-one'
        processes = [(record['pid'], record['start_ticks']) for record in records]
        assert len(set(processes)) == len(processes), 'a process identity was reused for more than one test'
        retained = {}
        targets = {}
        for record in records:
            assert record['schema'] == config['schema'] and record['status'] == 'pre_exec_fd_bound'
            assert record['phase'] == 'run' and record['gate'] == config['gate']
            assert record['source'] == config['source'] and record['coordinator'] == config['coordinator']
            assert record['capture_config_sha256'] == result['config_sha256']
            assert record['runner_sha256'] == result['runner_sha256']
            assert record['coordinator_descendant_verified'] and record['pre_exec_fd_identity_verified']
            assert record['observed_selected_tests'] == [record['exact_test']]
            args = record['argv']
            assert args.count('--exact') == 1 and '--list' not in args
            assert args[args.index('--exact') + 1] == record['exact_test']
            executable = Path(record['actual_executable'])
            assert args[0] == str(executable) and executable.is_relative_to(Path(config['target']))
            binary_target = declared_binary_target(config, executable)
            assert record['expected_binary_target'] == binary_target
            if mapping is not None:
                assert mapping[record['exact_test']] == binary_target, 'actual case used the wrong declared target'
            targets.setdefault(binary_target, set()).add(record['sha256'])
            image = Path(record['retained_copy'])
            assert image == directory / (record['sha256'] + '.elf')
            assert re.fullmatch(r'[a-f0-9]{64}', record['sha256'])
            if record['sha256'] not in retained:
                assert image.is_file() and not image.is_symlink()
                assert image.stat().st_size == record['bytes'] and digest(image) == record['sha256']
                retained[record['sha256']] = record['bytes']
            assert retained[record['sha256']] == record['bytes']
        result['unique_actual_elf_sha256'] = sorted(retained)
        assert set(targets) == expected_targets and all(len(images) == 1 for images in targets.values()), 'each exact target must have exactly one actual image'
        assert len(retained) == len(expected_targets), 'actual image count differs from the declared target set'
        result['actual_images_by_target'] = {name: sorted(images) for name, images in targets.items()}
        result['per_case_bijection_verified'] = True
    except Exception as error:
        result['errors'].append(repr(error))
    return result
