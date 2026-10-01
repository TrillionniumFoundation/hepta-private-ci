#!/usr/bin/env python3
"""Verify committed native sources and refresh only native identity metadata.

The current-source manifest owns the inventory policy, not a self-referential
snapshot of every file hash. Verification recomputes a canonical SHA-256 path
map from the exact checked-out commit. Qualification receipts bind that digest
to the source commit/tree and retained check log. This command does not create
implementation, alter owner authority, or turn test sources into passes.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps/hepta-native"
BASE = "7ddbfac88525196e7a4b31387ceae194958275f5"
BRANCH = "work/ui-native-qualified-integration-20260928"
WRITE_BRANCHES = {BRANCH}
TRACKED_ROOTS = (
    "apps/hepta-native",
    "codex-rs/hepta-native-gateway",
    "codex-rs/hepta-private-state",
)
INTEGRATION_ROOTS = (
    ROOT / "codex-rs/hepta-native-gateway",
    ROOT / "codex-rs/hepta-private-state",
)
INTEGRATION_FILES = (
    ROOT / "CALLERS.toml",
    ROOT / "docs/modules/ui.native/TECHNICAL.md",
    ROOT / "docs/modules/ui.native/REMEDIATION-20260927.md",
    ROOT / "docs/modules/ui.native/ACCEPTANCE-REPAIR-20260927.md",
    ROOT / "docs/modules/ui.native/QUALIFIED-INTEGRATION-20260928.md",
    ROOT / "docs/modules/ui.native/CURRENT_SOURCE.json",
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
    ROOT / ".github/workflows/hepta-ui-native-remediation.yml",
    ROOT / ".github/workflows/hepta-ui-native-remediation-format.yml",
    ROOT / ".github/workflows/hepta-ui-native-qualified-integration.yml",
    ROOT / ".github/workflows/hepta-ui-native-integrate-20260928.yml",
    ROOT / "scripts/hepta_ui_native_evidence.py",
    ROOT / "scripts/test_hepta_ui_native_evidence.py",
    ROOT / "scripts/hepta_ui_native_aggregate.py",
    ROOT / "scripts/test_hepta_ui_native_aggregate.py",
    ROOT / "scripts/hepta_ui_native_product_evidence.py",
    ROOT / "scripts/hepta_ui_native_integrate_20260928.py",
    ROOT / "scripts/test_hepta_ui_native_source.py",
)
SOURCE_LOG_PATHS = (
    tuple(path.relative_to(ROOT).as_posix() for path in INTEGRATION_FILES)
    + TRACKED_ROOTS
    + (":(exclude)apps/hepta-native/CURRENT_SOURCE.json",)
)


def git(*args):
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="strict",
    ).strip()


def committed_blob(path):
    relative = path.relative_to(ROOT).as_posix()
    try:
        return subprocess.check_output(["git", "show", f"HEAD:{relative}"], cwd=ROOT)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"native source identity requires committed path: {relative}"
        ) from error


def require_branch():
    write_branch = os.environ.get("HEPTA_UI_NATIVE_WRITE_BRANCH", BRANCH)
    if write_branch not in WRITE_BRANCHES:
        raise RuntimeError("unregistered native metadata write branch")
    branch = git("branch", "--show-current")
    if branch == write_branch:
        return
    if (
        not branch
        and subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                f"refs/remotes/origin/{write_branch}",
                "HEAD",
            ],
            cwd=ROOT,
            check=False,
        ).returncode
        == 0
    ):
        return
    raise RuntimeError(
        "metadata writes require the named native candidate or its isolated detached continuation"
    )


def prepare():
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", BASE, "HEAD"],
        cwd=ROOT,
        check=True,
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


def inventory_policy():
    return {
        "trackedRoots": list(TRACKED_ROOTS),
        "integrationFiles": sorted(
            path.relative_to(ROOT).as_posix() for path in INTEGRATION_FILES
        ),
        "excluded": ["apps/hepta-native/CURRENT_SOURCE.json"],
        "digest": "sha256-canonical-path-map-at-verification",
    }


def inventory_digest(observed):
    canonical = json.dumps(
        observed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def fingerprint(write):
    path = APP / "CURRENT_SOURCE.json"
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "--", *TRACKED_ROOTS], cwd=ROOT
    )
    names = {ROOT / name.decode("utf-8") for name in tracked.split(b"\0") if name}
    names.discard(path)
    for integration_file in INTEGRATION_FILES:
        if not integration_file.is_file():
            raise RuntimeError(
                f"missing integration source file: {integration_file.relative_to(ROOT)}"
            )
        names.add(integration_file)
    observed = {}
    for source_path in sorted(names):
        relative = source_path.relative_to(ROOT).as_posix()
        if source_path.is_symlink() or not source_path.is_file():
            raise RuntimeError(f"native source is missing or a symlink: {relative}")
        committed = committed_blob(source_path)
        if source_path.read_bytes() != committed:
            raise RuntimeError(
                f"native source differs from committed bytes: {relative}"
            )
        observed[relative] = hashlib.sha256(committed).hexdigest()
    policy = inventory_policy()
    if write:
        require_branch()
        path.write_text(
            json.dumps(
                {
                    "schema": "hepta.ui.native.current-source.v3",
                    "baselineCommit": BASE,
                    "baselineRole": "initial_convergence_ancestor",
                    "historicalSourceCommit": "3198549d80d6c59887b82e2c50018ab818217c53",
                    "canonicalBranch": BRANCH,
                    "inventoryPolicy": policy,
                    "identityBinding": "exact-git-commit-tree-plus-retained-sha256-inventory-log",
                    "productionQualified": False,
                    "releaseAuthorized": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    else:
        committed_manifest = committed_blob(path)
        if path.read_bytes() != committed_manifest:
            raise RuntimeError("native source manifest differs from committed bytes")
        manifest = json.loads(committed_manifest.decode("utf-8"))
        if (
            manifest.get("schema") != "hepta.ui.native.current-source.v3"
            or manifest.get("canonicalBranch") != BRANCH
            or manifest.get("inventoryPolicy") != policy
            or manifest.get("identityBinding")
            != "exact-git-commit-tree-plus-retained-sha256-inventory-log"
            or manifest.get("productionQualified") is not False
            or manifest.get("releaseAuthorized") is not False
        ):
            raise RuntimeError(
                "native source manifest is not the exact non-promoting v3 inventory policy"
            )
    print(
        f"verified {len(observed)} native source identities; "
        f"inventory_sha256={inventory_digest(observed)}"
    )


def native_row(data, collection):
    rows = [row for row in data[collection] if row.get("module") == "ui.native"]
    if len(rows) != 1:
        raise RuntimeError("expected exactly one ui.native row in {collection}")
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
        (ROOT / relative).write_text(text, encoding="utf-8", newline="\n")
    subprocess.run(["git", "add", "--", *changes], cwd=ROOT, check=True)


def sync_metadata():
    require_branch()
    source = git("log", "-1", "--format=%H", "--", *SOURCE_LOG_PATHS)
    if not source:
        raise RuntimeError("unable to resolve the committed native source candidate")
    tree = git("rev-parse", f"{source}^{{tree}}")
    path = ROOT / "docs/modules/ui.native/IMPLEMENTATION_MAP.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["sourceBase"] = {"commit": source, "tree": tree}
    for item in data.get("sourceObjects", []):
        item["object"] = git("rev-parse", f"{source}:{item['path']}")
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
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
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
        raise RuntimeError("expected one native source binding, found {len(changed)}")
    path.write_text(
        json.dumps(bindings, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
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
