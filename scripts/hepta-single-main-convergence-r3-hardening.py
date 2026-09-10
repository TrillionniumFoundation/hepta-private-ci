#!/usr/bin/env python3
"""R3 convergence hardening: exact binding rebasing, lock closure and compatibility gates."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
R3_PATH = HERE / "hepta-single-main-convergence-r3.py"
SPEC = importlib.util.spec_from_file_location("hepta_single_main_r3", R3_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load R3 executor: {R3_PATH}")
r3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r3)
r2 = r3.r2
r1 = r3.r1

NATIVE_BINDINGS = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
LANE_A_BINDINGS = "qualification/module-execution-dossiers/NATIVE_BINDINGS_LANE_A.json"
CONTRACT_TESTS = "qualification/module-execution-dossiers/test_implementation_contracts.py"
LEGACY_TEST_ENTRY = r3.IMPLEMENTATION_TEST_ENTRY
CARGO_MANIFEST = "codex-rs/Cargo.toml"
CARGO_LOCK = "codex-rs/Cargo.lock"
_ORIGINAL_NORMALIZE = r1.normalize_fixed_point
_LEGACY_LANE_G_SHA: str | None = None


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("ascii") + data).hexdigest()


def safe_source(relative: str) -> Path:
    item = Path(relative)
    if item.is_absolute() or ".." in item.parts:
        raise r1.ConvergenceError(f"unsafe source-observation path: {relative}")
    root = r1.ROOT.resolve()
    path = (root / item).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise r1.ConvergenceError(f"source-observation path is absent: {relative}")
    return path


def verify_exports(row: dict[str, Any]) -> bytes:
    relative = row.get("path")
    exports = row.get("exports")
    if not isinstance(relative, str) or not isinstance(exports, list) or not exports:
        raise r1.ConvergenceError(f"invalid source-observation row: {row!r}")
    data = safe_source(relative).read_bytes()
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise r1.ConvergenceError(f"source observation is not UTF-8: {relative}") from error
    for symbol in exports:
        if not isinstance(symbol, str) or not symbol or re.search(
            r"\b" + re.escape(symbol) + r"\b", source
        ) is None:
            raise r1.ConvergenceError(
                f"source-observation export {symbol!r} is absent from {relative}"
            )
    return data


def refresh_manifest(relative: str) -> dict[str, Any]:
    path = r1.ROOT / relative
    value = json.loads(path.read_text(encoding="utf-8"))
    rows = value.get("observations")
    if not isinstance(rows, list) or not rows:
        raise r1.ConvergenceError(f"{relative}: observations missing")
    rebound: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise r1.ConvergenceError(f"{relative}: observation row is not an object")
        data = verify_exports(row)
        observed = git_blob_sha(data)
        prior = row.get("blobSha")
        if prior != observed:
            rebound.append(
                {
                    "module": str(row.get("module")),
                    "prior": str(prior),
                    "observed": observed,
                }
            )
            row["blobSha"] = observed
    if relative == LANE_A_BINDINGS:
        value["sourceObservationDigest"] = hashlib.sha256(
            json.dumps(
                rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
    rendered = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    if path.read_text(encoding="utf-8") != rendered:
        path.write_text(rendered, encoding="utf-8")
    return {
        "path": relative,
        "observationCount": len(rows),
        "reboundCount": len(rebound),
        "rebound": rebound,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def refresh_native_manifests() -> list[dict[str, Any]]:
    return [refresh_manifest(NATIVE_BINDINGS), refresh_manifest(LANE_A_BINDINGS)]


def regenerate_and_validate_cargo_lock() -> dict[str, Any]:
    manifest = r1.ROOT / CARGO_MANIFEST
    lock = r1.ROOT / CARGO_LOCK
    if not manifest.is_file():
        raise r1.ConvergenceError(f"canonical Cargo manifest is absent: {CARGO_MANIFEST}")
    before = sha256_file(lock)
    generated = r1.run(
        (
            "cargo",
            "generate-lockfile",
            "--manifest-path",
            str(manifest),
        ),
        cwd=r1.ROOT,
        capture=True,
        timeout=3600,
    )
    after = sha256_file(lock)
    if after is None:
        raise r1.ConvergenceError(f"cargo did not materialize {CARGO_LOCK}")
    metadata = r1.run(
        (
            "cargo",
            "metadata",
            "--manifest-path",
            str(manifest),
            "--format-version",
            "1",
            "--locked",
            "--no-deps",
        ),
        cwd=r1.ROOT,
        capture=True,
        timeout=3600,
    )
    parsed = json.loads(metadata.stdout)
    packages = parsed.get("packages")
    workspace_members = parsed.get("workspace_members")
    if not isinstance(packages, list) or not isinstance(workspace_members, list):
        raise r1.ConvergenceError("cargo metadata returned an invalid workspace shape")
    return {
        "path": CARGO_LOCK,
        "beforeSha256": before,
        "afterSha256": after,
        "changed": before != after,
        "packageCount": len(packages),
        "workspaceMemberCount": len(workspace_members),
        "generateStdoutSha256": sha256_text(generated.stdout),
        "generateStderrSha256": sha256_text(generated.stderr),
        "metadataSha256": sha256_text(metadata.stdout),
        "metadataStderrSha256": sha256_text(metadata.stderr),
    }


def merge_lane_g(lane_g_sha: str) -> dict[str, Any]:
    global _LEGACY_LANE_G_SHA
    result = r3.merge_lane_g_semantically(lane_g_sha)
    _LEGACY_LANE_G_SHA = lane_g_sha
    return result


def run_contract_compatibility() -> dict[str, Any]:
    canonical = r1.run(
        (sys.executable, CONTRACT_TESTS), capture=True, timeout=1800
    )
    lane_a = r1.run(
        (sys.executable, "scripts/verify_lane_a_foundation.py", "verify"),
        capture=True,
        timeout=1800,
    )
    legacy_report: dict[str, Any] = {"executed": False}
    if _LEGACY_LANE_G_SHA:
        legacy_source = r1.git(
            "show", f"{_LEGACY_LANE_G_SHA}:{LEGACY_TEST_ENTRY}", capture=True
        ).stdout
        test_root = r1.ROOT / "qualification/module-execution-dossiers"
        temporary = test_root / f".lane-g-legacy-contract-r3-{r3.r2.RUN_ID}.py"
        temporary.write_text(legacy_source, encoding="utf-8")
        try:
            legacy = r1.run(
                (sys.executable, str(temporary)),
                cwd=test_root,
                capture=True,
                timeout=1800,
            )
        finally:
            temporary.unlink(missing_ok=True)
        legacy_report = {
            "executed": True,
            "sourceSha": _LEGACY_LANE_G_SHA,
            "sourceSha256": sha256_text(legacy_source),
            "stdoutSha256": sha256_text(legacy.stdout),
            "stderrSha256": sha256_text(legacy.stderr),
        }
    return {
        "canonicalSplitSuite": {
            "returnCode": canonical.returncode,
            "stdoutSha256": sha256_text(canonical.stdout),
            "stderrSha256": sha256_text(canonical.stderr),
        },
        "laneAFoundation": {
            "returnCode": lane_a.returncode,
            "stdoutSha256": sha256_text(lane_a.stdout),
            "stderrSha256": sha256_text(lane_a.stderr),
        },
        "legacyLaneGSuite": legacy_report,
    }


def normalize_fixed_point() -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    prior: str | None = None
    for outer_round in range(1, 7):
        inner = _ORIGINAL_NORMALIZE()
        cargo_lock = regenerate_and_validate_cargo_lock()
        bindings = refresh_native_manifests()
        digest = r1.sha256_bytes(
            r1.git("diff", "--binary", capture=True).stdout.encode("utf-8")
        )
        receipts.append(
            {
                "r3HardeningRound": outer_round,
                "innerFixedPoint": inner,
                "cargoLock": cargo_lock,
                "nativeRebinding": bindings,
                "diffSha256": digest,
            }
        )
        print(
            "r3 hardening fixed-point "
            f"round={outer_round} lockSha256={cargo_lock['afterSha256']} "
            f"diffSha256={digest}"
        )
        if digest == prior:
            compatibility = run_contract_compatibility()
            locked_metadata = regenerate_and_validate_cargo_lock()
            after = r1.sha256_bytes(
                r1.git("diff", "--binary", capture=True).stdout.encode("utf-8")
            )
            if after != digest:
                raise r1.ConvergenceError(
                    "compatibility or locked-metadata gates mutated the product tree"
                )
            receipts.append(
                {
                    "r3CompatibilityGates": compatibility,
                    "r3FinalCargoLockGate": locked_metadata,
                }
            )
            return receipts
        prior = digest
    raise r1.ConvergenceError(
        "R3 lock, native rebinding, generators and formatters did not converge"
    )


def lane_specific_repository_gates() -> None:
    commands = (
        (sys.executable, "scripts/verify_lane_a_foundation.py", "verify"),
        (sys.executable, "scripts/hepta-lane-b-truth.py"),
        (sys.executable, "scripts/hepta-lane-c-closure.py"),
        (sys.executable, "scripts/hepta-lane-d-semantic-conformance.py"),
        (sys.executable, "scripts/hepta-lane-e-closure.py"),
    )
    for command in commands:
        if (r1.ROOT / command[1]).is_file():
            r1.run(command, timeout=3600)
    tool_root = r1.ROOT / "tools/hepta-engineering-control"
    if tool_root.is_dir():
        r1.run(
            (
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                str(tool_root),
                "-p",
                "test_*.py",
            ),
            timeout=3600,
        )
        for name in ("lane_g_validate.py", "lane_g_hardening_validate.py"):
            path = tool_root / name
            if path.is_file():
                r1.run((sys.executable, str(path)), timeout=3600)
    for app in ("hepta-browser", "hepta-control-ui", "hepta-native"):
        tests = sorted((r1.ROOT / "apps" / app / "test").glob("*.test.js"))
        if tests:
            r1.run(("node", "--test", *[str(path) for path in tests]), timeout=3600)


r1.merge_lane_g = merge_lane_g
r1.normalize_fixed_point = normalize_fixed_point
r1.lane_specific_repository_gates = lane_specific_repository_gates


def main() -> int:
    return int(r3.main())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"HEPTA_SINGLE_MAIN_R3_HARDENING_ERROR: {error}", file=sys.stderr)
        raise
