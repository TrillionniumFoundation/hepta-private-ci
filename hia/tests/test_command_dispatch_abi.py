#!/usr/bin/env python3
"""Execute real continuation HIA with an independent wire/state oracle.

This gate validates buffers and protocol transitions. The public gate compares
the complete original Rust dispatcher and its real callback/path effects.
"""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import ctypes
import hashlib
import itertools
import json
from pathlib import Path
import random
import struct
import subprocess
import sys
import threading


INVALID, SHORT = 0xFFFFFFFF, 0xFFFFFFFE
MAX, MAGIC = (1 << 64) - 1, 0x48494144
GUARD = bytes(range(1, 34))


def words(*values):
    return struct.pack('<' + 'Q' * len(values), *values)


def packet(state, event, payload):
    return words(1, event) + state + payload


def components(records):
    return b''.join(words(kind, len(value)) + value for kind, value in records)


def expected(source, output_size):
    """No native results, Rust adapter state, or generated HIA are used here."""
    def reject(condition):
        if not condition:
            raise ValueError('malformed continuation frame')

    def word(at):
        reject(0 <= at <= len(source) - 8)
        return struct.unpack_from('<Q', source, at)[0]

    def stream(at, count):
        reject(at <= len(source) and count <= (len(source) - at) // 16)
        records = []
        for _ in range(count):
            kind, length = word(at), word(at + 8)
            at += 16
            reject(kind in (1, 2, 3, 4) and length <= len(source) - at)
            reject((kind == 4 and length != 0) or (kind != 4 and length == 0))
            records.append((kind, source[at:at + length]))
            at += length
        return at, records

    try:
        reject(len(source) >= 176 and word(0) == 1 and word(8) <= 8)
        event = word(8)
        s = [word(16 + index * 8) for index in range(20)]
        phase, flags, commands, count, index, matched, paths, path_index, resources, sequence = s[1:11]
        if event == 0:
            reject(s == [0] * 20 and len(source) == 200)
            reject(word(184) <= 1 and word(192) <= 1)
        else:
            reject(s[0] == MAGIC and 1 <= phase <= 9 and flags <= 3)
            reject(matched <= index <= count and path_index <= paths and 0 < sequence < MAX)
            reject(s[11:] == [0] * 9 and (phase == 9 or commands > 0))
            reject(resources == (5 if phase == 8 else 6 if phase in (4, 5, 6, 7) else 0))
            reject(phase not in (2, 8) or index < count)
            reject(phase != 6 or path_index < paths)
            reject(phase not in (3, 4, 5, 6, 7, 8) or flags % 2 == 1)
            reject(phase != 9 or flags >= 2)
            reject(phase not in (3, 4) or index == count)
            reject(phase not in (3, 4, 5, 6, 7, 9) or matched == 0)
            reject(phase not in (5, 6, 7) or index == matched == 0)
            reject(phase != 1 or (count == index == matched == paths == path_index == 0 and sequence == 1))
            reject(event == (2 if phase == 8 else 8 if phase == 9 else phase))
            if event in (1, 4, 5):
                reject(len(source) == 192 and word(176) <= 1)
                reject(word(176) == 1 or word(184) == 0)
            elif event == 2:
                reject(len(source) == 200 and word(176) == index)
                reject(word(184) == (0 if phase == 2 else 1) and word(192) <= 2)
            elif event == 3:
                reject(len(source) == 184 and word(176) <= 1)
            elif event == 6:
                reject(len(source) >= 200 and word(176) == path_index)
                end, program = stream(200, word(184))
                end, candidate = stream(end, word(192))
                reject(end == len(source))
            elif event == 7:
                reject(len(source) == 184 and word(176) == commands)
            elif event == 8:
                reject(len(source) == 184 and word(176) <= 2)
        if output_size < 200:
            return SHORT, None
        s[10] += 1
        append = cleanup = operand = 0

        def finish():
            return 9 if s[2] >= 2 else 0

        def post_exact():
            return 3 if s[2] % 2 and s[3] else finish()

        def release():
            nonlocal cleanup
            cleanup, s[9] = s[9], 0

        if event == 0:
            s[0], s[2], s[3] = MAGIC, word(184) + 2 * word(192), word(176)
            action = 1 if s[3] else finish()
        elif event == 1:
            s[4:7] = [word(184), 0, 0]
            action = 2 if s[4] else post_exact()
        elif event == 2:
            kind = word(192)
            append = 0 if kind == 0 else 2 if phase == 8 and kind == 1 else 1
            s[5] += 1
            s[6] += kind != 0
            if s[5] < s[4]:
                action, operand = phase, s[5]
            else:
                if phase == 8:
                    release()
                action = 0 if s[6] else finish() if phase == 8 else post_exact()
        elif event == 3:
            if word(176):
                s[9], action = 6, 4
            else:
                action = finish()
        elif event == 4:
            if word(176):
                s[4:7], action = [word(184), 0, 0], 5
            else:
                release()
                action = finish()
        elif event == 5:
            s[7:9] = [word(184), 0]
            if word(176) == 0:
                action = 7
            elif s[7]:
                action = 6
            else:
                release()
                action = finish()
        elif event == 6:
            s[8] += 1
            if program == candidate:
                action = 7
            elif s[8] < s[7]:
                action, operand = 6, s[8]
            else:
                release()
                action = finish()
        elif event == 7:
            s[9] = 5
            if s[4]:
                action = 8
            else:
                release()
                action = finish()
        else:
            append, action = 1, 0
        s[1] = action if action else 10
        return 0, words(*s, append, cleanup, action, operand, 0)
    except (ValueError, struct.error):
        return INVALID, None


class Native:
    def __init__(self, library):
        self.library = ctypes.CDLL(str(library))
        self.entry = self.library.f0
        self.entry.argtypes = [ctypes.c_void_p, ctypes.c_uint64] * 3
        self.entry.restype = ctypes.c_uint64
        self.counts = Counter()
        self.lock = threading.Lock()

    def call(self, source, category='valid', output_size=219, workspace_size=31, offset=1):
        status, result = expected(source, output_size)
        prefix = GUARD[:offset]
        buffers = [bytearray(prefix + source + GUARD),
                   bytearray(prefix + b'\xa5' * output_size + GUARD),
                   bytearray(prefix + b'\x5a' * workspace_size + GUARD)]
        before = tuple(map(bytes, buffers))
        arrays = [(ctypes.c_ubyte * len(data)).from_buffer(data) for data in buffers]
        pointers = [ctypes.addressof(array) + offset for array in arrays]
        for index, size in enumerate((len(source), output_size, workspace_size)):
            if size == 0:
                pointers[index] = None
        actual = self.entry(pointers[0], len(source), pointers[1], output_size, pointers[2], workspace_size)
        label = f'{category} bytes={len(source)} sha={hashlib.sha256(source).hexdigest()}'
        assert actual == status, f'{label}: status {actual:#x} != {status:#x}'
        for index in range(3):
            wanted = before[index]
            if index == 1 and result is not None:
                wanted = wanted[:offset] + result + wanted[offset + len(result):]
            assert bytes(buffers[index]) == wanted, f'{label}: buffer {index} changed incorrectly'
        with self.lock:
            self.counts['native_calls'] += 1
            self.counts[category] += 1
            self.counts['success' if status == 0 else 'error_no_write'] += 1
        return result


def verify(library):
    native = Native(library)
    frames = []
    sampled_phases = set()
    sample_program = [(1, b''), (4, b'opt'), (4, b'tool')]

    def session(commands, resolve, fallback, exact, host, allowlist, usable=True, category='sequential_session_steps'):
        source = packet(bytes(160), 0, words(commands, resolve, fallback))
        while True:
            result = native.call(source, category)
            assert result is not None
            phase = struct.unpack_from('<Q', source, 24)[0]
            if phase not in sampled_phases:
                frames.append(source)
                sampled_phases.add(phase)
            action, index = struct.unpack_from('<QQ', result, 176)
            state = result[:160]
            if action == 0:
                with native.lock:
                    native.counts['completed_sessions'] += 1
                return
            if action == 1:
                tag, payload = 1, words(exact is not None, len(exact or []))
            elif action in (2, 8):
                tag, payload = 2, words(index, action == 8, (exact if action == 2 else host)[index])
            elif action == 3:
                tag, payload = 3, words(usable)
            elif action == 4:
                tag, payload = 4, words(host is not None, len(host or []))
            elif action == 5:
                tag, payload = 5, words(allowlist is not None, len(allowlist or []))
            elif action == 6:
                path = allowlist[index]
                tag, payload = 6, words(index, len(sample_program), len(path)) + components(sample_program) + components(path)
            elif action == 7:
                tag, payload = 7, words(commands)
            else:
                tag, payload = 8, words((commands + len(exact or [])) % 3)
            source = packet(state, tag, payload)

    rules = [None, [], *[list(tags) for size in range(1, 4) for tags in itertools.product(range(3), repeat=size)]]
    paths = [None, [], [sample_program], [[(4, b'different')]], [[(4, b'x')], sample_program, [(4, b'untouched')]]]
    for exact in rules:
        for host in rules[:15]:
            for command_count, resolve, fallback in itertools.product((0, 1, 3), range(2), range(2)):
                for allowed in paths:
                    session(command_count, resolve, fallback, exact, host, allowed)
    session(2, 1, 1, [0], [1], None, usable=False, category='unusable_path')
    assert sampled_phases == set(range(10)), sampled_phases
    # All active phases including boundary counters, and valid non-UTF8 components.
    states = {}
    for source in frames:
        phase = struct.unpack_from('<Q', source, 24)[0]
        states.setdefault(phase, source)
    for source in list(states.values()):
        for end in range(len(source)):
            native.call(source[:end], 'truncation')
        for suffix in (b'\0', words(0), words(MAX)):
            native.call(source + suffix, 'trailing')
        for at in range(0, len(source) - 7, 8):
            for value in (0, 1, 2, 9, 10, 1 << 32, 1 << 63, MAX):
                native.call(source[:at] + words(value) + source[at + 8:], 'word_mutation')
        for capacity in (0, 1, 8, 159, 160, 199, 200, 201):
            native.call(source, 'capacity_precedence', output_size=capacity, workspace_size=0)
            native.call(source + b'\0', 'capacity_precedence', output_size=capacity, workspace_size=0)
        for offset in (1, 7, 16, 33):
            native.call(source, 'unaligned', offset=offset)
    # Construct a reachable path-comparison state independently of session sampling.
    s = [MAGIC, 6, 3, 1, 0, 0, 0, 2, 0, 6, 7] + [0] * 9
    for left, right in itertools.product([[], [(1, b'')], [(2, b'')], [(3, b'')],
                                         [(4, b'\xff\0')], [(4, 'é'.encode())], [(4, b'a' * 9)]], repeat=2):
        source = packet(words(*s), 6, words(0, len(left), len(right)) + components(left) + components(right))
        native.call(source, 'components')
        for end in range(176, len(source)):
            native.call(source[:end], 'component_truncation')
        native.call(source + words(4, MAX), 'invalid_tail_after_mismatch')
    for byte_count in (7, 8, 9, 511, 512, 513, 1 << 20):
        for ending in (b'a', b'b'):
            left, right = [(4, b'a' * byte_count)], [(4, b'a' * (byte_count - 1) + ending)]
            native.call(packet(words(*s), 6, words(0, 1, 1) + components(left) + components(right)), 'large_components')
    rng = random.Random(0x48494144)
    for _ in range(512):
        s = [MAGIC, 2, rng.randrange(4), MAX, MAX, MAX - 1, rng.randrange(2), 0, 0, 0, MAX - 1] + [0] * 9
        native.call(packet(words(*s), 2, words(MAX - 1, 0, rng.randrange(3))), 'full_width_counters')
    barrier = threading.Barrier(8)

    def worker(index):
        barrier.wait(timeout=10)
        for iteration in range(32):
            session(2, 1, 1, [0, 0], [index % 3, iteration % 3], paths[(index + iteration) % len(paths)], category='concurrent')

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(worker, range(8)))
    root = Path(__file__).resolve().parents[2]
    inputs = [library, library.with_name('libcodex_hia_command_dispatch.a'), library.with_name('build.json'),
              root / 'hia/command_dispatch.hepta', Path(__file__)]
    return {'passed': True, **native.counts, 'skipped': 0, 'concurrent_sessions': 256,
            'input_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
            'error_contract': 'complete frame/state validation before output capacity; errors write no bytes',
            'buffer_contract': 'disjoint buffers; source/workspace unchanged; successful output prefix exactly 200 bytes',
            'whole_policy_qualification': False, 'performance_qualification': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.report = args.report.resolve()
    root = Path(__file__).resolve().parents[2]
    if args.report == root or root in args.report.parents:
        parser.error('reports must be outside the source checkout')
    report = {'schema': 'codex.hia.command-dispatch-abi.v1', 'passed': False}
    if args.worker:
        try:
            report.update(verify(args.library.resolve(strict=True)))
        except BaseException as error:
            report['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            args.report.write_text(json.dumps(report, indent=2) + '\n')
        return
    if args.report.exists():
        parser.error('retain existing evidence; select a new report path')
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker',
               '--library', str(args.library.resolve()), '--report', str(args.report)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=300)
        report = json.loads(args.report.read_text())
        report['process'] = {'command': command, 'returncode': result.returncode,
                             'stdout': result.stdout, 'stderr': result.stderr}
        if result.returncode or report.get('passed') is not True:
            report['passed'] = False
            report.setdefault('error', 'native ABI worker did not complete')
    except subprocess.TimeoutExpired as error:
        report.update(error='native ABI worker exceeded 300 seconds', passed=False)
        report['process'] = {'command': command, 'stdout': (error.stdout or b'').decode(errors='replace'),
                             'stderr': (error.stderr or b'').decode(errors='replace')}
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'report': str(args.report)}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
