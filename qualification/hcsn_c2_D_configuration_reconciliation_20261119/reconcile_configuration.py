"""Derive two missing configurations from immutable original plans; keep all strict gates."""

import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import time
import zipfile

from audit_io import construction, require, save, sha
from replay import HERE, frozen


def main():
    started = time.monotonic()
    request = frozen()
    old = Path(request["predecessor_root"])
    alias = Path(request["alias_root"])
    output = HERE / "RUN_OUTPUT"
    output.mkdir()
    for base, field in ((old, "predecessor_outputs"), (alias, "alias_outputs")):
        for relative, expected in request[field].items():
            require(sha(base / relative) == expected["sha256"], "prior artifact identity: " + relative)
    terminal = json.loads((HERE / "ALIAS_NATIVE_TERMINAL.json").read_bytes())
    require(terminal["job_id"] == request["alias_native_job_id"] and terminal["terminal_publication_confirmed"]
            and terminal["state"] == "failed", "previous native terminal")
    previous = json.loads((alias / "RUN_OUTPUT/SUMMARY.json").read_bytes())
    initial_summary = json.loads((old / "RUN_OUTPUT/SUMMARY.json").read_bytes())
    previous_request = json.loads((HERE / "ALIAS_REQUEST.json").read_bytes())
    prior_fits = {r["name"]: r for r in previous_request["fits"]}
    costs0 = {r["name"]: r for r in initial_summary["costs"]}
    costs1 = {r["name"]: r for r in previous["costs"]}
    costs = {name: {"wall_seconds": costs0[name]["wall_seconds"] + costs1[name]["wall_seconds"]}
             for name in (r["name"] for r in request["fits"])}
    adapters = {r["name"]: r for r in json.loads((HERE / "CONFIGURATION_ADAPTER.json").read_bytes())}
    snapshot = json.loads((HERE / "ORIGINAL_TERMINAL_SNAPSHOT.json").read_bytes())
    parents = {r["name"]: r for r in snapshot["fits"]}
    require(len(request["fits"]) == len(adapters) == 2 and previous["combined_unique_current_best_coverage"] == 4,
            "exact two remaining first-forward candidates")
    for fit in request["fits"]:
        name, adapter = fit["name"], adapters[fit["name"]]
        record = json.loads((alias / "RUN_OUTPUT" / name / "RESULT.json").read_bytes())
        require(record["status"] == "FAILED_OR_UNFINISHED" and "ValueError: checkpoint semantics" in record.get("error", ""),
                "specific previous missing-configuration guard")
        require(not any((alias / "RUN_OUTPUT" / name / n).exists() for n in ("BATCHES.jsonl", "FRESH_D_LOGITS.pt"))
                and "runtime" not in record and "best_epoch" not in record, "any previous model activity blocks repeat")
        prior = prior_fits[name]
        require(prior["model_configuration"] is None and fit["model_configuration"] is not None,
                "only a missing index field may be repaired")
        require({k: v for k, v in fit.items() if k != "model_configuration"} ==
                {k: v for k, v in prior.items() if k != "model_configuration"}, "changed scientific model identity")
        expected = parents[name]["artifact_identities"]["plan.json"]
        binding = adapter["bound_parent_plan"]
        require(binding["sha256"] == expected["sha256"] and binding["bytes"] == expected["bytes"], "original plan binding")
        require(sha(HERE / binding["copy"]) == sha(binding["path"]) == expected["sha256"], "parent plan original bytes")
        require(sha(HERE / "audit_io.py") == adapter["construction_source_sha256"], "unchanged independent construction")
        plan = json.loads((HERE / binding["copy"]).read_bytes())
        require(plan["seed"] == fit["model_configuration"]["seed"] and plan["learning_rate"] == .001,
                "original parent plan candidate identity")
        require(construction(plan) == adapter["derived_configuration"] == fit["model_configuration"],
                "configuration must be independently derived, never copied from checkpoint")
    diagnostic = json.loads((HERE / "SEMANTICS_DIAGNOSTIC_NATIVE.json").read_bytes())
    metadata_spent = costs0["partial-chain"]["wall_seconds"] + costs1["partial-chain"]["wall_seconds"] + diagnostic["charged_wall_seconds"]
    costs["configuration-proof"] = {"wall_seconds": metadata_spent}
    stages = [{"name": "configuration-proof", "script": "validate_configuration.py", "cap": 360 - metadata_spent}]
    stages += [{"name": fit["name"], "script": "replay.py", "cap": 210 - costs[fit["name"]]["wall_seconds"]}
              for fit in request["fits"]]
    actual = []
    for stage in stages:
        grant = min(stage["cap"], request["global_deadline_unix"] - time.time() - 60)
        item = {"name": stage["name"], "remaining_original_stage_grant": grant}
        actual.append(item)
        if grant <= 0:
            item["status"] = "UNRUN_REMAINING_ORIGINAL_BUDGET_EXHAUSTED"
            continue
        if stage["script"] == "replay.py":
            require((output / "CONFIGURATION_PROOF.json").is_file() and json.loads((output / "CONFIGURATION_PROOF.json").read_bytes())["status"] == "PASSED", "configuration proof must pass before any forward")
        argv = [request["runtime"]["python"], "-B", str(HERE / stage["script"])]
        if stage["script"] == "replay.py":
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
    new_passed = sum(r.get("returncode") == 0 and r["name"] in {f["name"] for f in request["fits"]} for r in actual)
    summary = {"schema": "strict-configuration-index-reconciliation-v1", "predecessor_passed": previous["combined_unique_current_best_coverage"],
               "new_forward_passed": new_passed, "combined_unique_current_best_coverage": previous["combined_unique_current_best_coverage"] + new_passed,
               "denominator": 6, "costs": actual, "wall_seconds": time.monotonic() - started,
               "global_elapsed_from_original_native_creation": time.time() - (request["global_deadline_unix"] - 1800),
               "E_access": False, "original_controller_terminal": "UNKNOWN", "original_full_training_replays": "0/6",
               "original_full_C2_chain_auditor_completed": False, "scientific_admission": "HOLD"}
    save(output / "SUMMARY.json", summary)
    for adapter in adapters.values():
        require(sha(adapter["bound_parent_plan"]["path"]) == adapter["bound_parent_plan"]["sha256"], "parent plan changed during replay")
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
    return 0 if new_passed == 2 else 2


if __name__ == "__main__":
    raise SystemExit(main())
