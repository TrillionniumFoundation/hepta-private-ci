"""Registered execution07 process boundary around unchanged science entrypoints."""

import argparse
import importlib
import os
from pathlib import Path
import resource
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery07.process import (  # noqa: E402
    EPISODE,
    PREFIX,
    Guard,
    Terminated,
    adapter,
    load_config,
    read,
    require,
    write,
)

SCIENCE = {PREFIX + name for name in ("run_v2", "architecture_run_v2", "endpoint_v2")}
ANALYSIS, FINALIZER = PREFIX + "analysis_launch_v2", PREFIX + "finalize_v2"


def command(config, config_desc, token, module, flags):
    return [
        config["python"],
        "-B",
        str(
            Path(config["source_root"])
            / "operational/parameter_field_recovery07/worker.py"
        ),
        "--config",
        config_desc["path"],
        "--expected-config-sha256",
        config_desc["sha256"],
        "--token",
        token,
        "--original-module",
        module,
        "--",
        *flags,
    ]


def validate_request(config, token, module, flags, parent_pid=None):
    require(module in SCIENCE | {ANALYSIS, FINALIZER}, "Unregistered worker module")
    require(
        not any(
            flag in flags for flag in ("--resume-admission", "--recover-zero-work")
        ),
        "Execution07 is fresh and cannot resume science",
    )
    if module in SCIENCE:
        active = read(config["active_queue"])
        require(
            active["jobs"][-1]["id"] == token
            and active["jobs"][-1]["argv"] == ["-B", "-m", module, *flags],
            "Worker request differs from the active registered job",
        )
        return
    stage = "analysis" if module == ANALYSIS else "finalizer"
    result = read(
        Path(config["ops_root"]) / "registrations" / stage / "REGISTRATION.json"
    )
    frozen = result["files"][
        "ANALYSIS_SOURCE_FREEZE.json"
        if stage == "analysis"
        else "FINALIZER_SOURCE_FREEZE.json"
    ]
    core = importlib.import_module(PREFIX + "launch_v2")
    # The original queue parser does not accept the private analysis --child flag.
    values, offset = {}, 0
    while offset < len(flags):
        key = flags[offset]
        require(
            key.startswith("--") and key not in values,
            "Duplicate or malformed original worker flag",
        )
        if key in ("--execute", "--child"):
            values[key], offset = True, offset + 1
        else:
            require(offset + 1 < len(flags), "Missing original flag value")
            values[key], offset = flags[offset + 1], offset + 2
    amend = config["descriptors"]["amendment"]
    required = {
        "--root": config["raw_root"],
        "--freeze": frozen["path"],
        "--amendment": amend["path"],
        "--amendment-sha256": amend["sha256"],
    }
    if stage == "analysis":
        freeze = read(frozen)
        inputs = result["files"]["REPORT_INPUTS.json"]
        required.update(
            {
                "--inputs": inputs["path"],
                "--expected-sha256": inputs["sha256"],
                "--output": str(Path(config["raw_root"]) / freeze["output_relative"]),
                "--freeze-sha256": frozen["sha256"],
            }
        )
        if token == "ANALYSIS_CHILD":
            required.update(
                {
                    "--child": True,
                    "--parent-pid": str(
                        os.getppid() if parent_pid is None else parent_pid
                    ),
                }
            )
        else:
            require(token == "ANALYSIS_PARENT", "Wrong analysis wrapper identity")
    else:
        require(token == "FINALIZER", "Wrong finalizer wrapper identity")
        required.update({"--execute": True, "--evidence-id": "verification07"})
    require(
        values == required and core.digest(frozen["path"]) == frozen["sha256"],
        "Worker request differs from exact phase registration",
    )


class AnalysisSpawns:
    def __init__(self, original, config, config_desc):
        self.original, self.config, self.config_desc = original, config, config_desc

    def __getattr__(self, name):
        return getattr(self.original, name)

    def Popen(self, argv, *args, **kwargs):
        require(
            argv[:4] == [self.config["python"], "-B", "-m", ANALYSIS]
            and Path(kwargs.get("cwd")).resolve() == Path(self.config["source_root"]),
            "Unexpected original analysis child launch",
        )
        flags = argv[4:]
        validate_request(
            self.config, "ANALYSIS_CHILD", ANALYSIS, flags, parent_pid=os.getpid()
        )
        effective = command(
            self.config, self.config_desc, "ANALYSIS_CHILD", ANALYSIS, flags
        )
        kwargs["cwd"] = self.config["empty_cwd"]
        return self.original.Popen(effective, *args, **kwargs)


def dispatch(config, config_desc, token, module_name, flags, directory):
    module = importlib.import_module(module_name)
    old_argv = sys.argv
    sys.argv = [module_name, *flags]
    try:
        if module_name == ANALYSIS:
            context = importlib.import_module(
                "operational.parameter_field_recovery07.analysis_worker"
            )
            if token == "ANALYSIS_PARENT":
                owned = importlib.import_module(
                    "operational.parameter_field_recovery06.owned_children"
                )
                original = module.subprocess
                module.subprocess = AnalysisSpawns(original, config, config_desc)
                try:
                    return owned.run_controller(
                        module,
                        lambda: context.run(module, flags, config),
                        directory / "owned_children",
                        binding={
                            "execution_episode": EPISODE,
                            "pipeline_config": config_desc,
                            "component_schema_is_implementation_version_not_execution_episode": True,
                        },
                    )
                finally:
                    module.subprocess = original
            return context.run(module, flags, config)
        return module.main()
    finally:
        sys.argv = old_argv


def main():
    parser = argparse.ArgumentParser()
    for key in ("config", "expected-config-sha256", "token", "original-module"):
        parser.add_argument("--" + key, required=True)
    parser.add_argument("flags", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    require(args.flags[:1] == ["--"], "Explicit original argument separator required")
    flags = args.flags[1:]
    config, config_desc = load_config(args.config, args.expected_config_sha256)
    require(
        Path.cwd() == Path(config["empty_cwd"]),
        "Worker did not start in its registered empty cwd",
    )
    guard = Guard(config, config_desc)
    guard.verify()
    validate_request(config, args.token, args.original_module, flags)
    directory = Path(config["ops_root"]) / "wrapper_runs" / args.token
    directory.mkdir(parents=True, exist_ok=False)
    started, cpu = time.monotonic(), time.process_time()
    write(
        directory / "START.json",
        {
            "schema": "hepta.execution07.worker-start.1",
            "execution_episode": EPISODE,
            "pipeline_config": config_desc,
            "supervisor_policy": guard.policy_desc,
            "identity": guard.owned.proc_identity(os.getpid()),
            "original_module": args.original_module,
            "original_flags": flags,
            "effective_cwd": str(Path.cwd()),
            "started_unix": time.time(),
        },
    )

    def terminated(signum, frame):
        raise Terminated("Execution07 worker terminated with signal " + str(signum))

    signal.signal(signal.SIGTERM, terminated)
    try:
        with adapter(config, guard, args.token):
            try:
                result = dispatch(
                    config,
                    config_desc,
                    args.token,
                    args.original_module,
                    flags,
                    directory,
                )
                require(result in (None, 0), "Original entrypoint returned a failure")
            except SystemExit as status:
                require(
                    status.code in (None, 0),
                    "Original entrypoint exited with code " + str(status.code),
                )
        guard.verify()
        require(
            not any(Path(config["empty_cwd"]).iterdir()),
            "Scientific worker wrote into its isolated cwd",
        )
        write(
            directory / "COMPLETE.json",
            {
                "schema": "hepta.execution07.worker-completion.1",
                "complete": True,
                "execution_episode": EPISODE,
                "pipeline_config": config_desc,
                "original_entrypoint_returned_successfully": True,
                "scientific_seal_verified_by_controller": False,
                "wall_seconds": time.monotonic() - started,
                "self_cpu_seconds": time.process_time() - cpu,
                "process_peak_rss_bytes": resource.getrusage(
                    resource.RUSAGE_SELF
                ).ru_maxrss
                * 1024,
                "cost_scope": "Wrapper self CPU interval; worker kernel wait4 remains authoritative and includes descendants.",
            },
        )
    except BaseException as error:
        write(
            directory / "FAILED.json",
            {
                "complete": False,
                "execution_episode": EPISODE,
                "error_type": type(error).__name__,
                "message": str(error)[:8192],
                "automatic_scientific_retry": False,
                "partial_evidence_preserved": True,
            },
        )
        raise


if __name__ == "__main__":
    main()
