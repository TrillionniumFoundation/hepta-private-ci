#!/usr/bin/env python3
"""Finish schema-22 automation.taskflow source truth after ordinary source commits.

This one-shot editor changes repository declarations only. It keeps deployment,
selected-host execution, independent acceptance, activation, promotion and
release false; the temporary workflow removes this file after verification.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "docs/modules/automation.taskflow"
MAP = MODULE / "IMPLEMENTATION_MAP.json"
CONTRACT = MODULE / "SCHEMA_CONTRACT.json"


def git_object(path: str) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", f"HEAD:{path}"], cwd=ROOT, text=True
    ).strip()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"{path}: expected JSON object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def upsert(rows: list[dict[str, Any]], row: dict[str, Any], key: str) -> None:
    for index, existing in enumerate(rows):
        if existing.get(key) == row[key]:
            rows[index] = row
            return
    rows.append(row)


def source_operation(
    name: str,
    path: str,
    symbol: str,
    semantics: str,
    tests: list[tuple[str, str, str]],
) -> dict[str, Any]:
    return {
        "designOperation": name,
        "mappingClass": "owner_native",
        "ownerEntrypoint": {
            "role": "owner_entrypoint",
            "path": path,
            "symbol": symbol,
            "buildTarget": "codex-hepta-automation",
        },
        "delegatedCallees": [],
        "tests": [
            {"path": test_path, "kind": kind, "command": command}
            for test_path, kind, command in tests
        ],
        "sourceSemantics": semantics,
        "operation": name,
        "nativeSymbol": symbol,
        "sourcePath": path,
        "sourcePathExists": True,
        "sourceBlob": git_object(path),
    }


def update_contract() -> None:
    contract = load(CONTRACT)
    contract["storeSchemaVersion"] = 22
    composition = contract.setdefault("productComposition", {})
    composition.update(
        {
            "durableNeuralCircuitOwner": True,
            "durableNeuralCircuitRecovery": True,
            "boundedNativeStartupVerification": True,
            "selectedHostRuntimeBinding": True,
            "selectedHostExecutionProved": False,
            "signedCrossHostFenceContract": True,
            "crossHostRecoveryController": False,
        }
    )
    write(CONTRACT, contract)


def update_map() -> None:
    data = load(MAP)
    data["stateOwnerDisposition"] = (
        "Owns schema-22 durable V1 schedules, occurrences, TaskFlow runs/steps, "
        "timer epochs, fair recovery sweeps and durable Neural Circuit activation, "
        "choice and checkpoint state. It consumes verified external host-fence "
        "receipts but does not own deployment, provider, model or release authority."
    )
    operations = data.setdefault("operations", [])
    upsert(
        operations,
        source_operation(
            "verify_occurrence_startup",
            "codex-rs/hepta-automation/src/lifecycle_bounded.rs",
            "pub(crate) async fn verify_occurrence_store(",
            (
                "Verifies every durable occurrence with a fixed 256-row keyset page. "
                "Memory is bounded by one page and corruption beyond the first page "
                "still rejects store startup."
            ),
            [
                (
                    "codex-rs/hepta-automation/src/lifecycle_bounded.rs",
                    "corruption_after_first_page_rejects_startup",
                    "cargo test -p codex-hepta-automation bounded_startup_scan_rejects_corruption_after_the_first_page",
                )
            ],
        ),
        "designOperation",
    )
    upsert(
        operations,
        source_operation(
            "verify_cross_host_fence",
            "codex-rs/hepta-automation/src/external_host_fence.rs",
            "pub fn verify(",
            (
                "Verifies an Ed25519 controller receipt binding authority epoch, owner, "
                "source and target hosts, checkpoint, monotone writer epochs and a bounded "
                "validity interval before a recovery manifest can be created or admitted."
            ),
            [
                (
                    "codex-rs/hepta-automation/src/external_host_fence.rs",
                    "signed_tuple_tamper_expiry_and_controller_epoch",
                    "cargo test -p codex-hepta-automation external_host_fence",
                ),
                (
                    "codex-rs/hepta-automation/src/cross_host_recovery.rs",
                    "verified_fence_required_at_export_and_target_admission",
                    "cargo test -p codex-hepta-automation cross_host_recovery",
                ),
            ],
        ),
        "designOperation",
    )
    for operation in operations:
        if operation.get("designOperation") == "admit_cross_host_recovery":
            operation["sourceSemantics"] = (
                "Consumes a still-current opaque verified controller fence and validates "
                "owner, schema, exact checkpoint, source/target host identity and exactly "
                "the next writer epoch. Physical transfer and target installation remain "
                "deployment-controller operations."
            )
            operation["sourceBlob"] = git_object(
                "codex-rs/hepta-automation/src/cross_host_recovery.rs"
            )

    data["remainingModuleGaps"] = [
        (
            "Exact-head and deterministic synthetic-merge formatting, compile, strict "
            "Clippy, native owner tests and Agentd product qualification must reach "
            "terminal success on this final revision. Queued or historical runs do not count."
        ),
        (
            "The protected selected-host workflow must execute on a concrete deployment "
            "profile and retain its candidate-bound exact-input Rust receipts; source "
            "composition does not self-issue deployment qualification."
        ),
        (
            "A deployment controller must execute checkpoint transfer, source fencing, "
            "target writer installation and a real two-host fault/recovery exercise using "
            "the signed fence contract."
        ),
        (
            "Independent acceptance, activation, promotion and release remain separately "
            "authorized external transitions."
        ),
    ]
    data["repositoryControlledProductCompositionGaps"] = []
    claims = data.setdefault("claimBoundary", {})
    claims.update(
        {
            "durableStoreSchemaVersion": 22,
            "boundedAdmissionBatchComplete": True,
            "separateRecoveryBudgetComplete": True,
            "externalEffectProductCompositionComplete": True,
            "neuralCircuitRuntimeVerticalSliceComplete": True,
            "durableNeuralCircuitProductComplete": True,
            "crossHostRecoveryContractComplete": True,
            "crossHostRecoveryProductComplete": False,
            "selectedHostQualificationPathComplete": True,
            "independentAcceptanceVerificationPathComplete": True,
            "boundedNativeStartupVerificationComplete": True,
            "exactConsumedSelectedHostBindingComplete": True,
            "signedCrossHostFenceReceiptComplete": True,
            "repositoryControlledSourceBoundaryGapsClosed": False,
            "repositoryControlledProductCompositionGapsClosed": True,
            "repositoryControlledDocumentationGapsClosed": True,
            "nativeSourceComplete": False,
            "nativeComposedCallerComplete": True,
            "productExecutionProved": False,
            "deploymentQualificationComplete": False,
            "independentAcceptance": False,
            "activation": False,
            "promotion": False,
            "release": False,
            "claimCeiling": (
                "Repository source now includes fair recovery, exact error/cancel "
                "propagation, persistent Neural Circuit activation/continuation, signed "
                "cross-host fence admission, exact selected-host input binding and bounded "
                "native startup verification. Exact-candidate execution and all external "
                "deployment/acceptance/release decisions remain open."
            ),
        }
    )
    data["nativeSourceMappingComplete"] = True
    data["productionImplementation"] = False
    data["productCallerState"] = (
        "agentd_scheduler_calendar_effect_host_schema22_circuit_and_exact_selected_host_"
        "qualification_path_source_composed_external_execution_pending"
    )
    data["productionWriterState"] = (
        "schema_v22_durable_owner_with_fair_recovery_signed_handoff_and_bounded_"
        "startup_exact_candidate_execution_pending"
    )

    paths = set(data.get("observedSourcePaths", []))
    paths.update(
        {
            ".github/workflows/automation-taskflow-selected-host.yml",
            "codex-rs/hepta-agentd/tests/automation_selected_host.rs",
            "codex-rs/hepta-automation/Cargo.toml",
            "codex-rs/hepta-automation/src/cross_host_recovery.rs",
            "codex-rs/hepta-automation/src/external_host_fence.rs",
            "codex-rs/hepta-automation/src/lifecycle_bounded.rs",
            "codex-rs/hepta-automation/src/lib.rs",
            "codex-rs/hepta-automation/tests/selected_host_profile.rs",
            "scripts/automation_taskflow_selected_host.py",
            "scripts/test_automation_taskflow_selected_host.py",
        }
    )
    data["observedSourcePaths"] = sorted(paths)

    objects = {row.get("path"): row for row in data.setdefault("sourceObjects", [])}
    evidence = data.setdefault(
        "exactSourceEvidence", {"kind": "path_blob_manifest_v1", "entries": []}
    )
    entries = {row.get("path"): row for row in evidence.setdefault("entries", [])}
    for path in sorted(paths):
        absolute = ROOT / path
        if not absolute.is_file() or path == str(MAP.relative_to(ROOT)):
            continue
        objects[path] = {"path": path, "object": git_object(path)}
    for operation in operations:
        path = operation.get("sourcePath")
        if path and (ROOT / path).is_file():
            operation["sourceBlob"] = git_object(path)
            entries[path] = {"path": path, "blobSha": git_object(path)}
    for path in (
        ".github/workflows/automation-taskflow-selected-host.yml",
        "codex-rs/hepta-agentd/tests/automation_selected_host.rs",
        "codex-rs/hepta-automation/tests/selected_host_profile.rs",
        "scripts/automation_taskflow_selected_host.py",
    ):
        entries[path] = {"path": path, "blobSha": git_object(path)}
    data["sourceObjects"] = sorted(objects.values(), key=lambda row: row["path"])
    evidence["entries"] = sorted(entries.values(), key=lambda row: row["path"])
    write(MAP, data)


def update_contract_markers() -> None:
    path = ROOT / "scripts/automation_taskflow_contract.py"
    body = path.read_text(encoding="utf-8")
    old = re.compile(
        r'    "\.github/workflows/automation-taskflow-selected-host\.yml": \([^\n]+\),\n'
    )
    replacement = (
        '    ".github/workflows/automation-taskflow-selected-host.yml": '
        '("hepta-automation-selected-host", "AUTOMATION_TIMEZONE_PROFILE_FILE", '
        '"selected_host_profile", "automation_selected_host", '
        '"automation-taskflow-selected-host-receipt.json"),\n'
    )
    body, count = old.subn(replacement, body, count=1)
    if count != 1:
        raise SystemExit("selected-host source marker anchor is missing")
    anchor = '    "codex-rs/hepta-automation/src/cross_host_recovery.rs": '
    additions = (
        '    "codex-rs/hepta-automation/src/external_host_fence.rs": '
        '("VerifiedAutomationHostFenceV1", "verify_strict", "expires_at_ms"),\n'
        '    "codex-rs/hepta-automation/src/lifecycle_bounded.rs": '
        '("OCCURRENCE_VERIFY_PAGE_SIZE", "WHERE task_id > ?", '
        '"bounded_startup_scan_rejects_corruption_after_the_first_page"),\n'
        '    "scripts/automation_taskflow_selected_host.py": '
        '("actual-timezone-profile-rust-consumption", "derive_provider_identity", '
        '"sqliteRuntimeVersion"),\n'
    )
    if "VerifiedAutomationHostFenceV1" not in body:
        position = body.find(anchor)
        if position < 0:
            raise SystemExit("cross-host source marker anchor is missing")
        body = body[:position] + additions + body[position:]
    path.write_text(body, encoding="utf-8")


def append_once(path: Path, marker: str, section: str) -> None:
    body = path.read_text(encoding="utf-8")
    if marker not in body:
        path.write_text(body.rstrip() + "\n\n" + section.strip() + "\n", encoding="utf-8")


def update_documents() -> None:
    append_once(
        MODULE / "TECHNICAL.md",
        "## Schema-22 review closure supplement",
        """
## Schema-22 review closure supplement

The repository source now closes the reviewed runtime counterexamples without
introducing a second scheduler or store: recovery uses persistent fair sweeps,
fatal/fence errors retain their class through the scheduler, and cancellation is
checked before each new batch claim. Durable Neural Circuit activation reserves
cost before owner contact and persists exact choices plus Wait/Effect checkpoints.

Cross-host manifests consume only a current Ed25519-verified controller fence
bound to owner, source/target hosts, checkpoint and the next writer epoch. The
selected-host workflow hashes protected input files, makes Rust load those exact
bytes through Calendar V2 and the Agentd effect host, records the SQLx SQLite
runtime, and then builds the qualification receipt from the same bytes. Startup
occurrence verification uses 256-row keyset pages and still rejects corruption on
later pages.

These are source and qualification-path facts. A terminal-success exact-head and
synthetic-merge run, a concrete selected-host run, an operated two-host recovery,
independent acceptance, activation, promotion and release remain separate gates.
""",
    )
    append_once(
        MODULE / "MIGRATION_V19_RUNBOOK.md",
        "## 8. Signed source-fence and bounded startup verification",
        """
## 8. Signed source-fence and bounded startup verification

Before export, verify `SignedAutomationHostFenceV1` against the pinned controller
key and authority epoch. The claims must bind the exact owner, source/target host,
checkpoint digest, source epoch, target epoch `source + 1`, issue time and expiry.
Create the manifest only from the resulting opaque verified receipt. Revalidate
that same receipt immediately before target admission; a changed or expired
receipt is `TimerFenced`.

Store startup verifies occurrence history in fixed 256-row keyset pages. Do not
replace this with a prefix sample. Capacity evidence must grow retained history
while proving that corruption after the first page is still rejected.
""",
    )
    append_once(
        MODULE / "SLO.md",
        "## Startup and selected-host evidence bounds",
        """
## Startup and selected-host evidence bounds

- Native occurrence startup verification retains at most 256 rows per keyset page.
- Later-page corruption is a startup failure, not a skipped historical warning.
- Selected-host receipts are valid only when Rust consumed the exact timezone,
  provider, final-use, revocation and terminal-observer bytes named by the receipt.
- A queued workflow or metadata-only digest does not satisfy these objectives.
""",
    )
    append_once(
        MODULE / "RELEASE_QUALIFICATION.md",
        "## Exact-input selected-host qualification",
        """
## Exact-input selected-host qualification

The protected selected-host environment supplies canonical file paths, not
caller-authored identity digests. Qualification derives the tzdb tree/profile,
provider contract, FinalUse trust, revocation head and terminal observer identities
from those bytes; Rust must successfully load the same files and report the native
SQLx SQLite version. The resulting receipt still leaves deployment qualification,
independent acceptance, activation, promotion and release false until their own
operators issue candidate-bound evidence.
""",
    )
    append_once(
        ROOT / "qualification/module-execution-dossiers/detail/automation.taskflow.md",
        "## 11. Review-remediation closure paths",
        """
## 11. Review-remediation closure paths

Repository source includes persistent fair recovery sweeps, exact scheduler error
and cancellation boundaries, schema-22 durable Circuit checkpoints, signed
cross-host fence verification, exact-input selected-host qualification and bounded
native startup scanning. Each is mapped to a concrete negative regression. None of
these source paths is a substitute for terminal-success exact-candidate execution,
selected deployment operation or independent release authority.
""",
    )


def main() -> int:
    update_contract()
    update_map()
    update_contract_markers()
    update_documents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
