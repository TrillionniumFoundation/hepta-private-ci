"""Run every registered seed in order; a quality failure never drops a seed."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

from evolution_common import digest, read_json, require, retain
from longitudinal_campaign import campaign
from longitudinal_runtime import source_identity


def main(args):
    registered = read_json(args.campaign)
    require(
        digest(registered) == args.campaign_sha256 and registered == campaign(),
        "campaign changed",
    )
    require(
        digest(source_identity(args.repo)) == args.source_sha256,
        "source launch pin changed",
    )
    output = args.output.absolute()
    require(not output.exists(), "new campaign output required")
    output.mkdir(parents=True)
    retain(output / "registered-campaign.json", registered)
    receipts = []
    for seed in registered["launch_order"]:
        trial = Path(__file__).with_name("longitudinal_trial.py")
        command = [
            sys.executable,
            "-B",
            str(args.repo / "scripts/memory_cell_network/model_child.py"),
            "--parent-pid",
            str(os.getpid()),
            str(trial),
            "--repo",
            str(args.repo),
            "--model",
            str(args.model),
            "--campaign",
            str(args.campaign),
            "--campaign-sha256",
            args.campaign_sha256,
            "--source-sha256",
            args.source_sha256,
            "--seed",
            str(seed),
            "--output",
            str(output / f"seed-{seed}"),
        ]
        started = time.monotonic_ns()
        timed_out = False
        with (output / f"seed-{seed}.log").open("xb") as log:
            with subprocess.Popen(
                command, stdout=log, stderr=subprocess.STDOUT
            ) as process:
                try:
                    code = process.wait(timeout=6000)
                except subprocess.TimeoutExpired:
                    process.kill()
                    code = process.wait()
                    timed_out = True
        record = dict(
            seed=seed,
            command=command,
            pid=process.pid,
            returncode=code,
            timed_out=timed_out,
            elapsed_ns=time.monotonic_ns() - started,
            quality_failure_does_not_stop=code == 2,
        )
        retain(output / f"seed-{seed}.completion.json", record)
        receipts.append(record)
        if code not in (0, 2):
            retain(
                output / "campaign-incomplete.json",
                dict(
                    completed_receipts=receipts,
                    remaining_unexecuted=[
                        s
                        for s in registered["launch_order"]
                        if s not in {r["seed"] for r in receipts}
                    ],
                    reason="execution or environment failure, not selection on quality",
                    production_accepted=False,
                ),
            )
            return 1
    results = [
        read_json(output / f"seed-{s}/result.json") for s in registered["launch_order"]
    ]
    retain(
        output / "campaign-result.json",
        dict(
            schema="hepta.longitudinal.campaign-result.v1",
            completed=True,
            receipts=receipts,
            all_seeds_retained=True,
            per_seed_quality=[
                dict(
                    seed=r["seed"], gates=r["quality_gates"], passed=r["quality_passed"]
                )
                for r in results
            ],
            total_optimizer_updates=sum(
                r["costs"]["saved_optimizer_updates"] for r in results
            ),
            total_raw_rows=sum(r["costs"]["counted_raw_rows"] for r in results),
            independent_natural_task_groups=0,
            production_accepted=False,
        ),
    )
    return 0 if all(r["quality_passed"] for r in results) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "model", "campaign", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--campaign-sha256", required=True)
    parser.add_argument("--source-sha256", required=True)
    raise SystemExit(main(parser.parse_args()))
