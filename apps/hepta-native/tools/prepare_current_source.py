#!/usr/bin/env python3
"""Freeze committed native sources and refresh only native identity metadata.

The one-time source migration is already committed. This command does not
create implementation, alter owner authority, or turn test sources into passes.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/hepta-native"
BASE = "7ddbfac88525196e7a4b31387ceae194958275f5"
BRANCH = "work/ui-native-current-source-20260925"
INTEGRATION_ROOTS = (
    ROOT / "codex-rs/hepta-native-gateway",
    ROOT / "codex-rs/hepta-private-state",
)
INTEGRATION_FILES = (
    ROOT / "CALLERS.toml",
    ROOT / "codex-rs/Cargo.toml",
    ROOT / "codex-rs/Cargo.lock",
    ROOT / "codex-rs/hepta-contracts/Cargo.toml",
    ROOT / "codex-rs/hepta-contracts/src/lib.rs",
    ROOT / "codex-rs/hepta-contracts/src/native_gateway.rs",
    ROOT / "codex-rs/hepta-contracts/src/native_gateway_tests.rs",
    ROOT / "codex-rs/hepta-contracts/src/authority_lease.rs",
    ROOT / "codex-rs/hepta-contracts/src/final_use.rs",
    ROOT / "codex-rs/hepta-contracts/src/final_use_control.rs",
    ROOT / "codex-rs/hepta-contracts/src/final_use_store.rs",
    ROOT / "codex-rs/hepta-contracts/src/final_use_store_tests.rs",
    ROOT / "codex-rs/hepta-contracts/src/final_use_tests.rs",
    ROOT / "codex-rs/hepta-contracts/src/final_use_windows_tests.rs",
    ROOT / "codex-rs/hepta-contracts/tests/final_use_linearization.rs",
    ROOT / ".github/workflows/hepta-ui-native-current-source.yml",
)
SOURCE_LOG_PATHS = tuple(
    path.relative_to(ROOT).as_posix() for path in INTEGRATION_FILES
) + (
    "apps/hepta-native",
    "codex-rs/hepta-native-gateway",
    "codex-rs/hepta-private-state",
)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def committed_blob(path):
    relative = path.relative_to(ROOT).as_posix()
    try:
        return subprocess.check_output(
            ["git", "show", f"HEAD:{relative}"], cwd=ROOT
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"native source identity requires committed path: {relative}"
        ) from error


def require_branch():
    branch = git("branch", "--show-current")
    if branch == BRANCH:
        return
    if not branch and subprocess.run(
        ["git", "merge-base", "--is-ancestor", f"refs/remotes/origin/{BRANCH}", "HEAD"],
        cwd=ROOT, check=False,
    ).returncode == 0:
        return
    raise RuntimeError(
        "metadata writes require the named native candidate or its isolated detached continuation"
    )


def prepare():
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", BASE, "HEAD"], cwd=ROOT, check=True
    )
    if git("status", "--porcelain"):
        raise RuntimeError("source preparation requires a clean committed candidate")
    for retired in ["src/native.js", "src/shell-runtime.js"]:
        if (APP / retired).exists():
            raise RuntimeError(f"retired product entrypoint reappeared: {retired}")
    if not (APP / "Cargo.lock").is_file():
        raise RuntimeError(
            "the prepared candidate must retain its reviewed native Cargo lock"
        )
    print("committed native candidate", git("rev-parse", "HEAD"))


def fingerprint(write):
    path = APP / "CURRENT_SOURCE.json"
    names = {
        p
        for p in APP.rglob("*")
        if p.is_file()
        and not any(
            part in {"target", "__pycache__"} for part in p.relative_to(APP).parts
        )
        and p.name != "CURRENT_SOURCE.json"
    }
    for integration_root in INTEGRATION_ROOTS:
        if not integration_root.is_dir():
            raise RuntimeError(
                f"missing integration source root: {integration_root.relative_to(ROOT)}"
            )
        names.update(
            p
            for p in integration_root.rglob("*")
            if p.is_file()
            and not any(
                part in {"target", "__pycache__"}
                for part in p.relative_to(integration_root).parts
            )
        )
    for integration_file in INTEGRATION_FILES:
        if not integration_file.is_file():
            raise RuntimeError(
                f"missing integration source file: {integration_file.relative_to(ROOT)}"
            )
        names.add(integration_file)
    observed = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(committed_blob(p)).hexdigest()
        for p in sorted(names)
    }
    if write:
        require_branch()
        path.write_text(
            json.dumps(
                {
                    "schema": "hepta.ui.native.current-source.v2",
                    "baselineCommit": BASE,
                    "baselineRole": "initial_convergence_ancestor",
                    "historicalSourceCommit": "3198549d80d6c59887b82e2c50018ab818217c53",
                    "canonicalBranch": BRANCH,
                    "files": observed,
                    "productionQualified": False,
                    "releaseAuthorized": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    else:
        expected = json.loads(path.read_text(encoding="utf-8"))["files"]
        if observed != expected:
            changed = sorted(
                set(observed) ^ set(expected)
                | {
                    key
                    for key in set(observed) & set(expected)
                    if observed[key] != expected[key]
                }
            )
            raise RuntimeError("native source identity mismatch: " + ", ".join(changed))
        print(f"verified {len(observed)} native source identities")


def native_row(data, collection):
    rows = [row for row in data[collection] if row.get("module") == "ui.native"]
    if len(rows) != 1:
        raise RuntimeError(f"expected exactly one ui.native row in {collection}")
    return rows[0]


def rewrite_retired_navigation(value):
    replacements = {
        "apps/hepta-native/src/native.js": "apps/hepta-native/src/runtime.rs",
        "apps/hepta-native/src/shell-runtime.js": "apps/hepta-native/src/runtime.rs",
        "apps/hepta-native/test/native.test.js": "apps/hepta-native/tests/journal_regressions.rs",
        "apps/hepta-native/test/shell-runtime.test.js": "apps/hepta-native/tests/runtime.rs",
        "buildNativeIntent": "request_platform_capability",
        "observeNativeOutcome": "reconcile_pending",
    }
    if isinstance(value, str):
        if value.startswith("node --test apps/hepta-native/"):
            return "cargo test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets"
        return replacements.get(value, value)
    if isinstance(value, list):
        return [rewrite_retired_navigation(child) for child in value]
    if isinstance(value, dict):
        return {key: rewrite_retired_navigation(child) for key, child in value.items()}
    return value


def sync_registry_metadata():
    changes = {}
    # CARGO_BINDINGS.json is intentionally scoped to `codex-hepta-*` crates
    # discovered under codex-rs. The standalone native application is owned by
    # ui.native through MODULES/SOURCE_BINDINGS, not by pretending it is a
    # codex-rs workspace package.
    cargo_bindings = json.loads(
        (ROOT / "docs/modules/CARGO_BINDINGS.json").read_text(encoding="utf-8")
    )
    if any(
        row.get("packagePath") == "apps/hepta-native"
        for row in cargo_bindings["bindings"]
    ):
        raise RuntimeError(
            "standalone native application must not enter codex-rs CARGO_BINDINGS"
        )
    for relative, collection in [
        ("docs/modules/SOURCE_BINDINGS.json", "bindings"),
        ("docs/modules/MODULE_DOCS.json", "modules"),
    ]:
        data = json.loads((ROOT / relative).read_text(encoding="utf-8"))
        row = native_row(data, collection)
        updated = rewrite_retired_navigation(row)
        row.clear()
        row.update(updated)
        if relative.endswith("MODULE_DOCS.json"):
            text = (ROOT / row["path"]).read_text(encoding="utf-8")
            row.update(
                sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                bytes=len(text.encode("utf-8")),
                words=len(re.findall(r"\b[\w.-]+\b", text)),
            )
            if any(heading not in text for heading in row["requiredSections"]):
                raise RuntimeError(
                    "native technical guide is missing a registered section"
                )
        changes[relative] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    relative = "qualification/module-execution-dossiers/DETAILS.json"
    data = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    rows = [
        row
        for row in data["rows"]
        if row.get("path")
        == "qualification/module-execution-dossiers/detail/ui.native.md"
    ]
    if len(rows) != 1:
        raise RuntimeError("native dossier index coverage mismatch")
    text = (ROOT / rows[0]["path"]).read_text(encoding="utf-8")
    rows[0]["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    changes[relative] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    for relative, text in changes.items():
        (ROOT / relative).write_text(text, encoding="utf-8")
    # The exact-source metadata commit stages only these scoped registry
    # changes; no unrelated owner source or authority registry is staged.
    subprocess.run(["git", "add", "--", *changes], cwd=ROOT, check=True)


def sync_metadata():
    require_branch()
    source = git("log", "-1", "--format=%H", "--", *SOURCE_LOG_PATHS)
    if not source:
        raise RuntimeError("unable to resolve the committed native source candidate")
    tree = git("rev-parse", f"{source}^{{tree}}")
    path = ROOT / "docs/modules/ui.native/IMPLEMENTATION_MAP.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    app_test = (
        "cargo test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets"
    )
    owner_test = (
        "cargo test --manifest-path codex-rs/Cargo.toml --locked "
        "-p codex-hepta-native-gateway -p codex-hepta-contracts "
        "-p codex-hepta-private-state --all-targets --all-features"
    )
    entries = {
        "connect_runtime": {
            "file": "runtime.rs",
            "symbol": "pub fn connect_runtime(",
            "delegates": [
                (
                    "apps/hepta-native/src/security.rs",
                    "SignedEndpointManifestV1::verify",
                ),
                (
                    "apps/hepta-native/src/session_store.rs",
                    "GatewayCredentialStore::load",
                ),
                ("apps/hepta-native/src/backend.rs", "LoopbackGatewayBackend::connect"),
                ("codex-rs/hepta-native-gateway/src/lib.rs", "run_native_gateway"),
            ],
            "tests": [
                ("apps/hepta-native/tests/runtime.rs", "rust_integration", app_test),
                ("apps/hepta-native/tests/backend.rs", "rust_integration", app_test),
                ("codex-rs/hepta-native-gateway/src/lib.rs", "rust_unit", owner_test),
            ],
        },
        "render_runtime_view": {
            "file": "runtime.rs",
            "symbol": "pub fn refresh_runtime_view(",
            "delegates": [
                (
                    "apps/hepta-native/src/backend.rs",
                    "LoopbackGatewayBackend::runtime_status",
                ),
                ("codex-rs/hepta-native-gateway/src/lib.rs", "route_request"),
                ("apps/hepta-native/src/ui.rs", "HeptaNativeApp::refresh"),
            ],
            "tests": [
                ("apps/hepta-native/tests/backend.rs", "rust_integration", app_test),
                ("apps/hepta-native/tests/runtime.rs", "rust_integration", app_test),
                ("codex-rs/hepta-native-gateway/src/lib.rs", "rust_unit", owner_test),
            ],
        },
        "request_platform_capability": {
            "file": "runtime.rs",
            "symbol": "pub fn request_platform_capability(",
            "delegates": [
                ("apps/hepta-native/src/journal.rs", "OperationJournal::upsert"),
                (
                    "apps/hepta-native/src/security.rs",
                    "KernelFinalUseGate::with_platform_use",
                ),
                (
                    "codex-rs/hepta-contracts/src/final_use.rs",
                    "FinalUseAuthority::with_verified_effect",
                ),
                ("apps/hepta-native/src/platform.rs", "PlatformAdapter::invoke"),
            ],
            "tests": [
                ("apps/hepta-native/tests/runtime.rs", "rust_integration", app_test),
                (
                    "apps/hepta-native/tests/security_updater.rs",
                    "rust_integration",
                    app_test,
                ),
                (
                    "codex-rs/hepta-contracts/src/final_use_tests.rs",
                    "rust_unit",
                    owner_test,
                ),
                (
                    "codex-rs/hepta-contracts/tests/final_use_linearization.rs",
                    "rust_integration",
                    owner_test,
                ),
            ],
        },
        "apply_shell_update": {
            "file": "updater.rs",
            "symbol": "pub fn verify_and_stage(",
            "delegates": [
                ("apps/hepta-native/src/ui.rs", "HeptaNativeApp::stage_update"),
                ("apps/hepta-native/src/bin/hepta-native-updater.rs", "main"),
                ("apps/hepta-native/src/private_state.rs", "PrivateStateRoot::verify"),
            ],
            "tests": [
                (
                    "apps/hepta-native/tests/security_updater.rs",
                    "rust_integration",
                    app_test,
                ),
                (
                    "apps/hepta-native/tests/private_state.rs",
                    "rust_integration",
                    app_test,
                ),
                ("codex-rs/hepta-private-state/src/lib.rs", "rust_unit", owner_test),
            ],
        },
    }
    data["sourceBase"] = {"commit": source, "tree": tree}
    data["sourceMaturity"] = "native_product_candidate"
    data["repositoryControlledGaps"] = [
        "Execute and retain current exact-head and deterministic synthetic-merge app, gateway, authority and package receipts on Linux, macOS and Windows.",
        "Execute each generated unsigned package through its packaged binary smoke and retain measured build, package, smoke and artifact-size observations.",
    ]
    data["externalEvidenceGates"] = [
        "Apple Developer ID custody and notarization, Windows Authenticode/AppUserModelID, and Linux distribution signing or repository ownership",
        "physical keyboard, screen-reader, Chinese IME, focus-restoration and multi-monitor DPI acceptance from installed artifacts",
        "target-host startup, RSS, interaction and long-running resource acceptance",
        "independent release-channel selection, operator acceptance, promotion and release authority",
    ]
    data["productCallers"] = [
        {
            "sourcePath": "apps/hepta-native/src/main.rs",
            "nativeSymbol": "fn run(",
            "role": "desktop_product_bootstrap",
        }
    ]
    for op in data["operations"]:
        entry = entries[op["designOperation"]]
        symbol = entry["symbol"]
        source_path = f"apps/hepta-native/src/{entry['file']}"
        op["ownerEntrypoint"].update(
            path=source_path, symbol=symbol, buildTarget="hepta-native"
        )
        op["nativeSymbol"] = symbol
        op["sourcePath"] = source_path
        op["sourcePathExists"] = True
        op["delegatedCallees"] = [
            {"path": path, "symbol": callee} for path, callee in entry["delegates"]
        ]
        op["tests"] = [
            {"path": path, "kind": kind, "command": command}
            for path, kind, command in entry["tests"]
        ]
    data["claimBoundary"]["nativeSourceMappingComplete"] = True
    data["claimBoundary"]["repositoryControlledDocumentationGapsClosed"] = True
    data["claimBoundary"]["repositoryControlledMappingGapsClosed"] = True
    data["claimBoundary"]["repositoryControlledSourceBoundaryGapsClosed"] = True
    for key in [
        "productExecutionComplete",
        "deploymentQualificationComplete",
        "independentAcceptanceComplete",
        "productionImplementation",
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    ]:
        data["claimBoundary"][key] = False
    data["productionImplementation"] = False
    data["productCallerState"] = (
        "source_composed_authenticated_gateway_execution_pending"
    )
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    path = ROOT / "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
    bindings = json.loads(path.read_text(encoding="utf-8"))
    changed = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("module") == "ui.native" and "blobSha" in value:
                native = "apps/hepta-native/src/runtime.rs"
                value["path"] = native
                value["blobSha"] = git("hash-object", native)
                value["exports"] = [
                    "NativeShellRuntime",
                    "connect_runtime",
                    "refresh_runtime_view",
                    "request_platform_capability",
                    "reconcile_pending",
                ]
                changed.append(native)
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(bindings)
    if len(changed) != 1:
        raise RuntimeError(f"expected one native source binding, found {len(changed)}")
    path.write_text(json.dumps(bindings, indent=2) + "\n", encoding="utf-8")
    sync_registry_metadata()
    print("bound native mapping to committed source", source)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--prepare", action="store_true")
    group.add_argument("--write-fingerprints", action="store_true")
    group.add_argument("--sync-metadata", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.write_fingerprints:
        fingerprint(True)
    elif args.sync_metadata:
        sync_metadata()
    else:
        fingerprint(False)
