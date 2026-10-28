"""Versioned lower-temperature real PNG/UTF8 emission law for LAX training."""

from dataclasses import dataclass
import math

import torch

from ..v6.data import BOS, CAPTION_LENGTH
from ..v6.neural import model_from_config, parameter_hash
from ..v6.plan_training import PLANS
from ..unified_20261028.generator import (STAGES, RATES, actual_outputs, episode_costs,
                                         file_sha, final_state, hashes, leave_one_out,
                                         repeat_state, set_stage)


EMISSION = {"image_logit_sigma": .03, "text_temperature": .2,
            "latent_token_steps": CAPTION_LENGTH - 1,
            "sampling": "independent_normal_logits_and_autoregressive_categorical",
            "render": "sigmoid_round_uint8_PNG_and_unrepaired_UTF8",
            "latent_tokens_after_EOS": "sampled_and_density_accounted_fixed_horizon"}


@dataclass
class Sample:
    pixels: torch.Tensor
    tokens: torch.Tensor
    log_prob: torch.Tensor
    image_log_prob: torch.Tensor
    text_log_prob: torch.Tensor
    image_latent: torch.Tensor
    image_mean: torch.Tensor

    def pathwise_pixels(self):
        latent = self.image_mean + (self.image_latent - self.image_mean).detach()
        return latent.sigmoid().reshape(-1, 1, 28, 56)


def text_emission(model, state, rng=None, deterministic=False):
    hidden = torch.tanh(model.text_initial(torch.cat((state.h, state.text), dim=1))).unsqueeze(0)
    token = torch.full((len(state.h), 1), BOS, dtype=torch.long, device=state.h.device)
    emitted, log_probs = [token], []
    for _ in range(EMISSION["latent_token_steps"]):
        sequence, hidden = model.text_decoder(model.token_embedding(token), hidden)
        logits = model.text_projection(sequence[:, 0]) / EMISSION["text_temperature"]
        distribution = logits.log_softmax(-1)
        token = (logits.argmax(-1, keepdim=True) if deterministic else
                 torch.multinomial(distribution.exp(), 1, generator=rng)).detach()
        log_probs.append(distribution.gather(1, token)[:, 0])
        emitted.append(token)
    return torch.cat(emitted, 1), torch.stack(log_probs).sum(0)


def emit(model, state, rng, deterministic=False):
    mean = model.pixel_decoder(torch.cat((state.h, state.image), dim=1))
    sigma = EMISSION["image_logit_sigma"]
    latent = mean.detach() if deterministic else (mean + sigma * torch.randn(
        mean.shape, generator=rng, device=mean.device, dtype=mean.dtype)).detach()
    image_lp = (-.5 * ((latent - mean) / sigma).square()
                - math.log(sigma) - .5 * math.log(2 * math.pi)).sum(-1)
    tokens, text_lp = text_emission(model, state, rng, deterministic)
    return Sample(latent.sigmoid().reshape(-1, 1, 28, 56), tokens, image_lp + text_lp,
                  image_lp, text_lp, latent, mean)


def save_model(model, path, profile, metadata):
    torch.save({"schema": "hepta.ndu.fullpath-lax-emission.v1", "config": model.config,
                "state_dict": model.state_dict(), "model_sha256": parameter_hash(model),
                "profile": profile.to_dict(), "profile_sha256": profile.digest,
                "emission": EMISSION, "metadata": metadata}, path)


def load_model(path, profile):
    record = torch.load(path, weights_only=True, map_location="cpu")
    if (record["profile_sha256"] != profile.digest or record["profile"] != profile.to_dict()
            or record["emission"] != EMISSION):
        raise ValueError("Actual full-path objective or stochastic deployment law changed")
    model = model_from_config(record["config"])
    model.load_state_dict(record["state_dict"])
    if parameter_hash(model) != record["model_sha256"]:
        raise ValueError("Generator checkpoint identity changed")
    return model.eval(), record
