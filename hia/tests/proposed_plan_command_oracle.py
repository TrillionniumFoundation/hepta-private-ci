"""Apply explicit native ProposedPlan commands to unbounded test containers.

This module never classifies whitespace, markers, prefixes, lines or input text.
It checks the public wire shapes and executes only the commands returned by HIA.
"""
from proposed_plan_literal_data import ERRORS, WORD_MAX, case_data, literal_bytes, require, unpack


INITIAL = (0, 1, 0, 0, 0, 0, 0, 0)
TEXT_KINDS = {1: 'normal', 2: 'delta', 4: 'normal', 5: 'delta'}


def state_shape(state):
    require(len(state) == 8, 'state word count differs')
    active, detect, prefix, leading, trailing, pending, opened, last = state
    require(active in (0, 1) and detect in (0, 1) and opened in (0, 1)
            and last in (0, 1, 2), 'noncanonical state word')
    require((opened != 0 or last == 0)
            and (last == 0 or last == active + 1), 'public-call text state differs')
    if detect == 0:
        require((prefix, leading, trailing, pending) == (0, 0, 0, 0),
                'disabled candidate retained state')
        return
    require(0 <= prefix <= 30 and (prefix != 0 or trailing == 0),
            'candidate prefix shape differs')
    size = prefix if prefix <= 15 else prefix - 14
    require(leading <= WORD_MAX - size and trailing <= WORD_MAX - leading - size
            and leading + size + trailing == pending, 'candidate byte count differs')


def text_segment(segments, kind, data, continuation):
    require(data and continuation in (0, 1), 'invalid explicit text command')
    if continuation == 1:
        require(segments and segments[-1][0] == kind,
                'continuation lacks its matching public segment')
        segments[-1][1].extend(data)
    else:
        segments.append([kind, bytearray(data)])


def apply_commands(request, result, pending, segments):
    require(len(request) >= 88 and len(result) >= 80, 'short native wire header')
    words = unpack(request[:88])
    op, flags, size = words[:3]
    source_state = words[3:]
    state_shape(source_state)
    payload = request[88:]
    require(size == len(payload) and len(pending) == source_state[5],
            'actual pending/input extent differs from request')
    payload.decode('utf-8')
    header = unpack(result[:80])
    state, count, reserved = header[:8], header[8], header[9]
    state_shape(state)
    require(op in (0, 1, 2) and reserved == 0
            and len(result) == 80 + 32 * count, 'native count/reserved/EOF differs')
    bound = 3 * size if op == 0 else 3 if op == 1 else 0
    require(count <= bound, 'native command count exceeds contract')
    cursor = 0
    for index in range(count):
        kind, offset, length, continuation = unpack(result[80 + index * 32:112 + index * 32])
        require(kind <= 7, 'unknown native command')
        if kind in (0, 4, 5):
            require(op == 0 and offset == cursor and length > 0
                    and offset <= size and length <= size - offset,
                    'input command is not a complete ordered cover')
            end = offset + length
            require((offset == size or payload[offset] & 0xC0 != 0x80)
                    and (end == size or payload[end] & 0xC0 != 0x80),
                    'input command splits a UTF8 scalar')
            data = payload[offset:end]
            cursor = end
            if kind == 0:
                require(continuation == 0, 'Append has continuation')
                pending.extend(data)
            else:
                text_segment(segments, TEXT_KINDS[kind], data, continuation)
        elif kind in (1, 2, 3):
            require(offset == 0 and length > 0 and length == len(pending),
                    'pending command does not name the whole container')
            if kind == 3:
                require(continuation == 0, 'Drop has continuation')
            else:
                text_segment(segments, TEXT_KINDS[kind], bytes(pending), continuation)
            pending.clear()
        else:
            require((offset, length, continuation) == (0, 0, 0),
                    'barrier command carries a payload')
            segments.append(['start' if kind == 6 else 'end', bytearray()])
    require(cursor == size and len(pending) == state[5],
            'input cover or final pending-container binding differs')
    if op == 2:
        require(count == 0 and state == source_state, 'Inspect changed state or commands')
    elif op == 1:
        require(state == INITIAL, 'Finish failed to restore initial state')
    else:
        require(state[6] == (0 if flags & 2 else 1)
                and (not flags & 2 or state[7] == 0), 'public Push boundary differs')
    return state


def stream(probe, item, fill):
    state, pending, batches, order = INITIAL, bytearray(), {}, []
    calls = 0
    for position, call in enumerate(item['calls']):
        require(call['expected']['return'] not in ERRORS
                and call['logical_state_only'] is False,
                'stream includes an error or hypothetical-state fixture')
        name = call['public_call']
        for iteration in range(call['repeat']):
            raw, _ = case_data(call, iteration)
            words = unpack(raw[:88])
            op, flags = words[:2]
            require(words[3:] == state, 'literal request does not continue actual native state')
            if op == 2:
                require(name is None, 'Inspect created a public call')
                segments = []
            else:
                require(op in (0, 1) and type(name) is str and name,
                        'unknown public call')
                if name not in batches:
                    require(state[6] == 0, 'public call starts before preceding call ends')
                    require(op != 0 or flags & 1, 'public Push omitted first-frame flag')
                    order.append(name)
                    batches[name] = {'op': op, 'input': bytearray(), 'segments': []}
                else:
                    require(name == order[-1] and batches[name]['op'] == op == 0
                            and not flags & 1, 'noncontiguous or restarted public call')
                batch = batches[name]
                segments = batch['segments']
            request, result = probe.call(call, iteration, fill,
                                         f"stream/{item['id']}/{position}/{iteration}")
            require(request == raw, 'admitted literal changed before invocation')
            if op != 2:
                batch['input'].extend(raw[88:])
            state = apply_commands(raw, result, pending, segments)
            calls += 1
    require(state[6] == 0, 'stream leaves an unfinished public Push')
    expected = item['expected_public_results']
    require(order == [value['public_call'] for value in expected], 'public result order differs')
    records = []
    for value in expected:
        batch = batches[value['public_call']]
        actual = [(kind, bytes(data)) for kind, data in batch['segments']]
        wanted = [(segment['kind'], literal_bytes(segment['bytes']))
                  for segment in value['segments']]
        visible = b''.join(data for kind, data in actual if kind == 'normal')
        require(actual == wanted and visible == literal_bytes(value['visible']),
                'complete public segment or visible literal differs')
        batch['input'].decode('utf-8')
        visible.decode('utf-8')
        for _, data in actual:
            data.decode('utf-8')
        records.append({'public_call': value['public_call'],
                        'input_bytes': len(batch['input']), 'visible_bytes': len(visible),
                        'segment_kinds': [kind for kind, _ in actual],
                        'segment_bytes': [len(data) for _, data in actual]})
    require(state == tuple(int(value) for value in item['expected_final_state'])
            and bytes(pending) == literal_bytes(item['expected_pending']),
            'final state or complete pending literal differs')
    return {'id': item['id'], 'native_calls': calls, 'public_results': records,
            'final_state': list(state), 'pending_bytes': len(pending)}
