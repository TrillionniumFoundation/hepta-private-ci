"""Run isolated experiment stages with retained failures and at most two children."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import coding_sft, data, study_v2


class Execution:
    def __init__(self, root, materials, logs):
        self.root, self.materials, self.logs = map(Path, (root, materials, logs))
        self.root.mkdir(parents=True, exist_ok=False)
        self.logs.mkdir(parents=True, exist_ok=False)
        self.source = study_v2.sources()
        self.env = {
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "OMP_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "1",
        }
        coding_sft.write_new(
            self.logs / "EXECUTION_PLAN.json",
            {
                "schema": "hepta.repository-sequence.v2",
                "source": self.source,
                "supervisor_pid": os.getpid(),
                "source_digest": data.digest(self.source),
                "created_at_ns": time.time_ns(),
                "root": str(self.root),
                "materials": str(self.materials),
                "python": sys.executable,
                "maximum_parallel_children": 2,
                "stage_timeout_seconds": 2400,
                "automatic_retry": False,
                "scientific_independence_qualified": False,
            },
        )

    def stage(self, label, operation, name=None, builder=False):
        if study_v2.sources() != self.source:
            raise ValueError("source changed during campaign")
        directory = self.logs / label
        directory.mkdir()
        args = [
            sys.executable,
            "-m",
            "cell_experiments.repo_tasks" if builder else "cell_experiments.study_v2",
        ]
        if builder:
            args += [
                "--panel",
                operation,
                "--output",
                str(self.root / "inputs" / operation),
            ]
        else:
            args += [operation, "--root", str(self.root)]
            if name:
                args += ["--name", name]
            if operation == "prepare":
                args += ["--materials", str(self.materials)]
        started, wall = time.time_ns(), time.perf_counter()
        coding_sft.write_new(
            directory / "STARTED.json", {"argv": args, "started_at_ns": started}
        )
        print(json.dumps({"stage": label, "status": "STARTED"}), flush=True)
        code, error = None, None
        try:
            with (
                (directory / "stdout.txt").open("xb") as out,
                (directory / "stderr.txt").open("xb") as err,
            ):
                code = subprocess.run(
                    args,
                    stdout=out,
                    stderr=err,
                    env=self.env,
                    timeout=2400,
                    check=False,
                ).returncode
            if study_v2.sources() != self.source:
                raise ValueError("source changed during stage")
        except Exception as caught:
            error = repr(caught)
        result = {
            "stage": label,
            "exit_code": code,
            "error": error,
            "started_at_ns": started,
            "completed_at_ns": time.time_ns(),
            "wall_seconds": time.perf_counter() - wall,
            "stdout_sha256": coding_sft.file_hash(directory / "stdout.txt"),
            "stderr_sha256": coding_sft.file_hash(directory / "stderr.txt"),
            "status": "COMPLETE" if code == 0 and error is None else "FAILED",
        }
        coding_sft.write_new(directory / "RESULT.json", result)
        print(json.dumps(result), flush=True)
        if result["status"] != "COMPLETE":
            raise RuntimeError("stage failed; original logs retained: " + label)
        return json.loads((directory / "stdout.txt").read_text())

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
        started = time.time_ns()
        try:
            for panel in ("open", "confirmation", "warmup"):
                self.stage("01-build-" + panel, panel, builder=True)
            self.stage("02-freeze", "prepare")
            self.parallel(
                [("03-train-" + name, "train", name) for name in study_v2.TRAINED[:4]]
            )
            self.stage("04-collect-E2", "collect")
            self.parallel(
                [("05-train-" + name, "train", name) for name in study_v2.TRAINED[4:]]
            )
            self.stage("06-integrate-adapters", "mix")
            self.parallel(
                [("07-B-" + name, "evaluate-b", name) for name in study_v2.EVALUATED]
            )
            self.parallel(
                [("08-A-" + name, "evaluate-a", name) for name in study_v2.ROUTED]
            )
            selection = self.stage("09-B-selection", "select")
            result = self.stage(
                "10-C-use-recovery", "confirm", selection["selection_file_sha256"]
            )
            final = {
                "status": "COMPLETE_DEVELOPMENT",
                "result": result,
                "started_at_ns": started,
                "completed_at_ns": time.time_ns(),
                "source_digest": data.digest(self.source),
                "independent_scientific_qualification": "BLOCKED",
            }
        except Exception as error:
            final = {
                "status": "INCOMPLETE",
                "error": repr(error),
                "started_at_ns": started,
                "completed_at_ns": time.time_ns(),
                "automatic_retry": False,
                "source_digest": data.digest(self.source),
            }
            coding_sft.write_new(self.logs / "RESULT.json", final)
            raise
        coding_sft.write_new(self.logs / "RESULT.json", final)
        return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("root", "materials", "logs"):
        parser.add_argument("--" + field, required=True)
    options = parser.parse_args()
    print(
        json.dumps(Execution(options.root, options.materials, options.logs).run()),
        flush=True,
    )
