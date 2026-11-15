"""Deterministic valid, malformed, priority and large-frame boundary matrix."""
import itertools
import random
import struct
from .raw_reference import final_frame, key_frame, reference


def exercise(check):
    names = [b'', b'a', b'b', b'\0', 'é'.encode(), '中'.encode(), '😀'.encode()]
    for count in range(5):
        for keys in itertools.product(names[:4], repeat=count):
            for capacity in (0, 79, 80, 97):
                check(key_frame(keys), 0, capacity, 'key_exhaustive')
    rng = random.Random(0x19A201)
    for _ in range(2500):
        variables = [(rng.choice(names), rng.choice([b'', b'v', b'{{x}}', b'\0', '值é😀'.encode()])) for _ in range(rng.randrange(7))]
        placeholders = sorted(rng.sample(names, rng.randrange(len(names) + 1)))
        segments = [(rng.choice((1, 3)), rng.choice(names + [b' literal ', b'{{raw}}'])) for _ in range(rng.randrange(9))]
        source = final_frame(variables, placeholders, segments)
        status, query = reference(source, struct.pack('<4Q', 1, 1, 0, 0), 80)
        assert status == 0
        required = struct.unpack_from('<Q', query, 24)[0]
        for operation, capacity in ((1, 79), (1, 80), (1, 97), (2, required - 1), (2, required), (2, required + 17)):
            check(source, operation, capacity, 'final_selection_and_payload')
    private = [
        final_frame([], [], []), final_frame([], [], [(1, b''), (1, b'')]),
        final_frame([], [], [(3, b'')]), final_frame([(b'', b'zero')], [b''], [(3, b'')]),
        final_frame([(b'z', b'1'), (b'a', b'2')], [], [(3, b'missing')]),
        final_frame([(b'z', b'1'), (b'z', b'2')], [b'a'], []),
        final_frame([], [b'z', b'a'], []), final_frame([], [b'a', b'a'], []),
        final_frame([(b'a', b'v')], [b'a'], [(1, b''), (3, b'a'), (1, b''), (3, b'a')]),
        final_frame([(b'a', b'v')], [b'a'], [(3, b'b'), (3, b'c')]),
    ]
    for source in private:
        for operation in (1, 2):
            for capacity in (0, 79, 80, 90, 128):
                check(source, operation, capacity, 'private_dto_and_priority')
    bases = [(0, key_frame([b'a', b'b'])), (1, final_frame([(b'a', b'v')], [b'a'], [(3, b'a')]))]
    for base_operation, source in bases:
        for position in range(len(source)):
            for byte in range(256):
                changed = source[:position] + bytes([byte]) + source[position + 1:]
                check(changed, base_operation, 113, 'all_byte_position_mutations')
        for end in range(len(source)):
            check(source[:end], base_operation, 113, 'truncated_frames')
        for suffix in (b'\0', b'x', b'\xFF', b'\0' * 8):
            check(source + suffix, base_operation, 113, 'trailing_bytes')
        workspace = struct.pack('<4Q', 1, base_operation, 0, 0)
        for size in range(65):
            check(source, base_operation, 113, 'workspace_size', (workspace + b'\0' * 64)[:size])
        for position in range(32):
            for byte in (0, 1, 2, 3, 128, 255):
                check(source, base_operation, 113, 'workspace_fields', workspace[:position] + bytes([byte]) + workspace[position + 1:])
        for operation in (0, 1, 2, 3, (1 << 64) - 1):
            check(source, operation, 113, 'operation_frame_pair')
    invalid_utf8 = [b'\x80', b'\xC0\x80', b'\xC1\xBF', b'\xC2', b'\xE0\x80\x80', b'\xED\xA0\x80', b'\xF0\x80\x80\x80', b'\xF4\x90\x80\x80', b'\xF5\x80\x80\x80', b'\xFF']
    for bad in invalid_utf8:
        for source, operation in [
            (key_frame([b'a', b'a', bad]), 0),
            (final_frame([(bad, b'v')], [], []), 1),
            (final_frame([(b'a', bad), (b'a', b'x')], [], []), 2),
            (final_frame([], [bad], []), 1),
            (final_frame([], [], [(1, bad)]), 2),
            (final_frame([], [], [(3, bad)]), 1)]:
            for capacity in (0, 80, 113):
                check(source, operation, capacity, 'utf8_before_semantics_and_capacity')
    huge = b'x' * (1024 * 1024 + 513)
    large_cases = [
        (key_frame([huge, huge + b'y']), 0),
        (final_frame([(b'a', huge)], [b'a'], [(3, b'a')]), 2),
        (final_frame([], [], [(1, huge), (1, huge)]), 2),
        (final_frame([(b'a', huge), (b'a', b'next')], [b'z'], []), 2),
    ]
    for source, operation in large_cases:
        _, query = reference(source, struct.pack('<4Q', 1, 0 if operation == 0 else 1, 0, 0), 80)
        required = struct.unpack_from('<Q', query, 24)[0]
        check(source, 0 if operation == 0 else 1, 97, 'larger_than_one_mib')
        for capacity in (required - 1, required, required + 17):
            check(source, operation, capacity, 'larger_than_one_mib')
    many = [(f'key-{i:05}'.encode(), b'v') for i in range(1025)]
    source = final_frame(many, [name for name, _ in many], [(3, name) for name, _ in reversed(many)])
    for operation, capacity in ((1, 80), (2, 1104), (2, 1105), (2, 1122)):
        check(source, operation, capacity, 'more_than_1024_items')
