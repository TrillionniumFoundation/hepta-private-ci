#!/usr/bin/env python3
"""Bounded original CPython HTTP test method replay, not its full upstream suite.

The *only* executable upstream code consists of the SHA-pinned original
http/client.py module, original FakeSocket helper and unmodified selected
original CPython unittest methods. This is not general arbitrary source execution.
"""
from __future__ import annotations

import array
import ast
import hashlib
import importlib.util
import io
import itertools
import json
from pathlib import Path
import socket
import ssl  # import SSL class before disabling socket factory; no connection is opened
import sys
import unittest

MODULE_SHA = '8486d3c54d5ab5a8468703239287e60127d7f2159f5ae6652b33a456a3716444'
TEST_SHA = '347061ba9071babdcabcc74d4d1c2581a567f9d788864e3c4d958c2c3c009907'
CASES = (
    ('HeaderTests', 'test_auto_headers'),
    ('HeaderTests', 'test_content_length_0'),
    ('HeaderTests', 'test_putheader'),
    ('BasicTest', 'test_send'),
    ('BasicTest', 'test_send_iter'),
    ('BasicTest', 'test_send_type_error'),
    ('BasicTest', 'test_partial_reads'),
    ('BasicTest', 'test_mixed_reads'),
    ('BasicTest', 'test_partial_reads_past_end'),
    ('BasicTest', 'test_partial_reads_no_content_length'),
    ('BasicTest', 'test_partial_reads_incomplete_body'),
    ('BasicTest', 'test_malformed_content_length'),
    ('BasicTest', 'test_malformed_chunk_size'),
    ('BasicTest', 'test_incomplete_read'),
)
SCHEMA = 'hepta.memory.original-cpython-upstream-selected-methods.v1'
FAULTS = ('none', 'corrupt-header', 'corrupt-send')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def forbid_network(*_args, **_kwargs):
    raise RuntimeError('physical socket network prohibited')


def replay(original_module: Path, original_tests: Path, fault: str):
    if fault not in FAULTS:
        raise ValueError('unsupported fault profile')
    raw = original_module.read_bytes()
    tests_raw = original_tests.read_bytes()
    if (len(raw) != 60691 or digest(raw) != MODULE_SHA
            or len(tests_raw) != 111357 or digest(tests_raw) != TEST_SHA):
        raise ValueError('original upstream Git byte identity changed')
    if not sys.flags.isolated or not sys.flags.no_site:
        raise ValueError('isolated child process required')

    # Network lockdown before invoking the original implementation or tests.
    socket.socket = forbid_network
    socket.create_connection = forbid_network
    spec = importlib.util.spec_from_file_location('pinned_original_cpython_http_client', original_module)
    if spec is None or spec.loader is None:
        raise ValueError('no original-module loader')
    client = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client)
    if client.HTTPConnection.__module__ != 'pinned_original_cpython_http_client':
        raise ValueError('original method was not loaded')

    original_ast = ast.parse(tests_raw, filename=str(original_tests))
    classes = {}
    for node in original_ast.body:
        if isinstance(node, ast.ClassDef) and node.name in ('FakeSocket', 'HeaderTests', 'BasicTest'):
            if node.name in classes:
                raise ValueError('duplicate original upstream test class')
            classes[node.name] = node
    if set(classes) != {'FakeSocket', 'HeaderTests', 'BasicTest'}:
        raise ValueError('missing upstream class definitions')
    nodes = [classes['FakeSocket']]
    evidence = []
    for cname in ('HeaderTests', 'BasicTest'):
        old = classes[cname]
        methods = [node for node in old.body if isinstance(node, ast.FunctionDef)
                   and (cname, node.name) in CASES]
        expected = [method for c, method in CASES if c == cname]
        if len(methods) != len(expected) or {m.name for m in methods} != set(expected):
            raise ValueError('missing or duplicate original upstream method')
        for method in methods:
            original_segment = ast.get_source_segment(tests_raw.decode(), method)
            evidence.append(dict(case=f'{cname}.{method.name}', start_line=method.lineno,
                                 method_sha256=digest(original_segment.encode())))
        # New class shell, but each *original AST method* and its assertions are used unmodified.
        class_shell = ast.ClassDef(name=cname, bases=[ast.Name(id='TestCase', ctx=ast.Load())],
                                   keywords=[], body=methods, decorator_list=[])
        ast.copy_location(class_shell, old)
        nodes.append(class_shell)
    exec_ast = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
    # globals provide only original import names, no local backfills for missing test helpers
    env = {'__name__': '__original_test_selected__', 'client': client,
           'TestCase': unittest.TestCase, 'io': io, 'array': array,
           'itertools': itertools}
    exec(compile(exec_ast, str(original_tests), 'exec'), env)

    if fault == 'corrupt-header':
        original = client.HTTPConnection.putheader
        def corrupt(self, name, *values):
            if name.lower() == 'content-length' and values == (42,):
                return original(self, name, 41)
            return original(self, name, *values)
        client.HTTPConnection.putheader = corrupt
    elif fault == 'corrupt-send':
        original = client.HTTPConnection.send
        def corrupt(self, value):
            if isinstance(value, bytes) and value == b'this is a test this is only a test':
                value = b'this is a test this is ONLY a test'
            return original(self, value)
        client.HTTPConnection.send = corrupt

    test_suite = unittest.TestSuite([env[c](m) for c, m in CASES])
    class Receipt(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self.passes = []
        def addSuccess(self, test):
            super().addSuccess(test)
            self.passes.append(test.id().split('.')[-2] + '.' + test.id().split('.')[-1])
    outcome = Receipt()
    test_suite.run(outcome)
    all_ids = [f'{c}.{m}' for c, m in CASES]
    failed = [x.id().split('.')[-2] + '.' + x.id().split('.')[-1] for x, _ in outcome.failures]
    errored = [x.id().split('.')[-2] + '.' + x.id().split('.')[-1] for x, _ in outcome.errors]
    skipped = [x.id().split('.')[-2] + '.' + x.id().split('.')[-1] for x, _ in outcome.skipped]
    if outcome.testsRun != len(CASES) or len(set(all_ids)) != len(CASES):
        raise ValueError('upstream test census drift')
    if len(outcome.passes) + len(failed) + len(errored) + len(skipped) != len(CASES):
        raise ValueError('missing original test statuses')
    return dict(schema=SCHEMA, original_source_sha256=MODULE_SHA,
                original_upstream_tests_sha256=TEST_SHA,
                original_test_method_sources=evidence,
                exact_original_test_methods=len(CASES),
                planned_original_test_ids=all_ids, fault=fault,
                passed=outcome.passes, failed=failed, errors=errored, skipped=skipped,
                executed_original_test_methods=outcome.testsRun,
                original_module_loaded=True, original_test_methods_unmodified=True,
                actual_original_upstream_test_source_executed=True,
                entire_original_upstream_test_suite_executed=False,
                tests_rewritten_to_pass=False, network_permitted=False,
                pretrained_reader_calls=0, production_qualified=False)


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise ValueError('usage: worker <original-module> <original-test-file> <fault>')
    print(json.dumps(replay(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]),
                     sort_keys=True, ensure_ascii=False, separators=(',', ':')))
