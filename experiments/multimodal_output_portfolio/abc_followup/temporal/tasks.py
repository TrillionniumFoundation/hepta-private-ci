"""New finite fact groups and target-independent text decoding."""

import hashlib
import itertools
import json
import re

import numpy as np


WORDS = (("nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen"),
         ("red", "blue", "green", "yellow"), ("north", "south", "east", "west"))
ROLES = (("development", 0, 8), ("fit", 8, 32), ("selection", 40, 16),
         ("qualification", 56, 8), ("evaluation", 64, 64))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def manifest():
    facts = list(itertools.product(*(range(len(words)) for words in WORDS)))
    order = np.random.default_rng(20261025041).permutation(len(facts))
    roles = {}
    for role, start, count in ROLES:
        roles[role] = []
        for i in order[start:start + count]:
            fact = list(facts[int(i)])
            words = [v[index] for v, index in zip(WORDS, fact)]
            identity = hashlib.sha256(b"hepta.abc4.fact-group.v1\0" + canonical(words)).hexdigest()
            roles[role].append({"source_id": identity, "fact": fact, "words": words})
    return {"schema": "hepta.abc4.temporal-sources.v1", "roles": roles,
            "vocabulary": WORDS, "seed": 20261025041,
            "cluster": "underlying number/color/direction fact across all templates/scenarios/policies"}


def parse(text):
    text = re.sub(r"\b(?:9|1[0-6])\b", lambda m: WORDS[0][int(m[0]) - 9], text.lower())
    tokens = re.findall("[a-z]+", text)
    values = []
    for words in WORDS:
        seen = {words.index(token) for token in tokens if token in words}
        values.append(next(iter(seen)) if len(seen) == 1 else None)
    return tuple(values)


def sentence(fact, style, template=0):
    number, color, direction = [v[index] for v, index in zip(WORDS, fact)]
    if style == "compact":
        templates = (f"Send {number} {color} crates {direction}.",
                     f"Move {number} {color} boxes {direction}.",
                     f"Deliver {number} {color} packages {direction}.")
    elif style == "explicit":
        templates = (f"The number is {number}. The color is {color}. The destination is {direction}.",
                     f"Count {number}. Color {color}. Direction {direction}.",
                     f"There are {number} packages. They are {color}. Send them {direction}.")
    elif style == "redundant":
        templates = (f"The number is {number}, {number}. The color is {color}, {color}. The destination is {direction}, {direction}.",
                     f"Count {number}. Again, {number}. Color {color}. Again, {color}. Direction {direction}. Again, {direction}.",
                     f"There are {number} packages, {number}. They are {color}, {color}. Send them {direction}, {direction}.")
    else:
        raise ValueError("Unknown style")
    return templates[template]
