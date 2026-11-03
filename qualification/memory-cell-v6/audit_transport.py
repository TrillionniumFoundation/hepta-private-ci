"""Independent arithmetic checks for recorded transport and amortized routing."""

import math

COUNTS = (
    "rpc_attempts",
    "read_attempts",
    "validation_attempts",
    "attempted_request_bytes",
    "received_response_bytes",
    "node_count",
)


def check_row(row, prefix, check):
    transport, accepted_transport = row.get("transport"), None
    if transport is not None:
        valid = isinstance(transport, dict) and all(
            type(transport.get(name)) is int and transport[name] >= 0 for name in COUNTS
        )
        check(valid, prefix + "invalid transport counters")
        if valid:
            accepted_transport = transport
            check(
                transport["rpc_attempts"]
                == transport["read_attempts"] + transport["validation_attempts"],
                prefix + "RPC attempt conservation fails",
            )
            check(
                row["rpc_bytes"]
                == transport.get("rpc_bytes")
                == transport["attempted_request_bytes"]
                + transport["received_response_bytes"],
                prefix + "RPC byte conservation fails",
            )
            check(
                row["hops"] == transport["read_attempts"],
                prefix + "read hop accounting differs",
            )
            check(
                transport["validation_attempts"]
                <= transport["node_count"]
                <= transport["read_attempts"],
                prefix + "node/validation accounting differs",
            )
            if row["accepted"]:
                check(
                    transport["node_count"] > 0
                    and transport["validation_attempts"] == transport["node_count"],
                    prefix + "accepted without final participant validation",
                )
    if "routing_batch_amortized_seconds" in row:
        route, total = (
            row["routing_batch_amortized_seconds"],
            row.get("read_plus_amortized_routing_seconds"),
        )
        valid_cost = all(
            type(v) in (int, float) and math.isfinite(v) and v >= 0
            for v in (route, total, row["latency_seconds"])
        )
        check(valid_cost, prefix + "invalid routing cost")
        if valid_cost:
            check(
                math.isclose(
                    total, row["latency_seconds"] + route, rel_tol=1e-12, abs_tol=1e-12
                ),
                prefix + "routing cost conservation fails",
            )
    return accepted_transport
