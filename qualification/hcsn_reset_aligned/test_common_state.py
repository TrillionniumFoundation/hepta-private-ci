"""Actual source-law migration through a reset-aligned, restorable trajectory."""

import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from qualification.hcsn_joint_dde.graded_migration import migrate, migration_weights
from .mesh import aligned_model


class TestCommonCandidateState(unittest.TestCase):
    def setUp(self):
        self.theta = [.01, -.12, .5, math.exp(.66), .15]
        self.geometry = dict(left_intervals=8, right_intervals=24, endpoint=8., grading=1., delay=.2)
        self.model = aligned_model(self.theta, **self.geometry)[0]
        probability = np.zeros(25)
        probability[[0, 16, 20]] = [.6, .2, .2]
        content = np.c_[probability * np.sin(np.arange(25)), probability * np.cos(np.arange(25))]
        weights, _ = migration_weights(self.model.spatial.nodes)
        self.active, self.content, self.phase, self.receipt = migrate(self.model, probability, content, weights)
        self.controls = dict(rtol=2e-11, atol=2e-13, max_step=.01)

    def test_migrated_law_aligned_reset_and_cold_state_obey_dynamic_value(self):
        prefix = self.model.solve([.07, .137], self.active, self.content, self.phase,
                                  export_state=True, **self.controls)
        continued = self.model.solve([.417, 1.], checkpoint=prefix['checkpoint'], **self.controls)
        uninterrupted = self.model.solve([.07, .137, .417, 1.], self.active, self.content,
                                         self.phase, **self.controls)
        actual, expected = continued['rows'][-1], uninterrupted['rows'][-1]
        for field in ('active', 'upper', 'refractory', 'events', 'discounted_events',
                      'discounted_active_time', 'discounted_remaining_phase'):
            np.testing.assert_allclose(actual[field], expected[field], atol=4e-9, rtol=0)
        values, reset_value = self.model.perpetual()
        initial_value = self.active @ values
        for packet in self.phase:
            lo, hi = float(packet.start), float(packet.end)
            mean_discount = math.exp(-self.model.discount*lo) * -math.expm1(-self.model.discount*(hi-lo)) / (self.model.discount*(hi-lo))
            initial_value += float(packet.mass) * mean_discount * reset_value
        terminal = actual['active'][:, 0] @ values[1:-1] + actual['upper'][0]*self.model.active_reward/self.model.discount
        terminal += actual['discounted_remaining_phase'][0] * reset_value
        value = self.model.active_reward*actual['discounted_active_time'][0] + self.model.hit_reward*actual['discounted_events'][0]
        value += math.exp(-self.model.discount) * terminal
        self.assertAlmostEqual(value, initial_value, delta=5e-9)
        self.assertEqual(continued['integration_started_at'], .137)
        self.assertEqual(self.receipt['binding']['schema'], 'hcsn-graded-migration-map-v1')

    def test_parameter_update_cannot_reinterpret_retained_moving_nodes(self):
        prefix = self.model.solve([.137], self.active, self.content, self.phase,
                                  export_state=True, **self.controls)
        changed = list(self.theta)
        changed[3] = math.exp(.67)
        updated = aligned_model(changed, **self.geometry)[0]
        with self.assertRaisesRegex(ValueError, 'binding'):
            updated.solve([.417], checkpoint=prefix['checkpoint'], **self.controls)

    def test_changed_inherited_generator_source_is_rejected_in_new_process(self):
        prefix = self.model.solve([.137], self.active, self.content, self.phase,
                                  export_state=True, **self.controls)
        source_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for package in ('hcsn_joint_dde', 'hcsn_reset_aligned', 'hcsn_boundary_audit'):
                source = source_root / 'qualification' / package
                target = root / 'qualification' / package
                target.mkdir(parents=True)
                for path in source.glob('*.py'):
                    shutil.copyfile(path, target / path.name)
            checkpoint = root / 'before.json'
            checkpoint.write_bytes(prefix['checkpoint'])
            generator = root / 'qualification/hcsn_joint_dde/graded.py'
            generator.write_text(generator.read_text()+'\n# changed inherited implementation source\n')
            script = '''import json
from pathlib import Path
from qualification.hcsn_joint_dde.model import JointModel
from qualification.hcsn_reset_aligned.mesh import ResetAlignedSpatial
raw = Path("before.json").read_bytes()
physics = json.loads(raw)["payload"]["binding"]["physics"].copy()
spatial = ResetAlignedSpatial(**physics.pop("spatial"))
JointModel(spatial=spatial, **physics).solve([.417], checkpoint=raw)
'''
            completed = subprocess.run([sys.executable, '-B', '-c', script], cwd=root,
                env={**os.environ, 'PYTHONPATH': str(root)}, capture_output=True, timeout=30)
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn(b'exact operator binding mismatch', completed.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
