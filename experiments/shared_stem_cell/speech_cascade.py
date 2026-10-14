"""Calibrated spoken-content fast/slow execution; not NDU or deployment authority.

One frozen encoder per waveform. Foreground skips unrequested decodes. A separately
charged shadow control DOES decode those waveforms afterwards, preserving the
strong native comparator without pretending the entire experiment saved its work.
"""
from pathlib import Path

import torch

from experiments.shared_stem_cell import calibrated_fusion as fusion
from experiments.shared_stem_cell import execution as e, media_execution as media
from experiments.shared_stem_cell import speech_control as speech

THRESHOLDS = (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 2.0)


def audio_inputs(observations, width):
    """Fixed 32 slots: held-out lengths never determine the trained Head shape."""
    e.integer(width, 1, 384, "audio width")
    if not isinstance(observations, list) or not 1 <= len(observations) <= 256:
        raise e.InputError("bounded audio observation batch required")
    x = torch.zeros(len(observations), 32, width)
    mask = torch.zeros(len(observations), 32, dtype=torch.bool)
    times = torch.zeros(len(observations), 32, dtype=torch.long)
    for i, (value, stamps) in enumerate(observations):
        if (not isinstance(value, torch.Tensor) or not isinstance(stamps, torch.Tensor)
                or value.dtype != torch.float32 or value.device.type != "cpu" or value.ndim != 2
                or not 1 <= len(value) <= 32 or value.shape[1] != width
                or stamps.dtype != torch.long or stamps.device.type != "cpu"
                or stamps.shape != (len(value),)):
            raise e.InputError("declared audio landmark profile required")
        x[i, :len(value)], mask[i, :len(value)], times[i, :len(value)] = value, True, stamps
    inputs = {"audio": (x, mask, times)}
    fusion.validate(inputs, classes=10)
    return inputs


def select_threshold(probabilities, transcripts, labels):
    """Calibration only; fixed grid, full-output parser, never a held-out target."""
    if (not isinstance(probabilities, torch.Tensor) or probabilities.device.type != "cpu"
            or probabilities.dtype != torch.float32 or probabilities.ndim != 2
            or probabilities.shape[1] != 10 or not 1 <= len(probabilities) <= 64
            or not isinstance(labels, torch.Tensor) or labels.dtype != torch.long
            or labels.device.type != "cpu" or labels.shape != (len(probabilities),)
            or bool(((labels < 0) | (labels > 9)).any())
            or not isinstance(transcripts, list) or len(transcripts) != len(labels)):
        raise e.InputError("complete paired calibration outputs and labels required")
    fusion.score(probabilities, labels)
    fast = probabilities.argmax(-1).tolist()
    native = [speech.digit(text) for text in transcripts]
    confidence = probabilities.max(-1).values.tolist()
    gold = labels.tolist()
    floor = max(sum(a == y for a, y in zip(fast, gold)), sum(a == y for a, y in zip(native, gold)))
    grid = []
    for threshold in THRESHOLDS:
        slow = [p < threshold for p in confidence]
        guesses = [b if s else a for a, b, s in zip(fast, native, slow)]
        grid.append({"threshold": threshold, "correct": sum(g == y for g, y in zip(guesses, gold)),
                     "native_calls": sum(slow), "cases": len(gold)})
    eligible = [i for i, row in enumerate(grid) if row["correct"] >= floor]
    index = min(eligible, key=lambda i: (grid[i]["native_calls"], -grid[i]["correct"], i))
    return {"schema": "hepta.speech-cascade-threshold.v1", "grid": grid, "selected_index": index,
        "threshold": grid[index]["threshold"], "calibration_correct_floor": floor,
        "rule": "at least both baselines' calibration correct count; fewest native calls, most correct, grid order",
        "scoring": "whole_output", "same_calibration_used_for_checkpoint_and_threshold": True,
        "confidence_is_not_certified": True, "production_accepted": False}


@torch.no_grad()
def foreground(head, inputs, threshold, decode):
    """No labels or precomputed native answer. decode is truly lazy and called at most once."""
    if type(threshold) is not float or threshold not in THRESHOLDS:
        raise e.InputError("predeclared threshold required")
    if head.training or any(p.requires_grad for p in head.parameters()):
        raise e.InputError("frozen selected Head required")
    fusion.validate(inputs, classes=10)
    if len(inputs["audio"][0]) != 1:
        raise e.InputError("one waveform per foreground call")
    with e.measured() as work:
        probabilities = head(inputs).softmax(-1)
        fusion.score(probabilities, torch.zeros(1, dtype=torch.long))
        if probabilities.shape != (1, 10):
            raise e.InputError("ten spoken-content classes required")
        p = probabilities[0].tolist()
        fast = max(range(10), key=lambda j: p[j])
        slow = max(p) < threshold
        native = decode() if slow else None
        guess = speech.digit(native["raw_text"]) if slow else fast
    return {"probabilities": p, "fast_guess": fast, "cascade_guess": guess,
            "native_requested": slow, "head_and_routing_work": work}, native


def run(root, manifest, *, _towers=media.LocalTowers, _tokenizer=None):
    """Fit once, lock route, stream held-out audio, then score all sealed outputs."""
    root = Path(root)
    output = root / "cascade"
    output.mkdir(exist_ok=False)
    manifest_raw = (root / "manifest.json").read_bytes()
    if (e.decode(manifest_raw) != manifest or manifest["classes"] != 10
            or set(manifest["models"]) != {"whisper"}):
        raise e.InputError("exact staged standalone audio manifest required")
    e.write_once(output / "plan.json", {"manifest_sha256": e.sha(manifest_raw),
        "thresholds": THRESHOLDS, "audio_slots": 32, "shadow_native_comparator": True,
        "source_sha256": e.sha(Path(__file__).read_bytes()), "production_accepted": False})
    try:
        cases, labels = media.read_cases(root, manifest["dataset"], 10)
        if any(set(c.inputs) != {"audio"} for c in cases):
            raise e.InputError("audio-only cascade inputs required")
        ids = {s: [i for i, c in enumerate(cases) if c.split == s]
               for s in ("train", "calibration", "holdout")}
        if sum(map(len, ids.values())) != len(cases):
            raise e.InputError("explicit train/calibration/holdout profile required")
        with e.measured() as loading:
            towers = _towers(root, manifest["models"])
            if _tokenizer is None:
                from transformers import WhisperTokenizerFast
                tokenizer = WhisperTokenizerFast.from_pretrained(root / manifest["models"]["whisper"]["path"],
                    local_files_only=True, trust_remote_code=False)
            else:
                tokenizer = _tokenizer
        model = towers.models["whisper"]
        model_before = e.parameters(model)
        width = model.config.d_model
        features, native_calibration, calibration_native = {}, [], []
        with e.measured() as preparation:
            for i in ids["train"] + ids["calibration"]:
                case = cases[i]
                if case.split == "train":
                    features[i] = towers.encode("audio", case.inputs["audio"], root)
                else:
                    e.write_once(output / (case.case_id + ".calibration-started.json"),
                                 {"case_id": case.case_id, "input_digest": case.input_digest})
                    value, stamps, hidden, encode_work = speech.encode_shared(towers, case.inputs["audio"], root)
                    result = speech.decode_shared(model, tokenizer, hidden)
                    features[i] = value, stamps
                    native_calibration.append(result["raw_text"])
                    calibration_native.append({"case_id": case.case_id, "encode_work": encode_work, **result})
                    e.write_once(output / (case.case_id + ".calibration-native.json"), calibration_native[-1])
                    del hidden
        cal_seal = e.write_once(output / "calibration-native.json", calibration_native)
        take = lambda which: audio_inputs([features[i] for i in ids[which]], width)
        target = lambda which: torch.tensor([labels[cases[i].case_id] for i in ids[which]], dtype=torch.long)
        models, selection = fusion.fit_calibrated(take("train"), target("train"), take("calibration"),
            target("calibration"), classes=10, steps=manifest["steps"], seed=manifest["seed"])
        head_seal = e.write_once(output / "head-selection.json", selection)
        selected = models["audio"]["selected"]
        identity = e.parameters(selected)["sha256"]
        if identity != selection["model_identities"]["audio"]["selected"]:
            raise e.InputError("selected checkpoint identity mismatch")
        with torch.no_grad():
            cal_probabilities = selected(take("calibration")).softmax(-1)
        with e.measured() as routing_selection:
            policy = select_threshold(cal_probabilities, native_calibration, target("calibration"))
        policy.update({"head_sha256": identity, "head_selection_sha256": head_seal,
            "calibration_native_sha256": cal_seal, "calibration_ids": [cases[i].case_id for i in ids["calibration"]],
            "probabilities": cal_probabilities.tolist(), "labels": target("calibration").tolist(),
            "model_identity": towers.identities["whisper"], "manifest_sha256": e.sha(manifest_raw)})
        policy_seal = e.write_once(output / "routing-selection.json", policy)
        policy = e.decode(e.bound_file(output / "routing-selection.json", policy_seal))
        rows, originals = [], []
        for i in ids["holdout"]:
            case = cases[i]
            e.write_once(output / (case.case_id + ".started.json"),
                         {"case_id": case.case_id, "input_digest": case.input_digest, "policy_sha256": policy_seal})
            with e.measured() as wall:
                value, stamps, hidden, encode_work = speech.encode_shared(towers, case.inputs["audio"], root)
                inputs = audio_inputs([(value, stamps)], width)
                routed, native = foreground(selected, inputs, policy["threshold"],
                    lambda: speech.decode_shared(model, tokenizer, hidden))
            row = {"case_id": case.case_id, "input_digest": case.input_digest, "policy_sha256": policy_seal,
                   "foreground_work": wall, "encode_work": encode_work, **routed}
            # Publish the foreground result BEFORE any shadow-only native call.
            e.write_once(output / (case.case_id + ".foreground.json"), row)
            shadow = native is None
            if shadow:
                native = speech.decode_shared(model, tokenizer, hidden)
            originals.append({"case_id": case.case_id, "shadow_only": shadow, **native})
            e.write_once(output / (case.case_id + ".native.json"), originals[-1])
            rows.append(row)
            features[i] = value, stamps
            del hidden
        prediction_seal = e.write_once(output / "predictions.json", {"rows": rows, "native": originals,
                                                                   "policy_sha256": policy_seal})
        # Preserve existing final/frozen/selected/probe controls, explicitly extra work.
        control = fusion.execute_calibrated(models, selection, take("holdout"), ["holdout"] * len(rows))
        control_seal = e.write_once(output / "legacy-controls.json", control)
        if not torch.allclose(torch.tensor([r["probabilities"] for r in rows]),
                              torch.tensor(control["predictions"]["calibrated_mixture"]), atol=1e-5, rtol=1e-5):
            raise e.InputError("streamed and batched selected Head outputs disagree")
        towers.close()
        if e.parameters(model) != model_before or e.parameters(selected)["sha256"] != identity:
            raise e.InputError("frozen weights changed")
        media.read_cases(root, manifest["dataset"], 10)
        if (root / "manifest.json").read_bytes() != manifest_raw:
            raise e.InputError("source manifest changed")
        sealed = e.decode(e.bound_file(output / "predictions.json", prediction_seal))
        gold = target("holdout").tolist()
        scores = {}
        guesses = {"fast": [r["fast_guess"] for r in sealed["rows"]],
                   "cascade": [r["cascade_guess"] for r in sealed["rows"]],
                   "native": [speech.digit(r["raw_text"]) for r in sealed["native"]]}
        for name, predictions in guesses.items():
            scores[name] = {"cases": len(gold), "correct": sum(p == y for p, y in zip(predictions, gold)),
                            "unparsed": predictions.count(None)}
        punctuated = [speech.digit(r["raw_text"], punctuation=True) for r in sealed["native"]]
        secondary = {
            "native": sum(p == y for p, y in zip(punctuated, gold)),
            "cascade": sum((p if r["native_requested"] else r["fast_guess"]) == y
                           for p, r, y in zip(punctuated, rows, gold)),
            "cases": len(gold), "threshold_reselected": False}
        paired = {}
        for name in ("fast", "native"):
            left = [p == y for p, y in zip(guesses["cascade"], gold)]
            right = [p == y for p, y in zip(guesses[name], gold)]
            paired[name] = {"gains": sum(a and not b for a, b in zip(left, right)),
                            "losses": sum(b and not a for a, b in zip(left, right))}
        calls = sum(r["native_requested"] for r in rows)
        report = {"schema": "hepta.speech-cascade-executed.v1", "policy_sha256": policy_seal,
            "prediction_sha256": prediction_seal, "legacy_controls_sha256": control_seal,
            "scores": scores, "paired_cascade_vs": paired,
            "one_terminal_punctuation_diagnostic": secondary, "evaluation_ids": [r["case_id"] for r in rows], "evaluation_labels": gold,
            "foreground_native_calls": calls, "foreground_native_skipped": len(rows) - calls,
            "shadow_only_native_calls": len(rows) - calls, "calibration_native_calls": len(calibration_native),
            "actual_total_native_calls": len(originals) + len(calibration_native),
            "foreground_decoder_forwards": sum(r["decoder_forwards"] for r in originals if not r["shadow_only"]),
            "shadow_decoder_forwards": sum(r["decoder_forwards"] for r in originals if r["shadow_only"]),
            "calibration_decoder_forwards": sum(r["decoder_forwards"] for r in calibration_native),
            "foreground_compute_wall_ns": sum(r["foreground_work"]["wall_ns"] for r in rows),
            "shadow_decoder_wall_ns": sum(r["decoder_work"]["wall_ns"] for r in originals if r["shadow_only"]),
            "foreground_timing_excludes_receipt_writes": True,
            "native_decoder_forwards": sum(r["decoder_forwards"] for r in originals + calibration_native),
            "tower_forward_calls": towers.calls, "whole_whisper_parameters": model_before,
            "selected_head_parameters": e.parameters(selected), "model_load": loading,
            "preparation_including_calibration_decode": preparation, "routing_selection_work": routing_selection,
            "legacy_control_costs": control["costs"], "simulated_towers": towers.simulated,
            "experiment_includes_shadow_work": True, "new_training_algorithm": False,
            "equal_quality_resource_advantage_established": False, "independent_evaluation": False,
            "production_accepted": False}
        e.write_once(output / "report.json", report)
        return report
    except Exception as error:
        e.write_once(output / "failure.json", {"error": type(error).__name__, "message": str(error),
                                               "production_accepted": False})
        raise


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Existing staged public-audio root")
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.root, e.decode((args.root / "manifest.json").read_bytes()))
