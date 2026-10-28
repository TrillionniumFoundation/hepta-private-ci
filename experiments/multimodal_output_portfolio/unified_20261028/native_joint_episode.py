"""One train/deploy/evaluate trajectory through the real original native owner."""

from dataclasses import asdict
import hashlib
import math
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image
import torch

from ..continuation_20261027.control.client import sha
from .control import NativeController, ControlTariff
from .natural_model import draw, pack_bundle, parameter_hash, process_ffmpeg, cpu_seconds
from .profile import CostEvent, DeliveredOutcome, digest, net_return


TARIFF = ControlTariff(python_cpu_second=.001, native_cpu_second=.001, wall_second=0.)


def reopen(refs):
    with Image.open(refs["image"]) as image:
        if image.format != "PNG" or image.mode != "RGB" or image.size != (32, 32):
            raise ValueError("Physical image format changed")
        pixels = np.asarray(image, dtype=np.float32) / 255
    with wave.open(str(refs["audio"]), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()) != (1, 2, 8000, 4000):
            raise ValueError("Physical audio format changed")
        waveform = np.frombuffer(audio.readframes(4000), "<i2").astype(np.float32) / 32767
    caption = Path(refs["text"]).read_text(encoding="utf-8")
    frames = process_ffmpeg(["-i", "pipe:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                            Path(refs["video"]).read_bytes())
    video = np.frombuffer(frames, np.uint8).reshape(4, 32, 32, 3).astype(np.float32) / 255
    return {"image": pixels, "audio": waveform, "text": caption, "video": video}


def episode(*, model, checkpoint, binary, readout, calibration, profile, policy_sha256,
            directory, case, public, video, audio, seed, fault, expires, budget,
            private_score, implementation_paths, preparation_cost):
    """No optimizer update occurs here. Every actual emission contributes a score.

Fresh retry noise advances the episode generator. Public feedback reflects only
actual transport integrity. Private natural scoring runs after the owner closes.
Unexpected exceptions abort the diagnostic; an observed codec/transport failure
has declared zero utility and retains every sampled-action score and actual cost.
"""
    setup_started = cpu_seconds()
    parameter_before = parameter_hash(model)
    snapshot = torch.load(checkpoint, weights_only=True, map_location="cpu")
    if snapshot["profile_sha256"] != profile.digest or snapshot["parameter_sha256"] != parameter_before:
        raise ValueError("Actual episode model differs from the current bound snapshot/profile")
    if snapshot["vocabulary"] != model.vocabulary:
        raise ValueError("Actual token-to-UTF8 mapping differs from the bound checkpoint")
    if any(not torch.equal(value.detach().cpu(), snapshot["model"][name])
           for name, value in model.state_dict().items()):
        raise ValueError("Checkpoint tensor bytes differ from the actual episode parameters")
    controller = NativeController(binary=binary, readout=readout, calibration=calibration,
        generator_checkpoint=checkpoint, profile=profile, policy_sha256=policy_sha256, tariff=TARIFF,
        implementation_paths=(__file__, *implementation_paths))
    rng = torch.Generator().manual_seed(seed)
    log_probs, emissions = [], []
    setup_cost = CostEvent(case + ":host-snapshot-binding", .001 * (cpu_seconds() - setup_started),
                           profile.cost_unit, "host_snapshot_binding_cpu")

    def dispatch(action, public_state, output_dir):
        if public_state != public or parameter_hash(model) != parameter_before:
            raise ValueError("Public state or generator parameters changed within an episode")
        rng_before = hashlib.sha256(rng.get_state().numpy().tobytes()).hexdigest()
        values, logp = draw(model(video, audio), rng)
        # The frozen sampler omits fixed Gaussian normalizers. Restore them
        # here so receipt values are complete densities; gradients are unchanged.
        normalizer = sum(values[name][0].numel() * (math.log(sigma) + .5 * math.log(2 * math.pi))
                         for name, sigma in (("image", .015), ("video", .015), ("audio", .0015)))
        logp = logp - normalizer
        # Register the stochastic action BEFORE any codec can fail. Retry uses
        # fresh samples from the advanced generator, never a reused latent draw.
        log_probs.append(logp.sum())
        sampled = hashlib.sha256()
        for name, tensor in sorted(values.items()):
            sampled.update(name.encode())
            sampled.update(tensor.detach().cpu().numpy().tobytes())
        sample_hash = sampled.hexdigest()
        emission = {"action": action, "draw_index": len(emissions), "sampled_sha256": sample_hash,
            "rng_before_sha256": rng_before, "rng_after_sha256": hashlib.sha256(rng.get_state().numpy().tobytes()).hexdigest(),
            "log_probability": float(logp.detach().sum()), "model_parameter_sha256": parameter_before}
        emissions.append(emission)
        directory_path = Path(output_dir)
        suffixes = {"image": ".png", "audio": ".wav", "video": ".mkv", "text": ".txt"}
        failure, expected = None, {}
        try:
            _, expected, _ = pack_bundle(values, 0, model.vocabulary, directory_path)
            refs = {name: str(directory_path / (name + suffix)) for name, suffix in suffixes.items()}
            reopen(refs)
            if fault and action == "keep":
                path = Path(refs["video"])
                path.write_bytes(path.read_bytes()[:8])
            actual = {name: sha(path) for name, path in refs.items()}
            if actual != expected:
                try:
                    reopen(refs)
                except (RuntimeError, ValueError, OSError) as exc:
                    failure = {"kind": "observed_public_transport_failure", "type": type(exc).__name__}
                if failure is None:
                    raise ValueError("Injected integrity failure was not observed by physical readback")
        except (RuntimeError, ValueError, OSError) as exc:
            failure = {"kind": "actual_codec_or_readback_failure", "type": type(exc).__name__, "message": str(exc)[:300]}
            refs = {name: str(directory_path / (name + suffix)) for name, suffix in suffixes.items()
                    if (directory_path / (name + suffix)).is_file()}
            actual = {name: sha(path) for name, path in refs.items()}
        valid = failure is None
        emission.update(terminal_kind="delivered" if valid else "failed", failure=failure,
                        artifact_sha256=actual, expected_integrity_sha256=expected)
        return {"artifact_refs": refs, "artifact_sha256": actual, "public_feedback": 1 if valid else -1,
                "final_state_digest": digest({"parameter": parameter_before, "sampled": sample_hash}),
                "terminal_kind": "delivered" if valid else "failed", "generator_calls": 1,
                "delivery_units": int(valid), "failure": failure,
                "sampled_sha256": sample_hash, "emission_draw_index": len(emissions) - 1}

    run = controller.execute(directory=directory, case=case, public_state=public, dispatch=dispatch,
                             expires=expires, media_budget=budget, forecast="none", recovery="cold")
    owner_closed_ns = time.monotonic_ns()
    scoring_started_ns, scoring_cpu = time.monotonic_ns(), cpu_seconds()
    if parameter_hash(model) != parameter_before:
        raise ValueError("Parameters changed before completed trajectory scoring")
    expected_count = 1 + int(run["executed_action"] == "swap")
    if len(log_probs) != expected_count or run["measurements"]["actual_generator_calls"] != expected_count:
        raise ValueError("Trajectory score omitted an actual emission or counted an unexecuted retry")
    if expected_count == 2 and emissions[0]["sampled_sha256"] == emissions[1]["sampled_sha256"]:
        raise ValueError("Retry reused an earlier random draw; its density cannot be counted twice")
    terminal = run["final"]["terminal_kind"]
    if terminal == "delivered":
        # The private callback has no access path into NativeController context.
        observed = private_score(reopen(run["final"]["artifact_refs"]))
        utility = observed["utility"]
    else:
        observed, utility = {"utility": 0., "failure": run["final"].get("failure")}, 0.
    scoring_cost = CostEvent(case + ":terminal-natural-scoring", .001 * (cpu_seconds() - scoring_cpu),
                            profile.cost_unit, "terminal_readback_private_scoring_cpu")
    if (not isinstance(preparation_cost, CostEvent)
            or preparation_cost.kind != "per_episode_preparation_cpu"
            or preparation_cost.event_id != case + ":public-context-and-policy-preparation"):
        raise ValueError("The actual per-episode public input and policy preparation must be charged")
    costs = tuple(CostEvent(**event) for event in run["costs"]) + (preparation_cost, setup_cost, scoring_cost)
    outcome = DeliveredOutcome(public["event_id"], case, public["source_id"], utility, costs,
        tuple(sorted(run["final"]["artifact_sha256"].items())), profile.observer_sha256,
        profile.objective_sha256, profile.continuation_sha256, terminal)
    value = net_return(profile, outcome)
    log_probability = torch.stack(log_probs).sum()
    result = {"native_execution": run, "profile_sha256": profile.digest,
        "checkpoint_sha256": controller.identities["generator_checkpoint"],
        "parameter_sha256": parameter_before, "emissions": emissions, "trajectory_log_probability": float(log_probability.detach()),
        "actual_emission_scores": len(log_probs), "terminal_kind": terminal, "terminal_score": observed,
        "complete_costs": [asdict(event) for event in costs], "net_return": value,
        "owner_closed_ns": owner_closed_ns, "private_scoring_started_ns": scoring_started_ns,
        "private_target_access_phase": "after complete original-owner stop",
        "kernel_executions": run["measurements"]["actual_original_kernel_executions"],
        "cpu_parameter_derivative_estimated": False, "native_authority": "DENY_ALL"}
    return log_probability, value, result
