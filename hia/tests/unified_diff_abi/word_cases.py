#!/usr/bin/env python3
"""Independent count-only boundary matrix, using the complete original observer."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import struct
import subprocess

from .transport import MAX, binding, compare_outcome, sha256, validate_binding, validate_original_corpus


def numerical_mask_check():
    low = 0x7F7F7F7F7F7F7F7F
    high = 0x8080808080808080
    ones = 0x0101010101010101

    def flags(word, delimiter):
        value = word ^ (delimiter * ones)
        added = (value & low) + low
        assert added <= 0xFEFEFEFEFEFEFEFE <= MAX
        return ~(added | value | low) & high

    words = []
    for filler in (0, 1, 10, 11, 12, 13, 255):
        for lane in range(8):
            for byte in range(256):
                value = bytearray([filler] * 8)
                value[lane] = byte
                words.append(int.from_bytes(value, 'little'))
    rng = random.Random(0x9F38C0DE)
    words.extend(rng.getrandbits(64) for _ in range(16384))
    for word in words:
        data = word.to_bytes(8, 'little')
        cr = flags(word, 13)
        lf = flags(word, 10)
        for delimiter, found in ((13, cr), (10, lf)):
            expected = sum((128 << (8 * index)) for index, byte in enumerate(data) if byte == delimiter)
            assert found == expected
        for previous_cr in (0, 128):
            selected = cr | (lf & ~(((cr << 8) & MAX) | previous_cr))
            count = (((selected >> 7) * ones) & MAX) >> 56
            expected = sum(byte == 13 or (byte == 10 and (previous_cr == 0 if index == 0 else data[index - 1] != 13))
                           for index, byte in enumerate(data))
            assert count == expected
    for mask in range(256):
        lanes = sum(((mask >> index) & 1) << (8 * index) for index in range(8))
        assert ((lanes * ones) & MAX) >> 56 == mask.bit_count()
    return {
        'word_vectors': len(words), 'exact_delimiter_mask_checks': 2 * len(words),
        'previous_cr_count_checks': 2 * len(words), 'all_binary_lane_sum_patterns': 256,
        'checked_lane_add_upper_bound_hex': 'fefefefefefefefe',
        'numeric_only': True, 'actual_hia_performance_measured': False,
        'proof': 'Each seven-bit lane plus 127 is at most 254, so the checked u64 addition cannot carry between lanes or overflow. The exact high-bit zero test is verified for every u8 in every lane. At most eight unit flags enter the wrap-multiply lane sum; every cumulative byte is at most eight.'}


def make_cases():
    contexts = (0, 1, 3, 1 << 63, MAX)
    cases = []
    identities = {}

    def add(name, old, new, context):
        old, new = old.decode('utf-8'), new.decode('utf-8')
        key = (old, new, context)
        if key in identities:
            return
        identities[key] = len(cases)
        cases.append({'id': len(cases), 'name': name, 'old': old, 'new': new, 'context': context})

    # Every half-length pair independently checks that a CR at the old end does
    # not combine with an LF at the new start, regardless of absolute alignment.
    for old_length in range(65):
        old = b'a' * (old_length - 1) + b'\r' if old_length else b''
        for new_length in range(65):
            new = b'\n' + b'b' * (new_length - 1) if new_length else b''
            add(f'half-split-{old_length}-{new_length}', old, new,
                contexts[(old_length * 67 + new_length) % len(contexts)])

    atoms = (b'\r', b'\n', b'\r\n', b'\n\r', b'\r\r', b'\n\n',
             b'\n\v', b'\r\f', b'\r\n\r', b'\r\n\n', b'\0\r\n\0',
             '\u008a\u008d'.encode(), '\u0085\u2028\u2029'.encode(), '汉🙂'.encode())
    lengths = list(range(65)) + [65, 95, 96, 97, 127, 128, 129, 255, 256, 257]
    unicode_unit = '\u008a\u008d汉🙂\u0085\u2028\u2029'.encode()
    for length in lengths:
        for filler in (b'a' * length, b'\0' * length,
                       unicode_unit * (length // len(unicode_unit)) + b'x' * (length % len(unicode_unit))):
            add(f'no-ascii-delimiter-{length}', filler, filler, contexts[length % len(contexts)])
        positions = {0, max(0, length - 1), max(0, length - 2), max(0, length - 4)}
        for boundary in range(0, min(length, 80) + 1, 8):
            positions.update(boundary + offset for offset in (-2, -1, 0, 1))
        if length > 80:
            positions.update(length - offset for offset in range(1, 10))
        for start in sorted(positions):
            for index, atom in enumerate(atoms):
                if start < 0 or start + len(atom) > length:
                    continue
                value = b'a' * start + atom + b'b' * (length - start - len(atom))
                add(f'word-{length}-{start}-{index}', value, value,
                    contexts[(length + start + index) % len(contexts)])
        dense = (b'\r\n' * ((length + 1) // 2))[:length]
        add(f'dense-crlf-{length}', dense, dense, contexts[length % len(contexts)])
    assert len(cases) < 30000
    assert {len(x['old'].encode()) for x in cases}.issuperset(range(65))
    assert {len(x['new'].encode()) for x in cases}.issuperset(range(65))
    assert len([x for x in cases if x['name'].startswith('half-split-')]) == 65 * 65
    return cases


def verify(args, native, report):
    assert len(args.oracle_report) == 1
    assert sha256(args.oracle_report[0]) == args.original_report_sha
    original = validate_original_corpus(args.oracle_report[0])
    report['original_reference_provenance'] = original['bindings']
    report['numeric_mask_validation'] = numerical_mask_check()
    cases = make_cases()
    directory = args.report.with_name(args.report.stem + '.original')
    directory.mkdir(exist_ok=False)
    case_path, input_path = directory / 'cases.json', directory / 'cases.bin'
    case_path.write_text(json.dumps(cases, ensure_ascii=True) + '\n')
    with input_path.open('xb') as stream:
        for case in cases:
            old, new = case['old'].encode(), case['new'].encode()
            stream.write(struct.pack('<4Q', case['id'], case['context'], len(old), len(new)) + old + new)
    report['cases'] = binding(case_path)
    report['input'] = binding(input_path)
    report['original_commands'] = []
    references = {}
    for policy in range(4):
        command = original['commands'][policy]
        binary = validate_binding(command['binary'])
        validate_binding(command['rlib'])
        stdout, stderr = directory / f'policy-{policy}.stdout', directory / f'policy-{policy}.stderr'
        with input_path.open('rb') as source, stdout.open('xb') as out, stderr.open('xb') as err:
            process = subprocess.run([str(binary)], stdin=source, stdout=out, stderr=err, timeout=120)
        row = {'policy': policy, 'argv': [str(binary)], 'returncode': process.returncode,
               'binary': binding(binary), 'rlib': command['rlib'], 'stdout': binding(stdout), 'stderr': binding(stderr)}
        report['original_commands'].append(row)
        assert process.returncode == 0 and stderr.stat().st_size == 0, row
        rows = [json.loads(line) for line in stdout.read_text().splitlines()]
        assert len(rows) == len(cases) and [x['id'] for x in rows] == list(range(len(cases)))
        assert all('construction_panic_hex' not in x for x in rows)
        references[policy] = rows
    coverage = CounterMap()
    for case in cases:
        old, new = case['old'].encode(), case['new'].encode()
        coverage['old_ends_cr_new_starts_lf'] += bool(old.endswith(b'\r') and new.startswith(b'\n'))
        coverage['has_lf_vt_borrow_trap_fixture'] += b'\n\v' in old or b'\n\v' in new
        coverage['has_cr_ff_borrow_trap_fixture'] += b'\r\f' in old or b'\r\f' in new
        coverage['has_nul'] += b'\0' in old or b'\0' in new
        coverage['has_non_ascii'] += any(byte >= 128 for byte in old + new)
        for policy in range(4):
            expected = references[policy][case['id']]
            pairs = []
            for trusted in (False, True):
                query, result = native.valid_pair(old, new, case['context'], policy, trusted,
                    len(expected['old_tokens']), len(expected['new_tokens']),
                    extra_capacity=37, guard=1 + case['id'] % 31,
                    label=f"word-{case['id']}-{policy}-{trusted}")
                compare_outcome(case, expected, result)
                pairs.append((query.output, result.output))
            assert pairs[0] == pairs[1]
    def concurrent(index):
        case = cases[(index * 97) % len(cases)]
        policy = index % 4
        expected = references[policy][case['id']]
        _, result = native.valid_pair(case['old'].encode(), case['new'].encode(), case['context'],
            policy, bool(index % 2), len(expected['old_tokens']), len(expected['new_tokens']),
            label=f'word-concurrent-{index}')
        compare_outcome(case, expected, result)
        return 1
    with ThreadPoolExecutor(max_workers=8) as pool:
        report['concurrent_pairs'] = sum(pool.map(concurrent, range(128)))
    assert all(value > 0 for value in coverage.values())
    report['case_count'] = len(cases)
    report['source_half_length_grid'] = {'old_bytes': [0, 64], 'new_bytes': [0, 64], 'all_pairs': 4225}
    report['source_fixtures_coverage'] = dict(coverage)
    report['native_plan_comparisons'] = 8 * len(cases)
    report['strict_trusted_pairs'] = 4 * len(cases)
    report['policies_exercised'] = [0, 1, 2, 3]
    report['mixed_compile_profile_mapping_qualified'] = False
    report['whole_product_performance_qualified'] = False


class CounterMap(dict):
    def __missing__(self, key):
        return 0


