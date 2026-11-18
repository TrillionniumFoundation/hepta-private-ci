"""Execute pinned, trusted development tools and an independent pinned oracle.

All arms share source bytes, tools, oracle and opportunity ceilings. The arm name
is never sent to a tool. Every scheduled attempt gets a fresh capsule copy and
retained stdout/stderr. This is a Linux process owner, not an OS sandbox, a model
agent, authenticated source custody, or a complete-cost measurement system.
"""

from contextlib import suppress
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from .research_trial import TrialLedger, canonical, sha256, validate_plan
from .task_observation import TaskLedger


def write_original(path, value):
    raw = (canonical(value) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "path": str(Path(path).absolute()),
        "sha256": sha256(raw),
        "bytes": len(raw),
    }


def clock_identity():
    path = Path("/proc/sys/kernel/random/boot_id")
    if os.name != "posix" or not path.is_file():
        raise RuntimeError(
            "this runner requires Linux boot-bound monotonic observations"
        )
    return "linux-boot:" + path.read_text().strip()


def verify_files(root, files):
    total = 0
    for name, expected in files.items():
        path = root / name
        if path.resolve(strict=True) != path or not path.is_file():
            raise ValueError(
                "capsule file is missing, nonregular or symlinked: " + name
            )
        raw = path.read_bytes()
        total += len(raw)
        if total > 64 * 1024 * 1024 or sha256(raw) != expected:
            raise ValueError(
                "capsule byte mismatch or aggregate exceeds 64 MiB: " + name
            )


def output_inventory(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("output originals must not be symlinks")
        if path.is_file():
            raw = path.read_bytes()
            files[str(path.relative_to(root))] = {
                "bytes": len(raw),
                "sha256": sha256(raw),
            }
    return files


def command(argv, cwd, directory, timeout):
    """Retain whole streams; timeout never proves an external effect absent."""
    directory.mkdir()
    dispatch = write_original(
        directory / "STARTED.json",
        {
            "argv": argv,
            "cwd": str(cwd),
            "timeout_seconds": timeout,
            "start_monotonic_ns": time.perf_counter_ns(),
        },
    )
    started = time.perf_counter_ns()
    with (
        (directory / "stdout").open("xb") as stdout,
        (directory / "stderr").open("xb") as stderr,
    ):
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
            env={
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "TZ": "UTC",
            },
        )
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except BaseException:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            raise
        finally:
            stdout.flush()
            stderr.flush()
            os.fsync(stdout.fileno())
            os.fsync(stderr.fileno())
    result = {
        "pid": process.pid,
        "dispatch": dispatch,
        "returncode": process.returncode,
        "timed_out": timed_out,
        "wall_ns": time.perf_counter_ns() - started,
        "streams": {
            n: {
                "sha256": sha256((directory / n).read_bytes()),
                "bytes": (directory / n).stat().st_size,
            }
            for n in ("stdout", "stderr")
        },
        "external_effects": None,
        "process_tree_complete": None,
        "cost_scope": "wait for the launched process; detached descendants and full process-tree cost remain unknown",
    }
    write_original(directory / "PROCESS.json", result)
    return result


class DevelopmentTrial:
    """Run only frozen development attempts; pending attempts require review."""

    @classmethod
    def create(cls, root, *, plan, capsule_root):
        validate_plan(plan)
        source, root = Path(capsule_root).resolve(strict=True), Path(root).absolute()
        verify_files(source, plan["files"])
        if (
            sha256(Path(plan["runtime"]["executable"]).read_bytes())
            != plan["runtime"]["sha256"]
        ):
            raise ValueError("interpreter bytes differ from the frozen runtime")
        clock = clock_identity()
        root.mkdir(parents=True, exist_ok=False)
        frozen = root / "capsule"
        frozen.mkdir()
        for name in plan["files"]:
            target = frozen / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, target)
        verify_files(frozen, plan["files"])
        ledger = TrialLedger.create(root / "trial.sqlite", plan)
        write_original(root / "PLAN.json", plan)
        write_original(root / "CLOCK.json", {"clock_id": clock})
        TaskLedger.create(
            root / "tasks.sqlite",
            candidate_sha256=ledger.plan_sha256,
            clock_id=clock,
            tasks=[
                {
                    "task_id": a["attempt_id"],
                    "cell": "development-runner",
                    "phase": "development",
                    "arm": a["arm"],
                    "source_group": canonical(
                        plan["tasks"][a["task_id"]]["source_groups"]
                    ),
                }
                for a in plan["schedule"]
            ],
        )
        (root / "attempts").mkdir()
        return cls(root, expected_plan_sha256=ledger.plan_sha256)

    def __init__(self, root, *, expected_plan_sha256):
        self.root = Path(root).resolve(strict=True)
        self.ledger = TrialLedger(
            self.root / "trial.sqlite", expected_plan_sha256=expected_plan_sha256
        )
        self.plan = self.ledger.plan
        clock = json.loads((self.root / "CLOCK.json").read_text())["clock_id"]
        if clock != clock_identity():
            raise ValueError("boot changed; old durations cannot use the new clock")
        self.tasks = TaskLedger(
            self.root / "tasks.sqlite",
            candidate_sha256=expected_plan_sha256,
            clock_id=clock,
        )

    def execute(self, attempt_id):
        item = self.ledger.claim(attempt_id)
        self.tasks.accept(attempt_id)
        directory = self.root / "attempts" / attempt_id
        directory.mkdir()
        work, output = directory / "work", directory / "output"
        stage = "capsule-copy"
        try:
            verify_files(self.root / "capsule", self.plan["files"])
            work.mkdir()
            for name in self.plan["files"]:
                target = work / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.root / "capsule" / name, target)
            verify_files(work, self.plan["files"])
            runtime = self.plan["runtime"]
            if sha256(Path(runtime["executable"]).read_bytes()) != runtime["sha256"]:
                raise ValueError("interpreter bytes changed before dispatch")
            output.mkdir()
            substitutions = {
                "{python}": runtime["executable"],
                "{output}": str(output),
                "{task_id}": item["task_id"],
                "{tool_id}": item["tool_id"],
            }
            self.tasks.start(attempt_id)
            processes, oracle = {}, None
            for stage, template in (
                ("tool", self.plan["tools"][item["tool_id"]]),
                ("oracle", self.plan["oracle"]),
            ):
                verify_files(work, self.plan["files"])
                verify_files(self.root / "capsule", self.plan["files"])
                if (
                    sha256(Path(runtime["executable"]).read_bytes())
                    != runtime["sha256"]
                ):
                    raise ValueError("interpreter bytes changed before stage dispatch")
                stage_work = work
                if stage == "oracle":
                    # A tool cannot replace the oracle entry in its own work copy.
                    stage_work = directory / "oracle-work"
                    stage_work.mkdir()
                    for name in self.plan["files"]:
                        target = stage_work / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(self.root / "capsule" / name, target)
                    verify_files(stage_work, self.plan["files"])
                argv = [substitutions.get(arg, arg) for arg in template]
                result = command(
                    argv, stage_work, directory / stage, self.plan["timeout_seconds"]
                )
                processes[stage] = result
                verify_files(stage_work, self.plan["files"])
                if result["timed_out"] or result["returncode"] != 0:
                    break
            verify_files(work, self.plan["files"])
            verify_files(self.root / "capsule", self.plan["files"])
            if "oracle" in processes and processes["oracle"]["returncode"] == 0:
                raw = (directory / "oracle" / "stdout").read_bytes()
                if len(raw) > 1024 * 1024:
                    raise ValueError("oracle receipt exceeds 1 MiB")
                oracle = json.loads(raw)
                if (
                    not isinstance(oracle, dict)
                    or type(oracle.get("success")) is not bool
                ):
                    raise ValueError("oracle must report an explicit boolean success")
            outcome = (
                "unknown"
                if any(p["timed_out"] for p in processes.values())
                else "success"
                if oracle and oracle["success"]
                else "failed"
            )
            final = {
                "schema": "hepta.development-attempt.v1",
                "plan_sha256": self.ledger.plan_sha256,
                "attempt": item,
                "declared_source_groups": self.plan["tasks"][item["task_id"]][
                    "source_groups"
                ],
                "phase": "development",
                "outcome": outcome,
                "processes": processes,
                "oracle": oracle,
                "output_files": output_inventory(output),
                "external_effects": None,
                "research_accepted": None,
                "cell_generated_repair": False,
            }
            binding = write_original(directory / "FINAL.json", final)
            self.tasks.finish(attempt_id, binding["path"], outcome=outcome)
            self.ledger.settle(attempt_id, binding)
            return final
        except BaseException as error:
            write_original(
                directory / "INTERRUPTED.json",
                {
                    "stage": stage,
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "automatic_retry": False,
                    "effect_state": "unknown",
                },
            )
            with suppress(ValueError):
                self.tasks.interrupted(attempt_id, error)
            raise

    def report(self):
        """Keep planned/missing attempts and historical groups without inflating N."""
        report, observations = self.ledger.report(), self.tasks.report()
        for attempt_id, attempt in report["attempts"].items():
            if attempt["state"] != "terminal":
                continue
            directory = self.root / "attempts" / attempt_id
            raw = (directory / "FINAL.json").read_bytes()
            binding = attempt["receipt"]
            if binding != {
                "path": str(directory / "FINAL.json"),
                "sha256": sha256(raw),
                "bytes": len(raw),
            }:
                raise ValueError("terminal ledger binding differs from the original")
            final = json.loads(raw)
            if output_inventory(directory / "output") != final["output_files"]:
                raise ValueError("retained tool outputs changed")
            for stage, process in final["processes"].items():
                if (directory / stage / "PROCESS.json").read_bytes() != (
                    canonical(process) + "\n"
                ).encode():
                    raise ValueError("retained process receipt changed")
                dispatch = directory / stage / "STARTED.json"
                data = dispatch.read_bytes()
                if process["dispatch"] != {
                    "path": str(dispatch),
                    "sha256": sha256(data),
                    "bytes": len(data),
                }:
                    raise ValueError("retained dispatch receipt changed")
                for stream, expected in process["streams"].items():
                    data = (directory / stage / stream).read_bytes()
                    if {"bytes": len(data), "sha256": sha256(data)} != expected:
                        raise ValueError("retained process stream changed")
        return {
            "schema": "hepta.development-trial-report.v1",
            "trial": report,
            "task_observation": observations,
            "declared_source_groups": sorted(
                {
                    g
                    for task in self.plan["tasks"].values()
                    for g in task["source_groups"]
                }
            ),
            "authenticated_independent_source_groups": None,
            "fresh_confirmation": 0,
            "research_execution": None,
            "research_result": None,
        }
