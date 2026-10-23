"""Actual temporary-file mutations, not real checkpoint or model acceptance."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from artifact_guard import SnapshotGuard
from bakeoff import EvidenceError
import run_models
from run_models import laya_calibration_identity, laya_scores, runtime_identity


class FrozenArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'models--test--model' / 'snapshots' / ('a' * 40)
        self.root.mkdir(parents=True)
        (self.root / 'tokenizer_config.json').write_text('{"original": true}')
        (self.root / 'model.safetensors').write_bytes(b'original weights')

    def test_runtime_copy_is_independent_and_identical(self):
        with SnapshotGuard(self.root) as guard:
            self.assertEqual((guard.path / 'model.safetensors').read_bytes(), b'original weights')
            self.assertNotEqual(guard.path, self.root)
            self.assertEqual(guard.path.name, self.root.name)
            guard.verify('unchanged')
        self.assertFalse(guard.path.exists())

    def test_runtime_mutation_rejected_and_original_preserved(self):
        with self.assertRaisesRegex(EvidenceError, 'runtime copy artifact drift'):
            with SnapshotGuard(self.root) as guard:
                (guard.path / 'tokenizer_config.json').write_text('{"rewritten": true}')
                guard.verify('after load')
        self.assertEqual((self.root / 'tokenizer_config.json').read_text(), '{"original": true}')

    def test_original_mutation_rejected(self):
        with self.assertRaisesRegex(EvidenceError, 'frozen source artifact drift'):
            with SnapshotGuard(self.root) as guard:
                (self.root / 'model.safetensors').write_bytes(b'tampered')
                guard.verify('after inference')

    def test_added_removed_config_files_are_rejected(self):
        for operation in ('add', 'remove'):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(EvidenceError, 'artifact drift'):
                    with SnapshotGuard(self.root) as guard:
                        if operation == 'add':
                            (guard.path / 'config.json').write_text('{}')
                        else:
                            (guard.path / 'tokenizer_config.json').unlink()

    def test_mutating_sdk_stops_before_first_forward(self):
        called = []
        def load(path, **kwargs):
            (Path(path) / 'tokenizer_config.json').write_text('{"sdk_patch": true}')
            return types.SimpleNamespace(predict=lambda *_: called.append('forward'))
        with patch.dict(sys.modules, {'laya': types.SimpleNamespace(load=load)}):
            with self.assertRaisesRegex(EvidenceError, 'after Laya load: runtime copy artifact drift'):
                with SnapshotGuard(self.root) as guard:
                    laya_scores(guard.path, [], 'cpu', guard)
        self.assertEqual(called, [])
        self.assertEqual((self.root / 'tokenizer_config.json').read_text(), '{"original": true}')

    def test_external_symlink_is_rejected(self):
        external = Path(self.temp.name) / 'external.json'
        external.write_text('{}')
        (self.root / 'config.json').symlink_to(external)
        with self.assertRaisesRegex(EvidenceError, 'escaped snapshot file'):
            SnapshotGuard(self.root)


class LayaCalibrationTests(unittest.TestCase):
    def agent(self):
        return types.SimpleNamespace(temperature_raw=[1.0, 1.0, 1.0],
            temperature=[1.0, 1.0, 1.0], temperature_by_options_raw={'choice:2': 1.0},
            temperature_by_options={'choice:2': 1.0})

    def test_unchanged_calibration_has_stable_identity(self):
        a, b = self.agent(), self.agent()
        self.assertEqual(laya_calibration_identity(a), laya_calibration_identity(b))
        b.temperature_by_options_raw['choice:2'] = 2.0
        b.temperature_by_options['choice:2'] = 2.0
        self.assertNotEqual(laya_calibration_identity(a), laya_calibration_identity(b))

    def test_publisher_temperature_clamp_is_rejected(self):
        a = self.agent()
        a.temperature_by_options_raw['choice:11+'] = 0.10058280825614929
        a.temperature_by_options['choice:11+'] = 0.5
        with self.assertRaisesRegex(EvidenceError, 'altered publisher calibration'):
            laya_calibration_identity(a)

    def test_missing_and_invalid_calibration_fail_closed(self):
        with self.assertRaisesRegex(EvidenceError, 'does not expose'):
            laya_calibration_identity(types.SimpleNamespace())
        for value in (True, float('nan'), float('inf'), 0, -1):
            a = self.agent()
            a.temperature_raw[0] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(EvidenceError, 'calibration value'):
                    laya_calibration_identity(a)

    def test_invalid_effective_values_cannot_equal_publisher_numbers(self):
        for value in (True, float('nan'), float('inf'), 0, -1):
            a = self.agent()
            a.temperature[0] = value
            with self.subTest(value=value):
                with self.assertRaisesRegex(EvidenceError, 'effective calibration value'):
                    laya_calibration_identity(a)
        a = self.agent()
        a.temperature_by_options = {'choice:2': True}
        with self.assertRaisesRegex(EvidenceError, 'effective calibration value'):
            laya_calibration_identity(a)

    def test_invalid_effective_profile_schema_is_rejected(self):
        a = self.agent()
        a.temperature = None
        with self.assertRaisesRegex(EvidenceError, 'effective calibration schema'):
            laya_calibration_identity(a)
        a = self.agent()
        a.temperature_by_options = {2: 1.0}
        with self.assertRaisesRegex(EvidenceError, 'effective calibration schema'):
            laya_calibration_identity(a)

    def test_runtime_identity_changes_when_only_a_helper_changes(self):
        original_hash = run_models.file_hash
        baseline = runtime_identity()
        for helper in ('artifact_guard.py', 'retrieval.py', 'bakeoff.py'):
            def changed(path):
                return 'e' * 64 if path.name == helper else original_hash(path)
            with self.subTest(helper=helper):
                with patch.object(run_models, 'file_hash', side_effect=changed):
                    self.assertNotEqual(runtime_identity(), baseline)


if __name__ == '__main__':
    unittest.main()
