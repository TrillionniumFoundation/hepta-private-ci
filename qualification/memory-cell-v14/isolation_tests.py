"""Integration checks of trained artifacts and failure/restart boundaries."""

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from isolation import Adapter, IsolatedMemory, Refused, canonical, dataset, sha, tasks
from isolation_experiment import payload


INPUTS = Path(__file__).resolve().parent.parent / "memory-cell-v13/evidence/inputs"


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.encoder = json.loads((INPUTS / "encoder_manifest.json").read_text())["encoder_hash"]
        self.memory = IsolatedMemory(self.temp.name, "test-scope", self.encoder)
        self.X, self.rows = dataset(INPUTS, "train")
        self.memory.put("skill", "skills", payload(INPUTS, "train"), expected_revision=0)
        self.initial = self.memory.fit_publish("skill", "skills", INPUTS, "calibration")
        self.assertEqual(self.initial["status"], "published")

    def tearDown(self):
        self.memory.close()
        self.temp.cleanup()

    def read(self, kind="skill", key="skills", scope="test-scope", encoder=None):
        return self.memory.read(kind, key, self.X[:2], scope=scope,
                                encoder_hash=self.encoder if encoder is None else encoder)

    def project(self, frontier):
        event = tasks.resolve_profile(tasks.profile_journal(), "amber", frontier)
        prior = self.memory.owner.source("test-scope", "project:amber")
        self.memory.put("project", "amber", payload(INPUTS, f"profile-{frontier}-train", "amber", event),
                        expected_revision=prior["revision"] if prior else 0)

    def test_rejected_correction_falls_back_without_disabling_skill(self):
        before = self.read()
        self.project(3)
        self.assertEqual(self.read("project", "amber")["mode"], "fallback")
        installed = self.memory.fit_publish("project", "amber", INPUTS, "profile-3-calibration")
        self.assertEqual((installed["status"], self.read("project", "amber")["mode"]), ("published", "learned"))
        self.project(4)
        rejected = self.memory.fit_publish("project", "amber", INPUTS, "profile-4-calibration", steps=1, lr=1e-6)
        actual = self.read("project", "amber")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual((actual["mode"], actual["predictions"], actual["source_revision"]),
                         ("fallback", [tasks.SKILLS.index("sort_numeric")] * 2, 2))
        after = self.read()
        self.assertEqual((before["artifact"], before["predictions"]), (after["artifact"], after["predictions"]))
        source, current = self.memory._source("project", "amber")
        self.memory.put("project", "amber", current, expected_revision=source["revision"], active=False)
        self.assertEqual((self.read("project", "amber")["mode"], self.read()["mode"]), ("refused", "learned"))

    def test_request_and_source_identity_cannot_trigger_fallback(self):
        for request in (("skill", "skills", "wrong", self.encoder),
                        ("skill", "skills", "test-scope", "0" * 64),
                        ("project", "project:amber", "test-scope", self.encoder),
                        ("other", "skills", "test-scope", self.encoder)):
            self.assertEqual(self.read(*request)["mode"], "refused")
        self.project(3)
        # Explicit source-corruption injection, never a successful publication.
        source = self.memory.owner.source("test-scope", "project:amber")
        changed = json.loads(source["body"])
        changed["kind"] = "skill"
        self.memory.owner.put("test-scope", "project:amber", canonical(changed).decode(), expected_revision=1)
        self.assertEqual(self.read("project", "amber")["mode"], "refused")

    def test_mixed_training_ancestor_cannot_drop_project_dependency(self):
        self.project(3)
        cut, _ = self.memory.owner.snapshot("test-scope", ["skills", "project:amber"])
        XP, rows = dataset(INPUTS, "profile-3-train")
        ids = [i for i, r in enumerate(rows) if r["project"] == "amber"]
        X = np.vstack([self.X, XP[ids]])
        y = np.asarray([r["label"] for r in self.rows] + [rows[i]["label"] for i in ids])
        mixed = Adapter(384, len(tasks.SKILLS), 8, 713, encoder_hash=self.encoder, source_version=sha(canonical(cut)))
        mixed.train(X, y, steps=3, data_id="actual-mixed-training", source_version=sha(canonical(cut)))
        ancestor = self.memory.owner.stage("test-scope", cut, mixed)
        skill_cut = self.memory.owner.cut("test-scope", ["skills"])
        mixed.source_version = sha(canonical(skill_cut))
        with self.assertRaisesRegex(Refused, "discard fitted source dependencies"):
            self.memory.owner.stage("test-scope", skill_cut, mixed, parent_artifact=ancestor)

    def test_rejected_skill_candidate_keeps_previous_valid_release(self):
        before = self.read()
        rejected = self.memory.fit_publish("skill", "skills", INPUTS, "calibration", steps=1, lr=1e-6)
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual((self.read()["artifact"], self.read()["predictions"]), (before["artifact"], before["predictions"]))

    def test_restart_preserves_full_state_and_future_updates(self):
        artifact = self.initial["artifact"]
        expected, _ = self.memory.owner.load(artifact, "test-scope", self.encoder)
        self.memory.close()
        self.memory = IsolatedMemory(self.temp.name, "test-scope", self.encoder)
        actual, _ = self.memory.owner.load(artifact, "test-scope", self.encoder)
        self.assertEqual(expected.state_hash(), actual.state_hash())
        for model in (expected, actual):
            model.train(self.X, np.asarray([r["label"] for r in self.rows]), steps=7,
                        data_id=model.sampler["data_id"], source_version=model.source_version)
        self.assertEqual(expected.state_hash(), actual.state_hash())
        self.assertEqual(self.read()["artifact"], artifact)


if __name__ == "__main__":
    unittest.main()
