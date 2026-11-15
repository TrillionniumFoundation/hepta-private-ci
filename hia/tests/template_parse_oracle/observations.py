"""Validate the observer transport and actual ABI traces, not template syntax."""
from collections import Counter
import struct


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def word(self):
        assert self.offset + 8 <= len(self.data)
        result = struct.unpack_from('<Q', self.data, self.offset)[0]
        self.offset += 8
        return result

    def text(self):
        length = self.word()
        assert self.offset + length <= len(self.data)
        result = self.data[self.offset:self.offset+length].decode('utf-8')
        self.offset += length
        return result

    def boolean(self):
        value = self.word()
        assert value in (0, 1)
        return bool(value)

    def finish(self):
        assert self.offset == len(self.data)


def error(reader):
    debug, display = reader.text(), reader.text()
    assert reader.boolean() is True
    assert reader.text() == debug
    sources = []
    while reader.boolean():
        sources.append([reader.text(), reader.text()])
        assert len(sources) < 8
    return dict(debug=debug, display=display, sources=sources)


def rendering(reader):
    outcome = reader.word()
    if outcome == 0:
        value = reader.text()
        result = dict(kind='success', rendered_bytes=len(value.encode()))
    elif outcome == 1:
        result = dict(kind='error', error=error(reader))
    else:
        assert outcome == 2
        result = dict(kind='panic', payload_type=reader.text(), payload=reader.text())
    events = [reader.text() for _ in range(reader.word())]
    result['events'] = Counter(event.split(':', 1)[0] for event in events)
    result['event_count'] = len(events)
    return result


def public(data, fixture):
    reader = Reader(data)
    tag, length, start = reader.word(), reader.word(), reader.word()
    assert tag in range(5) and length == fixture['source_bytes']
    parsed_debug = reader.text()
    outcomes = []
    if tag == 0:
        assert start == 0 and parsed_debug.startswith('Ok(')
        assert reader.boolean() is True
        clone_debug = reader.text()
        reparse_debug = reader.text()
        assert parsed_debug == reparse_debug == 'Ok('+clone_debug+')'
        assert reader.boolean() is True
        eq_empty, ne_empty = reader.boolean(), reader.boolean()
        assert eq_empty != ne_empty
        count = reader.word()
        names = []
        remaining = count
        while True:
            assert reader.word() == remaining
            assert reader.word() == remaining
            if not reader.boolean():
                assert remaining == 0
                break
            names.append(reader.text())
            remaining -= 1
            assert reader.word() == remaining
        assert names == sorted(set(names)) and len(names) == count
        assert reader.boolean() and reader.word() == 0
        for _ in range(3):
            outcomes.append(rendering(reader))
        assert outcomes[1]['kind'] == outcomes[2]['kind'] == 'success'
    else:
        assert parsed_debug.startswith('Err(')
        direct, wrapped = error(reader), error(reader)
        assert direct['sources'] == []
        assert wrapped['sources'] == [[direct['debug'], direct['display']]]
    one_shot = rendering(reader)
    outcomes.append(one_shot)
    if tag:
        assert one_shot['events']['into_iter'] == 0
        if fixture['fault'] != 8 or not fixture['values']:
            assert one_shot['kind'] == 'error'
            assert one_shot['error']['debug'].startswith('Parse(')
    reader.finish()
    return dict(parse_tag=tag, source_bytes=length, error_start=start, outcomes=outcomes)


def constructors(data):
    reader = Reader(data)
    for _ in range(21):
        direct, wrapped = error(reader), error(reader)
        assert direct['sources'] == []
        assert wrapped['sources'] == [[direct['debug'], direct['display']]]
    assert reader.boolean() and reader.boolean()
    reader.finish()


def native(calls, observed):
    tag, length, start = (observed[k] for k in ['parse_tag', 'source_bytes', 'error_start'])
    expected = []
    for stage in ([1, 2, 4, 3] if tag == 0 else [1, 3]):
        size = 0 if stage == 4 else length
        expected.append((stage, 0, size))
        if tag == 0 and size:
            expected.append((stage, 1, size))
    assert len(calls) == len(expected)
    query = None
    counts = Counter()
    for row, (stage, operation, size) in zip(calls, expected):
        assert len(row) == 17
        actual_stage, source_len, capacity, workspace_len, status = row[:5]
        assert (actual_stage, source_len, workspace_len, status) == (stage, size, 32, 0)
        assert list(row[5:9]) == [1, operation, 0, 0]
        revision, op, source, count, needed, written, failure, offset = row[9:]
        assert (revision, op, source) == (1, operation, size)
        assert needed == 64 + 24*count
        assert written == capacity == (64 if operation == 0 else needed)
        assert failure == (0 if stage == 4 else tag)
        assert offset == (0 if stage == 4 else start)
        if failure:
            assert count == 0 and needed == 64
        elif size == 0:
            assert count == 0
        else:
            assert count > 0
        plan = (source, count, needed, failure, offset)
        if operation == 0:
            query = plan
        else:
            assert plan == query
        counts['query' if operation == 0 else 'emit'] += 1
    return counts
