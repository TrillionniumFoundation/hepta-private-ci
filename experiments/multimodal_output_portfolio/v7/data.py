"""Public reliability metadata and a complete, deliberately hard task census.

Untrusted channels contain BOTH correct and incorrect hints; their public flag
never tells whether the particular hint is correct. Severe missing-information
cases remain in all strict totals. The encoder receives only Observation.
"""

from dataclasses import dataclass

import torch

from ..v6.data import BOS, DIGIT_OFFSET, EOS, PAD, Observation, Target, render_tokens


VIEWS = ("clean", "noise", "occlusion", "missing_trusted", "conflict_untrusted",
         "missing_untrusted", "missing_unknown", "both_missing")
SUFFICIENT_VIEWS = VIEWS[:5]
UNTRUSTED_CORRECT_PROBABILITY = .5


@dataclass(frozen=True)
class Batch:
    observation: Observation
    target: Target
    source_ids: tuple[tuple[str, str], ...]
    views: tuple[str, ...]
    information_sufficient: tuple[bool, ...]
    untrusted_hint_correct: tuple[bool | None, ...]


def make_batch(corpus, split, batch_size, seed, view="mixture", offset=None):
    if view not in (*VIEWS, "mixture") or batch_size < 1:
        raise ValueError("Unknown view or invalid batch size")
    source = corpus.splits[split]
    rng = torch.Generator().manual_seed(int(seed))
    if offset is None:
        left = torch.randint(len(source), (batch_size,), generator=rng)
        right = (left + torch.randint(1, len(source), (batch_size,), generator=rng)) % len(source)
    else:
        if offset < 0 or 2 * (offset + batch_size) > len(source):
            raise ValueError("No-replacement pair range exceeds registered source role")
        left = torch.arange(2 * offset, 2 * (offset + batch_size), 2)
        right = left + 1
    pixels = torch.cat((source.images[left], source.images[right]), dim=3).float() / 255
    source_labels = torch.stack((source.labels[left], source.labels[right]), dim=1)
    swap = torch.randint(2, (batch_size,), generator=rng).bool()
    target_pixels, labels = pixels.clone(), source_labels.clone()
    target_pixels[swap] = torch.cat((pixels[swap, :, :, 28:], pixels[swap, :, :, :28]), dim=3)
    labels[swap] = labels[swap].flip(1)
    captions = torch.tensor([BOS, 3, 0, 4, 0, 5, 0, EOS]).repeat(batch_size, 1)
    captions[:, 2], captions[:, 4] = labels[:, 0] + DIGIT_OFFSET, labels[:, 1] + DIGIT_OFFSET
    captions[:, 6] = torch.sign(labels[:, 0] - labels[:, 1]) + 7
    tokens = torch.tensor([BOS, 9, 12, 11, 13, 11, EOS, PAD]).repeat(batch_size, 1)
    tokens[:, 1] = 9 + swap.long()
    chosen = (tuple(VIEWS[int(i)] for i in torch.randint(len(VIEWS), (batch_size,), generator=rng))
              if view == "mixture" else (view,) * batch_size)
    # Randomness is sampled for every case before view-specific branching. Thus
    # counterfactual views share sources/command/noise; a flag is never truth-derived.
    sides = torch.randint(2, (batch_size,), generator=rng)
    correct = torch.rand(batch_size, generator=rng) < UNTRUSTED_CORRECT_PROBABILITY
    alternative = torch.randint(1, 10, (batch_size,), generator=rng)
    patch_row = torch.randint(19, (batch_size, 2), generator=rng)
    patch_col = torch.randint(19, (batch_size, 2), generator=rng)
    noise = torch.randn(pixels.shape, generator=rng)
    mask, public = torch.ones_like(pixels), pixels.clone()
    hint_correct = []
    for i, case_view in enumerate(chosen):
        side = int(sides[i])
        if case_view == "both_missing":
            mask[i] = 0
        elif case_view.startswith("missing_"):
            mask[i, :, :, 28 * side:28 * (side + 1)] = 0
        elif case_view == "occlusion":
            for j in range(2):
                r, c = int(patch_row[i, j]), 28 * j + int(patch_col[i, j])
                mask[i, :, r:r + 10, c:c + 10] = 0
        if case_view == "missing_trusted":
            tokens[i, 3 + 2 * side] = source_labels[i, side] + DIGIT_OFFSET
        if case_view in {"conflict_untrusted", "missing_untrusted"}:
            tokens[i, 2 + 2 * side] = 11  # channel reliability, not correctness
            hint = source_labels[i, side]
            if not correct[i]:
                hint = (hint + alternative[i]) % 10
            tokens[i, 3 + 2 * side] = hint + DIGIT_OFFSET
            hint_correct.append(bool(correct[i]))
        else:
            hint_correct.append(None)
        scale = .22 if case_view == "noise" else (.08 if case_view != "clean" else 0.)
        public[i] = (pixels[i] + scale * noise[i]).clamp(0, 1) * mask[i]
    ids = tuple((source.ids[int(i)], source.ids[int(j)]) for i, j in zip(left, right))
    return Batch(Observation(public, mask, tokens), Target(target_pixels, captions, labels), ids,
                 chosen, tuple(item in SUFFICIENT_VIEWS for item in chosen), tuple(hint_correct))


def public_information_sufficiency(observation):
    """Structural evidence availability; never a guarantee of recognition.

    A wholly absent source is sufficient only with a declared reliable hint.
    Occluded/noisy source recognition may still fail and is scored normally.
    """
    visible = torch.stack((observation.mask[:, :, :, :28].sum((1, 2, 3)),
                           observation.mask[:, :, :, 28:].sum((1, 2, 3))), dim=1) > 0
    markers = observation.text_tokens[:, (2, 4)]
    digits = observation.text_tokens[:, (3, 5)]
    reliable = (markers == torch.tensor((12, 13))) & (digits >= DIGIT_OFFSET) & (digits < 24)
    return (visible | reliable).all(1)
