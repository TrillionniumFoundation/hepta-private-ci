#!/usr/bin/env python3
# Copyright 2026 TrillionniumFoundation
# SPDX-License-Identifier: Apache-2.0
"""Review frozen #94 records without starting Runtime or changing model weights.

Recomputes the published, source-pinned Fraction reference from every supplied
row rather than trusting the execution worker's pass flags. This is a records
review by another agent, not a new reference algorithm or task-efficacy trial.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import resource
import sys
import time


READS = {}


def data(path):
    raw = path.read_bytes()
    READS[str(path)] = hashlib.sha256(raw).hexdigest()
    return raw


def read(path):
    raw = data(path)
    return json.loads(gzip.decompress(raw) if path.suffix == '.gz' else raw)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def body(response):
    require(not response.get('isError') and 'rpc_error' not in response,
            'valid certificate returned a transport/tool error')
    return json.loads(response['content'][0]['text'])


def main(args):
    start, cpu = time.monotonic(), time.process_time()
    pkg = args.package.resolve()
    evidence = pkg / 'evidence'
    qualification = evidence / 'qualification'
    corpus = qualification / 'native-certificate-corpus-r1'
    protocol_path = qualification / 'native-certificate-execution-r1.json'
    protocol = read(protocol_path)
    bundle = read(evidence / 'BUNDLE_MANIFEST.json')
    require(sha(data(protocol_path)) == bundle['protocol_sha256'], 'execution protocol binding')
    require(bundle['published_source_commit'] == 'bc38fb82244b946907886704b3c677bf00761cb9',
            'unexpected source head')
    for name, record in bundle['files'].items():
        raw = data(evidence / name)
        require(len(raw) == record['bytes'] and sha(raw) == record['sha256'],
                'retained evidence file changed: ' + name)
    inputs = read(pkg / 'inputs/INPUT_MANIFEST.json')
    require(sha(data(pkg / 'inputs/INPUT_MANIFEST.json')) == protocol['input_manifest_sha256'],
            'input manifest binding')
    for item in inputs['files']:
        raw = data(pkg / 'inputs' / item['name'])
        require(len(raw) == item['bytes'] and sha(raw) == item['sha256'],
                'input file binding: ' + item['name'])
    drivers = evidence / 'executed_driver_snapshot'
    for name, expected in protocol['driver_sources'].items():
        require(sha(data(drivers / name)) == expected, 'frozen driver binding: ' + name)

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(drivers))
    import reference
    import run_corpus

    build = read(qualification / 'native-certificate-attempt-1/RESULT.json')
    require(build['all_passed'] and build['completed'], 'original build unsuccessful')
    require(build['binary']['sha256'] == protocol['binary_sha256'], 'build/execution binary mismatch')
    summaries = []
    for index, command in enumerate(build['commands'], 1):
        log = data(qualification / f'native-certificate-attempt-1/command-{index}.log')
        require(command['exit_code'] == 0 and not command['timed_out'], 'build gate failed')
        require(sha(log) == command['log_sha256'] and len(log) == command['log_bytes'],
                'build log binding')
        if 'test' in command['command']:
            matches = re.findall(rb'test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored;', log)
            require(matches and (b'87', b'0', b'2') in matches, 'focused test summary mismatch')
            summaries.append([int(x) for x in matches[-1]])
    source_manifest = read(qualification / 'native-certificate-attempt-1/SOURCE_MANIFEST.json')
    require(all(source_manifest[n]['sha256'] == s for n, s in protocol['native_sources'].items()),
            'qualification/execution source disagreement')
    result = read(corpus / 'RESULTS.json')
    require(result['binary_sha256'] == protocol['binary_sha256'], 'RPC binary identity mismatch')
    fits = []
    for fit in (11, 23, 37, 53, 71):
        params = read(pkg / 'inputs' / f'fit_{fit}_REQUEST.json.gz')
        native = body(read(corpus / f'fit_{fit}_RPC.json.gz'))
        actual = reference.reference(params)
        cached = read(pkg / 'inputs' / f'fit_{fit}_REFERENCE.json.gz')
        require(actual == cached, 'fresh Fraction differs from frozen reference')
        reference.compare_native(native, actual)
        require(native['implementation_source_sha256'] == protocol['native_sources']['src/mcp/weight_certificate.rs'],
                'native implementation identity')
        require(native['arithmetic_source_sha256'] == protocol['native_sources']['src/mcp/weight_certificate_exact.rs'],
                'native arithmetic identity')
        for key in ('checkpoint_sha256', 'witness_sha256'):
            require(native[key] == params['expected_' + key], 'native input digest mismatch')
        require(native['witness_rows'] == len(params['rows']), 'native omitted witness rows')
        fits.append({'fit': fit, 'rows': len(params['rows']), 'verdict': native['proof']['verdict'],
                     'complete_fraction_recompute_equal': True,
                     'center_bits_and_all_native_rationals_equal': True})
        print(json.dumps(fits[-1]), flush=True)
    controls = []
    for name, params, outcome in run_corpus.controls():
        response = read(corpus / f'control_{name}_RPC.json.gz')
        if outcome == 'ERROR':
            require(response.get('isError') or 'rpc_error' in response, 'invalid input admitted: ' + name)
        else:
            native = body(response)
            reference.compare_native(native, reference.reference(params))
            require(native['proof']['verdict'] == outcome, 'wrong control outcome: ' + name)
        controls.append({'name': name, 'expected': outcome, 'actual_record_checked': True})
    outer = read(qualification / 'native-certificate-corpus-r1-outer/PROCESS_RECEIPT.json')
    require(outer['completed'] and outer['exit_code'] == 0 and not outer['timed_out'],
            'corpus process unsuccessful')
    for path, expected in READS.items():
        require(sha(Path(path).read_bytes()) == expected, 'record changed during review: ' + path)
    report = {
        'schema': 'hepta.wsp.independent-native-record-review.v1', 'passed': True,
        'published_runtime_commit': bundle['published_source_commit'],
        'execution_protocol_sha256': bundle['protocol_sha256'],
        'binary_sha256': protocol['binary_sha256'],
        'evidence_files_hash_checked': len(bundle['files']),
        'source_manifest_entries_bound': len(protocol['native_sources']),
        'source_files_rebuilt_by_this_reviewer': False,
        'fresh_reference_implementation': False,
        'frozen_fraction_reference_reexecuted': True,
        'focused_test_summaries_passed_failed_ignored': summaries,
        'fits': fits, 'controls': controls, 'total_rows': sum(x['rows'] for x in fits),
        'all_records_unchanged_during_review': True,
        'records_read': [{'path': str(Path(p).relative_to(pkg)), 'sha256': h}
                         for p, h in sorted(READS.items())],
        'reviewer_source_sha256': sha(Path(__file__).read_bytes()),
        'review_self_cpu_seconds': time.process_time() - cpu,
        'review_wall_seconds': time.monotonic() - start,
        'review_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        'new_native_process_execution': False,
        'new_neural_training_or_forward': False,
        'source_semantics_reexecuted': False,
        'new_task_value_qualification': False,
        'scope': 'Independent review of frozen source-bound records; conditional exact arithmetic only.'
    }
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('fits', 'controls', 'records_read')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
