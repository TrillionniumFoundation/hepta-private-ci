"""Development-only driver boundaries; mocked effects establish no task benefit."""

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from perc1 import document_public_control as control
from perc1.document_collector import Collector
from perc1.schema import Invalid, sha
import test_perc1_public_actor as public_actor_tests


class PublicControlTests(unittest.TestCase):
    def test_unconfigured_encoder_rejects_before_source_io(self):
        collector = Collector.__new__(Collector)
        collector.finalization, collector.worker = None, None
        collector.dataset = SimpleNamespace(sources=Mock(), read=Mock())
        with self.assertRaisesRegex(Invalid, "encoder not configured"):
            collector.observe("missing", "global", encode=True)
        collector.dataset.read.assert_not_called()

    def test_driver_never_opens_confirmation_labels_or_executes_confirmation(self):
        fixture = public_actor_tests.PublicActorTests()
        fixture.setUp()
        episodes, sources = {}, {}
        for split in ("train", "dev", "confirmation"):
            ids = [split + "-" + i for i in ("initial", "extra")]
            episodes[split] = dict(
                fixture.episode,
                id=split,
                group=split,
                split=split,
                source_ids=ids,
                initial_ids=ids[:1],
            )
            for name in ids:
                sources[name] = dict(
                    fixture.dataset.sources["initial"],
                    split=split,
                    sha256=sha(name),
                    locator=dict(
                        fixture.dataset.sources["initial"]["locator"],
                        origin_sha256=sha(split),
                    ),
                )
        dataset = SimpleNamespace(
            episodes=episodes, sources=sources, value={"fixture": 1}
        )
        targets = [
            dict(episode_id=s, answer="extra", fields={"selected_word": "extra"})
            for s in ("train", "dev")
        ]

        def safe_load(path):
            return {
                "dataset.json": dataset.value,
                "panel.json": {"dataset_sha256": sha(dataset.value)},
                "training-targets.json": targets,
            }[Path(path).name]

        def observe(name, representation, *, encode):
            self.assertFalse(encode)
            self.assertFalse(name.startswith("confirmation"))
            value = fixture.observation(name)
            value["cost"]["acquisition"] = 10000
            value["ocr"]["text"] = name.split("-")[-1]
            return value

        def execute(collector, episode, *args):
            self.assertEqual(episode["split"], "dev")
            return dict(
                spent=1,
                trace=dict(
                    answer=dict(text="extra", fields={"selected_word": "extra"})
                ),
            )

        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "training-targets.json").write_text("[]")
            collector = SimpleNamespace(
                engine={},
                output=Path(folder),
                records=[],
                index={"startup_ns": 1},
                observe=Mock(side_effect=observe),
                accounted_cost=lambda r: r["cost"],
                finalize=lambda: {},
            )
            with (
                patch.object(control, "Dataset", return_value=dataset),
                patch.object(control, "load", side_effect=safe_load),
                patch.object(control.actor, "Collector", return_value=collector),
                patch.object(control.actor, "execute", side_effect=execute),
            ):
                report = control.run(folder, Path(folder) / "run")
            self.assertEqual(report["paired_rows"], 2)
            self.assertFalse(report["independent_evaluation"])
