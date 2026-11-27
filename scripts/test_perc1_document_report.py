"""Report accounting regressions use synthetic data and establish no efficacy."""

import copy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest

from perc1.document_report import evaluate
from perc1.experiment import FixtureExecutor, actor_context
from perc1.fixture import smoke
from perc1.schema import ARMS, Cost, Dataset, Invalid, load, sha


class DocumentReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        smoke(root)
        data, self.frozen, self.evaluator = [
            load(root / (n + ".json")) for n in ("dataset", "manifest", "evaluator")
        ]
        data["episodes"] = [
            e for e in data["episodes"] if e["family"] == "blurred_screenshot"
        ]
        ids = {e["id"] for e in data["episodes"]}
        data["sources"] = [s for s in data["sources"] if s["episode_id"] in ids]
        for e in data["episodes"]:
            e["source_ids"][1:] = reversed(e["source_ids"][1:])
        self.dataset = Dataset(data, root)
        self.frozen["dataset_sha256"] = sha(data)
        self.frozen["controller"]["training_runs"] = self.frozen["controller"][
            "training_runs"
        ][:1]
        self.frozen["splits"] = {
            s: [e["group"] for e in data["episodes"] if e["split"] == s]
            for s in ("train", "dev", "confirmation")
        }
        self.evaluator["targets"] = [
            t for t in self.evaluator["targets"] if t["episode_id"] in ids
        ]
        self.frozen["evaluator"]["targets_sha256"] = sha(self.evaluator["targets"])
        episode = next(e for e in data["episodes"] if e["split"] == "confirmation")
        seed = self.frozen["controller"]["training_runs"][0]["seed"]
        self.executions = []
        for arm in ARMS:
            trace = FixtureExecutor(self.frozen, self.dataset, episode, seed, arm).run()
            representation, mode = arm.split("_")
            self.executions.append(
                dict(
                    mode=mode,
                    representation=representation,
                    trace=trace,
                    spent=sum(Cost.parse(s["cost"]).total for s in trace["steps"]),
                    valid_native_trace=True,
                )
            )
        for mode in ("ocr_only", "direct_roi", "random"):
            trace = copy.deepcopy(self.executions[0]["trace"])
            trace["schema"] = "perc1.document-comparator.v1"
            if mode == "direct_roi":
                trace["steps"] = trace["steps"][1:]
            if mode == "ocr_only":
                trace["steps"] = trace["steps"][:1]
                trace["answer"] = {
                    "text": "",
                    "fields": {"critical": ""},
                    "evidence_ids": [],
                }
            for index, step in enumerate(trace["steps"]):
                if mode != "random":
                    step["cost"]["encoding"] = 0
                    obs = step["observation"]
                    text = trace["answer"]["text"]
                    step["observation"] = {
                        k: obs[k]
                        for k in (
                            "source_id",
                            "raw_sha256",
                            "raw_base64",
                            "locator",
                            "observed_ns",
                        )
                    }
                    step["observation"].update(
                        schema="perc1.document-ocr-observation.v1",
                        ocr={
                            "text": text,
                            "text_sha256": sha(text.encode()),
                            "capture_sha256": obs["raw_sha256"],
                        },
                    )
                step["input_sha256"] = sha(
                    actor_context(self.dataset, episode, trace["steps"][:index])
                )
            self.executions.append(
                dict(
                    mode=mode,
                    representation="global",
                    trace=trace,
                    spent=sum(Cost.parse(s["cost"]).total for s in trace["steps"]),
                    valid_native_trace=False,
                )
            )
        self.overheads = {
            "training_once": asdict(Cost(training=128)),
            "projection_once": asdict(Cost(training=10)),
            "collection_by_representation": {
                "global": asdict(Cost(acquisition=40)),
                "dense": asdict(Cost(acquisition=50)),
            },
            "head_fit_by_representation": {
                "global": asdict(Cost(training=5)),
                "dense": asdict(Cost(training=6)),
            },
            "label_preparation_by_representation": {
                "global": asdict(Cost(training=7)),
                "dense": asdict(Cost(training=8)),
            },
            "label_source_read_once": asdict(Cost(training=2)),
            "audit_finalization_once": asdict(Cost(communication=2)),
            "model_load_once": {"wall_ns": 20000, "proxy_microcredits": 20},
            "collector_startup_once": {"wall_ns": 3000, "proxy_microcredits": 3},
            "ocr_init_once": {"wall_ns": 1000, "proxy_microcredits": 1},
        }

    def report(self):
        return evaluate(
            self.frozen,
            self.dataset,
            self.executions,
            self.evaluator,
            1e-6,
            self.overheads,
            bootstrap=200,
        )

    def test_one_fit_gate_and_strong_baseline_cost_are_preserved(self):
        result = self.report()
        self.assertEqual(result["status"], "HOLD")
        self.assertFalse(result["scientific_qualified"])
        self.assertIn("at least two", result["complete_protocol_gate"]["reason"])
        self.assertEqual(
            result["costs"]["online_by_condition_and_phase"]["direct_roi"]["encoding"],
            0,
        )
        self.assertGreater(
            result["arms"]["direct_roi"]["utility"],
            result["arms"]["global_fixed"]["utility"],
        )
        self.assertEqual(result["effects"]["task_success"]["dense"]["estimate"], 0)

    def test_comparator_cannot_borrow_a_different_manifest(self):
        self.executions[-2]["trace"]["manifest_sha256"] = sha("changed")
        with self.assertRaises(Invalid):
            self.report()

    def test_ocr_baseline_cannot_be_charged_unused_encoding(self):
        record = self.executions[-2]
        record["trace"]["steps"][0]["cost"]["encoding"] = 1
        record["spent"] += 1
        with self.assertRaisesRegex(Invalid, "unused neural"):
            self.report()

    def test_missing_comparator_or_unacquired_answer_citation_rejected(self):
        self.executions[-2]["trace"]["answer"]["evidence_ids"] = ["unacquired"]
        with self.assertRaises(Invalid):
            self.report()

    def test_overhead_allocation_and_explicit_amortization_denominator(self):
        result = self.report()
        charges = result["deployment_charges"]
        self.assertEqual(
            {c: v["total"] for c, v in charges["one_time_by_condition"].items()},
            {
                "global_fixed": 33,
                "dense_fixed": 33,
                "global_active": 87,
                "dense_active": 99,
                "ocr_only": 1,
                "direct_roi": 1,
                "random": 33,
            },
        )
        sensitivity = charges["amortization_sensitivity"]
        for horizon in (1, 32, 1000):
            actual = sensitivity[str(horizon)]["global_active"]
            self.assertEqual(actual["one_time_per_task"], 87 / horizon)
            self.assertAlmostEqual(
                actual["fully_charged_utility"],
                result["arms"]["global_active"]["utility"] - 1e-6 * 87 / horizon,
            )
        self.assertEqual(
            charges["one_time_by_condition"]["direct_roi"]["projection"], 0
        )

    def test_comparator_raw_and_ocr_capture_bindings_are_checked(self):
        original = copy.deepcopy(self.executions)
        for mutation in ("raw_sha256", "ocr_capture"):
            self.executions = copy.deepcopy(original)
            obs = self.executions[-2]["trace"]["steps"][0]["observation"]
            if mutation == "raw_sha256":
                obs["raw_sha256"] = sha("changed")
            else:
                obs["ocr"]["capture_sha256"] = sha("another capture")
            with self.subTest(mutation=mutation), self.assertRaises(Invalid):
                self.report()
        self.executions.pop(-2)
        with self.assertRaises(Invalid):
            self.report()


if __name__ == "__main__":
    unittest.main()
