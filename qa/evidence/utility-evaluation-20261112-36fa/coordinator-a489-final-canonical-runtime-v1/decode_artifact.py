import base64
import gzip
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
NATIVE = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1/run'
OUT = ROOT / 'artifacts'
OUT.mkdir(exist_ok=True)
ARTIFACTS = {row['name']: row for row in json.loads((ROOT / 'ARTIFACTS.json').read_bytes())}

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def create(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path), **identity(raw)}

def payload(path):
    outer = json.loads(path.read_bytes())
    assert not outer.get('isError'), str(path)
    blocks = [row['text'] for row in outer['content'] if row['type'] == 'text']
    assert len(blocks) == 1, str(path)
    return json.loads(blocks[0])

for name in sys.argv[1:]:
    assert pathlib.Path(name).name == name and name in ARTIFACTS
    expected = ARTIFACTS[name]
    paths = sorted(p for p in ROOT.iterdir() if re.fullmatch(re.escape(name) + r'\.READ_[0-9]{2}\.original\.json', p.name))
    assert paths, name
    cursor = 0
    version = None
    chunks = []
    reads = []
    for p in paths:
        row = payload(p)
        block = base64.b64decode(row['data_base64'], validate=True)
        if version is None:
            version = row['version']
        assert row['path'] == NATIVE + '/' + name and row['version'] == version and row['size'] == expected['bytes']
        assert row['offset'] == cursor and row['next_offset'] == cursor + len(block)
        assert hashlib.sha256(block).hexdigest() == row['chunk_sha256']
        assert row['eof'] == (row['next_offset'] == row['size'])
        reads.append({'sdk': p.name, 'sdk_identity': identity(p.read_bytes()), 'offset': cursor, 'next_offset': row['next_offset'], 'chunk_sha256': row['chunk_sha256']})
        cursor = row['next_offset']
        chunks.append(block)
    assert cursor == expected['bytes'] and row['eof'], name
    raw = b''.join(chunks)
    assert identity(raw) == {k: expected[k] for k in ('bytes', 'sha256', 'git_blob')}, name
    actual = create(OUT / name, raw)
    report = {'format': 'hepta-actual-canonical-artifact-binary-readback-v1', 'name': name, 'native_path': NATIVE + '/' + name, 'version': version, 'actual': actual, 'reads': reads, 'full_bytes_read_from_original_native_file': True}
    if 'raw_bytes' in expected:
        expanded = gzip.decompress(raw)
        assert identity(expanded) == {k: expected['raw_' + k] for k in ('bytes', 'sha256', 'git_blob')}, name
        report['decoded_raw'] = create(OUT / name[:-3], expanded)
        report['exact_original_format_parts_derived_from_actual_native_gzip'] = []
        for part in expected['parts']:
            start = part['decoded_offset']
            block = raw[start:start + part['decoded_bytes']]
            assert len(block) == part['decoded_bytes'] and hashlib.sha256(block).hexdigest() == part['decoded_sha256']
            encoded = base64.b64encode(block) + b'\n'
            assert identity(encoded) == {k: part[k] for k in ('bytes', 'sha256', 'git_blob')}
            report['exact_original_format_parts_derived_from_actual_native_gzip'].append(create(OUT / part['name'], encoded))
    report_raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
    review = create(ROOT / (name + '.DECODED_READBACK.json'), report_raw)
    print(json.dumps({'name': name, 'actual': actual, 'decoded_raw': report.get('decoded_raw'), 'readback': review}))
