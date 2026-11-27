"""Real checkpoint population lifecycle, independent of final task scores."""

from dataclasses import asdict

from evolution_common import require, retain
from topology_owner import ActualOwners
from topology_store import TopologyStore


def candidate(cell, trained, support, derivation="clean_replay"):
    return dict(
        cell_id=cell,
        role="semantic",
        directory=trained["directory"],
        manifest_sha256=trained["manifest_sha256"],
        support_roots=support,
        derivation=derivation,
    )


def prepare_population(runtime):
    source = runtime.source_setup()
    base = runtime.build()
    retain(runtime.output / "base-result.json", base)
    groups = {}
    leaves = {c["case_id"]: c["leaf"] for c in runtime.protocol["cases"]}
    for name in runtime.protocol["cells"]:
        groups[name] = [
            f
            for f in source["facts"]
            if (name == "hint" and f["relation"] == "hint")
            or (f["relation"] == "color" and leaves[f["entity"]] == name)
        ]
    trained = {name: runtime.train(name, facts) for name, facts in groups.items()}
    topology = TopologyStore(
        runtime.output / "topology",
        runtime.protocol["scope"],
        runtime.frontier,
        ActualOwners(runtime.repo / "scripts"),
    )
    selected = [
        candidate(name, trained[name], [f["source_digest"] for f in groups[name]])
        for name in runtime.protocol["cells"]
    ]
    prepared = topology.prepare(
        "initial-population",
        "bootstrap",
        expected_generation=0,
        inputs=[],
        candidates=selected,
    )
    receipt = topology.commit("initial-population")
    retain(
        runtime.output / "topology-bootstrap.json",
        dict(prepared=prepared, receipt=receipt),
    )
    return topology, trained, groups


def exercise_topology(runtime, topology, trained, groups):
    events = []
    initial = topology.snapshot()
    support = [f["source_digest"] for f in groups["hint"]]
    children = [
        candidate("hint-0", trained["hint"], support[:3], "reuse"),
        candidate("hint-1", trained["hint"], support[3:], "reuse"),
    ]
    topology.prepare(
        "split-hint",
        "split",
        expected_generation=initial["generation"],
        inputs=["hint"],
        candidates=children,
    )
    split = topology.commit("split-hint")
    events.append(split)
    topology.prepare(
        "merge-hint",
        "merge",
        expected_generation=split["generation"],
        inputs=["hint-0", "hint-1"],
        candidates=[candidate("hint", trained["hint"], support)],
    )
    merged = topology.commit("merge-hint")
    events.append(merged)
    rolled = topology.rollback(
        "restore-split", split["generation"], expected_generation=merged["generation"]
    )
    events.append(rolled)
    restored = topology.rollback(
        "restore-merged", merged["generation"], expected_generation=rolled["generation"]
    )
    events.append(restored)
    after = topology.snapshot()
    require(
        {k: v["manifest_sha256"] for k, v in initial["cells"].items()}
        == {k: v["manifest_sha256"] for k, v in after["cells"].items()},
        "fixed population decoder weights changed through lifecycle",
    )
    require(
        after["cells"]["hint"]["version"] > initial["cells"]["hint"]["version"],
        "stable identity generation did not advance",
    )
    retain(
        runtime.output / "topology-lifecycle.json",
        dict(
            initial=initial,
            after=after,
            events=events,
            additional_training_updates=0,
            split_is_fixed_clone_partition=True,
            merge_reuses_prepared_joint_replay=True,
            production_accepted=False,
        ),
    )
    return split["generation"]


def activate_edges(topology, policy, operation_id):
    current = topology.snapshot()
    edges = (
        []
        if policy.recipe == "no-edges"
        else [["hint", target] for target in policy.targets]
    )
    topology.prepare(
        operation_id,
        "rewire",
        expected_generation=current["generation"],
        inputs=[],
        candidates=[],
        edges=edges,
        edge_policy=policy.binding,
    )
    return topology.commit(operation_id)


def withdrawal_rebuild(
    runtime, topology, trained, old_split_generation, learned_policy
):
    activate_edges(topology, learned_policy, "before-withdrawal-learned-policy")
    first = runtime.protocol["cases"][0]
    receipt = runtime.authority.revoke(first["case_id"] + "_hint", 0)
    remaining = [
        f for f in runtime.authority.snapshot()["facts"] if f["relation"] == "hint"
    ]
    callbacks, rejected = [], {}
    for name, operation in (
        (
            "parameter_ancestry",
            lambda: topology.invoke(
                "hint",
                [remaining[0]["source_digest"]],
                lambda active: callbacks.append(active.cell_id),
            ),
        ),
        ("learned_edge_ancestry", topology.graph_snapshot),
        (
            "old_topology_rollback",
            lambda: topology.rollback(
                "forbidden-revival",
                old_split_generation,
                expected_generation=topology.snapshot()["generation"],
            ),
        ),
    ):
        try:
            operation()
        except ValueError as error:
            rejected[name] = str(error)
    require(
        len(rejected) == 3 and callbacks == [],
        "withdrawal did not close old parameter/edge/rollback paths",
    )
    retain(
        runtime.output / "withdrawal-denials.json",
        dict(
            source_receipt=asdict(receipt),
            rejected=rejected,
            model_callbacks=len(callbacks),
        ),
    )
    rebuilt = runtime.train("hint-after-withdrawal", remaining)
    generation = topology.snapshot()["generation"]
    topology.prepare(
        "rebuild-after-withdrawal",
        "refresh",
        expected_generation=generation,
        inputs=["hint"],
        candidates=[
            candidate("hint", rebuilt, [f["source_digest"] for f in remaining])
        ],
    )
    published = topology.commit("rebuild-after-withdrawal")
    first_remaining = remaining[0]
    prompt = "What is the hint for " + first_remaining["entity"] + "?"
    row = topology.invoke(
        "hint",
        [first_remaining["source_digest"]],
        lambda active: runtime.reader(active, prompt),
    )
    retain(
        runtime.output / "withdrawal-rebuild.json",
        dict(
            training=rebuilt,
            publication=published,
            admitted_raw_row=row,
            old_learned_policy_not_reauthorized=True,
            old_checkpoints_retained=True,
            source_withdrawal_is_not_physical_erasure=True,
        ),
    )
    return dict(
        denied=len(rejected),
        denial_callbacks=0,
        fresh_replay_updates=rebuilt["training"]["steps"],
        old_edge_policy_cleared=topology.snapshot()["edge_policy"]["recipe"]
        == "no-edges",
    )
