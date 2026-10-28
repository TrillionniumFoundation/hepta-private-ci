"""Full parameter score gradients for the real inherited text/image generator.

The original frozen encoder/gate selects a plan. Current trainable parameters
never affect that discontinuous selection. Gaussian pre-codec pixels and an
autoregressive fixed-length token law are sampled and used identically at
deployment; rendered EOS may hide later latent tokens without changing the law.
"""

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import shutil
import time

import torch

from ..v6.data import BOS, CAPTION_LENGTH, render_tokens
from ..v6.neural import NeuralState, parameter_hash, model_from_config
from ..v6.plan_training import PLANS
from ..v6.observer import write_bundle, read_bundle, observe_tensors
from .profile import CostEvent, DeliveredOutcome, net_return


STAGES = (
    ("transition", ("semantic_cell", "coupling_cell")),
    ("adapter", ("initial_image", "initial_text", "image_cell", "text_cell")),
    ("emission", ("pixel_decoder", "text_initial", "text_decoder", "text_projection")),
    ("encoder", ("token_embedding", "text_encoder", "pixel_encoder", "fuse",
                 "command_embedding", "command_film")),
)
EMISSION = {"image_logit_sigma": .03, "text_temperature": .7,
            "latent_token_steps": CAPTION_LENGTH - 1,
            "sampling": "independent_normal_logits_and_autoregressive_categorical",
            "render": "sigmoid_round_uint8_PNG_and_unrepaired_UTF8",
            "latent_tokens_after_EOS": "sampled_and_density_accounted_fixed_horizon"}
RATES = {"encoder": .00015, "gate": .00005, "transition": .0001,
         "pixel_emission": .0003, "token_emission": .00002,
         "write": .00005, "read": .00005, "observer": .00015}


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def set_stage(model, index):
    model.requires_grad_(False)
    enabled = []
    for _, names in STAGES[:index + 1]:
        for name in names:
            if hasattr(model, name):
                getattr(model, name).requires_grad_(True)
                enabled.append(name)
    return enabled


def hashes(model):
    return {name: parameter_hash(module) for name, module in model.named_children()}


def final_state(model, reference, observation, noise):
    with torch.no_grad():
        old = reference._base._model.encode(observation, noise)
        choices = reference._gate(old.context).argmax(-1)
    initial = model.encode(observation, noise)
    groups, positions = [], []
    for index, plan in enumerate(PLANS):
        ids = torch.where(choices == index)[0]
        if not len(ids):
            continue
        state = NeuralState(*(getattr(initial, field)[ids]
                              for field in ("h", "image", "text", "context")))
        for action in plan:
            state = model.step(state, action)
        groups.append(state)
        positions.append(ids)
    order = torch.cat(positions).argsort()
    return NeuralState(*(torch.cat([getattr(s, field) for s in groups])[order]
                         for field in ("h", "image", "text", "context"))), choices


def repeat_state(state, count):
    return NeuralState(*(getattr(state, name).repeat(count, 1)
                         for name in ("h", "image", "text", "context")))


@dataclass
class Sample:
    pixels: torch.Tensor
    tokens: torch.Tensor
    log_prob: torch.Tensor
    image_log_prob: torch.Tensor
    text_log_prob: torch.Tensor


def emit(model, state, rng, deterministic=False):
    mean = model.pixel_decoder(torch.cat((state.h, state.image), dim=1))
    if deterministic:
        latent = mean.detach()
    else:
        eps = torch.randn(mean.shape, generator=rng, device=mean.device)
        latent = (mean + EMISSION["image_logit_sigma"] * eps).detach()
    sigma = EMISSION["image_logit_sigma"]
    image_lp = (-.5 * ((latent - mean) / sigma).square()
                - math.log(sigma) - .5 * math.log(2 * math.pi)).sum(-1)
    hidden = torch.tanh(model.text_initial(torch.cat((state.h, state.text), dim=1))).unsqueeze(0)
    token = torch.full((len(mean), 1), BOS, dtype=torch.long, device=mean.device)
    emitted, log_probs = [token], []
    for _ in range(EMISSION["latent_token_steps"]):
        sequence, hidden = model.text_decoder(model.token_embedding(token), hidden)
        logits = model.text_projection(sequence[:, 0]) / EMISSION["text_temperature"]
        distribution = logits.log_softmax(-1)
        token = (logits.argmax(-1, keepdim=True) if deterministic else
                 torch.multinomial(distribution.exp(), 1, generator=rng)).detach()
        log_probs.append(distribution.gather(1, token)[:, 0])
        emitted.append(token)
    text_lp = torch.stack(log_probs).sum(0)
    return Sample(latent.sigmoid().reshape(-1, 1, 28, 56), torch.cat(emitted, 1),
                  image_lp + text_lp, image_lp, text_lp)


def leave_one_out(costs):
    if costs.ndim != 2 or costs.shape[0] < 2:
        raise ValueError("Independent KxB emission costs with K>=2 are required")
    return costs - (costs.sum(0, keepdim=True) - costs) / (len(costs) - 1)


def episode_costs(profile, event_id):
    counts = {"encoder": 2, "gate": 1, "transition": 2,
              "pixel_emission": 1, "token_emission": EMISSION["latent_token_steps"],
              "write": 2, "read": 2, "observer": 1}
    return tuple(CostEvent(event_id=event_id + ":" + kind,
                          amount=RATES[kind] * units, unit=profile.cost_unit, kind=kind)
                 for kind, units in counts.items())


def actual_outputs(sample, target, observer, profile, directory, identities, retain=False):
    """Score actual files; temporary training media are deleted only after readback."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    pixels, captions, bundles = [], [], []
    for index, (value, tokens) in enumerate(zip(sample.pixels, sample.tokens)):
        refs = write_bundle(directory / f"out-{index:04d}", render_tokens(tokens), value)
        image, caption, sha = read_bundle(refs)
        pixels.append(image)
        captions.append(caption)
        bundles.append((refs, sha))
    scores = observe_tensors(observer, torch.cat(pixels), captions, target.pixels, target.labels)
    rows, returns = [], []
    execution_id = hashlib.sha256(str(directory.resolve()).encode()).hexdigest()
    for index, (score, (refs, sha), identity) in enumerate(zip(scores, bundles, identities)):
        context_id, sample_id, source_id = identity
        outcome = DeliveredOutcome(
            context_id=context_id, sample_id=sample_id, source_cluster_id=source_id,
            delivered_utility=score["utility"], costs=episode_costs(profile, execution_id + ":" + str(index)),
            objective_sha256=profile.objective_sha256, observer_sha256=profile.observer_sha256,
            continuation_sha256=profile.continuation_sha256, terminal_kind="delivered",
            artifact_sha256=tuple(sorted(sha.items())))
        value = net_return(profile, outcome)
        returns.append(value)
        rows.append({"context_id": context_id, "sample_id": sample_id, "source_cluster_id": source_id,
                     "profile_sha256": profile.digest, "gross_utility": score["utility"],
                     "net_return": value, "costs": [e.__dict__ for e in outcome.costs],
                     "score": score, "artifact_sha256": sha,
                     "artifacts": {k: str(Path(v).relative_to(directory)) for k, v in refs.items()},
                     "caption": captions[index], "terminal_kind": "delivered"})
    times = {"codec_observer_wall_ns": time.perf_counter_ns() - started,
             "codec_observer_cpu_ns": time.process_time_ns() - cpu,
             "actual_bundles": len(rows), "files_written_and_reopened": 2 * len(rows)}
    if not retain:
        shutil.rmtree(directory)
    return torch.tensor(returns, dtype=torch.float32), rows, times


def save_model(model, path, profile, metadata):
    torch.save({"schema": "hepta.ndu.fullpath-emission.v1", "config": model.config,
                "state_dict": model.state_dict(), "model_sha256": parameter_hash(model),
                "profile": profile.to_dict(), "profile_sha256": profile.digest,
                "emission": EMISSION, "metadata": metadata}, path)


def load_model(path, profile):
    record = torch.load(path, weights_only=True, map_location="cpu")
    if (record["profile_sha256"] != profile.digest or record["profile"] != profile.to_dict()
            or record["emission"] != EMISSION):
        raise ValueError("Generator deployment density or objective changed")
    model = model_from_config(record["config"])
    model.load_state_dict(record["state_dict"])
    if parameter_hash(model) != record["model_sha256"]:
        raise ValueError("Generator checkpoint identity mismatch")
    return model.eval(), record
