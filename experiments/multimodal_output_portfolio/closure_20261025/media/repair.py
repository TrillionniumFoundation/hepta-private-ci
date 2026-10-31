"""Train concrete development repairs without opening reserved final sources."""

import argparse
import json
from pathlib import Path
import time
import traceback

import torch
from torch.nn import functional as F

from ...v7.evaluation import load_reward
from ...v7.sources import load_roles
from ...v7_media.corpus import speech_spectrum
from ...v7_media.models import AcousticDecoder, video_targets, weights_sha256
from .repaired import EventVideoDecoder, RobustSpeech
from .sources import save_json, sha, source_pins, speech_role


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "cache", "manifest", "image-observer", "previous", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name("repair_protocol.json").read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu, pins = time.perf_counter_ns(), time.process_time_ns(), source_pins()
    pins["repair_protocol.json"] = sha(Path(__file__).with_name("repair_protocol.json"))
    registration = {"source_sha256": pins, "config": config, "started_unix_ns": time.time_ns(),
                    "archive_sha256": sha(args.archive), "previous_complete_sha256": sha(args.previous / "complete.json"),
                    "manifest_sha256": sha(args.manifest), "image_observer_sha256": sha(args.image_observer)}
    save_json(args.output / "registration.json", registration)
    reports, models = {}, {}
    try:
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        rng = torch.Generator().manual_seed(config["seed"])
        def fit(name, model, objective):
            before, t, c = weights_sha256(model), time.perf_counter_ns(), time.process_time_ns()
            model.train().requires_grad_(True)
            optimizer = torch.optim.AdamW(model.parameters(), lr=config["learning_rate"], weight_decay=1e-4)
            history, gradient = [], 0.
            for step in range(config["steps"][name]):
                optimizer.zero_grad(set_to_none=True)
                loss = objective(model)
                if not torch.isfinite(loss):
                    raise ValueError("Nonfinite training loss")
                loss.backward()
                gradient = max(gradient, sum(float(p.grad.abs().sum()) for p in model.parameters() if p.grad is not None))
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                optimizer.step()
                history.append(float(loss.detach()))
                if step % 250 == 0 or step + 1 == config["steps"][name]:
                    print(json.dumps({"stage": name, "step": step + 1, "loss": history[-1]}), flush=True)
            model.eval().requires_grad_(False)
            after = weights_sha256(model)
            if after == before or gradient == 0:
                raise RuntimeError("No actual learning")
            path = args.output / (name + ".pt")
            torch.save({"state_dict": model.state_dict(), "weights_sha256": after, "architecture": type(model).__name__}, path)
            reports[name] = {"path": str(path), "checkpoint_sha256": sha(path), "architecture": type(model).__name__,
                             "initial_parameters_sha256": before, "parameters_sha256": after, "steps": len(history),
                             "gradient_abs_sum_max": gradient, "loss_history": history,
                             "wall_ns": time.perf_counter_ns() - t, "cpu_ns": time.process_time_ns() - c}
            models[name] = model
            save_json(args.output / (name + ".training.json"), reports[name])
        for offset, (name, role) in enumerate((("reward", "reward"), ("audit", "audit"), ("audio_input", "generator"))):
            wav, labels, _ = speech_role(args.archive, role)
            spectra = speech_spectrum(wav)
            torch.manual_seed(config["seed"] + offset)
            def classify(model):
                indices = torch.randint(len(labels), (config["batch_size"],), generator=rng)
                x = torch.roll(spectra[indices], int(torch.randint(-10, 11, (), generator=rng)), -1).clone()
                x += .025 * torch.randn(x.shape, generator=rng)
                f, t = int(torch.randint(121, (), generator=rng)), int(torch.randint(93, (), generator=rng))
                x[:, :, f:f + 8] = x.mean()
                x[:, :, :, t:t + 8] = x.mean()
                return F.cross_entropy(model(x), labels[indices])
            fit(name, RobustSpeech(), classify)
        acoustic = AcousticDecoder()
        prior_record = torch.load(args.previous / "acoustic.pt", map_location="cpu", weights_only=True)
        acoustic.load_state_dict(prior_record["state_dict"], strict=True)
        def acoustic_loss(model):
            indices = torch.randint(len(labels), (config["batch_size"],), generator=rng)
            p = F.one_hot(labels[indices], 10).float()
            out, kl = model(spectra[indices], p, torch.randn((len(indices), 16), generator=rng))
            return F.l1_loss(out, spectra[indices]) + .0005 * kl + .15 * F.cross_entropy(models["reward"](model.decode(p)), labels[indices])
        fit("acoustic", acoustic, acoustic_loss)
        corpus = load_roles(args.cache, args.manifest, roles=("train",))
        images, digits = corpus.splits["train"].images.float() / 255, corpus.splits["train"].labels
        observer, _ = load_reward(args.image_observer, sha(args.image_observer))
        torch.manual_seed(config["seed"] + 30)
        def video_loss(model):
            ids = torch.randint(len(images), (config["batch_size"], 2), generator=rng)
            y = digits[ids]
            output = model(F.one_hot(y, 10).float())
            target = video_targets(images[ids[:, 0]], images[ids[:, 1]])
            return F.binary_cross_entropy_with_logits(output, target) + .15 * F.cross_entropy(observer(output.sigmoid().flatten(0, 1)), y.repeat_interleave(10, 1).flatten())
        fit("video", EventVideoDecoder(), video_loss)
        previous = json.loads((args.previous / "complete.json").read_text())
        reports["video_input"] = {**previous["models"]["video_input"], "path": str(args.previous / "video_input.pt"), "architecture": "VideoInput", "new_updates": 0}
        current = source_pins()
        current["repair_protocol.json"] = sha(Path(__file__).with_name("repair_protocol.json"))
        if current != pins:
            raise RuntimeError("Frozen repair source changed")
        save_json(args.output / "complete.json", {"status": "completed", "models": reports, "test_opened": False,
                  "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
    except BaseException as error:
        save_json(args.output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu})
        raise


if __name__ == "__main__":
    main()
