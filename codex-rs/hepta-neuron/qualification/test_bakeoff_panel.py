"""Exercise batch failure retention with real children, not model-quality fixtures."""
from __future__ import annotations

import argparse
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bakeoff_panel import run_panel

FIXTURE = '''import pathlib, sys, time
model = sys.argv[sys.argv.index('--model') + 1]
output = pathlib.Path(sys.argv[sys.argv.index('--output-dir') + 1])
print(model, flush=True)
if model == 'slow':
    print(__import__('os').getpid(), flush=True)
    time.sleep(30)
(output / (model + '.visited')).write_text('visited')
sys.exit(23 if model == 'broken' else 0)
'''


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script = self.root / 'fixture.py'
        self.script.write_text(FIXTURE)
        self.arguments = dict(script=self.script, output_dir=self.root / 'output',
                              model_root=self.root / 'models', device='cpu',
                              source={'commit': 'fixture-not-model-evidence'}, timeout_seconds=5)

    def run_models(self, models, **changes):
        with contextlib.redirect_stdout(io.StringIO()):
            return run_panel(models=models, **{**self.arguments, **changes})

    def test_failed_first_backend_does_not_hide_later_results(self):
        panel, report = self.run_models(('broken', 'good'))
        self.assertTrue(report['complete'])
        self.assertFalse(report['all_executed_successfully'])
        self.assertEqual([row['exit_code'] for row in report['attempts']], [23, 0])
        self.assertTrue((panel / 'good.visited').is_file())
        self.assertEqual(json.loads((panel / 'execution.json').read_text()), report)
        self.assertEqual(len((panel / 'execution-events.jsonl').read_text().splitlines()), 4)

    def test_panel_output_is_fresh_and_old_receipts_stay_outside(self):
        old = self.arguments['output_dir']
        old.mkdir()
        (old / 'receipt.current.json').write_text('stale')
        first, result = self.run_models(('good',))
        second, _ = self.run_models(('good',))
        self.assertNotEqual(first, second)
        self.assertFalse((first / 'receipt.current.json').exists())
        self.assertEqual((old / 'receipt.current.json').read_text(), 'stale')
        self.assertTrue(result['all_executed_successfully'])
        self.assertFalse(result['artifact_selection'])
        self.assertFalse(result['production_activation'])

    def test_timeout_reaps_child_and_retains_next_backend(self):
        panel, report = self.run_models(('slow', 'good'), timeout_seconds=0.25)
        self.assertEqual([row['status'] for row in report['attempts']], ['timed_out', 'completed'])
        pid = int((panel / 'slow.log').read_text().splitlines()[1])
        if os.name == 'posix':
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_invalid_models_reject_before_launch(self):
        for models in ((), ('good', 'good'), ('../escape',), ('x/y',)):
            with self.subTest(models=models), self.assertRaises(ValueError):
                self.run_models(models)
        self.assertFalse(self.arguments['output_dir'].exists())

    def test_invalid_timeout_rejects_before_launch(self):
        for value in (True, 0, -1, float('nan'), float('inf'), 3601):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_models(('good',), timeout_seconds=value)
        self.assertFalse(self.arguments['output_dir'].exists())

    def test_launch_failure_is_reported_for_each_requested_backend(self):
        with patch('bakeoff_panel.subprocess.Popen', side_effect=OSError('fixture')):
            _, report = self.run_models(('one', 'two'))
        self.assertEqual([r['status'] for r in report['attempts']], ['launch_failed', 'launch_failed'])
        self.assertFalse(report['all_executed_successfully'])

    def test_interrupt_preserves_record_and_does_not_launch_next(self):
        with patch('bakeoff_panel.subprocess.Popen', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_models(('one', 'two'))
        report = json.loads(next(self.arguments['output_dir'].glob('panel-*/execution.json')).read_text())
        self.assertFalse(report['complete'])
        self.assertEqual([r['model'] for r in report['attempts']], ['one'])
        self.assertEqual(report['attempts'][0]['status'], 'interrupted')


class CliTests(unittest.TestCase):
    def setUp(self):
        program = Path(__file__).with_name('decision_cell_bakeoff.py')
        tree = ast.parse(program.read_text())
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'command_all')
        self.state = {'__file__': str(program), 'argparse': argparse, 'Path': Path,
                      'MODEL_SPECS': {'one': {}, 'two': {}},
                      'repository_source': lambda: {'commit': 'same'},
                      'resolved_device': lambda d: d}
        self.calls = []
        self.state['command_summarize'] = lambda a: self.calls.append(('summarize', a.output_dir)) or 0
        self.state['command_verify'] = lambda a: self.calls.append(('verify', a.output_dir)) or 7
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(program), 'exec'), self.state)
        self.args = argparse.Namespace(output_dir=Path('/unused'), model_root=Path('/unused'),
                                       device='cpu', models=['one', 'two'], model_timeout_seconds=5)

    def test_incomplete_panel_never_summarizes_old_receipts(self):
        with patch('bakeoff_panel.run_panel', return_value=(Path('/fresh'), {'all_executed_successfully': False})):
            self.assertEqual(self.state['command_all'](self.args), 1)
        self.assertEqual(self.calls, [])

    def test_complete_panel_verifies_fresh_directory_and_propagates_failure(self):
        with patch('bakeoff_panel.run_panel', return_value=(Path('/fresh'), {'all_executed_successfully': True})):
            self.assertEqual(self.state['command_all'](self.args), 7)
        self.assertEqual(self.calls, [('summarize', Path('/fresh')), ('verify', Path('/fresh'))])
        self.assertEqual(self.args.output_dir, Path('/unused'))

    def test_source_drift_prevents_summary(self):
        with patch('bakeoff_panel.run_panel', return_value=(Path('/fresh'), {'all_executed_successfully': True})):
            with patch.dict(self.state, repository_source=iter(({'commit': 'old'}, {'commit': 'new'})).__next__):
                with self.assertRaisesRegex(RuntimeError, 'source changed'):
                    self.state['command_all'](self.args)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
