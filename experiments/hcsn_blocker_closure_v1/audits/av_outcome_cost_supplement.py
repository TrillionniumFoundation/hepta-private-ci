"""Completion-gated cost supplement; changes no AV metric or scientific gate."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import traceback


RUN = 41158089224
SEAL = "6469cc94a72aed214c5c9d2ff2fba14cdb146626"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def checked_seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("A measured nonnegative finite CPU duration is required")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-receipt", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--publication", type=Path, required=True)
    parser.add_argument("--failed-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve every cost supplement attempt")
    inputs, result = {}, {}
    started = time.process_time()

    def read(path):
        inputs[str(path.resolve())] = dict(sha256=sha(path), bytes=path.stat().st_size)
        return json.loads(path.read_text())

    try:
        run = read(args.run_receipt)
        if (run.get("id") != RUN or run.get("head_sha") != SEAL or run.get("status") != "completed"
                or run.get("repository", {}).get("full_name") != "TrillionniumFoundation/hepta-private-ci"):
            raise PermissionError("No study cost access before the exact full run completes")
        audit = read(args.audit)
        if (audit.get("passed") is not True or audit["run"]["id"] != RUN
                or audit["run"]["head_sha"] != SEAL):
            raise ValueError("The unchanged independent outcome audit must first pass integrity")
        driver_cpu = 0.
        for row in audit["shared_pipeline_stages"]:
            value = checked_seconds(row["direct_child_cpu_seconds"]) + checked_seconds(row["coordinator_body_cpu_seconds"])
            if not math.isclose(value, row["nonoverlap_cpu_seconds"], rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError("Driver cost decomposition changed")
            driver_cpu += value
        acquisition_cpu = 0.
        for row in audit["acquisition_stages"]:
            value = checked_seconds(row["python_cpu_seconds"]) + checked_seconds(row["child_cpu_seconds"])
            if not math.isclose(value, row["nonoverlap_cpu_seconds"], rel_tol=1e-12, abs_tol=1e-9):
                raise ValueError("Fresh acquisition cost decomposition changed")
            acquisition_cpu += value
        base = driver_cpu + acquisition_cpu
        if not math.isclose(base, audit["measured_nonoverlap_cpu_lower_bound"], rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("Frozen independent audit lower bound changed")
        publication = read(args.publication)
        if publication["execution_seal"] != SEAL or str(publication["github_run_id"]) != str(RUN):
            raise ValueError("Packaging receipt belongs to a different execution")
        package_cpu = checked_seconds(publication["packaging_cpu_seconds"])
        failed = read(args.failed_receipt)
        if (failed["schema"] != "hcsn-av-bootstrap-failure.v1" or failed["run_id"] != 41155791247
                or failed["job_id"] != 124402173988 or failed["cpu_seconds"] is not None
                or failed["job_wall_seconds"] != 12):
            raise ValueError("The known failed FFmpeg bootstrap receipt changed")
        result = dict(passed=True, full_run_id=RUN, execution_seal=SEAL,
            driver_coordinator_plus_direct_children_cpu_seconds=driver_cpu,
            fresh_acquisition_disjoint_body_cpu_seconds=acquisition_cpu,
            original_audit_measured_cpu_lower_bound=base,
            additional_nonoverlap_packaging_cpu_seconds=package_cpu,
            additional_packaging_wall_seconds=publication["packaging_wall_seconds"],
            augmented_measured_cpu_lower_bound=base + package_cpu,
            nested_worker_cpu_seconds=audit["measured_worker_cpu_seconds"],
            nested_training_cpu_seconds=audit["nested_training_cpu_seconds"],
            nested_costs_added_again=False,
            packaging_scope="PUBLICATION packaging process_time is outside prepare/train/finalize driver subprocesses; add only this measured packaging CPU once. Imports, verification/upload/push costs not metered here remain outside the CPU lower bound.",
            failed_ffmpeg_bootstrap=dict(run_id=failed["run_id"], job_id=failed["job_id"],
                execution_seal=failed["execution_seal"], job_wall_seconds=failed["job_wall_seconds"],
                cpu_seconds=None, media_acquired=failed["media_acquired"],
                training_jobs=failed["model_training_jobs"], cpu_interpretation="Unknown, never zero; not added to the measured CPU lower bound"),
            complete_training_and_publication_runner_wall=audit["complete_training_and_publication_runner_wall"],
            remaining_unmetered_cpu=["Checkout and dependency installation", "Launcher imports before stage clocks",
                "Initial data transport packaging", "Artifact upload/download, publication verification and git push",
                "Failed FFmpeg bootstrap CPU", "Other host/provider overhead not included in retained receipts"],
            direct_energy_joules=None,
            statistical_scope="Cost-only supplement. All original metrics, 10-bin ECE, bootstrap, baseline choices and scientific gates are unchanged.",
            baseline_qualification="Two development learning rates and validation-only checkpoints at30/60 training CPU seconds are the registered reference schedule; this is not exhaustive or SOTA baseline tuning.")
    except Exception as error:
        result = dict(passed=False, error=repr(error), traceback=traceback.format_exc())
    result.update(schema="hcsn-av-cost-scope-supplement.v1", source_sha256=sha(__file__),
                  input_files=inputs, contained_supplement_cpu_seconds=time.process_time() - started)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(passed=result["passed"], error=result.get("error"))))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
