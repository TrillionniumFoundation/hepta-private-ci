"""Public modality ingress and joint sampled text/image/wave/video generation."""

from dataclasses import dataclass, replace

import torch
from torch import nn
from torch.nn import functional as F

from ...v6.data import BOS, Observation
from ...closure_20261025.media.coherent import CoherentVideo, MelSpeech, motion_targets
from ...closure_20261025.media.network import VideoInput, ingress_state
from ..media.waveform import WaveformStudent


@dataclass(frozen=True)
class PublicTask:
    route: str
    observation: Observation | None = None
    text_digits: torch.Tensor | None = None
    spectrum: torch.Tensor | None = None
    audio_features: torch.Tensor | None = None
    video: torch.Tensor | None = None


class JointModel(nn.Module):
    """Five trainable components share a single causally encoded state."""

    def __init__(self, core, speech=None, motion=None, audio_input=None, video_input=None):
        super().__init__()
        self.core = core
        self.speech = speech if speech is not None else WaveformStudent()
        self.motion = motion if motion is not None else CoherentVideo()
        self.audio_input = audio_input if audio_input is not None else MelSpeech()
        self.video_input = video_input if video_input is not None else VideoInput()

    def encode(self, task, noise):
        if type(task) is not PublicTask:
            raise TypeError("Only public modality input may reach the generator")
        if task.route == "image":
            state = self.core.encode(task.observation, noise)
        else:
            if task.route == "text":
                if task.text_digits is None or task.text_digits.shape[1:] != (2,):
                    raise ValueError("A literal two-digit text request is required")
                probabilities = F.one_hot(task.text_digits, 10).float()
            elif task.route == "audio":
                logits = (self.audio_input.features(task.audio_features.flatten(0, 1))
                          if task.audio_features is not None else self.audio_input(task.spectrum.flatten(0, 1)))
                probabilities = logits.softmax(-1).reshape(-1, 2, 10)
            elif task.route == "video":
                probabilities = self.video_input(task.video).softmax(-1)
            else:
                raise ValueError("Unknown public input modality")
            state = ingress_state(self.core, probabilities)
            state = replace(state, h=state.h + self.core.noise_scale * noise)
        for action in ("refine_semantic", "couple"):
            state = self.core.step(state, action)
        return state

    def sample(self, state, rng, greedy=False):
        """Sample actual discrete text and semantic choices; retain their log law."""
        core = self.core
        hidden = core.text_initial(torch.cat((state.h, state.text), 1)).tanh()[None]
        token = torch.full((len(state.h), 1), BOS, dtype=torch.long)
        emitted, log_probs = [token], []
        for _ in range(7):
            sequence, hidden = core.text_decoder(core.token_embedding(token), hidden)
            logits = core.text_projection(sequence[:, -1])
            law = logits.log_softmax(-1)
            token = (law.argmax(-1, keepdim=True) if greedy else
                     torch.multinomial(law.detach().exp(), 1, generator=rng))
            log_probs.append(law.gather(1, token)[:, 0])
            emitted.append(token)
        law = core.digit_head(state.h.reshape(-1, 48)).log_softmax(-1)
        semantic = (law.argmax(-1, keepdim=True) if greedy else
                    torch.multinomial(law.detach().exp(), 1, generator=rng))
        semantic_log = law.gather(1, semantic).reshape(-1, 2).sum(-1)
        onehot = F.one_hot(semantic[:, 0], 10).float().reshape(-1, 2, 10)
        latent = torch.cat((state.h.reshape(-1, 48), state.image.reshape(-1, 48)), 1)
        panels = core.pixel_decoder(latent).reshape(-1, 2, 1, 28, 28).sigmoid()
        image = torch.cat((panels[:, 0], panels[:, 1]), 3)
        displacement = self.motion.displacements(onehot)
        from ...closure_20261025.media.coherent import spatial_video
        frames = spatial_video(image, displacement)
        waves = self.speech(onehot.flatten(0, 1)).reshape(-1, 2, 16000)
        return {"tokens": torch.cat(emitted, 1), "semantic_digits": semantic.reshape(-1, 2),
                "image": image, "waveform": waves, "video": frames, "displacement": displacement,
                "log_probability": torch.stack(log_probs).sum(0) + semantic_log}


def utility(output, target, reward, wave_targets):
    """Training reward from sampled content, separate from withheld ASR audits.

    The waveform fidelity and floating-point video motion terms are declared
    training proxies. This does not differentiate physical codec quantization.
    """
    labels = target.labels
    panels = torch.stack((output["image"][:, :, :, :28], output["image"][:, :, :, 28:]), 1)
    image = reward(panels.flatten(0, 1)).softmax(-1).gather(1, labels.flatten()[:, None]).reshape(-1, 2).mean(-1)
    text = (output["tokens"] == target.text_tokens).all(-1).float()
    expected_wave = wave_targets[labels]
    wave_error = (output["waveform"] - expected_wave).square().mean(-1)
    energy = expected_wave.square().mean(-1).clamp_min(1e-4)
    audio = (-(wave_error / energy)).exp().mean(-1)
    video_prob = reward(output["video"].flatten(0, 1)).softmax(-1)
    repeated = labels.repeat_interleave(10, 1).flatten()
    semantic_video = video_prob.gather(1, repeated[:, None]).reshape(-1, 20).mean(-1)
    desired_motion = output["displacement"].new_zeros(output["displacement"].shape)
    desired_motion[:, :, 0] = torch.linspace(-2, 2, 10).repeat(2)
    moving = (-(output["displacement"] - desired_motion).square().mean((1, 2))).exp()
    video = .8 * semantic_video + .2 * moving
    return torch.stack((image, text, audio, video), 1)


def policy_objective(rewards, log_probability, profile, gamma=2.):
    """Pathwise plus discrete score-function gradient for the declared proxy.

    Minimizing E[exp(-gamma U)] is equivalent to maximizing entropic CE. Using
    the moment rather than a minibatch log avoids self-normalized score weights.
    The stop-gradient correction has the required score derivative and exactly
    zero forward value. No straight-through categorical relaxation is used.
    """
    if profile not in {"mean", "entropic"}:
        raise ValueError("Unregistered training profile")
    value = rewards.mean(-1)
    cost = -value if profile == "mean" else torch.exp(-gamma * (value - .75)) / gamma
    baseline = -.75 if profile == "mean" else 1. / gamma
    return cost.mean() + ((cost.detach() - baseline) * (log_probability - log_probability.detach())).mean()


def make_task(batch, route, spectra=None, audio_labels=None, rng=None):
    """Dataset construction makes aligned public evidence before model access.

    Text tasks explicitly provide the digit string. Audio is actual training
    PCM selected by the task constructor, and video shows real source pixels.
    Ground truth is absent from PublicTask except the explicitly requested text.
    """
    if route == "image":
        return PublicTask(route, observation=batch.observation)
    if route == "text":
        return PublicTask(route, text_digits=batch.target.labels.clone())
    if route == "video":
        return PublicTask(route, video=motion_targets(batch.target.pixels))
    if route != "audio" or spectra is None or audio_labels is None or rng is None:
        raise ValueError("Audio tasks require actual registered source PCM")
    indices = []
    for label in batch.target.labels.flatten().tolist():
        pool = torch.nonzero(audio_labels == label).flatten()
        indices.append(pool[int(torch.randint(len(pool), (), generator=rng))])
    selected = spectra[torch.stack(indices)]
    if selected.shape[1:] == (1, 40, 64):
        return PublicTask(route, audio_features=selected.reshape(-1, 2, 1, 40, 64))
    return PublicTask(route, spectrum=selected.reshape(-1, 2, 1, 129, 101))
