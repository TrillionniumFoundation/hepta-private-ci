"""Frozen native Whisper control sharing the actual Cell encoder invocation.

No label/prompt argument enters decoding. A transient encoder-output clone is
consumed once then discarded. This is a comparison, not a production router.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import torch

from experiments.shared_stem_cell import execution as e, media_execution as media

WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
MAX_NEW_TOKENS = 16


def digit(text, *, punctuation=False):
    """Whole-output mapping only: no substring, synonym, or answer-informed repair."""
    if not isinstance(text, str) or len(text.encode()) > 1024:
        raise e.InputError("bounded original transcription required")
    value = text.strip().lower()
    if punctuation and value.endswith((".", "!", "?")):
        value = value[:-1].rstrip()
    if value in WORDS:
        return WORDS.index(value)
    return int(value) if value in tuple(str(i) for i in range(10)) else None


@torch.no_grad()
def decode_shared(model, tokenizer, hidden):
    """Stock generate(), supplied existing states; fail before ANY encoder retry."""
    from transformers.modeling_outputs import BaseModelOutput
    if (model.training or any(p.requires_grad for p in model.parameters())
            or not isinstance(hidden, torch.Tensor) or hidden.device.type != "cpu"
            or hidden.dtype != torch.float32 or hidden.shape != (1, 1500, model.config.d_model)
            or not 1 <= model.config.d_model <= 384 or not bool(torch.isfinite(hidden).all())):
        raise e.InputError("frozen bounded Whisper encoder states required")
    before = e.tensor_digest(hidden)
    config = deepcopy(model.generation_config)
    # Reset cross-utterance/fallback options, retaining publisher token suppression.
    config.do_sample = False
    config.num_beams = 1
    config.num_return_sequences = 1
    config.max_new_tokens = MAX_NEW_TOKENS
    config.return_dict_in_generate = True
    config.output_scores = False
    config.output_attentions = False
    config.output_hidden_states = False
    identity = e.sha(e.canonical(config.to_dict()))
    calls = []

    def forbid_encoder(_module, _args):
        raise e.InputError("native control attempted to re-encode shared observation")

    def count_decoder(_module, args, kwargs):
        tokens = kwargs.get("input_ids", args[0] if args else None)
        if not isinstance(tokens, torch.Tensor) or tokens.ndim != 2 or tokens.shape[0] != 1:
            raise e.InputError("one bounded decoder sequence required")
        calls.append(list(tokens.shape))
        if len(calls) > MAX_NEW_TOKENS:
            raise e.InputError("native decoder exceeded fixed forward budget")

    guard = model.model.encoder.register_forward_pre_hook(forbid_encoder)
    counter = model.model.decoder.register_forward_pre_hook(count_decoder, with_kwargs=True)
    try:
        with e.measured() as timing:
            result = model.generate(encoder_outputs=BaseModelOutput(last_hidden_state=hidden),
                generation_config=config, return_timestamps=False, temperature=0.0,
                condition_on_prev_tokens=False, compression_ratio_threshold=None,
                logprob_threshold=None, no_speech_threshold=None,
                force_unique_generate_call=True)
    finally:
        guard.remove()
        counter.remove()
    tokens = result.sequences
    if (not isinstance(tokens, torch.Tensor) or tokens.dtype != torch.long
            or tokens.device.type != "cpu" or tokens.ndim != 2 or tokens.shape[0] != 1
            or not 1 <= tokens.shape[1] <= MAX_NEW_TOKENS + 4 or not calls
            or bool((tokens < 0).any()) or bool((tokens >= model.config.vocab_size).any())
            or int(tokens[0, 0]) != model.config.decoder_start_token_id
            or e.tensor_digest(hidden) != before):
        raise e.InputError("native output budget/prefix or shared state mutation")
    text = tokenizer.decode(tokens[0], skip_special_tokens=True)
    digit(text)  # validate size; malformed semantic output remains a scored failure
    return {"raw_text": text, "token_ids": tokens[0].tolist(),
        "token_sha256": e.tensor_digest(tokens), "encoder_state_sha256": before,
        "generation_config_sha256": identity, "decoder_forward_shapes": calls,
        "decoder_forwards": len(calls), "decoder_work": timing,
        "additional_encoder_forwards": 0, "max_new_tokens": MAX_NEW_TOKENS,
        "eos_observed": model.config.eos_token_id in tokens[0, 1:].tolist()}


class NativeControl:
    """Read-only wrapper of existing LocalTowers; never exposes labels to model."""
    def __init__(self, towers, tokenizer, targets, output):
        self.towers, self.tokenizer, self.targets = towers, tokenizer, dict(targets)
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        self.records, self.seal = {}, None
        if (set(towers.models) != {"whisper"} or not 1 <= len(targets) <= 64
                or len(set(targets.values())) != len(targets)
                or any(not isinstance(v, str) or len(v) != 64
                       or any(ch not in "0123456789abcdef" for ch in v)
                       for pair in targets.items() for v in pair)):
            raise e.InputError("closed audio-only holdout control required")
        self.model_before = e.parameters(towers.models["whisper"])
        e.write_once(self.output / "plan.json", {"targets": targets,
            "model_identity": towers.identities["whisper"], "max_new_tokens": MAX_NEW_TOKENS,
            "source_sha256": e.sha(Path(__file__).read_bytes()),
            "scoring": "whole digit/word; separately allow one terminal .!?; invalid counts wrong",
            "no_audio_synthesis": True, "production_accepted": False})

    def __getattr__(self, name):
        return getattr(self.towers, name)

    def encode(self, name, item, root):
        if name != "audio":
            raise e.InputError("native control only accepts standalone audio")
        digest = item["sha256"]
        if digest not in self.targets:
            return self.towers.encode(name, item, root)
        if digest in self.records:
            raise e.InputError("duplicate native observation")
        case_id = self.targets[digest]
        e.write_once(self.output / (case_id + ".started.json"), {"case_id": case_id,
            "audio_sha256": digest, "status": "entered_not_completed"})
        captured = []

        def capture(_module, _args, value):
            if captured:
                raise e.InputError("multiple encoder forwards for one audio")
            hidden = value.last_hidden_state
            if (not isinstance(hidden, torch.Tensor) or hidden.dtype != torch.float32
                    or hidden.device.type != "cpu" or hidden.shape != (1, 1500, self.towers.models["whisper"].config.d_model)):
                raise e.InputError("missing or unbounded actual encoder states")
            captured.append(hidden.detach().clone().contiguous())

        handle = self.towers.models["whisper"].model.encoder.register_forward_hook(capture)
        try:
            with e.measured() as shared_work:
                value, stamps = self.towers.encode(name, item, root)
        finally:
            handle.remove()
        if len(captured) != 1:
            raise e.InputError("native comparison requires one physical encoder call")
        # Use the unpooled states, not fabricated states reconstructed from landmarks.
        record = {"case_id": case_id, "audio_sha256": digest,
            "landmark_sha256": e.tensor_digest(value), "shared_encode_work": shared_work,
            **decode_shared(self.towers.models["whisper"], self.tokenizer, captured[0])}
        e.write_once(self.output / (case_id + ".result.json"), record)
        self.records[digest] = record
        if len(self.records) == len(self.targets):
            self.seal = e.write_once(self.output / "predictions.json", {
                "records": [self.records[k] for k in self.targets],
                "model_identity": self.towers.identities["whisper"],
                "simulated_towers": self.towers.simulated, "production_accepted": False})
        return value, stamps

    def close(self):
        self.towers.close()
        if self.seal is None or e.parameters(self.towers.models["whisper"]) != self.model_before:
            raise e.InputError("incomplete native comparison or frozen weights changed")


def factory_for(root, manifest, base_factory=media.LocalTowers):
    """Case IDs configure coverage, never a transcript prompt or label feature."""
    from transformers import WhisperTokenizerFast
    cases, _labels = media.read_cases(root, manifest["dataset"], manifest["classes"])
    if any(set(case.inputs) != {"audio"} for case in cases) or manifest["classes"] != 10:
        raise e.InputError("registered spoken digit cohort required")
    selected = [case for case in cases if case.split in {"holdout", "retention"}]
    targets = {case.inputs["audio"]["sha256"]: case.case_id for case in selected}
    if len(targets) != len(selected):
        raise e.InputError("duplicate native target waveform")
    created = []

    def factory(model_root, models):
        towers = base_factory(model_root, models)
        tokenizer = WhisperTokenizerFast.from_pretrained(model_root / models["whisper"]["path"],
            local_files_only=True, trust_remote_code=False)
        wrapped = NativeControl(towers, tokenizer, targets, root / "native-control")
        created.append(wrapped)
        return wrapped
    return factory, created


def summarize(root, manifest, wrapped):
    """Compare sealed ORIGINAL outputs; native control cannot change Cell selection."""
    native = e.decode(e.bound_file(root / "native-control/predictions.json", wrapped.seal))
    media_report = e.decode((root / "execution/report.json").read_bytes())
    head = e.decode(e.bound_file(root / "execution/predictions.json", media_report["prediction_sha256"]))
    cases, labels = media.read_cases(root, manifest["dataset"], manifest["classes"])
    expected = [c for c in cases if c.split in {"holdout", "retention"}]
    if ([r["case_id"] for r in native["records"]] != [c.case_id for c in expected]
            or head["case_ids"] != [c.case_id for c in expected]
            or any(r["audio_sha256"] != c.inputs["audio"]["sha256"]
                   for r, c in zip(native["records"], expected))):
        raise e.InputError("native/Cell predictions do not cover identical heldout rows")
    gold = [labels[c.case_id] for c in expected]
    candidate = head["predictions"]["calibrated_mixture"]
    probabilities = torch.tensor(candidate)
    if (probabilities.shape != (len(gold), 10) or not bool(torch.isfinite(probabilities).all())
            or bool(((probabilities < 0) | (probabilities > 1)).any())
            or not bool(torch.allclose(probabilities.sum(-1), torch.ones(len(gold)), atol=1e-5))
            or native["model_identity"] != media_report["model_identities"]["whisper"]):
        raise e.InputError("invalid or mismatched same-sample comparison")
    flags = [max(range(10), key=lambda j: p[j]) == y for p, y in zip(candidate, gold)]
    scores = {}
    for name, allow in (("whole_output", False), ("one_terminal_punctuation", True)):
        guesses = [digit(row["raw_text"], punctuation=allow) for row in native["records"]]
        hits = [g == y for g, y in zip(guesses, gold)]
        scores[name] = {"cases": len(gold), "correct": sum(hits), "unparsed": guesses.count(None),
            "cell_correct": sum(flags), "native_gains": sum(a and not b for a, b in zip(hits, flags)),
            "native_losses": sum(b and not a for a, b in zip(hits, flags))}
    model = wrapped.towers.models["whisper"]
    report = {"schema": "hepta.shared-whisper-native-control.v1", "scores": scores,
        "native_prediction_sha256": wrapped.seal,
        "cell_prediction_sha256": media_report["prediction_sha256"],
        "calibration_selection_sha256": media_report["calibration_selection_sha256"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "native_records": len(gold), "extra_encoder_forwards": 0,
        "whole_model_parameters": wrapped.model_before,
        "encoder_parameters": e.parameters(model.model.encoder)["parameters"],
        "decoder_forwards": sum(r["decoder_forwards"] for r in native["records"]),
        "decode_wall_ns": sum(r["decoder_work"]["wall_ns"] for r in native["records"]),
        "media_encoding_span_includes_native_decoding": True,
        "simulated_towers": native["simulated_towers"],
        "independent_evaluation": False, "audio_synthesis_completed": False,
        "production_accepted": False}
    e.write_once(root / "native-control/report.json", report)
    return report
