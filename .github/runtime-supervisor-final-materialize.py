from __future__ import annotations

# Runner epoch 2: the transformation is intentionally platform-neutral.
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_optional_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count > 1:
        raise SystemExit(f"{label}: expected zero or one match, found {count}")
    if count == 1:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")


lib = ROOT / "codex-rs/hepta-supervisor/src/lib.rs"
replace_once(
    lib,
    "pub use error::ProcessDriverError;\npub use error::SupervisorError;",
    "pub use error::ControlEffectBoundary;\n"
    "pub use error::ControlFailureAction;\n"
    "pub use error::ControlFailureClass;\n"
    "pub use error::ControlFailureDisposition;\n"
    "pub use error::ProcessDriverError;\n"
    "pub use error::SupervisorError;",
    "public control failure exports",
)

recovery = ROOT / "codex-rs/hepta-supervisor/src/recovery.rs"
lines = recovery.read_text(encoding="utf-8").splitlines(keepends=True)
targets = {
    "control_intent::reconcile_absent(": 0,
    "control_intent::has_unresolved(": 0,
    "control_intent::recover_pending(": 0,
}
old_map = ".map_err(|error| SupervisorError::Invalid(error.to_string()))?"
new_map = ".map_err(SupervisorError::from)?"
for index, line in enumerate(lines):
    token = next((token for token in targets if token in line), None)
    if token is None:
        continue
    for candidate in range(index, min(index + 32, len(lines))):
        if old_map in lines[candidate]:
            lines[candidate] = lines[candidate].replace(old_map, new_map)
            targets[token] += 1
            break
    else:
        raise SystemExit(f"recovery durable mapping missing after {token} at line {index + 1}")
expected = {
    "control_intent::reconcile_absent(": 2,
    "control_intent::has_unresolved(": 1,
    "control_intent::recover_pending(": 1,
}
if targets != expected:
    raise SystemExit(f"unexpected recovery durable mapping counts: {targets!r}")
recovery.write_text("".join(lines), encoding="utf-8")

daemon = ROOT / "codex-rs/hepta-supervisor/src/daemon.rs"
replace_once(
    daemon,
    "#[cfg(any(unix, test))]\nuse crate::AgentSupervisorSnapshot;\n#[cfg(unix)]\nuse crate::H7H89ProductionGrant;",
    "#[cfg(any(unix, test))]\nuse crate::AgentSupervisorSnapshot;\n"
    "#[cfg(any(unix, test))]\nuse crate::ControlEffectBoundary;\n"
    "#[cfg(any(unix, test))]\nuse crate::ControlFailureClass;\n"
    "#[cfg(unix)]\nuse crate::H7H89ProductionGrant;",
    "daemon control classification imports",
)
replace_once(
    daemon,
    "    if let Err(_error) = mutation {\n"
    "        return error_payload(\n"
    "            \"operation_indeterminate\",\n"
    "            \"operation outcome is indeterminate; refresh before retry\",\n"
    "            post,\n"
    "        );\n"
    "    }",
    "    if let Err(error) = mutation {\n"
    "        return safe_rejection(error, post, /*mutation_started*/ true);\n"
    "    }",
    "post-dispatch failure classification",
)
replace_once(
    daemon,
    "fn safe_rejection(\n"
    "    error: SupervisorError,\n"
    "    actual: Option<SupervisordAgentStatus>,\n"
    "    mutation_started: bool,\n"
    ") -> SupervisordPayload {\n"
    "    if mutation_started {\n"
    "        return error_payload(\n"
    "            \"operation_indeterminate\",\n"
    "            \"operation outcome is indeterminate; refresh before retry\",\n"
    "            actual,\n"
    "        );\n"
    "    }\n"
    "    match error {",
    "fn safe_rejection(\n"
    "    error: SupervisorError,\n"
    "    actual: Option<SupervisordAgentStatus>,\n"
    "    mutation_started: bool,\n"
    ") -> SupervisordPayload {\n"
    "    let boundary = if mutation_started {\n"
    "        ControlEffectBoundary::EffectAttempted\n"
    "    } else {\n"
    "        ControlEffectBoundary::Preflight\n"
    "    };\n"
    "    match error.control_failure_disposition(boundary).class {\n"
    "        ControlFailureClass::TargetIdentityStale => {\n"
    "            return error_payload(\n"
    "                \"stale_control_target\",\n"
    "                \"selected Agent identity changed; refresh before retry\",\n"
    "                actual,\n"
    "            );\n"
    "        }\n"
    "        ControlFailureClass::AlreadyCompleted => {\n"
    "            return error_payload(\n"
    "                \"operation_already_completed\",\n"
    "                \"requested operation is already reflected in current state; do not retry\",\n"
    "                actual,\n"
    "            );\n"
    "        }\n"
    "        ControlFailureClass::PersistenceIndeterminate => {\n"
    "            return error_payload(\n"
    "                \"persistence_indeterminate\",\n"
    "                \"durable operation outcome is indeterminate; inspect status before retry\",\n"
    "                actual,\n"
    "            );\n"
    "        }\n"
    "        ControlFailureClass::RecoveryRequired => {\n"
    "            return error_payload(\n"
    "                \"recovery_required\",\n"
    "                \"durable control state requires recovery; ordinary retry is blocked\",\n"
    "                actual,\n"
    "            );\n"
    "        }\n"
    "        ControlFailureClass::NotStarted => {}\n"
    "    }\n"
    "    match error {",
    "safe rejection classification",
)
replace_once(
    daemon,
    "        SupervisorError::CorruptLease(_)\n"
    "        | SupervisorError::Registry(_)\n"
    "        | SupervisorError::Io(_) => error_payload(",
    "        SupervisorError::ControlPersistenceIndeterminate(_)\n"
    "        | SupervisorError::ControlRecoveryRequired(_)\n"
    "        | SupervisorError::CorruptLease(_)\n"
    "        | SupervisorError::Registry(_)\n"
    "        | SupervisorError::Io(_) => error_payload(",
    "exhaustive daemon error mapping",
)

workflow = ROOT / ".github/workflows/runtime-supervisor-control-recovery.yml"
replace_once(
    workflow,
    "  source:\n    runs-on: ubuntu-24.04-arm",
    "  source:\n    runs-on: ubuntu-24.04",
    "available exact-source runner",
)

technical = ROOT / "docs/modules/runtime.supervisor/TECHNICAL.md"
replace_optional_once(
    technical,
    "**Last synced:** August 30, 2026",
    "**Last synced:** September 28, 2026",
    "technical sync date",
)
replace_once(
    technical,
    "The current daemon serializes lifecycle mutations and tick work through one execution permit and the supervisor owner lock. Health, Roster and Snapshot use a bounded immutable observation with a two-second freshness limit, but mutation/tick and whole-fleet refresh still share the lifecycle lane. This is not per-Agent concurrency or a 256-process latency qualification. Persisted state below the Agent run root includes process leases, bounded restart budgets, the release transaction and signed intent. Pending control kinds, deadlines and local exit-cleanup witnesses are not yet durable across daemon restart.",
    "The current daemon serializes lifecycle mutations and tick work through one execution permit and the supervisor owner lock. Health, Roster and Snapshot use a bounded immutable observation with a two-second freshness limit, but mutation/tick and whole-fleet refresh still share the lifecycle lane. This is not per-Agent concurrency or a 256-process latency qualification. Persisted state below the Agent run root includes process leases, bounded restart budgets, the release transaction, signed intent and a bounded exact-target Stop/Kill control intent. Stop/Kill preserve the original stop deadline and acknowledgement phase across daemon restart; Drain and retained owned-handle cleanup evidence remain in-memory boundaries.",
    "runtime persistence status",
)
replace_once(
    technical,
    "Unexpected Agent exits use a durable bounded restart window with exponential backoff and a fixed attempt ceiling. After a driver returns an owned main or Matrix handle, lease publication failure retains that handle fenced until observed exit and same-owner exact cleanup; a failed first signal cannot discard it. Driver-internal setup failure after OS spawn and daemon death before a recoverable lease remain open. Stop/Kill do not yet durably supersede restart claims, and recovery does not yet prove predecessor versus replacement identity. The in-process retry repairs must not be described as complete cross-daemon recovery.",
    "Unexpected Agent exits use a durable bounded restart window with exponential backoff and a fixed attempt ceiling. After a driver returns an owned main or Matrix handle, lease publication failure retains that handle fenced until observed exit and same-owner exact cleanup; a failed first signal cannot discard it. Stop/Kill now durably bind the exact process identity before restart cancellation, lifecycle CAS or signaling; Kill may supersede Stop only for the same target, and recovery restores the original non-resetting deadline. Driver-internal setup failure after OS spawn, daemon death before a recoverable lease, durable Drain and complete predecessor/replacement proof for restart or promotion remain open. These remaining boundaries must not be described as complete cross-daemon recovery.",
    "failure and recovery status",
)
replace_once(
    technical,
    "Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.",
    "Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes. Native control failures are classified at their last durable boundary as `not_started`, `target_identity_stale`, `already_completed`, `persistence_indeterminate` or `recovery_required`; each class carries a distinct next action instead of an unconditional retry instruction.",
    "typed control failure semantics",
)
replace_once(
    technical,
    "The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-supervisor/src/supervisor.rs](../../../codex-rs/hepta-supervisor/src/supervisor.rs) and the linked implementation components.\n\n[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.",
    "The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/runtime.supervisor.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-supervisor/src/supervisor.rs](../../../codex-rs/hepta-supervisor/src/supervisor.rs) and the linked implementation components.\n\nThe daemon records bounded log2 histograms for read-view request latency, lifecycle-owner admission wait, full admitted control-request latency and supervisor mutex wait/hold time. Five-second operational snapshots report p50, p95 and p99 upper bounds plus maximum tick delay. These source metrics do not establish host qualification; selected-host load and soak receipts remain required.\n\n[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.",
    "performance measurements",
)
replace_once(
    technical,
    "Supplying the complete external grant/H7 verifier tuple selects the production release-authority posture: ordinary owner-local `Upgrade` and `Rollback` compatibility RPCs are rejected and release changes must use signed variants. Fleet owns the immutable release catalog plus per-Agent allow/revoke markers. The supervisor snapshots their bounded aggregate admission frontier into every registered source/target transaction and rejects any frontier drift at final start/rollback/recovery use. The deterministic compatibility-binding digest proves the exact source/target pair and policy cut used by this transaction; it is not by itself an independent semantic-compatibility approval. External selection/compatibility policy, signer rotation and deployment remain separately governed evidence.\n\nCurrent operating and state-format references:",
    "Supplying the complete external grant/H7 verifier tuple selects the production release-authority posture: ordinary owner-local `Upgrade` and `Rollback` compatibility RPCs are rejected and release changes must use signed variants. Fleet owns the immutable release catalog plus per-Agent allow/revoke markers. The supervisor snapshots their bounded aggregate admission frontier into every registered source/target transaction and rejects any frontier drift at final start/rollback/recovery use. The deterministic compatibility-binding digest proves the exact source/target pair and policy cut used by this transaction; it is not by itself an independent semantic-compatibility approval. External selection/compatibility policy, signer rotation and deployment remain separately governed evidence.\n\n`ControlDiagnosticsSnapshot` exposes owner-local operation identity, target spawn/runtime generation, current progress, blocker and resource-enforcement capability without command arguments, environment values or paths. `SupervisorOperationalSummary` aggregates target drift, exit wait, restart backoff/exhaustion, release transition, persistence uncertainty, recovery quarantine and control-state unavailability with one Fleet scan. Timeout enforcement is reported as native; memory, subprocess and network limits remain declared-only until a selected host installs and proves them.\n\nCurrent operating and state-format references:",
    "operational diagnostics",
)
replace_once(
    technical,
    "In `codex-rs`, run `just test -p codex-hepta-supervisor` and `just test -p codex-hepta-agentd`. Commands are invocations, not stored pass receipts. Exact-head and deterministic synthetic-merge workflows remain authoritative for the candidate.",
    "For the exact candidate, run `cargo fmt --manifest-path codex-rs/Cargo.toml --all -- --check`; default, `production-authority` and `qualification` all-target checks for `codex-hepta-supervisor`; default and production package tests; `cargo test --manifest-path codex-rs/Cargo.toml --locked -p codex-hepta-agentd`; and strict all-feature Clippy with `-D warnings`. The `Runtime supervisor control recovery` workflow executes every lane independently, uploads exact-SHA logs and fails unless all outcomes succeed. Commands are invocations, not stored pass receipts; exact-head and deterministic synthetic-merge evidence remain authoritative for the candidate.",
    "exact candidate commands",
)
replace_once(
    technical,
    "| B: cross-daemon control | Durable Stop/Kill supersession, predecessor/replacement restart linkage, non-resetting deadlines and durable exit reconciliation remain implementation work. Existing in-memory controls and cleanup witnesses do not close it. |",
    "| B: cross-daemon control | Exact-target durable Stop/Kill, same-target Kill supersession, non-resetting stop deadlines and absent-process terminal reconciliation are implemented as source. Durable Drain, complete predecessor/replacement restart linkage, launch-before-lease crash recovery and retained-handle cleanup evidence remain open. |",
    "stage B status",
)

print("runtime.supervisor semantic materialization complete")
