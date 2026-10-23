"""Independent synthetic red tests. No model work or real incident evidence.

Run against the exact review copy by default, or set PYTHONPATH to a patched
memory_cell_domain directory before loading this file via unittest discovery.
"""

import json
from pathlib import Path
import tempfile
import unittest

from domain_data import canonical, load_dataset, partition_cases, produce, sha
import test_domain_data


def pair(**shared):
    common = dict(project="review/fixture", **shared)
    return [
        dict(
            common,
            id="early",
            root_cause="annotated-a",
            observed_at="2026-01-01T00:00:00Z",
            resolved_at="2026-01-02T00:00:00Z",
        ),
        dict(
            common,
            id="late",
            root_cause="annotated-b",
            observed_at="2026-03-01T00:00:00Z",
            resolved_at="2026-03-02T00:00:00Z",
        ),
    ]


class SourceGroupRegressions(unittest.TestCase):
    def split(self, cases):
        return partition_cases(cases, "2026-01-05T00:00:00Z", "2026-01-10T00:00:00Z")

    def assert_purged_together(self, partitions):
        self.assertEqual(partitions["train"], [], partitions)
        self.assertEqual(partitions["future"], [], partitions)
        self.assertEqual(set(partitions["purged"]), {"early", "late"}, partitions)

    def test_shared_fixed_commit_cannot_cross_declared_cause_labels(self):
        self.assert_purged_together(self.split(pair(fixed_commit="f" * 40)))

    def test_shared_original_failure_source_cannot_cross_cause_labels(self):
        self.assert_purged_together(self.split(pair(failure_log_sha256="a" * 64)))

    def test_same_declared_group_remains_purged_positive_control(self):
        cases = pair()
        cases[1]["root_cause"] = cases[0]["root_cause"]
        self.assert_purged_together(self.split(cases))

    def test_transitive_commit_ancestry_and_shared_patch_are_grouped(self):
        cases = pair()
        cases[0]["fixed_commit"] = "a" * 40
        cases[1]["failed_commit"] = "b" * 40
        bridge = dict(
            cases[0],
            id="bridge",
            root_cause="third",
            failed_commit="a" * 40,
            fixed_commit="b" * 40,
        )
        partitions = self.split(cases + [bridge])
        self.assertEqual(set(partitions["purged"]), {"early", "late", "bridge"})
        self.assert_purged_together(self.split(pair(repair_patch_sha256="p" * 64)))

    def test_missing_creation_or_attempt_stays_unverified_and_new_created_can_pass(
        self,
    ):
        for mode in ("missing_created", "missing_attempt", "new"):
            with self.subTest(mode=mode):
                root, path, manifest, runs_path, runs = self.fixture()
                for run in runs:
                    run["created_at"] = run["updated_at"]
                    run["run_attempt"] = 1
                for run in runs[:2]:
                    run["created_at"] = "2026-03-01T09:00:00Z"
                    run["updated_at"] = "2026-03-01T10:00:00Z"
                if mode == "missing_created":
                    del runs[0]["created_at"]
                if mode == "missing_attempt":
                    del runs[0]["run_attempt"]
                manifest["cases"][0]["previously_seen"] = False
                self.save(path, manifest, runs_path, runs)
                receipt = produce(path, root / "review-produced")
                data = json.loads(Path(receipt["dataset"]).read_bytes())
                self.assertEqual("case-0" in data["prospective_cases"], mode == "new")

    def fixture(self):
        original = test_domain_data.DomainDataTests()
        original.setUp()
        self.addCleanup(original.doCleanups)
        path, manifest = original.fixture()
        runs_path = original.root / manifest["runs"]["path"]
        runs = json.loads(runs_path.read_bytes())
        return original.root, path, manifest, runs_path, runs

    def save(self, path, manifest, runs_path, runs):
        runs_path.write_bytes(canonical(runs))
        manifest["runs"]["sha256"] = sha(runs_path.read_bytes())
        path.write_bytes(canonical(manifest))

    def test_loader_rejects_legacy_or_reassigned_partitions_without_changing_evidence(
        self,
    ):
        root, path, manifest, runs_path, runs = self.fixture()
        receipt = produce(path, root / "review-produced")
        dataset = Path(receipt["dataset"])
        original = dataset.read_bytes()
        data = json.loads(original)
        data["schema"] = "hepta.domain.dataset.v1"
        dataset.write_bytes(canonical(data))
        with self.assertRaisesRegex(ValueError, "rebuild legacy"):
            load_dataset(dataset, sha(dataset.read_bytes()))
        data = json.loads(original)
        data["partitions"]["train"].remove("case-0")
        data["partitions"]["future"].append("case-0")
        dataset.write_bytes(canonical(data))
        with self.assertRaisesRegex(ValueError, "temporal partitions"):
            load_dataset(dataset, sha(dataset.read_bytes()))
        data = json.loads(original)
        data["cases"][0]["first_observed_at"] = "2026-03-01T00:00:00Z"
        case = data["cases"][0]
        case["source_digest"] = sha(
            canonical({k: v for k, v in case.items() if k != "source_digest"})
        )
        dataset.write_bytes(canonical(data))
        with self.assertRaisesRegex(ValueError, "original run"):
            load_dataset(dataset, sha(dataset.read_bytes()))

    def test_loader_rejects_dropped_bridges_and_rehashed_ancestry(self):
        root, path, manifest, runs_path, runs = self.fixture()
        receipt = produce(path, root / "review-produced")
        dataset = Path(receipt["dataset"])
        original = dataset.read_bytes()
        data = json.loads(original)
        data["cases"].pop()
        dataset.write_bytes(canonical(data))
        with self.assertRaisesRegex(ValueError, "original incident census"):
            load_dataset(dataset, sha(dataset.read_bytes()))
        data = json.loads(original)
        case = data["cases"][0]
        case["fixed_commit"] = "z" * 40
        case["source_digest"] = sha(
            canonical({k: v for k, v in case.items() if k != "source_digest"})
        )
        dataset.write_bytes(canonical(data))
        with self.assertRaisesRegex(ValueError, "original incident sources"):
            load_dataset(dataset, sha(dataset.read_bytes()))

    def test_updated_at_rerun_cannot_create_prospective_status(self):
        root, path, manifest, runs_path, runs = self.fixture()
        for run in runs:
            run["created_at"] = run["updated_at"]
            run["run_attempt"] = 1
        # Both runs existed before registration. Their later attempt completed
        # after it. A new timestamp is not a newly observed task.
        for run in runs[:2]:
            run["updated_at"] = "2026-03-01T10:00:00Z"
            run["run_attempt"] = 2
        manifest["cases"][0]["previously_seen"] = False
        self.save(path, manifest, runs_path, runs)
        receipt = produce(path, root / "review-produced")
        data = json.loads(Path(receipt["dataset"]).read_bytes())
        self.assertNotIn("case-0", data["prospective_cases"], data)

    def test_producer_reused_repair_commit_cannot_leak_into_future(self):
        root, path, manifest, runs_path, runs = self.fixture()
        manifest["cases"][1]["fix"] = dict(manifest["cases"][0]["fix"])
        manifest["cases"][1]["previously_seen"] = False
        runs[2]["head_sha"] = runs[0]["head_sha"]
        runs[3]["head_sha"] = runs[1]["head_sha"]
        for run in runs:
            run["created_at"] = run["updated_at"]
            run["run_attempt"] = 1
        for run in runs[2:4]:
            run["updated_at"] = "2026-03-01T10:00:00Z"
            run["run_attempt"] = 2
        self.save(path, manifest, runs_path, runs)
        receipt = produce(path, root / "review-produced")
        data = json.loads(Path(receipt["dataset"]).read_bytes())
        split = data["partitions"]
        self.assertFalse(
            "case-0" in split["train"] and "case-1" in split["future"], split
        )


if __name__ == "__main__":
    unittest.main()
