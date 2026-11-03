"""Actual routing for real-source task headers; keys never become route cues.

This profile recognizes a supplied task schema. It does not establish open-domain
question understanding. Labels are learned from training requests; declared task
aliases remain an independently reported deterministic baseline.
"""

import re

from .router import Router, RouteRequest, RouteSpec


TASK_KINDS = {
    "module_attribute": "semantic",
    "latest_sampled_change": "episodic",
    "schema_execution": "procedural",
    "schema_chain": "semantic",
    "commit_owner_chain": "episodic",
}


def header(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 16384:
        raise ValueError("invalid task-address text")
    parts = re.split(r"\s+for\s+", text, maxsplit=1, flags=re.IGNORECASE)
    return parts[0] if len(parts) == 2 else "unregistered-task"


def fit_router(bundles, profile, seed, directory):
    specs = [
        RouteSpec(
            kind,
            kind,
            tuple(task for task, owner in TASK_KINDS.items() if owner == kind),
        )
        for kind in ("semantic", "episodic", "procedural")
    ]
    router = Router(
        specs,
        seed=seed,
        threshold=profile["router_threshold"],
        margin=profile["router_margin"],
    )
    queries = [query for bundle in bundles.values() for query in bundle.train]
    observed = sorted(
        {(header(query.text), TASK_KINDS[query.task]) for query in queries}
    )
    task_kinds = sorted({(query.task, TASK_KINDS[query.task]) for query in queries})
    texts, labels, families = [], [], []
    groups = [observed] + [
        [(f"{verb} {task}", kind) for task, kind in task_kinds]
        for verb in ("Locate", "Inspect")
    ]
    for index, group in enumerate(groups):
        for text, label in [*group, ("unregistered-task", None)]:
            texts.append(text)
            labels.append(label)
            families.append(f"write-time-task-header-{index}")
    receipt = router.fit(
        texts,
        labels,
        families=families,
        steps=profile["router_steps"],
        lr=profile["router_learning_rate"],
    )
    receipt.update(
        raw_training_query_count=len(queries),
        distinct_training_headers=len(observed),
        addressing_scope="public-task-header-before-for;no-key-features;not-open-QA",
    )
    manifest = router.save(directory)
    restored = Router.load(directory, expected_scope="research")
    probes = [RouteRequest(text) for text in texts]
    if restored.route(probes) != router.route(probes):
        raise ValueError("router reload changed actual routing decisions")
    return restored, receipt, manifest


def route_queries(router, queries, mode):
    if mode == "typed":
        requests = [
            RouteRequest(header(query.text), cell_type=TASK_KINDS[query.task])
            for query in queries
        ]
    else:
        # No task, cell_type, key, target or oracle label is consumed here.
        requests = [RouteRequest(header(query.text)) for query in queries]
    return router.route(requests, mode=mode)
