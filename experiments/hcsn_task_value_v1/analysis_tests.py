"""Synthetic-only tests of integrity and statistical gates; no study data read."""

import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from .analysis import analyze, factorial, interval, pair, ratios
from .analysis_audit import audit_job, digest, pending_jobs, prediction_metrics, registered_jobs


SEEDS = (31031, 31067, 31103)
POLICY = dict(accuracy_noninferiority_margin=.02, ce_noninferiority_ratio=1.05,
              parameter_gap=.05, training_cpu_gap=.10)


def row(seed, arm, accuracy=.8, ce=.5, cpu=10., parameters=100):
    job = dict(task="selective_copy", arm=arm, width=16, seed=seed, updates=256,
               batch_size=8, learning_rate=.003, training_cpu_budget=None)
    metric = dict(accuracy=accuracy, cross_entropy=ce, data_sha256="same-data",
                  cohort_sha256="same-targets")
    return dict(id=f"{arm}-{seed}", job=job, audit_ok=True,
                metrics={"length32": metric}, dataset_sha256={"train": "a", "val": "b"},
                allocated_parameters=parameters, trainable_parameters=parameters,
                actual_updates=256, costs=dict(training_cpu_seconds=cpu, child_cpu_seconds=cpu+2,
                child_peak_rss_bytes=10000, checkpoint_bytes=2000))


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value))


def fixture(study, source):
    """One complete fake worker, including explicitly fabricated predictions."""
    (source/"cost_meter.py").write_text("# synthetic audit fixture\n")
    job = dict(id="fixture", family="freeze", task="selective_copy", arm="freeze_reset",
               width=16, seed=SEEDS[0], updates=2, batch_size=8, learning_rate=.003,
               validate_every=1, training_cpu_budget=None,
               source_hashes={"cost_meter.py": digest(source/"cost_meter.py")})
    write(study/"jobs/fixture.json", job)
    declared = {k: v for k, v in job.items() if k != "source_hashes"}
    declared["job_file_sha256"] = digest(study/"jobs/fixture.json")
    protocol = dict(jobs=[declared], expected_jobs=1, seeds=[SEEDS[0]], source_hashes=job["source_hashes"])
    write(study/"protocol.json", protocol)
    write(study/"registration_receipt.json", dict(protocol_sha256=digest(study/"protocol.json"),
          source_hashes=job["source_hashes"]))
    run = study/"runs/fixture"
    write(run/"job.json", job)
    (run/"selected.pt").write_bytes(b"Synthetic bytes, not a torch checkpoint")
    logits = np.zeros((128, 8), np.float32)
    labels = np.arange(128) % 8
    logits[np.arange(128), labels] = 1
    ce = float(np.log(np.exp(1.)+7)-1.)
    metrics = dict(accuracy=1., cross_entropy=ce, supervised_tokens=128, episodes=128)
    payload = dict(logits=logits, labels=labels, episodes=np.arange(128),
                   token_index=np.full(128, 31), correct=np.ones(128, bool))
    for name in ("validation_prediction", "prediction_length32", "prediction_length64", "prediction_length128"):
        np.savez_compressed(run/(name+".npz"), **payload)
    selected = dict(step=2, checkpoint_sha256=digest(run/"selected.pt"), validation=metrics)
    write(run/"selection.json", selected)
    trace = [dict(step=1, loss=2., gradient_norm=.2, training_cpu_seconds=.1,
                  validation={**metrics, "cross_entropy": ce+.1}),
             dict(step=2, loss=1.9, gradient_norm=.1, training_cpu_seconds=.2, validation=metrics)]
    write(run/"trace.json", trace)
    clock = time.time()+1
    access = [dict(split=s, length=32, missing_modality=None, sha256=s, unix_seconds=clock) for s in ("train", "val")]
    access += [dict(split="test", length=n, missing_modality=None, sha256=f"data-{n}", unix_seconds=clock)
               for n in (32, 64, 128)]
    write(run/"access.json", access)
    delta = dict(content=dict(l2=.2, changed=1, tensors=1, trainable=100),
                 reset=dict(l2=0., changed=0, tensors=1, trainable=0))
    summary = dict(job=job, config={}, runtime=dict(preflight=False), actual_updates=2,
                   group_delta=delta, selected_group_delta=copy.deepcopy(delta),
                   mean_gradient=dict(content=.1, reset=0), allocated_parameters=101,
                   trainable_parameters=100, training_cpu_seconds=.2, training_wall_seconds=.3,
                   worker_body_cpu_seconds=.5, worker_body_wall_seconds=.7,
                   validation_selection=selected, evaluation={f"length{n}": metrics for n in (32, 64, 128)},
                   inference={})
    write(run/"summary.json", summary)
    log = study/"meter/fixture.json.log"
    log.parent.mkdir()
    log.write_text("Synthetic worker completion\n")
    receipt = dict(returncode=0, timed_out=False, child_reaped=True, spawn_error=None,
                   log_path=str(log), log_sha256=digest(log), child_cpu_seconds=.7,
                   supervisor_cpu_seconds=.02, wall_seconds=.9, child_peak_rss_bytes=10000,
                   meter_source_sha256=job["source_hashes"]["cost_meter.py"],
                   inner_training_clocks_are_subtotals=True)
    write(study/"meter/fixture.json", receipt)
    write(study/"execution.json", dict(complete=True, protocol_sha256=digest(study/"protocol.json"),
          rows=[dict(id="fixture", returncode=0, receipt_exists=True, summary_exists=True)]))
    return protocol, summary


class StatisticalTests(unittest.TestCase):
    def test_three_seed_interval_is_paired_df_two(self):
        got = interval([.01, .02, .03])
        self.assertAlmostEqual(got["lower"], .02-4.302652729911275*.01/np.sqrt(3), places=14)
        self.assertEqual(got["n"], 3)
        self.assertIsNone(interval([.1])["lower"])

    def test_ratio_interval_and_zero_denominator(self):
        got = ratios([1., 2., 4.], [2., 4., 8.])
        self.assertEqual(got["upper"], .5)
        self.assertEqual(got["ratio_of_means"], .5)
        self.assertIsNone(ratios([1.], [0.]))

    def test_no_cost_advantage_without_quality(self):
        candidate = {s: row(s, "value_dual", accuracy=.7, cpu=1) for s in SEEDS}
        baseline = {s: row(s, "two_gates") for s in SEEDS}
        got = pair(candidate, baseline, "length32", SEEDS, POLICY)
        self.assertEqual(got["accuracy_sign"], "negative")
        self.assertLess(got["cost_ratios"]["child_cpu_seconds"]["upper"], 1.)
        self.assertFalse(got["qualified_whole_worker_cpu_advantage"])

    def test_ce_can_block_accuracy_noninferiority(self):
        candidate = {s: row(s, "value_dual", accuracy=.9, ce=.6, cpu=1) for s in SEEDS}
        baseline = {s: row(s, "two_gates") for s in SEEDS}
        got = pair(candidate, baseline, "length32", SEEDS, POLICY)
        self.assertTrue(got["accuracy_gain_nominal95"])
        self.assertFalse(got["quality_noninferiority_qualified"])
        self.assertFalse(got["matched_mechanism_accuracy_gain"])

    def test_complete_identity_and_budget_are_separate_gates(self):
        a = {s: row(s, "value_dual", accuracy=.9, ce=.49, cpu=9.5, parameters=105) for s in SEEDS}
        b = {s: row(s, "two_gates") for s in SEEDS}
        got = pair(a, b, "length32", SEEDS, POLICY)
        self.assertTrue(got["quality_noninferiority_qualified"])
        self.assertTrue(got["matched_mechanism_accuracy_gain"])
        self.assertTrue(got["qualified_whole_worker_cpu_advantage"])
        a[SEEDS[0]]["allocated_parameters"] = 106
        self.assertFalse(pair(a, b, "length32", SEEDS, POLICY)["matched_mechanism_accuracy_gain"])
        a[SEEDS[0]]["dataset_sha256"]["train"] = "different"
        self.assertFalse(pair(a, b, "length32", SEEDS, POLICY)["quality_noninferiority_qualified"])
        del a[SEEDS[0]]
        self.assertFalse(pair(a, b, "length32", SEEDS, POLICY)["accuracy_gain_nominal95"])

    def test_factorial_uses_seed_means_and_detects_interaction(self):
        arms = {}
        for bi, b in enumerate(("value", "fixed", "direct")):
            for ci, c in enumerate(("dual", "single", "ordinary")):
                arms[b+"_"+c] = {s: row(s, b+"_"+c, .6+.02*bi+.01*ci+.03*bi*ci+.001*j)
                                 for j, s in enumerate(SEEDS)}
        key = ("selective_copy", 16, 256, 8, .003, None)
        result = factorial({key: arms}, SEEDS)[0]
        self.assertTrue(result["complete"])
        effect = result["main_effects"][0]
        self.assertAlmostEqual(effect["accuracy"]["mean"], -.05)
        self.assertAlmostEqual(result["interactions"][0]["accuracy"]["mean"], .03)
        arms["direct_ordinary"][SEEDS[0]]["metrics"]["length32"]["cohort_sha256"] = "different"
        self.assertFalse(factorial({key: arms}, SEEDS)[0]["complete"])


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hcsn-analysis-fixture-")
        self.study = Path(self.temp.name)/"study"
        self.source = Path(self.temp.name)/"source"
        self.source.mkdir()
        self.protocol, self.summary = fixture(self.study, self.source)
        self.registration = registered_jobs(self.study, self.protocol)[0]

    def tearDown(self):
        self.temp.cleanup()

    def audit(self):
        with patch("experiments.hcsn_task_value_v1.analysis_audit.PACKAGE", self.source):
            return audit_job(self.study, self.registration)

    def test_complete_fixture_passes_without_torch_deserialization(self):
        got = self.audit()
        self.assertTrue(got["audit_ok"], got["errors"])
        self.assertEqual(got["metrics"]["length32"]["maximum_token_index"], 31)

    def test_completed_fixture_report_and_no_overwrite(self):
        output = self.study/"analysis"
        with patch("experiments.hcsn_task_value_v1.analysis_audit.PACKAGE", self.source):
            got = analyze(self.study, output, authorized=True)
            self.assertTrue(got["job_audit"][0]["audit_ok"])
            self.assertTrue((output/"RESULTS_ZH.md").is_file())
            with self.assertRaises(FileExistsError):
                analyze(self.study, output, authorized=True)

    def test_selected_frozen_group_is_checked_separately(self):
        self.summary["selected_group_delta"]["reset"]["l2"] = .01
        write(self.study/"runs/fixture/summary.json", self.summary)
        self.assertTrue(any("selected_group_delta" in e for e in self.audit()["errors"]))

    def test_job_tampering_is_retained_not_silently_redefined(self):
        spec = copy.deepcopy(self.registration["job"])
        spec["arm"] = "value_dual"
        write(self.study/"jobs/fixture.json", spec)
        got = registered_jobs(self.study, self.protocol)[0]
        self.assertEqual(got["job"]["arm"], "freeze_reset")
        self.assertGreater(len(got["registration_errors"]), 0)

    def test_terminal_launch_failure_does_not_disappear(self):
        (self.study/"meter/fixture.json").unlink()
        write(self.study/"execution.json", dict(complete=True,
              rows=[dict(id="fixture", returncode=None, launcher_error="synthetic launch failure")]))
        self.assertEqual(pending_jobs(self.study, [self.registration]), [])
        self.assertFalse(self.audit()["audit_ok"])

    def test_coordinator_gate_precedes_prediction_access(self):
        (self.study/"execution.json").unlink()
        with patch("numpy.load", side_effect=AssertionError("Prediction opened prematurely")):
            with self.assertRaisesRegex(RuntimeError, "not terminal"):
                analyze(self.study, self.study/"analysis", authorized=True)
            with self.assertRaisesRegex(RuntimeError, "authorization"):
                analyze(self.study, self.study/"analysis")

    def test_prediction_identity_includes_token_position(self):
        path = self.study/"runs/fixture/prediction_length32.npz"
        got = prediction_metrics(path, self.summary["evaluation"]["length32"])
        with np.load(path) as archive:
            payload = {key: archive[key] for key in archive.files}
        payload["token_index"] = payload["token_index"]-1
        np.savez_compressed(path, **payload)
        changed = prediction_metrics(path, self.summary["evaluation"]["length32"])
        self.assertNotEqual(got["cohort_sha256"], changed["cohort_sha256"])

    def test_test_access_cannot_precede_selection(self):
        path = self.study/"runs/fixture/access.json"
        access = json.loads(path.read_text())
        for value in access:
            if value["split"] == "test":
                value["unix_seconds"] = 0
        write(path, access)
        self.assertTrue(any("predates" in e for e in self.audit()["errors"]))


if __name__ == "__main__":
    unittest.main()
