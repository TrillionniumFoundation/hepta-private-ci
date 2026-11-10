"""A changed live extractor must fail before any OCR or target-file access."""

import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from perc1.schema import Invalid, sha


@unittest.skipUnless(
    importlib.util.find_spec("numpy"), "NumPy training runtime required"
)
class RepeatTrainingTests(unittest.TestCase):
    def test_changed_public_extractor_rejects_before_io(self):
        import perc1_repeat_training as runner
        from test_perc1_acquisition import pair

        pairs = [
            pair(f"{split}-{i}", split, value)
            for split in ("train", "dev")
            for i, value in enumerate((-1, 0, 1))
        ]
        episodes = {
            p["source_group"]: dict(group=p["source_group"], split=p["split"])
            for p in pairs
        }
        episodes["reserved"] = dict(group="reserved", split="confirmation")
        inputs = dict(
            confirmation_execution_allowed=False,
            pairs={
                c: dict(
                    path=c + ".json",
                    sha256=sha(pairs),
                    feature_extractor_sha256=sha("different extractor"),
                )
                for c in ("global", "dense", "public")
            },
        )

        def read(path):
            name = Path(path).name
            if name == "inputs.json":
                return inputs, sha(inputs)
            if name == "dataset.json":
                return {}, sha({})
            if name in ("global.json", "dense.json", "public.json"):
                return pairs, sha(pairs)
            self.fail("targets or captures were opened before extractor validation")

        with tempfile.TemporaryDirectory() as folder:
            with (
                patch.object(runner, "_read", side_effect=read),
                patch.object(
                    runner, "Dataset", return_value=SimpleNamespace(episodes=episodes)
                ),
                patch.object(runner.actor, "Collector") as collector,
            ):
                with self.assertRaisesRegex(Invalid, "extractor differs"):
                    runner.run(folder, Path(folder) / "run")
                collector.assert_not_called()
