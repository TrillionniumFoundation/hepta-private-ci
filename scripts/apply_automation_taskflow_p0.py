#!/usr/bin/env python3
"""Apply the automation.taskflow v19 P0 closure on the dedicated work branch.

This temporary branch applicator exists because the change spans Rust source,
closed caller inventory, module documentation and exact-source metadata.  It is
removed after the generated branch has passed its scoped qualification.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PatchError(RuntimeError):
    pass


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def write(relative: str, content: str) -> None:
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected one occurrence, observed {count}")
    return text.replace(old, new, 1)


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT
    ).strip()


def boundary_block(text: str, identifier: str) -> tuple[int, int, str]:
    marker = f'[[boundary]]\nid = "{identifier}"\n'
    start = text.find(marker)
    if start < 0:
        raise PatchError(f"missing caller boundary {identifier}")
    candidates = [
        value
        for value in (
            text.find("\n[[boundary]]", start + len(marker)),
            text.find("\n[[protected_file]]", start + len(marker)),
            text.find("\n[authority]", start + len(marker)),
        )
        if value >= 0
    ]
    end = min(candidates) if candidates else len(text)
    return start, end, text[start:end]


def set_boundary_callers(
    text: str, identifier: str, callers: list[str], markers: list[str]
) -> str:
    start, end, block = boundary_block(text, identifier)
    caller_line = "product_callers = " + json.dumps(callers)
    marker_line = "caller_markers = " + json.dumps(markers)
    changed, count = re.subn(
        r"product_callers = \[[^\n]*\]\ncaller_markers = \[[^\n]*\]",
        caller_line + "\n" + marker_line,
        block,
        count=1,
    )
    if count != 1:
        raise PatchError(f"{identifier}: caller fields were not found")
    return text[:start] + changed + text[end:]


def patch_effect_host() -> None:
    path = "codex-rs/hepta-agentd/src/automation_effect_host.rs"
    text = read(path)

    for line in (
        "use std::thread;\n",
        "use codex_hepta_automation::AuthorizedEffectDriver;\n",
        "use codex_hepta_automation::AuthorizedEffectDriverError;\n",
        "use codex_hepta_automation::AuthorizedEffectOutcome;\n",
        "use codex_hepta_automation::AuthorizedEffectProviderReceipt;\n",
        "use codex_hepta_automation::AuthorizedEffectRequest;\n",
        "use codex_hepta_contracts::ProviderEffectAck;\n",
        "use codex_hepta_contracts::ProviderEffectAckStatus;\n",
        "use codex_hepta_contracts::ProviderEffectAdapter;\n",
        "use codex_hepta_contracts::ProviderEffectDispatch;\n",
        "use codex_hepta_contracts::ProviderEffectIntent;\n",
        "use codex_hepta_contracts::ProviderEffectKey;\n",
        "use codex_hepta_contracts::ProviderEffectLookup;\n",
    ):
        if line not in text:
            raise PatchError(f"effect host import missing before patch: {line.strip()}")
        text = text.replace(line, "", 1)

    text = replace_once(
        text,
        "use codex_hepta_automation::AuthorizedEffectRecoveryResult;\n",
        "use codex_hepta_automation::AuthorizedEffectRecoveryResult;\n"
        "use codex_hepta_automation::AuthorizedProviderEffectLookup;\n"
        "use codex_hepta_automation::ProviderEffectTaskFlowDriver;\n",
        "effect host bridge imports",
    )

    text = replace_once(
        text,
        "        let mut driver = HttpAuthorizedEffectDriver {\n"
        "            adapter: self.adapter.clone(),\n"
        "            provider_scope: self.provider_scope.clone(),\n"
        "            destination_id: self.destination_id.clone(),\n"
        "        };\n"
        "        store\n"
        "            .execute_authorized_taskflow_effect(\n",
        "        let mut driver = ProviderEffectTaskFlowDriver::new(\n"
        "            self.destination_id.clone(),\n"
        "            self.adapter.clone(),\n"
        "        )\n"
        "        .map_err(|error| {\n"
        "            AgentdError::Protocol(format!(\n"
        "                \"configure automation provider-effect bridge: {error}\"\n"
        "            ))\n"
        "        })?;\n"
        "        store\n"
        "            .execute_authorized_taskflow_effect_async(\n",
        "effect host async product dispatch",
    )

    reconcile_start = text.find("        let provider_intent = self.provider_intent(&pending)?;")
    reconcile_end = text.find("\n    fn refresh_revocations", reconcile_start)
    if reconcile_start < 0 or reconcile_end < 0:
        raise PatchError("effect host reconciliation block was not found")
    reconcile = textwrap.dedent(
        """
                let driver = ProviderEffectTaskFlowDriver::new(
                    self.destination_id.clone(),
                    self.adapter.clone(),
                )
                .map_err(|error| {
                    AgentdError::Protocol(format!(
                        "configure automation provider-effect lookup bridge: {error}"
                    ))
                })?;
                match driver.lookup(&pending).await {
                    AuthorizedProviderEffectLookup::Observed(receipt) => {
                        match store
                            .recover_authorized_taskflow_effect(
                                run_id,
                                step_id,
                                attempt,
                                &fence,
                                AuthorizedEffectRecovery::Observed(receipt),
                                now_ms,
                            )
                            .await
                            .map_err(|error| {
                                AgentdError::Protocol(format!(
                                    "reconcile authorized effect terminal observation: {error}"
                                ))
                            })?
                        {
                            AuthorizedEffectRecoveryResult::Observed(receipt) => {
                                Ok(AgentdAutomationEffectReconcileOutcome::Observed(receipt))
                            }
                            AuthorizedEffectRecoveryResult::ProvenAbsent => Err(
                                AgentdError::Protocol(
                                    "terminal provider observation cannot become proven absent"
                                        .to_string(),
                                ),
                            ),
                        }
                    }
                    AuthorizedProviderEffectLookup::ProvenAbsent { proof_digest } => {
                        match store
                            .recover_authorized_taskflow_effect(
                                run_id,
                                step_id,
                                attempt,
                                &fence,
                                AuthorizedEffectRecovery::ProvenAbsent { proof_digest },
                                now_ms,
                            )
                            .await
                            .map_err(|error| {
                                AgentdError::Protocol(format!(
                                    "reconcile authorized effect proven absence: {error}"
                                ))
                            })?
                        {
                            AuthorizedEffectRecoveryResult::ProvenAbsent => {
                                Ok(AgentdAutomationEffectReconcileOutcome::ProvenAbsent)
                            }
                            AuthorizedEffectRecoveryResult::Observed(_) => Err(
                                AgentdError::Protocol(
                                    "provider absence proof cannot manufacture terminal effect"
                                        .to_string(),
                                ),
                            ),
                        }
                    }
                    AuthorizedProviderEffectLookup::Unresolved => {
                        Ok(AgentdAutomationEffectReconcileOutcome::Indeterminate)
                    }
                }
            }
        """
    )
    text = text[:reconcile_start] + reconcile + text[reconcile_end:]

    provider_method_start = text.find("\n    fn provider_intent(")
    provider_struct_start = text.find("\nstruct HttpAuthorizedEffectDriver", provider_method_start)
    if provider_method_start < 0 or provider_struct_start < 0:
        raise PatchError("legacy provider-intent method was not found")
    text = text[:provider_method_start] + "\n}" + text[provider_struct_start:]

    legacy_start = text.find("\nstruct HttpAuthorizedEffectDriver")
    legacy_end = text.find("\nfn read_host_file", legacy_start)
    if legacy_start < 0 or legacy_end < 0:
        raise PatchError("legacy synchronous driver block was not found")
    text = text[:legacy_start] + "\n" + text[legacy_end:]

    text = replace_once(
        text,
        "        let provider_key = ProviderEffectKey::for_operation(\n"
        "            \"provider/fixture-v1\",\n"
        "            &intent.run_id,\n"
        "            &intent.step_id,\n"
        "        )\n"
        "        .expect(\"provider key\");\n",
        "        let logical_effect_id =\n"
        "            format!(\"taskflow:{}:{}\", intent.run_id, intent.step_id);\n"
        "        let provider_key = ProviderEffectKey::for_logical_effect(\n"
        "            &intent.destination_id,\n"
        "            &logical_effect_id,\n"
        "        )\n"
        "        .expect(\"provider key\");\n",
        "effect host provider identity test",
    )
    write(path, text)


def patch_callers() -> None:
    path = "CALLERS.toml"
    text = read(path)
    text = set_boundary_callers(
        text,
        "http_provider_effect_adapter",
        ["codex-rs/hepta-agentd/src/automation_effect_host.rs"],
        [
            "HttpProviderEffectAdapter::new",
            "HttpProviderEffectContractAttestation::verify_signed",
            "AgentdAutomationEffectHost",
        ],
    )
    text = set_boundary_callers(
        text,
        "final_use_open_state",
        [
            "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "codex-rs/hepta-agentd/src/bin/hepta-agentd-browser.rs",
        ],
        ["FinalUseAuthority::open_state_dir", "SignedFinalUseGrant"],
    )
    text = set_boundary_callers(
        text,
        "final_use_async_dispatch_fence",
        ["codex-rs/hepta-automation/src/authorized_effect.rs"],
        [
            "with_verified_use_async",
            "execute_authorized_taskflow_effect_async",
            "begin_effect_dispatch_attempt",
        ],
    )
    text = set_boundary_callers(
        text,
        "automation_taskflow_provider_effect_bridge",
        ["codex-rs/hepta-agentd/src/automation_effect_host.rs"],
        [
            "ProviderEffectTaskFlowDriver::new",
            "execute_authorized_taskflow_effect_async",
            "FinalUseAuthority",
        ],
    )
    write(path, text)


def append_section(text: str, marker: str, section: str) -> str:
    if marker in text:
        raise PatchError(f"section marker already present: {marker}")
    return text.rstrip() + "\n\n" + textwrap.dedent(section).strip() + "\n"


def patch_docs() -> None:
    technical_path = "docs/modules/automation.taskflow/TECHNICAL.md"
    technical = read(technical_path)
    technical = technical.replace("schema v16", "schema v19")
    technical = technical.replace("schema-v16", "schema-v19")
    technical = append_section(
        technical,
        "Automation store schema: v19",
        """
        ## 19. Store schema v19 and product-effect composition

        **Automation store schema: v19.** The executable owner opens migrations
        through `0019_converged_owner_schema.sql`.  Schema v17 adds immutable
        destination-operation deduplication, v18 adds the single timer-writer
        lifecycle/epoch, and v19 converges the formerly displaced v17/v18
        migration histories without deleting either owner's records.  The
        reviewed migration and recovery procedure is
        [MIGRATION_AND_RECOVERY_RUNBOOK.md](MIGRATION_AND_RECOVERY_RUNBOOK.md).

        Agentd is the named product caller for external TaskFlow effects.  Its
        `AutomationExecuteEffect` control method loads an independently
        configured, attestation-checked provider host and a persistent
        `FinalUseAuthority`, then calls `ProviderEffectTaskFlowDriver` through
        `execute_authorized_taskflow_effect_async`.  Exact provider bytes are
        hashed before grant consumption; the provider key is derived from the
        durable destination plus TaskFlow run/step, and reconciliation performs
        lookup only.  This closes the repository-controlled caller gap.  It does
        not self-issue provider credentials, final-use signatures, a current
        IANA tzdb profile, selected-host measurements or independent acceptance.

        Older binaries that do not understand schema v19 must not replace the
        writer or open a copied database.  A rollback is a restore of a complete
        pre-upgrade snapshot plus its matching binary/configuration, never an
        in-place schema decrement.  Same-store timer epoch handoff is supported;
        cross-host database transfer remains fail-closed until the runbook's
        snapshot, exclusive-writer and digest requirements are independently
        satisfied.
        """,
    )
    write(technical_path, technical)

    dossier_path = "qualification/module-execution-dossiers/detail/automation.taskflow.md"
    dossier = read(dossier_path)
    dossier = replace_once(
        dossier,
        "Status: durable scheduling, deterministic occurrence identity, durable TaskFlow run/step state, stable App Server reconciliation, terminal observation, capability-negotiated Calendar V2 Agentd control, and the final-use-authorized effect seam are source-implemented. Calendar V2 product control is composed; arbitrary downstream effect product callers, activation and independently accepted providers remain separate gates.",
        "Status: schema-v19 durable scheduling, deterministic occurrence identity, durable TaskFlow run/step state, stable App Server reconciliation, terminal observation, capability-negotiated Calendar V2 Agentd control, and the final-use-authorized provider-effect product caller are source-composed. Selected-host deployment, authentic tzdb provenance, provider activation and independent acceptance remain separate gates.",
        "dossier status",
    )
    dossier = dossier.replace("schema v16", "schema v19")
    dossier = dossier.replace("schema-v16", "schema-v19")
    dossier = dossier.replace("migrations `0004`-`0016`", "migrations `0004`-`0019`")
    dossier = dossier.replace("migrations `0004`-`0016`.", "migrations `0004`-`0019`.")
    dossier = replace_once(
        dossier,
        "No second scheduler, TaskFlow engine, queue writer, authority issuer or terminality oracle was introduced. Rollback must preserve schema v19 records or use a binary that understands Calendar V2, frozen legacy schedule revisions, legacy dispatch-unknown reconciliation evidence, provider reconciliation history, and terminal-observer cursor progress; older binaries must not replace the owner against an upgraded store.",
        "No second scheduler, TaskFlow engine, queue writer, authority issuer or terminality oracle was introduced. The authoritative store is schema v19: v17 adds destination-operation dedupe, v18 adds timer writer lifecycle/epoch, and v19 converges the known displaced histories. Rollback is snapshot restore with the matching binary and configuration; older binaries must not open or replace an upgraded store.",
        "dossier rollback",
    )
    start = dossier.find("External-effect **product composition is still open**:")
    end = dossier.find("\n\nProduct execution, target-host deployment", start)
    if start < 0 or end < 0:
        raise PatchError("dossier product-boundary paragraph was not found")
    replacement = (
        "External-effect **repository product composition is source-closed**: "
        "Agentd exposes `AutomationExecuteEffect`/`AutomationReconcileEffect`, loads an "
        "independently provisioned `FinalUseAuthority` and attested HTTP provider host, and "
        "calls the TaskFlow-owned `ProviderEffectTaskFlowDriver` async bridge.  The durable "
        "attempt is written before provider contact and restart lookup reuses the same "
        "destination + run + step identity.  This is source composition only: provider "
        "credentials, signed grants, authentic/current IANA tzdb material, target-host "
        "measurements, activation and independent acceptance remain external evidence gates."
    )
    dossier = dossier[:start] + replacement + dossier[end:]
    dossier = dossier.replace(
        "- **Focused verification:**",
        "- **Schema v17-v19 convergence:** `migrations/0017_kernel_operation_dedupe.sql`, `0018_timer_lifecycle.sql`, `0019_converged_owner_schema.sql` and `src/migration_convergence_tests.rs` preserve both displaced histories and reject unknown checksum/version pairs.\n- **Focused verification:**",
        1,
    )
    if "Automation store schema: v19" not in dossier:
        dossier = dossier.replace(
            "## 1. Source and work envelope\n",
            "## 1. Source and work envelope\n\n**Automation store schema: v19.**\n",
            1,
        )
    write(dossier_path, dossier)

    lane_path = "docs/readiness/LANE_B_NATIVE_HOST.md"
    lane = read(lane_path)
    lane = lane.replace("schema-v16", "schema-v19")
    lane = lane.replace("schema v16", "schema v19")
    lane = lane.replace(
        "The final-use external-effect seam is durable, but concrete downstream product callers/owners remain independent authority, activation and evidence gates.",
        "The Agentd control plane now calls the TaskFlow-owned async provider-effect bridge through its attested provider host; independently provisioned authority/provider configuration, target-host activation and acceptance remain evidence gates.",
    )
    if "Automation store schema: v19" not in lane:
        lane = lane.replace(
            "This page describes executable behavior in the source, including gaps that require implementation. It takes precedence over older statements that all repository-controlled Lane B source gaps are closed.\n",
            "This page describes executable behavior in the source, including gaps that require implementation. It takes precedence over older statements that all repository-controlled Lane B source gaps are closed.\n\n**Automation store schema: v19.**\n",
            1,
        )
    write(lane_path, lane)


def create_runbooks() -> None:
    write(
        "docs/modules/automation.taskflow/MIGRATION_AND_RECOVERY_RUNBOOK.md",
        r"""
# automation.taskflow schema-v19 migration and recovery runbook

**Automation store schema: v19.** This runbook is operational guidance for the
single per-Agent `AutomationStore`; it does not authorize a provider, mint a
final-use grant, transfer ownership to a second scheduler or certify a host.

## Migration topology

| Store cut | Durable addition | Recovery rule |
|---|---|---|
| v16 | terminal-observer cursor | Preserve the exact opaque App Server cursor and resume by CAS. |
| v17 | `destination_operation_dedupe` | Immutable destination/scope/operation receipts are committed with the destination mutation. |
| v18 | `automation_timer_lifecycle` | One writer epoch owns `active -> draining -> active/retired`; unresolved dispatches block epoch transfer. |
| v19 | converged owner schema | Recognize only the reviewed displaced v17/v18 SQLx version/checksum pairs, remap those known histories, then validate normal migrations. |

`AUTOMATION_SCHEMA_VERSION`, the highest migration number and this document must
remain equal. Unknown checksums, duplicate semantic migrations, a dirty SQLx row,
missing triggers/tables, failed integrity checks or a non-positive writer epoch
fail the open before the process publishes readiness.

## Pre-upgrade procedure

1. Stop new automation admission and request timer draining.
2. Reconcile or explicitly retain every dispatch-unknown/provider-indeterminate
   attempt. Never convert an absent local receipt into provider absence.
3. Require no leased compatibility run and no unresolved dispatch before writer
   epoch handoff.
4. Stop the old process and take a crash-consistent copy of the database together
   with `-wal` and `-shm` when present. Record SHA-256, byte length, owner AgentId,
   writer epoch, schema version, binary commit, provider-host configuration digest,
   revocation frontier and filesystem permissions.
5. Copy the snapshot to protected storage before starting the v19 binary.

A live file copy without SQLite backup semantics is not a backup.

## Upgrade and verification

Start exactly one v19 owner. Opening performs legacy migration-ID reconciliation,
SQLx migration, private-file protection and full store verification before the
scheduler becomes ready. Then run the migration-convergence test matrix, open a
copy of every supported historical cut, verify the expected tables/triggers and
exercise one due occurrence, one dispatch-unknown reconciliation, one terminal
cursor continuation and one timer drain/resume cycle.

## Failure recovery

* Failure before migration commit: stop the candidate and reopen only after
  verifying the original snapshot and current files. Do not edit `_sqlx_migrations`.
* Ambiguous filesystem or SQLite error: fence the writer, retain all files and
  restore the complete pre-upgrade snapshot into a fresh private directory.
* Provider contact may have occurred: preserve the existing attempt and perform
  owner lookup with the same provider key. Never allocate a new external effect
  attempt until the registered owner proves absence.
* Cursor history exhausted without the bound turn: retain the durable
  indeterminate observation; do not infer success, failure or cancellation.

## Rollback and old binaries

Older binaries **MUST NOT** open, replace or write a schema-v19 database. Rollback
is not `UPDATE automation_meta SET schema_version = ...`; it is restoration of a
complete pre-upgrade snapshot with the exact matching binary, provider host,
revocation material and owner identity. New v17/v18/v19 rows must never be dropped
or projected into an older format.

## Cross-host boundary

Timer epoch handoff is a same-store ownership protocol, not cross-host replication.
A cross-host move is permitted only when admission is drained, the old writer is
stopped, an authenticated complete snapshot manifest is verified on the target,
exclusive filesystem/database ownership is established, target configuration and
revocation digests match, and the selected host re-runs recovery qualification.
Without those facts the target fails closed. Shared writable SQLite, concurrent
copy-and-run and treating a checkpoint receipt as distributed atomicity are
forbidden.
""",
    )

    write(
        "docs/modules/automation.taskflow/RELEASE_QUALIFICATION.md",
        r"""
# automation.taskflow release qualification

**Automation store schema: v19.** Repository source composition and external
qualification are separate assertions. The source can prove deterministic
identity, durable intent, bounded recovery and the named Agentd product caller;
it cannot self-issue target-host or independent-acceptance evidence.

## Repository-controlled gates

The focused workflow must pass schema/document drift, the closed privileged caller
inventory, Rust formatting, compile, strict clippy, package tests, migration
convergence, structural qualification, Agentd product-effect tests and an exact-SHA
command receipt. A failed or skipped required command is not a release receipt.

## External evidence still required

* selected-host Agentd/App Server execution and restart receipts;
* an independently provisioned final-use signer/verifying key and monotonic
  revocation frontier;
* an attested concrete provider plus trusted terminal/status lookup;
* authentic current IANA tzdb provenance and refresh policy;
* DST gap/overlap, multi-scheduler race, restore, saturation and backlog tests on
  the selected host;
* an independent principal's acceptance signature followed by explicit activation,
  promotion and release decisions.

Until all of those artifacts are bound to one immutable source SHA and target
profile, `deploymentQualificationComplete`, `independentAcceptance`, `activation`,
`promotion` and `release` remain false. Fixtures, localhost mocks, source hashes
and an administrator's own signature cannot substitute for those classes.
""",
    )


def create_schema_checker() -> None:
    write(
        "scripts/check_automation_taskflow_schema.py",
        r'''#!/usr/bin/env python3
"""Fail closed when automation schema, migrations, maps or docs drift."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_DOCS = (
    "docs/modules/automation.taskflow/TECHNICAL.md",
    "docs/modules/automation.taskflow/MIGRATION_AND_RECOVERY_RUNBOOK.md",
    "qualification/module-execution-dossiers/detail/automation.taskflow.md",
    "docs/readiness/LANE_B_NATIVE_HOST.md",
)


class SchemaDrift(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaDrift(message)


def verify(root: Path = ROOT) -> dict[str, object]:
    lib = (root / "codex-rs/hepta-automation/src/lib.rs").read_text(encoding="utf-8")
    match = re.search(r"AUTOMATION_SCHEMA_VERSION:\s*u32\s*=\s*(\d+)\s*;", lib)
    require(match is not None, "AUTOMATION_SCHEMA_VERSION is missing")
    code_version = int(match.group(1))

    migrations = sorted((root / "codex-rs/hepta-automation/migrations").glob("[0-9][0-9][0-9][0-9]_*.sql"))
    require(bool(migrations), "automation migrations are missing")
    migration_versions = [int(path.name.split("_", 1)[0]) for path in migrations]
    require(len(migration_versions) == len(set(migration_versions)), "duplicate migration version")
    migration_version = max(migration_versions)

    implementation = json.loads(
        (root / "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json").read_text(encoding="utf-8")
    )
    map_version = implementation.get("storeSchemaVersion")
    require(isinstance(map_version, int), "implementation map storeSchemaVersion is missing")
    require(
        implementation.get("migrationHead") == "0019_converged_owner_schema.sql",
        "implementation map migrationHead drift",
    )

    doc_versions: dict[str, int] = {}
    for relative in TARGET_DOCS:
        text = (root / relative).read_text(encoding="utf-8")
        marker = re.search(r"Automation store schema:\s*v(\d+)", text)
        require(marker is not None, f"{relative}: schema marker is missing")
        require("schema v16" not in text and "schema-v16" not in text, f"{relative}: stale v16 statement")
        doc_versions[relative] = int(marker.group(1))

    versions = {code_version, migration_version, map_version, *doc_versions.values()}
    require(len(versions) == 1, f"automation schema drift: {sorted(versions)}")
    require(code_version == 19, f"expected schema v19, observed v{code_version}")

    runbook = (root / TARGET_DOCS[1]).read_text(encoding="utf-8")
    for required in (
        "destination_operation_dedupe",
        "automation_timer_lifecycle",
        "0019_converged_owner_schema.sql",
        "Older binaries **MUST NOT**",
        "Cross-host boundary",
    ):
        require(required in runbook, f"migration runbook lacks {required!r}")

    callers = tomllib.loads((root / "CALLERS.toml").read_text(encoding="utf-8"))
    rows = {row["id"]: row for row in callers["boundary"]}
    effect_host = "codex-rs/hepta-agentd/src/automation_effect_host.rs"
    require(
        effect_host in rows["automation_taskflow_provider_effect_bridge"]["product_callers"],
        "ProviderEffectTaskFlowDriver has no product caller",
    )
    require(
        effect_host in rows["http_provider_effect_adapter"]["product_callers"],
        "HTTP provider-effect adapter has no product caller",
    )
    require(
        implementation["claimBoundary"]["externalEffectProductCompositionComplete"] is True,
        "implementation map does not record repository effect composition closure",
    )
    require(
        implementation["claimBoundary"]["release"] is False,
        "source drift check must not grant release",
    )

    return {
        "schema": "hepta.automation-taskflow.schema-drift-receipt.v1",
        "status": "PASS_AUTOMATION_TASKFLOW_SCHEMA_V19",
        "version": code_version,
        "migrationHead": migrations[-1].name,
        "documents": sorted(doc_versions),
        "productEffectCaller": effect_host,
        "release": False,
    }


def main() -> int:
    try:
        receipt = verify()
    except (OSError, ValueError, KeyError, SchemaDrift) as exc:
        print(f"FAIL_AUTOMATION_TASKFLOW_SCHEMA: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    )

    write(
        "scripts/test_automation_taskflow_schema.py",
        r'''from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "automation_schema_check", ROOT / "scripts/check_automation_taskflow_schema.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AutomationSchemaDriftTests(unittest.TestCase):
    def test_repository_is_schema_v19_consistent(self) -> None:
        receipt = MODULE.verify(ROOT)
        self.assertEqual(receipt["version"], 19)
        self.assertFalse(receipt["release"])

    def test_map_version_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            selected = [
                "codex-rs/hepta-automation/src/lib.rs",
                "codex-rs/hepta-automation/migrations",
                "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json",
                "docs/modules/automation.taskflow/TECHNICAL.md",
                "docs/modules/automation.taskflow/MIGRATION_AND_RECOVERY_RUNBOOK.md",
                "qualification/module-execution-dossiers/detail/automation.taskflow.md",
                "docs/readiness/LANE_B_NATIVE_HOST.md",
                "CALLERS.toml",
            ]
            for relative in selected:
                source = ROOT / relative
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, destination)
            path = target / "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["storeSchemaVersion"] = 18
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(MODULE.SchemaDrift, "schema drift"):
                MODULE.verify(target)


if __name__ == "__main__":
    unittest.main()
''',
    )


def apply_source() -> None:
    patch_effect_host()
    patch_callers()
    patch_docs()
    create_runbooks()
    create_schema_checker()


def update_source_objects(data: dict[str, object], source_sha: str) -> None:
    objects = data.setdefault("sourceObjects", [])
    assert isinstance(objects, list)
    wanted = {
        "CALLERS.toml",
        ".github/workflows/automation-taskflow-focused.yml",
        "codex-rs/hepta-agentd/src/automation_effect_host.rs",
        "docs/modules/automation.taskflow/TECHNICAL.md",
        "docs/modules/automation.taskflow/MIGRATION_AND_RECOVERY_RUNBOOK.md",
        "docs/modules/automation.taskflow/RELEASE_QUALIFICATION.md",
        "qualification/module-execution-dossiers/detail/automation.taskflow.md",
        "docs/readiness/LANE_B_NATIVE_HOST.md",
        "scripts/check_automation_taskflow_schema.py",
        "scripts/test_automation_taskflow_schema.py",
    }
    for row in objects:
        if isinstance(row, dict) and isinstance(row.get("path"), str):
            wanted.add(row["path"])
    updated = []
    for path in sorted(wanted):
        try:
            object_sha = git("rev-parse", f"{source_sha}:{path}")
        except subprocess.CalledProcessError as exc:
            raise PatchError(f"cannot bind source object {path}: {exc.output}") from exc
        updated.append({"path": path, "object": object_sha})
    data["sourceObjects"] = updated


def apply_metadata(source_sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise PatchError("source SHA must be an exact commit id")
    git("cat-file", "-e", f"{source_sha}^{{commit}}")
    path = "docs/modules/automation.taskflow/IMPLEMENTATION_MAP.json"
    data = json.loads(read(path))
    data["storeSchemaVersion"] = 19
    data["migrationHead"] = "0019_converged_owner_schema.sql"
    data["migrationTopology"] = {
        "v17": "destination_operation_dedupe",
        "v18": "automation_timer_lifecycle_writer_epoch",
        "v19": "known_displaced_history_convergence",
        "runbook": "docs/modules/automation.taskflow/MIGRATION_AND_RECOVERY_RUNBOOK.md",
    }
    data["sourceMaturity"] = "native_durable_taskflow_v19_product_effect_source_composed"
    data["observedAtHead"] = {
        "commit": source_sha,
        "tree": git("rev-parse", f"{source_sha}^{{tree}}"),
    }

    for operation in data["operations"]:
        source_path = operation["sourcePath"]
        operation["sourceBlob"] = git("rev-parse", f"{source_sha}:{source_path}")
        if operation["designOperation"] == "execute_step":
            operation["ownerEntrypoint"]["symbol"] = (
                "pub async fn execute_authorized_taskflow_effect_async"
            )
            operation["nativeSymbol"] = (
                "pub async fn execute_authorized_taskflow_effect_async"
            )
            operation["sourceSemantics"] = (
                "Persists the exact TaskFlow effect attempt before provider contact, "
                "consumes an independently signed final-use grant around the async "
                "ProviderEffectTaskFlowDriver, hashes unchanged wire bytes, derives a "
                "stable destination + run + step provider key, and performs lookup-only "
                "terminal/proven-absent reconciliation without blind redispatch."
            )
            operation["productCallers"] = [
                {
                    "role": "product_control_dispatch",
                    "path": "codex-rs/hepta-agentd/src/state_control.rs",
                    "symbol": "AgentdMethod::AutomationExecuteEffect",
                    "ownerModule": "runtime.agentd",
                },
                {
                    "role": "product_provider_host",
                    "path": "codex-rs/hepta-agentd/src/automation_effect_host.rs",
                    "symbol": "AgentdAutomationEffectHost::execute",
                    "ownerModule": "runtime.agentd",
                },
                {
                    "role": "product_terminal_reconciler",
                    "path": "codex-rs/hepta-agentd/src/automation_effect_host.rs",
                    "symbol": "AgentdAutomationEffectHost::reconcile",
                    "ownerModule": "runtime.agentd",
                },
            ]
            operation["productCompositionState"] = (
                "agentd_attested_provider_async_bridge_source_composed_external_qualification_pending"
            )
            tests = operation.setdefault("tests", [])
            if not any(
                isinstance(row, dict)
                and row.get("path")
                == "codex-rs/hepta-agentd/src/automation_effect_host.rs"
                for row in tests
            ):
                tests.append(
                    {
                        "path": "codex-rs/hepta-agentd/src/automation_effect_host.rs",
                        "kind": "agentd_product_exact_wire_async_bridge_and_reconciliation",
                        "command": "cargo test -p codex-hepta-agentd --lib automation_effect_host",
                    }
                )

    for entry in data["exactSourceEvidence"]["entries"]:
        entry["blobSha"] = git("rev-parse", f"{source_sha}:{entry['path']}")

    observed = set(data.get("observedSourcePaths", []))
    observed.update(
        {
            "CALLERS.toml",
            ".github/workflows/automation-taskflow-focused.yml",
            "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "docs/modules/automation.taskflow/TECHNICAL.md",
            "docs/modules/automation.taskflow/MIGRATION_AND_RECOVERY_RUNBOOK.md",
            "docs/modules/automation.taskflow/RELEASE_QUALIFICATION.md",
            "qualification/module-execution-dossiers/detail/automation.taskflow.md",
            "docs/readiness/LANE_B_NATIVE_HOST.md",
            "scripts/check_automation_taskflow_schema.py",
            "scripts/test_automation_taskflow_schema.py",
        }
    )
    data["observedSourcePaths"] = sorted(observed)

    claim = data["claimBoundary"]
    claim["repositoryControlledProductCompositionGapsClosed"] = True
    claim["externalEffectProductCompositionComplete"] = True
    claim["productExecutionComplete"] = False
    claim["deploymentQualificationComplete"] = False
    claim["independentAcceptanceComplete"] = False
    claim["productionImplementation"] = False
    claim["productExecutionProved"] = False
    claim["independentAcceptance"] = False
    claim["activation"] = False
    claim["release"] = False
    data["repositoryControlledProductCompositionGaps"] = []
    data["productCallerState"] = (
        "agentd_calendar_v2_and_final_use_provider_effect_product_callers_source_composed_external_qualification_pending"
    )
    data["releaseScope"] = (
        "repository source composition only; selected-host deployment, authentic tzdb, "
        "independent acceptance, activation, promotion and release remain false"
    )
    product_callers = data.setdefault("productCallers", [])
    for row in (
        {
            "sourcePath": "codex-rs/hepta-agentd/src/state_control.rs",
            "nativeSymbol": "AgentdMethod::AutomationExecuteEffect",
            "state": "generation_fenced_product_control_dispatch",
        },
        {
            "sourcePath": "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "nativeSymbol": "AgentdAutomationEffectHost::execute",
            "state": "attested_provider_and_final_use_async_product_host",
        },
        {
            "sourcePath": "codex-rs/hepta-agentd/src/automation_effect_host.rs",
            "nativeSymbol": "AgentdAutomationEffectHost::reconcile",
            "state": "lookup_only_product_terminal_reconciler",
        },
    ):
        if row not in product_callers:
            product_callers.append(row)

    update_source_objects(data, source_sha)
    write(path, json.dumps(data, indent=2, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("source")
    metadata = sub.add_parser("metadata")
    metadata.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    try:
        if args.command == "source":
            apply_source()
        else:
            apply_metadata(args.source_sha)
    except (OSError, ValueError, KeyError, PatchError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"automation.taskflow P0 patch failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
