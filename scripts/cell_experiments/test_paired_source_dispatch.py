import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from . import data, paired_source_dispatch

CASE = (
    Path(__file__).resolve().parents[2]
    / "qualification"
    / "paired-source-training-20261123"
)


class SourceDispatchTests(unittest.TestCase):
    def test_actual_no_update_cannot_enter_owner_dispatch(self):
        report = json.loads((CASE / "RETENTION.json").read_bytes())
        with zipfile.ZipFile(CASE / "engineering-run.zip") as archive:
            path = next(
                name for name in archive.namelist() if name.endswith("/FROZEN.json")
            )
            snap = json.loads(archive.read(path))
        with self.assertRaisesRegex(ValueError, "did not permit"):
            paired_source_dispatch.authorize(
                snap,
                {"source_retention_sha256": data.digest(report)},
                CASE / "RETENTION.json",
            )
        with self.assertRaisesRegex(ValueError, "not committed"):
            paired_source_dispatch.authorize(snap, {}, CASE / "RETENTION.json")

    def test_legacy_owner_refused_and_engineering_quality_checks_retained(self):
        snap = {
            "parent": {"test": "parent"},
            "candidate": {"test": "candidate"},
            "retention": [{"old": 1}, {"old": 2}],
        }

        def row(i):
            return {
                "panel": "retention",
                "record_sha256": data.digest({"old": i}),
                "parent": True,
                "candidate": True,
            }

        good = {
            "schema": "hepta.paired-learning.source-retention.v1",
            "policy": paired_source_dispatch.paired_source_gate.POLICY,
            "freeze_sha256": data.digest(snap),
            "parent_sha256": data.digest(snap["parent"]),
            "candidate_sha256": data.digest(snap["candidate"]),
            "prospective_records_read": 0,
            "comparisons": [row(1), row(2)],
            "decision": "eligible_for_prospective_evaluation",
            "scope": "owner_intake",
        }
        with TemporaryDirectory() as tmp:

            def run(report):
                path = Path(tmp) / "report"
                path.write_bytes(data.canonical(report))
                return paired_source_dispatch.authorize(
                    snap, {"source_retention_sha256": data.digest(report)}, path
                )

            with self.assertRaisesRegex(ValueError, "ORIGINAL_TURN_VERIFIER_REQUIRED"):
                run(good)
            good["scope"] = "engineering_fixture"
            with self.assertRaisesRegex(ValueError, "lacks original owner scope"):
                run(good)
            bad = copy.deepcopy(good)
            bad["comparisons"][0]["candidate"] = False
            with self.assertRaisesRegex(ValueError, "did not permit"):
                run(bad)
            for changes, reason in (
                ({"comparisons": [row(1)]}, "coverage differs"),
                ({"freeze_sha256": "f" * 64}, "does not identify"),
            ):
                with self.assertRaisesRegex(ValueError, reason):
                    run({**good, **changes})

    def test_freeze_observer_rechecks_original_scores_and_receipts(self):
        with (
            TemporaryDirectory() as tmp,
            zipfile.ZipFile(CASE / "engineering-run.zip") as archive,
        ):
            operation = Path(tmp)
            names = [
                "FROZEN.json",
                "RETENTION.json",
                "COMPLETED.json",
                "OWNER.json",
                "cold-retention/parent.json",
                "cold-retention/candidate.json",
            ]
            for name in names:
                target = operation / name
                target.parent.mkdir(parents=True, exist_ok=True)
                original = next(n for n in archive.namelist() if n.endswith("/" + name))
                target.write_bytes(archive.read(original))
            report_file = operation / "RETENTION.json"
            report = json.loads(report_file.read_bytes())
            completed = json.loads((operation / "COMPLETED.json").read_bytes())

            def verify():
                return paired_source_dispatch.verify_originals(
                    report_file, completed["study_sha256"], completed["freeze_sha256"]
                )

            with self.assertRaisesRegex(ValueError, "did not permit"):
                verify()
            raw_file = operation / "cold-retention/parent.json"
            raw = json.loads(raw_file.read_bytes())
            raw["rows"][1]["prediction"]["answer"] = "different answer"
            raw_file.write_bytes(data.canonical(raw))
            with self.assertRaisesRegex(ValueError, "original cold receipt"):
                verify()
            report["cold_receipts"]["parent"] = data.digest(raw)
            report_file.write_bytes(data.canonical(report))
            with self.assertRaisesRegex(ValueError, "original retention score differs"):
                verify()
