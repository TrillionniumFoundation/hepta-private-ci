#!/usr/bin/env python3
"""Independent fake-only replay of the originally observed ANSI/percent defect."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(
        b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
        'sha256': hashlib.sha256(data).hexdigest()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument('--output-directory', type=Path, required=True)
    args = ap.parse_args()
    root = args.root.resolve()
    collector = root / 'author-frozen/support/collect.py'
    assert identity(collector.read_bytes())['git_blob'] == 'f1dae501e6daa5b6ac8e26c9ed09729301c8e34f'
    previous = json.loads((root / 'preliminary-ansi/RESULTS.json').read_bytes())
    assert previous['draft_collector']['git_blob'] == '3537a5ed6562d22e44f329886396b93372dfe280'
    prior_leak = next(c for c in previous['results'] if c['name'] == 'percent_ansi_in_known_credential')
    assert prior_leak['exit'] == 0 and prior_leak['public_log_bytes_equal']
    fake = 'MOCK_ONLY_KNOWN_CREDENTIAL_468209'
    cases = [
        ('benign_ansi', b'\x1b[31merror:\x1b[0m ordinary dependency message\n', True, None),
        ('raw_known_credential', ('note ' + fake + '\n').encode(), False, 'KNOWN_CREDENTIAL_FOUND'),
        ('literal_ansi_in_known_credential', b'note MOCK_ONLY_\x1b[31mKNOWN_CREDENTIAL_468209\x1b[0m\n', False, 'KNOWN_CREDENTIAL_FOUND'),
        ('percent_ansi_in_known_credential', b'note MOCK_ONLY_%1b[31mKNOWN_CREDENTIAL_468209%1b[0m\n', False, 'KNOWN_CREDENTIAL_FOUND'),
        ('four_layer_percent_ansi', b'note MOCK_ONLY_%2525251b[31mKNOWN_CREDENTIAL_468209%2525251b[0m\n', False, 'KNOWN_CREDENTIAL_FOUND'),
        ('decoded_unsupported_control', b'ordinary message %07\n', False, 'UNSUPPORTED_CONTROL_BYTES'),
    ]
    out = args.output_directory.resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for name, log, expected_safe, expected_error in cases:
        case = out / name
        runner = case / 'runner'
        runner.mkdir(parents=True)
        evidence = Path(tempfile.mkdtemp(prefix='cargo-deny-evidence.', dir=runner))
        github_output = case / 'github-output.txt'
        github_output.write_bytes(b'')
        inputs = {
            'cargo-deny.log': log,
            'command-exit-code.txt': b'7\n', 'console-copy-exit-code.txt': b'0\n',
            'after-capture-exit-code.txt': b'0\n',
            'cargo-version.txt': b'cargo 1.95.0 (offline-stub)\n',
            'rustc-version.txt': b'rustc 1.95.0 (offline-stub)\n',
            'cargo-deny-version.txt': b'cargo-deny 0.19.0\n',
            'version-exits.json': b'{"cargo":0,"rustc":0,"cargo-deny":0}\n',
        }
        for phase in ('before', 'after'):
            inputs['source-' + phase + '.json'] = (json.dumps({
                'phase': phase, 'head': 'a'*40, 'tree': 'b'*40,
                'clean': True, 'git_exit_codes': [0, 0, 0]}) + '\n').encode()
        for filename, data in inputs.items():
            (evidence / filename).write_bytes(data)
        env = {'PATH': os.environ['PATH'], 'RUNNER_TEMP': str(runner),
               'PRIVATE_EVIDENCE_DIR': str(evidence), 'GITHUB_OUTPUT': str(github_output),
               'FAKE_AUDIT_CREDENTIAL': fake, 'CARGO_TERM_COLOR': 'always'}
        result = subprocess.run([sys.executable, str(collector)], env=env,
                                capture_output=True, timeout=10)
        (case / 'stdout.json').write_bytes(result.stdout)
        (case / 'stderr.txt').write_bytes(result.stderr)
        report = json.loads(result.stdout)
        assert report['safe_for_upload'] is expected_safe
        assert report.get('error_code') == expected_error
        assert result.returncode == (0 if expected_safe else 1) and not result.stderr
        assert fake.encode() not in result.stdout
        if expected_safe:
            assert 'safe_for_upload=true\n' in github_output.read_text()
            assert (evidence / 'public/cargo-deny.log').read_bytes() == log
            assert report['original_command_exit_code'] == 7
        else:
            assert not (evidence / 'public').exists() and not github_output.read_bytes()
        assert all((evidence / name).read_bytes() == data for name, data in inputs.items())
        results.append({'case': name, 'input_log': identity(log), 'exit': result.returncode,
                        'safe_for_upload': expected_safe, 'error_code': report.get('error_code'),
                        'private_input_bytes_unchanged': True,
                        'uploaded_original_bytes_equal': expected_safe})
    print(json.dumps({'schema': 'cargo-deny-independent-ANSI-correction-v1',
                      'original_observed_false_negative': previous['draft_collector'],
                      'corrected_collector': identity(collector.read_bytes()),
                      'source_workflow': '57f6095d18c5517c9e7cf7d0de05b9645b106152',
                      'cases': results, 'all_passed': True,
                      'fake_only_no_cargo_or_CI_execution': True}, indent=2))


if __name__ == '__main__':
    main()
