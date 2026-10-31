"""Execute pinned neural media training; preserve every update and failure cost."""

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
from ...v7_media.models import AcousticDecoder, SpeechObserver, TemporalPixelDecoder, video_targets, weights_sha256
from .network import VideoInput
from .sources import save_json, sha, source_pins, speech_role


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "cache", "manifest", "image-observer", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name("protocol.json").read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    pins = source_pins()
    registration = {"protocol_sha256": sha(Path(__file__).with_name("protocol.json")),
                    "source_sha256": pins, "config": config, "started_unix_ns": time.time_ns(),
                    "inputs": {k: {"path": str(getattr(args, k)), "sha256": sha(getattr(args, k))}
                               for k in ("archive", "manifest", "image_observer")},
                    "torch": torch.__version__, "threads": 1, "test_opened": False}
    save_json(args.output / "registration.json", registration)
    reports, frozen = {}, {}
    try:
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        seed = config["seed"]
        generator = torch.Generator().manual_seed(seed)

        def fit(name, model, objective, steps):
            model.train()
            before = weights_sha256(model)
            optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"])
            wall, process_cpu = time.perf_counter_ns(), time.process_time_ns()
            history, maximum_gradient = [], 0.
            for step in range(steps):
                optimizer.zero_grad(set_to_none=True)
                loss = objective(model)
                if not torch.isfinite(loss):
                    raise ValueError(f"Nonfinite {name} loss")
                loss.backward()
                maximum_gradient = max(maximum_gradient, sum(float(p.grad.detach().abs().sum())
                    for p in model.parameters() if p.grad is not None))
                torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                optimizer.step()
                history.append(float(loss.detach()))
                if step % 100 == 0 or step + 1 == steps:
                    print(json.dumps({"stage": name, "step": step + 1, "loss": history[-1]}), flush=True)
            after = weights_sha256(model)
            if before == after or maximum_gradient == 0:
                raise RuntimeError("Actual parameter training did not occur")
            model.eval().requires_grad_(False)
            path = args.output / (name + ".pt")
            torch.save({"state_dict": model.state_dict(), "weights_sha256": after,
                        "architecture": type(model).__name__}, path)
            reports[name] = {"steps": steps, "initial_parameters_sha256": before,
                             "parameters_sha256": after, "checkpoint_sha256": sha(path),
                             "parameter_count": sum(p.numel() for p in model.parameters()),
                             "gradient_abs_sum_max": maximum_gradient, "loss_history": history,
                             "wall_ns": time.perf_counter_ns() - wall,
                             "cpu_ns": time.process_time_ns() - process_cpu}
            frozen[name] = model
            save_json(args.output / (name + ".training.json"), reports[name])

        source_roles = {}
        for offset, (name, role) in enumerate((("reward", "reward"), ("audit", "audit"),
                                                ("audio_input", "generator"))):
            wav, labels, metadata = speech_role(args.archive, role)
            source_roles[role] = metadata
            spectra = speech_spectrum(wav)
            torch.manual_seed(seed + offset)
            def classification(model):
                indices = torch.randint(len(labels), (config["batch_size"],), generator=generator)
                return F.cross_entropy(model(spectra[indices]), labels[indices])
            fit(name, SpeechObserver(), classification, config["steps"][name])
        # The last role loaded above is the generator-only acoustic source.
        reward = frozen["reward"]
        torch.manual_seed(seed + 10)
        def acoustic_loss(model):
            indices = torch.randint(len(labels), (config["batch_size"],), generator=generator)
            conditions = F.one_hot(labels[indices], 10).float()
            noise = torch.randn((len(indices), model.latent), generator=generator)
            decoded, kl = model(spectra[indices], conditions, noise)
            prior = model.decode(conditions)
            return F.l1_loss(decoded, spectra[indices]) + .0005 * kl + .15 * F.cross_entropy(reward(prior), labels[indices])
        fit("acoustic", AcousticDecoder(), acoustic_loss, config["steps"]["acoustic"])
        del wav, spectra, labels
        corpus = load_roles(args.cache, args.manifest, roles=(config["image_fit_role"],))
        images = corpus.splits[config["image_fit_role"]].images.float() / 255
        digits = corpus.splits[config["image_fit_role"]].labels
        image_observer, _ = load_reward(args.image_observer, sha(args.image_observer))
        def video_batch():
            indices = torch.randint(len(images), (config["batch_size"], 2), generator=generator)
            y = digits[indices]
            return F.one_hot(y, 10).float(), video_targets(images[indices[:, 0]], images[indices[:, 1]]), y
        torch.manual_seed(seed + 20)
        def video_loss(model):
            conditions, target, y = video_batch()
            logits = model(conditions)
            semantic = image_observer(logits.sigmoid().flatten(0, 1))
            return F.binary_cross_entropy_with_logits(logits, target) + .15 * F.cross_entropy(semantic, y.repeat_interleave(10, 1).flatten())
        fit("video", TemporalPixelDecoder(), video_loss, config["steps"]["video"])
        torch.manual_seed(seed + 30)
        def video_input_loss(model):
            _, pixels, y = video_batch()
            return F.cross_entropy(model(pixels).flatten(0, 1), y.flatten())
        fit("video_input", VideoInput(), video_input_loss, config["steps"]["video_input"])
        save_json(args.output / "speech-source-roles.json", source_roles)
        if source_pins() != pins:
            raise RuntimeError("Training source changed during execution")
        save_json(args.output / "complete.json", {"status": "completed", "models": reports,
                  "registration_sha256": sha(args.output / "registration.json"),
                  "source_roles_sha256": sha(args.output / "speech-source-roles.json"),
                  "test_opened": False, "wall_ns": time.perf_counter_ns() - started,
                  "cpu_ns": time.process_time_ns() - cpu})
    except BaseException as error:
        save_json(args.output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
                  "completed_models": list(reports)})
        raise


if __name__ == "__main__":
    main()
