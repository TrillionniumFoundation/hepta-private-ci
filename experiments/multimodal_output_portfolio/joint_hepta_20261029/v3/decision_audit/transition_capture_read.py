"""Read a complete development capture; no score or training is produced."""

import hashlib
import json
import math
from pathlib import Path

from .transition_capture import canonical, file_identity


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verified_json(path, identity):
    require(file_identity(path) == identity, f"Retained bytes changed: {path.name}")
    return json.loads(path.read_bytes())


def finite_costs(item):
    for key in ("cpu_seconds", "wall_seconds"):
        require(type(item[key]) in (int, float) and math.isfinite(item[key]) and item[key] >= 0,
                "Invalid or unknown numeric cost was presented as measured")


def read_capture(output):
    """Validate source bindings, events, transitions, real files and close.

    These are integrity checks on observations, not authenticated independent
    data custody or proof that a generated explanation/diagram is useful.
    """
    out = Path(output)
    root = out / "transition_capture"
    write_cost = json.loads((root / "summary_write_cost.json").read_bytes())
    finite_costs(write_cost)
    summary = verified_json(root / "SUMMARY.json", write_cost["summary"])
    require(summary["schema"] == "hepta.development-transition-summary.v1"
            and summary["status"] == "COMPLETE" and summary["fault"] is None,
            "Capture did not complete; retain this failed or unknown work")
    raw = (root / "transitions.jsonl").read_bytes()
    require(raw.endswith(b"\n"), "Partial final journal line")
    rows = [json.loads(line) for line in raw.splitlines()]
    previous = "0" * 64
    for sequence, row in enumerate(rows):
        require(set(row) == {"sequence", "phase", "previous_sha256", "payload", "sha256"},
                "Unexpected journal schema")
        require(row["sequence"] == sequence and row["previous_sha256"] == previous,
                "Missing, duplicate or reordered journal record")
        unsigned = {key: value for key, value in row.items() if key != "sha256"}
        require(hashlib.sha256(canonical(unsigned)).hexdigest() == row["sha256"],
                "Journal bytes do not match their chain")
        previous = row["sha256"]
    require(len(rows) == summary["records"] and previous == summary["chain_head"],
            "Summary does not bind the full journal")
    require(len(rows) >= 3 and rows[0]["phase"] == "start" and rows[-1]["phase"] == "finish",
            "Missing original start or final capture terminal")
    start = rows[0]["payload"]
    require(start["schema"] == "hepta.development-transition-capture.v1", "Unknown capture schema")
    source, request, settings = start["declared_source"], start["request"], start["settings"]
    admission = settings.get("observer_admission")
    require(admission in (None, "fresh-after-capture-v1"), "Unknown observer admission contract")
    require(source["split"] in ("train", "development"), "Test source cannot be exported as train")
    require((source["source_id"], source["image_sha256"], source["instruction_sha256"]) ==
            (request["source_id"], request["image_sha256"],
             hashlib.sha256(request["instruction"].encode("utf-8")).hexdigest()),
            "Public request differs from its declared source")
    result = summary["result"]
    require(rows[-1]["payload"] == result, "Finish record and summary differ")
    require(result["source_files_after"] == {"runtime": start["runtime_source"],
            "recorder": start["recorder_source"]}, "Observed source identity changed")
    report = verified_json(out / "report.json", result["report"])
    verified_json(out / "report_write_cost.json", result["report_write_cost"])
    if result["request_file"] is not None:
        require(verified_json(out / "request.json", result["request_file"]) == request,
                "Original request file differs from captured request")
    for name, identity in result["backend_files"].items():
        require(name in ("backend.json", "backend_final.json"), "Unexpected backend evidence path")
        verified_json(out / name, identity)
    require(report["seed"] == settings["seed"] and report["horizon"] == settings["horizon"]
            and report["source_id"] == source["source_id"] and report["tariffs"] ==
            {"cpu_second": settings["cpu_tariff"], "wall_second": settings["wall_tariff"]},
            "Original run parameters changed")
    events, current, expected_step, transitions, ended = [], None, 0, [], None
    for row in rows[1:-1]:
        phase, payload = row["phase"], row["payload"]
        require(ended is None, "Observation follows episode_end")
        new_events = payload["new_original_events"]
        require([event["event_id"] for event in new_events] ==
                list(range(len(events), len(events) + len(new_events))), "Original event gap or duplicate")
        for event in new_events:
            finite_costs(event)
        events.extend(new_events)
        detail, state = payload["detail"], payload["state"]
        if phase == "before_controller":
            require(detail["step"] == expected_step and
                    (current is None or current["phase"] == "after_action"), "Decision order changed")
            require(current is None or current.get("choice") != "stop", "Decision after STOP")
            require(set(detail["view"]) == {"instruction", "plan", "plan_version", "text", "image_path",
                    "critique", "history", "remaining_decisions", "remaining_seconds"},
                    "Controller view includes hidden or missing inputs")
            current = {"step": expected_step, "phase": phase, "before_view": detail["view"]}
            transitions.append(current)
            expected_step += 1
        elif phase == "choice":
            require(current is not None and current["phase"] == "before_controller"
                    and detail["step"] == current["step"], "Choice has no matching public view")
            require(events[-1]["action"] == "controller" and events[-1]["status"] == "ok"
                    and events[-1]["detail"] == {"choice": detail["chosen"]}, "Choice differs from original event")
            if admission is not None:
                actual_view = detail.get("controller_view")
                observed_view = current["before_view"]
                require(isinstance(actual_view, dict) and set(actual_view) == set(observed_view),
                        "Actual controller view is missing or has hidden inputs")
                require(all(actual_view[key] == observed_view[key] for key in observed_view
                            if key != "remaining_seconds"), "Controller inputs changed during capture")
                remaining = actual_view["remaining_seconds"]
                require(type(remaining) in (int, float) and math.isfinite(remaining)
                        and 0 < remaining <= observed_view["remaining_seconds"],
                        "Controller was admitted with an expired or extended budget")
                current["before_capture_view"] = observed_view
                current["before_view"] = actual_view
            else:
                require("controller_view" not in detail, "Unversioned controller-view change")
            current.update(phase=phase, choice=detail["chosen"])
        elif phase in ("before_action", "after_action"):
            expected_phase = "choice" if phase == "before_action" else "before_action"
            require(current is not None and current["phase"] == expected_phase
                    and detail["step"] == current["step"] and state["action"] == current["choice"],
                    "Action observation has no corresponding actual decision")
            if phase == "after_action":
                require(events[-1]["action"] == current["choice"] and events[-1]["status"] == "ok",
                        "After-state has no original synchronized action return")
                current["actual_after_state"] = state
            current["phase"] = phase
        elif phase == "failure":
            require(state["episode_status_so_far"] in ("failed", "cancelled", "timeout")
                    and state["episode_error_so_far"] is not None and payload["selected"] == [],
                    "Failure was not preserved")
            if current is not None:
                current["failure_state"] = state
        elif phase == "episode_end":
            ended = payload
        else:
            raise ValueError("Unexpected or repeated capture phase")
    require(ended is not None and events == report["events"], "Missing original event costs or episode end")
    require(ended["state"]["episode_status_so_far"] == report["status"]
            and ended["state"]["episode_error_so_far"] == report["error"]
            and ended["selected"] == report["selected"] and ended["artifacts"] == report["artifacts"]
            and ended["state"]["history"] == report["history"], "Actual final state differs from original report")
    require(result["episode_status"] == report["status"] and result["episode_error"] == report["error"],
            "Episode failure/terminal was rewritten")
    require(result["original_cost"] == {key: report[key] for key in result["original_cost"]},
            "Original cost ledger changed")
    for key in ("cpu_seconds", "wall_seconds", "tariff_amount"):
        require(report[key] == math.fsum(event[key] for event in events), "Original event total mismatch")
    retained = []
    for path in sorted(out.iterdir()):
        if path.is_file() and path.suffix in (".png", ".txt"):
            retained.append({"path": path.name, **file_identity(path)})
    require(retained == result["retained_files"] == report["retained_files"],
            "Unselected, partial or selected artifact was deleted/changed")
    require(result["selected"] == report["selected"], "Selected work changed")
    selected = {(item["path"], item["sha256"]) for item in report["selected"]}
    require(result["unselected_retained_files"] == [item for item in retained if
            (item["path"], item["sha256"]) not in selected], "Unselected work was omitted")
    for item in summary["observation_costs"]:
        finite_costs(item)
        require(item["placement"] in ("inside_episode", "after_original_event_clock", "after_original_report"),
                "Observer cost placement is unknown")
    finite_costs(summary["run_envelope_through_capture_finalize"])
    return {"report": report, "summary": summary, "transitions": transitions, "journal": rows,
            "semantic_acceptance": "pending_independent_evaluation", "training_performed": False,
            "roster_custody_authenticated": False, "production_qualified": False}
