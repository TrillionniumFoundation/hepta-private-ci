"""Offline all-history content/count checks, never inputs to the controller."""


def continuation_statistics(graph, evaluated):
    result = {}
    for history in sorted(graph.nodes, key=len, reverse=True):
        node = graph.nodes[history]
        action = evaluated["choices"][history]
        if action == "STOP":
            result[history] = dict(reads=0., skips=0., correctness=node["q"]["STOP"])
        else:
            result[history] = {key: sum(p*result[child][key] for p, child, _ in node["edges"][action])
                               for key in ("reads", "skips", "correctness")}
            result[history]["reads"] += action == "READ"
            result[history]["skips"] += action == "SKIP"
    return result


def all_history_dominance(graph, before, after):
    """Check every graph history, including states unoccupied by either policy."""
    left = continuation_statistics(graph, before)
    right = continuation_statistics(graph, after)
    errors = dict(reads=0., correctness=0., return_saved=0., original_identity=0., guarded_identity=0.)
    minimum = float("inf")
    for history in graph.nodes:
        a, b = left[history], right[history]
        improvement = after["values"][history]-before["values"][history]
        saved = (a["skips"]-b["skips"])*graph.config.skip_cost
        local = dict(reads=abs(a["reads"]-b["reads"]), correctness=abs(a["correctness"]-b["correctness"]),
                     return_saved=abs(improvement-saved))
        for name, values, actual in (("original_identity", a, before["values"][history]),
                                    ("guarded_identity", b, after["values"][history])):
            local[name] = abs(actual-(values["correctness"]-values["reads"]*graph.config.read_cost
                                     -values["skips"]*graph.config.skip_cost))
        errors = {key:max(errors[key], local[key]) for key in errors}
        minimum = min(minimum, improvement)
    if minimum < -2e-10 or max(errors.values()) > 2e-10:
        raise AssertionError((minimum, errors))
    summary = dict(histories_checked=len(graph.nodes), minimum_history_improvement=minimum, errors=errors,
                   saved_task_fee=(left[()]["skips"]-right[()]["skips"])*graph.config.skip_cost)
    return summary, left, right
