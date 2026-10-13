"""Check internal consistency of existing live work observations.

A consistent record is not an authenticated profiler or a complete system cost.
Known executed prefixes survive failed/unknown scopes, but those scopes cannot
support complete phase counts. The original meter schema and units are unchanged.
"""
from __future__ import annotations

from paired_execution import PHASES, _integer

_SCOPE_FIELDS = {"phase", "component", "calls", "formula_flops", "unknown_operators",
                 "failed_calls", "elapsed_ns", "cpu_ns"}


def validate_work_record(record, *, expected_policy=None):
    if (not isinstance(record, dict)
            or record.get("schema") != "hepta.execution-work-observation.v1"
            or not isinstance(record.get("profile"), str) or not record["profile"]
            or not isinstance(record.get("policy"), dict)):
        raise ValueError("complete versioned work observation required")
    if expected_policy is not None and record["policy"] != expected_policy:
        raise ValueError("work policy differs from the frozen configuration")
    stopped = record.get("stopped")
    if stopped is not None and (not isinstance(stopped, str) or not stopped):
        raise ValueError("invalid recorded stop reason")
    for key, expected in (("torch_dispatch_only", True), ("hardware_instruction_count", False),
                          ("observer_evaluation_measured", False), ("production_authorized", False)):
        if record.get(key) is not expected:
            raise ValueError("work observation cannot upgrade its declared scope: " + key)
    for key in ("elapsed_ns", "cpu_ns", "aborted_formula_reservations"):
        _integer(record.get(key), key)
    if record["aborted_formula_reservations"] and stopped is None:
        raise ValueError("aborted operator reservation requires a stopped ledger")
    scopes = record.get("scopes")
    totals, incomplete, seen = dict.fromkeys(PHASES, 0), set(), set()
    if not isinstance(scopes, list) or len(scopes) > 35:
        raise ValueError("bounded work scopes required")
    unknown_count = failed_count = 0
    for scope in scopes:
        if not isinstance(scope, dict) or set(scope) != _SCOPE_FIELDS:
            raise ValueError("complete work scope fields required")
        phase, component = scope["phase"], scope["component"]
        if phase not in (*PHASES, "setup", "verification") or component not in (
                "encoder", "bank", "initialization", "publication", "material"):
            raise ValueError("unknown work scope")
        key = (phase, component)
        if key in seen:
            raise ValueError("duplicate work scope would double count the prefix")
        seen.add(key)
        for name in _SCOPE_FIELDS - {"phase", "component"}:
            _integer(scope[name], "scope " + name, 1 if name == "calls" else 0)
        if scope["failed_calls"] > scope["calls"]:
            raise ValueError("failed scope calls exceed attempted calls")
        unknown_count += scope["unknown_operators"]
        failed_count += scope["failed_calls"]
        if phase in totals:
            totals[phase] += scope["formula_flops"]
            if scope["unknown_operators"] or scope["failed_calls"]:
                incomplete.add(phase)
    operators, unknown = record.get("operators"), record.get("unknown_operators")
    for mapping in (operators, unknown):
        if (not isinstance(mapping, dict) or len(mapping) > 512
                or any(not isinstance(k, str) or not k for k in mapping)):
            raise ValueError("bounded operator inventory required")
        for value in mapping.values():
            _integer(value, "operator attempts", 1)
    if any(name not in operators or count > operators[name] for name, count in unknown.items()):
        raise ValueError("unknown operator inventory contradicts attempted operators")
    # Formula uncertainty and execution uncertainty are separate increments.
    # An unknown kernel that also fails contributes to BOTH; a known failed
    # kernel contributes only to scope uncertainty. At most one kernel failure
    # escapes each failed scope call. Never reject a legitimate failed prefix
    # merely because its uncertainty count exceeds its operator count.
    formula_unknowns = sum(unknown.values())
    if not formula_unknowns <= unknown_count <= formula_unknowns + failed_count:
        raise ValueError("scope and operator uncertainty counts disagree")
    if record["aborted_formula_reservations"] and not failed_count:
        raise ValueError("aborted operator reservation lacks a failed scope")
    phases = record.get("phase_flops")
    if not isinstance(phases, dict) or set(phases) != set(PHASES):
        raise ValueError("all declared work phases must be explicit")
    for phase, value in phases.items():
        if value is None:
            continue  # Omitted coverage never becomes zero from a known prefix.
        _integer(value, "complete phase count")
        if phase in incomplete or not any(p == phase for p, _ in seen):
            raise ValueError("unknown, failed or unobserved phase cannot claim complete work")
        if value != totals[phase]:
            raise ValueError("complete phase count contradicts its executed prefix")
    return totals
