"""Interpret the original analysis CLI's zero exit without rewriting its receipt."""


def legacy_analysis_exit(closure, waited, wait4_item):
    """Only the fully accounted legacy analysis-child call can use this form."""
    error = closure.get("original_exception")
    if (
        type(error) is not dict
        or error != {"type": "SystemExit", "system_exit_code": 0, "message": "0"}
        or type(error.get("system_exit_code")) is not int
        or closure.get("schema") != "hepta.execution06.owned-children.closure.1"
        or closure.get("pending_signal") is not None
        or closure.get("return_value") is not None
        or waited.get("wait_status") != 0
        or type(waited.get("wait_status")) is not int
    ):
        return False
    attempts, children = closure.get("attempts", []), closure.get("children", [])
    if len(attempts) != 1 or len(children) != 1:
        return False
    attempt, child = attempts[0], children[0]
    controller = closure.get("controller_identity", {})
    identity = waited.get("identity", {})
    argv = attempt.get("argv", [])
    return (
        type(controller.get("pid")) is int
        and controller["pid"] > 0
        and type(waited.get("pid")) is int
        and waited["pid"] > 0
        and child.get("pid") == attempt.get("pid") == identity.get("pid") == waited["pid"]
        and child.get("identity") == identity
        and identity.get("parent_pid") == controller["pid"]
        and child.get("signals") == []
        and child.get("wait4_unavailable") is None
        and child.get("wait4_receipt") == wait4_item
        and attempt.get("returned_child") is True
        and attempt.get("construction_entered") is True
        and attempt.get("construction_wait4_unavailable") is False
        and argv[:7]
        == [
            attempt.get("executable"),
            "-B",
            "-m",
            "experiments.parameter_field_fullstudy_20261029.analysis_launch_v2",
            "--child",
            "--parent-pid",
            str(controller["pid"]),
        ]
    )
