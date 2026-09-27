#!/usr/bin/env python3
"""Apply the one-time runtime.fleet process-admission daemon migration."""

from pathlib import Path

PATH = Path("codex-rs/hepta-supervisor/src/daemon.rs")
text = PATH.read_text(encoding="utf-8")


def replace_exact(old: str, new: str, *, count: int = 1) -> None:
    global text
    actual = text.count(old)
    if actual != count:
        raise SystemExit(
            f"daemon migration expected {count} occurrence(s), found {actual}: {old!r}"
        )
    text = text.replace(old, new)


replace_exact(
    "#[cfg(unix)]\nuse crate::AgentRelease;",
    "#[cfg(unix)]\nuse crate::AdmissionProcessDriver;\n#[cfg(unix)]\nuse crate::AgentRelease;",
)
replace_exact(
    "use crate::SupervisorError;\n#[cfg(unix)]\nuse crate::UnixProcessDriver;",
    "use crate::SharedProcessAdmission;\nuse crate::SupervisorError;\n#[cfg(unix)]\nuse crate::UnixProcessDriver;",
)
replace_exact(
    "run_supervisord_inner(fleet_root, cancellation, None).await",
    "run_supervisord_inner(fleet_root, cancellation, None, None).await",
)
replace_exact(
    "run_supervisord_inner(fleet_root, cancellation, Some(verifier)).await",
    "run_supervisord_inner(fleet_root, cancellation, Some(verifier), None).await",
)

marker = "#[cfg(unix)]\nasync fn run_supervisord_inner("
if text.count(marker) != 1:
    raise SystemExit("daemon migration could not locate the Unix owner entry point")
product_entry = '''/// Product entry point that installs a final-use process admission guard at the
/// exact spawn/adopt effect boundary. The admission object is independently
/// configured by the product host; the daemon never derives trust roots from a
/// mutation request or from the durable revocation snapshot itself.
pub async fn run_supervisord_with_product_controls(
    fleet_root: HeptaFleetRoot,
    cancellation: CancellationToken,
    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,
    process_admission: SharedProcessAdmission,
) -> Result<(), SupervisorError> {
    if production_grant_verifier.is_some() && !PRODUCTION_AUTHORITY_FEATURE_ENABLED {
        return Err(SupervisorError::ProductionAuthorityFeatureDisabled);
    }
    run_supervisord_inner(
        fleet_root,
        cancellation,
        production_grant_verifier,
        Some(process_admission),
    )
    .await
}

'''
text = text.replace(marker, product_entry + marker)

replace_exact(
    "    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n) -> Result<(), SupervisorError> {",
    "    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n    process_admission: Option<SharedProcessAdmission>,\n) -> Result<(), SupervisorError> {",
    count=2,
)
replace_exact(
    "    let driver =\n        UnixProcessDriver::new(256).map_err(|error| SupervisorError::Invalid(error.to_string()))?;\n    let (supervisor, recovery) = Supervisor::recover(",
    "    let driver =\n        UnixProcessDriver::new(256).map_err(|error| SupervisorError::Invalid(error.to_string()))?;\n    let driver = AdmissionProcessDriver::new(driver, process_admission);\n    let (supervisor, recovery) = Supervisor::recover(",
)
replace_exact(
    "DaemonState<UnixProcessDriver>",
    "DaemonState<AdmissionProcessDriver<UnixProcessDriver>>",
    count=2,
)
replace_exact(
    "    _production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n    process_admission: Option<SharedProcessAdmission>,",
    "    _production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n    _process_admission: Option<SharedProcessAdmission>,",
)

PATH.write_text(text, encoding="utf-8")
