"""Real learned-state lifecycle checks; fixtures do not establish language gains."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from adapter import Adapter
from lifecycle import Refused, SourceOwner, canonical, sha


BASE = sha(b"explicit synthetic encoder identity for behavior tests")
X = np.eye(8, 384, dtype=np.float32)
Y = np.asarray([0, 0, 1, 1, 0, 1, 0, 1], dtype=np.int64)


def body(labels):
    return canonical(dict(labels=labels.tolist(), features_sha256=sha(X.tobytes()))).decode()


def validate(model, records):
    expected = json.loads(records[0]["body"])["labels"]
    return dict(passed=model.predict(X).tolist() == expected, queries=len(X),
                scope="synthetic known-feature classification; no semantic efficacy claim")


def fit(owner, labels=Y, initial=None):
    cut, _ = owner.snapshot("scope-a", ["facts"])
    version = sha(canonical(cut))
    model = initial.clone() if initial is not None else Adapter(
        num_classes=2, rank=4, seed=73, encoder_hash=BASE, source_version=version)
    model.train(X, labels, steps=80, batch_size=4, data_id=sha(labels.tobytes()),
                source_version=version, allow_data_change=initial is not None)
    return model, cut


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.owner = SourceOwner(self.tmp.name)
        self.owner.put("scope-a", "facts", body(Y), expected_revision=0)
        self.model, self.cut = fit(self.owner)
        self.artifact = self.owner.stage("scope-a", self.cut, self.model)

    def tearDown(self):
        self.owner.close()
        self.tmp.cleanup()

    def publish(self, artifact=None, epoch=0):
        return self.owner.publish("scope-a", "memory", artifact or self.artifact, BASE,
                                  expected_epoch=epoch, validator=validate)

    def test_complete_model_publication_cold_read_and_idempotent_staging(self):
        self.assertEqual(self.artifact, self.owner.stage("scope-a", self.cut, self.model))
        with self.assertRaises(Refused):
            self.owner.read("scope-a", "memory", X, BASE)
        self.publish()
        before = self.owner.read("scope-a", "memory", X, BASE)
        self.assertEqual(before["predictions"], Y.tolist())
        self.owner.close()
        self.owner = SourceOwner(self.tmp.name)
        self.assertEqual(self.owner.read("scope-a", "memory", X, BASE), before)
        restored, _ = self.owner.load(self.artifact, "scope-a", BASE)
        self.assertEqual(restored.state_hash(), self.model.state_hash())
        with self.assertRaises(Refused):
            self.publish(epoch=0)

    def test_correction_fences_old_reads_rejects_relabelled_weights_and_preserves_other_answers(self):
        self.publish()
        changed = Y.copy()
        changed[0] = 1 - changed[0]
        self.owner.put("scope-a", "facts", body(changed), expected_revision=1)
        with self.assertRaises(Refused):
            self.owner.read("scope-a", "memory", X, BASE)
        with self.assertRaises(Refused):
            self.publish(epoch=1)
        new_cut, _ = self.owner.snapshot("scope-a", ["facts"])
        forged = self.model.clone()
        forged.source_version = sha(canonical(new_cut))
        forged_artifact = self.owner.stage("scope-a", new_cut, forged, parent_artifact=self.artifact)
        with self.assertRaises(Refused):
            self.publish(forged_artifact, epoch=1)
        updated, cut = fit(self.owner, changed, self.model)
        artifact = self.owner.stage("scope-a", cut, updated, parent_artifact=self.artifact)
        self.publish(artifact, epoch=1)
        self.assertEqual(self.owner.read("scope-a", "memory", X, BASE)["predictions"], changed.tolist())
        self.owner.put("scope-a", "unrelated", "unrelated text", expected_revision=0)
        self.assertEqual(self.owner.read("scope-a", "memory", X, BASE)["predictions"], changed.tolist())
        self.owner.put("scope-a", "facts", body(changed), expected_revision=2, active=False)
        with self.assertRaises(Refused):
            self.owner.read("scope-a", "memory", X, BASE)
        with self.assertRaises(Refused):
            self.publish(artifact, epoch=2)

    def test_scope_encoder_and_immutable_bytes_are_checked(self):
        self.publish()
        with self.assertRaises(Refused):
            self.owner.load(self.artifact, "scope-b", BASE)
        with self.assertRaises(Refused):
            self.owner.read("scope-b", "memory", X, BASE)
        with self.assertRaises(Refused):
            self.owner.stage("scope-b", self.cut, self.model)
        with self.assertRaises(Refused):
            self.owner.load(self.artifact, "scope-a", "0" * 64)
        self.owner.put("scope-a", "extra", "new scope", expected_revision=0)
        expanded, _ = self.owner.snapshot("scope-a", ["facts", "extra"])
        inherited = self.model.clone()
        inherited.source_version = sha(canonical(expanded))
        expanded_artifact = self.owner.stage("scope-a", expanded, inherited, parent_artifact=self.artifact)
        with self.assertRaises(Refused):
            self.owner.stage("scope-a", self.cut, self.model, parent_artifact=expanded_artifact)
        path = Path(self.tmp.name) / "artifacts" / self.artifact / "model.npz"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(Refused):
            self.owner.read("scope-a", "memory", X, BASE)
        with self.assertRaises(Refused):
            self.owner.stage("scope-a", self.cut, self.model)

    @unittest.skipUnless(sys.platform.startswith("linux"), "actual SIGKILL contract uses Linux")
    def test_real_sigkill_before_and_after_publication_commit(self):
        for boundary in ("before_commit", "after_commit"):
            with self.subTest(boundary=boundary):
                child = subprocess.run([sys.executable, __file__, "crash", self.tmp.name,
                                        self.artifact, boundary], capture_output=True, text=True)
                self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr)
                self.owner.close()
                self.owner = SourceOwner(self.tmp.name)
                if boundary == "before_commit":
                    with self.assertRaises(Refused):
                        self.owner.read("scope-a", "memory", X, BASE)
                else:
                    result = self.owner.read("scope-a", "memory", X, BASE)
                    self.assertEqual(result["predictions"], Y.tolist())
                    self.assertEqual(result["epoch"], 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "crash":
        owner = SourceOwner(sys.argv[2])
        def kill(boundary):
            if boundary == sys.argv[4]:
                os.kill(os.getpid(), signal.SIGKILL)
        owner.publish("scope-a", "memory", sys.argv[3], BASE, expected_epoch=0,
                      validator=validate, boundary_hook=kill)
    else:
        unittest.main()
