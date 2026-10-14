"""Native-control contracts: real Torch callbacks, explicitly synthetic decoder."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import torch
from torch import nn

from experiments.shared_stem_cell import execution as e, speech_control as c, public_audio as a
from experiments.shared_stem_cell import calibrated_fusion as f, media_execution as media
from experiments.shared_stem_cell.test_public_audio import FixtureTowers
from experiments.shared_stem_cell import test_public_audio as audio_fixtures


class Config:
    def __init__(self):
        self.do_sample = True
        self.no_timestamps_token_id = 3
    def to_dict(self):
        return dict(vars(self))


class Encoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(8), requires_grad=False)
    def forward(self, x):
        return SimpleNamespace(last_hidden_state=x * self.weight)


class Decoder(nn.Module):
    def forward(self, input_ids):
        return input_ids


class FakeModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = nn.Module()
        self.model.encoder, self.model.decoder = Encoder(), Decoder()
        self.config = SimpleNamespace(d_model=8, vocab_size=20, decoder_start_token_id=1, eos_token_id=2)
        self.generation_config = Config()
        self.bad = None
        self.generate_calls = 0
        self.eval().requires_grad_(False)
    def generate(self, **kwargs):
        self.generate_calls += 1
        self.kwargs = kwargs
        hidden = kwargs["encoder_outputs"].last_hidden_state
        if self.bad == "encoder": self.model.encoder(hidden)
        if self.bad == "mutate": hidden.add_(1)
        if self.bad == "raise": raise RuntimeError("synthetic decoder failure")
        for i in range(3):
            self.model.decoder(input_ids=torch.ones(1, 2 if i == 0 else 1, dtype=torch.long))
        return SimpleNamespace(sequences=torch.tensor([[1, 3, 7, 2]] if self.bad != "tokens" else [[1]*25]))


class Tokenizer:
    text = " Seven."
    def decode(self, tokens, *, skip_special_tokens):
        assert skip_special_tokens
        return self.text


class Towers(FixtureTowers):
    def __init__(self, root, models):
        super().__init__(root, models)
        self.models = {"whisper": FakeModel()}
    def encode(self, name, item, root):
        self.models["whisper"].model.encoder(torch.ones(1, 1500, 8))
        return super().encode(name, item, root)


class SpeechControlTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.modules = patch.dict(sys.modules, {"transformers.modeling_outputs":
            SimpleNamespace(BaseModelOutput=lambda **kwargs: SimpleNamespace(**kwargs))})
        self.modules.start()
    def tearDown(self):
        self.modules.stop()
        self.tmp.cleanup()
    def test_mapping_keeps_invalid_outputs_in_denominator(self):
        self.assertEqual(c.digit(" SEVEN "), 7)
        self.assertIsNone(c.digit("seven."))
        self.assertEqual(c.digit("seven.", punctuation=True), 7)
        for text in ("", "one two", "someone", "7.0", "oh", "three..", "three apples", "7 8"):
            self.assertIsNone(c.digit(text, punctuation=True))
    def test_existing_states_and_real_hooks_no_encoder_work(self):
        model = FakeModel(); hidden = torch.ones(1, 1500, 8)
        original = deepcopy(model.generation_config.to_dict())
        result = c.decode_shared(model, Tokenizer(), hidden)
        self.assertEqual(result["decoder_forward_shapes"], [[1, 2], [1, 1], [1, 1]])
        self.assertEqual(result["additional_encoder_forwards"], 0)
        self.assertEqual(result["raw_text"], " Seven.")
        self.assertEqual(model.generation_config.to_dict(), original)
        self.assertNotIn("input_features", model.kwargs)
        self.assertNotIn("prompt_ids", model.kwargs)
    def test_reencoding_refused_and_hooks_removed(self):
        model = FakeModel(); model.bad = "encoder"
        with self.assertRaisesRegex(e.InputError, "re-encode"):
            c.decode_shared(model, Tokenizer(), torch.ones(1, 1500, 8))
        self.assertFalse(model.model.encoder._forward_pre_hooks)
        self.assertFalse(model.model.decoder._forward_pre_hooks)
    def test_preflight_rejects_invalid_state_before_generate(self):
        model = FakeModel()
        for hidden in (torch.zeros(2,1500,8), torch.zeros(1,10,8), torch.ones(1,1500,8).double(),
                       torch.full((1,1500,8),float("nan"))):
            with self.assertRaises(e.InputError): c.decode_shared(model, Tokenizer(), hidden)
        self.assertEqual(model.generate_calls, 0)
    def test_corrupt_or_mutating_decoder_output_rejected(self):
        for bad in ("mutate", "tokens"):
            model = FakeModel(); model.bad = bad
            with self.assertRaises(e.InputError): c.decode_shared(model, Tokenizer(), torch.ones(1,1500,8))
    def test_decoder_exception_does_not_leak_hook(self):
        model = FakeModel(); model.bad = "raise"
        with self.assertRaises(RuntimeError): c.decode_shared(model, Tokenizer(), torch.ones(1,1500,8))
        self.assertFalse(model.model.encoder._forward_pre_hooks)
        self.assertFalse(model.model.decoder._forward_pre_hooks)
    def test_unfrozen_model_rejected(self):
        model = FakeModel().train()
        with self.assertRaises(e.InputError): c.decode_shared(model, Tokenizer(), torch.ones(1,1500,8))
        self.assertEqual(model.generate_calls, 0)
    def fixture(self, output, native):
        helper = audio_fixtures.PublicAudioTests(methodName="test_fixed_cohort_is_class_balanced_and_speaker_disjoint")
        helper.root = self.root
        wrapped = []
        def factory_for(root, manifest, base_factory):
            cases, _ = media.read_cases(root, manifest["dataset"], 10)
            targets = {case.inputs["audio"]["sha256"]: case.case_id for case in cases if case.split == "holdout"}
            def factory(model_root, models):
                item = c.NativeControl(Towers(model_root, models), Tokenizer(), targets, root / "native-control")
                wrapped.append(item)
                return item
            return factory, wrapped
        def stage(*args, **kwargs):
            return {"path": "model", "kind": "whisper", "revision": "a"*40, "files": {}}
        original_execute = f.execute_calibrated
        def execute(*args, **kwargs):
            if native:
                self.assertTrue((output / "native-control/predictions.json").is_file())
                self.assertEqual(len(wrapped[0].records), 40)
            return original_execute(*args, **kwargs)
        with patch.object(c, "factory_for", side_effect=factory_for), patch.object(f,"execute_calibrated",side_effect=execute):
            report = a.run(output, native_control=native, _acquire=helper.staged, _stage=stage, _towers=Towers)
        return report, wrapped
    def test_full_pipeline_seal_native_before_holdout_and_preserve_head_predictions(self):
        report, wrapped = self.fixture(self.root/"native", True)
        plain, _ = self.fixture(self.root/"plain", False)
        p = e.decode((self.root/"native/execution/predictions.json").read_bytes())
        q = e.decode((self.root/"plain/execution/predictions.json").read_bytes())
        for key in ("predictions", "frozen_predictions", "modality_interventions"):
            if key != "modality_interventions": self.assertEqual(p[key], q[key])
        score = report["native_control"]["scores"]
        self.assertEqual(score["whole_output"]["correct"], 0)
        self.assertEqual(score["whole_output"]["unparsed"], 40)
        self.assertEqual(score["one_terminal_punctuation"]["correct"], 4)
        self.assertEqual(wrapped[0].calls["whisper"], 240)
        self.assertEqual(wrapped[0].models["whisper"].generate_calls, 40)
        self.assertEqual(report["native_control"]["extra_encoder_forwards"], 0)
        self.assertEqual(plain["scores"], report["scores"])
        digest = next(iter(wrapped[0].targets))
        with self.assertRaisesRegex(e.InputError,"duplicate"):
            wrapped[0].encode("audio", {"sha256":digest}, self.root)
        wrapped[0].models["whisper"].model.encoder.weight.add_(1)
        with self.assertRaisesRegex(e.InputError,"weights changed"): wrapped[0].close()
    def test_incomplete_or_wrong_target_rejected(self):
        obj = c.NativeControl(Towers(None, None), Tokenizer(), {"a"*64:"b"*64}, self.root/"native")
        with self.assertRaisesRegex(e.InputError,"incomplete"): obj.close()
        with self.assertRaises(e.InputError): obj.encode("text", {}, self.root)
    def test_native_failure_preserves_started_but_no_success_receipt(self):
        from experiments.shared_stem_cell.test_public_audio import wav_bytes
        audio = self.root/"file.wav"; audio.write_bytes(wav_bytes(rate=16000))
        digest = e.sha(audio.read_bytes())
        towers = Towers(None, None); towers.models["whisper"].bad = "raise"
        obj = c.NativeControl(towers, Tokenizer(), {digest:"a"*64}, self.root/"native")
        with self.assertRaises(RuntimeError):
            obj.encode("audio", {"path":audio.name,"sha256":digest}, self.root)
        self.assertTrue((self.root/"native"/(("a"*64)+".started.json")).is_file())
        self.assertFalse((self.root/"native/predictions.json").exists())


if __name__ == "__main__": unittest.main()
