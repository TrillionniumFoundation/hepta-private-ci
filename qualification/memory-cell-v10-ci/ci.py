"""Run one request mode and retain a failure receipt even when preparation fails."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BASELINE, ROOT, REQUEST_RELATIVE, WORKFLOW, Runner, git, git_text, identity, load, require, save
from request import read_request


def main(args):
    output = args.output.absolute()
    require(not output.exists() and not any(p.is_symlink() for p in (output, *output.parents)),
            "new nonsymlink evidence directory required")
    output.mkdir(parents=True)
    started, cpu = time.monotonic_ns(), time.process_time_ns()
    receipt = {"schema": "hepta.memory.v10.ci-receipt.v1", "passed": False,
               "tests_executed": False, "final_fix_executed": False, "formatter_executed": False,
               "old_holdout_run": False, "scientific_superiority_claimed": False,
               "full_lifecycle_cost_exact": False, "baseline_commit": BASELINE,
               "source_commit": git_text("rev-parse", "HEAD"), "source_tree": git_text("rev-parse", "HEAD^{tree}"),
               "initial_tracked_changes": git_text("status", "--porcelain", "--untracked-files=no"),
               "github": {name: os.environ.get(name) for name in ("GITHUB_SHA", "GITHUB_REF", "GITHUB_RUN_ID",
                            "GITHUB_RUN_ATTEMPT", "GITHUB_REPOSITORY", "GITHUB_JOB")}}
    runner = Runner(output)
    save(output / "receipt.json", receipt)
    hardware = {"schema": "hepta.memory.v10.ci-hardware.v1", "platform": platform.platform(),
                "machine": platform.machine(), "python": sys.version, "logical_cpus": os.cpu_count(),
                "disk_before": shutil.disk_usage(output)._asdict(), "wrapper_started_monotonic_ns": started,
                "job_setup_cpu_measured": False, "process_rss_is_not_whole_job_rss": True}
    if args.job_start_marker is not None and args.job_start_marker.is_file():
        marker = load(args.job_start_marker, 16_384)
        save(output / "JOB_START.json", marker)
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        hardware["job_pre_wrapper_wall_ns"] = started - marker["monotonic_ns"] if marker.get("boot_id") == boot else None
    save(output / "HARDWARE.json", hardware)
    try:
        require(os.environ.get("GITHUB_ACTIONS") == "true", "registered GitHub Actions execution required")
        require(receipt["source_commit"] == os.environ.get("GITHUB_SHA") and not receipt["initial_tracked_changes"],
                "exact clean GitHub checkout required")
        request = read_request()
        receipt.update(request=request, mode=request["mode"], request_identity=identity(ROOT / REQUEST_RELATIVE),
                       workflow_identity=identity(ROOT / WORKFLOW), tests_before_final_fix_and_format=True)
        save(output / "REQUEST.json", request)
        save(output / "receipt.json", receipt)
        for name, command in (("rustc-version", ["rustc", "--version"]), ("cargo-version", ["cargo", "--version"]),
                              ("nextest-version", ["cargo", "nextest", "--version"]), ("just-version", ["just", "--version"])):
            runner.execute(name, command)
        if request["mode"] == "verify":
            from verify import run
            run(runner, args.runtime.absolute(), receipt)
        else:
            from finalize import run
            run(runner, receipt)
    except Exception as error:
        receipt.update(passed=False, error_type=type(error).__name__, error=str(error))
        print("V10 CI failed: " + str(error), flush=True)
    finally:
        receipt.update(executions=runner.executions, wrapper_wall_ns=time.monotonic_ns() - started,
                       wrapper_own_cpu_ns=time.process_time_ns() - cpu,
                       final_tracked_changes=git_text("status", "--porcelain", "--untracked-files=no"),
                       disk_after=shutil.disk_usage(output)._asdict())
        (output / "generated.patch").write_bytes(git("diff", "--binary", "--full-index", "--no-ext-diff", "--no-textconv"))
        save(output / "receipt.json", receipt)
        print("V10_CI_RECEIPT " + str(output / "receipt.json"), flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--job-start-marker", type=Path)
    raise SystemExit(main(parser.parse_args()))
