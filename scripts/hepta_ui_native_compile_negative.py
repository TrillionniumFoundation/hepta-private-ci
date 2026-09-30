#!/usr/bin/env python3
"""Prove that native durability and admission internals are not external APIs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "journal_storage": "use hepta_native::journal_storage::append_wal_frame;\nfn main() {}\n",
    "retirement": "use hepta_native::retirement::RetirementStore;\nfn main() {}\n",
    "task_supervisor": "use hepta_native::ui::task_supervisor::TaskAdmission;\nfn main() {}\n",
}
APP_LOCK = "apps/hepta-native/Cargo.lock"


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="strict",
    ).strip()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def fixture_manifest(name: str) -> str:
    dependency = (ROOT / "apps/hepta-native").resolve().as_posix()
    return f'''[package]
name = "ui-native-negative-{name.replace("_", "-")}"
version = "0.0.0"
edition = "2024"
publish = false

[dependencies]
hepta-native = {{ path = "{dependency}" }}
'''


def package_map(content: bytes) -> dict[tuple[str, str, str | None], dict]:
    value = tomllib.loads(content.decode("utf-8"))
    require(
        isinstance(value.get("package"), list),
        "Cargo lock package inventory is missing",
    )
    packages = {}
    for package in value["package"]:
        require(isinstance(package, dict), "Cargo lock package is not an object")
        identity = (package.get("name"), package.get("version"), package.get("source"))
        require(
            all(isinstance(part, str) and part for part in identity[:2]),
            "Cargo package identity is invalid",
        )
        require(
            identity[2] is None or isinstance(identity[2], str),
            "Cargo package source is invalid",
        )
        require(
            identity not in packages, "Cargo lock contains duplicate package identities"
        )
        packages[identity] = package
    return packages


def dependency_edges(package: dict, packages: dict) -> set[tuple[str, str, str | None]]:
    resolved = set()
    for edge in package.get("dependencies", []):
        match = re.fullmatch(r"([^ ()]+)(?: ([^ ()]+))?(?: \((.*)\))?", edge)
        require(match is not None, f"invalid Cargo lock dependency edge: {edge}")
        name, version, source = match.groups()
        matches = [
            identity
            for identity in packages
            if identity[0] == name
            and (version is None or identity[1] == version)
            and (source is None or identity[2] == source)
        ]
        require(
            len(matches) == 1,
            f"ambiguous or missing Cargo lock dependency edge: {edge}",
        )
        resolved.add(matches[0])
    return resolved


def verify_fixture_lock(seed: bytes, observed: bytes, name: str) -> None:
    """Allow Cargo to prune unreachable dev packages, never change dependency identities."""
    original, normalized = package_map(seed), package_map(observed)
    fixture = (f"ui-native-negative-{name.replace('_', '-')}", "0.0.0", None)
    require(fixture in normalized, "normalized lock lacks the external fixture package")
    native = [
        identity
        for identity in original
        if identity[0] == "hepta-native" and identity[2] is None
    ]
    require(
        len(native) == 1 and native[0] in normalized,
        "normalized lock lacks the exact native package",
    )
    require(
        dependency_edges(normalized[fixture], normalized) == {native[0]},
        "fixture dependency is not the exact native package",
    )
    for identity, package in normalized.items():
        if identity == fixture:
            continue
        require(
            identity in original,
            f"fixture floated beyond application Cargo.lock: {identity}",
        )
        baseline = original[identity]
        require(
            {key: value for key, value in package.items() if key != "dependencies"}
            == {key: value for key, value in baseline.items() if key != "dependencies"},
            f"fixture changed locked package metadata or checksum: {identity}",
        )
    for identity, package in normalized.items():
        if identity == fixture:
            continue
        require(
            dependency_edges(package, normalized)
            <= dependency_edges(original[identity], original),
            f"fixture changed locked dependency edges: {identity}",
        )


def diagnostics(result: subprocess.CompletedProcess) -> str:
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    if len(output) > 16000:
        output = (
            output[:8000] + "\n... diagnostic output truncated ...\n" + output[-8000:]
        )
    return output or "(compiler produced no diagnostic output)"


def run_case(name: str, source: str, base: Path, seed: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"hepta-{name}-", dir=base) as directory:
        root = Path(directory)
        (root / "src").mkdir()
        manifest = root / "Cargo.toml"
        manifest.write_text(fixture_manifest(name), encoding="utf-8")
        (root / "src/main.rs").write_text(source, encoding="utf-8")
        lock = root / "Cargo.lock"
        lock.write_bytes(seed)
        env = {
            **os.environ,
            "CARGO_TARGET_DIR": os.environ.get(
                "CARGO_TARGET_DIR", str(ROOT / "apps/hepta-native/target")
            ),
        }
        compiler = subprocess.run(
            ["rustc", "+1.95.0", "-vV"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        require(
            compiler.returncode == 0,
            f"{name}: compiler host discovery failed (exit {compiler.returncode}):\n{diagnostics(compiler)}",
        )
        hosts = [
            line
            for line in compiler.stdout.decode("utf-8", errors="replace").splitlines()
            if line.startswith("host:")
        ]
        host = (
            re.fullmatch(r"host: ([a-z0-9_.]+(?:-[a-z0-9_.]+){2,})", hosts[0])
            if len(hosts) == 1
            else None
        )
        require(
            host is not None,
            f"{name}: compiler host discovery returned an invalid or ambiguous host:\n{diagnostics(compiler)}",
        )
        # A different root package requires lock normalization. Full metadata
        # resolves the fixture and prunes dev-only entries using the seed;
        # --no-deps skips resolution and leaves the fixture out of the lock.
        # Filter to the compiler host to avoid downloading unused platform crates.
        # Reject any floating resolution before invoking the compiler.
        prepared = subprocess.run(
            [
                "cargo",
                "+1.95.0",
                "metadata",
                "--offline",
                "--format-version",
                "1",
                "--filter-platform",
                host.group(1),
                "--manifest-path",
                str(manifest),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        require(
            prepared.returncode == 0,
            f"{name}: fixture lock normalization failed (exit {prepared.returncode}):\n{diagnostics(prepared)}",
        )
        observed = lock.read_bytes()
        verify_fixture_lock(seed, observed, name)
        result = subprocess.run(
            [
                "cargo",
                "+1.95.0",
                "check",
                "--offline",
                "--locked",
                "--quiet",
                "--manifest-path",
                str(manifest),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        require(result.returncode != 0, f"private module {name} unexpectedly compiled")
        require(
            "error[E0603]" in stderr,
            f"{name} failed for a reason other than privacy (exit {result.returncode}):\n{diagnostics(result)}",
        )
        require(
            f"module `{name}` is private" in stderr,
            f"missing private-module diagnostic for {name}:\n{diagnostics(result)}",
        )
        require(
            lock.read_bytes() == observed,
            f"{name}: locked compiler check changed the fixture lock",
        )
        return {
            "module": name,
            "exitCode": result.returncode,
            "diagnosticSha256": sha256(result.stderr),
            "privacyDiagnosticObserved": True,
            "seedCargoLockSha256": sha256(seed),
            "fixtureCargoLockSha256": sha256(observed),
            "dependencyResolutionPinned": True,
            "lockedCompilerCheck": True,
        }


def main() -> int:
    expected = os.environ.get("NATIVE_EXPECTED_HEAD")
    before = git("rev-parse", "HEAD")
    require(
        expected is None or before == expected,
        "compile-negative source identity mismatch",
    )
    require(
        not git("status", "--porcelain", "--untracked-files=no"),
        "tracked source is dirty",
    )

    base = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    lock = ROOT / APP_LOCK
    require(
        lock.is_file() and not lock.is_symlink(),
        "application Cargo.lock is missing or unsafe",
    )
    seed = lock.read_bytes()
    package_map(seed)
    observations = []
    for name, source in CASES.items():
        observations.append(run_case(name, source, base, seed))

    after = git("rev-parse", "HEAD")
    require(after == before, "compile-negative test changed source identity")
    require(
        not git("status", "--porcelain", "--untracked-files=no"),
        "compile-negative test dirtied tracked source",
    )
    receipt = {
        "schema": "hepta.ui-native-compile-negative.v1",
        "sourceSha": before,
        "applicationCargoLockSha256": sha256(seed),
        "cases": observations,
        "compilerNegativePassed": True,
        "effectAuthorityGranted": False,
        "releaseAuthorized": False,
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
