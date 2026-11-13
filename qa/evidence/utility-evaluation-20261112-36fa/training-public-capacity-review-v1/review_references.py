"""Verify local read-only references against the pinned complete cc57 inventory."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
inventory_path = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
raw = inventory_path.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9'
by_path = {row['path']: row for row in json.loads(raw)['files']}
rows = []
for source in sorted((HERE / 'reference').glob('*.rs')):
    path = 'codex-rs/hepta-agentd/src/' + source.name
    expected = by_path[path]
    body = source.read_bytes()
    sha = hashlib.sha256(body).hexdigest()
    blob = hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest()
    assert len(body) == expected['bytes'] and sha == expected['sha256'] and blob == expected['working_blob'], path
    rows.append({'path': path, 'bytes': len(body), 'sha256': sha, 'git_blob': blob})
print(json.dumps({'source': 'cc57c7198db6293ccca562253c42fffbe2a04633',
                  'tree': 'b7b357c07b5539769a068c6b9b009629f5612d1e',
                  'canonical_inventory_sha256': hashlib.sha256(raw).hexdigest(),
                  'source_references': rows, 'H_calls': 0, 'Rust_execution': False,
                  'source_edits': False, 'qualification': False}, indent=2, sort_keys=True))
