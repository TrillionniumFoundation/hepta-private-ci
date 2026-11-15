"""Immutable boundary inputs and transport requests; expected output is never synthesized."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import struct

MAX = (1 << 64) - 1


def adversarial_fixture(output):
    source = Path(__file__).with_name("adversarial.json.gz")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == "bde43b6b7fffb88e8e7173fa3df2ae9d4a8ffd6fd5a0b446a231306b0b25af1c"
    data = gzip.decompress(source.read_bytes())
    assert len(data) == 1125050
    assert hashlib.sha256(data).hexdigest() == "132d95e8eeb009d1d3c8ea5f728be0a4991c4c2cd03da59f13b4aba195ce963f"
    path = output / "adversarial-v1/cases.json"
    path.parent.mkdir()
    path.write_bytes(data)
    return path


def frontend_fixture(output):
    left = bytes.fromhex("000000000000000000000000000000000a").decode()
    right = bytes.fromhex("010000000000000053020000000100000a").decode()
    cases = []
    def add(name, old, new):
        for context in (0, 1, 3, MAX // 2 + 1, MAX):
            cases.append({"id": len(cases), "name": name, "old": old, "new": new, "context": context})
    for count in (100, 101, 102, 127, 128, 257):
        unique = [f"汉🙂e\u0301\0-{i:04x}\n" for i in range(count)]
        add(f"distinct-unicode-{count}", "".join(unique), "".join(unique[1:] + unique[:1]))
        add(f"distinct-unicode-reverse-{count}", "".join(unique), "".join(reversed(unique)))
        repeated = [("é🙂\0\n", "👩\u200d💻\r\n", "汉e\u0301\r")[i % 3] for i in range(count)]
        add(f"repeated-unicode-{count}", "".join(repeated), "".join(repeated[1:] + repeated[:1]))
        add(f"one-sided-unicode-{count}", "", "".join(unique))
        add(f"collision-fill-{count}", "filler\n" * (count - 1) + left, "filler\n" * (count - 1) + right)
        add(f"collision-alternate-{count}", "".join((left, right)[i % 2] for i in range(count)),
            "".join((right, left)[i % 2] for i in range(count)))
    data = (json.dumps(cases, ensure_ascii=True) + "\n").encode()
    assert len(cases) == 180 and hashlib.sha256(data).hexdigest() == "132d0063459e9bda8cb310ecfa2e9b2211e12738617e13f97f56d53a6c7c2b6f"
    path = output / "frontend.original/cases.json"
    path.parent.mkdir()
    path.write_bytes(data)
    return path


def prepare_cases(context):
    OUT, REPORT, common = context.output, context.report, context
    sources = [
        (adversarial_fixture(OUT), '132d95e8eeb009d1d3c8ea5f728be0a4991c4c2cd03da59f13b4aba195ce963f', 3732),
        (frontend_fixture(OUT), '132d0063459e9bda8cb310ecfa2e9b2211e12738617e13f97f56d53a6c7c2b6f', 180),
    ]
    cases = []
    REPORT['fixture_sources'] = []

    def full_chunk(old, new):
        old_lines = old.split('\n')
        if old_lines[-1] == '':
            old_lines.pop()
        return {'change_context': None, 'old_lines': old_lines, 'new_lines': new.split('\n'),
                'context_line_indices': [], 'is_end_of_file': False}

    def add(name, old, chunks, context=1, route=1, file_kind=0):
        cases.append({'id': len(cases), 'name': name, 'old_hex': old.hex(), 'chunks': chunks,
                      'context': context, 'route': route, 'file_kind': file_kind})

    for source, digest, count in sources:
        assert common.sha(source) == digest
        values = json.loads(source.read_bytes())
        assert len(values) == count
        REPORT['fixture_sources'].append(common.bind(source))
        for value in values:
            add(f"{source.parent.name}:{value['id']}", value['old'].encode(),
                [full_chunk(value['old'], value['new'])], value['context'])
        # Exercise the separate default-context public entry over each frontend shape.
        if count == 180:
            for value in values[::5]:
                add(f"default:{value['name']}", value['old'].encode(),
                    [full_chunk(value['old'], value['new'])], route=0)
    for route in (0, 1):
        for old, new in [('', ''), ('a\n', 'a\n'), ('a\r\nb\r', 'a\rb\r\n'),
                         ('same\nsame\nlast', 'same\nlast\n'), ('\x00汉🙂\n', '🙂\x00汉\n')]:
            add('direct-small', old.encode(), [full_chunk(old, new)], route=route)
        for old in (b'', b'a\n', b'a\r\nb\r'):
            add('empty-chunks', old, [], route=route)
        add('missing-file', b'', [], route=route, file_kind=1)
        add('directory-file', b'', [], route=route, file_kind=2)
        add('invalid-file-utf8', b'\xff\xfe', [], route=route)
        add('missing-match', b'a\n', [full_chunk('missing\n', 'new\n')], route=route)
    old = 'x' * (2 * 1024 * 1024) + '\n'
    add('two-mib-single-line', old.encode(), [full_chunk(old, old[:-2] + 'y\n')], 3)
    old = '汉🙂e\u0301\x00' * 65536 + '\n'
    add('large-unicode-single-line', old.encode(), [full_chunk(old, old + 'tail\n')], 0)
    common.create(OUT / 'cases.json', cases)
    binary = bytearray(b'UDOWN001') + struct.pack('<Q', len(cases))

    def number(value):
        binary.extend(struct.pack('<Q', value))

    def bytes_value(value):
        number(len(value))
        binary.extend(value)

    def strings(values):
        number(len(values))
        for value in values:
            bytes_value(value.encode())

    for case in cases:
        for key in ('id', 'route', 'context', 'file_kind'):
            number(case[key])
        bytes_value(bytes.fromhex(case['old_hex']))
        number(len(case['chunks']))
        for chunk in case['chunks']:
            number(chunk['change_context'] is not None)
            if chunk['change_context'] is not None:
                bytes_value(chunk['change_context'].encode())
            strings(chunk['old_lines'])
            strings(chunk['new_lines'])
            number(len(chunk['context_line_indices']))
            for old_index, new_index in chunk['context_line_indices']:
                number(old_index)
                number(new_index)
            number(chunk['is_end_of_file'])
    with (OUT / 'cases.bin').open('xb') as stream:
        stream.write(binary)
    REPORT['cases'] = common.bind(OUT / 'cases.json')
    REPORT['wire_input'] = common.bind(OUT / 'cases.bin')
    assert len(cases) == 3974
    assert REPORT['cases']['sha256'] == 'ab79f18355c834bc66a92d16137f196b5fe717a73fdcf51afae4a2bf0caad796'
    assert REPORT['wire_input']['sha256'] == '3e5f796ff9662fcc8159b18a9aeda6d339c8d9a041ff850097c145c4446e413f'
    REPORT['case_count'] = len(cases)
    REPORT['route_counts'] = dict(Counter(str(x['route']) for x in cases))
    REPORT['fixture_transform'] = 'Inputs become full-file UpdateFileChunk requests. Expected contents/diff/errors/panics come exclusively from the complete original public crate; public LF normalization is not bypassed.'
    return cases
