"""Two real modality encoders with one shared classification head."""

import torch
from torch import nn
from torch.nn import functional as F

from ..content.models import build


class PairedEncoder(nn.Module):
    def __init__(self, arm, seed, design):
        super().__init__()
        initial = design["initialization"]
        arguments = dict(input_dim=design["input_dimension_per_modality"],
                         output_dim=design["embedding_dimension"],
                         width=design["width"], depth=design["depth"])
        self.audio = build(arm, seed=seed+initial["audio_seed_offset"], **arguments)
        self.video = build(arm, seed=seed+initial["video_seed_offset"], **arguments)
        with torch.random.fork_rng():
            torch.manual_seed(seed+initial["head_seed_offset"])
            self.head = nn.Linear(design["embedding_dimension"], design["classes"])
        self.config = dict(arm=arm, seed=seed, audio=self.audio.config, video=self.video.config,
            input_dimension=design["input_dimension_per_modality"],
            embedding_dimension=design["embedding_dimension"], shared_head=True,
            fusion="Arithmetic mean of the two shared-head logits", dt_override=None,
            time_contract="Stored dt unchanged; physical HCSN scale0.1 restores seconds")

    def forward(self, audio, video, dt, return_aux=True):
        if audio.shape != video.shape or dt.shape != audio.shape[:2]:
            raise ValueError("Paired [batch,time,features] modalities and aligned dt required")
        if not bool(torch.isfinite(dt).all()) or bool((dt <= 0).any()):
            raise ValueError("Positive finite real elapsed durations required")
        a = self.audio(audio, dt, return_aux=return_aux)
        v = self.video(video, dt, return_aux=return_aux)
        aux = None
        if return_aux:
            a, audio_aux = a
            v, video_aux = v
            aux = dict(audio=audio_aux, video=video_aux)
        audio_logits, video_logits = self.head(a), self.head(v)
        result = dict(audio_embedding=a, video_embedding=v,
                      audio_logits=audio_logits, video_logits=video_logits,
                      fused_logits=.5*(audio_logits+video_logits))
        return (result, aux) if return_aux else result

    def parameter_groups(self):
        groups = {}
        for modality in ("audio", "video"):
            for group, entries in getattr(self, modality).parameter_groups().items():
                groups.setdefault(group, []).extend(
                    (f"{modality}.{name}", parameter) for name, parameter in entries)
        groups.setdefault("content", []).extend((f"head.{name}", parameter)
                                                 for name, parameter in self.head.named_parameters())
        return groups

    def counts(self):
        audio, video = self.audio.counts(), self.video.counts()
        return dict(audio=audio, video=video, shared_head=sum(p.numel() for p in self.head.parameters()),
            backbone=audio["backbone"]+video["backbone"],
            total=sum(p.numel() for p in self.parameters()),
            trainable=sum(p.numel() for p in self.parameters() if p.requires_grad),
            groups={key: sum(p.numel() for _, p in entries) for key, entries in self.parameter_groups().items()})


def common_state(model):
    prefixes = ("audio.frontend.", "audio.readout.", "video.frontend.", "video.readout.", "head.")
    return {name: value for name, value in model.state_dict().items() if name.startswith(prefixes)}


def objective(outputs, labels, temperature=.1):
    a = F.normalize(outputs["audio_embedding"], dim=-1, eps=1e-12)
    v = F.normalize(outputs["video_embedding"], dim=-1, eps=1e-12)
    logits = a @ v.T / temperature
    indices = torch.arange(len(labels), device=labels.device)
    contrastive = .5*(F.cross_entropy(logits, indices)+F.cross_entropy(logits.T, indices))
    fused = F.cross_entropy(outputs["fused_logits"], labels)
    audio = F.cross_entropy(outputs["audio_logits"], labels)
    video = F.cross_entropy(outputs["video_logits"], labels)
    loss = fused+.25*(audio+video)+.5*contrastive
    return loss, dict(fused_ce=float(fused.detach()), audio_ce=float(audio.detach()),
                     video_ce=float(video.detach()), symmetric_infonce=float(contrastive.detach()))
