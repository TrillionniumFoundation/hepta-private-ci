"""Frozen addressing evaluation: known lexical cues and unseen synonyms differ.

Typed mode receives a public structured address. Literal/learned modes receive
only text and scope, never the oracle target or the structured cell-type field.
This experiment does not establish an end-to-end memory-system advantage.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import time

import numpy as np

from .router import RouteRequest, RouteSpec, Router


DEFAULT_PROFILE = {
    "steps": 600,
    "learning_rate": 0.03,
    "threshold": 0.8,
    "margin": 0.25,
}
SCOPE = "research"
SPECS = tuple(
    RouteSpec(kind + "-cell", kind, (kind,))
    for kind in ("semantic", "episodic", "procedural")
)
TRAIN_CUES = {
    "semantic-cell": ("semantic", "owner", "attribute", "definition"),
    "episodic-cell": ("episodic", "history", "timeline", "revision"),
    "procedural-cell": ("procedural", "validate", "execute", "rule"),
    None: ("decline", "unrelated", "outside", "ignore"),
}
SYNONYMS = {
    "semantic-cell": ("proprietor", "characteristic", "denotation"),
    "episodic-cell": ("chronicle", "retrospect", "antecedent"),
    "procedural-cell": ("enforce", "adjudicate", "perform"),
}
TRAIN_TEMPLATES = {
    "direct": "Please find {cue} for {key}.",
    "question": "For {key}, which {cue} should I consult?",
}
HELD_TEMPLATES = (
    "Regarding {key}, return its {cue}.",
    "The next lookup concerns {cue}; item {key} is newly supplied.",
    "Could the {cue} associated with {key} be supplied?",
)
DESIGN = {
    "training_families": list(TRAIN_TEMPLATES),
    "repetitions_per_training_cue": 4,
    "public_alias_per_type": 8,
    "known_cue_per_type": 12,
    "unseen_synonym_per_type": 12,
    "rejection_queries_per_group": 12,
    "training_examples": 128,
    "held_queries": 156,
    "training_cues": [
        {"route": route, "cues": list(cues)} for route, cues in TRAIN_CUES.items()
    ],
    "held_synonyms": SYNONYMS,
    "typed_input_scope": "public structured cell_type supplied by caller, an explicitly richer interface",
    "learned_literal_input_scope": "request.text and request.scope only; cell_type is always None",
    "seed_effect": "initialization, order and identifiers vary; numeric identifiers are excluded from lexical features; cue and wording design is shared",
    "overall_weighting": "query-count-weighted frozen mix; per-group results distinguish unequal interface capabilities",
    "learned_mode_scope": "trained linear softmax plus deterministic scope/declaration checks and evidence-consensus gates; rejection is not solely learned",
    "oracle_scope": "annotated ideal decisions including rejection; no executable oracle is passed to a router",
}


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


@dataclass(frozen=True)
class RoutingExample:
    query_id: str
    key: str
    text: str
    scope: str
    declared_type: str | None
    target: str | None
    group: str


def requests_for(examples, mode):
    if mode not in ("typed", "literal", "learned"):
        raise ValueError("unknown route mode")
    return [
        RouteRequest(e.text, e.scope, e.declared_type if mode == "typed" else None)
        for e in examples
    ]


def build_routing_data(seed):
    training = {"texts": [], "labels": [], "families": [], "keys": []}
    counter = 0
    for family, template in TRAIN_TEMPLATES.items():
        for route, cues in TRAIN_CUES.items():
            for cue in cues:
                for _ in range(DESIGN["repetitions_per_training_cue"]):
                    key = f"record-{seed}-{counter:06d}"
                    training["texts"].append(template.format(cue=cue, key=key))
                    training["labels"].append(route)
                    training["families"].append(family)
                    training["keys"].append(key)
                    counter += 1
    rng = np.random.default_rng(seed)
    permutation = rng.permutation(len(training["texts"])).tolist()
    training = {
        name: [values[i] for i in permutation] for name, values in training.items()
    }
    held = []

    def add(group, text, scope, declared_type, target):
        key = f"query-{seed}-{len(held):06d}"
        text = text.format(key=key)
        identity = sha256(
            canonical([group, key, text, scope, declared_type])
        ).hexdigest()
        held.append(
            RoutingExample(identity, key, text, scope, declared_type, target, group)
        )

    for spec in SPECS:
        for group, cues, count in (
            ("public_type_alias", (spec.cell_type,), DESIGN["public_alias_per_type"]),
            (
                "known_cue_new_keys",
                TRAIN_CUES[spec.route_id][1:],
                DESIGN["known_cue_per_type"],
            ),
            (
                "unseen_synonyms",
                SYNONYMS[spec.route_id],
                DESIGN["unseen_synonym_per_type"],
            ),
        ):
            for index in range(count):
                text = HELD_TEMPLATES[index % len(HELD_TEMPLATES)].replace(
                    "{cue}", cues[index % len(cues)]
                )
                add(group, text, SCOPE, spec.cell_type, spec.route_id)
    for index in range(DESIGN["rejection_queries_per_group"]):
        first, second = SPECS[index % 3], SPECS[(index + 1) % 3]
        cue = TRAIN_CUES[first.route_id][1]
        text = "Return " + cue + " for {key}."
        add(
            "unknown_scope",
            text if index % 2 == 0 else text + " scope=foreign",
            "foreign" if index % 2 == 0 else SCOPE,
            first.cell_type,
            None,
        )
        add(
            "unknown_cue",
            "Discuss "
            + ("astronomy", "gardening", "sonnets")[index % 3]
            + " about {key}.",
            SCOPE,
            None,
            None,
        )
        pair = (
            (first.cell_type, second.cell_type)
            if index % 2 == 0
            else (TRAIN_CUES[first.route_id][1], TRAIN_CUES[second.route_id][1])
        )
        add(
            "ambiguous",
            "Find both " + pair[0] + " and " + pair[1] + " for {key}.",
            SCOPE,
            None,
            None,
        )
        add(
            "conflict",
            f"type={first.cell_type} route={second.route_id}; read {{key}}.",
            SCOPE,
            first.cell_type,
            None,
        )
        add(
            "refusal",
            "Decline this " + first.cell_type + " request for {key}; do not route it.",
            SCOPE,
            first.cell_type,
            None,
        )
    held = tuple(held[i] for i in rng.permutation(len(held)))
    if set(training["keys"]) & {e.key for e in held}:
        raise ValueError("training/held effective key overlap")
    return training, held


def decision_metrics(targets, predictions):
    if len(targets) != len(predictions) or not targets:
        raise ValueError("aligned nonempty decision arrays required")
    accepted = sum(value is not None for value in predictions)
    correct_accepted = sum(
        p is not None and p == t for t, p in zip(targets, predictions)
    )
    rejects = sum(t is None for t in targets)
    correct_rejects = sum(t is None and p is None for t, p in zip(targets, predictions))
    wrong = sum(p is not None and p != t for t, p in zip(targets, predictions))
    accuracy = (correct_accepted + correct_rejects) / len(targets)
    return {
        "queries": len(targets),
        "decision_accuracy": accuracy,
        "coverage": accepted / len(targets),
        "conditional_accuracy": correct_accepted / accepted if accepted else None,
        "reject_recall": correct_rejects / rejects if rejects else None,
        "wrong_accepted": wrong,
        "wrong_accepted_rate": wrong / len(targets),
        "accepted": accepted,
        "expected_rejects": rejects,
        "correct_accepted": correct_accepted,
        "correct_rejects": correct_rejects,
        "missed_known": sum(
            t is not None and p is None for t, p in zip(targets, predictions)
        ),
        "oracle_decision_accuracy": 1.0,
        "oracle_gap": 1.0 - accuracy,
    }


def _timed(router, requests, mode):
    started = time.perf_counter()
    decisions = router.route(requests, mode)
    return decisions, time.perf_counter() - started


def _raw_rows(examples, decisions, requests):
    return [
        {
            **asdict(example),
            "requests": {mode: asdict(values[i]) for mode, values in requests.items()},
            "decisions": {
                mode: asdict(values[i]) for mode, values in decisions.items()
            },
        }
        for i, example in enumerate(examples)
    ]


def _write_lines(path, rows):
    blob = b"".join(canonical(row) + b"\n" for row in rows)
    path.write_bytes(blob)
    return sha256(blob).hexdigest()


def _run_seed(profile, directory, source_commit, seed):
    started = time.perf_counter()
    directory.mkdir(parents=True)
    training, examples = build_routing_data(seed)
    _json(directory / "training.json", training)
    _json(directory / "held-queries.json", [asdict(e) for e in examples])
    learned = Router(SPECS, SCOPE, seed, profile["threshold"], profile["margin"])
    receipt = learned.fit(
        training["texts"],
        training["labels"],
        families=training["families"],
        steps=profile["steps"],
        lr=profile["learning_rate"],
    )
    rule = Router(SPECS, SCOPE, seed, profile["threshold"], profile["margin"])
    routers = {"typed": rule, "literal": rule, "learned": learned}
    requests = {mode: requests_for(examples, mode) for mode in routers}
    before = {
        mode: router.route(requests[mode], mode) for mode, router in routers.items()
    }
    trained_requests = [RouteRequest(text, SCOPE) for text in training["texts"]]
    training_decisions = learned.route(trained_requests, "learned")
    training_operational = decision_metrics(
        training["labels"], [d.route_id for d in training_decisions]
    )
    save_started = time.perf_counter()
    learned_manifest = learned.save(directory / "learned-router")
    rule.save(directory / "rule-router")
    save_seconds = time.perf_counter() - save_started
    reload_started = time.perf_counter()
    restored_learned = Router.load(directory / "learned-router", expected_scope=SCOPE)
    restored_rule = Router.load(directory / "rule-router", expected_scope=SCOPE)
    reload_seconds = time.perf_counter() - reload_started
    loaded = {
        "typed": restored_rule,
        "literal": restored_rule,
        "learned": restored_learned,
    }
    after, latency, metrics = {}, {}, {}
    for mode, router in loaded.items():
        after[mode], latency[mode] = _timed(router, requests[mode], mode)
        metrics[mode] = {
            "all": decision_metrics(
                [e.target for e in examples], [d.route_id for d in after[mode]]
            ),
            "groups": {
                group: decision_metrics(
                    [e.target for e in examples if e.group == group],
                    [
                        d.route_id
                        for e, d in zip(examples, after[mode])
                        if e.group == group
                    ],
                )
                for group in sorted({e.group for e in examples})
            },
            "reason_counts": dict(Counter(d.reason for d in after[mode])),
            "group_reason_counts": {
                group: dict(
                    Counter(
                        d.reason
                        for e, d in zip(examples, after[mode])
                        if e.group == group
                    )
                )
                for group in sorted({e.group for e in examples})
            },
        }
    before_digest = _write_lines(
        directory / "predictions-before-reload.jsonl",
        _raw_rows(examples, before, requests),
    )
    after_digest = _write_lines(
        directory / "predictions.jsonl", _raw_rows(examples, after, requests)
    )
    if before != after or before_digest != after_digest:
        raise ValueError("saved router changed an actual decision on reload")
    digest_payload = {name: training[name] for name in ("texts", "labels", "families")}
    if receipt["training_digest"] != sha256(canonical(digest_payload)).hexdigest():
        raise ValueError("training receipt is not bound to the saved examples")
    storage = {}
    for mode, router in loaded.items():
        artifact = directory / (
            "learned-router" if mode == "learned" else "rule-router"
        )
        storage[mode] = {
            "parameter_bytes": router.parameter_bytes,
            "trainable_params": router.trainable_params,
            "artifact_bytes": sum(p.stat().st_size for p in artifact.iterdir()),
            "vocabulary_payload_bytes": len(canonical(router.vocabulary)),
            "schema_payload_bytes": len(
                canonical({"scope": SCOPE, "specs": [asdict(s) for s in SPECS]})
            ),
            "artifact": artifact.name,
            "shared_with": "literal"
            if mode == "typed"
            else "typed"
            if mode == "literal"
            else None,
        }
    receipt.update(
        {
            "source_commit": source_commit,
            "save_seconds": save_seconds,
            "reload_seconds": reload_seconds,
            "artifact_digest": learned_manifest["artifact_digest"],
            "actual_reload_predictions_equal": True,
            "raw_predictions_sha256": after_digest,
            "training_data_file_sha256": sha256(
                (directory / "training.json").read_bytes()
            ).hexdigest(),
        }
    )
    _json(directory / "training-receipt.json", receipt)
    result = {
        "seed": seed,
        "metrics": metrics,
        "storage": storage,
        "latency_seconds": latency,
        "latency_seconds_per_query": {
            mode: value / len(examples) for mode, value in latency.items()
        },
        "raw_training_accuracy": receipt["training_accuracy"],
        "operational_training_metrics": training_operational,
        "training_receipt": receipt,
        "reload_same_predictions": True,
        "raw_predictions_sha256": after_digest,
        "training_held_keys_disjoint": True,
        "training_examples": len(training["texts"]),
        "held_queries": len(examples),
        "latency_scope": "one actual post-load batch per mode; no latency confidence interval",
        "study_wall_seconds_before_summary": time.perf_counter() - started,
        "research_physical_bytes_before_summary": sum(
            p.stat().st_size for p in directory.rglob("*") if p.is_file()
        ),
        "claim_scope": "known-cue addressing is distinct from unseen-synonym semantic routing; typed input is richer; no end-to-end memory advantage inferred",
    }
    _json(directory / "summary.json", result)
    return result


def run_routing(
    protocol, output_dir: Path, source_commit: str, seeds: list[int], development=False
) -> dict:
    profile = dict(protocol["routing_v2_profile"])
    if profile != DEFAULT_PROFILE:
        raise ValueError(
            "routing schedule and thresholds are frozen; no hidden-set tuning"
        )
    if development and set(seeds) - {8001, 8003}:
        raise ValueError("development is limited to seeds 8001 and 8003")
    if not development and list(seeds) != protocol.get("seeds"):
        raise ValueError("formal seeds must exactly match the frozen protocol")
    directory = Path(output_dir) / "routing"
    directory.mkdir(parents=True, exist_ok=False)
    _json(
        directory / "config.json",
        {
            "profile": profile,
            "design": DESIGN,
            "source_commit": source_commit,
            "source_module_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "router_module_sha256": sha256(
                Path(Router.fit.__code__.co_filename).read_bytes()
            ).hexdigest(),
            "seeds": seeds,
            "development_only": development,
            "runtime": {
                "python": platform.python_version(),
                "numpy": np.__version__,
                "platform": platform.system(),
                "thread_settings": {
                    key: os.environ.get(key)
                    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")
                },
            },
        },
    )
    result = {
        "stage": "routing_v2",
        "profile": profile,
        "design": DESIGN,
        "development_only": development,
        "runs": [
            _run_seed(profile, directory / f"seed-{seed}", source_commit, seed)
            for seed in seeds
        ],
    }
    _json(directory / "summary.json", result)
    return result
