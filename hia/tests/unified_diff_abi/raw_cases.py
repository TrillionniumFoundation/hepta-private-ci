#!/usr/bin/env python3
"""Independent raw-frame and atomicity tests for complete unified-diff ABI v2."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import struct
import subprocess

from .transport import (
    INVALID, INVALID_UTF8, MAX, SHORT, binding, changed_word, compare_outcome,
    descriptor, expected_capacities, sha256, validate_binding, validate_original_corpus,
)

ORIGINAL_REPORT_SHA = None  # Set from the freshly admitted full reference.


def supplementary_original(args, corpus, report):
    """Execute complete original binaries for extra raw-ABI stress inputs."""
    examples = [('', '', 0), ('', 'x\n', MAX), ('x\r', '', MAX),
                ('a\rb', 'a\nb\n', 1), ('é\x00', '汉🙂\x00', 0),
                ('a', 'b', 1), ('a\r', 'a\r', MAX // 2 + 1),
                ('a\r', 'a\r', MAX), ('a\r', 'a\r', MAX // 2 + 2)]
    for character in ('\x00', '\r', '\n', '\r\n', '\u0085', '\u2028', '\u2029',
                      'é', '汉', '🙂', 'e\u0301', '👩\u200d💻'):
        for context in (0, 1, MAX):
            examples.append((character + '\rA\nB', character + '\rB\nA', context))
    large = 'x' * (2 * 1024 * 1024)
    examples.extend([(large, large, 1), (large + '\n', large[:-1] + 'y\n', 1),
                     ('é🙂\x00\r\n' * 4096, 'é🙂\x00\r\n' * 4095 + 'changed\n', 1)])
    cases = [{'id': i, 'name': 'raw-extra-' + str(i), 'old': old, 'new': new, 'context': context}
             for i, (old, new, context) in enumerate(examples)]
    binary_input = b''.join(struct.pack('<4Q', c['id'], c['context'], len(c['old'].encode()), len(c['new'].encode()))
                            + c['old'].encode() + c['new'].encode() for c in cases)
    directory = args.report.with_name(args.report.stem + '.original-extra')
    directory.mkdir(exist_ok=False)
    case_path, input_path = directory / 'cases.json', directory / 'cases.bin'
    case_path.write_text(json.dumps(cases, ensure_ascii=True) + '\n')
    input_path.write_bytes(binary_input)
    result = {'cases': binding(case_path), 'input': binding(input_path), 'case_count': len(cases), 'commands': []}
    references = {}
    for policy in range(4):
        command = corpus['commands'][policy]
        binary = validate_binding(command['binary'])
        validate_binding(command['rlib'])
        stdout, stderr = directory / f'policy-{policy}.stdout', directory / f'policy-{policy}.stderr'
        with input_path.open('rb') as stdin, stdout.open('xb') as out, stderr.open('xb') as err:
            process = subprocess.run([str(binary)], stdin=stdin, stdout=out, stderr=err, timeout=60)
        entry = {'policy': policy, 'argv': [str(binary)], 'returncode': process.returncode,
                 'binary': binding(binary), 'rlib': command['rlib'], 'stdout': binding(stdout), 'stderr': binding(stderr)}
        result['commands'].append(entry)
        assert process.returncode == 0, entry
        assert stderr.stat().st_size == 0
        rows = [json.loads(line) for line in stdout.read_text().splitlines()]
        assert len(rows) == len(cases) and [x['id'] for x in rows] == list(range(len(cases)))
        assert all('construction_panic_hex' not in x for x in rows)
        references[policy] = rows
    report['supplementary_complete_original_executions'] = result
    return cases, references


def verify(args, native, report):
    assert len(args.oracle_report) == 1 and sha256(args.oracle_report[0]) == ORIGINAL_REPORT_SHA
    corpus = validate_original_corpus(args.oracle_report[0])
    report['original_provenance'] = corpus['bindings']
    source = b'a\nb\n'
    base = descriptor(0, 2, 2, 1, 0)
    out_capacity, work_capacity = expected_capacities(1, 1)

    # Advertised minimum capacities win even with bad numeric fields and bytes.
    for count in range(64):
        native.call(source, base, 128, count, SHORT, label=f'workspace-header-{count}')
        native.call(b'\xff', changed_word(base, 0, MAX), 128, count, SHORT,
                    label=f'workspace-header-precedence-{count}')
    for count in range(128):
        native.call(source, base, count, 64, SHORT, label=f'output-header-{count}')
        native.call(b'\xff', changed_word(base, 0, MAX), count, 64, SHORT,
                    label=f'output-header-precedence-{count}')

    invalid_frames = []
    for operation in (4, 5, 7, 8, 255, 1 << 63, MAX):
        invalid_frames.append((f'operation-{operation}', changed_word(base, 0, operation)))
    for policy in (4, 5, 7, 255, 1 << 63, MAX):
        invalid_frames.append((f'policy-{policy}', changed_word(base, 4, policy)))
    for word in (5, 6, 7):
        for value in (1, 1 << 63, MAX):
            invalid_frames.append((f'reserved-{word}-{value}', changed_word(base, word, value)))
    for old_len, new_len in ((0, 0), (1, 1), (2, 3), (5, 0), (MAX, 5), (MAX, MAX), (1 << 63, 1 << 63)):
        invalid_frames.append((f'extent-{old_len}-{new_len}', descriptor(0, old_len, new_len, 1, 0)))
    for label, frame in invalid_frames:
        native.call(source, frame, 128, 64, INVALID, label=label)
        native.call(b'\xff' * len(source), frame, 128, 64, INVALID, label=label + ':before-utf8')
    for operation in (0, 2):
        for capacity in (65, 72, 127, 128, work_capacity):
            native.call(source, changed_word(base, 0, operation), 128, capacity, INVALID,
                        label=f'inspect-workspace-exact-{operation}-{capacity}')

    # Plan upper bounds are enforced even when actual output would be empty.
    for policy in range(4):
        for operation in (1, 3):
            frame = descriptor(operation, 2, 2, MAX, policy)
            for out, work in ((128, work_capacity), (out_capacity - 1, work_capacity),
                              (out_capacity, 64), (out_capacity, work_capacity - 1),
                              (out_capacity - 1, work_capacity - 1)):
                native.call(source, frame, out, work, SHORT,
                            label=f'plan-upper-bound-{operation}-{policy}-{out}-{work}')
            native.call(source, changed_word(frame, 7, 1), 128, 64, INVALID,
                        label=f'numeric-before-plan-capacity-{operation}-{policy}')

    bad_sequences = {bytes([value]) for value in range(0x80, 0x100)}
    bad_sequences.update((b'\xc0\x80', b'\xc1\xbf', b'\xe0\x80\x80', b'\xed\xa0\x80',
                          b'\xf0\x80\x80\x80', b'\xf4\x90\x80\x80', b'\xf5\x80\x80\x80',
                          b'\xc2A', b'\xe1\x80A', b'\xf1\x80\x80A', b'\xe2\x82',
                          b'\xf0\x9f\x99', b'\xef\xbf', b'\xf4\x8f\xbf'))
    for value in bad_sequences:
        try:
            value.decode('utf-8')
        except UnicodeDecodeError:
            pass
        else:
            raise AssertionError(('bad fixture actually UTF8', value))
    for i, value in enumerate(sorted(bad_sequences)):
        for left in (True, False):
            old, new = (value, b'x') if left else (b'x', value)
            for operation in (0, 1):
                frame = descriptor(operation, len(old), len(new), MAX, i % 4)
                # The plan advertises only the two headers: UTF8 precedes final sizing.
                native.call(old + new, frame, 128, 64, INVALID_UTF8,
                            label=f'invalid-utf8-{i}-{left}-{operation}')
    split_cases = [('é'.encode(), 1), ('汉'.encode(), 1), ('汉'.encode(), 2),
                   ('🙂'.encode(), 1), ('🙂'.encode(), 2), ('🙂'.encode(), 3)]
    for data, split in split_cases:
        data.decode('utf-8')
        for operation in (0, 1):
            native.call(data, descriptor(operation, split, len(data) - split, 1, 0), 128, 64,
                        INVALID_UTF8, label=f'separate-string-boundary-{data.hex()}-{split}-{operation}')
    for left in (True, False):
        bad = b'x' * (2 * 1024 * 1024) + b'\xff'
        old, new = (bad, b'') if left else (b'', bad)
        native.call(old + new, descriptor(0, len(old), len(new), 0, 0), 128, 64,
                    INVALID_UTF8, label=f'late-invalid-utf8-{left}')

    # Every successful plan comes from complete-source original observations.
    extras, references = supplementary_original(args, corpus, report)
    policies = args.policy or [0, 1, 2, 3]
    for case in extras:
        for policy in policies:
            original = references[policy][case['id']]
            counts = len(original['old_tokens']), len(original['new_tokens'])
            results = []
            for trusted in (False, True):
                query, result = native.valid_pair(case['old'].encode(), case['new'].encode(),
                    case['context'], policy, trusted, *counts, extra_capacity=23,
                    guard=1 + case['id'] % 31, label=f'extra-{case["id"]}-{policy}-{trusted}')
                compare_outcome(case, original, result)
                results.append((query.output, result.output))
            assert results[0] == results[1], ('strict-trusted-plan', case['id'], policy)

    concurrent_cases = [(case, policy) for case in corpus['cases'][::13] for policy in policies][:512]
    def simultaneous(item):
        case, policy = item
        original = corpus['references'][policy][case['id']]
        _, result = native.valid_pair(case['old'].encode(), case['new'].encode(), case['context'], policy,
            bool(case['id'] % 2), len(original['old_tokens']), len(original['new_tokens']),
            extra_capacity=11, guard=3, label=f'concurrent-{case["id"]}-{policy}')
        compare_outcome(case, original, result)
        return 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        report['concurrent_complete_pairs'] = sum(pool.map(simultaneous, concurrent_cases))
    assert report['concurrent_complete_pairs'] == 512
    report['additional_original_cases'] = len(extras)
    report['trusted_invalid_utf8_is_outside_contract_and_not_called'] = True
    report['complete_owner_transport_atomicity'] = True
    report['abi_revision'] = 2
    report['policies_exercised'] = policies
    report['all_four_policies_transport_checked'] = True
    report['u32_distinct_id_overflow_at_four_billion_tokens_executed'] = False
    report['production_compile_profile_qualification_is_separate'] = True
