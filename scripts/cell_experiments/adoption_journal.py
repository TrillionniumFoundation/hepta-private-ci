"""Retain one experiment operation without recreating lost execution history.

These local consistency checks are not native owner authentication or an external
freshness anchor. Incomplete admission requires reconciliation, never a retry.
"""

import json
import os
import sqlite3


def open_selection(root, operation, binding, selected, decision, api):
    """Create once, or open the original complete store without schema repair."""
    database, marker = root / "selection.sqlite", root / "ADMISSION.json"
    expected = dict(
        schema="hepta.e6.admission.v1",
        operation_id=operation,
        evidence_binding=binding,
        selected_model_digest=selected,
        model_decision=decision,
    )
    fresh = False
    if marker.exists():
        api.require(
            api.read_json(marker) == expected, "output belongs to another admission"
        )
        api.require(
            database.is_file(), "admitted selection store is missing", "INCOMPLETE"
        )
    elif not database.exists():
        api.require(
            not any(root.iterdir()),
            "nonempty output has no original selection store",
            "INCOMPLETE",
        )
        try:
            with marker.open("xb") as stream:
                stream.write(api.canonical(expected) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as error:
            raise api.EvidenceError(
                "INCOMPLETE", "another admission owns this output"
            ) from error
        if os.name != "nt":
            descriptor = os.open(root, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        # A crash after the marker is durable leaves an explicit incomplete
        # admission. It cannot be mistaken for an unused experiment directory.
        with database.open("xb"):
            pass
        fresh = True
    api.require(
        not database.is_symlink() and database.is_file(),
        "selection store must be an original regular file",
    )
    db = sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, isolation_level=None)
    try:
        if fresh:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute(
                "CREATE TABLE selections(operation TEXT PRIMARY KEY,binding TEXT,selected TEXT,decision TEXT,report TEXT)"
            )
        else:
            tables = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            columns = db.execute("PRAGMA table_info(selections)").fetchall()
            api.require(
                tables == [("selections",)]
                and columns
                == [
                    (0, "operation", "TEXT", 0, None, 1),
                    (1, "binding", "TEXT", 0, None, 0),
                    (2, "selected", "TEXT", 0, None, 0),
                    (3, "decision", "TEXT", 0, None, 0),
                    (4, "report", "TEXT", 0, None, 0),
                ],
                "original selection schema is missing or changed",
            )
            rows = db.execute(
                "SELECT operation,binding,selected,decision FROM selections"
            ).fetchall()
            api.require(
                rows == [(operation, binding, selected, decision)],
                "original selection is missing or bound to another operation",
            )
            retained = root / "REQUEST.json"
            api.require(
                retained.is_file(),
                "original request is missing; reconcile without dispatch",
                "INCOMPLETE",
            )
            api.require(
                api.digest(api.read_json(retained)) == binding,
                "original request binding changed",
            )
        return db
    except BaseException:
        db.close()
        raise


def completed_report(root, prior, binding, selected, decision, plan_digest, api):
    """Check the retained selection, C and cold originals before readback."""
    old = json.loads(prior) if prior else None
    if not old or old.get("status") not in ("ADOPTED", "NO_UPDATE"):
        return None
    api.require(
        old.get("model_decision") == decision
        and old.get("status") == decision
        and old.get("selected_model_digest") == selected
        and old.get("evidence_binding") == binding
        and old.get("plan_digest") == plan_digest,
        "retained terminal identity changed",
    )
    request = api.read_json(root / "REQUEST.json")
    expected_decision = {
        k: v
        for k, v in old.items()
        if k
        not in (
            "cold",
            "cold_wall_seconds",
            "cold_process_digest",
            "cold_scope",
            "wall_seconds",
            "D",
            "fresh_D_status",
            "execution_costs",
            "inference_attempts",
        )
    }
    expected_decision.update(status="INCOMPLETE", C=[])
    expected_cold = dict(
        manifest=request["candidate"] if decision == "ADOPTED" else request["parent"],
        artifact_root=str(api.Path(request["artifact_root"]).resolve()),
        database=str(root / "selection.sqlite"),
        operation_id=request["plan"]["operation_id"],
        binding=binding,
        record=request["c_tasks"][-1]["record"],
    )
    if "d_tasks" in request:
        expected_cold.update(
            d_tasks=request["d_tasks"],
            replay_expected=api.comparable(old["C"][-1]["prediction"]),
        )
    for name, value in (
        ("RESULT.json", old),
        ("C_RECEIPTS.json", old.get("C")),
        ("DECISION.json", expected_decision),
        ("COLD_REQUEST.json", expected_cold),
    ):
        path = root / name
        api.require(
            path.is_file(),
            "retained completion material is missing: " + name,
            "INCOMPLETE",
        )
        api.require(
            api.read_json(path) == value,
            "retained completion material changed: " + name,
        )
    path = root / "COLD_PROCESS.json"
    api.require(path.is_file(), "retained cold process is missing", "INCOMPLETE")
    process = api.read_json(path)
    if "cold_process_digest" in old:
        api.require(
            api.digest(process) == old["cold_process_digest"],
            "retained cold process bytes changed",
        )
    api.require(
        process.get("returncode") == 0
        and json.loads(process["stdout"]) == old.get("cold")
        and process.get("seconds") == old.get("cold_wall_seconds"),
        "retained cold process changed",
    )
    if "d_tasks" in request:
        from .adoption_future import measured_costs

        materials = {
            "D_RECEIPTS.json": old.get("D"),
            "COLD_ADMISSION.json": dict(
                schema="hepta.e6.cold-admission.v1",
                binding=binding,
                spec_digest=api.digest(expected_cold),
            ),
        }
        for name, value in materials.items():
            path = root / name
            api.require(
                path.is_file(), "retained D material is missing: " + name, "INCOMPLETE"
            )
            api.require(
                api.read_json(path) == value, "retained D material changed: " + name
            )
        api.require(
            old.get("D") == old["cold"].get("D")
            and old.get("execution_costs") == measured_costs(old),
            "retained D or cost accounting changed",
        )
    if "inference_attempts" in old:
        from .adoption_costs import collect, measured_costs

        api.require(
            collect(root, api) == old["inference_attempts"]
            and old.get("execution_costs") == measured_costs(old["inference_attempts"]),
            "retained inference costs changed or are missing",
            "INCOMPLETE",
        )
    return old
