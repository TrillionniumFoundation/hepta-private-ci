"""Run only the explicitly selected unmodified evolution mechanism suite."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source'
OUT = ROOT / 'execution'
EVENTS = []
sys.path.insert(0, str(ROOT))
from module_origin_collector import collect_module_origins


def retain(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def audit_event(event, arguments):
    if event == 'subprocess.Popen':
        executable, argv, cwd, _environment = arguments
        EVENTS.append({'event': event, 'executable': str(executable),
                       'argv': list(argv) if isinstance(argv, (tuple, list)) else str(argv),
                       'cwd': str(cwd) if cwd is not None else None,
                       'observed_at_ns': time.time_ns()})


started = time.monotonic_ns()
try:
    sys.addaudithook(audit_event)
    suite = unittest.defaultTestLoader.discover(str(SOURCE / 'scripts/memory_cell_evolution'), pattern='test_*.py')
    discovered = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    origins = collect_module_origins(sys.modules, SOURCE)
    modules = origins['source_module_origins']
    prohibited = [name for name in sys.modules if name in {'parametric_model', 'pretrained'} or name.startswith(('transformers', 'peft'))]
    record = {'schema': 'hepta.memory-union.evolution-mechanisms.v1',
              'expected_tests': 22, 'discovered': discovered, 'tests_run': result.testsRun,
              'was_successful': result.wasSuccessful(), 'failures': result.failures,
              'errors': result.errors, 'skipped': result.skipped,
              'unexpected_successes': result.unexpectedSuccesses,
              'expected_failures': result.expectedFailures,
              'wall_ns_in_runner': time.monotonic_ns() - started,
              'python': sys.version, 'executable': sys.executable, 'pid': os.getpid(),
              'tensor_dependency_versions': {name: importlib.metadata.version(name) for name in ['torch', 'safetensors']},
              'tensor_modules_loaded': {'torch': 'torch' in sys.modules, 'safetensors': 'safetensors' in sys.modules},
              'model_modules_loaded': prohibited, 'source_modules_loaded': modules, 'module_origin_collection': origins,
              'subprocess_events': EVENTS,
              'model_execution_boundary': 'Static reviewed tests call only stubs/structural tensor validation; no model classes or training/generation module imported.',
              'budget_local_suite_executed': False}
    for key in ('failures', 'errors', 'skipped', 'expected_failures'):
        record[key] = [[str(test), detail] for test, detail in record[key]]
    record['unexpected_successes'] = [str(test) for test in record['unexpected_successes']]
    retain(OUT / 'evolution-result.json', record)
    print(json.dumps({k: record[k] for k in ['expected_tests', 'discovered', 'tests_run', 'was_successful', 'tensor_dependency_versions', 'model_modules_loaded']}, sort_keys=True), flush=True)
    code = 0 if discovered == 22 and result.testsRun == 22 and result.wasSuccessful() and not result.skipped and not prohibited else 2
except BaseException as error:
    retain(OUT / 'evolution-runner-failure.json', {'type': type(error).__name__, 'message': str(error),
           'traceback': traceback.format_exc(), 'subprocess_events': EVENTS,
           'wall_ns': time.monotonic_ns() - started})
    raise
raise SystemExit(code)
