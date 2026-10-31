"""Public-state feedback with innovations sampled only after action commitment.

The owner holds RNGs, records and experiment identities. A policy receives only
PublicFrame. This is an explicit data-flow boundary, not a Python security
sandbox against a caller that deliberately captures hidden data in a closure.
The caller selects grad/no_grad mode. Fixed-action actual-output training and
deployment therefore execute exactly the same state and emission program.
"""

from collections import Counter
from dataclasses import dataclass, replace
import hashlib
import json

import torch
from torch.nn import functional as F

from ..v6.data import CAPTION_LENGTH, EOS, Observation, VOCAB
from ..v7.model import SlotPortfolio, State, observation_digest
from .emission import output_digests, sample_emission


ACTIONS = ("stop", "refine_semantic", "refine_image", "refine_text", "couple")
PREFIX = ("refine_semantic", "couple")
HORIZON = 2
FEATURE_DIM = 673


@dataclass(frozen=True, slots=True)
class PublicFrame:
    """Current public latent state, actual draft and remaining generation budget."""

    state: State
    pixels: torch.Tensor
    tokens: torch.Tensor
    remaining: int


@dataclass(frozen=True)
class RunState:
    """Owner-side state; never pass this object or its ledger to a policy."""

    state: State
    pixels: torch.Tensor
    tokens: torch.Tensor
    remaining: int
    image_log_probability: torch.Tensor
    text_log_probability: torch.Tensor
    anchor_h: torch.Tensor
    content_mode: str
    shared_mode: str
    context_mode: str
    ledger: tuple[dict, ...]
    done: bool = False

    @property
    def terminal_log_probability(self):
        """Retained-output score for fixed-action, terminal-output-only training.

        Native transitions never read sampled drafts. With fixed actions, scores
        for discarded samples can be integrated out. This is not an adaptive
        policy trajectory score. If actions depend on drafts/parameters, or if
        the objective charges costs depending on discarded draws, retain their
        scores and every required policy score instead of using this property.
        """
        return self.image_log_probability + self.text_log_probability


class TransitionFailure(RuntimeError):
    """Preserve the pre-innovation commitment when an actual transition fails."""

    def __init__(self, cause, ledger):
        super().__init__(f"Generation transition failed: {type(cause).__name__}: {cause}")
        self.ledger = ledger


def public_frame(run):
    """Give the policy detached copies, with checkpoint/source identities cleared."""
    state = replace(run.state, **{name: getattr(run.state, name).detach().clone()
                                  for name in ("h", "image", "text", "context")},
                    snapshot_digest="", source_digest="")
    return PublicFrame(state, run.pixels.detach().clone(), run.tokens.detach().clone(),
                       run.remaining)


def public_digest(frame):
    """Bind exactly public state/content/budget, excluding RNGs and owner records."""
    digest = hashlib.sha256(b"hepta.abc.public-frame.v1\0")
    digest.update(json.dumps({"remaining": frame.remaining,
                              "step_count": frame.state.step_count,
                              "content_control": frame.state.content_control},
                             sort_keys=True, separators=(",", ":")).encode())
    for value in (frame.state.h, frame.state.image, frame.state.text, frame.state.context,
                  frame.pixels, frame.tokens):
        array = value.detach().cpu().contiguous().numpy()
        digest.update(str((array.dtype.str, array.shape)).encode() + b"\0" + array.tobytes())
    return digest.hexdigest()


def feasible_mask(frame):
    """Feasible controls depend on current public budget and content permission."""
    enabled = frame.remaining > 0
    shared = enabled and frame.state.content_control
    return torch.tensor([True, shared, enabled, enabled, shared], dtype=torch.bool,
                         device=frame.state.h.device)


def _emission_work(emission):
    batch = len(emission.tokens)
    active = torch.cat((torch.ones((batch, 1), dtype=torch.bool, device=emission.tokens.device),
                        (emission.tokens[:, 1:-1] != EOS).cumprod(1).bool()), 1)
    return {"emission_calls": 1, "pixel_decoder_calls": 1,
            "pixel_decoder_panel_examples": 2 * batch,
            "text_decoder_step_calls": CAPTION_LENGTH - 1,
            "text_decoder_example_steps": batch * (CAPTION_LENGTH - 1),
            "token_projection_example_steps": batch * (CAPTION_LENGTH - 1),
            "bernoulli_sample_calls": 1, "sampled_bernoulli_variables": emission.pixels.numel(),
            "categorical_sample_calls": int(active.any(0).sum()),
            "sampled_categorical_variables": int(active.sum())}


def initialize(model, observation, *, generator, content_mode="full",
               shared_mode="adaptive", context_mode="persistent"):
    """Common two-action prefix, then a complete stochastic draft, with H=2.

    Shared-state clamping is a continuation intervention anchored *after* this
    common prefix. Allocation-only also applies only to continuation actions.
    The initial-only context intervention clears context during both prefix and
    continuation; it does not claim matched retraining of that architecture.
    """
    if not isinstance(model, SlotPortfolio):
        raise TypeError("A SlotPortfolio is required")
    if not isinstance(observation, Observation):
        raise TypeError("Initialization accepts public Observation only")
    if (content_mode not in {"full", "allocation_only"}
            or shared_mode not in {"adaptive", "clamped_initial"}
            or context_mode not in {"persistent", "initial_only_context_intervention"}):
        raise ValueError("Unsupported runtime intervention")
    state = model.encode(observation)
    batch = len(state.h)
    if context_mode != "persistent":
        state = replace(state, context=torch.zeros_like(state.context))
    for action in PREFIX:
        state = model.step(state, action)
    state = replace(state, content_control=content_mode == "full")
    emission = sample_emission(model, state, generator=generator)
    work = {"encoder_calls": 1, "encoder_examples": batch,
            "input_pixel_encoder_panel_examples": 2 * batch,
            "state_transition_calls": len(PREFIX),
            "state_transition_examples": len(PREFIX) * batch,
            "refine_semantic_calls": 1, "couple_calls": 1,
            "committed_image_examples": batch, "committed_text_examples": batch,
            **_emission_work(emission)}
    if context_mode != "persistent":
        work["context_zero_examples"] = batch
    run = RunState(state, emission.pixels, emission.tokens, HORIZON,
                   emission.image_log_probability, emission.text_log_probability, state.h.clone(),
                   content_mode, shared_mode, context_mode, ())
    entry = {"phase": "initialized", "prefix": list(PREFIX), "batch_size": batch,
             "observation_sha256": observation_digest(observation),
             "after_public_sha256": public_digest(public_frame(run)),
             "output_sha256": list(emission.row_sha256),
             "innovation_rng_before_sha256": emission.rng_before_sha256,
             "innovation_rng_after_sha256": emission.rng_after_sha256,
             "context_mode": context_mode, "shared_mode": shared_mode,
             "content_mode": content_mode, "matched_encoder_training_claim": False,
             "work": work}
    return replace(run, ledger=(entry,))


def transition(model, run, action, *, generator):
    """Commit one action before drawing any future decoder innovation.

    One action is shared by all rows in a batch. Counterfactual branches may use
    the same immutable parent run with separately supplied owner-side RNGs.
    Semantic refinement updates h but retains the *current* actual draft.
    Image/text refinement computes a full emission and discards the other
    modality, with that discarded computation and RNG use included in work.
    """
    if not isinstance(model, SlotPortfolio):
        raise TypeError("A SlotPortfolio is required")
    if run.done or action not in ACTIONS:
        raise ValueError("Episode is finished or action is unknown")
    before = public_frame(run)
    if not bool(feasible_mask(before)[ACTIONS.index(action)]):
        raise ValueError("Action is infeasible under the public control profile")
    commit = {"phase": "action_committed", "action": action,
              "before_public_sha256": public_digest(before), "remaining": run.remaining}
    ledger = run.ledger + (commit,)
    try:
        state, pixels, tokens = run.state, run.pixels, run.tokens
        image_score, text_score = run.image_log_probability, run.text_log_probability
        batch = len(pixels)
        work = {}
        rng_before = rng_after = None
        remaining = run.remaining
        if action != "stop":
            if run.context_mode != "persistent":
                state = replace(state, context=torch.zeros_like(state.context))
                work["context_zero_examples"] = batch
            state = model.step(state, action)
            work.update({"state_transition_calls": 1, "state_transition_examples": batch,
                         action + "_calls": 1})
            if run.shared_mode == "clamped_initial":
                state = replace(state, h=run.anchor_h.clone())
                work["shared_clamp_examples"] = batch
            remaining -= 1
            if action != "refine_semantic":
                emission = sample_emission(model, state, generator=generator)
                work.update(_emission_work(emission))
                rng_before, rng_after = emission.rng_before_sha256, emission.rng_after_sha256
                if action in {"refine_image", "couple"}:
                    pixels = emission.pixels
                    image_score = emission.image_log_probability
                    work["committed_image_examples"] = batch
                else:
                    work["discarded_image_examples"] = batch
                if action in {"refine_text", "couple"}:
                    tokens = emission.tokens
                    text_score = emission.text_log_probability
                    work["committed_text_examples"] = batch
                else:
                    work["discarded_text_examples"] = batch
        updated = replace(run, state=state, pixels=pixels, tokens=tokens, remaining=remaining,
                          image_log_probability=image_score, text_log_probability=text_score,
                          done=action == "stop" or remaining == 0)
        record = {"phase": "transition_completed", "action": action,
                  "after_public_sha256": public_digest(public_frame(updated)),
                  "output_sha256": list(output_digests(pixels, tokens)),
                  "innovation_rng_before_sha256": rng_before,
                  "innovation_rng_after_sha256": rng_after,
                  "remaining": remaining, "done": updated.done, "work": work}
    except Exception as error:
        failed = {"phase": "transition_failed", "action": action,
                  "error_type": type(error).__name__, "error": str(error)}
        raise TransitionFailure(error, ledger + (failed,)) from error
    return replace(updated, ledger=ledger + (record,))


@torch.no_grad()
def public_features(model, frame, *, draft_mode="observed", work=None):
    """Return [B,673] float32 features using only a public frame and fixed model.

    The optional owner-side Counter receives actual feature-extractor work.
    The generation ledger cannot measure arbitrary policy-internal computation;
    the runner must combine these counts, critic work and full elapsed costs.
    Masked-draft ablation skips draft encoding and zeros its feature block.
    """
    if not isinstance(model, SlotPortfolio) or model.training or not isinstance(frame, PublicFrame):
        raise TypeError("Expected an eval-mode generator and PublicFrame")
    if draft_mode not in {"observed", "masked"}:
        raise ValueError("Unknown draft observation mode")
    batch = len(frame.pixels)
    latent = torch.cat(tuple(getattr(frame.state, name)
                             for name in ("h", "image", "text", "context")), 1)
    counts = {"public_feature_calls": 1, "public_feature_examples": batch}
    if draft_mode == "observed":
        panels = torch.stack((frame.pixels[:, :, :, :28], frame.pixels[:, :, :, 28:]), 1)
        panels = panels.flatten(0, 1)
        visual = model.pixel_encoder(torch.cat((panels, torch.ones_like(panels)), 1))
        visual = visual.reshape(batch, 2 * model.slot)
        textual = F.one_hot(frame.tokens, num_classes=len(VOCAB)).flatten(1).to(latent.dtype)
        counts.update({"draft_pixel_encoder_calls": 1, "draft_pixel_encoder_panel_examples": 2 * batch,
                       "token_onehot_examples": batch})
    else:
        visual = torch.zeros((batch, 2 * model.slot), dtype=latent.dtype, device=latent.device)
        textual = torch.zeros((batch, CAPTION_LENGTH * len(VOCAB)),
                              dtype=latent.dtype, device=latent.device)
    budget = torch.full((batch, 1), frame.remaining / HORIZON,
                        dtype=latent.dtype, device=latent.device)
    features = torch.cat((latent, visual, textual, budget), 1).float().detach()
    if features.shape != (batch, FEATURE_DIM) or not torch.isfinite(features).all():
        raise ValueError("Invalid public feature matrix")
    if work is not None:
        for name, count in counts.items():
            work[name] = work.get(name, 0) + count
    return features


def work_counts(run):
    """Sum completed generation work without double-counting commitment records."""
    counts = Counter()
    for record in run.ledger:
        counts.update(record.get("work", {}))
    return dict(counts)


def rollout(model, observation, policy, *, generator, **interventions):
    """Owner executes the policy(frame) decisions; policy receives no future RNG."""
    run = initialize(model, observation, generator=generator, **interventions)
    while not run.done:
        action = policy(public_frame(run))
        run = transition(model, run, action, generator=generator)
    return run
