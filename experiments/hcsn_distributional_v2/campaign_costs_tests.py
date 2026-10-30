"""Small evidence fixtures for cost containment, SHA binding and archive priority."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from experiments.hcsn_distributional_v2.campaign_costs import (
    Ledger, SELF, WAIT4, aggregate_receipts, archive_receipts, lif_receipts, numeric, scaling_receipts,
)


class CostEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.package = Path(self.temporary.name) / "repo/experiments/hcsn_distributional_v2"
        self.package.mkdir(parents=True)
        self.ledger = Ledger(self.package)

    def save(self, relative, value):
        path = self.package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def fixture_bundle(self, name, self_cpu, outer_cpu=None):
        archive_sha = "a" * 64
        manifest = self.save("artifacts/" + name + ".json", dict(
            schema="hcsn-evidence-bundle.v1", name=name, archive_sha256=archive_sha,
            members=[], parts=[]))
        self.save("artifacts/" + name + "_EXECUTION.json", dict(
            schema="hcsn-v2-evidence-seal.v1", name=name, archive_sha256=archive_sha,
            members=0, verified_restore=dict(archive_sha256=archive_sha, restored_or_already_identical=0),
            whole_process_self_cpu_seconds_through_seal=self_cpu))
        if outer_cpu is not None:
            self.save("results/content_checkpoint_archives/receipts/" + name + ".json", dict(
                bundle_name=name, manifest_path=str(manifest), returncode=0,
                cpu_seconds_including_children=outer_cpu,
                wait4_user_cpu_seconds=outer_cpu - .1, wait4_system_cpu_seconds=.1))
        return manifest

    def test_outer_replaces_inner_for_its_bundle_only(self):
        self.fixture_bundle("first", 2., 3.)
        self.fixture_bundle("second", 4.)
        self.save("results/content_checkpoint_archives/instances/one_EXECUTION.json", dict(own_cpu_seconds=.2))
        archive_receipts(self.ledger, "artifacts/ARCHIVE_COMPLETION.json")
        observed = {x["scope_id"]: x["observed_cpu_seconds"] for x in self.ledger.rows}
        self.assertEqual(observed, {"archive_first": 3., "archive_second": 4., "archive_watcher_one_EXECUTION": .2})
        self.assertAlmostEqual(sum(observed.values()), 7.2)
        self.assertTrue(self.ledger.missing)

    def test_nested_field_cannot_be_charged_again(self):
        path = self.save("receipt.json", {"outer": 5., "inner": 3.})
        self.ledger.add("tree", "test", self.ledger.binding(path, "/outer"), WAIT4, "whole tree",
                        [self.ledger.binding(path, "/inner")])
        with self.assertRaisesRegex(ValueError, "reused"):
            self.ledger.single("nested", "test", path, "/inner", SELF, "would double count")

    def test_receipt_sha_is_checked(self):
        path = self.save("receipt.json", {"cpu": 1.})
        original_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_text('{"cpu": 2.0}')
        with self.assertRaisesRegex(ValueError, "SHA mismatch"):
            self.ledger.binding(path, "/cpu", original_sha)

    def test_failed_pack_cost_survives_without_published_manifest(self):
        self.save("results/content_checkpoint_archives/receipts/failure.json", dict(
            bundle_name="failure", manifest_path="not_published.json", returncode=7,
            cpu_seconds_including_children=.75,
            wait4_user_cpu_seconds=.7, wait4_system_cpu_seconds=.05))
        archive_receipts(self.ledger, "artifacts/ARCHIVE_COMPLETION.json")
        self.assertEqual([(r["scope_id"], r["observed_cpu_seconds"]) for r in self.ledger.rows], [("archive_failed_failure", .75)])

    def test_archive_must_bind_verified_restore(self):
        self.fixture_bundle("bad", 1.)
        seal = self.package / "artifacts/bad_EXECUTION.json"
        data = json.loads(seal.read_text())
        data["verified_restore"]["archive_sha256"] = "b" * 64
        seal.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "seal/manifest mismatch"):
            archive_receipts(self.ledger, "artifacts/ARCHIVE_COMPLETION.json")

    def test_numerical_aggregate_must_match_raw_fields(self):
        child = self.save("child.json", dict(complete_child_cpu_seconds=2., coordinator_cpu_seconds=.1))
        self.save("results/NUMERICAL_COSTS.json", dict(complete_receipt_runs=[dict(
            receipt=str(child), receipt_sha256=hashlib.sha256(child.read_bytes()).hexdigest(),
            complete_child_cpu_seconds=2., recorded_separate_wrapper_window_cpu_seconds=.1)],
            partial_receipt_runs=[], totals=dict(sum_of_disjoint_recorded_cpu_scopes_lower_bound=9.)))
        with self.assertRaisesRegex(ValueError, "numerical aggregate"):
            aggregate_receipts(self.ledger)

    def test_invalid_cpu_values_are_not_silently_zeroed(self):
        for value in (-1., float("nan"), float("inf"), None, True, "3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                numeric(value)

    def test_content_original_field_variants_are_reconciled(self):
        rows = []
        for name, field, amount in [("content_preflight002_EXECUTION.json", "complete_child_cpu_seconds", 2.),
                                    ("content_tests004_EXECUTION.json", "child_cpu_seconds", 3.)]:
            path = self.save("results/" + name, {field: amount})
            rows.append(dict(path=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(), cpu_seconds=amount))
        self.save("results/content_engineering_COSTS.json", dict(complete_processes=rows,
            partial_measurements=[], recorded_engineering_cpu_lower_bound_seconds=5.))
        aggregate_receipts(self.ledger)
        self.assertEqual([(row["scope_id"], row["observed_cpu_seconds"]) for row in self.ledger.rows], [("content_engineering", 5.)])

    def test_staged_outer_child_and_coordinator_replace_nested_seal(self):
        manifest = self.fixture_bundle("staged", 2.)
        self.save("results/evidence_sealing/staged/EXECUTION.json", dict(
            schema="hcsn-v2-staged-bundle-execution.v1", status="completed", bundle_name="staged",
            manifest_path=str(manifest), complete_archive_child_cpu_seconds=3.,
            coordinator_whole_self_cpu_seconds_through_cutoff=.5))
        archive_receipts(self.ledger, "artifacts/ARCHIVE_COMPLETION.json")
        self.assertEqual({r["scope_id"]: r["observed_cpu_seconds"] for r in self.ledger.rows},
                         {"archive_staged": 3., "archive_coordinator_staged": .5})

    def test_lif_original_exit_code_and_success_pointer_are_explicit(self):
        scheduler = "results/lif_supplement001/SCHEDULER_EXECUTION.json"
        self.save(scheduler, dict(schema="hcsn-lif-scheduler-tree-execution.v1",
                                 exit_code=0, complete_child_cpu_seconds=22.))
        self.save("results/lif_supplement001/COMPLETE.json", dict(status="completed", completed=18, failures=0,
            records=[dict(child_total_cpu_seconds=1.) for _ in range(18)], complete_child_cpu_seconds=18.))
        self.save("analysis.json", dict(exit_code=0, child_cpu=2.5))
        self.save("watcher.json", dict(status="completed", self_cpu=.25))
        entries = [("lif_scheduler", scheduler, "/complete_child_cpu_seconds", 22., WAIT4, "/exit_code", 0),
                   ("lif_analysis", "analysis.json", "/child_cpu", 2.5, WAIT4, "/exit_code", 0),
                   ("lif_analysis_watcher", "watcher.json", "/self_cpu", .25, SELF, "/status", "completed")]
        scopes = [dict(scope_id=name, receipt=path, receipt_sha256=hashlib.sha256((self.package / path).read_bytes()).hexdigest(),
            field=field, cpu_seconds=amount, measurement_kind=kind, success_field=success_field,
            success_value=success_value, scope="Explicit original LIF receipt fixture")
            for name, path, field, amount, kind, success_field, success_value in entries]
        self.save("results/lif_cost_receipts001/RECEIPTS.json", dict(schema="hcsn-lif-cost-receipts.v1", status="completed", scopes=scopes))
        lif_receipts(self.ledger)
        self.assertEqual({r["scope_id"]: r["observed_cpu_seconds"] for r in self.ledger.rows},
                         {"lif_scheduler": 22., "lif_analysis": 2.5, "lif_analysis_watcher": .25})
        self.save(scheduler, dict(schema="hcsn-lif-scheduler-tree-execution.v1", exit_code=1, complete_child_cpu_seconds=22.))
        scopes[0]["receipt_sha256"] = hashlib.sha256((self.package / scheduler).read_bytes()).hexdigest()
        self.save("results/lif_cost_receipts001/RECEIPTS.json", dict(schema="hcsn-lif-cost-receipts.v1", status="completed", scopes=scopes))
        with self.assertRaisesRegex(ValueError, "success field"):
            lif_receipts(Ledger(self.package))

    def test_registered_scaling_charges_outer_and_supervisor_once(self):
        protocol = self.save("SCALING001_PROTOCOL.json", dict(cases=[dict(case_id=f"case_{i}") for i in range(30)], source_files_sha256={}))
        protocol_sha = hashlib.sha256(protocol.read_bytes()).hexdigest()
        records = []
        for i in range(30):
            path = f"results/scaling001/cases/case_{i}/EXECUTION.json"
            row = dict(case_id=f"case_{i}", complete_child_cpu_seconds=.1, receipt_path=path)
            self.save(path, row)
            records.append(row)
        completion = self.save("results/scaling001/COMPLETE.json", dict(records=records, expected_cases=30,
            completed_cases=30, status="completed", protocol_sha256=protocol_sha, source_files_sha256={}, complete_worker_cpu_seconds=3.))
        self.save("results/scaling001/SUITE_EXECUTION.json", dict(returncode=0, complete_child_cpu_seconds=4.,
            supervisor_self_cpu_seconds_through_cutoff=.2, protocol_sha256=protocol_sha, source_files_sha256={},
            complete_receipt_sha256=hashlib.sha256(completion.read_bytes()).hexdigest()))
        scaling_receipts(self.ledger)
        self.assertEqual({r["scope_id"]: r["observed_cpu_seconds"] for r in self.ledger.rows},
                         {"scaling001_suite": 4., "scaling001_supervisor": .2})
        self.assertEqual(self.ledger.missing, [])
        with self.assertRaisesRegex(ValueError, "reused"):
            self.ledger.single("duplicate_worker", "scaling", "results/scaling001/cases/case_0/EXECUTION.json",
                               "/complete_child_cpu_seconds", WAIT4, "Would repeat a nested worker")


if __name__ == "__main__":
    unittest.main()
