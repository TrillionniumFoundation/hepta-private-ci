"""Label-fenced public task selection and real Torch controls; no pretrained claims."""
import hashlib
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from PIL import Image
import torch

from experiments.shared_stem_cell import controls, execution as e, public_media as p
from experiments.shared_stem_cell.control_evaluation import evaluate_controls, summarize
from experiments.shared_stem_cell.public_smoke import publisher_file


class Tokenizer:
    def __call__(self, text, *, truncation):
        assert truncation is False
        return {"input_ids": list(range(len(text.split())))}

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        assert tokenize is False and add_generation_prompt is True
        return "\n".join(m["content"] for m in messages)


def public_rows():
    result = {}
    for offset, split in enumerate(p.SIZES):
        result[split] = []
        for i in range(4):
            raw = io.BytesIO()
            Image.new("RGB", (8, 8), (offset * 20 + i, 2, 3)).save(raw, format="PNG")
            result[split].append({"image": {"bytes": raw.getvalue(), "path": None},
                "question": f"Which option fits example {offset}-{i}?", "hint": "",
                "choices": ["First", "Second", "Third", "Fourth"]})
    return result


class PublicMediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.rows = public_rows()
        self.sizes = {s: 2 for s in p.SIZES}

    def tearDown(self):
        self.temp.cleanup()

    def test_labels_read_only_after_whole_cohort_sealed(self):
        seen = []
        def answer(split, index):
            sealed = e.decode((self.root / "cohort-before-labels.json").read_bytes())
            self.assertEqual(sum(map(len, sealed.values())), 6)
            seen.append((split, index))
            return index % 4
        data, seal = p.stage_cases(self.root, self.rows, answer, Tokenizer(), sizes=self.sizes)
        self.assertEqual(len(seen), 6)
        self.assertEqual(seal, e.sha((self.root / "cohort-before-labels.json").read_bytes()))
        cases, labels = p.media.read_cases(self.root, data, 4)
        self.assertEqual(len(cases), 6)
        self.assertEqual(len(labels), 6)
        self.assertFalse(any(hasattr(c, "label") for c in cases))
        self.assertTrue(all(p.media.image_bytes(p.media.reference(self.root, c.inputs["image"])).size == (8, 8) for c in cases))

    def test_answer_or_solution_fields_never_enter_selector(self):
        for field in ("answer", "lecture", "solution"):
            row = dict(self.rows["train"][0], **{field: "secret"})
            with self.assertRaises(e.InputError):
                p.prompt(row)

    def test_choice_count_filter_does_not_read_labels(self):
        self.rows["train"][0]["choices"] = ["yes", "no"]
        chosen = p.choose(self.rows, Tokenizer(), sizes=self.sizes)
        self.assertNotIn(0, [r["source_index"] for r in chosen["train"]])

    def test_long_tokens_fail_without_truncation(self):
        class Long(Tokenizer):
            def __call__(self, text, *, truncation):
                self.test = truncation
                return {"input_ids": list(range(65))}
        with self.assertRaisesRegex(e.InputError, "insufficient"):
            p.choose(self.rows, Long(), sizes=self.sizes)
        self.assertFalse((self.root / "cohort-before-labels.json").exists())

    def test_pixel_duplicates_across_reencoded_files_not_selected(self):
        raw = self.rows["train"][0]["image"]["bytes"]
        image = p.media.image_bytes(raw)
        alternate = io.BytesIO()
        image.save(alternate, format="PNG", compress_level=0)
        self.rows["test"][0]["image"]["bytes"] = alternate.getvalue()
        chosen = p.choose(self.rows, Tokenizer(), sizes={s: 3 for s in p.SIZES})
        all_pixels = [r["pixel_sha256"] for entries in chosen.values() for r in entries]
        self.assertEqual(len(all_pixels), len(set(all_pixels)))

    def test_missing_embedded_image_never_fetches_path(self):
        self.rows["train"][0]["image"] = {"path": "https://untrusted.invalid/media", "bytes": None}
        with self.assertRaises(e.InputError):
            p.choose(self.rows, Tokenizer(), sizes=self.sizes)

    def test_bad_label_fails_after_label_free_cohort_not_resampling(self):
        with self.assertRaises(e.InputError):
            p.stage_cases(self.root, self.rows, lambda *_: True, Tokenizer(), sizes=self.sizes)
        self.assertTrue((self.root / "cohort-before-labels.json").exists())
        self.assertFalse((self.root / "dataset.jsonl").exists())

    def test_reader_receives_no_target_and_preserves_raw_text(self):
        data, _ = p.stage_cases(self.root, self.rows, lambda *_: 0, Tokenizer(), sizes=self.sizes)
        cases, _ = p.media.read_cases(self.root, data, 4)
        class Generator:
            tokenizer = Tokenizer()
            identity = "fixture-not-pretrained"
            def generate(self, texts, *, maximum_new_tokens):
                assert maximum_new_tokens == 32
                assert all("No image is provided." in s for s in texts)
                return {"model_digest": self.identity, "outputs": [{"text": "not a valid answer"}]}
        seal = p.text_reader(Generator(), cases, self.root / "text")
        result = e.decode(e.bound_file(self.root / "text/predictions.json", seal))
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(all(r["text"] == "not a valid answer" for r in result["rows"]))
        self.assertNotIn("accuracy", result)

    def test_failed_reader_retains_started_record_without_success(self):
        data, _ = p.stage_cases(self.root, self.rows, lambda *_: 0, Tokenizer(), sizes=self.sizes)
        cases, _ = p.media.read_cases(self.root, data, 4)
        class Broken:
            tokenizer = Tokenizer()
            identity = "fixture"
            def generate(self, *a, **kw):
                raise RuntimeError("actual invocation failed")
        with self.assertRaises(RuntimeError):
            p.text_reader(Broken(), cases, self.root / "text")
        self.assertTrue((self.root / "text/started-000.json").exists())
        self.assertFalse((self.root / "text/predictions.json").exists())

    def test_publisher_git_and_lfs_digest_checked(self):
        path = self.root / "member"
        path.write_bytes(b"original")
        blob = hashlib.sha1(b"blob 8\0original").hexdigest()
        sha = e.sha(b"original")
        for item in (SimpleNamespace(size=8, lfs=None, blob_id=blob),
                     SimpleNamespace(size=8, lfs={"sha256": sha})):
            self.assertEqual(publisher_file(path, item)["sha256"], sha)
            path.write_bytes(b"tampered")
            with self.assertRaises(ValueError):
                publisher_file(path, item)
            path.write_bytes(b"original")

    def test_unknown_size_or_absent_publisher_hash_rejected(self):
        path = self.root / "member"
        path.write_bytes(b"one")
        for item in (SimpleNamespace(size=None), SimpleNamespace(size=3)):
            with self.assertRaises(ValueError):
                publisher_file(path, item)


class ControlScoreTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "controls.json"
        self.cases = [e.Case(str(i), "one-correlated-group", "holdout", None, 0, "scope", str(i)) for i in range(4)]
        self.labels = {str(i): i % 2 for i in range(4)}
        x = torch.arange(32, dtype=torch.float32).reshape(8, 4) / 32
        x[:, -1] = torch.arange(8) % 2
        y = torch.arange(8) % 2
        self.value = {"split": controls.split_trial(x, y, x[:4], classes=2, steps=2),
            "system2": controls.recurrent_trial(x.unsqueeze(1), y, x.unsqueeze(1), y,
                x[:4].unsqueeze(1), classes=2, steps=2), "holdout_case_ids": [str(i) for i in range(4)]}

    def tearDown(self):
        self.temp.cleanup()

    def evaluate(self, value=None):
        seal = e.write_once(self.path, self.value if value is None else value)
        return evaluate_controls(self.path, seal, self.labels, self.cases, classes=2)

    def test_real_trained_controls_are_scored_after_seal(self):
        result = self.evaluate()
        self.assertEqual(result["system2"]["paired"]["adaptive"]["declared_groups"], 1)
        self.assertIsNone(result["system2"]["paired"]["adaptive"]["independent_group_count"])
        self.assertEqual(result["system2"]["cell_transitions"]["no_recurrence"], 4)
        self.assertFalse(result["system2"]["matched_compute"])
        self.assertFalse(result["production_accepted"])

    def test_missing_arm_not_reported_as_zero(self):
        self.value["system2"]["predictions"].pop("adaptive")
        with self.assertRaises(e.InputError):
            self.evaluate()

    def test_missing_or_duplicate_case_rejected(self):
        self.value["holdout_case_ids"] = ["0", "1", "2", "2"]
        with self.assertRaises(e.InputError):
            self.evaluate()

    def test_forged_work_count_rejected_even_with_new_seal(self):
        self.value["system2"]["costs"]["adaptive"]["cell_transitions"] = 0
        with self.assertRaises(e.InputError):
            self.evaluate()

    def test_illegal_class_width_or_nan_rejected(self):
        for row in ([0.5, 0.5, 0], [float("nan"), 0]):
            with self.assertRaises(e.InputError):
                summarize({"arm": [row]}, [0], ["g"], classes=2)

    def test_pairwise_gains_losses_and_ties(self):
        pred = {"base": [[1., 0.], [0., 1.], [1., 0.]],
                "new": [[0., 1.], [1., 0.], [1., 0.]]}
        result = summarize(pred, [1, 1, 0], ["a", "a", "b"], classes=2, control="base")
        self.assertEqual([result["paired"]["new"][k] for k in ("gains", "losses", "ties")], [1, 1, 1])

    def test_single_modality_trained_once_and_frozen_retained(self):
        x = torch.arange(24, dtype=torch.float32).reshape(4, 2, 3) / 24
        inputs = {"text": (x, torch.ones(4, 2, dtype=torch.bool), torch.tensor([[0, 1]] * 4))}
        result = controls.modality_trial(inputs, torch.tensor([0, 1, 0, 1]), inputs, classes=2, steps=2)
        self.assertEqual(set(result["predictions"]), {"text"})
        self.assertEqual(set(result["frozen_predictions"]), {"text"})
        self.assertNotEqual(result["costs"]["text"]["sha256"], result["costs"]["text"]["same_init_frozen"]["sha256"])
        self.assertEqual(result["costs"]["text"]["examples_processed"], 8)

    def test_control_file_drift_rejected(self):
        seal = e.write_once(self.path, self.value)
        self.path.write_bytes(b"{}\n")
        with self.assertRaises(e.InputError):
            evaluate_controls(self.path, seal, self.labels, self.cases, classes=2)


if __name__ == "__main__":
    unittest.main()
