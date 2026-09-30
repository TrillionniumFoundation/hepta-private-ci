#!/usr/bin/env python3
"""Prove that native durability and admission internals are not external APIs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "journal_storage": "use hepta_native::journal_storage::append_wal_frame;\nfn main() {}\n",
    "retirement": "use hepta_native::retirement::RetirementStore;\nfn main() {}\n",
    "task_supervisor": "use hepta_native::ui::task_supervisor::TaskAdmission;\nfn main() {}\n",
}


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
name = "ui-native-negative-{name.replace('_', '-')}"
version = "0.0.0"
edition = "2024"
publish = false

[dependencies]
hepta-native = {{ path = "{dependency}" }}
'''


def main() -> int:
    expected = os.environ.get("NATIVE_EXPECTED_HEAD")
    before = git("rev-parse", "HEAD")
    require(expected is None or before == expected, "compile-negative source identity mismatch")
    require(not git("status", "--porcelain", "--untracked-files=no"), "tracked source is dirty")

    base = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).resolve()
    observations = []
    for name, source in CASES.items():
        with tempfile.TemporaryDirectory(prefix=f"hepta-{name}-", dir=base) as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "Cargo.toml").write_text(fixture_manifest(name), encoding="utf-8")
            (root / "src/main.rs").write_text(source, encoding="utf-8")
            result = subprocess.run(
                [
                    "cargo",
                    "+1.95.0",
                    "check",
                    "--offline",
                    "--quiet",
                    "--manifest-path",
                    str(root / "Cargo.toml"),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            stderr = result.stderr.decode("utf-8", errors="strict")
            require(result.returncode != 0, f"private module {name} unexpectedly compiled")
            require("error[E0603]" in stderr, f"{name} failed for a reason other than privacy")
            require(f"module `{name}` is private" in stderr, f"missing private-module diagnostic for {name}")
            observations.append(
                {
                    "module": name,
                    "exitCode": result.returncode,
                    "diagnosticSha256": sha256(result.stderr),
                    "privacyDiagnosticObserved": True,
                }
            )

    after = git("rev-parse", "HEAD")
    require(after == before, "compile-negative test changed source identity")
    require(not git("status", "--porcelain", "--untracked-files=no"), "compile-negative test dirtied tracked source")
    receipt = {
        "schema": "hepta.ui-native-compile-negative.v1",
        "sourceSha": before,
        "cases": observations,
        "compilerNegativePassed": True,
        "effectAuthorityGranted": False,
        "releaseAuthorized": False,
    }
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
