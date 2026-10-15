"""Process-isolated four-arm Granite97 scientific fitting, not production execution.

Unlike the original in-interpreter 2x2 driver, each arm has an independent
Python process, cold model load, optimizer and allocator. The independent
stdlib reviewer also runs in a separate process. This is an *observed*
resource boundary, not third-party host attestation or efficacy evidence.
"""
from __future__ import annotations

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

from group_feedback_factorial_review import MATRIX

SCHEMA = "hepta.group.factorial-process-isolation.v1"
MAX_LOG_BYTES = 2_000_000
MAX_TIMEOUT_SECONDS = 7200


def _file_sha(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("fixed regular script required; symlinks are forbidden")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cpu_ns(stamp):
    return int((stamp.ru_utime + stamp.ru_stime) * 1_000_000_000)


def _launch(argv, *, cwd, log, timeout_seconds):
    """Use one new OS process group, bound its runtime, and observe child CPU."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.perf_counter_ns()
    with log.open("xb") as stream:
        with subprocess.Popen(argv, cwd=cwd, stdout=stream,
                              stderr=subprocess.STDOUT, start_new_session=True) as proc:
            pid = proc.pid
            try:
                returncode = proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                # Terminate children of the private research job as well.
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                raise ValueError("bounded independent research arm timed out") from exc
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    elapsed = time.perf_counter_ns() - start
    size = log.stat().st_size
    if not 0 <= size <= MAX_LOG_BYTES:
        raise ValueError("unbounded original runner log; no success receipt")
    entry = dict(pid=pid, exit_code=returncode, wall_ns=elapsed,
                 waited_child_cpu_ns=max(0, _cpu_ns(after) - _cpu_ns(before)),
                 log_sha256=_file_sha(log), log_bytes=size)
    if returncode != 0:
        raise ValueError(f"original separate research process failed (exit {returncode})")
    return entry


def isolated_factorial(snapshot, output_root, *, seed=41, steps=120,
                       train_count=256, heldout_count=96, profile="sgd_v1",
                       timeout_seconds=3600, campaign_script=None,
                       reviewer_script=None):
    """Run four independent PIDs, then independently re-audit the original files.

    The two explicit script paths exist for local fault-injection testing; the
    public CLI always binds to its own sibling originals.
    """
    if (type(seed) is not int or not 0 <= seed < 2**31
            or type(steps) is not int or not 1 <= steps <= 10000
            or type(train_count) is not int or not 16 <= train_count <= 2048
            or type(heldout_count) is not int or not 12 <= heldout_count <= 256
            or type(profile) is not str or profile not in ("sgd_v1", "adam_v1")
            or type(timeout_seconds) is not int
            or not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS):
        raise ValueError("fixed positive seed/cohort/optimizer/timeout limits required")
    snapshot = Path(snapshot).absolute()
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise ValueError("existing non-symlink original model snapshot required")
    output_root = Path(output_root).absolute()
    script = Path(campaign_script or Path(__file__).with_name(
        "group_attention_campaign.py")).absolute()
    reviewer = Path(reviewer_script or Path(__file__).with_name(
        "group_feedback_factorial_review.py")).absolute()
    script_sha, reviewer_sha = _file_sha(script), _file_sha(reviewer)
    if output_root.exists():
        raise ValueError("factorial output must be create-only")
    output_root.mkdir(parents=True)
    recorded = {}
    for name, (guarded, feedback) in MATRIX.items():
        argv = [sys.executable, "-B", str(script),
                "--snapshot", str(snapshot), "--output", str(output_root / name),
                "--seed", str(seed), "--steps", str(steps),
                "--train-count", str(train_count),
                "--heldout-count", str(heldout_count),
                "--training-profile", profile,
                "--training-feedback-policy", feedback]
        if guarded:
            argv.append("--terminal-guard")
        receipt = _launch(argv, cwd=str(script.parent),
                          log=output_root / (name + ".log"),
                          timeout_seconds=timeout_seconds)
        if not (output_root / name / "report.json").is_file():
            raise ValueError("model arm exited success without original training report")
        recorded[name] = dict(receipt, terminal_guard=guarded,
                              training_feedback_policy=feedback,
                              original_report_sha256=_file_sha(
                                  output_root / name / "report.json"))
    if len(set(recorded[k]["pid"] for k in MATRIX)) != 4:
        raise ValueError("four distinct OS model processes not observed")
    # Reopen all original Head weights, source rows and traces with the
    # separately executed unmodified stdlib-only four-arm reviewer.
    arguments = [sys.executable, "-B", "-S", str(reviewer)]
    for name in MATRIX:
        arguments.extend(("--" + name.replace("_", "-"), str(output_root / name)))
    arguments.extend(("--output", str(output_root / "factorial-independent-review.json")))
    review = _launch(arguments, cwd=str(reviewer.parent),
                     log=output_root / "independent-review.log",
                     timeout_seconds=timeout_seconds)
    review_path = output_root / "factorial-independent-review.json"
    if not review_path.is_file() or review.pid in {v["pid"] for v in recorded.values()}:
        raise ValueError("separate original scientific reviewer did not produce a report")
    # The validation rules here cannot replace the original source-owning reviewer.
    from group_checkpoint_audit import strict_json_file
    report = strict_json_file(review_path)
    if (report.get("passed") is not True or report.get("authority") != "DENY_ALL"
            or report.get("production_promotion_permitted") is not False
            or report.get("independently_future_tested") is not False):
        raise ValueError("original model result is not research-admissible")
    details = dict(schema=SCHEMA, authority="DENY_ALL",
                   completed_four_isolated_model_processes=True,
                   separate_independent_audit_process=True,
                   original_checkpoint_and_trace_evidence_attested_independently=False,
                   physical_host_provenance_independently_attested=False,
                   matched_total_compute_established=False,
                   trained_model_selected=False, production_promotion_permitted=False,
                   original_campaign_source_sha256=script_sha,
                   original_reviewer_source_sha256=reviewer_sha,
                   snapshot_path_not_attested=str(snapshot),
                   seed=seed, steps=steps, profile=profile,
                   model_arms=recorded, independent_review_process=review,
                   independent_review_sha256=_file_sha(review_path))
    with (output_root / "isolation-receipt.json").open("x") as f:
        json.dump(details, f, sort_keys=True, allow_nan=False)
    return details


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--seed", type=int, default=41)
    parser.add_argument("--steps", type=int, default=120)
    parser.add_argument("--train-count", type=int, default=256)
    parser.add_argument("--heldout-count", type=int, default=96)
    parser.add_argument("--training-profile", choices=("sgd_v1", "adam_v1"),
                        default="sgd_v1")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    args = parser.parse_args()
    r = isolated_factorial(
        args.snapshot, args.output_root, seed=args.seed, steps=args.steps,
        train_count=args.train_count, heldout_count=args.heldout_count,
        profile=args.training_profile, timeout_seconds=args.timeout_seconds)
    print(json.dumps(dict(schema=r["schema"], authority=r["authority"],
          success=True, production_promotion_permitted=False), sort_keys=True))


if __name__ == "__main__":
    main()
