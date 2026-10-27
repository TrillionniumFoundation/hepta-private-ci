"""Observe executed tools, immutable image inputs and the offline dependency seed."""

import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import time

from .commands import Commands
from .contract import IMAGE_ROOTS, TARGET, verify_tools
from .files import (
    checksum,
    copy_file,
    describe,
    inventory,
    physical,
    verify,
    write_json,
)


CACHE_BOOKKEEPING = {
    ".package-cache",
    ".package-cache-mutate",
    ".global-cache",
    ".global-cache-journal",
    ".global-cache-wal",
    ".global-cache-shm",
}


def source_clean(commands, seal):
    for expression, expected in (
        ("HEAD", seal["qualification_commit"]),
        ("HEAD^{tree}", seal["qualification_tree"]),
    ):
        if (
            commands.text("git", ["rev-parse", expression], label="source-identity")
            != expected
        ):
            raise ValueError("Qualification source identity changed")
    if commands.text(
        "git",
        ["status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"],
        label="source-clean",
    ):
        raise ValueError("Qualification source is not clean, including ignored files")
    for name, identity in seal["bound_files"].items():
        verify(commands.cwd / name, identity)


def sealed_path_environment(contract, root):
    root = physical(root)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, tool in contract["tools"].items():
        (root / name).symlink_to(tool["path"])
    return str(root)


def build_environment(contract, work, closed_path):
    tools = contract["tools"]
    return {
        "PATH": closed_path,
        "HOME": str(work / "home"),
        "TMPDIR": str(work / "tmp"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_OPTIONAL_LOCKS": "0",
        "CARGO_HOME": str(work / "cargo-home"),
        "CARGO_NET_OFFLINE": "true",
        "RUSTC": tools["rustc"]["path"],
        "RUSTDOC": tools["rustdoc"]["path"],
        "CARGO_BUILD_TARGET": TARGET,
        "CARGO_BUILD_JOBS": "2",
        "CARGO_INCREMENTAL": "0",
        "CARGO_PROFILE_DEV_DEBUG": "0",
        "CARGO_PROFILE_TEST_DEBUG": "0",
        "CARGO_TERM_COLOR": "never",
        "CC": tools["cc"]["path"],
        "CXX": tools["c++"]["path"],
        "AR": tools["ar"]["path"],
        "RANLIB": tools["ranlib"]["path"],
        "CMAKE": tools["cmake"]["path"],
        "MAKE": tools["make"]["path"],
        "PKG_CONFIG": tools["pkg-config"]["path"],
    }


def dependency_inventory(seed):
    entries = inventory(seed)
    forbidden = [
        name
        for name in entries
        if Path(name).parts[0] not in {"registry", "git", *CACHE_BOOKKEEPING}
    ]
    if forbidden:
        raise ValueError(
            "Offline seed may contain only registry/git and known Cargo bookkeeping; no credentials/config/bin"
        )
    return {
        name: {**identity, "mode": stat.S_IMODE((seed / name).stat().st_mode)}
        for name, identity in entries.items()
        if name not in CACHE_BOOKKEEPING
    }


def copy_seed(seed, destination, expected):
    seed, destination = physical(seed), physical(destination)
    before = dependency_inventory(seed)
    if before != expected or not before:
        raise ValueError(
            "Complete offline dependency seed differs from its frozen ledger"
        )
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name, item in before.items():
        copy_file(
            seed / name, destination / name, executable=bool(item["mode"] & 0o111)
        )
        os.chmod(destination / name, item["mode"])
    if (
        dependency_inventory(destination) != before
        or dependency_inventory(seed) != before
    ):
        raise ValueError(
            "Dependency seed copy failed complete write/readback verification"
        )
    return before


def image_file_tree(root):
    """Full actual Rust sysroot, including link identities and their resolved bytes."""
    root = Path(root).resolve(strict=True)
    if not str(root).startswith(IMAGE_ROOTS):
        raise ValueError("Sysroot escaped the immutable image")
    entries = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not str(target).startswith(IMAGE_ROOTS) or not target.is_file():
                raise ValueError(
                    "Sysroot contains a link outside immutable image files"
                )
            entries[name] = {
                "link": os.readlink(path),
                "resolved": str(target),
                **describe(target),
            }
        elif path.is_file():
            entries[name] = describe(path)
        elif not path.is_dir():
            raise ValueError("Sysroot contains a special file")
    if not entries:
        raise ValueError("Rust sysroot inventory is empty")
    return {"root": str(root), "files": entries}


def elf_closure(commands, executable, label):
    executable = Path(executable).resolve(strict=True)
    header = commands.text(
        "readelf", ["-h", str(executable)], label=label + "-elf-header"
    )
    if "AArch64" not in header or "ELF64" not in header:
        raise ValueError("Qualification executable is not a native ARM64 ELF64 binary")
    record, output = commands.run(
        "ldd", [str(executable)], label=label + "-elf-ldd", required=False
    )
    text = (
        output.read_text() + (commands.directory / record["stderr"]["path"]).read_text()
    )
    if "not found" in text:
        raise ValueError("ELF has unresolved runtime libraries")
    libraries = {}
    for token in re.findall(r"(?:=>\s*)?(/[^\s()]+)", text):
        path = Path(token).resolve(strict=True)
        if not str(path).startswith(IMAGE_ROOTS):
            raise ValueError("ELF runtime library escaped the immutable image")
        libraries[str(path)] = describe(path)
    if (
        not libraries
        and "statically linked" not in text
        and "not a dynamic executable" not in text
    ):
        raise ValueError(
            "ELF library discovery did not establish a dynamic or static closure"
        )
    return {
        "executable": {"path": str(executable), **describe(executable)},
        "libraries": libraries,
    }


def observe_inputs(contract, commands, output):
    started = time.monotonic()
    if (platform.system(), platform.machine()) != ("Linux", "aarch64"):
        raise ValueError("Only actual native Linux ARM64 execution can qualify")
    tools = verify_tools(contract)
    if inventory(Path("/hepta-tools")) != contract["tool_bundle"]["files"]:
        raise ValueError("Mounted tool bundle contains missing, changed or extra files")
    for socket in ("/var/run/docker.sock", "/run/docker.sock", "/hepta-control/docker"):
        if Path(socket).exists():
            raise ValueError(
                "Business/build container inherited Docker control authority"
            )
    rustc = commands.text("rustc", ["-Vv"], label="rustc-vv")
    for line in (
        "release: 1.96.0",
        "host: " + TARGET,
        "commit-hash: ac68faa20c58cbccd01ee7208bf3b6e93a7d7f96",
    ):
        if line not in rustc.splitlines():
            raise ValueError("Actual compiler release, commit or native host differs")
    cargo = commands.text("cargo", ["-V"], label="cargo-version")
    rustdoc = commands.text("rustdoc", ["-V"], label="rustdoc-version")
    nextest = commands.text(
        "cargo-nextest", ["nextest", "--version"], label="nextest-version"
    )
    if (
        not cargo.startswith("cargo 1.96.0 ")
        or not rustdoc.startswith("rustdoc 1.96.0 ")
        or not nextest.startswith("cargo-nextest 0.9.103 ")
    ):
        raise ValueError("Actual Cargo, rustdoc or nextest version differs")
    sysroot = commands.text("rustc", ["--print", "sysroot"], label="rust-sysroot")
    ledger = {
        "schema": "hepta.synapse.linux.inputs.v1",
        "tools": tools,
        "rustc_vv": rustc,
        "cargo_version": cargo,
        "rustdoc_version": rustdoc,
        "nextest_version": nextest,
        "rust_sysroot": image_file_tree(sysroot),
        "tool_elf_closures": {
            name: elf_closure(commands, tools[name]["path"], name)
            for name in (
                "rustc",
                "cargo",
                "rustdoc",
                "python3",
                "just",
                "cargo-nextest",
                "cc",
                "bwrap",
            )
        },
        "kernel": platform.uname()._asdict(),
        "uid": os.getuid(),
        "gid": os.getgid(),
        "groups": os.getgroups(),
        "proc_status": Path("/proc/self/status").read_text(),
        "mountinfo": Path("/proc/self/mountinfo").read_text(),
        "network_devices": Path("/proc/net/dev").read_text(),
        "memory": Path("/proc/meminfo").read_text(),
        "filesystem_free_bytes": shutil.disk_usage(output).free,
        "compiler_environment": commands.environment,
        "container_docker_authority_absent": True,
    }
    if ledger["uid"] == 0 or "CapEff:\t0000000000000000" not in ledger["proc_status"]:
        raise ValueError(
            "Build/business process must be non-root with no effective capabilities"
        )
    if "NoNewPrivs:\t1" not in ledger["proc_status"]:
        raise ValueError(
            "Build/business process lacks the observed no-new-privileges boundary"
        )
    network_names = {
        line.split(":", 1)[0].strip()
        for line in ledger["network_devices"].splitlines()
        if ":" in line
    }
    if network_names != {"lo"}:
        raise ValueError(
            "Business/build container has a non-loopback network interface"
        )
    ledger["observation_wall_seconds"] = time.monotonic() - started
    write_json(output / "INPUTS.json", ledger)
    return ledger
