"""Concrete source-integrity, snapshot semantics and real Git predicate checks."""

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from urllib.parse import urlencode

from event_experience import question
from event_projection import EventProjection, Lookup

from external_git_projection import PRECOMMIT_SHA, load_receipt, verify_admission
from external_git_trial import documents, verify_procedure
from select_prospective_sources import metadata_pairs

ROOT = Path(__file__).resolve().parent
RECEIPT = ROOT / "calibration-git-capture/nushell__nushell/source-receipt.json"


class ExternalGitProfileTests(unittest.TestCase):
    def test_bounded_primary_metadata_first_parent_order_and_window_binding(self):
        repo = "llvm/llvm-project"
        window = ("2026-10-12T16:05:00Z", "2026-10-20T00:00:00Z")
        rows = json.loads((ROOT / "v2-llvm__llvm-project-commits.json").read_text())
        wrapper = dict(
            schema="hepta.external-git-event.api-capture.v1",
            repository=repo,
            request_url="https://api.github.com/repos/"
            + repo
            + "/commits?"
            + urlencode(dict(since=window[0], until=window[1], per_page=32)),
            completed_at="2026-10-21T09:00:00+00:00",
            response=rows,
        )
        pairs = metadata_pairs(repo, 0, wrapper, window)
        self.assertEqual(
            pairs[0]["current_sha"], "34acb4f973d920e091af32882fdf800bee589b8b"
        )
        self.assertEqual(
            pairs[0]["previous_sha"], "46dad3d4cc704ddf59172f17234aeb25736dd0ea"
        )
        with self.assertRaisesRegex(ValueError, "32-commit census"):
            metadata_pairs(repo, 0, wrapper | {"response": rows + [rows[0]]}, window)
        with self.assertRaisesRegex(ValueError, "closed precommitted window"):
            metadata_pairs(
                repo, 0, wrapper | {"completed_at": "2026-10-19T09:00:00+00:00"}, window
            )

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
        labels = json.loads(
            (ROOT / "calibration-projection-v4/labels.json").read_text()
        )
        label = next(item for item in labels if item["kind"] == "procedure")
        procedure = label["procedure"]
        correct = verify_procedure(procedure, label["expected"])
        wrong_identifier = next(
            mode for mode in procedure["modes"] if mode != label["expected"]
        )
        wrong = verify_procedure(procedure, wrong_identifier)
        unknown = verify_procedure(procedure, "mode_00000000")
        self.assertEqual((correct["exit_code"], wrong["exit_code"]), (0, 0))
        self.assertTrue(correct["predicate_success"])
        self.assertFalse(wrong["predicate_success"])
        self.assertFalse(unknown["executed"])

    def test_replace_ref_ignored_and_actual_scoring_object_corruption_rejected(self):
        labels = json.loads(
            (ROOT / "calibration-projection-v4/labels.json").read_text()
        )
        label = next(item for item in labels if item["kind"] == "procedure")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "capture"
            shutil.copytree(RECEIPT.parent, target)
            procedure = label["procedure"] | dict(
                bare_git_dir=str(target / "objects.git"),
                source_receipt_path=str(target / "source-receipt.json"),
            )
            tree = procedure["modes"][label["expected"]]
            wrong = next(
                value
                for key, value in procedure["modes"].items()
                if key != label["expected"]
            )
            subprocess.run(
                [
                    "git",
                    "--git-dir",
                    procedure["bare_git_dir"],
                    "update-ref",
                    "refs/replace/" + tree,
                    wrong,
                ],
                check=True,
                capture_output=True,
            )
            verified = verify_procedure(procedure, label["expected"])
            self.assertTrue(verified["predicate_success"])
            self.assertTrue(verified["git_replace_objects_disabled"])
            original = (target / "current-tree.raw").read_bytes()
            altered = original + b"x"
            loose = target / "objects.git/objects" / tree[:2] / tree[2:]
            loose.parent.mkdir(exist_ok=True)
            loose.write_bytes(
                zlib.compress(f"tree {len(altered)}\0".encode() + altered)
            )
            # Git can prefer an intact packed copy. Remove packs only from this
            # temporary test copy so the corrupted loose object is exercised.
            pack = target / "objects.git/objects/pack"
            self.assertTrue(pack.resolve().is_relative_to(Path(directory).resolve()))
            shutil.rmtree(pack)
            with self.assertRaisesRegex(ValueError, "bytes/type drifted"):
                verify_procedure(procedure, label["expected"])

    def test_admission_hash_order_and_real_calibration_overlap_fail_closed(self):
        projection = ROOT / "calibration-projection-v4"
        proof = json.loads((projection / "projection-proof.json").read_text())
        paths = [Path(c["source_receipt_path"]) for c in proof["cases"]]
        entries = [
            json.loads(p.read_text())["entry"]
            | dict(
                source_receipt_path=str(p),
                source_receipt_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            )
            for p in paths
        ]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            pairs = target / "EVALUATION_PAIRS.json"
            pairs.write_text(json.dumps(dict(entries=entries)))
            admission = dict(
                schema="hepta.external-git-event.prospective-admission.v1",
                precommit_sha256=PRECOMMIT_SHA,
                complete=True,
                admitted_sources=8,
                planned_sources=8,
                selected_pairs_sha256=hashlib.sha256(pairs.read_bytes()).hexdigest(),
                calibration_collection_sha256=hashlib.sha256(
                    (projection / "collection.json").read_bytes()
                ).hexdigest(),
                windows_extended=False,
                source_replacements=False,
                model_outcomes_consulted=False,
                source_selection=[
                    dict(repository=e["repo"], status="admitted") for e in entries
                ],
            )
            path = target / "admission.json"
            path.write_text(json.dumps(admission))
            with self.assertRaisesRegex(ValueError, "exact object leaked"):
                verify_admission(path, pairs, projection / "collection.json", paths)
            with self.assertRaisesRegex(ValueError, "ordered admitted source receipt"):
                verify_admission(
                    path, pairs, projection / "collection.json", list(reversed(paths))
                )
            pairs.write_text(pairs.read_text() + " ")
            with self.assertRaisesRegex(
                ValueError, "admission/pairs/calibration binding"
            ):
                verify_admission(path, pairs, projection / "collection.json", paths)

    def test_real_calibration_projections_obey_snapshot_and_path_semantics(self):
        inputs = ROOT / "calibration-projection-v4"
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
            organized, _ = proj.select(
                lookup, candidates, mode="organized", revoked=set()
            )
            self.assertEqual(set(organized), set(support[spec["id"]]))
            for key in organized:
                self.assertLessEqual(proj.facts[key]["revision"], spec["revision"])
            if len(spec["path"]) == 2:
                first, _ = proj.select(
                    Lookup(lookup.entity, (lookup.path[0],), lookup.revision),
                    candidates,
                    mode="entity_time",
                    revoked=set(),
                )
                self.assertNotEqual(set(first), set(organized))


if __name__ == "__main__":
    unittest.main()
