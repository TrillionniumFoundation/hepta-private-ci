"""Owner-admitted fresh readers for a previously selected arrival experiment."""

from dataclasses import asdict
from pathlib import Path

from growth_policy import ARMS
from growth_runtime import typed_slot
from parametric_cohort import questions, score
from parametric_owner import Frontier, ParametricOwner


def read_arms(
    *,
    model,
    report,
    old,
    incoming,
    frontier,
    output,
    final_template,
    read_worker,
    write_json,
):
    """Read only after byte and withdrawal admission; score after all journals."""
    scope = old[0]["scope"]
    if type(frontier) is not Frontier or frontier.scope != scope:
        raise ValueError("independently supplied scope frontier required")
    if Frontier(**report["source_frontier"]) != frontier:
        raise ValueError("source frontier changed since candidate training")
    facts = old + incoming
    allowed = {row["source_digest"] for row in facts}
    if allowed & set(frontier.revoked):
        raise ValueError("withdrawn final query source")
    for versions in report["versions"].values():
        for version in versions:
            roots = set(version["roots"])
            if not roots <= allowed or roots & set(frontier.revoked):
                raise ValueError("unadmitted or withdrawn candidate ancestor")
    output = Path(output)
    output.mkdir(exist_ok=False)
    (output / "reader-cwd").mkdir()
    write_json(output / "owner-frontier.json", asdict(frontier))
    owner = ParametricOwner(output / "owner.sqlite3")
    provider = lambda: frontier
    query = questions(facts, final_template)
    rows_by_arm, calls, activations = {}, [], []
    for arm in ARMS:
        rows = [None] * len(facts)
        for slot, version in enumerate(report["versions"][arm]):
            cell_id = f"{arm}-{slot}"
            active = owner.activate(
                cell_id,
                version["directory"],
                version["manifest_sha256"],
                scope=scope,
                expected_current=None,
                generation=0,
                provider=provider,
                allowed_roots=allowed,
            )
            activations.append(asdict(active))
            indices = [
                i
                for i, fact in enumerate(facts)
                if typed_slot(arm, fact["relation"]) == slot
            ]
            known_query_roots = {
                facts[i]["source_digest"]
                for i in indices
                if facts[i]["source_digest"] in active.roots
            }
            unwritten = [
                i for i in indices if facts[i]["source_digest"] not in active.roots
            ]
            if unwritten and arm != "nochange":
                raise ValueError("only nochange may emit unwritten diagnostics")

            def invoke(admitted):
                return read_worker(
                    model,
                    admitted.directory,
                    admitted.manifest_sha256,
                    scope,
                    admitted.roots,
                    [query[i] for i in indices],
                    output,
                    cell_id,
                )

            journal = owner.invoke(
                cell_id,
                scope,
                provider,
                invoke,
                query_roots=known_query_roots,
            )
            for index, row in zip(indices, journal["rows"], strict=True):
                rows[index] = row
            calls.append(
                {
                    "arm": arm,
                    "slot": slot,
                    "query_indices": indices,
                    "manifest_sha256": version["manifest_sha256"],
                    "fresh_process_wall_seconds": journal["fresh_process_wall_seconds"],
                    "unwritten_diagnostic_indices": unwritten,
                    "owner_admitted_before_and_after": True,
                }
            )
        rows_by_arm[arm] = rows
    # All journals exist before gold is used for final scoring.
    metrics = {
        arm: {
            "old": score(rows[: len(old)], old),
            "new": score(rows[len(old) :], incoming),
            "all": score(rows, facts),
        }
        for arm, rows in rows_by_arm.items()
    }
    result = {
        "schema": "hepta.parametric-memory.arrival-reads.v1",
        "chosen_before_final_read": report["selection"]["chosen_arm"],
        "metrics": metrics,
        "routed_calls": calls,
        "work": {
            arm: {
                "input_tokens": sum(row["input_tokens"] for row in rows),
                "generated_tokens": sum(row["generated_tokens"] for row in rows),
                "generation_seconds": sum(row["seconds"] for row in rows),
                "fresh_process_wall_seconds": sum(
                    call["fresh_process_wall_seconds"]
                    for call in calls
                    if call["arm"] == arm
                ),
            }
            for arm, rows in rows_by_arm.items()
        },
        "fresh_worker_processes": len(calls),
        "active_versions": activations,
        "source_frontier": asdict(frontier),
        "frontier_is_pinned_local_snapshot": True,
        "nochange_new_answers_are_unwritten_diagnostics": True,
        "reader_answer_values_or_lexicon_input": False,
        "owner_database_bytes": (output / "owner.sqlite3").stat().st_size,
        "physical_hosts": 1,
        "production_accepted": False,
    }
    write_json(output / "result.json", result)
    return result
