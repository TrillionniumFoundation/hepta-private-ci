"""Acceptance of complete fit evidence; rejection of pseudo-complete results."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from .analyze import ARMS, CPU_ARMS, analyze_confirmation, paired_interval, plan_from_development


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value).encode()
    path.write_bytes(gzip.compress(raw, mtime=0) if path.name.endswith(".gz") else raw)


def summaries(fit, delta, splits):
    result = []
    for split in splits:
        for arm in (*ARMS, "bayes"):
            utility = delta if "structured_off" in arm else 0.
            if arm.startswith("first_passage_bank__structured_on"):
                utility = 2*delta
            if arm.startswith("first_passage_bank__impulse_on"):
                utility = 3*delta
            if arm.startswith("ordinary_bank__structured_on"):
                utility = .5*delta
            for controller in ("fixed", "value"):
                result.append(dict(fit=fit, split=split, candidate=arm, controller=controller,
                                   worlds=96 if split != "validation" else 32,
                                   metrics=dict(utility=utility if controller=="value" else 0., execution_cpu_seconds=.001)))
    return result


class FitAnalysisChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.protocol = dict(fits=[1, 2, 3], development_fits=[101,103,107], iid_worlds=96,
                             ood_worlds=96, validation_worlds=32, batch_states=128,
                             updates=240, training_cpu_seconds=16.)
        for fit, delta in zip(self.protocol["fits"], (.1,.2,.3)):
            summary = summaries(fit, delta, ("iid","ood"))
            write(self.root/f"confirm/fit_{fit}/summary.json", summary)
            for split in ("iid","ood"):
                raw = [dict(fit=fit,split=split,candidate=row["candidate"],controller=row["controller"],
                            world=f"world_{i}",metrics=row["metrics"],label_access_after_terminal=True)
                       for row in summary if row["split"] == split for i in range(96)]
                write(self.root/f"confirm/fit_{fit}/{split}_episodes.json.gz",raw)
            write(self.root/f"train/fit_{fit}/FINISHED.json", dict(fit=fit, development=False,
                  models={arm:{} for arm in ARMS}, source_sha256={"science.py":"one-fixed-source"}))
            for arm in ARMS:
                cpu = arm in CPU_ARMS
                write(self.root/f"train/fit_{fit}/training/{arm}.json.gz", dict(
                    fit=fit, spec=dict(id=arm,budget="cpu" if cpu else "updates"), batch_size=128,
                    optimizer_updates=100 if cpu else 240, learning_cpu_seconds=16.1 if cpu else 10.,
                    setup_cpu_seconds=.1, cpu_budget_overshoot=.1 if cpu else 0.,
                    training_cpu_budget=16. if cpu else None, capacity=dict(allocated=1707)))
            for folder, stage in (("train","train"),("confirm","confirm")):
                write(self.root/f"{folder}/process_receipts/fit_{fit}.json", dict(fit=fit,stage=stage,
                      returncode=0,whole_process_cpu_seconds=400.,user_cpu_seconds=390.,
                      system_cpu_seconds=10.,whole_process_wall_seconds=450.,peak_rss_kib=1000))
        for fit, delta in zip(self.protocol["development_fits"], (.1,.3,.5)):
            write(self.root/f"dev/fit_{fit}/validation_summary.json", summaries(fit,delta,("validation",)))

    def tearDown(self):
        self.tmp.cleanup()

    def analyze(self):
        return analyze_confirmation(self.root/"confirm", self.root/"train", self.protocol)

    def test_fit_not_world_sample_size_and_correct_paired_variance(self):
        result = self.analyze()
        terminal = next(row for row in result["primary_results"] if row["contrast"]=="terminal_structure" and row["split"]=="iid")
        self.assertEqual(terminal["n_independent_fits"], 3)
        self.assertEqual(terminal["degrees_of_freedom"], 2)
        self.assertAlmostEqual(terminal["mean"], .2)
        self.assertAlmostEqual(terminal["sample_sd"], .1)
        self.assertEqual(terminal["multiplicity"], 8)
        self.assertGreater(terminal["confidence_interval"][1]-terminal["mean"], .1)
        self.assertEqual(result["external_process_cpu_total"], 2400.)
        self.assertFalse(result["cost_superiority_established"])

    def test_missing_arm_duplicate_row_or_fit_is_rejected(self):
        path = self.root/"confirm/fit_1/summary.json"
        rows = json.loads(path.read_text())
        for changed in (rows[:-1], rows+[rows[0]]):
            write(path, changed)
            with self.assertRaises(ValueError):
                self.analyze()
        write(path, rows)
        protocol = dict(self.protocol, fits=[1,1,3])
        with self.assertRaises(ValueError):
            analyze_confirmation(self.root/"confirm", self.root/"train", protocol)
        (self.root/"confirm/fit_4").mkdir()
        with self.assertRaises(ValueError):
            self.analyze()

    def test_cpu_budget_substitution_rejected(self):
        path = self.root/f"train/fit_1/training/{CPU_ARMS[0]}.json.gz"
        row = json.loads(gzip.decompress(path.read_bytes()))
        row["training_cpu_budget"] = 17.
        write(path,row)
        with self.assertRaises(ValueError):
            self.analyze()

    def test_unpaired_raw_world_or_inaccurate_summary_rejected(self):
        path = self.root/"confirm/fit_1/iid_episodes.json.gz"
        rows = json.loads(gzip.decompress(path.read_bytes()))
        rows[0]["world"] = "unpaired_world"
        write(path,rows)
        with self.assertRaises(ValueError):
            self.analyze()
        rows[0]["world"] = "world_0"
        rows[0]["metrics"]["utility"] += .2
        write(path,rows)
        with self.assertRaises(ValueError):
            self.analyze()

    def test_failed_attempt_cost_is_retained_without_extra_fit(self):
        write(self.root/"failed/process_receipts/fit_101.json", dict(fit=101,stage="development",returncode=1,
              whole_process_cpu_seconds=20.,user_cpu_seconds=19.,system_cpu_seconds=1.,
              whole_process_wall_seconds=25.,peak_rss_kib=1000))
        result = analyze_confirmation(self.root/"confirm",self.root/"train",self.protocol,
                                      additional_attempt_roots=[self.root/"failed"])
        self.assertEqual(result["external_process_cpu_total"],2420.)
        self.assertEqual(result["fits"],[1,2,3])
        self.assertEqual(result["additional_attempt_processes"][0]["returncode"],1)

    def test_three_fit_planning_preserves_resource_cap(self):
        plan = plan_from_development(self.root/"dev",self.protocol)
        self.assertGreater(plan["maximum_requested_fits"],16)
        self.assertEqual(plan["selected_fits"],16)
        self.assertTrue(plan["resource_cap_binds"])
        self.assertFalse(plan["multiplier_is_confidence_bound"])
        self.assertFalse(plan["planned_power_claim"])

    def test_exact_signflip_uses_fit_units(self):
        result = paired_interval([1,2,3], [.1,.2,.3], signflip=True)
        self.assertEqual(result["signflip_two_sided_p_unadjusted"],.25)


if __name__ == "__main__":
    unittest.main()
