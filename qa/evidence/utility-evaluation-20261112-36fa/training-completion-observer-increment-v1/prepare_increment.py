"""Prepare a test-only additive increment; never edit the frozen base."""
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = Path('/tmp/hepta-36fa-fresh-training-b-fixture-proposal-v1')
PREFIX = Path('codex-rs/hepta-agentd/src')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(raw)


items = [
    ('cell_q24_training_bootstrap_original_ports_tests.rs', BASE / 'after' / PREFIX,
     'aec983844a859a7d292f2ab53fd3756d2a42a222', 'bootstrap_append.rs.txt'),
    ('cell_q24_training_command_support_tests.rs', HERE / 'reference',
     '80e37d6b6f41081cc661850ea29b9ff61a5787ef', 'command_append.rs.txt'),
]
changes, patches = [], []
for name, parent, expected, addition in items:
    before = (parent / name).read_bytes()
    assert pin(before)['git_blob'] == expected
    after = before + (HERE / addition).read_bytes()
    assert after.startswith(before)
    path = (PREFIX / name).as_posix()
    write(HERE / 'before' / path, before)
    write(HERE / 'after' / path, after)
    changes.append({'path': path, 'before': pin(before), 'after': pin(after),
                    'old_bytes_exact_prefix': True,
                    'before_content': before.decode(), 'after_content': after.decode()})
    patches.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                   fromfile='a/' + path, tofile='b/' + path))
packet = {'format': 'hepta-test-only-training-completion-observer-increment-v1',
          'status': 'HOLD_UNFORMATTED_UNCOMPILED_UNEXECUTED',
          'canonical_source': 'cc57c7198db6293ccca562253c42fffbe2a04633',
          'layered_fixture_packet': '8d5b1eeea4e63ae04bb77c91abc996a34cdeccfa',
          'changes': changes, 'source_activated': False, 'production_changes': 0,
          'H_Cargo_format_tests': 0, 'qualification': False}
write(HERE / 'SOURCE_PACKET.json', (json.dumps(packet, indent=2, sort_keys=True) + '\n').encode())
write(HERE / 'SOURCE_DELTA.patch', ''.join(patches).encode())
manifest = {k:v for k,v in packet.items() if k != 'changes'}
manifest['changes'] = [{k:v for k,v in row.items() if not k.endswith('_content')} for row in changes]
manifest['packet'] = pin((HERE / 'SOURCE_PACKET.json').read_bytes())
manifest['patch'] = pin((HERE / 'SOURCE_DELTA.patch').read_bytes())
write(HERE / 'MANIFEST.json', (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode())
print(json.dumps(manifest, indent=2, sort_keys=True))
