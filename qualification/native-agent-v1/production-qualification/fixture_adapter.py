"""Reuse the existing resident three-lane runner without expanding its claimed scope."""

import json
import math
from pathlib import Path
import subprocess
import sys

from contracts import BUDGET, CONTROLS, digest, preflight

ADAPTER = "fixture_v2"
OWNER_SCOPE = "qualification_fixture"


def run_lane(plan, lane, directory):
    errors = preflight(plan)
    if errors:
        return {"lane": lane, "status": "held", "reasons": errors}, {}
    root = Path(plan["source_root"])
    raw = directory / (lane + "-raw")
    argv = [sys.executable, str(root / "benchmark_v2.py"), "--lane", lane,
        "--mode", plan["mode"], "--output", str(raw), "--fixture", plan["fixture"]["directory"],
        "--upstream", plan["upstream"], "--repeats", str(plan["repeats"]),
        "--timeout", str(plan["timeout_seconds"]), "--tasks", *CONTROLS.values()]
    for name in ("native", "codex", "facade"):
        argv += ["--" + name, plan["binaries"][name]["path"]]
    if plan["warmup"]:
        argv.append("--warmup")
    # The runner owns cancellation and cleanup. No outer timeout may kill it and
    # silently abandon runtime jobs; a failed lane is never retried here.
    with (directory / (lane + "-adapter.log")).open("xb") as log:
        result = subprocess.run(argv, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=False)
    record = {"lane": lane, "adapter": ADAPTER, "owner_scope": OWNER_SCOPE,
              "status": "finished", "exit_code": result.returncode, "argv": argv}
    report_path = raw / "REPORT.json"
    if not report_path.is_file():
        record.update(status="failed", reasons=["no completed REPORT.json; inspect retained adapter log and partial report"])
        return record, {}
    record.update(report=str(report_path.relative_to(directory)), report_sha256=digest(report_path))
    report = json.loads(report_path.read_text())
    errors = preflight(plan)
    if report.get("lane") != lane or report.get("mode") != plan["mode"]:
        errors.append("runner report lane/mode mismatch")
    if report.get("model") != plan["model"]["id"] or report.get("budgets") != BUDGET:
        errors.append("runner actual model/ceilings mismatch")
    if report.get("source_fingerprints") != plan["source_hashes"]:
        errors.append("runner source fingerprints mismatch")
    executor = "codex" if lane == "app-server" else lane
    if report.get("executor_sha256") != plan["binaries"][executor]["sha256"]:
        errors.append("runner executor fingerprint mismatch")
    if report.get("runtime_helper_sha256") != plan["binaries"]["native"]["sha256"]:
        errors.append("runner native helper fingerprint mismatch")
    expected = {f"{i:02}-{task}" for i in range(plan["repeats"]) for task in CONTROLS.values()}
    actual = {}
    for row in report.get("rows", []):
        if row.get("warmup") is True and row.get("name") == "warmup" and plan["warmup"]:
            continue
        name = row.get("name")
        if name not in expected or name in actual:
            errors.append("unexpected/duplicate raw row")
        else:
            actual[name] = row
            elapsed = row.get("wall_ms")
            valid = type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0
            row["adapter_wall_ms"] = elapsed if valid else None
            if not valid:
                errors.append("invalid/missing elapsed time in raw row: " + name)
    record["integrity_errors"] = errors
    record["actual_configuration_files"] = {str(path.relative_to(directory)): digest(path)
        for path in (raw / "runner.json", raw / "runtime.json", raw / "codex-home" / "config.toml") if path.is_file()}
    record["metrics"] = report.get("metrics")
    record["measurement_windows"] = report.get("measurement_windows")
    record["model_inventory"] = report.get("model_inventory")
    record["resources_are_lane_totals_not_case_totals"] = True
    record["model_tokens_are_synthetic"] = plan["mode"] == "replay"
    record["scope"] = "resident executor + fixture helper + observer + selected runtime jobs; remote inference excluded"
    record["claim_limits"] = report.get("limits", [])
    if errors or result.returncode != 0:
        record["status"] = "failed"
    for row in actual.values():
        row["adapter_passed"] = (not errors and row.get("correct") is True
            and row.get("tool_feedback_audit", {}).get("valid") is True
            and report.get("model_capture_complete") is True
            and report.get("only_shared_tool_inventory") is True)
    return record, actual
