"""Deterministic, source-bound new knowledge for the V14 language experiment.

All task functions and text templates are frozen before final evaluation.  This
is a constrained language interface, not an open-domain language benchmark.
"""

import argparse
import hashlib
import json
import random
import re
from pathlib import Path


MODEL = "google/bert_uncased_L-2_H-128_A-2"
REVISION = "30b0a37ccaaa32f332884b96992754e246e48c5f"
WEIGHTS_SHA256 = "7fb69ad9f6866d8983183c930e33828f326470bf6ad8bbb2ad4ed957a92e9414"
SEEDS = [17, 29, 43]
NAMES = ("amber birch cedar coral dove eagle elm fern flint frost hazel iris jade "
         "lake maple moss oak olive pearl pine plum quartz raven reed river rose "
         "ruby sage silver stone teal willow acorn ash bay beach blue bronze "
         "cloud copper crane dawn dusk gold grass green hill ivory juniper larch "
         "leaf lilac lily moon night ocean opal orchid peach pink rain red sand "
         "shell sky snow sun violet wave west white wind wolf wood yellow zinc").split()
TRAIN_TEMPLATES = [
    "For case {entity}, retrieve its {field}.",
    "What is the {field} assigned to case {entity}?",
    "Find the stored {field} of case {entity}.",
    "Report case {entity} and its registered {field}.",
    "Please recall the {field} for case {entity}.",
    "Look up case {entity}: I need its {field}.",
]
VALID_TEMPLATES = ["Tell me which {field} belongs to case {entity}."]
TEST_TEMPLATES = [
    "Which {field} did we record for case {entity}?",
    "I am asking about case {entity}; return the relevant {field}.",
    "From the memory of case {entity}, recover its {field}.",
]
OPERATIONS = ["add", "subtract", "multiply", "minimum", "maximum", "first", "second", "absolute_difference"]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def parse_key(text):
    """Parse only public query syntax; never access labels or evaluation metadata."""
    entity = re.search(r"\bcase ([a-z]+)\b", text.lower())
    fields = [x for x in ("marker", "harbor", "program") if re.search(r"\b" + x + r"\b", text.lower())]
    return (entity.group(1), fields[0]) if entity and len(fields) == 1 else None


def execute(label, x, y):
    """A shared supplied interpreter: predicting label is program selection only."""
    if not 0 <= int(label) < len(OPERATIONS):
        return None
    return (x + y, x - y, x * y, min(x, y), max(x, y), x, y, abs(x - y))[int(label)]


def generate(seed, task):
    if task not in ("facts", "procedure_selection"):
        raise ValueError(task)
    rng = random.Random(seed)
    entities = rng.sample(NAMES, 36)
    fields = ["marker", "harbor"] if task == "facts" else ["program"]
    keys = [(entity, field) for entity in entities[:32] for field in fields]
    labels = list(range(8)) * (len(keys) // 8)
    rng.shuffle(labels)
    sources = []
    for index, ((entity, field), label) in enumerate(zip(keys, labels)):
        sources.append({"source_id": f"{task}-{seed}-{index:03d}", "entity": entity,
                        "field": field, "label": label, "phase": 0 if entity in entities[:24] else 1,
                        "text": f"The registered {field} for case {entity} is value {label}."})

    def rows(which):
        templates = {"train": TRAIN_TEMPLATES, "validation": VALID_TEMPLATES, "test": TEST_TEMPLATES}[which]
        return [{"query": template.format(**source), "label": source["label"],
                 "source_id": source["source_id"], "phase": source["phase"],
                 "template_id": f"{which}-{number}", "entity": source["entity"],
                 "field": source["field"]}
                for source in sources for number, template in enumerate(templates)]

    unknown = [{"query": TEST_TEMPLATES[0].format(entity=entity, field=fields[0]), "label": -1,
                "source_id": None, "phase": 2} for entity in entities[32:]]
    data = {"seed": seed, "task": task, "sources": sources, "train": rows("train"),
            "validation": rows("validation"), "test": rows("test"), "unknown": unknown,
            "model_revision_precedes_synthetic_knowledge": REVISION,
            "interpretation": "label recall" if task == "facts" else "known-program selection, not learned arithmetic"}
    if task == "procedure_selection":
        pool = data["test"]
        data["composition"] = [{"first": rng.randrange(len(pool)), "second": rng.randrange(len(pool)),
                                "x": rng.randrange(-31, 32), "y": rng.randrange(-31, 32),
                                "z": rng.randrange(-31, 32)} for _ in range(96)]
    return data


def manifest():
    return {f"{seed}/{task}": {"data_sha256": digest(generate(seed, task)),
                              "test_sha256": digest(generate(seed, task)["test"]),
                              "source_sha256": digest(generate(seed, task)["sources"])}
            for seed in SEEDS for task in ("facts", "procedure_selection")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    args.manifest.write_text(json.dumps(manifest(), indent=2) + "\n")
