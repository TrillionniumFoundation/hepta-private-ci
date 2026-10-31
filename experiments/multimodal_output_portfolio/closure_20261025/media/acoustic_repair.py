"""Correct a measured posterior/prior mismatch without independent-audit gradients."""

import argparse
import json
from pathlib import Path
import time
import traceback

import torch
from torch.nn import functional as F

from ...v7_media.corpus import speech_spectrum, spectrum_waveform
from ...v7_media.models import AcousticDecoder, weights_sha256
from .coherent import MelSpeech
from .sources import save_json, sha, source_pins, speech_role


def actual_dependencies():
    # Freeze the complete imported experiment dependency set, allowing unrelated
    # waveform-reference engineering to proceed in a separate process.
    paths = source_pins()
    prefix = "closure_20261025/media/"
    local = {"acoustic_repair.py", "coherent.py", "sources.py", "protocol.json", "__init__.py"}
    return {key: value for key, value in paths.items() if not key.startswith(prefix) or key[len(prefix):] in local}


def align_voice(spectra):
    result = []
    for value, energy in zip(spectra, (10 * spectra[:, 0]).clamp(-24, 8).exp().mean(1)):
        active = torch.where(energy > energy.max() * .01)[0]
        voice = F.interpolate(value[None, :, :, int(active[0]):int(active[-1]) + 1],
                              size=(129, 81), mode="bilinear", align_corners=False)[0]
        result.append(F.pad(voice, (10, 10), value=-2.302585093))
    return torch.stack(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "previous", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    protocol_path = Path(__file__).with_name("acoustic_repair_protocol.json")
    config = json.loads(protocol_path.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu, pins = time.perf_counter_ns(), time.process_time_ns(), actual_dependencies()
    root = Path(__file__).resolve().parents[2]
    pins[str(protocol_path.relative_to(root))] = sha(protocol_path)
    save_json(args.output / "registration.json", {"source_sha256": pins, "config": config,
              "archive_sha256": sha(args.archive), "previous_complete_sha256": sha(args.previous / "complete.json"),
              "started_unix_ns": time.time_ns(), "audit_checkpoint_loaded": False})
    for relative, expected in pins.items():
        source = root / relative
        if sha(source) != expected:
            raise ValueError("Source changed at registration")
        destination = args.output / "frozen-source" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    reports = {}
    try:
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        rng = torch.Generator().manual_seed(config["seed"])

        def fit(name, model, objective):
            before, started, process = weights_sha256(model), time.perf_counter_ns(), time.process_time_ns()
            model.train().requires_grad_(True)
            optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=1e-4)
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, config["steps"][name], eta_min=config["learning_rate"] * .1)
            losses, gradient = [], 0.
            for step in range(config["steps"][name]):
                optimizer.zero_grad(set_to_none=True)
                loss = objective(model, step)
                if not torch.isfinite(loss):
                    raise ValueError("Nonfinite canonical-voice objective")
                loss.backward()
                gradient = max(gradient, sum(float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None))
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                optimizer.step()
                scheduler.step()
                losses.append(float(loss.detach()))
                if step % 400 == 0 or step + 1 == config["steps"][name]:
                    print(json.dumps({"stage": name, "step": step + 1, "loss": losses[-1]}), flush=True)
            model.eval().requires_grad_(False)
            after = weights_sha256(model)
            if after == before or gradient <= 0:
                raise RuntimeError("No actual acoustic learning")
            path = args.output / (name + ".pt")
            torch.save({"state_dict": model.state_dict(), "weights_sha256": after, "architecture": type(model).__name__}, path)
            reports[name] = {"path": str(path), "checkpoint_sha256": sha(path), "architecture": type(model).__name__,
                             "parameters_sha256": after, "initial_parameters_sha256": before,
                             "steps": len(losses), "loss_history": losses, "gradient_abs_sum_max": gradient,
                             "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - process}
            save_json(args.output / (name + ".training.json"), reports[name])
            return model

        wav, labels, metadata = speech_role(args.archive, "reward")
        save_json(args.output / "reward.sources.json", metadata)
        torch.manual_seed(config["seed"])
        reward = MelSpeech()
        with torch.no_grad():
            features = reward.front_end(speech_spectrum(wav))

        def classify(model, step):
            ids = torch.randint(len(labels), (config["batch_size"],), generator=rng)
            x = torch.roll(features[ids], int(torch.randint(-4, 5, (), generator=rng)), -1).clone()
            x += .025 * torch.randn(x.shape, generator=rng)
            f, t = int(torch.randint(37, (), generator=rng)), int(torch.randint(61, (), generator=rng))
            x[:, :, f:f + 4] = 0
            x[:, :, :, t:t + 4] = 0
            return F.cross_entropy(model.features(x), labels[ids])
        reward = fit("reward", reward, classify)
        wav, labels, metadata = speech_role(args.archive, "generator")
        ids = [i for i, row in enumerate(metadata) if row["speaker"] == config["canonical_voice"]]
        if len(ids) != config["generator_recordings"]:
            raise ValueError("Canonical voice source count changed")
        targets, labels = align_voice(speech_spectrum(wav[ids])), labels[ids]
        save_json(args.output / "acoustic.sources.json", [metadata[i] for i in ids])
        torch.manual_seed(config["seed"] + 1)

        def acoustic_loss(model, step):
            ids = torch.randint(len(labels), (config["batch_size"],), generator=rng)
            condition = F.one_hot(labels[ids], 10).float()
            posterior, kl = model(targets[ids], condition, torch.randn((len(ids), 16), generator=rng))
            prior = model.decode(condition)
            actual_waveform = spectrum_waveform(prior, config["seed"] + step, iterations=4)
            return (.5 * F.l1_loss(posterior, targets[ids]) + .5 * F.l1_loss(prior, targets[ids])
                    + .005 * kl + .05 * F.cross_entropy(reward(speech_spectrum(actual_waveform)), labels[ids]))
        fit("acoustic", AcousticDecoder(), acoustic_loss)
        previous = json.loads((args.previous / "complete.json").read_text())
        for name in ("audit", "audio_input", "video", "video_input"):
            reports[name] = {**previous["models"][name], "new_updates": 0}
        current = actual_dependencies()
        current[str(protocol_path.relative_to(root))] = sha(protocol_path)
        if current != pins:
            raise RuntimeError("Actual acoustic training dependency changed")
        save_json(args.output / "complete.json", {"status": "completed", "models": reports, "test_opened": False,
                  "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
    except BaseException as error:
        save_json(args.output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "wall_ns": time.perf_counter_ns() - wall})
        raise


if __name__ == "__main__":
    main()
