"""Observable candidate readback and already-arrived scalar; no target input."""

import re

import numpy as np
import torch

from .verify_media import read_outputs


def observed_semantics(initial, candidate, feedback, observation, recognizer):
    """Features precede final commit and any private candidate grade.

    A nonzero external scalar identifies which of the two semantic orders was
    requested. It does not certify the final generated image. The public image
    recognizer supplies evidence about that remaining uncertainty.
    """
    if feedback not in (-1, 0, 1):
        raise ValueError("Unregistered delivered feedback")
    initial_match = re.fullmatch(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)", initial["caption"].strip())
    if feedback and initial_match is None:
        raise ValueError("A nonzero scalar is inconsistent with initial public text")
    inferred = None
    if feedback:
        inferred = [int(initial_match[1]), int(initial_match[2])]
        if feedback < 0:
            inferred.reverse()
    pixels, caption = read_outputs(candidate)
    candidate_match = re.fullmatch(r"left ([0-9]) right ([0-9]) relation (less|equal|greater)", caption.strip())
    candidate_digits = [int(candidate_match[1]), int(candidate_match[2])] if candidate_match else None
    relation = ("less" if inferred[0] < inferred[1] else "greater" if inferred[0] > inferred[1] else "equal") if inferred else None
    caption_matches = bool(inferred is not None and candidate_digits == inferred and candidate_match[3] == relation)
    with torch.inference_mode():
        image = torch.from_numpy(pixels)
        distributions = torch.stack((recognizer(image[:, :, :, :28]).softmax(-1)[0],
                                     recognizer(image[:, :, :, 28:]).softmax(-1)[0]))
    minimum_probability = min(float(distributions[i, label]) for i, label in enumerate(inferred)) if inferred else 0.0
    image_agrees = bool(inferred is not None and distributions.argmax(-1).tolist() == inferred)
    missing = bool(torch.all(observation.mask == 0) and int(observation.text_tokens[0, 3]) == 11
                   and int(observation.text_tokens[0, 5]) == 11)
    return {"feedback_known": inferred is not None, "feedback": feedback, "inferred_order_from_arrived_scalar": inferred,
        "caption_matches_inferred_order": caption_matches, "public_image_argmax_agrees": image_agrees,
        "minimum_inferred_digit_probability": minimum_probability, "declared_both_missing": missing,
        "input_contains_private_target": False, "prediction_role": "post-codec, pre-final-commit semantic probability"}


def category(features, threshold):
    if features["declared_both_missing"]:
        return "declared_ood"
    if not features["feedback_known"]:
        return "unknown_preference"
    if not features["caption_matches_inferred_order"]:
        return "caption_inconsistent"
    if features["public_image_argmax_agrees"] and features["minimum_inferred_digit_probability"] >= threshold:
        return "selective_candidate"
    return "uncertain_image"
