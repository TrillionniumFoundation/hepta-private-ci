"""Execute source-selected adapters behind a durable local research owner."""

from pathlib import Path

from parametric_cohort import questions, score, TEST_TEMPLATE
from parametric_evolution import route_questions
from parametric_owner import Frontier, ParametricOwner


def read_network(cell, *, model, evolution, facts, output, read_worker, write_json):
    output = Path(output)
    output.mkdir()
    (output / "reader-cwd").mkdir()
    scope = facts[0]["scope"]
    roots = {f["source_digest"] for f in facts}
    view = Frontier(scope)
    owner = ParametricOwner(output / "network.sqlite3")
    query = questions(facts, TEST_TEMPLATE)
    routing = route_questions(cell, query, evolution["router"])
    write_json(output / "routing.json", routing)
    write_json(
        output / "precommitted-selection.json",
        {
            "chosen_arm": evolution["chosen_arm"],
            "chosen_cells": evolution["chosen_cells"],
            "selection_rule": evolution["selection_rule"],
            "test_scores_used": False,
        },
    )
    all_rows, calls = {}, []
    for arm in ("nochange", "continue", "split"):
        rows = [None] * len(facts)
        for slot, version in enumerate(evolution["arms"][arm]["cells"]):
            key = f"{arm}-{slot}"
            owner.activate(
                key,
                version["directory"],
                version["manifest_sha256"],
                scope=scope,
                expected_current=None,
                generation=0,
                provider=lambda: view,
                allowed_roots=roots,
            )
            indices = [i for i, routed in enumerate(routing["slots"]) if routed == slot]
            if not indices:
                continue
            journal = owner.invoke(
                key,
                scope,
                lambda: view,
                lambda active: read_worker(
                    model,
                    active.directory,
                    active.manifest_sha256,
                    scope,
                    active.roots,
                    [query[i] for i in indices],
                    output,
                    key,
                ),
            )
            for index, record in zip(indices, journal["rows"], strict=True):
                rows[index] = record
            calls.append(
                dict(
                    cell=key,
                    query_indices=indices,
                    manifest_sha256=version["manifest_sha256"],
                    fresh_process_wall_seconds=journal["fresh_process_wall_seconds"],
                )
            )
        if any(row is None for row in rows):
            raise ValueError("network omitted a routed query")
        all_rows[arm] = rows
    # Scores cannot influence the already persisted selection or routing.
    metrics = {arm: score(rows, facts) for arm, rows in all_rows.items()}
    result = dict(
        schema="hepta.parametric-memory.local-network.v1",
        chosen_arm=evolution["chosen_arm"],
        metrics=metrics,
        routed_calls=calls,
        active_slots_per_query=1,
        fresh_decoder_processes=len(calls),
        nochange_slots_share_one_parent_artifact=True,
        router_input_tokens=routing["embedding_charge"]["input_tokens"],
        physical_hosts=1,
        distributed_consensus_tested=False,
        worker_data_inputs="weights, scope, provenance hashes and question strings",
        production_accepted=False,
    )
    write_json(output / "result.json", result)
    return result
