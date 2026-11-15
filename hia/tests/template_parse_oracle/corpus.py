"""Deterministic full-public inputs; the complete original determines outcomes."""
from collections import Counter
import gzip
import hashlib
import itertools
import json
import struct
from .common import binding, require, save
from .original import catalog

PROFILES = [[], [('a', 'A')], [('b', 'B'), ('a', 'A')],
            [('b', 'first'), ('b', 'second'), ('a', 'A')],
            [('z', 'unused'), ('a', 'one'), ('a', 'two')],
            [('', '\0'), ('名前', '漢🚀'), ('a', '{{literal}}\n')]]
SPACE = [9, 10, 11, 12, 13, 32, 0x85, 0xa0, 0x1680,
         *range(0x2000, 0x200b), 0x2028, 0x2029, 0x202f, 0x205f, 0x3000]


def cases():
    for length in range(13):
        for index, braces in enumerate(itertools.product('{}', repeat=length)):
            yield f'braces-{length}-{index}', 'braces-exhaustive', ''.join(braces), PROFILES[index % 6], 0
    atoms = ['a', 'b', '{', '}', '{{', '}}', '{{{{', '}}}}', '{{a}}', '{{ b }}',
             '\0', '\r\n', '\t', '漢', '🚀', 'é', 'e\u0301', '\u2003', '{{}}',
             '{{a{{b}}', '{{\0}}', '{{ a }', '}}x', '{{名前}}', '{{ a b }}']
    state = 0xd51b6a71c08f239e
    def next_u64():
        nonlocal state
        state ^= state >> 12
        state ^= (state << 25) & ((1 << 64)-1)
        state ^= state >> 27
        return (state * 2685821657736338717) & ((1 << 64)-1)
    for index in range(3000):
        value = ''.join(atoms[next_u64() % len(atoms)] for _ in range(next_u64() % 24))
        yield f'composite-{index}', 'deterministic-compositions', value, PROFILES[next_u64() % 6], 0
    directed = ['', 'plain', '{}', '{a}', '{{a}}', '{{b}}{{a}}{{b}}',
        '{{ z }}{{ a }}', '{{ }}', '{{a', '}}', '{{a{{b}}', '{{{{', '}}}}',
        '{{{{a}}}}', '{{{{{{a}}}}}}', '{{a}}{{}}', '{{}}{{a', '}}{{a{{b}}',
        '{{ a b }}', '{{a\nb}}', '{{\0}}', '\0{{a}}\0', '{{名前}}',
        '{{ b }} / {{ a }}', '{{a}}{', 'é{{a}}🚀{{ b }}', '{{a}}}}',
        '{{{{}}}}', '{{a}{b}}', '{{a}}}}}}', '{{ a }}{{ a }}', '{{\u200ba}}']
    for index, source in enumerate(directed):
        for profile, values in enumerate(PROFILES):
            for fault in range(9):
                yield f'lifecycle-{index}-{profile}-{fault}', 'lifecycle-and-precedence', source, values, fault
    for codepoint in SPACE:
        space = chr(codepoint)
        for index, source in enumerate(['{{'+space+'a'+space+'}}', '{{'+space+'}}',
            '漢{{'+space+'名前'+space+'}}', '{{a'+space+'b}}', '{{'+space+'{{x}}']):
            yield f'space-{codepoint:x}-{index}', 'unicode-whitespace', source, PROFILES[index % 6], 0
    for codepoint in [0, 0x7f, 0x84, 0x86, 0x180e, 0x200b, 0x200c, 0x200d,
                       0x2027, 0x202a, 0x2060, 0xfeff, 0xfffd, 0x10000, 0x10ffff]:
        value = chr(codepoint)
        for index, source in enumerate([value+'{{a}}', '{{'+value+'}}', '{{'+value+'a'+value+'}}']):
            yield f'unicode-{codepoint:x}-{index}', 'unicode-nonwhitespace', source, [('a', 'A')], 0
    for length in [0, 1, 2, 3, 7, 8, 15, 16, 23, 24, 31, 32, 63, 64, 127, 128]:
        for index, tail in enumerate(['{{a}}', '{{{{', '}}}}', '{{', '}}', '{{a{{b}}', '{{\0}}']):
            yield f'boundary-{length}-{index}', 'byte-boundaries', 'x'*length+tail, [('a', 'A')], 0
    large = [('literal-ascii', 'A' * (1024*1024+37)),
        ('literal-unicode', '漢字🚀' * 104861 + '{{a}}'),
        ('unterminated-offset', 'x' * (1024*1024+17) + '{{'),
        ('coalesced-escapes', '{{{{}}}}' * 131077),
        ('many-segments', 'é{{a}}' * 150007)]
    for name, source in large:
        yield f'large-{name}', 'larger-than-one-mib', source, [('a', 'A')], 0


def emit(output, index):
    """Write exactly the frozen wire/index; usable with comparison-only streams."""
    info = list(cases())
    categories, faults = Counter(), Counter()
    maximum = 0
    output.write(b'TPC1'+struct.pack('<Q', len(info)))
    def text(value):
        data = value.encode()
        output.write(struct.pack('<Q', len(data))+data)
        return data
    for number, (label, category, source, values, fault) in enumerate(info):
        output.write(struct.pack('<Q', number))
        data = text(source)
        output.write(struct.pack('<QQ', fault, len(values)))
        for key, value in values:
            text(key); text(value)
        record = dict(id=number, label=label, category=category, source_bytes=len(data),
                      source_sha256=hashlib.sha256(data).hexdigest(), values=values, fault=fault)
        index.write((json.dumps(record, ensure_ascii=True)+'\n').encode())
        categories[category] += 1
        faults[str(fault)] += 1
        maximum = max(maximum, len(data))
    require(len(info) == 13206 and categories['braces-exhaustive'] == 8191
            and categories['deterministic-compositions'] == 3000
            and categories['lifecycle-and-precedence'] == 1728 and len(SPACE) == 25,
            'the full frozen corpus scope changed')
    return dict(cases=len(info), categories=dict(categories), faults=dict(faults),
                maximum_source_bytes=maximum)


def generate(destination, resources):
    resources.check('write complete public corpus', 8*1024*1024)
    destination.mkdir()
    wire, compressed_index = destination/'cases.bin', destination/'case-index.jsonl.gz'
    with wire.open('xb') as output, compressed_index.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as index:
            counts = emit(output, index)
    wanted = catalog()['corpus_wire']
    observed = binding(wire)
    require(observed['bytes'] == wanted['bytes'] and observed['sha256'] == wanted['sha256']
            and counts['cases'] == wanted['cases'], 'full binary corpus differs from the frozen actual input')
    report = dict(schema='codex.hia.template-public-corpus.v2', **counts,
        full_inputs=observed, index=binding(compressed_index), constructor_values=21,
        grammar_expected_values='Only the complete unchanged original crate supplies outcomes.',
        resources=resources.check('complete corpus written'))
    save(destination/'report.json', report)
    return report
