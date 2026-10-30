"""Real tiny measured supervisors; all primary completions here are synthetic."""

import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest import mock

from . import wait4_launcher as launcher


class Wait4LauncherTests(unittest.TestCase):
    def setUp(self):
        target = os.environ.get('HEPTA_SUPERVISOR_TEST_OUTPUT')
        if target:
            self.base = Path(target)/self._testMethodName; self.base.mkdir(parents=True, exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(prefix='hepta-outer-fixture-'); self.addCleanup(temporary.cleanup); self.base = Path(temporary.name)
        self.ops = self.base/'ops'; self.ops.mkdir()
        self.cwd = self.base/'empty'; self.cwd.mkdir()
        self.directory = self.ops/'wait4_launcher'
        (self.base/'SYNTHETIC_TEST_FIXTURE.json').write_text(json.dumps({'scientific_tasks_executed': 0,
            'scope': 'Only tiny local stdlib subprocesses; any primary completion in this case is synthetic.'})+'\n')

    def config(self, code):
        script = self.base/'tiny_supervisor.py'; script.write_text(code)
        config = {'python': sys.executable, 'source_root': str(Path(__file__).resolve().parents[2]),
                  'ops_root': str(self.ops), 'empty_cwd': str(self.cwd),
                  'descriptors': {'own_supervisor': launcher.archive.descriptor(script)}}
        item = launcher.archive.write_json(self.base/'CONFIG.json', config)
        return config, item

    def closure(self):
        value = json.loads((self.directory/'owned_supervisor/CLOSURE.json').read_text())
        self.assertEqual((value['attempt_count'], value['returned_children']), (1, 1))
        self.assertTrue(value['all_returned_direct_children_reaped'])
        self.assertTrue(value['accounting_complete_for_attempted_direct_workers'])
        self.assertFalse(Path('/proc/%d' % value['children'][0]['pid']).exists())
        return value

    def test_success_wait4_nested_cost_and_new_session(self):
        code = "import json,pathlib\np=pathlib.Path(%r)\np.write_text(json.dumps({'schema':'hepta.fullstudy.pipeline-completion.4','complete':True,'synthetic_test_fixture':True})+'\\n')\n" % str(self.ops/'COMPLETE.json')
        config, item = self.config(code)
        result = launcher.run_measured(config, item, self.directory)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['argv'], launcher.supervisor_argv(config, item))
        identity = result['child_identity']
        self.assertEqual(identity['pid'], identity['pgid']); self.assertEqual(identity['pid'], identity['sid'])
        closure = self.closure()
        self.assertEqual(result['total_cpu_seconds_inclusive'], closure['children'][0]['wait4']['cpu_seconds'])
        self.assertGreater(result['total_cpu_seconds_inclusive'], 0)
        self.assertEqual(result['primary_complete'], launcher.archive.descriptor(self.ops/'COMPLETE.json'))
        self.assertEqual(result, json.loads((self.directory/'WAIT4_COMPLETE.json').read_text()))

    def test_nonzero_exit_is_recorded_without_retry(self):
        config, item = self.config('raise SystemExit(7)\n')
        result = launcher.run_measured(config, item, self.directory)
        self.assertEqual(result['exit_code'], 7)
        self.assertNotIn('primary_complete', result)
        self.closure()

    def test_actual_signal_wait_status_preserved(self):
        config, item = self.config('import os,signal\nsignal.signal(signal.SIGTERM,signal.SIG_DFL)\nos.kill(os.getpid(),signal.SIGTERM)\n')
        result = launcher.run_measured(config, item, self.directory)
        self.assertEqual(result['exit_code'], -signal.SIGTERM)
        self.assertTrue(os.WIFSIGNALED(result['wait_status']))
        self.assertEqual(os.WTERMSIG(result['wait_status']), signal.SIGTERM)
        self.closure()

    def test_start_publication_failure_still_has_real_wait4_and_preserves_error(self):
        config, item = self.config('import time\ntime.sleep(30)\n')
        original = OSError('synthetic outer START publication failure')
        write = launcher.archive.write_json
        def fail(path, value, **kwargs):
            if Path(path) == self.directory/'START.json':
                raise original
            return write(path, value, **kwargs)
        with mock.patch.object(launcher.archive, 'write_json', fail):
            with self.assertRaises(OSError) as caught:
                launcher.run_measured(config, item, self.directory)
        self.assertIs(caught.exception, original)
        closure = self.closure()
        failure = json.loads((self.directory/'LAUNCH_FAILED.json').read_text())
        self.assertEqual(failure['returned_supervisor_wait4'], closure['children'][0]['wait4'])
        self.assertFalse(failure['construction_cost_unknown_unless_recorded_in_owned_closure'])
        self.assertFalse((self.directory/'WAIT4_COMPLETE.json').exists())

    def test_zero_exit_invalid_primary_preserves_measured_cost_without_completion_claim(self):
        config, item = self.config('pass\n')
        with self.assertRaises(FileNotFoundError):
            launcher.run_measured(config, item, self.directory)
        closure = self.closure()
        record = json.loads((self.directory/'WAIT4_PRIMARY_INVALID.json').read_text())
        self.assertEqual(record['exit_code'], 0)
        self.assertFalse(record['primary_completion_verified'])
        self.assertEqual(record['total_cpu_seconds_inclusive'], closure['children'][0]['wait4']['cpu_seconds'])
        self.assertFalse((self.directory/'WAIT4_COMPLETE.json').exists())


if __name__ == '__main__':
    unittest.main()
