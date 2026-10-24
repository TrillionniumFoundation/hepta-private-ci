"""Same 28 original-input load requests; retain rejects and budget stops."""

from budget_ledger import digest
from cohort_contract import retain
from model_budget import model_call


def continued_load(versions, queries, routes, records, ledger, args, directory):
    natural = [q for q in queries if q["kind"] == "natural_time_holdout"]
    slots = {r["query_id"]: r["slot"] for r in routes}
    observations = []
    stop = None
    for repetition in range(7):
        for slot, version in enumerate(versions):
            selected = [q for q in natural if slots[q["id"]] == slot]
            if not selected:
                continue
            state = ledger.snapshot()
            remaining = {
                k: state["config"]["limits"][k] - state["used"][k] - state["pending"][k]
                for k in state["used"]
            }
            # Preserve capacity for the complete final file inventory.
            if (
                remaining["decoder_queries"] < len(selected)
                or remaining["wall_ns"] < 95 * 10**9
                or remaining["read_bytes"] < 2 * 1024**3
            ):
                stop = "common_budget_preserves_final_inventory"
                break
            event = f"load-{repetition}-{slot}"
            request = dict(
                phase="read",
                model=str(args.model),
                version=version,
                allowed_roots=[r["source_digest"] for r in records],
                questions=[q["question"] for q in selected],
                control="adapter",
            )
            measured = model_call(
                ledger,
                event,
                request,
                implementation=args.implementation,
                directory=directory / event,
                maximum_seconds=60,
            )
            raw = measured["output"]
            rows = {
                index: row for index, row in zip(raw["indices"], raw["journal"]["rows"])
            }
            rejected = {r["index"]: r for r in raw["rejected"]}
            observations.extend(
                dict(
                    repetition=repetition,
                    query_id=query["id"],
                    slot=slot,
                    raw=rows.get(index),
                    rejection=rejected.get(index),
                    measurement_sha256=digest(measured),
                )
                for index, query in enumerate(selected)
            )
        if stop:
            break
    result = dict(
        planned_requests=28,
        completed_requests=len(observations),
        uncompleted_requests=28 - len(observations),
        actual_decoder_queries=sum(r["raw"] is not None for r in observations),
        observations=observations,
        independent_task_count=4,
        requests_are_repeated_original_inputs=True,
        stop_reason=stop,
        fresh_process_per_active_slot_per_repetition=True,
    )
    retain(directory / "continuous-load.json", result)
    return result
