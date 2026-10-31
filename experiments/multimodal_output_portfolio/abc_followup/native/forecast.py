"""Public pre-transition features and a genuinely future-output predictor."""

import numpy as np
import torch

from ...abc_next.native.features import features

Q = 2**24
ACTIONS = ("refine_text", "couple")
INPUT_DIM = 478
STATE_DIM = 32
HIDDEN = 64


def quantize(x):
    x = np.asarray(x, dtype=np.float64)
    return np.where(x >= 0, np.floor(x * Q + .5), np.ceil(x * Q - .5)).astype(np.int64)


@torch.inference_mode()
def public_input(model, frame, observation, action):
    if action not in ACTIONS:
        raise ValueError("Unknown frozen future action")
    full = features(model, frame, observation)
    # Keep32 of48 coordinates per actual image panel. This leaves room for
    # the32 newly observed state coordinates inside native MAX_INPUT_FEATURES.
    x = torch.cat((full[:, :224], full[:, 240:272], full[:, 288:]), 1)
    flag = torch.zeros((len(x), 2), dtype=x.dtype)
    flag[:, ACTIONS.index(action)] = 1
    return quantize(torch.cat((x, flag), 1).double().numpy())


@torch.inference_mode()
def emitted_state(model, frame):
    """16 visual and16 textual coordinates from actually emitted media only.

    The visual encoder is bounded by its existing tanh. Text coordinates are
    tanh of eight frozen token-embedding coordinates for each emitted fact slot.
    No hidden target, quality observer, source identity or future RNG is read.
    """
    pixels = frame.pixels
    panels = torch.stack((pixels[:, :, :, :28], pixels[:, :, :, 28:]), 1).flatten(0, 1)
    encoded = model.pixel_encoder(torch.cat((panels, torch.ones_like(panels)), 1))
    visual = encoded.reshape(len(pixels), 2, -1)[:, :, :8].flatten(1)
    text = model.token_embedding(frame.tokens[:, (2, 4)])[:, :, :8].tanh().flatten(1)
    result = torch.cat((visual, text), 1).double().numpy()
    if result.shape != (len(pixels), STATE_DIM) or np.abs(result).max() > 1:
        raise ValueError("Future public state is outside its declared profile")
    return quantize(result)


def absent(x):
    return ((x[:, 448:450] == 0).all(1) & (x[:, 460] == 1) & (x[:, 471] == 1))


def predict(weights, x):
    hidden = np.tanh(x @ np.asarray(weights["w1"]).T + weights["b1"])
    output = hidden @ np.asarray(weights["w2"]).T + weights["b2"]
    token_state = np.asarray(weights["token_state"])
    past = np.concatenate((x[:, 192:200], x[:, 224:232],
                           x[:, 304:328] @ token_state, x[:, 352:376] @ token_state), 1)
    delta = np.tanh(output[:, :STATE_DIM])
    # refine_text preserves actual pixels by the existing generator contract.
    delta[x[:, 476] == 1, :16] = 0
    forecast = np.clip(past + delta, -1, 1)
    return forecast, 1 / (1 + np.exp(-output[:, STATE_DIM]))


def groups(x, raw_probability, cuts):
    action = x[:, 476:478].argmax(1)
    result = np.searchsorted(cuts, raw_probability, side="right") + 3 * action
    result[absent(x)] = 6 + action[absent(x)]
    return result


def runtime_predictions(weights, calibration, x, observed):
    forecast, raw = predict(weights, x)
    group = groups(x, raw, calibration["cuts"])
    probability = np.asarray(calibration["probabilities"])[group]
    prediction = quantize(np.column_stack((probability, forecast)))
    drive = quantize(np.column_stack((np.ones(len(x)), observed)))
    error = np.abs(drive - prediction).max(1)
    confidence = 1_000_000 - np.minimum(error * 1_000_000 // Q, 1_000_000)
    ood = np.minimum(error * 1_000_000 // Q, 1_000_000)
    return forecast, raw, probability, prediction, drive, confidence, ood, group
