"""Run a frozen development campaign in bounded, isolated Python processes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import coding_sft, data


def source_inventory():
    return {
        p.name: coding_sft.file_hash(p)
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }


class Execution:
    def __init__(self, root, dataset, materials, logs):
        self.root, self.dataset, self.materials = map(Path, (root, dataset, materials))
        self.logs = Path(logs)
        self.logs.mkdir(parents=True, exist_ok=False)
        self.source = source_inventory()
        self.source_digest = data.digest(self.source)
        self.dataset_hash = coding_sft.file_hash(self.dataset)
        self.started = time.time_ns()
        self.env = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
        }
        coding_sft.write_new(
            self.logs / "EXECUTION_PLAN.json",
            {
                "schema": "hepta.development-sequence.v1",
                "started_at_ns": self.started,
                "source_inventory": self.source,
                "source_digest": self.source_digest,
                "dataset_sha256": self.dataset_hash,
                "root": str(self.root),
                "python": sys.executable,
                "maximum_parallel_processes": 2,
                "per_stage_timeout_seconds": 1800,
                "automatic_retry": False,
                "independent_experiments_qualified": False,
            },
        )

    def guard(self):
        if (
            source_inventory() != self.source
            or coding_sft.file_hash(self.dataset) != self.dataset_hash
        ):
            raise ValueError(
                "frozen executable source or input file changed during execution"
            )

    def stage(self, label, operation, name=None, interaction=False):
        self.guard()
        directory = self.logs / label
        directory.mkdir()
        module = (
            "cell_experiments.interaction_campaign"
            if interaction
            else "cell_experiments.campaign"
        )
        args = [sys.executable, "-m", module]
        args += ["--operation", operation] if interaction else [operation]
        args += ["--root", str(self.root), "--dataset", str(self.dataset)]
        if name:
            args += ["--name", name]
        if operation == "prepare":
            args += [
                "--materials",
                str(self.materials),
                "--source-digest",
                self.source_digest,
            ]
        begin, wall = time.time_ns(), time.perf_counter()
        coding_sft.write_new(
            directory / "STARTED.json",
            {"argv": args, "started_at_ns": begin, "source_digest": self.source_digest},
        )
        print(
            json.dumps({"stage": label, "state": "started", "time_ns": begin}),
            flush=True,
        )
        code, error = None, None
        try:
            with (
                (directory / "stdout.txt").open("xb") as out,
                (directory / "stderr.txt").open("xb") as err,
            ):
                completed = subprocess.run(
                    args,
                    stdout=out,
                    stderr=err,
                    env=self.env,
                    timeout=1800,
                    check=False,
                )
            code = completed.returncode
            self.guard()
        except BaseException as caught:
            error = repr(caught)
        result = {
            "stage": label,
            "exit_code": code,
            "error": error,
            "started_at_ns": begin,
            "completed_at_ns": time.time_ns(),
            "wall_seconds": time.perf_counter() - wall,
            "stdout_sha256": coding_sft.file_hash(directory / "stdout.txt"),
            "stderr_sha256": coding_sft.file_hash(directory / "stderr.txt"),
            "status": "COMPLETE" if code == 0 and error is None else "FAILED",
        }
        coding_sft.write_new(directory / "RESULT.json", result)
        print(json.dumps(result), flush=True)
        if result["status"] != "COMPLETE":
            raise RuntimeError("stage failed; original evidence retained: " + label)
        return result

    def parallel(self, jobs):
        errors = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.stage, *job) for job in jobs]
            for future in futures:
                try:
                    future.result()
                except Exception as error:
                    errors.append(repr(error))
        if errors:
            raise RuntimeError(errors)

    def run(self):
        try:
            self.stage("01-prepare", "prepare")
            self.parallel(
                [
                    (f"02-train-{name}", "train", name)
                    for name in ("final_answer", "trajectory")
                ]
            )
            self.parallel(
                [
                    (f"03-train-{name}", "train", name)
                    for name in ("numeric_specialist", "boolean_specialist")
                ]
            )
            self.parallel(
                [
                    (f"04-B-{name}", "evaluate", name)
                    for name in ("final_answer", "trajectory")
                ]
            )
            self.stage("05-features-teachers-retrieval-B", "after")
            self.stage("06-E2-collect-A", "collect", interaction=True)
            names = ("e2_demonstration", "e2_shadow", "e2_controlled")
            self.parallel([(f"07-train-{name}", "train", name, True) for name in names])
            self.parallel([(f"08-B-{name}", "evaluate", name, True) for name in names])
            self.stage("09-E2-freeze-selection", "select", interaction=True)
            self.stage("10-E3-E4-E5", "compose")
            self.parallel(
                [
                    (f"11-E6-{name}", "e6", name)
                    for name in ("final_answer", "trajectory")
                ]
            )
            self.stage("12-E1-C-readout", "confirm")
            self.stage("13-E2-C-readout", "confirm", interaction=True)
            result = {
                "status": "COMPLETE_DEVELOPMENT_CAMPAIGN",
                "independent_experiments_qualified": False,
                "source_digest": self.source_digest,
                "dataset_sha256": self.dataset_hash,
                "started_at_ns": self.started,
                "completed_at_ns": time.time_ns(),
                "production_eligible": False,
                "native_runtime_adoption": False,
            }
        except BaseException as error:
            result = {
                "status": "INCOMPLETE",
                "error": repr(error),
                "automatic_retry": False,
                "source_digest": self.source_digest,
                "completed_at_ns": time.time_ns(),
                "production_eligible": False,
                "independent_experiments_qualified": False,
            }
            coding_sft.write_new(self.logs / "RESULT.json", result)
            raise
        coding_sft.write_new(self.logs / "RESULT.json", result)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("root", "dataset", "materials", "logs"):
        parser.add_argument("--" + field, required=True)
    args = parser.parse_args()
    print(
        json.dumps(Execution(args.root, args.dataset, args.materials, args.logs).run()),
        flush=True,
    )


if __name__ == "__main__":
    main()
