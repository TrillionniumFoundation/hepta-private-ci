"""Synthetic cache-integrity controls, not scientific model or quality evidence.

The original scores() aggregation runs on real small NPZ files and real metric
code. Dataset/corpus are explicit synthetic fixtures. The model constructor,
decoder and teacher-forced inference are forbidden during these cache tests.
"""
from contextlib import redirect_stdout
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np


HERE = Path(__file__).resolve().parent


def load_evaluator(path):
    """Load actual evaluator plus its checked-in, unchanged direct dependencies."""
    path = Path(path).resolve()
    saved = sys.path[:]
    try:
        sys.path[:0] = [str(path.parent), str(path.parent.parent / "generation")]
        with patch.dict(sys.modules):
            for name in ("fit", "model", "metrics"):
                sys.modules.pop(name, None)
            spec = importlib.util.spec_from_file_location("score_binding_subject", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    finally:
        sys.path[:] = saved


class CachedPanel:
    def __init__(self, evaluator, root):
        self.evaluator = evaluator
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.scores_root = self.root / "generation"
        self.scores_root.mkdir()
        colors = ["blue", "red", "green", "white", "black", "yellow"]
        captions = [["a", color, "field", "today"] for color in colors]
        self.references = [[caption] for caption in captions]
        self.ids = [f"synthetic-image-{i}" for i in range(6)]
        words = sorted({word for caption in captions for word in caption})
        vocabulary = {word: i + 4 for i, word in enumerate(words)}
        evaluator.write(self.root / "vocabulary.json", vocabulary)
        pixels = np.broadcast_to(
            np.arange(12, dtype=np.uint8)[:, None, None, None], (12, 32, 32, 3)
        ).copy()
        self.data = SimpleNamespace(
            pix=pixels, tr=np.arange(6), te=np.arange(6, 12), vocab=len(words) + 4
        )
        self.train_text = captions
        metric = evaluator.CaptionMetrics(self.references)

        def arrays_and_summary(predictions):
            shift = [predictions[i] for i in np.roll(np.arange(6), 1)]
            aligned, a = metric.evaluate(predictions)
            shifted, b = metric.evaluate(shift)
            aligned["length_capped"] = 0
            arrays = dict(
                ids=self.ids,
                tokens=np.zeros((6, 16), dtype=np.int16),
                stopped=np.ones(6, dtype=bool),
                aligned_cider=a["cider_d"],
                aligned_rouge=a["rouge_l"],
                shifted_cider=b["cider_d"],
                shifted_rouge=b["rouge_l"],
                dedup_cider=a["cider_d"],
                candidate_lengths=a["candidate_lengths"],
                reference_lengths=a["reference_lengths"],
                clipped=a["clipped"],
                total_ngrams=a["total_ngrams"],
                token_loss=np.full(6, 10.0),
                token_counts=np.full(6, 4),
            )
            return arrays, dict(
                aligned=aligned,
                shifted=shifted,
                deduplicated=copy.deepcopy(aligned),
                teacher_forced_nll=2.5,
            )

        self.arrays, metrics = arrays_and_summary(captions)
        self.alternate_arrays, _ = arrays_and_summary([[] for _ in captions])
        self.alternate = self.scores_root / "alternate.npz"
        np.savez_compressed(self.alternate, **self.alternate_arrays)
        self.outside = self.root / "outside.npz"
        self.outside.write_bytes(self.alternate.read_bytes())
        selections = {}
        self.cache_paths = []
        self.expected_score_paths = set()
        for arm in evaluator.ARMS:
            for seed in evaluator.SEEDS:
                key = f"{arm}-{seed}"
                loc = self.root / "training" / key
                loc.mkdir(parents=True)
                model_identity = loc / "end-60.pt"
                model_identity.write_text(
                    "SYNTHETIC CACHE IDENTITY ONLY; NOT A MODEL TENSOR: " + key + "\n"
                )
                identity = evaluator.sha(model_identity)
                selected = dict(file=model_identity.name, sha256=identity, gate=60)
                selections[key] = dict(
                    best=selected, final=copy.deepcopy(selected), fit_sha256="unused"
                )
                score_path = self.scores_root / f"{key}-60.npz"
                np.savez_compressed(score_path, **self.arrays)
                result_path = score_path.with_suffix(".json")
                evaluator.write(
                    result_path,
                    dict(
                        model_sha256=identity,
                        gate=60,
                        score_file=score_path.name,
                        score_sha256=evaluator.sha(score_path),
                        metrics=copy.deepcopy(metrics),
                        seconds=0.0,
                        examples=[],
                    ),
                )
                self.cache_paths.extend((score_path, result_path, model_identity))
                self.expected_score_paths.add(score_path)
        evaluator.write(self.root / "selection.json", selections)
        self.target = self.scores_root / "literal-109-60.json"
        self.loads = []
        self.byte_loads = []
        self.model_calls = None

    def change_target(self, **changes):
        record = self.evaluator.read(self.target)
        record.update(changes)
        self.evaluator.write(self.target, record)

    def run(self, before_load=None):
        evaluator = self.evaluator
        actual_load = np.load

        def observe_load(path, *args, **kwargs):
            if isinstance(path, io.BytesIO):
                self.byte_loads.append({
                    "sha256": evaluator.hashlib.sha256(path.getvalue()).hexdigest(),
                    "allow_pickle": kwargs.get("allow_pickle"),
                })
            else:
                self.loads.append(Path(path))
            if before_load is not None:
                before_load(path)
            return actual_load(path, *args, **kwargs)

        captured = io.StringIO()
        try:
            with (
                patch.object(evaluator, "Dataset", return_value=self.data),
                patch.object(
                    evaluator,
                    "corpus",
                    return_value=(self.ids, self.references, self.train_text),
                ),
                patch.object(
                    evaluator, "Captioner", side_effect=AssertionError("no model construction")
                ) as model,
                patch.object(
                    evaluator, "decode", side_effect=AssertionError("no model generation")
                ),
                patch.object(
                    evaluator, "token_loss", side_effect=AssertionError("no model inference")
                ),
                patch.object(evaluator.np, "load", side_effect=observe_load),
                redirect_stdout(captured),
            ):
                try:
                    evaluator.scores(self.root, self.root / "synthetic-material")
                finally:
                    self.model_calls = model.call_count
                    if self.model_calls:
                        raise AssertionError("cache test attempted model construction")
        finally:
            (self.root / "aggregation.stdout").write_text(captured.getvalue())
        return evaluator.read(self.root / "generation_terminal.json")


class ScoreCacheBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evaluator = load_evaluator(HERE / "evaluate.py")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rsicd-cache-control-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def panel(self, name="case"):
        return CachedPanel(self.evaluator, self.root / name)

    def test_valid_cached_panel_preserves_results_and_duplicate_selections(self):
        panel = self.panel()
        before = {path: path.read_bytes() for path in panel.cache_paths}
        result = panel.run()
        self.assertEqual(len(result["results"]), 24)
        self.assertEqual(result["averages"]["best"], result["averages"]["final"])
        for which in ("best", "final"):
            for comparison in result["paired_image_deltas"][which].values():
                self.assertEqual(comparison, {"cider": [0.0, 0.0, 0.0], "rouge": [0.0, 0.0, 0.0]})
        self.assertEqual({path: path.read_bytes() for path in panel.cache_paths}, before)
        self.assertEqual(panel.loads, [])
        self.assertEqual(len(panel.byte_loads), len(panel.expected_score_paths))
        self.assertEqual(
            {item["sha256"] for item in panel.byte_loads},
            {self.evaluator.sha(path) for path in panel.expected_score_paths},
        )
        self.assertTrue(all(item["allow_pickle"] is False for item in panel.byte_loads))
        self.assertEqual(panel.model_calls, 0)

    def test_different_or_escaping_score_file_is_rejected_before_aggregation(self):
        for name in ("different", "parent", "absolute"):
            with self.subTest(name=name):
                panel = self.panel(name)
                alias = {
                    "different": panel.alternate.name,
                    "parent": "../outside.npz",
                    "absolute": str(panel.alternate),
                }[name]
                panel.change_target(score_file=alias)
                with self.assertRaisesRegex(ValueError, "score or state identity"):
                    panel.run()
                self.assertFalse((panel.root / "generation_terminal.json").exists())
                self.assertEqual(panel.loads, [])
                self.assertEqual(panel.model_calls, 0)

    def test_same_path_replacement_after_digest_cannot_change_aggregated_arrays(self):
        panel = self.panel()
        selected = panel.target.with_suffix(".npz")
        original_digest = self.evaluator.sha(selected)
        replacements = []

        def replace_after_digest(source):
            if not replacements:
                self.assertIsInstance(source, io.BytesIO)
                selected.write_bytes(panel.alternate.read_bytes())
                replacements.append(selected)

        result = panel.run(before_load=replace_after_digest)
        self.assertEqual(replacements, [selected])
        self.assertNotEqual(self.evaluator.sha(selected), original_digest)
        self.assertEqual(selected.read_bytes(), panel.alternate.read_bytes())
        for which in ("best", "final"):
            for comparison in result["paired_image_deltas"][which].values():
                self.assertEqual(comparison, {"cider": [0.0, 0.0, 0.0], "rouge": [0.0, 0.0, 0.0]})
            self.assertEqual(
                result["averages"][which]["literal"]["cider_d"],
                float(np.mean(panel.arrays["aligned_cider"])),
            )
        self.assertEqual(panel.loads, [])
        self.assertEqual(panel.model_calls, 0)

    def test_cached_gate_must_match_selected_gate(self):
        panel = self.panel()
        panel.change_target(gate=900)
        with self.assertRaisesRegex(ValueError, "score or state identity"):
            panel.run()
        self.assertFalse((panel.root / "generation_terminal.json").exists())
        self.assertEqual(panel.loads, [])

    def test_original_score_digest_check_is_preserved(self):
        panel = self.panel()
        expected = panel.target.with_suffix(".npz")
        expected.write_bytes(panel.alternate.read_bytes())
        with self.assertRaisesRegex(ValueError, "score or state identity"):
            panel.run()
        self.assertFalse((panel.root / "generation_terminal.json").exists())
        self.assertEqual(panel.loads, [])

    def test_original_result_model_identity_check_is_preserved(self):
        panel = self.panel()
        panel.change_target(model_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "score or state identity"):
            panel.run()
        self.assertFalse((panel.root / "generation_terminal.json").exists())
        self.assertEqual(panel.loads, [])

    def test_original_selected_model_digest_check_is_preserved(self):
        panel = self.panel()
        (panel.root / "training/literal-109/end-60.pt").write_text("changed synthetic identity\n")
        with self.assertRaisesRegex(ValueError, "model hash"):
            panel.run()
        self.assertFalse((panel.root / "generation_terminal.json").exists())
        self.assertEqual(panel.loads, [])


if __name__ == "__main__":
    unittest.main()
