"""Receipt binding regressions; no neural or task-quality evidence."""
from copy import deepcopy
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

import five_causal_experiments as c
import shared_gate_cosine_residual as residual
import shared_gate_cosine_residual_trial as legacy
import shared_gate_cosine_residual_trial_v2 as v2


def origins():
    saved, current = {}, {}
    for index, role in enumerate(("heads", "crossed"), start=1):
        base = dict(residual.ORIGINS[role], ready=True,
                    observed_status="completed", observed_conclusion="success",
                    run_attempt=1, artifact_id=100 + index,
                    artifact_sha256=str(index) * 64,
                    metadata_sha256=str(index + 2) * 64)
        saved[role] = base | {"status": "ready_for_saved_feature_readout"}
        current[role] = base | {"status": "ready_for_residual_study",
                                "metadata_sha256": str(index + 4) * 64}
    current["similarity"] = dict(residual.ORIGINS["similarity"], ready=True)
    return saved, current


class OriginReceiptTests(unittest.TestCase):
    def test_different_observation_digests_same_immutable_bytes_are_accepted(self):
        saved, current = origins()
        result = v2.bind_saved_similarity_origins(saved, current)
        self.assertEqual(set(result), {"heads", "crossed"})
        self.assertTrue(all(not row["same_observation_digest"] for row in result.values()))
        self.assertTrue(all(row["artifact_sha256"] == saved[role]["artifact_sha256"]
                            for role, row in result.items()))

    def test_same_observation_digest_is_also_accepted(self):
        saved, current = origins()
        for role in saved:
            current[role]["metadata_sha256"] = saved[role]["metadata_sha256"]
        result = v2.bind_saved_similarity_origins(saved, current)
        self.assertTrue(all(row["same_observation_digest"] for row in result.values()))

    def reject(self, change):
        saved, current = origins(); change(saved, current)
        with self.assertRaises(c.Invalid):
            v2.bind_saved_similarity_origins(saved, current)

    def test_changed_artifact_bytes_rejected(self):
        self.reject(lambda saved, current: current["heads"].update(artifact_sha256="f" * 64))

    def test_changed_artifact_id_rejected(self):
        self.reject(lambda saved, current: current["crossed"].update(artifact_id=999))

    def test_changed_run_source_or_path_rejected(self):
        for field, value in (("run", 1), ("source", "0" * 40), ("path", "other.yml")):
            with self.subTest(field=field):
                self.reject(lambda saved, current, f=field, v=value:
                            current["heads"].update({f: v}))

    def test_invalid_or_missing_metadata_digest_rejected(self):
        self.reject(lambda saved, current: current["heads"].update(metadata_sha256="bad"))
        self.reject(lambda saved, current: saved["crossed"].pop("metadata_sha256"))

    def test_failed_or_unready_origin_rejected(self):
        self.reject(lambda saved, current: current["heads"].update(ready=False))
        self.reject(lambda saved, current: saved["crossed"].update(observed_conclusion="failure"))

    def test_attempt_mismatch_rejected(self):
        self.reject(lambda saved, current: current["heads"].update(run_attempt=2))

    def test_wrapper_installs_only_validator_override(self):
        self.assertIs(legacy.validate_similarity, v2.validate_similarity)
        self.assertTrue(callable(legacy.run))


class EntrypointTests(unittest.TestCase):
    def test_help_from_foreign_directory_without_pythonpath(self):
        script = Path(v2.__file__)
        env = dict(os.environ); env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as directory:
            run = subprocess.run([sys.executable, str(script), "--help"], cwd=directory,
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("dependency", run.stdout)
        self.assertIn("run", run.stdout)
        self.assertNotIn("ModuleNotFoundError", run.stderr)


if __name__ == "__main__":
    unittest.main()
