"""Concrete source-integrity, snapshot semantics and real Git predicate checks."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from urllib.parse import urlencode

from event_experience import question
from event_projection import EventProjection, Lookup
from external_git_projection import load_receipt
from external_git_trial import documents, verify_procedure
from select_prospective_sources import metadata_pairs


ROOT = Path(__file__).resolve().parent
RECEIPT = ROOT / "calibration-git-capture/nushell__nushell/source-receipt.json"


class ExternalGitProfileTests(unittest.TestCase):
    def test_bounded_primary_metadata_first_parent_order_and_window_binding(self):
        repo = "llvm/llvm-project"
        window = ("2026-10-12T16:05:00Z", "2026-10-20T00:00:00Z")
        rows = json.loads((ROOT / "v2-llvm__llvm-project-commits.json").read_text())
        wrapper = dict(schema="hepta.external-git-event.api-capture.v1", repository=repo,
            request_url="https://api.github.com/repos/" + repo + "/commits?" + urlencode(
                dict(since=window[0], until=window[1], per_page=32)),
            completed_at="2026-10-21T09:00:00+00:00", response=rows)
        pairs = metadata_pairs(repo, 0, wrapper, window)
        self.assertEqual(pairs[0]["current_sha"], "34acb4f973d920e091af32882fdf800bee589b8b")
        self.assertEqual(pairs[0]["previous_sha"], "46dad3d4cc704ddf59172f17234aeb25736dd0ea")
        with self.assertRaisesRegex(ValueError, "32-commit census"):
            metadata_pairs(repo, 0, wrapper | {"response": rows + [rows[0]]}, window)
        with self.assertRaisesRegex(ValueError, "closed precommitted window"):
            metadata_pairs(repo, 0, wrapper | {"completed_at": "2026-10-19T09:00:00+00:00"}, window)

    def test_original_timestamp_and_byte_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for source in RECEIPT.parent.iterdir():
                if source.is_file():
                    shutil.copyfile(source, target / source.name)
            path = target / "source-receipt.json"
            load_receipt(path)
            record = json.loads(path.read_text())
            record["entry"]["current_date"] = "2026-10-16T11:53:13Z"
            path.write_text(json.dumps(record))
            with self.assertRaisesRegex(ValueError, "committer date"):
                load_receipt(path)
            shutil.copyfile(RECEIPT, path)
            raw = target / "current-commit.raw"
            raw.write_bytes(raw.read_bytes() + b"altered")
            with self.assertRaisesRegex(ValueError, "byte identity"):
                load_receipt(path)

    def test_actual_git_success_predicate_differs_from_zero_exit(self):
        labels = json.loads((ROOT / "calibration-projection-v3/labels.json").read_text())
        label = next(item for item in labels if item["kind"] == "procedure")
        procedure = label["procedure"]
        correct = verify_procedure(procedure, label["expected"])
        wrong_identifier = next(mode for mode in procedure["modes"] if mode != label["expected"])
        wrong = verify_procedure(procedure, wrong_identifier)
        unknown = verify_procedure(procedure, "mode_00000000")
        self.assertEqual((correct["exit_code"], wrong["exit_code"]), (0, 0))
        self.assertTrue(correct["predicate_success"])
        self.assertFalse(wrong["predicate_success"])
        self.assertFalse(unknown["executed"])

    def test_real_calibration_projections_obey_snapshot_and_path_semantics(self):
        inputs = ROOT / "calibration-projection-v3"
        source = documents(json.loads((inputs / "sources.json").read_text()))
        specs = json.loads((inputs / "questions.json").read_text())
        support = json.loads((inputs / "program-support.json").read_text())
        self.assertEqual(len(source), 88)
        self.assertEqual(len(specs), 8)
        for spec in specs:
            scoped = tuple(d for d in source.values() if d.scope == spec["id"])
            proj = EventProjection(scoped)
            _, lookup = question(spec, "2026-10-21T10:00:00Z")
            candidates = tuple(d.identity for d in scoped)
            organized, _ = proj.select(lookup, candidates, mode="organized", revoked=set())
            self.assertEqual(set(organized), set(support[spec["id"]]))
            for key in organized:
                self.assertLessEqual(proj.facts[key]["revision"], spec["revision"])
            if len(spec["path"]) == 2:
                first, _ = proj.select(Lookup(lookup.entity, (lookup.path[0],), lookup.revision),
                                       candidates, mode="entity_time", revoked=set())
                self.assertNotEqual(set(first), set(organized))


if __name__ == "__main__":
    unittest.main()
