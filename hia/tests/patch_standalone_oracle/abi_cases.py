"""The complete exercised raw continuation matrix; not a process oracle."""
from collections import Counter
import ctypes
import hashlib
import json
import random
import struct
import time
SHORT = 4294967294
INVALID = 4294967295
MAX = (1 << 64) - 1
FIXED = {(0, 0, 0): (1, 1, 0), (0, 1, 1): (2, 2, 0), (0, 1, 2): (3, 3, 0), (0, 2, 3): (4, 4, 0), (0, 2, 4): (10, 10, 0), (0, 3, 6): (12, 12, 0), (0, 4, 7): (5, 5, 0), (0, 4, 8): (13, 13, 0), (0, 5, 9): (6, 6, 0), (0, 5, 10): (14, 14, 0), (0, 6, 11): (7, 7, 0), (0, 6, 12): (15, 15, 0), (0, 7, 13): (8, 8, 0), (0, 8, 14): (9, 9, 0), (0, 8, 15): (16, 16, 1), (0, 9, 16): (16, 16, 0), (0, 10, 16): (16, 16, 1), (0, 11, 16): (16, 16, 2), (0, 12, 16): (16, 16, 1), (0, 13, 16): (16, 16, 2), (0, 14, 16): (16, 16, 1), (0, 15, 16): (16, 16, 1), (1, 0, 18): (16, 17, 0)}

def identity(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

def expected(frame, data, capacity, workspace_length):
    if capacity < 64 or workspace_length < 64:
        return (SHORT, None)
    if workspace_length != 64:
        return (INVALID, None)
    version, entry, phase, event, *reserved = frame
    if version != 1 or entry > 1 or phase > 16 or (event > 18) or any(reserved):
        return (INVALID, None)
    key = (entry, phase, event)
    if data and key not in ((0, 3, 5), (1, 0, 17)):
        return (INVALID, None)
    if key == (0, 3, 5):
        plan = (4, 4, 0) if data else (11, 11, 0)
    elif key == (1, 0, 17):
        plan = (16, 17, int(data == b'1'))
    else:
        plan = FIXED.get(key)
    if plan is None:
        return (INVALID, None)
    return (0, (1, entry, plan[0], plan[1], plan[2], phase, event, 0))

def frame(entry, phase, event):
    return [1, entry, phase, event, 0, 0, 0, 0]

def run_cases(entry, trace_path):
    started = time.monotonic_ns()
    counters = Counter()
    statuses = Counter()
    transitions, outcomes, actions = (set(), set(), set())
    traces = []
    report = {'passed': False}
    with trace_path.open('x') as log:

        def invoke(words, data=b'', capacity=64, workspace_length=64, label='matrix'):
            index = counters['calls']
            pattern = bytes([index * 17 + 91 & 255])
            source_bytes = b's' * 16 + data + b'S' * 16
            request = struct.pack('<8Q', *words)
            workspace_bytes = b'w' * 16 + request + b'q' * max(0, workspace_length - 64) + b'W' * 16
            output_bytes = b'o' * 16 + pattern * capacity + b'O' * 16
            source = ctypes.create_string_buffer(source_bytes, len(source_bytes))
            workspace = ctypes.create_string_buffer(workspace_bytes, len(workspace_bytes))
            output = ctypes.create_string_buffer(output_bytes, len(output_bytes))
            want, plan = expected(words, data, capacity, workspace_length)
            actual = entry(ctypes.addressof(source) + 16, len(data), ctypes.addressof(output) + 16, capacity, ctypes.addressof(workspace) + 16, workspace_length)
            after = bytes(output)
            assert bytes(source) == source_bytes, (label, 'source changed')
            assert bytes(workspace) == workspace_bytes, (label, 'workspace changed')
            assert actual == want, (label, words, data[:32], capacity, workspace_length, actual, want)
            if actual:
                assert after == output_bytes, (label, 'error partially wrote output')
                counters['error_no_write_calls'] += 1
            else:
                assert after[:16] == output_bytes[:16] and after[80:] == output_bytes[80:]
                actual_plan = struct.unpack('<8Q', after[16:80])
                assert actual_plan == plan, (label, words, actual_plan, plan)
                transitions.add(tuple(words[1:4]))
                outcomes.add((tuple(words[1:4]), plan[2:5]))
                actions.add(plan[3])
                counters['success_calls'] += 1
            counters['calls'] += 1
            counters[label] += 1
            statuses[str(actual)] += 1
            log.write(json.dumps({'index': index, 'label': label, 'request': words, 'source_bytes': len(data), 'source_sha256': hashlib.sha256(data).hexdigest(), 'capacity': capacity, 'workspace_length': workspace_length, 'status': actual, 'response': plan, 'buffers_unchanged_on_error': bool(actual)}) + '\n')
            return plan
        try:
            for kind in (0, 1, 2, MAX):
                for phase in (*range(18), MAX):
                    for event in (*range(20), MAX):
                        for data in (b'', b'1', b'\xff'):
                            invoke(frame(kind, phase, event), data)
            for byte in range(256):
                invoke(frame(1, 0, 17), bytes([byte]), label='all_single_bytes')
            for data in (b'', b'0', b'01', b'1\x00', b' 1', b'1\n', b'1\r', b'true', '１'.encode(), '1\u200b'.encode(), b'\xc3', b'\xc3\xa9', b'\xf0\x9f\x99\x82', b'x' * (2 * 1024 * 1024 + 7)):
                invoke(frame(1, 0, 17), data, label='environment_edges')
                invoke(frame(0, 3, 5), data, label='stdin_length_edges')
            for position in range(8):
                for value in (1, 2, 17, 19, 1 << 63, MAX):
                    words = frame(0, 0, 0)
                    words[position] = value
                    invoke(words, label='frame_mutation')
            for length in range(64):
                for words in (frame(0, 0, 0), [MAX] * 8):
                    invoke(words, b'1', 64, length, 'short_workspace')
                    invoke(words, b'1', length, 64, 'short_output')
            for length in (65, 80, 256, 1024 * 1024 + 1):
                for capacity in (0, 63, 64, 80):
                    invoke(frame(0, 0, 0), b'', capacity, length, 'workspace_exact_size')
            for capacity in (64, 65, 80, 255, 2 * 1024 * 1024 + 7):
                invoke(frame(0, 0, 0), capacity=capacity, label='output_tail')
                invoke(frame(0, 16, 16), capacity=capacity, label='output_tail')
            null_result = entry(None, 0, None, 0, None, 0)
            assert null_result == SHORT
            counters['calls'] += 1
            counters['error_no_write_calls'] += 1
            counters['null_empty_short'] += 1
            statuses[str(null_result)] += 1
            log.write(json.dumps({'label': 'null_empty_short', 'status': null_result}) + '\n')
            prefixes = [[(0, b''), (1, b''), (3, b'')], [(0, b''), (2, b''), (5, b'patch')]]
            suffixes = [[(8, b''), (16, b'')], [(7, b''), (10, b''), (16, b'')], [(7, b''), (9, b''), (12, b''), (16, b'')], [(7, b''), (9, b''), (11, b''), (13, b''), (15, b'')], [(7, b''), (9, b''), (11, b''), (13, b''), (14, b''), (16, b'')]]
            sequences = [prefix + suffix for prefix in prefixes for suffix in suffixes]
            sequences.extend([[(0, b''), (1, b''), (4, b''), (16, b'')], [(0, b''), (2, b''), (5, b''), (16, b'')], [(0, b''), (2, b''), (6, b''), (16, b'')]])
            for index, sequence in enumerate(sequences):
                phase, trace = (0, [])
                for event, data in sequence:
                    response = invoke(frame(0, phase, event), data, label='complete_trace')
                    trace.append(response)
                    phase = response[2]
                assert phase == 16 and trace[-1][3] == 16
                invoke(frame(0, phase, 16), label='terminal_rejection')
                traces.append({'index': index, 'responses': trace, 'exit': trace[-1][4]})
            rng = random.Random(507337)
            states = [[0, 0, sequences[index % len(sequences)]] for index in range(128)]
            remaining = list(range(len(states)))
            while remaining:
                index = rng.choice(remaining)
                phase, offset, sequence = states[index]
                event, data = sequence[offset]
                response = invoke(frame(0, phase, event), data, label='interleaved_instance')
                states[index][:2] = [response[2], offset + 1]
                if offset + 1 == len(sequence):
                    assert response[2] == 16
                    remaining.remove(index)
            assert len(transitions) == 25 and len(outcomes) == 27 and (actions == set(range(1, 18)))
            report['passed'] = True
        except Exception as error:
            report['error'] = type(error).__name__ + ': ' + str(error)
        finally:
            log.flush()
            report.update(counters=dict(counters), statuses=dict(statuses), legal_transition_keys=[list(x) for x in sorted(transitions)], unique_transition_keys=len(transitions), source_condition_outcomes=len(outcomes), actions=sorted(actions), complete_callback_traces=traces, interleaved_instances=128, elapsed_ns=time.monotonic_ns() - started, call_trace=identity(trace_path))
    return report
