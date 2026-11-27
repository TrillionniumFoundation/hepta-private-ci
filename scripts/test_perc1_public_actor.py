"""Public-only actor wiring; synthetic heads do not establish task benefit."""

from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call

from perc1 import document_actor as actor
from perc1.acquisition import train_head
from perc1.schema import Invalid, PHASES, sha
from test_perc1_acquisition import pair


class PublicActorTests(unittest.TestCase):
    def setUp(self):
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
        self.dataset = SimpleNamespace(
            sources={
                name: dict(
                    id=name,
                    locator=loc,
                    description="registered view",
                    sha256=sha(name),
                )
                for name in ("initial", "extra")
            }
        )
        self.episode = dict(
            id="episode",
            task="Transcribe rectangle (0,0,8,8)",
            initial_ids=["initial"],
            source_ids=["initial", "extra"],
        )
        self.manifest = dict(
            budget=dict(cap=actor.CAP, tariff=dict.fromkeys(PHASES, 1)),
            controller=dict(training_runs=[dict(seed=0)]),
        )

    def observation(self, name):
        return dict(
            source_id=name,
            encoded=False,
            representation="ocr",
            receipt_sha256=sha([name, "receipt"]),
            cost={**dict.fromkeys(PHASES, 0), "acquisition": 1},
            ocr=dict(text=name, confidence=50.0),
            observation=dict(observed_ns=time.perf_counter_ns()),
        )

    def extract(self, acquired, **kwargs):
        return actor.public_features(
            self.dataset,
            self.episode,
            acquired,
            "extra",
            sha("prefix"),
            actor.CAP,
            "global",
            **kwargs,
        )

    def head(self, latent=()):
        pairs = [pair(split, split, 1.0) for split in ("train", "dev")]
        for value in pairs:
            value["features"]["task_goal"] = [1.0, 0.0, 0.0, 0.5, 0.5]
            value["features"]["acquired_latent"] = list(latent)
        return train_head(
            pairs[:1],
            pairs[1:],
            dict(train=["train"], dev=["dev"], confirmation=["test"]),
            feature_extractor_sha256=sha("diagnostic public features"),
        )

    def test_public_features_never_read_tokens(self):
        record = self.observation("initial")
        expected = self.extract([record], channel="public")
        self.assertEqual(expected["acquired_latent"], [])
        for observation in ({}, {"tokens": object()}, None):
            record["observation"] = observation
            self.assertEqual(self.extract([record], channel="public"), expected)

    def test_public_rejects_encoded_or_charged_evidence(self):
        initial = self.observation("initial")
        for edit in (dict(encoded=True), dict(cost={**initial["cost"], "encoding": 1})):
            extra = {**self.observation("extra"), **edit}
            with self.assertRaisesRegex(Invalid, "fresh OCR-only"):
                self.extract([initial, extra], channel="public")
        with self.assertRaisesRegex(Invalid, "matching executed initial encoder"):
            self.extract([initial])
        initial.update(
            encoded=True,
            representation="global",
            observation=dict(tokens=[dict(values=[0.1, 0.2])]),
        )
        self.assertEqual(self.extract([initial])["acquired_latent"], [0.1, 0.2])

    def test_public_active_executes_only_ocr(self):
        with tempfile.TemporaryDirectory() as folder:
            collector = SimpleNamespace(
                dataset=self.dataset,
                output=Path(folder),
                observe=Mock(side_effect=lambda name, *a, **k: self.observation(name)),
                accounted_cost=lambda r: r["cost"],
            )
            result = actor.execute(
                collector,
                self.episode,
                "global",
                "public_active",
                self.manifest,
                self.head(),
            )
            self.assertEqual(
                collector.observe.call_args_list,
                [
                    call("initial", "global", encode=False),
                    call("extra", "global", encode=False),
                ],
            )
            self.assertEqual(
                result["trace"]["answer"],
                dict(
                    text="extra",
                    fields=dict(selected_word="extra"),
                    evidence_ids=["extra"],
                ),
            )
            self.assertFalse(result["trace"]["encoder_executed"])
            self.assertFalse(result["valid_native_trace"])
            self.assertEqual(
                result["spent"],
                sum(sum(s["cost"].values()) for s in result["trace"]["steps"]),
            )
            self.assertEqual(
                sum(s["cost"]["encoding"] for s in result["trace"]["steps"]), 0
            )

    def test_public_execute_rejects_neural_head_before_io(self):
        head = self.head([0.1])
        collector = SimpleNamespace(observe=Mock())
        with self.assertRaises(Invalid):
            actor.execute(
                collector, self.episode, "global", "public_active", self.manifest, head
            )
        collector.observe.assert_not_called()

    def test_public_execute_rejects_neural_result_even_on_last_read(self):
        for failing in ("initial", "extra"):
            with self.subTest(source=failing), tempfile.TemporaryDirectory() as folder:

                def observe(name, *args, **kwargs):
                    record = self.observation(name)
                    record["encoded"] = name == failing
                    return record

                collector = SimpleNamespace(
                    dataset=self.dataset,
                    output=Path(folder),
                    observe=Mock(side_effect=observe),
                    accounted_cost=lambda r: r["cost"],
                )
                with self.assertRaisesRegex(Invalid, "fresh OCR-only"):
                    actor.execute(
                        collector,
                        self.episode,
                        "global",
                        "public_active",
                        self.manifest,
                        self.head(),
                    )


if __name__ == "__main__":
    unittest.main()
