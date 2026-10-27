"""External trusted controller for a single source-bound Linux qualification."""

import os
from pathlib import Path
import secrets
import shutil
import sys

from .commands import Commands
from .contract import (
    ENTRY,
    PROXY,
    exact_keys,
    load_contract,
    reject_compiler_overrides,
    tool_identity,
)
from .docker_control import DockerControl, mount, process_command
from .files import (
    checksum,
    copy_file,
    describe,
    inventory,
    physical,
    read_json,
    verify,
    write_bytes,
    write_json,
)
from .inputs import source_clean
from .receipts import completion, junit
from .source import prepare_source
from .synapse import start_proxy, start_synapse


def bound(host_path, container_path):
    return {"path": str(container_path), **describe(host_path)}


def host_commands(args, output):
    seal = read_json(Path(args.host_tools), args.host_tools_sha256)
    exact_keys(seal, ("schema", "tools"), "controller tool seal")
    if seal["schema"] != "hepta.synapse.linux.host-tools.v1" or set(seal["tools"]) != {
        "python3",
        "git",
        "docker",
    }:
        raise ValueError("Host controller tool seal differs")
    for tool in seal["tools"].values():
        tool_identity(tool)
        verify(Path(tool["path"]), {key: tool[key] for key in ("bytes", "sha256")})
    if Path(sys.executable).resolve(strict=True) != Path(
        seal["tools"]["python3"]["path"]
    ):
        raise ValueError(
            "The actual controller Python differs from the prepared host tool seal"
        )
    socket = Path(args.docker_socket).resolve(strict=True)
    config = output / "empty-docker-config"
    config.mkdir(mode=0o700)
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "DOCKER_HOST": "unix://" + str(socket),
        "DOCKER_CONFIG": str(config),
    }
    return Commands(
        output / "controller-commands",
        seal["tools"],
        environment,
        Path(args.restored_root).resolve(),
    )


def fixture_manifest(source, build, ready, plan_dir, runtime_dir, build_dir):
    identities = {
        name: {key: item[key] for key in ("path", "bytes", "sha256")}
        for name, item in build["binaries"].items()
    }
    return {
        "schema_version": 1,
        "qualification_kind": "linux_exact",
        "scope": "native-linux-arm64",
        "source_root": source["source_root"],
        "candidate_sha": source["qualification_commit"],
        "candidate_tree_sha": source["qualification_tree"],
        "source_seal": bound(
            plan_dir / "SOURCE_SEAL.json", "/hepta-plan/SOURCE_SEAL.json"
        ),
        "builder_seal": bound(
            plan_dir / "BUILDER_SEAL.json", "/hepta-plan/BUILDER_SEAL.json"
        ),
        "build_result": bound(
            build_dir / "BUILD_RESULT.json", "/hepta-build/BUILD_RESULT.json"
        ),
        "build_inputs": bound(build_dir / "INPUTS.json", "/hepta-build/INPUTS.json"),
        "controller_snapshot": bound(
            plan_dir / "RUNTIME_CONTROLLER.json", "/hepta-plan/RUNTIME_CONTROLLER.json"
        ),
        "proxy_source": bound(
            plan_dir / "synapse-loopback-proxy.py",
            "/hepta-plan/synapse-loopback-proxy.py",
        ),
        "proxy_ready": bound(
            plan_dir / "PROXY_READY.json", "/hepta-plan/PROXY_READY.json"
        ),
        "binaries": identities,
        "fixture_root": "/hepta-runtime",
        "credentials_directory": "/hepta-runtime/credentials",
        "runtime_tmp_root": "/hepta-runtime/runtime",
        "process_identity_ledger": "/hepta-runtime/process-identity-ledger.json",
        "homeserver": f"http://127.0.0.1:{ready['port']}",
    }


def run(args):
    output = physical(Path(args.output).absolute())
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    record = {
        "schema": "hepta.synapse.linux.qualification.v1",
        "status": "started",
        "scope": "native-linux-arm64",
        "macos_qualification": False,
        "windows_qualification": False,
        "production_approval": False,
        "promotion_allowed": False,
        "commands": [],
    }
    write_json(output / "STARTED.json", record)
    control, commands = None, None
    try:
        reject_compiler_overrides(os.environ)
        contract = load_contract(Path(args.builder_seal), args.builder_seal_sha256)
        commands = host_commands(args, output)
        builder_identity = contract["image"]
        if "archive" in builder_identity:
            verify(Path(args.builder_archive), builder_identity["archive"])
        control = DockerControl(commands, output, contract, args.docker_socket)
        control.preflight()
        bundle = Path(args.tool_bundle).resolve(strict=True)
        if inventory(bundle) != contract["tool_bundle"]["files"]:
            raise ValueError(
                "External builder tool bundle differs, including extra files"
            )
        source_evidence = output / "source"
        source_evidence.mkdir(mode=0o700)
        source = prepare_source(
            Path(args.restored_root).resolve(),
            Path(args.producer).resolve(),
            args.producer_result_sha256,
            args.source_commit,
            Path(args.worktree).absolute(),
            source_evidence,
            commands,
        )
        checkout = Path(source["source_root"])
        plan_dir, build_dir, runtime_dir = (
            output / "plan",
            output / "build",
            output / "runtime",
        )
        for directory in (plan_dir, build_dir, runtime_dir):
            directory.mkdir(mode=0o700)
        copy_file(Path(args.builder_seal), plan_dir / "BUILDER_SEAL.json")
        copy_file(source_evidence / "SOURCE_SEAL.json", plan_dir / "SOURCE_SEAL.json")
        verify(
            Path(args.seed_ledger),
            {
                "bytes": Path(args.seed_ledger).stat().st_size,
                "sha256": args.seed_ledger_sha256,
            },
        )
        copy_file(Path(args.seed_ledger), plan_dir / "SEED_LEDGER.json")
        seed_identity = read_json(plan_dir / "SEED_LEDGER.json")
        if (
            seed_identity["schema"] != "hepta.synapse.linux.seed.v1"
            or seed_identity["producer_result_sha256"]
            != source["producer_result_sha256"]
            or seed_identity["candidate_tree"] != source["candidate_tree"]
            or seed_identity["cargo_lock"]
            != source["bound_files"]["codex-rs/Cargo.lock"]
        ):
            raise ValueError(
                "Offline dependency seed was prepared from a different producer/candidate/lock"
            )
        plan = {
            "schema": "hepta.synapse.linux.build-plan.v1",
            "builder_seal": bound(
                plan_dir / "BUILDER_SEAL.json", "/hepta-plan/BUILDER_SEAL.json"
            ),
            "source_seal": bound(
                plan_dir / "SOURCE_SEAL.json", "/hepta-plan/SOURCE_SEAL.json"
            ),
            "seed_ledger": bound(
                plan_dir / "SEED_LEDGER.json", "/hepta-plan/SEED_LEDGER.json"
            ),
        }
        write_json(plan_dir / "BUILD_PLAN.json", plan)
        shared = [
            (checkout, str(checkout), False),
            (
                Path(source["private_git_authority"]),
                source["private_git_authority"],
                False,
            ),
            (
                Path(source["original_object_directory"]),
                source["original_object_directory"],
                False,
            ),
            (plan_dir, "/hepta-plan", False),
            (bundle, "/hepta-tools", False),
        ]
        build_mounts = [
            *shared,
            (Path(args.cargo_seed).resolve(), "/hepta-seed", False),
            (build_dir, "/hepta-build", True),
        ]
        options = [
            argument
            for src, dest, rw in build_mounts
            for argument in mount(src, dest, writable=rw)
        ]
        executable = checkout / ENTRY
        builder = control.isolated(
            "build",
            options,
            process_command(
                contract,
                executable,
                [
                    "build-inside",
                    "--plan",
                    "/hepta-plan/BUILD_PLAN.json",
                    "--plan-sha256",
                    checksum(plan_dir / "BUILD_PLAN.json"),
                ],
            ),
        )
        control.check_isolated(
            builder,
            expected_running=False,
            expected_mounts={(str(src), dest, rw) for src, dest, rw in build_mounts},
        )
        control.start(builder, attach=True)
        built_state = control.check_isolated(
            builder,
            expected_running=False,
            expected_mounts={(str(src), dest, rw) for src, dest, rw in build_mounts},
        )
        build = read_json(build_dir / "BUILD_RESULT.json")
        if (
            built_state["State"]["ExitCode"] != 0
            or build["status"] != "built_not_executed"
        ):
            raise ValueError("Actual offline cold build did not complete")
        for item in build["binaries"].values():
            verify(
                build_dir / Path(item["path"]).relative_to("/hepta-build"),
                {key: item[key] for key in ("bytes", "sha256")},
            )
        # This container has exited. Only reproducible dependency/tool aliases
        # are discarded; the complete binary/build/log evidence remains.
        for name in ("cargo-home", "home", "tmp", "closed-bin"):
            shutil.rmtree(build_dir / name)
        write_json(
            build_dir / "CACHE_RECLAMATION.json",
            {
                "container_exited": True,
                "removed_regenerable_only": ["cargo-home", "home", "tmp", "closed-bin"],
                "actual_binaries_preserved_and_reopened": True,
                "cold_targets_deleted_inside_after_readback": True,
            },
        )
        for name in ("credentials", "runtime", "completion"):
            (runtime_dir / name).mkdir(mode=0o700)
        write_json(
            runtime_dir / "process-identity-ledger.json",
            {
                "schema_version": 1,
                "active": [],
                "history": [],
                "explicit_shutdown_completed": False,
                "all_historical_pids_absent": False,
            },
        )
        runtime_mounts = [
            *shared,
            (build_dir, "/hepta-build", False),
            (runtime_dir, "/hepta-runtime", True),
        ]
        options = [
            argument
            for src, dest, rw in runtime_mounts
            for argument in mount(src, dest, writable=rw)
        ]
        runtime = control.isolated(
            "runtime", options, process_command(contract, executable, ["idle"])
        )
        control.start(runtime)
        expected_runtime_mounts = {
            (str(src), dest, rw) for src, dest, rw in runtime_mounts
        }
        control.check_isolated(
            runtime, expected_running=True, expected_mounts=expected_runtime_mounts
        )
        server, synapse = start_synapse(control, runtime_dir / "credentials")
        control_binary = output / "privileged-transport-tool"
        copy_file(
            Path(commands.tools["docker"]["path"]),
            control_binary / "docker",
            executable=True,
        )
        proxy, ready = start_proxy(
            control, runtime, server, checkout, bundle, control_binary, output
        )
        copy_file(checkout / PROXY, plan_dir / "synapse-loopback-proxy.py")
        copy_file(output / "proxy/ready.json", plan_dir / "PROXY_READY.json")
        snapshot = {
            "schema": "hepta.synapse.linux.runtime-controller.v1",
            "scope": "native-linux-arm64",
            "runtime_gid": os.getgid(),
            "runtime_inspect": control.check_isolated(
                runtime, expected_running=True, expected_mounts=expected_runtime_mounts
            ),
            "build_inspect": built_state,
            "proxy_inspect": control.inspect(proxy, "proxy-before-test"),
            "synapse": synapse,
            "proxy_has_broad_docker_authority": True,
            "business_has_docker_authority": False,
            "macos_qualification": False,
        }
        write_json(plan_dir / "RUNTIME_CONTROLLER.json", snapshot)
        write_json(
            plan_dir / "FIXTURE_MANIFEST.json",
            fixture_manifest(source, build, ready, plan_dir, runtime_dir, build_dir),
        )
        nonce = secrets.token_hex(32)
        write_bytes(runtime_dir / "credentials/completion-nonce", nonce.encode())
        run_plan = {
            "schema": "hepta.synapse.linux.run-plan.v1",
            "builder_seal": plan["builder_seal"],
            "source_seal": plan["source_seal"],
            "build_result": bound(
                build_dir / "BUILD_RESULT.json", "/hepta-build/BUILD_RESULT.json"
            ),
            "fixture_manifest": bound(
                plan_dir / "FIXTURE_MANIFEST.json", "/hepta-plan/FIXTURE_MANIFEST.json"
            ),
        }
        write_json(plan_dir / "RUN_PLAN.json", run_plan)
        commands.run(
            "docker",
            [
                "exec",
                runtime,
                *process_command(
                    contract,
                    executable,
                    [
                        "run-inside",
                        "--plan",
                        "/hepta-plan/RUN_PLAN.json",
                        "--plan-sha256",
                        checksum(plan_dir / "RUN_PLAN.json"),
                    ],
                ),
            ],
            label="actual-linux-business-qualification",
        )
        execution = read_json(runtime_dir / "EXECUTION_RESULT.json")
        if execution["status"] != "business_test_passed_pending_external_teardown":
            raise ValueError(
                "Actual just test did not produce a complete runtime receipt"
            )
        record["completion"] = completion(
            runtime_dir / "completion/completion.json", nonce, source, runtime_dir
        )
        record["junit"] = junit(runtime_dir / "nextest-store/linux-synapse/junit.xml")
        control.check_isolated(
            runtime, expected_running=True, expected_mounts=expected_runtime_mounts
        )
        control.inspect(proxy, "proxy-after-test")
        commands.run(
            "docker",
            ["top", runtime, "-eo", "pid,args"],
            label="runtime-processes-after-test",
        )
        verification = Commands(
            output / "final-source-commands",
            commands.tools,
            commands.environment,
            checkout,
        )
        source_clean(verification, source)
        if (
            commands.text(
                "git", ["rev-parse", "HEAD"], label="original-restore-head-after-test"
            )
            != args.source_commit
        ):
            raise ValueError(
                "The original restore checkout HEAD changed during qualification"
            )
        for item in build["binaries"].values():
            verify(
                build_dir / Path(item["path"]).relative_to("/hepta-build"),
                {key: item[key] for key in ("bytes", "sha256")},
            )
        record.update(
            status="business_passed_pending_teardown",
            original_restore_head_unchanged=True,
            source_seal=describe(source_evidence / "SOURCE_SEAL.json"),
            actual_binaries_unchanged=True,
        )
    except BaseException as error:
        record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        if control is not None:
            teardown = control.cleanup()
            if (
                record["status"] == "business_passed_pending_teardown"
                and teardown["all_owned_resources_absent"]
            ):
                record["status"] = "qualified_native_linux_arm64_only"
            elif not teardown["all_owned_resources_absent"]:
                record.update(status="failed", teardown_failed=True)
        credentials = output / "runtime/credentials"
        if credentials.exists():
            names = sorted(item.name for item in credentials.iterdir())
            shutil.rmtree(credentials)
            record["unconsumed_test_credentials_scrubbed_after_failure"] = names
        if commands is not None:
            record["commands"] = commands.records
        write_json(output / "RESULT.json", record)
    if record["status"] != "qualified_native_linux_arm64_only":
        raise RuntimeError(
            "Linux qualification did not complete every runtime and teardown gate"
        )
    return record
