"""Closed split/merge/rollback plans; support allocation never erases ancestry."""

from evolution_common import digest, identifier, require, roots

MAX_CELLS = 16
MAX_HISTORY = 256


def candidate(value):
    fields = {
        "cell_id",
        "role",
        "directory",
        "manifest_sha256",
        "support_roots",
        "derivation",
    }
    require(
        type(value) is dict and set(value) == fields,
        "closed checkpoint candidate required",
    )
    identifier(value["cell_id"])
    require(value["role"] in ("semantic", "procedural"), "unregistered cell role")
    require(
        value["derivation"] in ("inherit", "clean_replay", "reuse"),
        "explicit checkpoint derivation required",
    )
    require(
        type(value["directory"]) is str
        and 0 < len(value["directory"].encode()) <= 4096,
        "bounded checkpoint path",
    )
    roots([value["manifest_sha256"]])
    support = roots(value["support_roots"])
    require(support, "empty cell support")
    return value | {"support_roots": support}


def edge_contract(edges, policy, cells, frontier):
    require(type(edges) is list and len(edges) <= MAX_CELLS**2, "bounded edge list")
    require(
        all(
            type(e) is list
            and len(e) == 2
            and e[0] in cells
            and e[1] in cells
            and e[0] != e[1]
            for e in edges
        ),
        "edge endpoint is absent or self-referential",
    )
    require(len({tuple(e) for e in edges}) == len(edges), "duplicate edge")
    require(
        type(policy) is dict and set(policy) == {"recipe", "sha256", "ancestry_roots"},
        "closed edge policy binding",
    )
    identifier(policy["recipe"])
    roots([policy["sha256"]])
    ancestry = roots(policy["ancestry_roots"])
    require(
        set(ancestry) <= set(frontier["roots"]), "edge training ancestry is not current"
    )
    return sorted(edges), policy | {"ancestry_roots": ancestry}


def make_plan(
    op_id,
    kind,
    current,
    inputs,
    candidates,
    latest,
    frontier,
    edges,
    policy,
    target_generation=None,
):
    identifier(op_id)
    require(
        type(inputs) is list
        and len(set(inputs)) == len(inputs)
        and all(c in current["cells"] for c in inputs),
        "distinct active input cells required",
    )
    require(
        type(candidates) is list and len(candidates) <= MAX_CELLS,
        "bounded candidate population",
    )
    selected = [candidate(c) for c in candidates]
    output_ids = [c["cell_id"] for c in selected]
    require(len(set(output_ids)) == len(output_ids), "duplicate output cell identity")
    require(
        not set(output_ids) & (set(current["cells"]) - set(inputs)),
        "output collides with unaffected cell",
    )
    if kind == "bootstrap":
        require(
            not inputs and not current["cells"] and selected,
            "bootstrap requires empty population",
        )
    elif kind == "split":
        require(
            len(inputs) == 1 and len(selected) >= 2 and inputs[0] not in output_ids,
            "split replaces one identity with distinct children",
        )
        parts = [set(c["support_roots"]) for c in selected]
        require(
            sum(map(len, parts)) == len(set.union(*parts)),
            "split support allocations overlap",
        )
        require(
            set.union(*parts) == set(current["cells"][inputs[0]]["support_roots"]),
            "split must partition complete parent support",
        )
    elif kind == "merge":
        require(
            len(inputs) >= 2 and len(selected) == 1,
            "merge needs multiple parents and one output",
        )
        require(
            set(selected[0]["support_roots"])
            == set().union(
                *(set(current["cells"][c]["support_roots"]) for c in inputs)
            ),
            "merge must retain union of support",
        )
        require(
            selected[0]["derivation"] == "clean_replay",
            "merge uses measured fresh-base replay, never weight arithmetic",
        )
    elif kind == "refresh":
        require(
            inputs and set(output_ids) <= set(inputs),
            "refresh preserves stable identities",
        )
        removed = set(inputs) - set(output_ids)
        require(
            all(
                not set(current["cells"][c]["support_roots"]) & set(frontier["roots"])
                for c in removed
            ),
            "refresh cannot retire currently supported roots",
        )
    elif kind == "rewire":
        require(not inputs and not selected, "rewire cannot replace cell parameters")
    elif kind == "retire":
        require(
            inputs and not selected,
            "retire requires active identities and no replacement",
        )
        require(
            all(
                not set(current["cells"][c]["support_roots"]) & set(frontier["roots"])
                for c in inputs
            ),
            "retire cannot discard current supported roots",
        )
    elif kind == "rollback":
        require(
            set(inputs) == set(current["cells"])
            and type(target_generation) is int
            and target_generation < current["generation"],
            "rollback requires a prior committed topology",
        )
        before = set().union(
            *(set(c["support_roots"]) for c in current["cells"].values())
        )
        after = (
            set().union(*(set(c["support_roots"]) for c in selected))
            if selected
            else set()
        )
        require(
            after == before, "rollback cannot silently discard newly supported sources"
        )
    else:
        raise ValueError("unregistered topology operation")
    remaining = {k: v for k, v in current["cells"].items() if k not in inputs}
    require(
        len(remaining) + len(selected) <= MAX_CELLS, "live population budget exceeded"
    )
    parents = [current["cells"][c] for c in inputs]
    for c in selected:
        require(
            set(c["support_roots"]) <= set(frontier["roots"]),
            "candidate support is withdrawn or not authorized",
        )
        old = latest.get(c["cell_id"])
        require(
            old is None or old["role"] == c["role"], "stable cell role cannot change"
        )
        c["version"] = old["version"] + 1 if old else 0
        c["previous"] = old
        c["parents"] = [
            dict(
                cell_id=p["cell_id"],
                version=p["version"],
                manifest_sha256=p["manifest_sha256"],
                roots=p["roots"],
            )
            for p in parents
        ]
        if kind == "rollback":
            c["rollback_pinned_manifest"] = c["manifest_sha256"]
        remaining[c["cell_id"]] = c
    edges, policy = edge_contract(edges, policy, remaining, frontier)
    value = dict(
        schema="hepta.topology.plan.v1",
        operation_id=op_id,
        kind=kind,
        base_generation=current["generation"],
        source_frontier=frontier,
        inputs=inputs,
        candidates=selected,
        edges=edges,
        edge_policy=policy,
        rollback_target=target_generation,
        production_accepted=False,
    )
    return value | {"plan_sha256": digest(value)}


def empty_policy():
    return dict(
        recipe="no-edges",
        sha256=digest({"recipe": "no-edges", "edges": []}),
        ancestry_roots=[],
    )
