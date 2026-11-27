"""Source-step intervention panel; final inference has no access to these labels."""

from evolution_common import digest, require, retain


def observe_source(executor, task, targets, source_value, *, output):
    graph, frontier = executor.topology.graph_snapshot()
    entry = executor._capability(task["entry_cell"], task["entity"], "hint")
    require(entry is not None, "source entry capability absent")
    first_trace = []
    first = executor._step(task["entry_cell"], entry, entry["question"], first_trace)
    require(first is not None, "source entry invocation failed")
    retain(output / "entry.json", first_trace)
    state = dict(
        question=entry["question"], cell_id=task["entry_cell"], raw_text=first["text"]
    )
    observed, source_roots = {}, set(entry["source_roots"])
    # Raw model output depends on all learned ancestors, not just the queried
    # source capability. Retain a conservative closure even for partial panels.
    for cell in [task["entry_cell"], *targets]:
        require(cell in graph["cells"], "observed population cell is absent")
        source_roots.update(graph["cells"][cell]["roots"])
    source_roots.update(graph["edge_policy"]["ancestry_roots"])
    import json

    for target in targets:
        require(
            executor.topology.graph_snapshot() == (graph, frontier),
            "source panel changed mid-observation",
        )
        capability = executor._capability(target, task["entity"], "color")
        require(capability is not None, "source utility lacks target-key metadata")
        source_roots.update(capability["source_roots"])
        trace = []
        prompt = (
            capability["question"]
            + " Previous cell output: "
            + json.dumps(first["text"], ensure_ascii=False)
        )
        row = executor._step(target, capability, prompt, trace)
        retain(output / (target + ".json"), trace)
        observed[target] = dict(
            status=trace[-1]["status"],
            raw_text=row["text"] if row else None,
            receipt_sha256=digest(trace),
            actual_callbacks=sum(t["actual_callbacks"] for t in trace),
        )
    require(
        executor.topology.graph_snapshot() == (graph, frontier),
        "source panel final authority changed",
    )
    record = dict(
        case_id=task["task_id"],
        phase="source",
        state=state,
        target_value=source_value,
        candidate_outputs=observed,
        source_roots=sorted(source_roots),
    )
    retain(output / "observation.json", record)
    return record
