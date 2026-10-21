"""Learned raw multimodal codec and independent task-unit output readback."""

import math

import torch
from torch import nn
import torch.nn.functional as F

from data import BIN_CENTERS, MODALITIES, SHAPES


class Encoder(nn.Module):
    """Fuse only observed raw modalities and predict six continuous facts."""

    def __init__(self):
        super().__init__()
        self.encoders = nn.ModuleDict({m: nn.Sequential(
            nn.Flatten(), nn.Linear(math.prod(SHAPES[m]), 64), nn.SiLU(),
            nn.Linear(64, 24), nn.SiLU()) for m in MODALITIES})
        self.fusion = nn.Sequential(nn.Linear(100, 64), nn.SiLU(), nn.Linear(64, 32), nn.SiLU())
        self.facts = nn.Linear(32, 6)

    def forward(self, inputs, masks):
        observed = [self.encoders[m](inputs[m]) * masks[:, i:i+1]
                    for i, m in enumerate(MODALITIES)]
        context = self.fusion(torch.cat(observed + [masks], dim=1))
        return context, self.facts(context)


class Decoder(nn.Module):
    """Decode facts/style with a shared learned time-conditioned frame model.

    Physical frame time is separate from generative rollout time. No analytic
    motion, Gaussian rendering, or ground-truth fact access occurs here.
    """

    def __init__(self):
        super().__init__()
        self.shared = nn.Sequential(nn.Linear(7, 128), nn.SiLU(),
                                    nn.Linear(128, 128), nn.SiLU())
        self.heads = nn.ModuleDict({m: nn.Linear(128, math.prod(SHAPES[m]))
                                   for m in ("text", "audio")})
        self.frame = nn.Sequential(nn.Linear(8, 192), nn.SiLU(),
                                   nn.Linear(192, 192), nn.SiLU(), nn.Linear(192, 768))
        self.style = nn.Linear(128, 2)

    def forward(self, state):
        hidden = self.shared(state)
        out = {m: self.heads[m](hidden).reshape(-1, *SHAPES[m]) for m in ("text", "audio")}
        frame_time = state.new_tensor([0., -1., -1/3, 1/3, 1.]).reshape(1, 5, 1)
        frames_input = torch.cat((state[:, None].expand(-1, 5, -1),
                                  frame_time.expand(len(state), -1, -1)), dim=-1)
        # A squared intensity link is nonnegative and has gradients on both
        # signs. Training consumes exactly the emitted tensors; no post-hoc
        # clipping can change the image support at evaluation time.
        frames = self.frame(frames_input.reshape(-1, 8)).square().reshape(-1, 5, 3, 16, 16)
        out["image"], out["video"] = frames[:, 0], frames[:, 1:]
        out["style_logits"] = self.style(hidden)
        return out


def spatial_moment_loss(predicted, target):
    """Train emitted pixels' mass, center, and spread against raw target images.

    This declared physical supervision helps a small decoder preserve shape;
    evaluation thresholds and readout are unchanged. No heldout facts enter.
    """
    predicted = predicted.reshape(-1, 3, 16, 16)
    target = target.reshape(-1, 3, 16, 16)
    grid = torch.linspace(0, 1, 16, dtype=predicted.dtype, device=predicted.device)
    yy, xx = torch.meshgrid(grid, grid, indexing="ij")

    def moments(images):
        channel_mass = images.sum((2, 3))
        mass = channel_mass.sum(1).clamp_min(0.5)
        density = images.sum(1)
        cx = (density * xx).sum((1, 2)) / mass
        cy = (density * yy).sum((1, 2)) / mass
        variance = (density * ((xx - cx[:, None, None]).square()
                              + (yy - cy[:, None, None]).square())).sum((1, 2)) / (2 * mass)
        return channel_mass, torch.stack((cx, cy), 1), variance.clamp_min(1e-8).sqrt()

    pm, pc, ps = moments(predicted)
    tm, tc, ts = moments(target)
    return (((pm - tm) / tm.clamp_min(1)).square().mean()
            + ((pc - tc) / 0.24).square().mean() + ((ps - ts) / 0.08).square().mean())


def loss_decoder(predicted, targets):
    """Fixed training loss for actual raw outputs, balanced by modality scale."""
    text = F.cross_entropy(predicted["text"].reshape(-1, 16),
                           targets["text"].argmax(-1).reshape(-1)) / math.log(16)
    audio = F.mse_loss(predicted["audio"], targets["audio"]) / 0.32
    image = F.mse_loss(predicted["image"], targets["image"]) * 100
    video = F.mse_loss(predicted["video"], targets["video"]) * 100
    style = F.cross_entropy(predicted["style_logits"], targets["style_index"])
    moments = (spatial_moment_loss(predicted["image"], targets["image"])
               + spatial_moment_loss(predicted["video"], targets["video"])) / 2
    return (text + audio + image + video) / 4 + 0.15 * style + 0.5 * moments


def _image_readback(images):
    nonnegative = images.clamp_min(0)
    mass = nonnegative.sum((1, 2, 3)).clamp_min(1e-8)
    density = nonnegative.sum(1)
    grid = torch.linspace(0, 1, 16, device=images.device, dtype=images.dtype)
    yy, xx = torch.meshgrid(grid, grid, indexing="ij")
    cx = (density * xx).sum((1, 2)) / mass
    cy = (density * yy).sum((1, 2)) / mass
    color = (nonnegative[:, 0].sum((1, 2)) - nonnegative[:, 1].sum((1, 2))) / (0.4 * mass)
    variance = (density * ((xx - cx[:, None, None]) ** 2
                          + (yy - cy[:, None, None]) ** 2)).sum((1, 2)) / (2 * mass)
    sigma = variance.clamp_min(0).sqrt()
    blob = torch.exp(-((xx - cx[:, None, None]) ** 2 + (yy - cy[:, None, None]) ** 2)
                     / (2 * sigma[:, None, None].square().clamp_min(1e-8)))
    coefficients = (nonnegative * blob[:, None]).sum((2, 3)) / blob.square().sum((1, 2))[:, None].clamp_min(1e-8)
    fitted = coefficients[:, :, None, None] * blob[:, None]
    residual = (images - fitted).square().sum((1, 2, 3)) / images.square().sum((1, 2, 3)).clamp_min(1e-8)
    return torch.stack(((cx - 0.5) / 0.24, (cy - 0.5) / 0.24, color), -1), sigma, mass, residual


def _audio_readback(audio):
    """Fit frequency/phase to raw waves, independent of learned codec weights."""
    frequencies = torch.linspace(3, 7, 513, device=audio.device, dtype=audio.dtype)
    time = torch.arange(64, device=audio.device, dtype=audio.dtype) / 64
    angle = 2 * math.pi * frequencies[:, None] * time
    sin, cos = angle.sin(), angle.cos()
    ss, cc, sc = (sin * sin).sum(-1), (cos * cos).sum(-1), (sin * cos).sum(-1)
    det = ss * cc - sc * sc
    ys, yc = audio @ sin.T, audio @ cos.T
    a = (ys * cc - yc * sc) / det
    b = (yc * ss - ys * sc) / det
    explained = a * ys + b * yc
    best = explained.argmax(-1)
    row = torch.arange(len(audio), device=audio.device)
    amplitude = (a[row, best] ** 2 + b[row, best] ** 2).sqrt()
    phase = torch.atan2(b[row, best], a[row, best])
    energy = (audio * audio).sum(-1).clamp_min(1e-8)
    residual = (1 - explained[row, best] / energy).clamp(0, 1)
    return (frequencies[best] - 5) / 2.5, phase, amplitude, residual


@torch.no_grad()
def semantic_metrics(predicted, facts):
    """Return per-example externally anchored semantics from generated raw outputs.

    Missing or malformed output is penalized rather than silently omitted.
    Resolved requires every text field's top probability >=0.20, identifiable
    audio, and a single image/video blob with width in [0.045,0.120]. Accuracy
    uses an absolute 0.20 task-unit tolerance, independently of text confidence.
    Supported factual fields: text six, audio frequency, image x/y/color,
    video x/y/vx/vy/color. Raw agreement cannot by itself establish truth.
    """
    n, device = len(facts), facts.device
    finite = {m: torch.isfinite(predicted[m]).flatten(1).all(1)
              for m in (*MODALITIES, "style_logits")}
    # A malformed modality receives an explicit failure, not an argmax/centroid
    # of NaNs. Sanitize before arithmetic so evidence arrays remain valid JSON.
    predicted = {m: torch.where(finite[m].reshape(n, *([1] * (v.ndim - 1))),
                                v, torch.zeros_like(v))
                 for m, v in predicted.items() if m in finite}
    finite["text"] = finite["text"] & finite["style_logits"]
    output_finite = torch.stack([finite[m] for m in MODALITIES], 1).all(1)
    text = BIN_CENTERS.to(device)[predicted["text"].argmax(-1)]
    text_top = predicted["text"].softmax(-1).amax(-1)
    text_conf = text_top.mean(-1)
    image, image_width, image_mass, image_residual = _image_readback(predicted["image"])
    video_frames, video_width, video_mass, video_residual = _image_readback(predicted["video"].reshape(-1, 3, 16, 16))
    video_frames = video_frames.reshape(n, 4, 3)
    video = torch.stack((video_frames[:, :, 0].mean(1),
                         video_frames[:, :, 1].mean(1),
                         (video_frames[:, -1, 0] - video_frames[:, 0, 0]) * 1.2,
                         (video_frames[:, -1, 1] - video_frames[:, 0, 1]) * 1.2,
                         video_frames[:, :, 2].mean(1)), dim=1)
    audio, phase, amplitude, audio_residual = _audio_readback(predicted["audio"])
    image_valid = finite["image"] & (image_mass > 0.5) & (image_residual < 0.50) & (image_width > 0.045) & (image_width < 0.12)
    video_valid = ((video_mass > 0.5) & (video_residual < 0.50)
                   & (video_width > 0.045) & (video_width < 0.12)).reshape(n, 4).all(1) & finite["video"]
    audio_valid = finite["audio"] & (amplitude > 0.10) & (audio_residual < 0.50)
    text_error = (text - facts).square().mean(1) / 2.25
    text_error = torch.where(finite["text"], text_error, torch.ones_like(text_error))
    image_error = (image - facts[:, [0, 1, 4]]).square().mean(1) / 2.25
    video_error = (video - facts[:, :5]).square().mean(1) / 2.25
    audio_error = (audio - facts[:, 5]).square() / 2.25
    image_error = torch.where(image_valid, image_error, torch.ones_like(image_error))
    video_error = torch.where(video_valid, video_error, torch.ones_like(video_error))
    audio_error = torch.where(audio_valid, audio_error, torch.ones_like(audio_error))
    per_modality = torch.stack((text_error, audio_error, image_error, video_error), 1)
    all_error = torch.cat(((text - facts).abs(), (audio[:, None] - facts[:, 5:6]).abs(),
                           (image - facts[:, [0, 1, 4]]).abs(),
                           (video - facts[:, :5]).abs()), 1)
    valid = finite["text"] & image_valid & video_valid & audio_valid
    resolved = valid & (text_top.amin(-1) >= 0.20)
    correct = (all_error < 0.20).all(1) & valid
    # Style validity is distinct from facts: both signs are lawful.
    styles = torch.stack((predicted["style_logits"].argmax(-1), (phase > 0).long(),
                          (image_width > 0.08).long(),
                          (video_width.reshape(n, 4).mean(1) > 0.08).long()), 1)
    style_consistent = (styles == styles[:, :1]).all(1) & output_finite
    style_lawful = ((phase.abs() - 0.45).abs() < 0.35) & (
        torch.minimum((image_width - 0.065).abs(), (image_width - 0.095).abs()) < 0.01) & (
        torch.minimum((video_width - 0.065).abs(), (video_width - 0.095).abs()) < 0.01).reshape(n, 4).all(1) & valid
    disagreement = torch.stack(((text[:, [0, 1, 4]] - image).square().mean(1),
                                 (text[:, :5] - video).square().mean(1),
                                 (text[:, 5] - audio).square(),
                                 (image - video[:, [0, 1, 4]]).square().mean(1)), 1).mean(1) / 2.25
    factual_loss = torch.where(output_finite, per_modality.mean(1), torch.ones(n, device=device))
    return {"factual_loss": factual_loss, "modality_loss": per_modality,
            "invalid_nonfinite": (~output_finite).float(),
            "correct": correct.float(), "resolved": resolved.float(),
            "correct_resolved": (correct & resolved).float(), "disagreement": disagreement,
            "style_positive": styles[:, 0].float(), "style_consistent": style_consistent.float(),
            "style_lawful": style_lawful.float(), "text_confidence": text_conf,
            "lawful_consistent": (style_lawful & style_consistent).float(),
            "raw_facts_text": text, "raw_facts_audio": audio[:, None],
            "raw_facts_image": image, "raw_facts_video": video}
