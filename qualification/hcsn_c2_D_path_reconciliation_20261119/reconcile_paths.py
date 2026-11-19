"""Resolve three missing aliases before their first forward, with no budget reset."""

import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time
import zipfile

from audit_io import require, save, sha
from replay import HERE, frozen


def main():
    started = time.monotonic()
    request = frozen()
    old = Path(request["predecessor_root"])
    output = HERE / "RUN_OUTPUT"
    output.mkdir()
    for relative, expected in request["predecessor_outputs"].items():
        require(sha(old / relative) == expected["sha256"], "predecessor output changed: " + relative)
    terminal = json.loads((HERE / "PREDECESSOR_NATIVE_TERMINAL.json").read_bytes())
    require(terminal["job_id"] == request["predecessor_native_job_id"] and
            terminal["terminal_publication_confirmed"] is True and terminal["state"] in ("failed", "succeeded"), "predecessor native terminal")
    previous = json.loads((old / "RUN_OUTPUT/SUMMARY.json").read_bytes())
    previous_request = json.loads((HERE / "PREDECESSOR_REQUEST.json").read_bytes())
    prior_fits = {r["name"]: r for r in previous_request["fits"]}
    costs = {r["name"]: r for r in previous["costs"]}
    require(previous["denominator"] == 6 and len(request["fits"]) == 3, "fixed predecessor and reconciliation rosters")
    for fit in request["fits"]:
        name = fit["name"]
        report = json.loads((old / "RUN_OUTPUT" / name / "RESULT.json").read_bytes())
        before = prior_fits[name]
        require(report["status"] == "FAILED_OR_UNFINISHED" and costs[name]["returncode"] == 2,
                "only pre-forward failed targets may be reconciled")
        require("bound input identity: " + before["initial"]["path"] in report.get("error", ""), "specific missing initial alias")
        require(not any((old / "RUN_OUTPUT" / name / n).exists() for n in ("BATCHES.jsonl", "INPUTS_BEFORE.json", "FRESH_D_LOGITS.pt"))
                and "runtime" not in report and "best_epoch" not in report, "any prior model/forward activity blocks repeat")
        require({k: v for k, v in fit.items() if k != "initial"} == {k: v for k, v in before.items() if k != "initial"}, "changed model selection")
        require(fit["initial"]["sha256"] == before["initial"]["sha256"] == sha(fit["initial"]["path"]), "same initialization bytes")
    stages = [{"name": "partial-chain", "script": "partial_chain.py", "cap": 360 - costs["partial-chain"]["wall_seconds"]}]
    stages += [{"name": fit["name"], "script": "replay.py", "cap": 210 - costs[fit["name"]]["wall_seconds"]} for fit in request["fits"]]
    actual = []
    for stage in stages:
        grant = min(stage["cap"], request["global_deadline_unix"] - time.time() - 60)
        item = {"name": stage["name"], "remaining_original_stage_grant": grant}
        actual.append(item)
        if grant <= 0:
            item["status"] = "UNRUN_REMAINING_ORIGINAL_BUDGET_EXHAUSTED"
            continue
        argv = [request["runtime"]["python"], "-B", str(HERE / stage["script"])]
        if stage["name"] != "partial-chain":
            argv += ["--fit", stage["name"]]
        begin = time.monotonic()
        with (output / (stage["name"] + ".stdout")).open("xb") as stdout, (output / (stage["name"] + ".stderr")).open("xb") as stderr:
            process = subprocess.Popen(argv, stdout=stdout, stderr=stderr, start_new_session=True)
            timed_out = False
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                if time.monotonic() - begin >= grant:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGKILL)
                    _, status, usage = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                time.sleep(.1)
        item.update(returncode=process.returncode, timed_out=timed_out, wall_seconds=time.monotonic() - begin,
                    cpu_seconds=usage.ru_utime + usage.ru_stime, peak_rss_kib=usage.ru_maxrss,
                    prior_stage_wall_seconds=costs[stage["name"]]["wall_seconds"], scope="exact child wait4 through exit")
        save(output / (stage["name"] + ".COST.json"), item)
    new_passed = sum(r.get("returncode") == 0 and r["name"] != "partial-chain" for r in actual)
    summary = {"schema": "exact-initial-alias-reconciliation-v1", "predecessor_passed": previous["passed"],
               "new_forward_passed": new_passed, "combined_unique_current_best_coverage": previous["passed"] + new_passed,
               "denominator": 6, "costs": actual, "wall_seconds": time.monotonic() - started,
               "global_elapsed_from_original_native_creation": time.time() - (request["global_deadline_unix"] - 1800),
               "E_access": False, "original_controller_terminal": "UNKNOWN", "original_full_training_replays": "0/6",
               "original_full_C2_chain_auditor_completed": False, "scientific_admission": "HOLD"}
    save(output / "SUMMARY.json", summary)
    files = sorted(p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    manifest = {str(p.relative_to(HERE)): {"bytes": p.stat().st_size, "sha256": sha(p)} for p in files}
    with zipfile.ZipFile(HERE / "originals.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            archive.write(p, str(p.relative_to(HERE)))
        archive.writestr("MANIFEST.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    save(HERE / "ARCHIVE.json", {"bytes": (HERE / "originals.zip").stat().st_size, "sha256": sha(HERE / "originals.zip"),
                                "members": len(files) + 1, "global_elapsed_seconds": time.time() - (request["global_deadline_unix"] - 1800)})
    require(time.time() <= request["global_deadline_unix"], "original global envelope exceeded")
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0 if new_passed == 3 else 2


if __name__ == "__main__":
    raise SystemExit(main())
