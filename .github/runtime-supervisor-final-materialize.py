from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
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

print("runtime.supervisor semantic materialization complete")
