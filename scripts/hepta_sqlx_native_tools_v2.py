"""Verify the actual ARM Cargo payload while retaining the original compiler."""

import io
import os
from pathlib import Path
import shutil
import tarfile

URL = "https://static.rust-lang.org/dist/2026-11-13/cargo-nightly-aarch64-unknown-linux-gnu.tar.xz"
ARCHIVE_SHA = "9a4841d2a2f90b8cd865f17ff092fecbd6d762d12e9a3a54a3ecfe002037d41e"
RELEASE = "1.102.0-nightly"
COMMIT = "ede6cefea9731cb595942338824c2f9a610b8189"
TARGET = "aarch64-unknown-linux-gnu"


def physical(old, path):
    actual = Path(path).resolve(strict=True)
    raw = old.read_regular(actual, 256 * 1024 * 1024)
    old.require(os.access(actual, os.X_OK), "tool is not executable")
    return {"path": str(actual), "bytes": len(raw), "sha256": old.digest(raw)}


def arm_elf(old, raw):
    old.require(
        len(raw) >= 64
        and raw[:6] == b"\x7fELF\x02\x01"
        and int.from_bytes(raw[18:20], "little") == 183,
        "tool is not an ELF64 little-endian AArch64 binary",
    )


def prepare(scope, old):
    tools = {
        name: physical(old, shutil.which(name) or "")
        for name in ("rustup", "curl", "just", "cargo-nextest")
    }
    scope.result["tools"] = tools
    launcher = physical(old, shutil.which("cargo") or "")
    old.require(
        {k: launcher[k] for k in ("bytes", "sha256")}
        == {k: tools["rustup"][k] for k in ("bytes", "sha256")},
        "native just must resolve cargo to the checked original rustup proxy",
    )
    tools["cargo_launcher"] = launcher
    for name in ("cargo", "rustc"):
        _, raw, _ = scope.invoke(
            "locate-" + name,
            [tools["rustup"]["path"], "which", "--toolchain", "1.96.0", name],
        )
        lines = raw.decode().splitlines()
        old.require(
            len(lines) == 1 and Path(lines[0]).is_absolute(),
            "original tool path is ambiguous",
        )
        tools[name] = physical(old, lines[0])
        arm_elf(old, old.read_regular(Path(lines[0]), 256 * 1024 * 1024))
    _, cargo_version, _ = scope.invoke(
        "original-cargo-version", ["cargo", "+1.96.0", "--version", "--verbose"]
    )
    _, rustc_version, _ = scope.invoke(
        "original-rustc-version", [tools["rustc"]["path"], "--version", "--verbose"]
    )
    old.require(
        cargo_version.decode().startswith("cargo 1.96.0 ")
        and "\nhost: " + TARGET + "\n" in cargo_version.decode()
        and rustc_version.decode().startswith("rustc 1.96.0 ")
        and "\nhost: " + TARGET + "\n" in rustc_version.decode(),
        "the actual original Cargo/Rust compiler or host differs",
    )
    archive = scope.directory / "official-cargo.tar.xz"
    old.require(not archive.exists(), "official archive was already acquired")
    scope.invoke(
        "official-arm-cargo-download",
        [
            tools["curl"]["path"],
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--max-time",
            "30",
            "--retry",
            "0",
            "--max-filesize",
            "67108864",
            "--output",
            str(archive),
            URL,
        ],
    )
    raw = old.read_regular(archive, 64 * 1024 * 1024)
    old.require(old.digest(raw) == ARCHIVE_SHA, "official ARM Cargo archive differs")
    binary = None
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as bundle:
        names, expanded = set(), 0
        for entry in bundle:
            expanded += entry.size
            old.require(
                entry.name not in names
                and len(names) < 10000
                and expanded <= 256 * 1024 * 1024
                and len(entry.name) <= 4096,
                "official archive duplicate or expansion limit",
            )
            names.add(entry.name)
            if entry.name == "cargo-nightly-aarch64-unknown-linux-gnu/cargo/bin/cargo":
                old.require(
                    entry.isfile() and 0 < entry.size <= 64 * 1024 * 1024,
                    "official binary archive member differs",
                )
                with bundle.extractfile(entry) as stream:
                    binary = stream.read(64 * 1024 * 1024 + 1)
                old.require(len(binary) == entry.size, "official extraction incomplete")
    old.require(binary is not None, "official Cargo binary is absent")
    arm_elf(old, binary)
    executable = scope.directory / "official-cargo"
    with executable.open("xb") as output:
        output.write(binary)
        output.flush()
        os.fsync(output.fileno())
    executable.chmod(0o700)
    tools["fixture_cargo"] = physical(old, executable)
    _, version, _ = scope.invoke(
        "official-arm-cargo-version", [str(executable), "--version", "--verbose"]
    )
    old.require(
        version.decode().startswith("cargo " + RELEASE + " ")
        and "\nrelease: " + RELEASE + "\n" in version.decode()
        and "\ncommit-hash: " + COMMIT + "\n" in version.decode()
        and "\nhost: " + TARGET + "\n" in version.decode(),
        "actual official ARM Cargo release, commit or host differs",
    )
    scope.result["official_archive"] = {
        "file": archive.name,
        "bytes": len(raw),
        "sha256": ARCHIVE_SHA,
        "url": URL,
        "installer_executed": False,
    }
    scope.result["tools"] = tools
    return tools


def check_versions(scope, old, tools):
    _, nextest, _ = scope.invoke(
        "nextest-version", ["cargo", "+1.96.0", "nextest", "--version"]
    )
    _, just, _ = scope.invoke("just-version", ["just", "--version"])
    old.require(
        nextest.decode().split()[:2] == ["cargo-nextest", "0.9.103"]
        and just.decode().strip() == "just 1.51.0",
        "native wrapper tools differ from the admitted versions",
    )
    archive = Path(os.environ.get("RUSTY_V8_ARCHIVE", ""))
    binding = Path(os.environ.get("RUSTY_V8_SRC_BINDING_PATH", ""))
    old.require(
        archive.is_absolute()
        and binding.is_absolute()
        and archive.parent == binding.parent
        and os.environ.get("V8_FROM_SOURCE") not in ("true", "1", "yes"),
        "the original verified V8 pair was not prepared",
    )
    checksums = archive.parent / (
        "rusty_v8_ptrcomp_sandbox_release_" + TARGET + ".sha256"
    )
    expected = {}
    for line in old.read_regular(checksums, 4096).decode().splitlines():
        sha, name = line.split()
        old.require(name not in expected, "duplicate V8 checksum")
        expected[name] = sha
    old.require(
        set(expected) == {archive.name, binding.name}, "V8 checksum roster differs"
    )
    pair = {}
    for path in (archive, binding):
        raw = old.read_regular(path, 256 * 1024 * 1024)
        old.require(old.digest(raw) == expected[path.name], "prepared V8 pair changed")
        pair[str(path)] = {"bytes": len(raw), "sha256": old.digest(raw)}
    scope.result["verified_v8_pair"] = pair
    scope.result["native_cargo_routing"] = {
        "PATH": os.environ["PATH"],
        "RUSTUP_TOOLCHAIN": "1.96.0",
        "cargo_launcher": tools["cargo_launcher"],
        "main_physical_cargo": tools["cargo"],
        "fixture_physical_cargo": tools["fixture_cargo"],
        "fixture_RUSTC": tools["rustc"],
        "blanket_PATH_override": False,
    }


def recheck(old, tools, directory, v8_pair):
    for path, pin in v8_pair.items():
        raw = old.read_regular(Path(path), 256 * 1024 * 1024)
        old.require(
            {"bytes": len(raw), "sha256": old.digest(raw)} == pin,
            "V8 pair changed during native scope",
        )
    for original in tools.values():
        old.require(physical(old, original["path"]) == original, "used tool changed")
    old.require(
        old.digest(
            old.read_regular(directory / "official-cargo.tar.xz", 64 * 1024 * 1024)
        )
        == ARCHIVE_SHA,
        "retained official archive changed",
    )
