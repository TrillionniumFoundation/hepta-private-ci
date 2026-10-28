"""Train-source mechanism check of full-size draws, physical codecs and replay.

The public feature provider is deliberately a fixed zero-vector test double;
this isolates the new generator/codec likelihood contract. This is neither a
complete native episode nor a semantic observer or capability qualification.
"""
import argparse
import copy
import json
from pathlib import Path
import time

import numpy as np
import torch

from .data_sources import digest, save
from .natural_model import LAW, NaturalGenerator, parameter_hash
from .natural_port import NaturalPort, array_hash
from .natural_proxy_data import LazyProxyDataset
from .natural_train import generator_rows
from .profile_contract import cpu_seconds


class FixedPublicFeatures:
    def features(self, frames):
        return np.zeros((len(frames), 2222), np.float32)

    def audio_features(self, audio):
        return np.zeros((len(audio), 1551), np.float32)


def check(assets, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(6821)
    plan, rows = generator_rows(assets, "generator_train")
    directory, event = rows[0]
    model = NaturalGenerator(copy.deepcopy(plan["ontology"])).eval()
    provider = FixedPublicFeatures()
    adapter = NaturalPort(model=model, event_directory=directory, tsm=provider, pann=provider,
                          seed=7631, route="stochastic", actor_features=False)
    cpu, started = cpu_seconds(), time.monotonic()
    public = adapter.prepare()
    context = {"video_features": np.zeros((len(rows), 2222), np.float32),
               "audio_features": np.zeros((len(rows), 1551), np.float32)}
    lazy = LazyProxyDataset(rows, plan["ontology"], context)
    lazy_public, lazy_truth = lazy[0]
    if array_hash(lazy_public) != array_hash(adapter.public):
        raise ValueError("Lazy warmstart public tensors differ from actual prepare tensors")
    with np.load(directory / "EVENT.npz") as reference:
        expected = {"video": torch.tensor(reference["target_video"].transpose(0, 3, 1, 2).copy()[None]).float()/255,
                    "image": torch.tensor(reference["target_image"].transpose(2, 0, 1).copy()[None]).float()/255,
                    "audio": torch.tensor(reference["target_audio"].copy()[None]),
                    "action": torch.tensor([model.action_ids.index(event["action_id"])]),
                    "sound": torch.tensor([model.sound_ids.index(event["sound_id"])])}
    if array_hash(lazy_truth) != array_hash(expected):
        raise ValueError("Lazy warmstart targets differ from the frozen source tensors/labels")
    with torch.no_grad():
        full = model(adapter.public)
        interpolation = model.interpolate(adapter.public)
        equality = {key: torch.equal(full["base_"+key], interpolation[key]) for key in ("image", "video", "audio")}
        equality.update({key: torch.equal(full[key], interpolation[key]) for key in ("action_logits", "sound_logits")})
    if not all(equality.values()):
        raise ValueError("Efficient fixed interpolation changed its registered output law")
    del full, interpolation
    samples, receipts = [], []
    for number in range(2):
        folder = output / ("draw-" + str(number))
        folder.mkdir()
        def register(logp, descriptor):
            samples.append({**descriptor, "log_probability": float(logp.detach())})
        def write_file(modality, suffix, payload):
            path = folder / (modality + suffix)
            with path.open("xb") as stream:
                stream.write(payload)
            return str(path)
        with torch.no_grad():
            receipt = adapter.emit("keep" if number == 0 else "swap", public, folder, register, write_file)
        receipts.append(receipt)
    if (samples[0]["rng_after_sha256"] != samples[1]["rng_before_sha256"]
            or samples[0]["sampled_sha256"] == samples[1]["sampled_sha256"]):
        raise ValueError("Retry did not make a fresh draw on the continued RNG stream")
    score, replay = adapter.replay_score()
    if [row["sampled_sha256"] for row in replay["checks"]] != [row["sampled_sha256"] for row in samples]:
        raise ValueError("Replay omitted or reordered an actual pre-codec sample")
    gradients = torch.autograd.grad(score, tuple(model.parameters()), allow_unused=True)
    if not all(torch.isfinite(value).all() for value in gradients if value is not None):
        raise ValueError("Nonfinite actual sampled-action score gradient")
    report = {"schema": "hepta.closure.natural-mechanism-check.v1", "source_protocol_sha256": plan["protocol_sha256"],
        "training_source_id": event["source_id"], "training_event_npz_sha256": digest((directory / "EVENT.npz").read_bytes()),
        "parameter_sha256": parameter_hash(model), "law": LAW, "actual_full_size_draws": 2,
        "public_tensor_identity_lazy_vs_prepare": True, "target_tensor_identity_lazy_vs_source": True,
        "efficient_interpolation_exact": equality, "registered_samples": samples, "replay": replay,
        "finite_actual_score_gradient": True, "physical_four_media_receipts": receipts,
        "cpu_seconds": cpu_seconds()-cpu, "wall_seconds": time.monotonic()-started,
        "real_native_episode": False, "pretrained_backbones_exercised": False,
        "semantic_or_generation_efficacy_claim": False, "development_or_holdout_access": False,
        "implementation_sha256": {name: digest((Path(__file__).parent/name).read_bytes()) for name in
            ("natural_execution_check.py", "natural_model.py", "natural_port.py", "natural_proxy_data.py", "natural_media.py")},
        "passed": True}
    save(output / "RESULT.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = check(args.assets, args.output)
    print(json.dumps({"passed": result["passed"], "cpu_seconds": result["cpu_seconds"],
                      "actual_full_size_draws": result["actual_full_size_draws"]}))
