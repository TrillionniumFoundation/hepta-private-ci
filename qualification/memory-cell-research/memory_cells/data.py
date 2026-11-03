"""Frozen research tasks, source identities and explicit-memory baselines.

Facts are legitimately visible during writing; held-out query wording and feedback
are not. Synthetic tasks measure associative storage, not natural-language
understanding. Neither task metadata nor a routing key may be counted as weights.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
from pathlib import Path
import re

import numpy as np


TRAIN_TEMPLATES = (
    "In {domain}, remember the value associated with {key}.",
    "Find the stored value for {key} in {domain}.",
    "Record lookup: {domain} {key}.",
)
SELECTION_TEMPLATES = ("Which value belongs to {key}, within {domain}?",)
TEST_TEMPLATES = (
    "For the item {key} under {domain}, report its current value.",
    "Consult {domain}: what is associated with {key}?",
)
DOMAIN_NAMES = ("semantic-alpha", "semantic-beta", "semantic-gamma", "semantic-delta")


@dataclass(frozen=True)
class MemoryEvent:
    record_id: str
    key: str
    domain: str
    value: int | None
    revision: int
    source_ref: str
    source_sha256: str
    step: int = 0
    deleted: bool = False


@dataclass(frozen=True)
class MemoryQuery:
    query_id: str
    key: str
    domain: str
    text: str
    target: int | None
    split: str
    episode_id: str
    source_record_id: str
    revision: int


@dataclass(frozen=True)
class MemoryDataset:
    events: tuple[MemoryEvent, ...]
    train: tuple[MemoryQuery, ...]
    selection: tuple[MemoryQuery, ...]
    test: tuple[MemoryQuery, ...]
    metadata: dict

    def to_dict(self):
        return asdict(self)


def _digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def queries_for(events, split):
    """Different templates, same legitimately written facts; no answer in text."""
    templates = {
        "train": TRAIN_TEMPLATES,
        "selection": SELECTION_TEMPLATES,
        "test": TEST_TEMPLATES,
    }[split]
    result = []
    for event in events:
        for index, template in enumerate(templates):
            identity = f"{event.record_id}@{event.revision}/{split}/{index}"
            result.append(
                MemoryQuery(
                    identity,
                    event.key,
                    event.domain,
                    template.format(domain=event.domain, key=event.key),
                    None if event.deleted else event.value,
                    split,
                    event.record_id,
                    event.record_id,
                    event.revision,
                )
            )
    return tuple(result)


def dataset_from_events(events, metadata=None):
    events = tuple(events)
    return MemoryDataset(
        events,
        queries_for(events, "train"),
        queries_for(events, "selection"),
        queries_for(events, "test"),
        metadata or {},
    )


def make_associative(
    seed, domain_sizes=(24, 24, 24, 24), num_classes=64, domain_names=None
):
    """Independent key/value RNG streams prevent an encoded answer in the key."""
    if not domain_sizes or any(size < 1 for size in domain_sizes):
        raise ValueError("domain sizes must be positive")
    if num_classes < 2:
        raise ValueError("at least two classes are required")
    names = tuple(domain_names or DOMAIN_NAMES[: len(domain_sizes)])
    if len(names) != len(domain_sizes) or len(set(names)) != len(names):
        raise ValueError("one distinct domain name is required per size")
    streams = np.random.SeedSequence(seed).spawn(2)
    key_rng, value_rng = (np.random.default_rng(stream) for stream in streams)
    events = []
    used = set()
    alphabet = np.array(list("abcdefghijklmnopqrstuvwxyz"))
    for domain, size in zip(names, domain_sizes):
        for _ in range(size):
            key = "item-" + "".join(key_rng.choice(alphabet, size=12))
            while key in used:
                key = "item-" + "".join(key_rng.choice(alphabet, size=12))
            used.add(key)
            value = int(value_rng.integers(num_classes))
            record_id = f"synthetic:{seed}:{domain}:{key}"
            events.append(
                MemoryEvent(
                    record_id,
                    key,
                    domain,
                    value,
                    1,
                    f"synthetic://associative/{seed}/{domain}/{key}",
                    _digest(
                        {"key": key, "domain": domain, "value": value, "revision": 1}
                    ),
                )
            )
    return dataset_from_events(
        events,
        {
            "schema": "memory-cell-associative-v1",
            "seed": seed,
            "domain_sizes": list(domain_sizes),
            "num_classes": num_classes,
            "population": "synthetic independent random associations",
            "query_split": "held-out wording; same written source facts",
            "broad_language_generalization": False,
        },
    )


def active_events(history):
    """Resolve latest revisions; same-revision conflicts are never overwritten."""
    heads = {}
    for event in history:
        key = (event.domain, event.key)
        old = heads.get(key)
        if old and event.revision == old.revision and event != old:
            raise ValueError("conflicting event revision")
        if old is None or event.revision > old.revision:
            heads[key] = event
    return tuple(event for key, event in sorted(heads.items()) if not event.deleted)


def make_continual(base, seed, additions=12, corrections=8, deletions=4):
    """Return a versioned write stream and separate current/retention queries."""
    original = active_events(base.events)
    if min(additions, corrections, deletions) < 0 or corrections + deletions > len(
        original
    ):
        raise ValueError("invalid stream counts")
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(original)).tolist()
    classes = base.metadata["num_classes"]
    updated, removed = [], []
    for index in order[:corrections]:
        old = original[index]
        value = (old.value + int(rng.integers(1, classes))) % classes
        updated.append(
            replace(
                old,
                value=value,
                revision=old.revision + 1,
                step=1,
                source_sha256=_digest(
                    {"predecessor": old.source_sha256, "value": value}
                ),
            )
        )
    for index in order[corrections : corrections + deletions]:
        old = original[index]
        removed.append(
            replace(
                old,
                value=None,
                revision=old.revision + 1,
                step=1,
                deleted=True,
                source_sha256=_digest({"tombstone": old.source_sha256}),
            )
        )
    new = ()
    if additions:
        fresh = make_associative(
            seed + 104729, (additions,), classes, domain_names=("semantic-new",)
        )
        new = tuple(replace(event, step=1) for event in fresh.events)
    history = original + tuple(updated) + tuple(removed) + new
    affected = {event.record_id for event in updated + removed}
    retained = tuple(event for event in original if event.record_id not in affected)
    return {
        "history": history,
        "current": dataset_from_events(active_events(history), dict(base.metadata)),
        "retained": dataset_from_events(retained, dict(base.metadata)),
        "additions": new,
        "corrections": tuple(updated),
        "deletions": tuple(removed),
        "deleted_queries": queries_for(removed, "test"),
    }


def slot_key(index):
    """Public code vocabulary for graph intermediates, not an answer lookup."""
    if index < 0:
        raise ValueError("negative slot")
    letters = "abcdefghijklmnopqrstuvwxyz"
    digits = ""
    while True:
        digits = letters[index % 26] + digits
        index = index // 26 - 1
        if index < 0:
            return "slot-" + digits


def make_composition(seed, size=32, num_classes=64):
    """Two independently stored maps; the supplied two-hop scaffold is explicit."""
    if not 1 <= size <= num_classes:
        raise ValueError("composition size must fit intermediate class vocabulary")
    first = make_associative(seed, (size,), num_classes, ("episodic-entity",))
    rng = np.random.default_rng(np.random.SeedSequence([seed, 991]))
    permutation, values = rng.permutation(size), rng.integers(num_classes, size=size)
    first_events = tuple(
        replace(
            event,
            value=int(permutation[index]),
            source_sha256=_digest(
                {"source": event.source_sha256, "slot": int(permutation[index])}
            ),
        )
        for index, event in enumerate(first.events)
    )
    second_events = tuple(
        MemoryEvent(
            f"composition:{seed}:{slot_key(index)}",
            slot_key(index),
            "semantic-code",
            int(values[index]),
            1,
            f"synthetic://composition/{seed}/{slot_key(index)}",
            _digest({"slot": index, "value": int(values[index])}),
        )
        for index in range(size)
    )
    terminal = []
    for query in queries_for(first_events, "test"):
        terminal.append(
            replace(
                query,
                target=int(values[query.target]),
                text=query.text + " Follow the second memory to obtain the final code.",
            )
        )
    metadata = {
        "schema": "memory-cell-composition-v1",
        "seed": seed,
        "num_classes": num_classes,
        "scaffold": "given two-hop typed composition",
        "learned_topology": False,
        "query_targets": "never supplied to edge construction",
    }
    return {
        "first": dataset_from_events(first_events, metadata),
        "second": dataset_from_events(second_events, metadata),
        "queries": tuple(terminal),
        "metadata": metadata,
    }


def from_module_registry(path, source_commit, field="owner", expected_blob_sha=None):
    """Real repository facts; a narrow categorical recall diagnostic, not broad QA."""
    if field not in {"owner", "plane", "kind", "state"}:
        raise ValueError("unsupported registry field")
    raw = Path(path).read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if expected_blob_sha is not None and blob != expected_blob_sha:
        raise ValueError("registry source identity mismatch")
    rows = json.loads(raw)["modules"]
    labels = sorted({row[field] for row in rows})
    label_ids = {label: index for index, label in enumerate(labels)}
    digest = hashlib.sha256(raw).hexdigest()
    events = tuple(
        MemoryEvent(
            f"registry:{row['id']}:{field}",
            row["id"],
            f"module-{field}",
            label_ids[row[field]],
            1,
            f"git:{source_commit}:docs/modules/MODULES.json#{row['id']}/{field}",
            digest,
        )
        for row in rows
    )
    return dataset_from_events(
        events,
        {
            "schema": "memory-cell-registry-v1",
            "source_commit": source_commit,
            "source_path": "docs/modules/MODULES.json",
            "source_sha256": digest,
            "git_blob_sha": blob,
            "field": field,
            "label_catalog": labels,
            "label_catalog_bytes": len(json.dumps(labels).encode()),
            "num_classes": len(labels),
            "population": "single pinned repository registry",
            "query_split": "held-out wording; facts from the same written source",
            "broad_language_generalization": False,
        },
    )


def exact_store_predict(events, queries):
    store = {(event.domain, event.key): event.value for event in active_events(events)}
    return [store.get((query.domain, query.key)) for query in queries]


def lexical_retrieval_predict(events, queries):
    """Jaccard term retrieval over source keys/domains, with no oracle labels."""
    events = active_events(events)
    terms = [
        set(re.findall(r"[\w.-]+", f"{event.domain} {event.key}".lower()))
        for event in events
    ]
    predictions = []
    for query in queries:
        query_terms = set(re.findall(r"[\w.-]+", query.text.lower()))
        scores = [len(query_terms & item) / len(query_terms | item) for item in terms]
        if not scores or max(scores) == 0:
            predictions.append(None)
        else:
            index = int(np.argmax(scores))
            # Exact source-key presence avoids guessing when a record was deleted.
            predictions.append(
                events[index].value
                if events[index].key.lower() in query_terms
                else None
            )
    return predictions
