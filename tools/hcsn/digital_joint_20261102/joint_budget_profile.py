"""Real-process budget instrumentation qualification, not model efficacy data."""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

from .joint_budget import BudgetCheckpoint, BudgetSpec, cost_ledger, match_group, run_limited, write_new


def worker(mode, artifact, seed):
    import numpy as np
    rng = np.random.default_rng(seed)
    x, y = rng.normal(size=(128, 32)), rng.normal(size=(128, 16))
    w = rng.normal(size=(32, 16))*.1
    budget, updates = BudgetCheckpoint.from_env(), 0
    if mode == "sleep":
        time.sleep(3)
    if mode == "fork":
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"])
    while mode in ("overrun", "fork") or (updates < 20 if mode == "quick" else budget.can_continue(.002)):
        gradient = x.T @ (x @ w-y)/len(x)
        w -= .01*gradient
        updates += 1
    write_new(artifact, dict(mode=mode, updates=updates, loss=float(np.mean((x @ w-y)**2)),
                             weight_sha256=hashlib.sha256(w.tobytes()).hexdigest(),
                             process_plus_shared_cpu_before_export=budget.used_cpu_seconds))


def hardware():
    devices = list(Path("/dev").glob("nvidia*"))
    dri = list(Path("/dev/dri").glob("*")) if Path("/dev/dri").exists() else []
    energy = list(Path("/sys/class/powercap").glob("**/energy_uj"))
    return dict(platform=platform.platform(), architecture=platform.machine(),
                nvidia_smi=shutil.which("nvidia-smi"), nvidia_devices=list(map(str, devices)),
                dri_devices=list(map(str, dri)), energy_counter_paths=list(map(str, energy)),
                gpu_qualification="unavailable" if not devices and not dri else "not_measured",
                energy_qualification="unavailable" if not energy else "not_measured",
                energy_joules=None, gpu_latency_seconds=None)


def profile(out):
    out.mkdir(parents=True, exist_ok=False)
    module = "tools.hcsn.digital_joint_20261102.joint_budget_profile"
    # Publish settings locally before any measured subprocess is launched.
    ordinary = BudgetSpec(2., export_reserve_seconds=.10, wall_seconds=15.)
    shared_spec = BudgetSpec(.7, export_reserve_seconds=.10, wall_seconds=10.)
    failure = BudgetSpec(.5, export_reserve_seconds=.10, wall_seconds=10.)
    protocol = dict(schema="joint-budget-instrumentation-profile-v1", nominal=asdict(ordinary),
                    shared=asdict(shared_spec), rejection=asdict(failure),
                    purpose="supervisor qualification on actual bounded NumPy optimization; not a fit or speedup result", hardware=hardware(),
                    sources={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), Path(__file__).with_name("joint_budget.py"))})
    write_new(out/"PROTOCOL.json", protocol)
    def launch(name, mode, spec, shared=None, consumers=1):
        command = [sys.executable, "-m", module, "--worker", mode, "--artifact", str(out/name/"artifact.json")]
        return run_limited(command, spec, out/name, shared, consumers)
    preparation = launch("shared", "work", shared_spec)
    a = launch("fit_a", "work", ordinary, out/"shared/RECEIPT.json", 2)
    b = launch("fit_b", "work", ordinary, out/"shared/RECEIPT.json", 2)
    over = launch("overrun", "overrun", failure)
    sleep = launch("wall", "sleep", BudgetSpec(2., export_reserve_seconds=.1, wall_seconds=.4))
    fork = launch("subprocess", "fork", ordinary)
    quick = launch("underused", "quick", ordinary)
    strict = launch("backstop_cpu_control", "overrun", failure)
    # Real child completion followed by a real supervisor scheduling delay.
    # No CPU/wall values or child exit results are synthesized.
    original_wait4 = os.wait4
    def delayed_reap(pid, flags):
        result = original_wait4(pid, 0)
        time.sleep(.15)
        return result
    try:
        os.wait4 = delayed_reap
        late = run_limited([sys.executable, "-c", "pass"],
                           BudgetSpec(2., export_reserve_seconds=.1, wall_seconds=.1), out/"late_completion")
    finally:
        os.wait4 = original_wait4
    results = dict(shared_preparation_admitted=preparation["admissible"],
                   bounded_fit_a_admitted=a["admissible"], bounded_fit_b_admitted=b["admissible"],
                   bounded_pair_actual_matched=match_group([a, b])["matched"],
                   ignored_checkpoint_cpu_overrun_rejected=not over["admissible"] and "cpu" in over["rejection_reason"],
                   low_cpu_wall_overrun_rejected=not sleep["admissible"] and sleep["rejection_reason"] == "wall_limit_exceeded",
                   subprocess_contract_rejected=not fork["admissible"] and fork["rejection_reason"] == "unsupported_subprocess_observed",
                   early_success_not_called_matched=quick["admissible"] and not quick["actual_cpu_in_match_band"])
    results["completed_child_past_wall_deadline_rejected"] = (not late["admissible"] and late["rejection_reason"] == "final_wall_limit_exceeded")
    actual = strict["cpu_backstop"]
    expected = math.ceil(failure.cpu_backstop_multiplier*failure.cpu_limit)
    results["wide_backstop_recorded_scientific_cpu_overrun_still_rejected"] = (
        actual["actual_rlimit_cpu_seconds"] == actual["configured_rlimit_cpu_seconds"] == [expected, expected+1]
        and expected > failure.cpu_limit and strict["worker_cpu_seconds"] > failure.cpu_limit
        and not strict["admissible"] and "cpu" in strict["rejection_reason"] and strict["returncode"] == -signal.SIGTERM)
    report = dict(schema="joint-budget-profile-result-v1", passed=all(results.values()), checks=results,
                  paired_match=match_group([a, b]), costs=cost_ledger([a, b]), hardware=protocol["hardware"],
                  receipts={n: json.loads((out/n/"RECEIPT.json").read_text()) for n in ("shared", "fit_a", "fit_b", "overrun", "wall", "subprocess", "underused", "late_completion", "backstop_cpu_control")},
                  no_candidate_benefit_or_energy_claim=True)
    write_new(out/"SUMMARY.json", report)
    print(json.dumps(dict(passed=report["passed"], checks=results, paired_cpu=report["paired_match"])))
    if not report["passed"]:
        raise RuntimeError("budget instrumentation qualification failed; preserve this attempt")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path)
    p.add_argument("--worker", choices=("work", "overrun", "sleep", "fork", "quick"))
    p.add_argument("--artifact", type=Path)
    p.add_argument("--seed", type=int, default=11)
    a = p.parse_args()
    if a.worker:
        worker(a.worker, a.artifact, a.seed)
    else:
        profile(a.out)


if __name__ == "__main__":
    main()
