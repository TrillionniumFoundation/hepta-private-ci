"""Save complete received MCP objects; optionally decode one bounded binary chunk."""
import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
name = sys.argv[1]
assert '/' not in name and name.endswith('.json')
record = json.loads(sys.argv[2])
path = ROOT / 'receipts' / name
with path.open('x') as stream:
    json.dump(record, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
result = record['result']
assert not result.get('isError'), name
payload = json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))
if record['kind'] == 'chunk':
    raw = base64.b64decode(payload['data_base64'], validate=True)
    assert len(raw) == payload['next_offset'] - payload['offset']
    assert len(raw) <= record['request']['limit']
    assert hashlib.sha256(raw).hexdigest() == payload['chunk_sha256']
    assert payload['offset'] == record['request']['offset']
    assert payload['version'] == record['request']['expected_version']
    assert payload['next_offset'] == payload['offset'] + len(raw)
    chunk_name = name.removesuffix('.json') + '.bin'
    with (ROOT / 'chunks' / chunk_name).open('xb') as stream:
        stream.write(raw)
    print(json.dumps({'chunk': chunk_name, 'bytes': len(raw), 'sha256': payload['chunk_sha256']}))
else:
    print(json.dumps({'receipt': name, 'bytes': payload.get('size'), 'sha256': payload.get('sha256')}))
