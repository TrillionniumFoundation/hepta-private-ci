"""Local schema/identity contracts only; never loads real emotion-model weights."""

import argparse
import hashlib
import importlib.abc
import json
from pathlib import Path
import sys

import numpy as np
from . import contracts, model


HERE = Path(__file__).resolve().parent


def run(out):
    count, attempts = 0, []
    sources = {str(p.relative_to(HERE)): contracts.sha(p) for p in
               (Path(__file__), HERE / "contracts.py", HERE / "model.py")}

    def check(condition, label):
        nonlocal count
        count += 1
        if not condition:
            raise AssertionError(label)

    def reject(call, label, types=(ValueError,)):
        try:
            call()
        except types:
            check(True, label)
        else:
            raise AssertionError(label + " was not rejected")

    class NoScientificModelImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split(".")[0] in ("torch", "transformers", "safetensors"):
                attempts.append(fullname)
                raise AssertionError("Unexpected model runtime import: " + fullname)

    blocker = NoScientificModelImports()
    check(not any(n.split(".")[0] in ("torch", "transformers", "safetensors") for n in sys.modules),
          "fresh no-model-runtime process")
    sys.meta_path.insert(0, blocker)
    try:
        base = np.linspace(-1., 1., 16000, dtype=np.float32)
        for tail in (np.full(99, np.nan), np.full(99, 100000.)):
            check(np.array_equal(model.bounded(np.r_[base, tail]), base), "bounded ignores future suffix")
        for value in (base[:-1], np.r_[np.nan, base[1:]], base[None]):
            reject(lambda value=value: model.bounded(value), "invalid accepted prefix")
        prefix = "wav2vec2.encoder.pos_conv_embed.conv."
        old = {prefix + "weight_g": np.ones((1, 1, 3)), prefix + "weight_v": np.ones((2, 2, 3)),
               "classifier.dense.bias": np.zeros(2)}
        expected = {prefix + "parametrizations.weight.original0": old[prefix + "weight_g"],
                    prefix + "parametrizations.weight.original1": old[prefix + "weight_v"],
                    "classifier.dense.bias": old["classifier.dense.bias"]}
        converted, mapping = model.canonical_weights(old, expected)
        check(set(converted) == set(expected) and len(mapping) == 2, "two exact legacy aliases")
        check(all(np.array_equal(converted[k], v) for k, v in expected.items()), "alias values preserved")
        check(model.canonical_weights(expected, expected)[1] == [], "modern keys preserved")
        mixed = dict(old, **{prefix + "parametrizations.weight.original0": np.ones((1, 1, 3))})
        reject(lambda: model.canonical_weights(mixed, expected), "mixed alias collision")
        reject(lambda: model.canonical_weights({k: v for k, v in old.items() if not k.endswith("weight_g")}, expected), "missing key")
        reject(lambda: model.canonical_weights(dict(old, extra=np.zeros(1)), expected), "unexpected key")
        reject(lambda: model.canonical_weights(dict(old, **{prefix + "weight_g": np.zeros(4)}), expected), "wrong shape")
        url = "https://user:private@cdn.hf.co/object?X-Amz-Signature=hidden&token=secret#fragment"
        check(contracts.safe_url(url) == "https://cdn.hf.co/object", "URL drops credentials/query/fragment")
        clean = contracts.safe_error(ValueError("Download failed: " + url))
        check(all(token not in clean for token in ("private", "hidden", "secret", "fragment", "user:")), "error sanitized")
        out.parent.mkdir(parents=True, exist_ok=True)
        fixture = out.parent / (out.stem + "_synthetic_fixture")
        fixture.mkdir(exist_ok=False)
        config = {"model_type": "wav2vec2", "hidden_size": 1024, "num_hidden_layers": 12,
                  "num_attention_heads": 16, "intermediate_size": 4096, "conv_bias": True,
                  "feat_extract_norm": "layer", "do_stable_layer_norm": True, "pooling_mode": "mean",
                  "problem_type": "regression", "conv_kernel": [10, 3, 3, 3, 3, 2, 2],
                  "conv_stride": [5, 2, 2, 2, 2, 2, 2], "conv_dim": [512] * 7,
                  "id2label": {"0": "arousal", "1": "dominance", "2": "valence"}}
        processor = {"feature_extractor_type": "Wav2Vec2FeatureExtractor", "sampling_rate": 16000,
                     "feature_size": 1, "do_normalize": True, "return_attention_mask": True,
                     "padding_side": "right", "padding_value": 0.0}
        (fixture / "README.md").write_text("---\nlicense: cc-by-nc-sa-4.0\n---\nSynthetic contract fixture; no real model.\n")
        (fixture / "config.json").write_text(json.dumps(config))
        (fixture / "preprocessor_config.json").write_text(json.dumps(processor))
        (fixture / "model.safetensors").write_bytes(b"synthetic invalid checkpoint; never parsed")
        check(contracts.metadata_contract(fixture)["research_only"], "synthetic metadata contract")
        seal = {"model": contracts.MODEL, "revision": contracts.REVISION,
                "files": {name: {"bytes": (fixture / name).stat().st_size, "sha256": contracts.sha(fixture / name)}
                          for name in contracts.FILES}, "synthetic_fixture": True}
        (fixture / "ASSET_SEAL.json").write_text(json.dumps(seal, indent=2) + "\n")
        reject(lambda: model.EmotionEncoder(fixture), "wrong official checkpoint identity")
        reject(lambda: model.EmotionEncoder(fixture / "absent"), "missing model assets", (FileNotFoundError,))
        seal["revision"] = "wrong"
        (fixture / "ASSET_SEAL.json").write_text(json.dumps(seal, indent=2) + "\n")
        reject(lambda: model.EmotionEncoder(fixture), "wrong immutable revision")
        pcm = json.loads((HERE / "inputs/PCM_IDENTITY.json").read_text())
        path = HERE / "inputs/WAVEFORMS.npz"
        check(contracts.sha(path) == pcm["waveforms_npz_sha256"], "actual transport identity")
        check(contracts.sha(HERE / "inputs/COHORT.json") == pcm["copied_cohort_sha256"], "actual cohort identity")
        with np.load(path, allow_pickle=False) as arrays:
            waveforms = arrays["waveforms"]
            check(waveforms.shape == (288, 16000) and waveforms.dtype == np.float32, "actual waveform dimensions")
            check(np.isfinite(waveforms).all() and len(set(arrays["actor"].tolist())) == 24, "actual finite24actor inputs")
            check(hashlib.sha256(waveforms.tobytes()).hexdigest() == pcm["array_sha256"], "actual whole PCM array SHA")
            for index, row in enumerate(pcm["details"]):
                check(str(arrays["clip"][index]) == row["clip"] and str(arrays["actor"][index]) == row["actor"], "actual row identity")
                check(hashlib.sha256(waveforms[index].tobytes()).hexdigest() == row["waveform_sha256"], "actual PCM row SHA")
                clock = row["source_clock"]
                check(clock["padded_samples"] == 0 and clock["accepted_samples"] == 16000, "no manufactured short-window padding")
                check(clock["future_pcm_used"] is False and clock["full_recording_normalization"] is False, "accepted-only preparation")
        check(attempts == [], "no model runtime import attempted")
        check(all(contracts.sha(HERE / name) == digest for name, digest in sources.items()), "tested source unchanged")
    finally:
        sys.meta_path.remove(blocker)
    contracts.write(out, {"schema": "hcsn-v13-emotion-local-contracts.v1", "checks": count, "status": "PASS",
        "source_sha256": sources, "forbidden_model_import_attempts": attempts,
        "synthetic_fixture": "Toy NumPy key/shape arrays and explicitly synthetic local metadata, no pretrained state",
        "actual_transport_rows": 288, "actual_emotion_model_forwards": 0, "real_emotion_weights_loaded": False})
    print(json.dumps({"status": "PASS", "checks": count, "actual_emotion_model_forwards": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args().out)
