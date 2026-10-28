"""Query-level routing, provenance and numeric scoring kept outside inference."""

from dataclasses import asdict
import math
import re

from .learned_graph import typed_permutation
from .numeric_graph import EXACT_PLANS, INTENTS, SPECS, make_query, target_for
from .semantic_router import REJECT


TOLERANCES = {"co2": 25, "temperature": 10, "sunspots": 100, "unemployment": 10}


def literal_route(utterance):
    """Fixed lexical comparator; never called by the learned router."""
    text = utterance.lower()
    if any(
        word in text
        for word in (
            "predict",
            "forecast",
            "why",
            "cause",
            "median",
            "deviation",
            "ratio",
            "delete",
            "rewrite",
            "percentage",
            "entire year",
        )
    ):
        return None
    patterns = (
        (
            "range3",
            r"\brange\b|\bspread\b|maximum minus minimum|largest minus smallest",
        ),
        ("mean3", r"\baverage\b|\bmean\b"),
        ("peak3", r"\bhighest\b|\bmaximum\b|\bpeak\b|\blargest\b|\bgreatest\b"),
        ("change", r"\bchange\b|\bdifference\b|\bsubtract\b|increase or decrease"),
        (
            "previous",
            r"\bprevious\b|\bpreceding\b|month before|month earlier|immediately preceding",
        ),
        (
            "at",
            r"\bwhat was\b|\bread\b|\brecorded\b|\blook up\b|\bobservation\b|\breading\b",
        ),
    )
    return next((name for name, pattern in patterns if re.search(pattern, text)), None)


def route_summary(rows, routes):
    known = [i for i, row in enumerate(rows) if row["intent"] != REJECT]
    unsupported = [i for i, row in enumerate(rows) if row["intent"] == REJECT]
    correct = sum(routes[i] == rows[i]["intent"] for i in known)
    accepted = sum(routes[i] is not None for i in known)
    false_accept = sum(routes[i] is not None for i in unsupported)
    return {
        "queries": len(rows),
        "known_queries": len(known),
        "unsupported_queries": len(unsupported),
        "known_correct_accepted_rate": correct / len(known) if known else None,
        "known_coverage": accepted / len(known) if known else None,
        "accepted_known_accuracy": correct / accepted if accepted else None,
        "unsupported_false_accept_rate": false_accept / len(unsupported)
        if unsupported
        else None,
        "decision_accuracy": (correct + len(unsupported) - false_accept) / len(rows),
        "per_intent": {
            intent: {
                "queries": sum(row["intent"] == intent for row in rows),
                "correct": sum(
                    route == intent if intent != REJECT else route is None
                    for row, route in zip(rows, routes, strict=True)
                    if row["intent"] == intent
                ),
            }
            for intent in (*INTENTS, REJECT)
        },
    }


def evaluate_arm(
    rows,
    source,
    executor,
    graph,
    routes,
    *,
    arm,
    seed,
    planner=False,
    maximum_hops=None,
    mode="connected",
    shuffled=False,
):
    permutation = typed_permutation(SPECS, seed) if shuffled else None
    records = []
    for row, route in zip(rows, routes, strict=True):
        initial, query = make_query(row)
        path = (
            EXACT_PLANS.get(route)
            if planner
            else graph.select(route, "address", maximum_hops=maximum_hops)
        )
        if path is None:
            actual, execution = (
                None,
                {
                    "trace": [],
                    "calls": 0,
                    "seconds": 0.0,
                    "disposition": "router_abstained",
                },
            )
        else:
            actual, execution = executor.run(
                path,
                initial,
                query,
                expected_generation=executor.generation,
                mode=mode,
                permutation=permutation,
            )
        supported = row["intent"] != REJECT
        target = (
            target_for(source, row["intent"], tuple(row["address"]))
            if supported
            else None
        )
        numeric = actual is not None and actual.kind == "number"
        error = (
            abs(float(actual.value) - float(target.value))
            if numeric and supported
            else None
        )
        provenance = supported and numeric and actual.support == target.support
        exact = bool(provenance and error <= 1e-9)
        correct_abstain = not supported and actual is None
        records.append(
            {
                "arm": arm,
                "query_id": row["id"],
                "domain": row["domain"],
                "intent": row["intent"],
                "partition": row["partition"],
                "utterance": row["utterance"],
                "address": row["address"],
                "template_index": row["template_index"],
                "route": route,
                "selected_path": None if path is None else list(path),
                "actual": None if actual is None else asdict(actual),
                "target": None if target is None else asdict(target),
                "execution": execution,
                "numeric_answer": numeric,
                "provenance_correct": bool(provenance),
                "absolute_error_scaled": error,
                "absolute_error_physical": None
                if error is None
                else error / source["scale"],
                "exact_answer": exact,
                "within_declared_tolerance": bool(
                    provenance and error <= TOLERANCES[source["domain"]]
                ),
                "correct_unsupported_abstention": correct_abstain,
                "decision_exact": exact if supported else correct_abstain,
            }
        )
    return records, summarize_arm(records, source, permutation=permutation)


def summarize_arm(records, source, *, permutation=None):
    known = [row for row in records if row["intent"] != REJECT]
    unsupported = [row for row in records if row["intent"] == REJECT]
    answered = [row for row in known if row["numeric_answer"]]
    correct_support = [row for row in known if row["provenance_correct"]]
    composed = [row for row in known if row["intent"] != "at"]
    errors = [row["absolute_error_physical"] for row in answered]
    support_errors = [row["absolute_error_physical"] for row in correct_support]

    def average(values):
        return sum(values) / len(values) if values else None

    groups = {}
    for row in known:
        groups.setdefault((tuple(row["address"]), row["template_index"]), {})[
            row["intent"]
        ] = row["exact_answer"]
    flows = [group for group in groups.values() if set(group) == set(INTENTS)]
    return {
        "queries": len(records),
        "known_queries": len(known),
        "unsupported_queries": len(unsupported),
        "exact_answer_rate": average([row["exact_answer"] for row in known]),
        "decision_exact_rate": average([row["decision_exact"] for row in records]),
        "numeric_coverage": len(answered) / len(known) if known else None,
        "correct_provenance_rate": len(correct_support) / len(known) if known else None,
        "composed_exact_answer_rate": average(
            [row["exact_answer"] for row in composed]
        ),
        "within_declared_tolerance_rate": average(
            [row["within_declared_tolerance"] for row in known]
        ),
        "declared_tolerance_scaled": TOLERANCES[source["domain"]],
        "tolerance_is_not_losslessness": True,
        "answered_mae_physical": average(errors),
        "answered_rmse_physical": math.sqrt(average([x * x for x in errors]))
        if errors
        else None,
        "correct_provenance_mae_physical": average(support_errors),
        "correct_provenance_rmse_physical": math.sqrt(
            average([x * x for x in support_errors])
        )
        if support_errors
        else None,
        "unsupported_numeric_false_accept_rate": average(
            [row["numeric_answer"] for row in unsupported]
        ),
        "unsupported_nonabstention_rate": average(
            [row["actual"] is not None for row in unsupported]
        ),
        "six_predicate_flow_count": len(flows),
        "six_predicate_flow_exact_rate": average(
            [all(group.values()) for group in flows]
        ),
        "all_calls": sum(row["execution"]["calls"] for row in records),
        "semantic_numeric_reader_calls": sum(
            hop["cell_type"] == "semantic"
            for row in records
            for hop in row["execution"]["trace"]
        ),
        "all_execution_seconds": sum(row["execution"]["seconds"] for row in records),
        "per_intent": {
            intent: {
                "queries": sum(row["intent"] == intent for row in known),
                "exact_answer_rate": average(
                    [row["exact_answer"] for row in known if row["intent"] == intent]
                ),
                "correct_provenance_rate": average(
                    [
                        row["provenance_correct"]
                        for row in known
                        if row["intent"] == intent
                    ]
                ),
            }
            for intent in INTENTS
        },
        "permutation": permutation,
        "permuted_operation_count": None
        if permutation is None
        else sum(k != v for k, v in permutation.items()),
    }
