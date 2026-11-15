"""Compare exact public writer transcripts, including partial writes and errors."""
import collections
import hashlib
import json
from pathlib import Path
import re
import subprocess

HEADER = b'Success. Updated the following files:\n'
UNLIMITED = (1 << 64) - 1
GROUPS = ('added', 'modified', 'deleted')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def require(value, message):
    if not value:
        raise RuntimeError(message)


def number(value):
    require(re.fullmatch(r'0|[1-9][0-9]*', value) is not None, 'noncanonical count')
    return int(value)


def unhex(value):
    require(re.fullmatch(r'(?:[0-9a-f]{2})*', value) is not None, 'noncanonical bytes')
    return bytes.fromhex(value)


def fixture(case):
    groups = [[], [], []]
    if case <= 26:
        for group in range(3):
            groups[group] = [f'group-{group}/item-{index}'.encode()
                             for index in range(case % 3)]
            case //= 3
    elif case == 27:
        for group in range(3):
            groups[group] = [f'{group}/{path}'.encode()
                             for path in ('甲/乙', '😀', 'e\u0301', '文件 name', 'a\\b')]
    elif case == 28:
        groups = [[b'same', b'same', b'', b'same', b'same'] for _ in range(3)]
    elif case == 29:
        values = [b'\xff', b'a\x80b', b'\xc0\xaf', b'\xe2\x82', b'\xed\xa0\x80',
                  b'\xf4\x90\x80\x80', b'\xef\xbf\xbd', b'before\xffafter\xfe']
        groups = [values[:] for _ in range(3)]
    elif case == 30:
        values = [b'', b'.', b'..', b'/', b'//srv//a/../b/', b'line\nfile',
                  b'tab\tfile', b'nul\0byte', b'\r\n', b'A misleading-prefix']
        groups = [values[:] for _ in range(3)]
    elif case == 31:
        groups = [[b'x' * (2 * 1024 * 1024)], [b'after-long-path'], []]
    elif case == 32:
        groups = [[], [], ['甲'.encode() * (2 * 1024 * 1024 // 3)]]
    else:
        raise RuntimeError('unknown fixed fixture')
    return groups


def matrix():
    rows = []
    common = [(0, 0, UNLIMITED), (0, 0, 1), (0, 0, 7)]
    common += [(1, point, UNLIMITED) for point in (1, 2, 7, 40)]
    common += [(2, point, UNLIMITED) for point in (0, 37, 38, 80)]
    common += [(3, point, UNLIMITED) for point in (1, 4)]
    formats = [(policy, point, UNLIMITED) for policy in (4, 5) for point in (1, 2, 5)]
    for case in range(33):
        for style in (0, 1):
            configurations = common + (formats if style else [])
            if case >= 31:
                # A partial-write trace records each remaining input slice;
                # only bounded attempts are appropriate for the 2 MiB cases.
                configurations = [(0, 0, UNLIMITED), (2, 80, UNLIMITED)]
                if style:
                    configurations += [(4, 2, UNLIMITED)]
            for policy, point, fragment in configurations:
                rows.append({'id': len(rows), 'case': case, 'style': style,
                             'policy': policy, 'point': point, 'fragment': fragment})
    return rows


def parse(raw):
    require(raw.endswith(b'\n'), 'observer lacks final newline')
    values = {}
    for line in raw[:-1].split(b'\n'):
        key, separator, value = line.partition(b'=')
        require(separator, 'malformed observer field')
        key, value = key.decode('ascii'), value.decode('ascii')
        require(key not in values, 'duplicate observer field')
        if key.endswith('_hex'):
            unhex(value)
        values[key] = value
    require(values.get('protocol') == 'HPSO0001' and
            values.get('observation_complete') == 'true', 'incomplete observer')
    require(raw.rsplit(b'\n', 2)[-2].startswith(b'native_calls='),
            'native call count is not the final field')
    return values


def validate(values, row, *, native):
    required = {'protocol', 'case', 'style', 'policy', 'point', 'fragment', 'result',
                'output_hex', 'write_calls', 'format_calls', 'flush_calls',
                'observation_complete', 'native_calls'}
    for name in ('case', 'style', 'policy', 'point', 'fragment'):
        require(number(values[name]) == row[name], 'executed fixture argument differs')
    paths = fixture(row['case'])
    for name, group in zip(GROUPS, paths):
        count = f'input_{name}_count'
        required.add(count)
        require(number(values[count]) == len(group), 'input count differs')
        for index, path in enumerate(group):
            key = f'input_{name}_{index}_hex'
            required.add(key)
            require(unhex(values[key]) == path, 'actual input path bytes differ')
    success = values['result'] == 'ok'
    require(success or values['result'] == 'error', 'unknown public result')
    if not success:
        required.update(('error_kind', 'error_display_hex', 'error_debug_hex'))
        require(values['error_kind'] in {'BrokenPipe', 'WriteZero', 'Other', 'Interrupted'},
                'unexpected writer error kind')
    writes = number(values['write_calls'])
    formats = number(values['format_calls'])
    accepted = bytearray()
    write_errors = collections.Counter()
    for index in range(writes):
        key = f'write_{index}'
        required.update((key + '_input_hex', key + '_result_hex'))
        data = unhex(values[key + '_input_hex'])
        result = unhex(values[key + '_result_hex']).decode()
        if result.startswith('ok:'):
            count = number(result[3:])
            require(count <= len(data) and count <= row['fragment'],
                    'writer accepted an impossible number of bytes')
            accepted.extend(data[:count])
        else:
            require(result in {'error:BrokenPipe:summary write sentinel',
                               'error:Interrupted:summary write interrupted'},
                    'unexpected callback error')
            write_errors[result.split(':', 2)[1]] += 1
    require(bytes(accepted) == unhex(values['output_hex']),
            'output does not equal the accepted write prefixes')
    for index in range(formats):
        key = f'format_{index}'
        required.add(key + '_static')
        require(values[key + '_static'] in {'true', 'false'}, 'invalid format static flag')
        if values[key + '_static'] == 'true':
            required.add(key + '_literal_hex')
            require(index == 0 and unhex(values[key + '_literal_hex']) == HEADER,
                    'unexpected literal formatting request')
    require(number(values['flush_calls']) == 0, 'print_summary unexpectedly flushes')
    total_paths = sum(map(len, paths))
    calls = number(values['native_calls'])
    if native:
        if row['style']:
            require(calls == formats + int(success), 'native commands do not match format calls')
        elif success:
            require(calls == total_paths + 2, 'native successful command count differs')
        else:
            require(1 <= calls <= total_paths + 1, 'native failed command count differs')
    else:
        require(calls == 0, 'the original unexpectedly calls HIA')
    require((formats > 0) == bool(row['style']), 'wrong Write implementation exercised')
    require(set(values) == required, 'missing or unexpected observer fields')
    if row['policy'] == 0:
        require(success, 'an accepting writer returned an error')
    if row['policy'] == 3:
        require(success, 'default write_all did not recover from Interrupted')
    if success:
        require(accepted.startswith(HEADER), 'successful output lacks exact header')
        if row['case'] != 29:
            # The invalid-UTF8 display case is compared directly with Rust;
            # this additional assertion is intentionally only for valid UTF8.
            expected = HEADER + b''.join(prefix + path + b'\n'
                for prefix, group in zip((b'A ', b'M ', b'D '), paths) for path in group)
            require(accepted == expected, 'successful output has wrong path order or bytes')
    return {'status': 'ok' if success else values['error_kind'], 'native_calls': calls,
            'write_calls': writes, 'format_calls': formats, 'output_bytes': len(accepted),
            'callback_errors': dict(write_errors)}


def run(binaries, producer, env, output):
    output.mkdir()
    cases = output / 'cases'
    cases.mkdir()
    rows = matrix()
    require(len(rows) == 1002, 'the reviewed fixed writer corpus changed')
    save(output / 'matrix.json', rows)
    identities = {name: sha(binary) for name, binary in binaries.items()}
    report = {'passed': False, 'planned_pairs': len(rows), 'skipped': 0, 'mismatches': 0,
              'matrix_sha256': sha(output / 'matrix.json'), 'results': []}
    totals, callbacks = collections.Counter(), collections.Counter()
    total_calls = 0
    with (output / 'observations.jsonl').open('x') as journal:
        for row in rows:
            observations, raw_results, artifacts = {}, {}, {}
            for name, binary in binaries.items():
                stdout = cases / f'{row["id"]:04d}-{name}.stdout'
                stderr = cases / f'{row["id"]:04d}-{name}.stderr'
                argv = [str(binary)] + [str(row[key]) for key in
                                       ('case', 'style', 'policy', 'point', 'fragment')]
                with stdout.open('xb') as out, stderr.open('xb') as errors:
                    result = subprocess.run(argv, cwd=producer, env=env,
                                            stdout=out, stderr=errors, timeout=30)
                require(result.returncode == 0 and stderr.stat().st_size == 0,
                        'actual observer process failed: ' + str(row['id']) + '/' + name)
                raw = stdout.read_bytes()
                values = parse(raw)
                observations[name] = validate(values, row, native=name == 'native')
                raw_results[name] = raw.rsplit(b'native_calls=', 1)[0]
                artifacts[name] = {'argv': argv, 'returncode': result.returncode,
                    'stdout': str(stdout), 'stdout_bytes': len(raw), 'stdout_sha256': sha(stdout),
                    'stderr': str(stderr), 'stderr_sha256': sha(stderr)}
            require(raw_results['original'] == raw_results['native'],
                    'public writer transcript mismatch: ' + str(row['id']))
            observation = observations['native']
            totals[observation['status']] += 1
            callbacks.update(observation['callback_errors'])
            total_calls += observation['native_calls']
            journal.write(json.dumps({'id': row['id'], 'arguments': row,
                'observation': observation, 'artifacts': artifacts,
                'equal_except_final_native_counter': True}, sort_keys=True) + '\n')
            journal.flush()
            report['results'].append({'id': row['id'], **observation})
    for name, binary in binaries.items():
        require(sha(binary) == identities[name], 'an executed writer observer changed')
    require(set(totals) == {'ok', 'BrokenPipe', 'WriteZero', 'Other', 'Interrupted'},
            'the matrix did not exercise every required writer outcome')
    require(callbacks['BrokenPipe'] > 0 and callbacks['Interrupted'] > 0,
            'writer callback errors were not actually exercised')
    report.update(passed=True, compared_pairs=len(rows), actual_processes=2 * len(rows),
                  native_forwarded_calls=total_calls, outcomes=dict(totals),
                  callback_errors=dict(callbacks),
                  observation_journal_sha256=sha(output / 'observations.jsonl'))
    save(output / 'report.json', report)
    return report
