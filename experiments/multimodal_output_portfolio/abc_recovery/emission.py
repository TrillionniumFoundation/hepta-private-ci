"""One actual-output sampling law for both training and deployment.

Images are sampled binary pixels, not deterministic sigmoid images paired with
the likelihood of a different latent variable. Text is sampled autoregressively
from its own previously emitted tokens; EOS makes the remaining positions PAD.
No target, scorer, teacher token or argmax substitution enters the sampler.

The score-function objective below is a *joint task/noise exponential moment*.
It is not the average of task-conditional certainty equivalents, a normalized
finite-sample CE gradient, or a proof of an optimal learned controller.
"""

from dataclasses import dataclass
import hashlib
import json
import math

import torch
from torch.nn import functional as F

from ..v6.data import BOS, CAPTION_LENGTH, EOS, PAD
from ..v7.model import SlotPortfolio, State


EMISSION_LAW = "bernoulli-pixels-ar-categorical-eos-absorbing-v1"


@dataclass(frozen=True)
class Emission:
    """An actual sampled pixel/token path and its complete decoder likelihood.

    The digest binds decoded uint8 pixels and the fixed-width integer token
    path. It is not a PNG-file hash or a marginal probability of a rendered
    string: rendering may map several token paths to the same text.
    """

    pixels: torch.Tensor
    tokens: torch.Tensor
    image_log_probability: torch.Tensor
    text_log_probability: torch.Tensor
    log_probability: torch.Tensor
    row_sha256: tuple[str, ...]
    rng_before_sha256: str
    rng_after_sha256: str
    law: str = EMISSION_LAW


@dataclass(frozen=True)
class ScoreFunctionEstimate:
    """Only ``surrogate`` supplies a gradient; reported CE values are empirical."""

    surrogate: torch.Tensor
    objective: str
    risk_aversion: float
    empirical_transformed_moment: float
    empirical_joint_loss_ce: float
    empirical_mean_conditional_loss_ce: float
    empirical_exponential_moment: float | None
    baseline: torch.Tensor
    advantage: torch.Tensor


def output_digests(pixels, tokens):
    """Hash actual sampled contents without grammar repair or image smoothing."""
    if (pixels.ndim != 4 or pixels.shape[1:] != (1, 28, 56)
            or tokens.shape != (len(pixels), CAPTION_LENGTH)
            or tokens.dtype != torch.long
            or not ((pixels == 0) | (pixels == 1)).all()):
        raise ValueError("Expected binary pixel emissions and integer token paths")
    images = (pixels.detach().cpu() * 255).to(torch.uint8).contiguous().numpy()
    token_rows = tokens.detach().cpu().tolist()
    return tuple(hashlib.sha256(
        b"hepta.actual-emission.uint8-1x28x56-and-token-path.v1\0"
        + image.tobytes() + json.dumps(row, separators=(",", ":")).encode()
    ).hexdigest() for image, row in zip(images, token_rows))


def sample_emission(model, state, *, generator):
    """Draw from the same decoder law in training and deployment.

    ``state`` may retain its gradient through the encoder and generation cells.
    All discrete draws are detached, but their log probabilities retain the
    parameter dependence of both neural decoders and the sampled AR prefixes.
    If preceding actions have parameter-dependent probabilities, callers must
    also include their log probabilities in the full trajectory score.

    The explicit generator must be on the state's device. This function never
    changes the model's train/eval mode or consumes the global Torch RNG.
    """
    if not isinstance(model, SlotPortfolio) or not isinstance(state, State):
        raise TypeError("Expected a SlotPortfolio and its public generation State")
    if not isinstance(generator, torch.Generator):
        raise TypeError("An explicit torch.Generator is required")
    if torch.device(generator.device) != state.h.device:
        raise ValueError("Generator and generation state must use the same device")
    batch = len(state.h)
    if (batch < 1 or any(value.shape != (batch, model.hidden)
                         or not value.is_floating_point()
                         or not torch.isfinite(value).all()
                         for value in (state.h, state.image, state.text))):
        raise ValueError("Invalid decoder state")
    before = hashlib.sha256(generator.get_state().cpu().numpy().tobytes()).hexdigest()
    digit_latents = torch.cat((state.h.reshape(-1, model.slot),
                               state.image.reshape(-1, model.slot)), 1)
    panels = model.pixel_decoder(digit_latents).reshape(batch, 2, 1, 28, 28)
    image_logits = torch.cat((panels[:, 0], panels[:, 1]), dim=3)
    if not torch.isfinite(image_logits).all():
        raise FloatingPointError("Nonfinite pixel logits")
    pixels = torch.bernoulli(image_logits.detach().sigmoid(), generator=generator).detach()
    image_score = -F.binary_cross_entropy_with_logits(
        image_logits, pixels, reduction="none"
    ).flatten(1).sum(1)

    hidden = torch.tanh(model.text_initial(torch.cat((state.h, state.text), 1))).unsqueeze(0)
    token = torch.full((batch, 1), BOS, dtype=torch.long, device=state.h.device)
    emitted = [token]
    active = torch.ones(batch, dtype=torch.bool, device=state.h.device)
    text_score = torch.zeros(batch, dtype=image_logits.dtype, device=state.h.device)
    for _ in range(CAPTION_LENGTH - 1):
        sequence, hidden = model.text_decoder(model.token_embedding(token), hidden)
        logits = model.text_projection(sequence)[:, 0]
        if not torch.isfinite(logits).all():
            raise FloatingPointError("Nonfinite token logits")
        token = torch.full((batch, 1), PAD, dtype=torch.long, device=state.h.device)
        if active.any():
            token[active] = torch.multinomial(
                logits[active].detach().softmax(-1), 1, generator=generator
            )
        token = token.detach()
        selected = logits.log_softmax(-1).gather(1, token).squeeze(1)
        text_score = text_score + torch.where(active, selected, torch.zeros_like(selected))
        emitted.append(token)
        active = active & (token[:, 0] != EOS)
    tokens = torch.cat(emitted, dim=1).detach()
    after = hashlib.sha256(generator.get_state().cpu().numpy().tobytes()).hexdigest()
    return Emission(pixels, tokens, image_score, text_score, image_score + text_score,
                    output_digests(pixels, tokens), before, after)


def score_function_objective(log_probability, observed_loss, *, risk_aversion):
    """Unbiased score gradient of a declared exponential-moment objective.

    Arrays have shape [conditions, independent draws], with at least two draws
    per condition. For gamma > 0 the objective is

        E_x E_w[expm1(gamma * L(x,w)) / gamma].

    For gamma = 0 it is E[L]. Negative losses are supported: with L = -U,
    minimizing the positive-gamma moment maximizes the *joint* entropic CE of U.
    Shared parameters generally make this differ from mean conditional CE.

    The leave-one-out baseline is independent of a draw's score conditional on
    its input, provided draws are conditionally independent and parameters are
    fixed during collection. No random normalization by a batch moment is used.
    The returned surrogate value is not the objective's Monte Carlo value.

    ``observed_loss`` must be detached and have no explicit parameter dependence
    outside the sampled path. A deterministic theta-dependent scored output with
    an unrelated latent/action score does not satisfy this contract. For an
    adaptive trajectory, ``log_probability`` must cover every parameter-dependent
    stochastic choice; this helper cannot verify that semantic obligation.
    """
    if (isinstance(risk_aversion, bool) or not isinstance(risk_aversion, (int, float))
            or not math.isfinite(risk_aversion) or risk_aversion < 0):
        raise ValueError("Risk aversion must be finite and nonnegative")
    if (log_probability.ndim != 2 or log_probability.shape[0] < 1
            or log_probability.shape[1] < 2
            or observed_loss.shape != log_probability.shape
            or observed_loss.device != log_probability.device
            or not log_probability.is_floating_point()
            or not observed_loss.is_floating_point()
            or not torch.isfinite(log_probability).all()
            or not torch.isfinite(observed_loss).all()):
        raise ValueError("Expected finite [conditions, independent draws>=2] arrays")
    if observed_loss.requires_grad:
        raise ValueError("Observed actual-output losses must be detached")
    gamma = float(risk_aversion)
    losses = observed_loss.detach().double()
    if gamma == 0:
        weights = losses
        joint_ce = conditional_ce = float(losses.mean())
        exponential_moment = None
        objective = "mean_observed_loss"
    else:
        scaled = gamma * losses
        weights = torch.expm1(scaled) / gamma
        if not torch.isfinite(weights).all():
            raise FloatingPointError("Exponential moment overflow; losses were not clipped")
        joint_ce = float((torch.logsumexp(scaled.flatten(), 0)
                          - math.log(losses.numel())) / gamma)
        conditional_ce = float(((torch.logsumexp(scaled, 1)
                                 - math.log(losses.shape[1])) / gamma).mean())
        exponential_moment = float(scaled.exp().mean())
        objective = "joint_exponential_moment"
    baseline = (weights.sum(1, keepdim=True) - weights) / (weights.shape[1] - 1)
    advantage = (weights - baseline).detach()
    surrogate = (advantage * log_probability.double()).mean()
    return ScoreFunctionEstimate(surrogate, objective, gamma, float(weights.mean()),
                                 joint_ce, conditional_ce, exponential_moment,
                                 baseline.detach(), advantage)
