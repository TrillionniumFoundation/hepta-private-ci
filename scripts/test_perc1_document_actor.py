"""Actor contracts plus one optional, real TRAIN-document seven-condition smoke.

Set PERC_TEST_MOBILENET_WEIGHTS and PERC_TEST_DOCUMENT_DATASET to run it.
PERC_TEST_DOCUMENT_OUTPUT_DIR retains evidence; otherwise it is temporary.
Synthetic diagnostic heads exercise acquisition, not learned task efficacy.
"""

import base64
import importlib.util
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from perc1.schema import Cost, Dataset, Invalid, PHASES, canonical, load, sha

try:
    from PIL import Image
    from perc1 import document_actor as actor
    from perc1.acquisition import train_head
    from perc1.producer import FrozenMobileNet, PREPROCESS
    from perc1.projection import fit_projection
except ImportError:
    actor = None

WEIGHTS_SHA = "047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f"
ACTUAL = (
    actor is not None
    and importlib.util.find_spec("torch")
    and os.environ.get("PERC_TEST_MOBILENET_WEIGHTS")
    and os.environ.get("PERC_TEST_DOCUMENT_DATASET")
)


@unittest.skipUnless(actor is not None, "optional document runtime unavailable")
class DocumentBudgetTests(unittest.TestCase):
    def context(self, output):
        loc = dict(
            kind="image",
            origin_sha256=sha("document"),
            x0=0,
            y0=0,
            x1=8,
            y1=8,
            width=16,
            height=16,
        )
        source = dict(id="opaque-source", locator=loc, description="registered view")
        episode = dict(
            id="opaque-episode",
            task="Transcribe rectangle (0,0,8,8)",
            source_ids=[source["id"]],
            initial_ids=[source["id"]],
        )
        collector = SimpleNamespace(
            output=output,
            dataset=SimpleNamespace(sources={source["id"]: source}),
            observe=Mock(),
            accounted_cost=lambda r: r["cost"],
        )
        manifest = dict(
            budget=dict(cap=actor.CAP, tariff=dict.fromkeys(PHASES, 1)),
            controller=dict(training_runs=[dict(seed=0)]),
        )
        return collector, episode, manifest

    def test_unaffordable_read_never_calls_producer(self):
        with tempfile.TemporaryDirectory() as folder:
            collector, episode, manifest = self.context(Path(folder))
            collector.observe.side_effect = AssertionError("unreserved I/O")
            with patch.object(actor, "READ_QUOTE", actor.CAP + 1):
                result = actor.execute(
                    collector, episode, "global", "ocr_only", manifest, None
                )
            collector.observe.assert_not_called()
            self.assertEqual(result["trace"]["steps"][0]["status"], "budget_denied")
            self.assertEqual(result["receipt_sha256s"], [])

    def test_actual_quote_overrun_is_retained_and_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            collector, episode, manifest = self.context(Path(folder))

            def overrun(*args, **kwargs):
                cost = dict.fromkeys(PHASES, 0)
                cost["inference"] = actor.READ_QUOTE + 1
                return dict(
                    source_id="opaque-source",
                    cost=cost,
                    receipt_sha256=sha("diagnostic receipt"),
                    observation=dict(observed_ns=time.perf_counter_ns()),
                )

            collector.observe.side_effect = overrun
            with self.assertRaisesRegex(Invalid, "full failure retained"):
                actor.execute(collector, episode, "global", "ocr_only", manifest, None)
            failures = list(Path(folder).glob("budget-overrun-*.json"))
            self.assertEqual(len(failures), 1)
            self.assertGreater(load(failures[0])["actual"], actor.READ_QUOTE)
            self.assertEqual(collector.observe.call_count, 1)


@unittest.skipUnless(
    ACTUAL, "explicit checkpoint and document dataset runtime required"
)
class DocumentExecutedTests(unittest.TestCase):
    def test_real_train_document_all_seven_conditions(self):
        from test_perc1_acquisition import pair

        configured = os.environ.get("PERC_TEST_DOCUMENT_OUTPUT_DIR")
        if configured:
            output = Path(configured)
            self.assertFalse(output.exists(), "preserve prior evidence")
            output.mkdir(parents=True)
        else:
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            output = Path(temporary.name)
        root = Path(os.environ["PERC_TEST_DOCUMENT_DATASET"])
        dataset = Dataset(load(root / "dataset.json"), root)
        train = [e for e in dataset.episodes.values() if e["split"] == "train"][:3]
        self.assertEqual(len(train), 3)
        worker = FrozenMobileNet(os.environ["PERC_TEST_MOBILENET_WEIGHTS"], WEIGHTS_SHA)
        values, captures, groups = [], [], []
        for episode in train:
            source_id = episode["initial_ids"][0]
            raw = dataset.read(source_id)
            with Image.open(dataset.root / dataset.sources[source_id]["path"]) as image:
                regions = actor.regions_for(image)
            _, feature, _ = worker.features(raw, regions)
            values.extend(feature)
            captures.extend([dict(sha256=sha(raw), split="train")] * 4)
            groups.extend([episode["group"]] * 4)
        projection = fit_projection(
            values,
            captures=captures,
            groups=groups,
            backbone_sha256=WEIGHTS_SHA,
            dimension=8,
        )
        (output / "projection.json").write_bytes(canonical(projection) + b"\n")
        collector = actor.Collector(dataset, worker, projection, output / "collector")
        heads = {}
        for representation, length in (("global", 8), ("dense", 32)):
            pairs = [
                pair("diagnostic-" + split, split, 1.0) for split in ("train", "dev")
            ]
            for value in pairs:
                value["features"].update(
                    task_goal=[1.0, 0.0, 0.0, 0.1, 0.1], acquired_latent=[0.0] * length
                )
            splits = dict(
                train=["diagnostic-train"],
                dev=["diagnostic-dev"],
                confirmation=["unused-diagnostic"],
            )
            heads[representation] = train_head(
                pairs[:1],
                pairs[1:],
                splits,
                feature_extractor_sha256=sha("diagnostic public features"),
            )
        manifest = dict(
            schema="perc1.manifest.v1",
            dataset_sha256=sha(dataset.value),
            encoder=dict(
                kind="external_artifact",
                checkpoint_sha256=collector.encoder_sha256,
                preprocessor_sha256=sha(PREPROCESS),
                dimension=8,
            ),
            controller=dict(
                sha256=sha(heads),
                training_runs=[
                    dict(
                        seed=0,
                        receipt_sha256=sha(heads),
                        cost={**dict.fromkeys(PHASES, 0), "training": 1},
                    )
                ],
            ),
            evaluator={
                k: sha("unused evaluator contract")
                for k in (
                    "identity_sha256",
                    "rubric_sha256",
                    "targets_sha256",
                    "canaries_sha256",
                )
            },
            teacher_sha256=None,
            budget=dict(
                unit="microcredits_v1", cap=actor.CAP, tariff=dict.fromkeys(PHASES, 1)
            ),
            splits={
                s: sorted(
                    {e["group"] for e in dataset.episodes.values() if e["split"] == s}
                )
                for s in ("train", "dev", "confirmation")
            },
            thresholds=None,
        )
        (output / "manifest.json").write_bytes(canonical(manifest) + b"\n")
        conditions = [(r, m) for r in ("global", "dense") for m in ("fixed", "active")]
        conditions += [("global", m) for m in ("random", "ocr_only", "direct_roi")]
        executions = []
        for representation, mode in conditions:
            before = worker.calls
            result = actor.execute(
                collector,
                train[0],
                representation,
                mode,
                manifest,
                heads[representation],
            )
            self.assertLessEqual(result["spent"], actor.CAP)
            self.assertEqual(
                result["spent"],
                sum(Cost.parse(s["cost"]).total for s in result["trace"]["steps"]),
            )
            self.assertEqual(result["valid_native_trace"], mode in ("fixed", "active"))
            if mode in ("ocr_only", "direct_roi"):
                self.assertEqual(worker.calls, before)
                self.assertEqual(len(result["receipt_sha256s"]), 1)
                self.assertEqual(
                    sum(s["cost"]["encoding"] for s in result["trace"]["steps"]), 0
                )
            executions.append(result)
        finalized = collector.finalize()
        index = load(collector.output / "index.json")
        self.assertEqual(len(index["index_write_ns"]), len(index["records"]))
        for entry in index["records"]:
            record = load(collector.output / entry["path"])
            self.assertEqual(
                record["receipt_sha256"],
                sha({k: v for k, v in record.items() if k != "receipt_sha256"}),
            )
            self.assertEqual(
                base64.b64decode(record["observation"]["raw_base64"]),
                dataset.read(record["source_id"]),
            )
            self.assertGreater(
                entry["accounted_cost"]["communication"],
                record["cost"]["communication"],
            )
            if record["encoded"]:
                self.assertEqual(
                    sha(
                        (collector.output / record["native_wire"]["path"]).read_bytes()
                    ),
                    record["producer"]["observation_sha256"],
                )
                if record["ocr"]["text"]:
                    self.assertEqual(
                        record["producer"]["exact_text"]["text"], record["ocr"]["text"]
                    )
        summary = dict(
            schema="perc1.document-actor-development-smoke.v1",
            status="PASS",
            scope="engineering contracts on TRAIN images with synthetic diagnostic heads; no efficacy evaluation",
            train_document=train[0]["id"],
            dataset_sha256=sha(dataset.value),
            conditions=len(executions),
            records=len(index["records"]),
            formal_trace_count=sum(r["valid_native_trace"] for r in executions),
            encoder_calls=worker.calls,
            cap=actor.CAP,
            read_quote=actor.READ_QUOTE,
            ocr_engine=collector.engine,
            finalization=finalized,
            conditions_summary=[
                dict(
                    mode=r["mode"],
                    representation=r["representation"],
                    spent=r["spent"],
                    phases={
                        p: sum(s["cost"][p] for s in r["trace"]["steps"])
                        for p in PHASES
                    },
                )
                for r in executions
            ],
            phase_max_per_observation={
                p: max(e["accounted_cost"][p] for e in index["records"]) for p in PHASES
            },
            phase_max_per_step={
                p: max(s["cost"][p] for r in executions for s in r["trace"]["steps"])
                for p in PHASES
            },
            actor_code_sha256=sha(Path(actor.__file__).read_bytes()),
            scientific_qualified=False,
        )
        (output / "summary.json").write_bytes(canonical(summary) + b"\n")
        (output / "executions.json").write_bytes(canonical(executions) + b"\n")


if __name__ == "__main__":
    unittest.main()
