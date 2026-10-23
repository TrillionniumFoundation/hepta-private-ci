"""Synthetic source facts; memory recall and unseen-fact generalization are distinct.

The global value vocabulary and query templates precede all source sampling.
Only the writer/evaluator imports this module. The generation worker never does.
"""

import random

from native import digest

VALUES = ("red", "blue", "green", "yellow", "black", "white", "orange", "purple")
ENTITIES = (
    "Alice",
    "Bob",
    "Cara",
    "Dylan",
    "Emma",
    "Finn",
    "Gina",
    "Hugo",
    "Iris",
    "Jade",
    "Kara",
    "Liam",
    "Milo",
    "Nora",
    "Owen",
    "Paul",
)
TRAIN_TEMPLATES = (
    "What is {entity}'s {relation}?",
    "Recall the {relation} assigned to {entity}.",
    "{entity} has which {relation}?",
    "Return {entity}'s {relation}.",
)
SELECT_TEMPLATE = "State the {relation} for {entity}."
TEST_TEMPLATE = "Which {relation} did we assign to {entity}?"


def fact(scope, entity, value, revision=0):
    source = dict(
        scope=scope, entity=entity, relation="color", value=value, revision=revision
    )
    return {k: v for k, v in source.items() if k != "revision"} | {
        "source_digest": digest(["hepta.parametric.source.v1", source])
    }


def cohort(seed, scope, *, count=16):
    if type(seed) is not int or count not in (8, 16):
        raise ValueError("registered balanced source cohort required")
    values = list(VALUES) * (count // len(VALUES))
    random.Random(seed).shuffle(values)
    return [
        fact(scope, entity, value) for entity, value in zip(ENTITIES[:count], values)
    ]


def questions(facts, template):
    return [template.format(entity=f["entity"], relation=f["relation"]) for f in facts]


def score(rows, facts):
    if len(rows) != len(facts):
        raise ValueError("complete ordered generation journal required")
    # No casing, punctuation removal, regex extraction or answer-list decoding.
    correct = [row["text"] == f["value"] for row, f in zip(rows, facts)]
    return dict(
        correct=sum(correct),
        total=len(correct),
        exact_match=sum(correct) / len(correct),
    )
