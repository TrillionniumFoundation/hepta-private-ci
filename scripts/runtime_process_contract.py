"""Exact request and durable terminal witness contract for runtime d3d75c3."""

import re
from runtime_stdio import canonical, digest, require


def process_digest(params):
    # Runtime d3d75c30719db966b004756f610007a7c723729e RequestBinding field set.
    fields = (
        "args",
        "cpu_quota_percent",
        "cwd",
        "env",
        "executable",
        "host",
        "memory_max_bytes",
        "nice",
        "stdin",
        "timeout_seconds",
    )
    normalized = {key: params.get(key) for key in fields}
    normalized["args"] = params.get("args", [])
    normalized["env"] = params.get("env", {})
    return digest(canonical(normalized))


def terminal_proof(status, job_id):
    require(status.get("job_id") == job_id, "status identifies a different job")
    state = status.get("state")
    if (
        state not in {"succeeded", "failed", "cancelled", "timed_out"}
        or status.get("status_authoritative") is False
        or status.get("effect_outcome") == "unknown"
        or status.get("outcome") == "unknown"
    ):
        return None
    require(
        type(status.get("terminal_publication_protocol")) is int
        and status["terminal_publication_protocol"] == 1
        and all(
            status.get(k) is True
            for k in (
                "terminal_publication_confirmed",
                "output_complete",
                "output_durable",
            )
        ),
        "terminal output lacks a complete durable publication witness",
    )
    require(
        isinstance(status.get("launch_nonce"), str)
        and re.fullmatch("[0-9a-fA-F]{32}", status["launch_nonce"]),
        "invalid original launch nonce",
    )
    require(type(status.get("exit_code")) is int, "exit code is not an integer")
    require(
        type(status.get("timed_out")) is bool and type(status.get("cancelled")) is bool,
        "terminal outcome flags missing",
    )
    expected = (
        "timed_out"
        if status["timed_out"]
        else "cancelled"
        if status["cancelled"]
        else "succeeded"
        if status["exit_code"] == 0
        else "failed"
    )
    require(state == expected, "terminal state disagrees with original outcome")
    counts = {}
    for name in ("stdout", "stderr"):
        count = status.get("log_bytes", {}).get(name, {}).get("stored")
        require(
            type(count) is int
            and count >= 0
            and status["log_bytes"][name].get("seen") == count
            and status.get("log_truncated", {}).get(name) is False
            and name in status.get("log_errors", {})
            and status["log_errors"][name] is None
            and status.get("log_synced", {}).get(name) is True,
            "terminal stream is incomplete, truncated or unsynced",
        )
        counts[name] = count
    require(
        type(status.get("at_unix_ms")) is int and status["at_unix_ms"] >= 0,
        "terminal publication time missing",
    )
    return {
        "state": state,
        "exit_code": status["exit_code"],
        "launch_nonce": status["launch_nonce"],
        "at_unix_ms": status["at_unix_ms"],
        "counts": counts,
    }
