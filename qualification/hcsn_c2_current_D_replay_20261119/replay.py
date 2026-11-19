"""Six current strict-best D replays; original controller UNKNOWN stays intact."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time
import traceback
import zipfile

from audit_io import read_dev, require, save, sha, verify_files

HERE = Path(__file__).resolve().parent


def frozen():
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_bytes())
    for name, expected in freeze["files"].items():
        require(sha(HERE / name) == expected, "program identity: " + name)
    return json.loads((HERE / "REQUEST.json").read_bytes())


def live_original_processes(request):
    """Point-in-time writer check; deliberately not an original exit receipt."""
    matches, errors = [], []
    for directory in Path("/proc").iterdir():
        if not directory.name.isdecimal() or int(directory.name) in (os.getpid(), os.getppid()):
            continue
        try:
            args = (directory / "cmdline").read_bytes().split(b"\0")
            args = [s.decode(errors="replace") for s in args if s]
            if any(s in request["original_program_paths"] or
                   s.startswith(request["original_output_root"] + "/") for s in args):
                matches.append({"pid": int(directory.name), "args": args})
        except FileNotFoundError:
            pass
        except PermissionError:
            errors.append(int(directory.name))
    return {"matches": matches, "permission_errors": errors,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "unix_time": time.time(), "original_controller_terminal": "UNKNOWN",
            "scope": "Current process arguments only; no inferred historic exit, CPU or launch outcome."}


def child(name):
    started, cpu = time.monotonic(), time.process_time()
    request = frozen()
    limits = request["limits"]
    resource.setrlimit(resource.RLIMIT_AS, (limits["address_space_bytes"],) * 2)
    os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    row = next(r for r in request["fits"] if r["name"] == name)
    out = HERE / "RUN_OUTPUT" / name
    out.mkdir()
    inputs = {}
    result = {"name": name, "status": "FAILED_OR_UNFINISHED", "E_access": False,
              "training_updates": 0, "optimizer_construct_restore_step": 0, "backward_calls": 0,
              "original_controller_terminal": "UNKNOWN", "original_full_training_replays": "0/6"}

    def budget():
        require(time.monotonic() - started <= limits["per_fit_wall_seconds"], "fit wall budget")
        require(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 <= limits["rss_bytes"], "fit RSS budget")

    def checked(path, expected):
        require(Path(path).is_file() and not Path(path).is_symlink() and sha(path) == expected,
                "bound input identity: " + str(path))
        inputs[str(path)] = expected

    try:
        checked(Path(sys.executable).resolve(), request["runtime"]["python_binary_sha256"])
        checked(request["runtime"]["restoration_result_path"], request["runtime"]["restoration_result_sha256"])
        for item in (row["checkpoint"], row["D_logits"], row["initial"]):
            checked(item["path"], item["sha256"])
        report_path = HERE / row["report_copy"] if "report_copy" in row else Path(row["report"]["path"])
        checked(report_path, row["report"]["sha256"])
        for historical, expected in row["source_file_sha256"].items():
            actual = request["source_aliases"].get(historical, historical)
            checked(actual, expected)
        plan = json.loads((HERE / "DATA_PLAN.json").read_bytes())
        rows = read_dev(plan, inputs)
        save(out / "INPUTS_BEFORE.json", inputs)
        import numpy as np
        import torch
        from independent_metrics import compare_metrics, metrics
        from replay_fit import fresh_forward, tensor_digest
        require(torch.__version__ == request["runtime"]["torch"] and
                torch.version.git_version == request["runtime"]["torch_git"] and
                np.__version__ == request["runtime"]["numpy"], "restored scientific runtime")
        require(str(Path(torch.__file__).resolve()).startswith(request["runtime"]["site_packages"] + "/"), "Torch origin")
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        torch.use_deterministic_algorithms(True)
        source = Path(request["model_source"])
        sys.path.insert(0, str(source / "proposals/localization-v3"))
        import cores
        from hcsn_study_support import batches, sources
        require(Path(cores.__file__).resolve() == source / "proposals/localization-v3/cores.py", "core origin")
        checkpoint = torch.load(row["checkpoint"]["path"], weights_only=True, map_location="cpu")
        require(checkpoint["epochs_completed"] == row["strict_history"]["best_epoch"] and
                checkpoint["model_configuration"] == row["model_configuration"] and
                checkpoint["data_manifest_sha256"] == plan["data_manifest_sha256"], "checkpoint semantics")
        model = cores.CoreStudyModel(**checkpoint["model_configuration"])
        model.load_state_dict(checkpoint["model"], strict=True)
        initial = torch.load(row["initial"]["path"], weights_only=True, map_location="cpu")
        for key, value in model.state_dict().items():
            require(bool(torch.isfinite(value).all()), "nonfinite trained tensor")
            if key.startswith(("frontend.", "head.")) or ".physics." in key:
                require(torch.equal(value, initial["model"][key]), "frozen shared/physical tensor")
        expected_sources = {request["source_aliases"].get(k, k): v for k, v in row["source_file_sha256"].items()}
        actual_sources = sources(model)
        require(actual_sources == expected_sources, "actual dependency source map")
        require(model.core.recorder is None, "unexpected trace recorder")
        result.update(best_epoch=checkpoint["epochs_completed"], checkpoint_sha256=row["checkpoint"]["sha256"],
                      source_map_actual=actual_sources, frozen_shared_and_physics_equal_initial=True,
                      runtime={"python": sys.version, "executable": sys.executable, "torch": torch.__version__,
                               "torch_git": torch.version.git_version, "numpy": np.__version__})
        del checkpoint, initial
        with (out / "BATCHES.jsonl").open("x") as journal:
            def record(item):
                journal.write(json.dumps({**item, "process_wall_seconds": time.monotonic() - started}) + "\n")
                journal.flush()
            logits, labels, before = fresh_forward(model, rows, 32, batches, budget, record)
        expected_labels = torch.tensor([y for r in rows for y in r["y"]], dtype=torch.long)
        ids = [r["id"] for r in rows]
        require(torch.equal(labels, expected_labels) and logits.shape == (31952, 11), "full D order/shape")
        saved = torch.load(row["D_logits"]["path"], weights_only=True, map_location="cpu")
        require(saved["episode_ids"] == ids and torch.equal(saved["labels"], labels), "saved D order/labels")
        fresh_metrics = metrics(logits.numpy(), labels.numpy())
        saved_metrics = metrics(saved["logits"].numpy(), saved["labels"].numpy())
        difference = compare_metrics(fresh_metrics, row["D_metrics"], 2e-12)
        saved_difference = compare_metrics(saved_metrics, row["D_metrics"], 2e-12)
        logit_difference = float((logits - saved["logits"]).abs().max())
        require(logit_difference <= 2e-12, "fresh/saved full logits mismatch")
        payload = {"logits": logits, "labels": labels, "episode_ids": ids,
                   "event_episode_index": torch.tensor([i for i, r in enumerate(rows) for _ in r["y"]]),
                   "event_position": torch.tensor([i for r in rows for i in range(len(r["y"]))]),
                   "source_rows": torch.tensor([i for r in rows for i in r["source_rows"]]),
                   "best_epoch": result["best_epoch"], "checkpoint_sha256": row["checkpoint"]["sha256"]}
        with (out / "FRESH_D_LOGITS.pt").open("xb") as stream:
            torch.save(payload, stream)
        require(sources(model) == actual_sources, "source changed during forward")
        result.update(status="PASSED_CURRENT_BEST_FULL_D_REPLAY", fresh_metrics=fresh_metrics,
                      saved_metrics=saved_metrics, fresh_recorded_metric_differences=difference,
                      saved_recorded_metric_differences=saved_difference, max_abs_logit_difference=logit_difference,
                      bitwise_saved_logit_match=torch.equal(logits, saved["logits"]),
                      model_tensor_digest_before=before, model_tensor_digest_after=tensor_digest(model.state_dict()),
                      fresh_logits={"sha256": sha(out / "FRESH_D_LOGITS.pt"), "bytes": (out / "FRESH_D_LOGITS.pt").stat().st_size},
                      model_state_dict_tensor_bytes=sum(t.numel() * t.element_size() for t in model.state_dict().values()),
                      complete_recurrent_density_content_delay_state_bytes=None)
    except Exception:
        result["error"] = traceback.format_exc()
    finally:
        try:
            verify_files(inputs)
            frozen()
            budget()
            result["inputs_unchanged"] = True
        except Exception:
            result.update(status="FAILED_OR_UNFINISHED", final_error=traceback.format_exc(), inputs_unchanged=False)
        result.update(wall_seconds=time.monotonic() - started, cpu_seconds=time.process_time() - cpu,
                      peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        save(out / "RESULT.json", result)
    return 0 if result["status"] == "PASSED_CURRENT_BEST_FULL_D_REPLAY" else 2


def controller():
    started = time.monotonic()
    request = frozen()
    output = HERE / "RUN_OUTPUT"
    output.mkdir()
    observation = live_original_processes(request)
    save(output / "POSTMORTEM_PROCESS_OBSERVATION.json", observation)
    require(not observation["matches"] and not observation["permission_errors"], "live/unknown original writer")
    costs = []
    for fit in request["fits"]:
        remaining = request["limits"]["whole_wall_seconds"] - (time.monotonic() - started) - 60
        timeout = min(request["limits"]["per_fit_wall_seconds"], remaining)
        if timeout <= 0:
            costs.append({"name": fit["name"], "status": "UNRUN_WITHIN_BUDGET"})
            continue
        begin = time.monotonic()
        with (output / (fit["name"] + ".stdout")).open("xb") as stdout, (output / (fit["name"] + ".stderr")).open("xb") as stderr:
            process = subprocess.Popen([request["runtime"]["python"], "-B", str(HERE / "replay.py"), "--fit", fit["name"]],
                                       stdout=stdout, stderr=stderr, start_new_session=True)
            timed_out = False
            while True:
                pid, status, usage = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                if time.monotonic() - begin >= timeout:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGKILL)
                    _, status, usage = os.wait4(process.pid, 0)
                    process.returncode = os.waitstatus_to_exitcode(status)
                    break
                time.sleep(.1)
        item = {"name": fit["name"], "returncode": process.returncode, "timed_out": timed_out,
                "wall_seconds": time.monotonic() - begin, "cpu_seconds": usage.ru_utime + usage.ru_stime,
                "peak_rss_kib": usage.ru_maxrss, "scope": "exact child wait4 through exit"}
        costs.append(item)
        save(output / (fit["name"] + ".COST.json"), item)
    passed = sum(c.get("returncode") == 0 for c in costs)
    summary = {"schema": "six-current-C2-best-D-replay-v1", "passed": passed, "denominator": 6,
               "costs": costs, "wall_seconds": time.monotonic() - started, "E_access": False,
               "original_controller_terminal": "UNKNOWN", "original_full_training_replays": "0/6",
               "original_full_C2_chain_auditor_completed": False, "scientific_admission": "HOLD"}
    save(output / "SUMMARY.json", summary)
    files = sorted(p for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    manifest = {str(p.relative_to(HERE)): {"bytes": p.stat().st_size, "sha256": sha(p)} for p in files}
    with zipfile.ZipFile(HERE / "originals.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, str(path.relative_to(HERE)))
        archive.writestr("MANIFEST.json", json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    save(HERE / "ARCHIVE.json", {"bytes": (HERE / "originals.zip").stat().st_size,
                               "sha256": sha(HERE / "originals.zip"), "members": len(files) + 1,
                               "whole_stage_wall_seconds": time.monotonic() - started})
    print(json.dumps(summary, sort_keys=True), flush=True)
    require(time.monotonic() - started <= request["limits"]["whole_wall_seconds"], "whole replay budget")
    return 0 if passed == 6 else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit")
    args = parser.parse_args()
    raise SystemExit(child(args.fit) if args.fit else controller())
