"""Conditional modality baselines and an unbiased continuous control variate.

Actual rewards come only from reopened PNG/UTF8. The frozen soft observer enters
the zero-mean LAX correction, never the reward, selector or evaluation metrics.
"""

import torch

from ..v6.data import render_tokens
from ..v6.observer import CAPTION, METRIC


def loss_from_return(value, gamma):
    return -value if gamma == 0 else torch.expm1(-gamma * value) / gamma


def continuous_proxy(observer, pixels, tokens, target, gamma, deployment_cost):
    """Only pixels carry a gradient. Observer, text and references are frozen.

There is no direct generator-parameter dependence in this function: otherwise
the ordinary LAX pathwise term would require a direct-partial correction.
"""
    if any(parameter.requires_grad for parameter in observer.parameters()):
        raise ValueError("The LAX observer must have frozen parameters")
    text_error, relation_error, parsed, valid = [], [], [], []
    labels = target.labels.detach()
    for row, expected in zip(tokens.detach(), labels.tolist()):
        match = CAPTION.fullmatch(render_tokens(row).strip())
        digits = [int(match[1]), int(match[2])] if match else [0, 0]
        relation = "less" if expected[0] < expected[1] else "greater" if expected[0] > expected[1] else "equal"
        text_error.append(sum(a != b for a, b in zip(digits, expected)) / 2 if match else 1.)
        relation_error.append(float(match[3] != relation) if match else 1.)
        parsed.append(digits); valid.append(match is not None)
    probabilities = torch.stack((observer(pixels[:, :, :, :28]).softmax(-1),
                                 observer(pixels[:, :, :, 28:]).softmax(-1)), dim=1)
    image_error = (1 - probabilities.gather(-1, labels[..., None]).squeeze(-1)).mean(-1)
    text_digits = torch.tensor(parsed, dtype=torch.long, device=pixels.device)
    agreement = probabilities.gather(-1, text_digits[..., None]).squeeze(-1).mean(-1)
    disagreement = torch.where(torch.tensor(valid, device=pixels.device), 1 - agreement, torch.ones_like(agreement))
    fields = {"text_fact": pixels.new_tensor(text_error), "relation": pixels.new_tensor(relation_error),
              "image_fact": image_error, "crossmodal_disagreement": disagreement,
              "pixel_mse": (pixels - target.pixels.detach()).square().flatten(1).mean(1)}
    soft_loss = sum(METRIC["weights"][key] * value for key, value in fields.items())
    return loss_from_return(1 - 2 * soft_loss - deployment_cost, gamma)


def surrogate(actual_loss, same_text_mean_image_loss, same_image_greedy_text_loss,
              proxy_sample, proxy_mean, image_log_prob, text_log_prob):
    """Averages unbiased pre-optimizer score/pathwise gradient estimates.

I and T are conditionally independent given the shared state/exogenous noise.
The image baseline depends on T and the condition; the text baseline depends on
I and the condition. Every score coefficient is detached. The proxy depends on
theta only through a reparameterized image. Gradient clipping/Adam are separate
optimizer operations and are not claimed to preserve unbiasedness.
"""
    image_coefficient = (actual_loss - same_text_mean_image_loss - proxy_sample + proxy_mean).detach()
    text_coefficient = (actual_loss - same_image_greedy_text_loss).detach()
    return (image_coefficient * image_log_prob + text_coefficient * text_log_prob + proxy_sample).mean()
