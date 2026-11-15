"""Run each real observer once; retain lossless stdout and literal public bytes."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time

from .common import binding, require, save, verify
from . import observations, native_traces


def capture(variant, binary, fixture, fixtures, output, env, resources, reference=None):
    resources.check(f'{variant} public process', 6*1024*1024)
    out = output/f'{variant}-transcript.bin.gz'
    err = output/f'{variant}-public.stderr'
    summary = output/f'{variant}-observations.jsonl.gz'
    counts, parse_tags, outcomes, errors, panics, events = [Counter() for _ in range(6)]
    full_hash, public_hash = hashlib.sha256(), hashlib.sha256()
    raw_bytes = 0
    completed = 0
    failure = None
    started = time.time_ns()
    request = dict(argv=[str(binary)], cwd=str(output), input=binding(fixture),
                   binary=binding(binary), resources=resources.check(f'{variant} process start'))
    save(output/f'{variant}-public-request.json', request)
    with fixture.open('rb') as source, err.open('xb') as stderr, out.open('xb') as raw, summary.open('xb') as index_raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed, \
             gzip.GzipFile(filename='', mode='wb', fileobj=index_raw, mtime=0) as index:
            process = subprocess.Popen(request['argv'], stdin=source, stdout=subprocess.PIPE,
                                       stderr=stderr, cwd=output, env=env)
            def read(size):
                nonlocal raw_bytes
                data = process.stdout.read(size)
                compressed.write(data)
                full_hash.update(data)
                raw_bytes += len(data)
                if len(data) != size:
                    raise ValueError(f'partial frame ({len(data)}/{size})')
                return data
            try:
                for expected in [None, *fixtures]:
                    header = read(24)
                    number, size, call_count = struct.unpack('<QQQ', header)
                    assert size < 128*1024*1024
                    bound = 0 if expected is None else 16 + 2 * len(expected['values']) + 2 * expected['source_bytes']
                    assert call_count <= bound
                    wanted = (1 << 64)-1 if expected is None else expected['id']
                    assert number == wanted
                    payload = read(size)
                    call_bytes = read(call_count*native_traces.WORDS*8)
                    calls = list(struct.iter_unpack('<20Q', call_bytes))
                    public_hash.update(struct.pack('<QQ', number, size)+payload)
                    if reference is not None:
                        reference_header = reference.read(24)
                        assert len(reference_header) == 24
                        ref_number, ref_size, ref_calls = struct.unpack('<QQQ', reference_header)
                        assert (ref_number, ref_size, ref_calls) == (number, size, 0)
                        ref_payload = reference.read(ref_size)
                        if payload != ref_payload:
                            offset = next(i for i, (a, b) in enumerate(zip(payload, ref_payload)) if a != b)
                            raise ValueError(f'complete public payload differs: id={number}, offset={offset}')
                    if expected is None:
                        observations.constructors(payload)
                        assert calls == []
                    else:
                        observed = observations.public(payload, expected)
                        if variant == 'native':
                            counts.update(native_traces.validate(calls, observed))
                        else:
                            assert not calls
                        parse_tags[str(observed['parse_tag'])] += 1
                        for result in observed['outcomes']:
                            outcomes[result['kind']] += 1
                            events.update(result['events'])
                            if result['kind'] == 'error':
                                debug = result['error']['debug']
                                for name in ['DuplicateValue', 'ExtraValue', 'MissingValue']:
                                    if name in debug:
                                        errors[name] += 1
                            elif result['kind'] == 'panic':
                                panics[result['payload']] += 1
                        index.write((json.dumps(dict(fixture=expected,
                            payload_bytes=size, payload_sha256=hashlib.sha256(payload).hexdigest(),
                            native_calls=call_count, observed=observed), ensure_ascii=True)+'\n').encode())
                        completed += 1
                    if completed % 512 == 0:
                        resources.check(f'{variant} frame {completed}', 1024*1024)
                trailing = process.stdout.read(1)
                compressed.write(trailing)
                full_hash.update(trailing)
                raw_bytes += len(trailing)
                assert trailing == b''
                if reference is not None:
                    assert reference.read(1) == b''
            except BaseException as error:
                failure = dict(type=type(error).__name__, message=str(error),
                               next_case=completed, fixture=fixtures[completed] if completed < len(fixtures) else None)
                # Preserve the rest and the real process exit; do not retry or kill it.
                for chunk in iter(lambda: process.stdout.read(1024*1024), b''):
                    compressed.write(chunk)
                    full_hash.update(chunk)
                    raw_bytes += len(chunk)
            finally:
                code = process.wait()
    if failure is None and code == 0:
        try:
            assert completed == len(fixtures)
            assert set(parse_tags) == {'0', '1', '2', '3', '4'}
            assert set(errors) == {'DuplicateValue', 'ExtraValue', 'MissingValue'}
            assert set(panics) == {f'input fault {i}' for i in range(1, 9)}
        except BaseException as error:
            failure = dict(type=type(error).__name__, message='coverage: '+str(error))
    result = dict(schema='codex.hia.template-public-observer-run.v1', variant=variant,
        passed=failure is None and code == 0, returncode=code,
        signal=-code if code < 0 else None, elapsed_ns=time.time_ns()-started,
        request=request, completed_cases=completed, intended_cases=len(fixtures),
        stdout=binding(out), stdout_uncompressed_bytes=raw_bytes,
        stdout_uncompressed_sha256=full_hash.hexdigest(), stderr=binding(err),
        public_payloads_sha256=public_hash.hexdigest(), observation_index=binding(summary),
        native_operations=dict(counts), native_calls=sum(counts.values()),
        parse_tags=dict(parse_tags), render_outcomes=dict(outcomes),
        render_errors=dict(errors), actual_input_panics=dict(panics), lifecycle_events=dict(events),
        failure=failure, resources=resources.check(f'{variant} terminal'))
    save(output/f'{variant}-public-report.json', result)
    if not result['passed']:
        raise RuntimeError(f'{variant} public failed: {failure}; code={code}')
    return result


def verify_gzip(record):
    digest, count = hashlib.sha256(), 0
    with gzip.open(record['stdout']['path'], 'rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
            count += len(block)
    require(count == record['stdout_uncompressed_bytes']
            and digest.hexdigest() == record['stdout_uncompressed_sha256'],
            'complete lossless stdout/CRC identity changed')
    with gzip.open(record['observation_index']['path'], 'rb') as stream:
        lines = sum(1 for _ in stream)
    require(lines == record['completed_cases'], 'complete observation index/CRC differs')


def observe(compiled, corpus, output, env, resources):
    output.mkdir()
    fixture = Path(corpus['full_inputs']['path'])
    with gzip.open(corpus['index']['path'], 'rt') as stream:
        fixtures = [json.loads(line) for line in stream]
    require(len(fixtures) == corpus['cases'] == 13206, 'incomplete frozen case index')
    inputs = [corpus['full_inputs'], corpus['index'], *compiled['sources'].values()]
    for side in compiled['observers'].values():
        inputs.extend([side['binary'], side['owner_library']])
    for item in inputs:
        verify(item)
    report = dict(schema='codex.hia.template-current-cargo-public-results.v2', passed=False,
        inputs=inputs, intended_case_pairs=13206, constructor_values_compared=21,
        comparison='Literal complete public payload bytes; native ABI trace is a separate appended channel.',
        tests_skipped=0, runs={})
    try:
        original = capture('original', Path(compiled['observers']['original']['binary']['path']),
                           fixture, fixtures, output, env, resources)
        report['runs']['original'] = binding(output/'original-public-report.json')
        verify_gzip(original)
        with gzip.open(original['stdout']['path'], 'rb') as reference:
            native = capture('native', Path(compiled['observers']['native']['binary']['path']),
                             fixture, fixtures, output, env, resources, reference)
        report['runs']['native'] = binding(output/'native-public-report.json')
        verify_gzip(native)
        for key in ['public_payloads_sha256', 'parse_tags', 'render_outcomes', 'render_errors',
                    'actual_input_panics', 'lifecycle_events']:
            require(original[key] == native[key], 'original/native complete observation differs: '+key)
        require(native['native_calls'] == 66549
                and native['native_operations'] == {'parse_query': 32184, 'parse_emit': 8103,
                    'render_check_candidate': 11502, 'render_query': 8554, 'render_emit': 6206},
                'actual parse/render native operation coverage differs')
        for item in inputs:
            verify(item)
        report.update(passed=True, case_pairs=13206, public_payloads_sha256=original['public_payloads_sha256'],
            actual_native_calls=native['native_calls'], actual_native_operations=native['native_operations'],
            parse_tags=original['parse_tags'], render_errors=original['render_errors'],
            render_outcomes=original['render_outcomes'], input_panics=original['actual_input_panics'],
            lifecycle_events=original['lifecycle_events'], full_gzip_crc_and_raw_hash_verified=True,
            process_returncodes={'original': original['returncode'], 'native': native['returncode']},
            artifacts=[original[name] for name in ['stdout', 'stderr', 'observation_index']]
                      +[native[name] for name in ['stdout', 'stderr', 'observation_index']],
            all_observer_inputs_unchanged=True, resources=resources.check('complete public differential'))
    except BaseException as error:
        report['failure'] = repr(error)
        raise
    finally:
        save(output/'report.json', report)
    return report
