"""Controlled integration of real SGD/checkpoint reload with the original runner."""

from dataclasses import asdict
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from . import dual_runtime as runtime
from . import r2_action_value as av
from . import r2_greedy_policy as policy
from . import test_r2_action_value as fixtures
from .test_transition_capture import SyntheticBackend
from .transition_capture import file_identity, write_new


CHILD = """
import json, sys
from pathlib import Path
from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit import dual_runtime as runtime
from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.r2_greedy_policy import DevelopmentGreedy
from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.test_transition_capture import SyntheticBackend
job = json.load(sys.stdin)
assert set(job) == {'request', 'model', 'output'}
output = Path(job['output'])
controller = DevelopmentGreedy(*job['model'], output / 'policy')
backend = SyntheticBackend()
report = runtime.run(runtime.Request(**job['request']), backend, controller, output,
                     horizon=8, deadline_seconds=30, cpu_tariff=0.02, wall_tariff=0.001)
runtime.write_json(output / 'backend_calls.json', backend.calls)
print(json.dumps({'status': report['status'], 'history': report['history']}))
"""


class GreedyPolicyTests(unittest.TestCase):
    evidence_parent = None

    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory() if cls.evidence_parent is None else None
        cls.base = Path(cls.temporary.name if cls.temporary else cls.evidence_parent)
        cls.base.mkdir(parents=True, exist_ok=True)
        helper = fixtures.ActionValueTests()
        helper.root, helper.counter = cls.base / 'training-fixture', 0
        helper.root.mkdir()
        schedules = [('text', 'draft', 'stop'), ('draft', 'text', 'stop'),
                     ('text', 'text', 'draft', 'draft', 'verify', 'refine', 'verify', 'stop'),
                     ('perceive', 'text', 'draft', 'verify', 'revise', 'refine', 'text', 'verify', 'stop'),
                     ('draft', 'revise', 'refine', 'text', 'stop'), ('perceive', 'stop')]
        captures = [helper.capture(actions=actions, horizon=12) for actions in schedules]
        bundle = helper.bundle(captures)
        bundle['config'].update(updates=600, service_tariffs={a: 0.05 for a in runtime.ACTIONS})
        rows = []
        potential = lambda v: 0.4 * (v['text'] is not None) + 0.4 * (v['image_path'] is not None)
        for entry, captured, _ in captures:
            for transition in captured['transitions']:
                after = transition['actual_after_state']
                rows.append({'capture_id': entry['capture_id'], 'step': transition['step'],
                             'transition_sha256': av.digest(transition),
                             'utility_before': potential(transition['before_view']),
                             'utility_after': 0.0 if after['episode_status_so_far'] == 'abstained' else potential(after)})
        bundle['label_manifest'].update(rows=rows, evaluator_id='synthetic-presence-control-not-independent',
            evaluator_source_sha256=file_identity(__file__)['sha256'],
            rubric_sha256=av.digest({'synthetic_potential': '0.4*has_text+0.4*has_image; abstention=0'}))
        bundle['labels_sha256'] = av.digest(bundle['label_manifest'])
        write_new(helper.root / 'BUNDLE.json', bundle)
        cls.fit, report = helper.fit(bundle)
        if report['status'] != 'completed':
            raise RuntimeError(report)
        cls.binding = [str(cls.fit / 'checkpoint.json'), report['checkpoint']['sha256'], report['fit_receipt']['sha256']]

    @classmethod
    def tearDownClass(cls):
        if cls.temporary:
            cls.temporary.cleanup()

    def setUp(self):
        self.root = self.base / self._testMethodName
        self.root.mkdir()
        self.counter = 0
        image = self.root / 'input.png'
        Image.new('RGB', (2, 2), (10, 20, 30)).save(image)
        self.request = runtime.Request('synthetic-greedy-control', str(image), file_identity(image)['sha256'], 'Describe shapes.')
        self.started = time.process_time(), time.perf_counter()
        self.usage = resource.getrusage(resource.RUSAGE_CHILDREN)

    def tearDown(self):
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        write_new(self.root / 'TEST-COST.json', {
            'cpu_seconds': time.process_time() - self.started[0], 'wall_seconds': time.perf_counter() - self.started[1],
            'child_cpu_seconds': usage.ru_utime + usage.ru_stime - self.usage.ru_utime - self.usage.ru_stime,
            'scope': 'test body including runner subsets; shared training fixture and this receipt write are outside',
            'real_model_calls': 0, 'independent_labels': False})

    def execute(self, *, binding=None, controller=None, **kwargs):
        output = self.root / f'episode-{self.counter}'
        self.counter += 1
        greedy = policy.DevelopmentGreedy(*(binding or self.binding), output / 'policy')
        backend = SyntheticBackend()
        report = runtime.run(self.request, backend, controller(greedy) if controller else greedy, output,
                             cpu_tariff=0.02, wall_tariff=0.001, **kwargs)
        write_new(output / 'backend_calls.json', backend.calls)
        return report, greedy, backend

    def test_real_sgd_checkpoint_new_process_runs_original_runtime(self):
        reload = self.root / 'model'
        reload.mkdir()
        for name in ('checkpoint.json', 'FIT.json'):
            shutil.copyfile(self.fit / name, reload / name)
        checkpoint = json.loads((reload / 'checkpoint.json').read_bytes())
        self.assertNotEqual(checkpoint['initial_parameter_sha256'], checkpoint['parameter_sha256'])
        job = {'request': asdict(self.request), 'model': [str(reload / 'checkpoint.json'), *self.binding[1:]],
               'output': str(self.root / 'new-process')}
        write_new(self.root / 'CHILD-INPUT.json', job)
        (self.root / 'child.py').write_text(CHILD)
        result = subprocess.run([sys.executable, '-B', '-c', CHILD], input=json.dumps(job), text=True,
                                capture_output=True, timeout=45)
        (self.root / 'child.stdout').write_text(result.stdout)
        (self.root / 'child.stderr').write_text(result.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((Path(job['output']) / 'report.json').read_bytes())
        self.assertIn(report['status'], ('delivered', 'abstained', 'incomplete'))
        self.assertTrue(any(a in ('text', 'draft', 'refine', 'perceive', 'revise') for a, _ in report['history']))
        predictor = av.ActionValue(*job['model'])
        rows = [json.loads(p.read_bytes()) for p in sorted((Path(job['output']) / 'policy').glob('decision-*.json'))]
        controllers = [event for event in report['events'] if event['action'] == 'controller']
        for row, event in zip(rows, controllers, strict=True):
            self.assertLessEqual(row['prediction_calls'], 7)
            self.assertLessEqual(row['metering']['wall_seconds'], event['wall_seconds'])
            for candidate in row['candidates']:
                if candidate['status'] == 'scored':
                    self.assertEqual(candidate['predicted_one_step_net_gain'], predictor.predict(row['view'], candidate['action']))
            if row['choice'] != 'stop':
                self.assertGreater(next(c['predicted_one_step_net_gain'] for c in row['candidates'] if c['selected']), 0)

    def test_refine_keeps_old_draft_after_public_plan_invalidation(self):
        class Prefix:
            def __init__(self, greedy): self.greedy = greedy
            def choose(self, view):
                return ('draft', 'revise')[len(view.history)] if len(view.history) < 2 else self.greedy.choose(view)
        def scores(model, view, action):
            return 0.4 if len(view.history) == 2 and action == 'refine' else -0.2
        with patch.object(av.ActionValue, 'predict', scores):
            report, greedy, backend = self.execute(controller=Prefix, horizon=5)
        self.assertEqual(report['history'], [('draft', 'ok'), ('revise', 'ok'), ('refine', 'ok'), ('stop', 'ok')])
        self.assertIsNone(greedy.decisions[0]['view']['image_path'])
        self.assertEqual([call[-1] for call in backend.calls if call[0] == 'draw'], [None, '00-draft.png'])
        write_new(self.root / 'FAULT.json', {'synthetic_score_injection': 'refine=0.4 only after draft/revise; others=-0.2'})

    def test_unknown_legal_action_is_null_and_blocks_even_known_positive_gain(self):
        helper = fixtures.ActionValueTests()
        helper.root, helper.counter = self.root / 'partial-training', 0
        helper.root.mkdir()
        capture = helper.capture(actions=('text', 'stop'))
        bundle = helper.bundle([capture])
        fit, receipt = helper.fit(bundle)
        self.assertEqual(receipt['status'], 'completed')
        binding = [str(fit / 'checkpoint.json'), receipt['checkpoint']['sha256'], receipt['fit_receipt']['sha256']]
        report, greedy, backend = self.execute(binding=binding)
        row = greedy.decisions[0]
        self.assertEqual((report['status'], row['choice'], row['status']), ('abstained', 'stop', 'fallback'))
        self.assertIn('unknown_legal_action', row['reason'])
        self.assertGreater(next(c['predicted_one_step_net_gain'] for c in row['candidates'] if c['action'] == 'text'), 0)
        self.assertTrue(all(c['predicted_one_step_net_gain'] is None for c in row['candidates'] if c['status'] == 'unknown_untrained_action'))
        self.assertFalse(any(call[0] in ('describe', 'draw') for call in backend.calls))

    def test_strict_positive_ties_stop_scoring_and_call_bound(self):
        for value, expected in ((0.0, 'stop'), (-0.2, 'stop'), (0.2, 'perceive')):
            with patch.object(av.ActionValue, 'predict', return_value=value) as predict:
                report, greedy, _ = self.execute(horizon=1)
            self.assertEqual(report['history'], [(expected, 'ok')])
            self.assertEqual(predict.call_count, greedy.decisions[0]['prediction_calls'])
            self.assertLessEqual(predict.call_count, 7)
        with patch.object(av.ActionValue, 'predict', lambda model, view, a: 0.8 if a == 'stop' else 0.2):
            report, _, _ = self.execute(horizon=1)
        self.assertEqual(report['history'], [('stop', 'ok')])
        write_new(self.root / 'FAULT.json', {'synthetic_score_injections': [0.0, -0.2, 0.2, 'stop=0.8; others=0.2']})

    def test_failed_and_late_scoring_retains_work_without_generator_dispatch(self):
        def failing(model, view, action):
            if action == 'text': raise FloatingPointError('injected second-score failure')
            return 0.3
        with patch.object(av.ActionValue, 'predict', failing):
            report, greedy, backend = self.execute()
        row = greedy.decisions[0]
        self.assertEqual((row['status'], row['choice'], row['reason']), ('fallback', 'stop', 'prediction_failed'))
        self.assertEqual([c['status'] for c in row['candidates'][:2]], ['scored', 'prediction_failed'])
        self.assertTrue(all(c['prediction_metering']['wall_seconds'] >= 0 for c in row['candidates'] if c['prediction_metering']))
        self.assertFalse(any(call[0] in ('describe', 'draw') for call in backend.calls))
        real, offset = runtime.time, [0.0]
        clock = SimpleNamespace(process_time=real.process_time, perf_counter=lambda: real.perf_counter() + offset[0])
        def late(model, view, action):
            offset[0] = 100.0  # Deadline fault only; not measured latency.
            return 0.3
        with patch.object(runtime, 'time', clock), patch.object(av.ActionValue, 'predict', late):
            report, greedy, backend = self.execute(deadline_seconds=60)
        self.assertEqual((report['status'], report['history']), ('timeout', []))
        self.assertTrue(greedy.decisions[0]['prediction_calls'])
        self.assertFalse(any(call[0] in ('describe', 'draw') for call in backend.calls))
        write_new(self.root / 'FAULT.json', {'synthetic_injections': ['second-score failure', 'runtime wall clock +100s after scoring'], 'not_physical_latency': True})

    def test_bad_fit_pin_and_trace_failure_fence_before_any_generation(self):
        report, greedy, backend = self.execute(binding=[*self.binding[:2], '0' * 64])
        self.assertEqual((report['status'], greedy.decisions[0]['prediction_calls']), ('failed', 0))
        self.assertFalse(any(call[0] in ('describe', 'draw') for call in backend.calls))
        original = policy.write_new
        def fail_header(path, value):
            if Path(path).name == 'POLICY.json': raise OSError('injected trace initialization failure')
            return original(path, value)
        with patch.object(policy, 'write_new', fail_header):
            report, greedy, backend = self.execute()
        self.assertEqual(report['status'], 'failed')
        with self.assertRaisesRegex(ValueError, 'fenced'):
            greedy.choose(runtime.View('Describe shapes.', 'Describe shapes.', 0, None, None, '', (), 10, 60))
        self.assertFalse(any(call[0] in ('describe', 'draw') for call in backend.calls))
        write_new(self.root / 'FAULT.json', {'synthetic_injections': ['wrong FIT pin', 'POLICY.json write failure']})


if __name__ == '__main__':
    unittest.main()
