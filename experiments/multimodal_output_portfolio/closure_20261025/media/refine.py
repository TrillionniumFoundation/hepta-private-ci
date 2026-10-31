"""Train source-disjoint auditory models and a coupled learned motion decoder."""

import argparse
import json
from pathlib import Path
import time
import traceback

import torch
from torch.nn import functional as F

from ...v7.sources import load_roles
from ...v7_media.corpus import speech_spectrum
from ...v7_media.models import weights_sha256
from .coherent import CoherentVideo, MelSpeech, motion_targets
from .sources import save_json, sha, source_pins, speech_role


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "cache", "manifest", "previous", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    config_path = Path(__file__).with_name("refine_protocol.json")
    config = json.loads(config_path.read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu, pins = time.perf_counter_ns(), time.process_time_ns(), source_pins()
    pins[str(config_path.relative_to(Path(__file__).resolve().parents[2]))] = sha(config_path)
    save_json(args.output / "registration.json", {"config": config, "source_sha256": pins,
              "started_unix_ns": time.time_ns(), "archive_sha256": sha(args.archive),
              "manifest_sha256": sha(args.manifest), "previous_complete_sha256": sha(args.previous / "complete.json")})
    for relative, expected in pins.items():
        path = Path(__file__).resolve().parents[2] / relative
        if sha(path) != expected:
            raise ValueError("Source changed at registration")
        target = args.output / "frozen-source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    reports = {}
    try:
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        rng = torch.Generator().manual_seed(config["seed"])

        def fit(name, model, objective):
            before, started, process = weights_sha256(model), time.perf_counter_ns(), time.process_time_ns()
            model.train().requires_grad_(True)
            optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=1e-4)
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, config["steps"][name], eta_min=config["learning_rate"] * config["cosine_minimum_fraction"])
            history, maximum_gradient = [], 0.
            for step in range(config["steps"][name]):
                optimizer.zero_grad(set_to_none=True)
                loss = objective(model)
                if not torch.isfinite(loss):
                    raise ValueError("Nonfinite refinement loss")
                loss.backward()
                maximum_gradient = max(maximum_gradient, sum(float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None))
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                optimizer.step()
                scheduler.step()
                history.append(float(loss.detach()))
                if step % 400 == 0 or step + 1 == config["steps"][name]:
                    print(json.dumps({"stage": name, "step": step + 1, "loss": history[-1]}), flush=True)
            model.eval().requires_grad_(False)
            after = weights_sha256(model)
            if before == after or maximum_gradient <= 0:
                raise RuntimeError("Refinement did not learn")
            path = args.output / (name + ".pt")
            torch.save({"state_dict": model.state_dict(), "weights_sha256": after, "architecture": type(model).__name__}, path)
            reports[name] = {"path": str(path), "architecture": type(model).__name__, "checkpoint_sha256": sha(path),
                             "parameters_sha256": after, "initial_parameters_sha256": before,
                             "trainable_parameters": sum(p.numel() for p in model.parameters()),
                             "steps": len(history), "loss_history": history, "gradient_abs_sum_max": maximum_gradient,
                             "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - process}
            save_json(args.output / (name + ".training.json"), reports[name])
        for offset, (name, role) in enumerate((("audit", "audit"), ("audio_input", "generator"))):
            waveforms, labels, metadata = speech_role(args.archive, role)
            save_json(args.output / (name + ".sources.json"), metadata)
            torch.manual_seed(config["seed"] + offset)
            model = MelSpeech()
            with torch.no_grad():
                features = model.front_end(speech_spectrum(waveforms))

            def classify(network):
                indices = torch.randint(len(labels), (config["batch_size"],), generator=rng)
                x = torch.roll(features[indices], int(torch.randint(-4, 5, (), generator=rng)), -1).clone()
                x += .025 * torch.randn(x.shape, generator=rng)
                f, t = int(torch.randint(37, (), generator=rng)), int(torch.randint(61, (), generator=rng))
                x[:, :, f:f + 4] = 0
                x[:, :, :, t:t + 4] = 0
                return F.cross_entropy(network.features(x), labels[indices])
            fit(name, model, classify)
        corpus = load_roles(args.cache, args.manifest, roles=("train",))
        images, digits = corpus.splits["train"].images.float() / 255, corpus.splits["train"].labels
        torch.manual_seed(config["seed"] + 10)

        def video_loss(model):
            indices = torch.randint(len(images), (config["batch_size"], 2), generator=rng)
            pixels = torch.cat((images[indices[:, 0]], images[indices[:, 1]]), -1)
            condition = F.one_hot(digits[indices], 10).float()
            return F.mse_loss(model(condition, pixels).sigmoid(), motion_targets(pixels))
        fit("video", CoherentVideo(), video_loss)
        previous = json.loads((args.previous / "complete.json").read_text())
        for name in ("reward", "acoustic", "video_input"):
            reports[name] = {**previous["models"][name], "new_updates": 0}
        current = source_pins()
        current[str(config_path.relative_to(Path(__file__).resolve().parents[2]))] = sha(config_path)
        if current != pins:
            raise RuntimeError("Frozen refinement changed during training")
        save_json(args.output / "complete.json", {"status": "completed", "models": reports, "test_opened": False,
                  "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
    except BaseException as error:
        save_json(args.output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "wall_ns": time.perf_counter_ns() - wall})
        raise


if __name__ == "__main__":
    main()
