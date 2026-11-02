"""Typed counter admission for the three inherited generated memory schemas."""

COUNTER_KEYS_BY_SCHEMA = {
    "hcsn-r15-addressed-state-v1": frozenset(("propagations", "observations", "writes")),
    "hcsn-r16-packed-state-v1": frozenset(("propagations", "observations", "writes")),
    "hcsn-r16-anchored-state-v1": frozenset(("propagations", "observations", "writes")),
}


def validate_counters(payload):
    """Require the exact generated counter map before inherited restoration.

    The source schemas generate only nonnegative Python integer counters, not
    CPU-time floats. Exact int type excludes bool, float and nested JSON values.
    Python integers are finite; no invented upper bound truncates old counts.
    """
    if type(payload) is not dict:
        raise ValueError("Owned memory checkpoint must be a JSON object")
    schema = payload.get("schema")
    expected = COUNTER_KEYS_BY_SCHEMA.get(schema) if type(schema) is str else None
    operations = payload.get("operations")
    if (expected is None or type(operations) is not dict or set(operations) != expected
            or any(type(value) is not int or value < 0 for value in operations.values())):
        raise ValueError("Invalid owned memory operation counter schema")


def restore_owned(memory_type, law, payload, *, expected_projection):
    """Preflight generated metadata; retain inherited checksum/state validation.

    Full memory otherwise passes projection/method through by reference. Admit
    only the caller's declared string mode and the implemented expm method.
    """
    validate_counters(payload)
    if payload["schema"] == "hcsn-r15-addressed-state-v1":
        projection, method = payload.get("projection"), payload.get("method")
        if (type(projection) is not str or projection != expected_projection
                or projection not in ("full", "factorized", "mean")
                or type(method) is not str or method != "expm"):
            raise ValueError("Invalid owned memory propagation metadata")
    elif expected_projection != "block":
        raise ValueError("Packed owned memory requires block projection")
    return memory_type.restore(law, payload)
