"""Pure byte/patch checks only; does not execute any candidate Rust or gate."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile

root = Path('/tmp/hepta-36fa-b-preheld-objective-increment-v1')
packet = json.loads((root / 'SOURCE_PACKET.json').read_text())


def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


checks = []
with tempfile.TemporaryDirectory(prefix='hepta-b-objective-static-') as temporary:
    applied = Path(temporary)
    for change in packet['changes']:
        for side in ('before', 'after'):
            data = (root / side / change['path']).read_bytes()
            assert pin(data) == change[side]
            assert data.decode() == change[side + '_text']
        destination = applied / change['path']
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(change['before_text'])
    commands = [
        ['git', 'apply', '--check', str(root / 'SOURCE_DELTA.patch')],
        ['git', 'apply', str(root / 'SOURCE_DELTA.patch')],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=applied, capture_output=True, text=True)
        assert result.returncode == 0, (command, result.stderr)
    for change in packet['changes']:
        assert (applied / change['path']).read_text() == change['after_text']
    result = subprocess.run(['git', 'apply', '--reverse', str(root / 'SOURCE_DELTA.patch')],
                            cwd=applied, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for change in packet['changes']:
        assert (applied / change['path']).read_text() == change['before_text']
        checks.append({'path': change['path'], 'forward_full_bytes_equal': True,
                       'reverse_full_bytes_equal': True})

stage_before = packet['changes'][2]['before_text']
stage_after = packet['changes'][2]['after_text']
assert stage_after.startswith(stage_before)
assert stage_before.count('#[tokio::test(') == 2
assert stage_after.count('#[tokio::test(') == 3

source_before = packet['changes'][0]['before_text']
source_after = packet['changes'][0]['after_text']
assertion_counts = {}
for marker in ('assert_eq!(', 'assert!(', 'material::evaluation_provider::decision(',
               'material::evaluation_provider::outcome('):
    assert source_before.count(marker) == source_after.count(marker), marker
    assertion_counts[marker] = source_before.count(marker)

fresh_before = packet['changes'][1]['before_text']
fresh_after = packet['changes'][1]['after_text']
old_method = fresh_before[fresh_before.index('    pub(in super::super) fn from_original_completion('):
                          fresh_before.index('\n}\n\n/// Created before Material/T;')]
new_method = fresh_after[fresh_after.index('    pub(in super::super) fn from_original_completion('):
                        fresh_after.index('\n\n    /// Receive a complete pre-held')]
restored = new_method.replace(
    '            objective: BorrowedOriginalObjective::from_original_record(previous.original_record()),',
    '            previous,')
assert restored == old_method

root89 = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3/overlay-pending-material-registration-v3')
root89_checks = []
for change in packet['changes']:
    assert (root89 / change['path']).read_text() == change['before_text']
    root89_checks.append({'path': change['path'], 'root89_full_before_bytes_equal': True,
                          'git_blob': change['before']['git_blob']})

report = {
    'scope': 'Pure file identities and Git patch application in a throw-away directory; '
             'no Rust module execution, compiler, formatter, QA or H',
    'patch_check_returncode': 0,
    'forward_and_reverse': checks,
    'original_two_test_methods_full_prefix_equal': True,
    'new_unexecuted_test_methods': 1,
    'old_from_original_completion_exact_after_one_field_projection': True,
    'old_B_assertion_and_signed_append_counts_unchanged': assertion_counts,
    'packet': pin((root / 'SOURCE_PACKET.json').read_bytes()),
    'patch': pin((root / 'SOURCE_DELTA.patch').read_bytes()),
    'root89_preimages': {'map': '23d710dbda6f7d88ef6b693c1e77933d168b0177',
                        'checks': root89_checks},
}
(root / 'BYTE_PATCH_REVIEW.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
