"""Constructed, source-grouped factual tasks and public causal state.

These are controlled semantic combinations, not a natural-speech population.
Target facts are confined to the episode owner and offline scorer.
"""

from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
import re

import numpy as np


WORDS = (("one", "two", "three", "four", "five", "six", "seven", "eight"),
         ("red", "blue", "green", "yellow"), ("north", "south", "east", "west"))
PREFIX = "I will check the details."
ACTIONS = ("keep_normal", "fuse_normal", "keep_slow", "fuse_slow", "fuse_clamp_normal")
GENERATOR_ACTIONS = ACTIONS[:4]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def source_manifest(seed=2026102501):
    facts = list(itertools.product(*(range(len(words)) for words in WORDS)))
    order = np.random.default_rng(seed).permutation(len(facts))
    roles = {}
    for name, start, count in (("development", 0, 16), ("fit", 16, 32),
                               ("qualification", 48, 16), ("evaluation", 64, 64)):
        rows = []
        for index in order[start:start + count]:
            fact = list(facts[int(index)])
            identity = hashlib.sha256(b"hepta.text-speech.fact-group.v1\0" + canonical(fact)).hexdigest()
            rows.append({"source_id": identity, "fact": fact})
        roles[name] = rows
    return {"schema": "hepta.abc3.text-speech-fact-manifest.v1", "seed": seed,
            "vocabulary": WORDS, "roles": roles,
            "unit": "unique number/color/direction combination; all scenarios, actions and policy seeds stay grouped",
            "natural_population_or_voice_generalization": False}


def sentences(fact):
    count, color, direction = (words[index] for words, index in zip(WORDS, fact))
    return (f"The number is {count}. The color is {color}.", f"The direction is {direction}.")


def parse_facts(text):
    # Public, target-independent normalization also handles ASR number spelling.
    text = re.sub(r"\b[1-8]\b", lambda match: WORDS[0][int(match[0]) - 1], text.lower())
    tokens = re.findall(r"[a-z]+", text)
    result = []
    for vocabulary in WORDS:
        seen = {vocabulary.index(token) for token in tokens if token in vocabulary}
        result.append(next(iter(seen)) if len(seen) == 1 else None)
    return tuple(result)


def _likelihood(observed, quality, classes):
    result = np.full(classes, (1 - quality) / (classes - 1))
    result[observed] = quality
    return result


@dataclass(frozen=True)
class PublicFrame:
    initial: tuple[int, ...]
    initial_quality: tuple[float, ...]
    fresh: tuple[int, ...]
    fresh_quality: tuple[float, ...]
    posterior: tuple[tuple[float, ...], ...]
    probe_fact: tuple[int | None, ...]
    probe_confidence: float
    probe_word_count: int

    def fused(self):
        return tuple(int(np.argmax(values)) for values in self.posterior)

    def serialized(self):
        return asdict(self)


def owner_public_frame(target, source_id, scenario, probe_fact=(None, None, None),
                       probe_confidence=0.0, probe_word_count=0):
    """The private owner constructs noisy observations; policies see only return."""
    if scenario not in range(4):
        raise ValueError("Unknown predeclared observation scenario")
    profiles = (((.90, .90, .90), (.65, .65, .65)),
                ((.55, .55, .55), (.95, .95, .95)),
                ((.75, .75, .75), (.80, .80, .80)),
                ((.55, .90, .75), (.95, .65, .80)))
    initial_q, fresh_q = profiles[scenario]
    seed = int.from_bytes(hashlib.sha256(canonical([source_id, scenario, 2026102502])).digest()[:8], "little")
    rng = np.random.default_rng(seed)
    observed = []
    for qualities in (initial_q, fresh_q):
        sample = []
        for truth, quality, vocabulary in zip(target, qualities, WORDS):
            sample.append(int(rng.choice(len(vocabulary), p=_likelihood(truth, quality, len(vocabulary)))))
        observed.append(tuple(sample))
    posterior = []
    for index, vocabulary in enumerate(WORDS):
        product = (_likelihood(observed[0][index], initial_q[index], len(vocabulary)) *
                   _likelihood(observed[1][index], fresh_q[index], len(vocabulary)))
        posterior.append(tuple(float(value) for value in product / product.sum()))
    return PublicFrame(observed[0], initial_q, observed[1], fresh_q, tuple(posterior),
                       tuple(probe_fact), float(probe_confidence), int(probe_word_count))


def update_probe(frame, observation):
    values = frame.serialized()
    values.update(probe_fact=parse_facts(observation["transcript"]),
                  probe_confidence=observation["mean_word_confidence"],
                  probe_word_count=len(observation["words"]))
    return PublicFrame(**values)


def features(frame, initial_only=False, mask_probe=False):
    """No target, source identity, RNG state, or future terminal output is accepted."""
    if type(frame) is not PublicFrame:
        raise TypeError("Policy features require a detached PublicFrame")
    row = [1.0, *frame.initial_quality]
    for value, vocabulary in zip(frame.initial, WORDS):
        row.extend(float(value == index) for index in range(len(vocabulary)))
    if initial_only:
        return np.asarray(row, dtype=np.float64)
    row.extend(frame.fresh_quality)
    for initial, fresh, posterior in zip(frame.initial, frame.fresh, frame.posterior):
        array = np.asarray(posterior)
        row.extend((float(initial != fresh), max(posterior), posterior[initial],
                    -float(np.sum(array * np.log(np.maximum(array, 1e-12)))),
                    float(initial != np.argmax(posterior))))
    for fresh, vocabulary in zip(frame.fresh, WORDS):
        row.extend(float(fresh == index) for index in range(len(vocabulary)))
    if mask_probe:
        row.extend([0.0] * 8)
    else:
        row.extend((frame.probe_confidence, min(frame.probe_word_count, 24) / 24))
        row.extend(float(value is None) for value in frame.probe_fact)
        row.extend(float(a == b) for a, b in zip(frame.probe_fact, frame.initial))
    return np.asarray(row, dtype=np.float64)


def action_fact(frame, action):
    if action not in ACTIONS:
        raise ValueError("Unsupported action")
    return frame.fused() if action.startswith("fuse_") and "clamp" not in action else frame.initial


def action_cost(action):
    return .02 * action.startswith("fuse_") + .01 * action.endswith("slow")


def observed_metrics(target, text, transcript, physical_complete):
    text_fact, audio_fact = parse_facts(text), parse_facts(transcript)
    text_score = np.mean([value == truth for value, truth in zip(text_fact, target)])
    audio_score = np.mean([value == truth for value, truth in zip(audio_fact, target)])
    agreement = np.mean([a is not None and b is not None and a == b for a, b in zip(text_fact, audio_fact)])
    complete = bool(physical_complete and None not in text_fact and None not in audio_fact)
    success = bool(complete and text_fact == tuple(target) and audio_fact == tuple(target))
    utility = .6 * (text_score + audio_score) / 2 + .2 * agreement + .2 * success
    return {"text_fact_accuracy": float(text_score), "audio_fact_accuracy": float(audio_score),
            "fact_agreement": float(agreement), "required_semantic_completion": complete,
            "joint_task_success": success, "utility": float(utility), "loss": float(1 - utility),
            "text_fact": text_fact, "audio_fact": audio_fact}
