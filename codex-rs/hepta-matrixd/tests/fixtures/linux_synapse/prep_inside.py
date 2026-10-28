"""Actual ARM64 tool probing and online seed fetch, before offline qualification."""

import json
import os
from pathlib import Path
import platform
import shutil

from .commands import Commands
from .dependencies import SEED_SCHEMA, dependency_inventory
from .contract import TARGET, TOOLS, load_contract, verify_tools
from .files import describe, inventory, read_json, write_json
from .inputs import (
    build_environment,
    sealed_path_environment,
    source_clean,
)


def probe_tools(output):
    if (platform.system(), platform.machine()) != ("Linux", "aarch64"):
        raise ValueError("Tool materialization must execute on native ARM64")
    environment = {
        "PATH": "/hepta-tools:/usr/local/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "RUSTUP_HOME": "/usr/local/rustup",
        "CARGO_HOME": "/usr/local/cargo",
    }
    tools = {}
    bootstrap_commands = None
    for name in sorted(TOOLS):
        if name in {"rustc", "cargo", "rustdoc"}:
            rustup = Path(shutil.which("rustup", path=environment["PATH"])).resolve(
                strict=True
            )
            if bootstrap_commands is None:
                bootstrap_commands = Commands(
                    output / "bootstrap-tool-commands",
                    {"rustup": {"path": str(rustup), **describe(rustup)}},
                    environment,
                    Path("/"),
                )
            actual = bootstrap_commands.text(
                "rustup", ["which", name], label="actual-" + name
            )
            path = Path(actual).resolve(strict=True)
        else:
            found = shutil.which(name, path=environment["PATH"])
            if not found:
                raise ValueError(
                    f"Prepared builder still lacks required actual tool: {name}"
                )
            path = Path(found).resolve(strict=True)
        tools[name] = {"path": str(path), **describe(path)}
    commands = Commands(output / "probe-commands", tools, environment, Path("/"))
    versions = {}
    for name, arguments in (
        ("rustc", ["-Vv"]),
        ("cargo", ["-V"]),
        ("rustdoc", ["-V"]),
        ("cargo-nextest", ["nextest", "--version"]),
        ("just", ["--version"]),
        ("dotslash", ["--version"]),
    ):
        versions[name] = commands.text(name, arguments, label=name + "-version")
    if (
        "release: 1.96.0" not in versions["rustc"].splitlines()
        or "host: " + TARGET not in versions["rustc"].splitlines()
        or "commit-hash: ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96"
        not in versions["rustc"].splitlines()
    ):
        raise ValueError(
            "Materialized Rust compiler differs from the fixed official release"
        )
    if (
        versions["just"] != "just 1.51.0"
        or versions["cargo-nextest"].split()[1] != "0.9.103"
        or versions["dotslash"].lower().split() != ["dotslash", "0.5.9"]
    ):
        raise ValueError(
            "Actual official tool version differs from its fixed release asset"
        )
    native = {
        "bwrap_version": commands.text(
            "bwrap", ["--version"], label="actual-bwrap-version"
        ),
        "libcap_version": commands.text(
            "pkg-config", ["--modversion", "libcap"], label="actual-libcap-version"
        ),
        "libcap_link_flags": commands.text(
            "pkg-config",
            ["--cflags", "--libs", "libcap"],
            label="actual-libcap-link-flags",
        ),
    }
    help_text = commands.text("bwrap", ["--help"], label="actual-bwrap-capabilities")
    if not all(flag in help_text for flag in ("--as-pid-1", "--perms")):
        raise ValueError(
            "Prepared system bubblewrap lacks the original launcher's required capabilities"
        )
    native["system_launcher_required_capabilities"] = ["--as-pid-1", "--perms"]
    native["qualification_sandbox_executed"] = False
    result = {
        "schema": "hepta.synapse.linux.tool-probe.v1",
        "native_architecture": "aarch64",
        "tools": tools,
        "versions": versions,
        "tool_bundle": inventory(Path("/hepta-tools")),
        "linux_native_prerequisites": native,
        "commands": commands.records,
        "qualification_executed": False,
    }
    write_json(output / "TOOL_PROBE.json", result)
    return result


def fetch_seed(plan_path, plan_sha):
    plan = read_json(plan_path, plan_sha)
    contract = load_contract(
        Path(plan["builder_seal"]["path"]), plan["builder_seal"]["sha256"]
    )
    source = read_json(Path(plan["source_seal"]["path"]), plan["source_seal"]["sha256"])
    work = Path("/hepta-prefetch")
    for name in ("home", "tmp", "cargo-home"):
        (work / name).mkdir(mode=0o700, exist_ok=False)
    environment = build_environment(
        contract, work, sealed_path_environment(contract, work / "closed-bin")
    )
    tools = verify_tools(contract)
    commands = Commands(
        work / "commands", tools, environment, Path(source["source_root"])
    )
    record = {
        "schema": "hepta.synapse.linux.prefetch.v1",
        "status": "started",
        "network_scope": "explicit online preparation only; no build or tests",
        "commands": [],
        "producer_result_sha256": source["producer_result_sha256"],
        "candidate_tree": source["candidate_tree"],
    }
    write_json(work / "PREFETCH_STARTED.json", record)
    try:
        source_clean(commands, source)
        # Full locked fetch also supplies manifests needed by full offline
        # Cargo metadata. It is not restricted to a potentially incomplete
        # native download subset, and does not execute crate build scripts.
        commands.run(
            "cargo",
            [
                "fetch",
                "--manifest-path",
                str(Path(source["source_root"]) / "codex-rs/Cargo.toml"),
                "--locked",
            ],
            label="online-complete-locked-seed",
            environment={"CARGO_NET_OFFLINE": "false"},
        )
        source_clean(commands, source)
        files = dependency_inventory(work / "cargo-home")
        write_json(
            work / "SEED_LEDGER.json",
            {
                "schema": SEED_SCHEMA,
                "producer_result_sha256": source["producer_result_sha256"],
                "candidate_tree": source["candidate_tree"],
                "cargo_lock": source["bound_files"]["codex-rs/Cargo.lock"],
                "files": files,
                "excluded_mutable_bookkeeping_is_not_source": True,
            },
        )
        record.update(
            status="prepared_not_qualified",
            seed_files=len(files),
            seed_payload_bytes=sum(item["bytes"] for item in files.values() if item["kind"] == "regular"),
            seed_symlink_count=sum(item["kind"] == "symlink" for item in files.values()),
            seed_ledger=describe(work / "SEED_LEDGER.json"),
            source_clean=True,
        )
    except BaseException as error:
        record.update(
            status="failed", error_type=type(error).__name__, error=str(error)
        )
        raise
    finally:
        record["commands"] = commands.records
        write_json(work / "PREFETCH_RESULT.json", record)
    return record
