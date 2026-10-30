"""Small stdlib fixtures for isolated incremental archiving; no training imports."""

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from .content_checkpoint_archives import ArchiveWatcher, PACKAGE, add_coverage, file_hash, read_json, write_new


class Fixture:
    def __init__(self, base, count=3):
        self.package = Path(base) / "experiments/hcsn_distributional_v2"
        self.package.mkdir(parents=True)
        self.study = self.package / "results/content002"
        self.study.mkdir(parents=True)
        self.jobs = [dict(task="fixture", model="model", seed=seed) for seed in range(count)]
        self.protocol = dict(jobs=self.jobs, source_files_sha256={},
                             data=dict(fixture=dict(sha256="fixture-data")),
                             execution=dict(expected_searches=count))
        write_new(self.package / "CONTENT002_PROTOCOL.json", self.protocol)
        self.protocol_sha = file_hash(self.package / "CONTENT002_PROTOCOL.json")
        write_new(self.study / "REGISTRATION.json", dict(jobs=count, protocol_sha256=self.protocol_sha))
        for source, destination in ((PACKAGE / "evidence_bundle.py", self.package / "evidence_bundle.py"),
                (PACKAGE.parent / "hcsn_free_boundary_v1/archive.py",
                 self.package.parent / "hcsn_free_boundary_v1/archive.py")):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        self.rows = []

    def finish(self, index):
        job = self.jobs[index]
        run_id = f"fixture__model__{index}"
        directory = self.study / "runs" / run_id
        directory.mkdir(parents=True, exist_ok=True)
        log = self.study / "process_logs" / (run_id + ".log")
        log.parent.mkdir(exist_ok=True)
        log.write_text("successful fixture worker\n")
        row = dict(job=job, protocol_sha256=self.protocol_sha, returncode=0,
                   output="runs/" + run_id, measurement="os.wait4 complete isolated worker",
                   stdout_sha256=file_hash(log), child_total_cpu_seconds=.01)
        write_new(directory / "EXECUTION.json", row)
        write_new(directory / "IDENTITY.json", dict(job=job, protocol_sha256=self.protocol_sha,
                   status="completed", source_files_sha256={}, dataset_sha256="fixture-data"))
        write_new(directory / "summary.json", dict(status="completed"))
        candidate = directory / "lr_0_0.001"
        candidate.mkdir()
        (candidate / "all_checkpoint_bytes.npz").write_bytes(bytes(range(256)) * 8)
        (candidate / "updates.jsonl").write_text('{"step":1}\n{"step":2}\n')
        self.rows.append(row)
        (self.study / "PROGRESS.json").write_text(json.dumps(dict(
            protocol_sha256=self.protocol_sha, completed=len(self.rows), expected=len(self.jobs), records=self.rows)))

    def complete(self, scheduler=True):
        write_new(self.study / "COMPLETE.json", dict(status="completed", protocol_sha256=self.protocol_sha,
            expected=len(self.jobs), completed=len(self.rows), failures=0, records=self.rows))
        if scheduler:
            write_new(self.study / "SCHEDULER_EXECUTION.json", dict(protocol_sha256=self.protocol_sha, returncode=0))


class IncrementalArchiveTests(unittest.TestCase):
    def test_complete_runs_only_then_verified_tail(self):
        with tempfile.TemporaryDirectory(prefix="hcsn-checkpoint-test-") as base:
            fixture = Fixture(base)
            fixture.finish(0)
            fixture.finish(1)
            active = fixture.study / "runs/fixture__model__2"
            active.mkdir()
            (active / "active_file").write_text("not complete yet")
            first = ArchiveWatcher(fixture.package, batch_size=2)
            self.assertEqual(first.run(watch=False), 0)
            manifest = read_json(fixture.package / "artifacts/content002_runs_000.json")
            paths = [member["path"] for member in manifest["members"]]
            self.assertTrue(any(path.endswith("updates.jsonl") for path in paths))
            self.assertTrue(any(path.endswith("all_checkpoint_bytes.npz") for path in paths))
            self.assertFalse(any("fixture__model__2" in path or path.endswith("PROGRESS.json") for path in paths))
            self.assertFalse((first.state / "COMPLETE.json").exists())
            fixture.finish(2)
            fixture.complete(scheduler=False)
            second = ArchiveWatcher(fixture.package, batch_size=2)
            self.assertEqual(second.run(watch=False), 0)
            self.assertFalse((fixture.package / "artifacts/content002_runs_001.json").exists())
            write_new(fixture.study / "SCHEDULER_EXECUTION.json", dict(protocol_sha256=fixture.protocol_sha, returncode=0))
            third = ArchiveWatcher(fixture.package, batch_size=2)
            self.assertEqual(third.run(watch=False), 0)
            final = read_json(third.state / "COMPLETE.json")
            self.assertEqual(final["covered"], 3)
            self.assertEqual(len(final["bundles"]), 2)
            self.assertEqual(len(final["bundles"][1]["run_ids"]), 1)
            for index in range(2):
                receipt = read_json(third.state / "receipts" / f"content002_runs_{index:03d}.json")
                self.assertEqual(receipt["returncode"], 0)
                self.assertGreater(receipt["cpu_seconds_including_children"], 0)

    def test_failed_child_stays_outside_discovery(self):
        with tempfile.TemporaryDirectory(prefix="hcsn-checkpoint-test-") as base:
            fixture = Fixture(base, count=1)
            # Replace only the fixture link; original archive source is unchanged.
            fake_source = fixture.package / "evidence_bundle.py"
            fake_source.unlink()
            fake_source.write_text('from pathlib import Path\nimport json\np=Path(__file__).parent/"artifacts"\np.mkdir()\n(p/"content002_runs_000.json").write_text(json.dumps({"schema":"hcsn-evidence-bundle.v1"}))\nraise SystemExit(7)\n')
            fixture.finish(0)
            watcher = ArchiveWatcher(fixture.package, batch_size=1)
            with self.assertRaisesRegex(RuntimeError, "return code 7"):
                watcher.run(watch=False)
            self.assertEqual(list(watcher.artifacts.glob("*.json")), [])
            receipt = read_json(watcher.state / "receipts/content002_runs_000.json")
            self.assertEqual(receipt["returncode"], 7)
            self.assertTrue((watcher.state / "failures/content002_runs_000.json").exists())
            self.assertTrue((watcher.state / "work/content002_runs_000/experiments/hcsn_distributional_v2/artifacts/content002_runs_000.json").exists())
            self.assertEqual(watcher.next_name(), "content002_runs_001")

    def test_receipt_mismatch_and_overlap_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix="hcsn-checkpoint-test-") as base:
            fixture = Fixture(base, count=1)
            fixture.finish(0)
            path = fixture.study / "runs/fixture__model__0/EXECUTION.json"
            row = read_json(path)
            row["returncode"] = 1
            path.write_text(json.dumps(row))
            with self.assertRaisesRegex(RuntimeError, "PROGRESS and worker EXECUTION differ"):
                ArchiveWatcher(fixture.package).progress()
        with self.assertRaisesRegex(RuntimeError, "Overlapping bundles"):
            add_coverage({"job": "first"}, ["job"], "second")

    def test_abort_is_failure_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory(prefix="hcsn-checkpoint-test-") as base:
            fixture = Fixture(base, count=1)
            write_new(fixture.study / "ABORTED.json", dict(status="aborted", protocol_sha256=fixture.protocol_sha,
                                                           reason="test_only", records=[]))
            watcher = ArchiveWatcher(fixture.package, batch_size=1)
            self.assertEqual(watcher.run(watch=False), 1)
            self.assertFalse((watcher.state / "COMPLETE.json").exists())
            self.assertEqual(read_json(watcher.state / "STATUS.json")["status"], "study_aborted")
            self.assertEqual(len(list((watcher.state / "failures").glob("*_study_aborted.json"))), 1)


if __name__ == "__main__":
    unittest.main()
