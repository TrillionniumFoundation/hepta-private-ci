"""Real control flow/optimization with generated waveforms and a SYNTHETIC tower."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from torch import nn

from experiments.shared_stem_cell import speech_cascade as c, speech_control as speech
from experiments.shared_stem_cell import public_audio as audio, execution as e
from experiments.shared_stem_cell import test_speech_control as native_fixture
from experiments.shared_stem_cell import test_public_audio as audio_fixture


class FixedHead(nn.Module):
    def __init__(self, confidence=0.9):
        super().__init__()
        self.register_buffer("logits", torch.tensor([[confidence] + [(1-confidence)/9]*9]).log())
        self.calls = 0
        self.eval()
    def forward(self, inputs):
        self.calls += 1
        return self.logits


class CascadeTowers(native_fixture.Towers):
    def encode(self, name, item, root):
        value, stamps = super().encode(name, item, root)
        return torch.cat([value, torch.zeros(len(value), 4)], -1), stamps


class CascadeTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous_module = sys.modules.get("transformers.modeling_outputs")
        sys.modules["transformers.modeling_outputs"] = SimpleNamespace(
            BaseModelOutput=lambda **kw: SimpleNamespace(**kw))
    def tearDown(self):
        if self.previous_module is None:
            sys.modules.pop("transformers.modeling_outputs", None)
        else:
            sys.modules["transformers.modeling_outputs"] = self.previous_module
        self.temp.cleanup()
    def inputs(self):
        return c.audio_inputs([(torch.zeros(2, 8), torch.tensor([0, 20000]))], 8)
    def probabilities(self):
        p = torch.zeros(4, 10)
        for row, j, confidence in zip(p, (0, 2, 2, 2), (.95, .4, .9, .3)):
            row.fill_((1-confidence)/9)
            row[j] = confidence
        return p
    def test_calibration_grid_respects_both_baselines_and_charges_calls(self):
        result = c.select_threshold(self.probabilities(), ["zero", "one", "nine", "three"], torch.arange(4))
        self.assertEqual(result["calibration_correct_floor"], 3)
        self.assertEqual(result["threshold"], .5)
        self.assertEqual(result["grid"][result["selected_index"]],
                         {"threshold": .5, "cases": 4, "correct": 4, "native_calls": 2})
    def test_all_fast_retained_when_native_has_no_calibration_advantage(self):
        result = c.select_threshold(self.probabilities(), ["invalid"]*4, torch.arange(4))
        self.assertEqual(result["threshold"], 0.)
        self.assertEqual(result["grid"][0]["native_calls"], 0)
    def test_calibration_rejects_missing_and_invalid_rows(self):
        with self.assertRaises(e.InputError):
            c.select_threshold(self.probabilities(), ["zero"], torch.arange(4))
        p = self.probabilities(); p[-1, 0] = float("nan")
        with self.assertRaises(e.InputError): c.select_threshold(p, ["zero"]*4, torch.arange(4))
    def test_fast_path_never_calls_decoder(self):
        decode = unittest.mock.Mock(side_effect=AssertionError("unexpected native call"))
        row, native = c.foreground(FixedHead(), self.inputs(), .8, decode)
        decode.assert_not_called()
        self.assertFalse(row["native_requested"])
        self.assertEqual(row["cascade_guess"], 0)
        self.assertIsNone(native)
    def test_slow_path_calls_once_and_keeps_invalid_transcription(self):
        decode = unittest.mock.Mock(return_value={"raw_text": "one two"})
        row, _ = c.foreground(FixedHead(.3), self.inputs(), .5, decode)
        decode.assert_called_once_with()
        self.assertIsNone(row["cascade_guess"])
    def test_full_native_endpoint_handles_certainty_and_boundaries(self):
        decode = unittest.mock.Mock(return_value={"raw_text": "seven"})
        row, _ = c.foreground(FixedHead(1.), self.inputs(), 2., decode)
        self.assertEqual(row["cascade_guess"], 7)
        self.assertEqual(decode.call_count, 1)
    def test_invalid_policy_fails_before_head_or_decoder(self):
        head, decode = FixedHead(), unittest.mock.Mock()
        for threshold in (True, .333, float("nan")):
            with self.assertRaises(e.InputError): c.foreground(head, self.inputs(), threshold, decode)
        self.assertEqual(head.calls, 0)
        decode.assert_not_called()
    def test_invalid_features_fail_before_model(self):
        head, decode = FixedHead(), unittest.mock.Mock()
        inputs = self.inputs(); inputs["audio"][0][0,0,0] = float("nan")
        with self.assertRaises(e.InputError): c.foreground(head, inputs, .8, decode)
        self.assertEqual(head.calls, 0)
    def test_fixed_padding_does_not_depend_on_later_utterance_length(self):
        self.assertEqual(c.audio_inputs([(torch.zeros(1,8),torch.tensor([0]))],8)["audio"][0].shape, (1,32,8))
        with self.assertRaises(e.InputError):
            c.audio_inputs([(torch.zeros(33,8),torch.arange(33))],8)
    def test_decoder_exception_propagates_without_guess_repair(self):
        decode = unittest.mock.Mock(side_effect=RuntimeError("native unavailable"))
        with self.assertRaises(RuntimeError): c.foreground(FixedHead(.3), self.inputs(), .5, decode)

    def study(self, path):
        helper = audio_fixture.PublicAudioTests(methodName="test_fixed_cohort_is_class_balanced_and_speaker_disjoint")
        helper.root = self.root
        created = []
        def factory(root, models):
            towers = CascadeTowers(root, models); created.append(towers); return towers
        def stage(*args, **kw): return {"path": "model", "revision": "a"*40, "files": {}}
        original = c.run
        def run(root, manifest, **kwargs):
            return original(root, manifest, _tokenizer=native_fixture.Tokenizer(), **kwargs)
        with patch.object(c, "run", side_effect=run):
            result = audio.run(path, cascade_control=True, _acquire=helper.staged, _stage=stage, _towers=factory)
        return result, created[0]
    def test_whole_pipeline_actual_skips_shadow_charged_and_unchanged_training(self):
        path = self.root/"study"
        native_decode = speech.decode_shared
        observed = []
        def decode(model, tokenizer, hidden):
            if model.generate_calls >= 40:
                self.assertTrue((path/"cascade/routing-selection.json").is_file())
                # Fixture unparsed native outputs make calibration choose fast-only.
                self.assertGreater(len(list((path/"cascade").glob("*.foreground.json"))), len(observed))
                observed.append(1)
            return native_decode(model, tokenizer, hidden)
        with patch.object(speech,"decode_shared",side_effect=decode): result, towers = self.study(path)
        report = e.decode((path/"cascade/report.json").read_bytes())
        selection = e.decode((path/"cascade/head-selection.json").read_bytes())
        self.assertEqual(report["foreground_native_calls"], 0)
        self.assertEqual(report["shadow_only_native_calls"], 40)
        self.assertEqual(towers.calls, {"whisper":240})
        self.assertEqual(towers.models["whisper"].generate_calls, 80)
        self.assertEqual(selection["costs"]["actual_optimizer_steps"],80)
        self.assertEqual(result["scores"]["cascade"], result["scores"]["fast"])
        self.assertEqual({s["cases"] for s in report["scores"].values()}, {40})
        self.assertFalse(report["equal_quality_resource_advantage_established"])
        self.assertTrue((path/"cascade/legacy-controls.json").is_file())
    def test_changed_holdout_labels_do_not_change_threshold_or_predictions(self):
        path = self.root/"base"
        self.study(path)
        # Change labels only AFTER staging but before run; fitting still sees the same train/calibration.
        original = c.media.read_cases
        def changed(*args, **kwargs):
            cases, labels = original(*args, **kwargs)
            labels = deepcopy(labels)
            for case in cases:
                if case.split == "holdout": labels[case.case_id] = (labels[case.case_id]+1)%10
            return cases, labels
        with patch.object(c.media,"read_cases",side_effect=changed): self.study(self.root/"changed")
        a = e.decode((path/"cascade/routing-selection.json").read_bytes())
        b = e.decode((self.root/"changed/cascade/routing-selection.json").read_bytes())
        for key in ("threshold","selected_index","grid","head_sha256"): self.assertEqual(a[key],b[key])
        pa=e.decode((path/"cascade/predictions.json").read_bytes())
        pb=e.decode((self.root/"changed/cascade/predictions.json").read_bytes())
        self.assertEqual([r["cascade_guess"] for r in pa["rows"]],[r["cascade_guess"] for r in pb["rows"]])
    def test_failed_shadow_keeps_foreground_but_does_not_publish_success(self):
        path = self.root/"shadow-failure"
        actual = speech.decode_shared
        def fail(model, tokenizer, hidden):
            if model.generate_calls >= 40:
                raise RuntimeError("synthetic shadow failure")
            return actual(model, tokenizer, hidden)
        with patch.object(speech, "decode_shared", side_effect=fail), self.assertRaises(RuntimeError):
            self.study(path)
        self.assertEqual(len(list((path/"cascade").glob("*.foreground.json"))), 1)
        self.assertFalse((path/"cascade/report.json").exists())
        self.assertTrue((path/"cascade/failure.json").exists())

    def test_exclusive_modes_reject_before_acquisition(self):
        acquire = unittest.mock.Mock()
        with self.assertRaises(e.InputError):
            audio.run(self.root/"bad", native_control=True, cascade_control=True, _acquire=acquire)
        acquire.assert_not_called()


if __name__ == "__main__": unittest.main()
