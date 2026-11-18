"""Retain inference dispatches, including failures; no full-cost qualification."""

import time


PHASE_FILES = {
    "hot_C": "C_INFERENCE.json",
    "cold_C_replay": "COLD_REPLAY_INFERENCE.json",
    "cold_D": "D_INFERENCE.json",
}


def predict(predictor, record, selected, root, phase, api):
    """Persist intent before dispatch so a lost return remains unmeasured work."""
    path = root / PHASE_FILES[phase]
    rows = api.read_json(path) if path.exists() else []
    row = dict(
        record_digest=api.digest(record),
        selected_model_digest=selected,
        status="DISPATCH_INTENT",
        started_at_ns=time.time_ns(),
    )
    rows.append(row)
    api.save(path, rows)
    started = time.monotonic()
    try:
        result = api.prediction(predictor, record, selected)
    except Exception as error:
        row.update(status="FAILED", error_type=type(error).__name__)
        raise
    else:
        row.update(
            status="COMPLETE",
            measurements={
                k: result[k]
                for k in ("input_tokens", "output_tokens", "elapsed_seconds")
            },
        )
        return result
    finally:
        row.update(
            completed_at_ns=time.time_ns(),
            call_wall_seconds=time.monotonic() - started,
        )
        api.save(path, rows)


def collect(root, api):
    """Missing or unreadable streams remain unknown, including before dispatch."""
    streams = {}
    for phase, filename in PHASE_FILES.items():
        try:
            rows = api.read_json(root / filename)
            api.require(isinstance(rows, list) and rows, "inference stream shape")
            for row in rows:
                api.need(
                    row, "record_digest selected_model_digest status started_at_ns"
                )
                api.require(
                    row["status"] in ("COMPLETE", "FAILED", "DISPATCH_INTENT"),
                    "inference status",
                )
                if row["status"] == "COMPLETE":
                    api.need(row, "measurements")
                    measurement = row["measurements"]
                    api.need(measurement, "input_tokens output_tokens elapsed_seconds")
                    api.require(
                        all(
                            type(measurement[k]) is int and measurement[k] >= 0
                            for k in ("input_tokens", "output_tokens")
                        )
                        and type(measurement["elapsed_seconds"]) in (int, float)
                        and api.math.isfinite(measurement["elapsed_seconds"])
                        and measurement["elapsed_seconds"] >= 0,
                        "inference measurements",
                    )
            streams[phase] = rows
        except (OSError, ValueError, TypeError, KeyError):
            streams[phase] = None
    return streams


def measured_costs(streams):
    phases = {}
    for phase, rows in streams.items():
        complete = [r for r in rows or [] if r["status"] == "COMPLETE"]
        unresolved = None if rows is None else len(rows) - len(complete)
        known = {
            key: sum(r["measurements"][source] for r in complete)
            for key, source in (
                ("input_tokens", "input_tokens"),
                ("output_tokens", "output_tokens"),
                ("reported_prediction_seconds", "elapsed_seconds"),
            )
        }
        measured = rows is not None and unresolved == 0
        phases[phase] = dict(
            measurement_status="COMPLETE_OBSERVED_DISPATCHES"
            if measured
            else "INCOMPLETE",
            dispatch_intents=None if rows is None else len(rows),
            observed_complete_predictions=len(complete),
            unmeasured_dispatch_intents=unresolved,
            model_calls=len(complete) if measured else None,
            **{key: value if measured else None for key, value in known.items()},
            observed_complete_prediction_costs=known,
        )
    return dict(
        scope="inference dispatches only; failed or lost-return costs remain unknown; wall times overlap inference",
        phases=phases,
        training_and_B_costs=None,
        energy_joules=None,
        complete_physical_costs=False,
    )
