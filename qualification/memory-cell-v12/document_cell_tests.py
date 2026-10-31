"""Lifecycle regressions on explicit fixtures; these are not efficacy evidence."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from document_cell import DocumentCell, Refused, canonical_question


def document(module, owner="team-a"):
    return (f"**Module:** `{module}`\n**Owner:** `{owner}`\n"
            "**Deputy:** `backup-a`\n**Lifecycle:** `active`\n")


def artifact_bytes(owner, artifact):
    directory = owner.root / "artifacts" / artifact
    return {path.name: path.read_bytes() for path in sorted(directory.iterdir())}


class DocumentCellTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "owner"
        self.owner = DocumentCell(self.root)
        self.addCleanup(lambda: self.owner.close())
        for module in ("alpha.one", "beta.two"):
            self.owner.put(document(module), dict(test_fixture=True))

    def test_stage_is_idempotent_after_reopen_without_rewriting_artifact(self):
        candidate = self.owner.fit(["alpha.one", "beta.two"])
        artifact = self.owner.stage(candidate)
        original = artifact_bytes(self.owner, artifact)
        original_mtime = {path.name: path.stat().st_mtime_ns
                          for path in (self.root / "artifacts" / artifact).iterdir()}
        self.assertEqual(self.owner.stage(candidate), artifact)
        self.owner.close()
        self.owner = DocumentCell(self.root)
        self.assertEqual(self.owner.stage(candidate), artifact)
        self.assertEqual(artifact_bytes(self.owner, artifact), original)
        self.assertEqual({path.name: path.stat().st_mtime_ns
                          for path in (self.root / "artifacts" / artifact).iterdir()},
                         original_mtime)
        self.assertEqual(self.owner.publish("fields", artifact), 1)
        answer = self.owner.read("fields", canonical_question("alpha.one"))
        self.assertEqual(answer["fields"],
                         dict(owner="team-a", deputy="backup-a", lifecycle="active"))

    def test_same_name_corruption_is_refused_and_is_not_repaired_by_retry(self):
        candidate = self.owner.fit(["alpha.one", "beta.two"])
        artifact = self.owner.stage(candidate)
        serving = self.root / "artifacts" / artifact / "serving.json"
        changed = bytearray(serving.read_bytes())
        changed[len(changed) // 2] ^= 1
        serving.write_bytes(changed)
        corrupted = artifact_bytes(self.owner, artifact)
        with self.assertRaises(Refused):
            self.owner.stage(candidate)
        self.assertEqual(artifact_bytes(self.owner, artifact), corrupted)
        with self.assertRaises(Refused):
            self.owner.publish("fields", artifact)

    def test_scope_shrink_with_same_codebook_is_an_independent_clean_fit(self):
        parent = self.owner.fit(["alpha.one", "beta.two"])
        child = self.owner.fit(["alpha.one"], seed=19001, initial=parent)
        clean = self.owner.fit(["alpha.one"], seed=19001)
        self.assertEqual(child["codebook"], parent["codebook"])
        self.assertEqual(child["modules"], ["alpha.one"])
        self.assertFalse(child["continuation"])
        self.assertEqual(child["training_receipt"]["initial_optimizer_step"], 0)
        self.assertEqual(child["serving"]["arrays"], clean["serving"]["arrays"])
        self.assertEqual(child["checkpoint"]["optimizer"], clean["checkpoint"]["optimizer"])
        self.assertEqual(child["cut"], self.owner.cut(["alpha.one"]))
        self.assertNotEqual(child["training_receipt"]["initial_parameter_sha256"],
                            parent["serving"]["parameter_sha256"])

    def test_forged_fresh_cut_cannot_publish_stale_learned_answers(self):
        self.owner.put(document("beta.two", "team-b"), dict(test_fixture=True),
                       expected_revision=1)
        candidate = self.owner.fit(["alpha.one", "beta.two"])
        original = self.owner.stage(candidate)
        self.assertEqual(self.owner.publish("fields", original), 1)
        self.owner.put(document("alpha.one", "team-b"), dict(controlled_correction=True),
                       expected_revision=1)
        forged = deepcopy(candidate)
        forged["cut"] = self.owner.cut(forged["modules"])
        forged_artifact = self.owner.stage(forged)
        # Integrity and declared freshness pass; current source reconstruction
        # must independently reject old trained values under fresh metadata.
        self.assertEqual(self.owner.load(forged_artifact)["serving.json"]["cut"],
                         self.owner.cut(candidate["modules"]))
        with self.assertRaisesRegex(Refused, "current source reconstruction"):
            self.owner.publish("fields", forged_artifact)
        selected = dict(self.owner.db.execute("SELECT * FROM releases WHERE cell='fields'").fetchone())
        self.assertEqual(selected, dict(cell="fields", artifact=original, epoch=1))
        with self.assertRaises(Refused):
            self.owner.read("fields", canonical_question("alpha.one"))


if __name__ == "__main__":
    unittest.main()
