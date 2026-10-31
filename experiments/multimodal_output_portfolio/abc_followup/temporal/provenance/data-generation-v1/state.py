"""Detached causal observations and a shared public belief state."""

from dataclasses import asdict, dataclass
import hashlib

import numpy as np

from .tasks import WORDS, canonical, parse


GAMMA = 2.0
PRICE = .05
PRICE_GRID = (0.0, .025, .05, .1, .2)
SEEDS = (17, 29, 43)
ROUTES = ((0, 0), (0, 1), (1, 0), (1, 1))
PREFIX = "Checking the shipping request."
INITIAL_QUALITY = (.80, .80, .80)
SENSOR_QUALITY = ((.90, .90, .90), (.98, .98, .98), (.98, .98, .98))


def likelihood(value, quality, size):
    values = np.full(size, (1 - quality) / (size - 1))
    values[value] = quality
    return values


class CueOwner:
    """Only this environment owner receives truth or unreleased cue content."""

    def __init__(self, source, scenario):
        seed = int.from_bytes(hashlib.sha256(canonical([source["source_id"], scenario, 20261025042])).digest()[:8], "little")
        rng = np.random.default_rng(seed)
        qualities = (INITIAL_QUALITY, *SENSOR_QUALITY)
        # Alternate scenarios are independent sensor futures, not distinct N.
        self._observed = [tuple(int(rng.choice(len(words), p=likelihood(truth, quality, len(words))))
                                for truth, quality, words in zip(source["fact"], q, WORDS))
                          for q in qualities]
        self._released = {0}

    def initial(self):
        return self._observed[0]

    def release(self, index):
        if index not in (1, 2, 3) or index in self._released:
            raise ValueError("Cue must be acquired exactly once through its owner")
        self._released.add(index)
        return self._observed[index]


@dataclass(frozen=True)
class Frame:
    initial: tuple
    posterior: tuple
    observations: tuple
    observation_confidence: tuple
    previous_audio_fact: tuple
    stage: int
    template: int
    first_action: int
    elapsed_seconds: float

    def values(self):
        return tuple(int(np.argmax(p)) for p in self.posterior)

    def detached(self):
        return asdict(self)


def initial_frame(initial, template):
    posterior = tuple(tuple(likelihood(v, q, len(words)))
                      for v, q, words in zip(initial, INITIAL_QUALITY, WORDS))
    return Frame(tuple(initial), posterior, (), (), (None, None, None), 0, template, -1, 0.0)


def incorporate(frame, observation, cue_index):
    decoded = parse(observation["transcript"])
    posterior = []
    # This is a declared public fusion rule, not an exact ASR posterior.
    # Discount nominal sensor trust for imperfect unrestricted Vosk decoding.
    qualities = tuple(.85 * q + .15 / len(words)
                      for q, words in zip(SENSOR_QUALITY[cue_index - 1], WORDS))
    for prior, value, quality, words in zip(frame.posterior, decoded, qualities, WORDS):
        probability = np.asarray(prior).copy()
        if value is not None:
            probability *= likelihood(value, quality, len(words))
        posterior.append(tuple(float(v) for v in probability / probability.sum()))
    state = frame.detached()
    state.update(posterior=tuple(posterior), observations=(*frame.observations, decoded),
                 observation_confidence=(*frame.observation_confidence, observation["mean_word_confidence"]))
    return Frame(**state)


def features(frame, initial_only=False):
    if type(frame) is not Frame:
        raise TypeError("Policy accepts only a detached public Frame")
    row = [1.0, float(frame.template), float(frame.stage), float(frame.first_action)]
    for value, words in zip(frame.initial, WORDS):
        row.extend(float(value == index) for index in range(len(words)))
    if initial_only:
        row.extend([0.] * 30)
        return np.asarray(row)
    for initial, probability in zip(frame.initial, frame.posterior):
        p = np.asarray(probability)
        row.extend((float(p.max()), float(p[initial]), -float(np.sum(p * np.log(np.maximum(p, 1e-12)))),
                    float(initial != np.argmax(p))))
    for index in range(3):
        values = [entry[index] for entry in frame.observations]
        nonmissing = [v for v in values if v is not None]
        row.extend((len(nonmissing) / 3, float(len(set(nonmissing)) > 1),
                    float(frame.previous_audio_fact[index] is None),
                    float(frame.previous_audio_fact[index] == frame.values()[index])))
    row.extend((len(frame.observations) / 3,
                float(np.mean(frame.observation_confidence)) if frame.observation_confidence else 0.,
                0., 0., 0., 0.))
    return np.asarray(row)


def chunk_text(frame):
    number, color, direction = [words[index] for words, index in zip(WORDS, frame.values())]
    if frame.stage == 0:
        return (f"Send {number} {color} crates.", f"Move {number} {color} boxes.")[frame.template]
    return (f"They should go {direction}.", f"Their destination is {direction}.")[frame.template]


def metrics(target, text, transcript, physical):
    text_fact, audio_fact = parse(text), parse(transcript)
    text_accuracy = np.mean([a == b for a, b in zip(text_fact, target)])
    audio_accuracy = np.mean([a == b for a, b in zip(audio_fact, target)])
    agreement = np.mean([a is not None and a == b for a, b in zip(text_fact, audio_fact)])
    complete = bool(physical and None not in text_fact and None not in audio_fact)
    success = bool(complete and text_fact == tuple(target) and audio_fact == tuple(target))
    utility = .6 * (text_accuracy + audio_accuracy) / 2 + .2 * agreement + .2 * success
    return {"text_fact": text_fact, "audio_fact": audio_fact, "utility": float(utility),
            "text_accuracy": float(text_accuracy), "audio_accuracy": float(audio_accuracy),
            "agreement": float(agreement), "success": success, "semantic_complete": complete,
            "physical_complete": bool(physical), "loss": float(1 - utility)}
