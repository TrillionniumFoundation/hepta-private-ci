#!/usr/bin/env python3
"""Apply the one-time runtime.fleet process-admission daemon migration."""

from pathlib import Path


def replace_checked(text: str, old: str, new: str, *, count: int = 1, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise SystemExit(
            f"{label} migration expected {count} occurrence(s), found {actual}: {old!r}"
        )
    return text.replace(old, new)


path = Path("codex-rs/hepta-supervisor/src/daemon.rs")
text = path.read_text(encoding="utf-8")
text = replace_checked(
    text,
    "#[cfg(unix)]\nuse crate::AgentRelease;",
    "#[cfg(unix)]\nuse crate::AdmissionProcessDriver;\n#[cfg(unix)]\nuse crate::AgentRelease;",
    label="daemon",
)
text = replace_checked(
    text,
    "use crate::SupervisorError;\n#[cfg(unix)]\nuse crate::UnixProcessDriver;",
    "use crate::SharedProcessAdmission;\nuse crate::SupervisorError;\n#[cfg(unix)]\nuse crate::UnixProcessDriver;",
    label="daemon",
)
text = replace_checked(
    text,
    "run_supervisord_inner(fleet_root, cancellation, None).await",
    "run_supervisord_inner(fleet_root, cancellation, None, None).await",
    label="daemon",
)
text = replace_checked(
    text,
    "run_supervisord_inner(fleet_root, cancellation, Some(verifier)).await",
    "run_supervisord_inner(fleet_root, cancellation, Some(verifier), None).await",
    label="daemon",
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
text = replace_checked(
    text,
    "    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n) -> Result<(), SupervisorError> {",
    "    production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n    process_admission: Option<SharedProcessAdmission>,\n) -> Result<(), SupervisorError> {",
    label="daemon",
)
text = replace_checked(
    text,
    "    _production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n) -> Result<(), SupervisorError> {",
    "    _production_grant_verifier: Option<H7H89ProductionGrantVerifier>,\n    _process_admission: Option<SharedProcessAdmission>,\n) -> Result<(), SupervisorError> {",
    label="daemon",
)
text = replace_checked(
    text,
    "    let driver =\n        UnixProcessDriver::new(256).map_err(|error| SupervisorError::Invalid(error.to_string()))?;\n    let (supervisor, recovery) = Supervisor::recover(",
    "    let driver =\n        UnixProcessDriver::new(256).map_err(|error| SupervisorError::Invalid(error.to_string()))?;\n    let driver = AdmissionProcessDriver::new(driver, process_admission);\n    let (supervisor, recovery) = Supervisor::recover(",
    label="daemon",
)
text = replace_checked(
    text,
    "DaemonState<UnixProcessDriver>",
    "DaemonState<AdmissionProcessDriver<UnixProcessDriver>>",
    count=2,
    label="daemon",
)
path.write_text(text, encoding="utf-8")

path = Path("codex-rs/hepta-supervisor/src/fleet_process_admission.rs")
text = path.read_text(encoding="utf-8")
text = replace_checked(
    text,
    '''fn load_profile(path: &Path) -> Result<ValidatedProfileV1, ProcessDriverError> {
    let path = path.canonicalize().map_err(ProcessDriverError::from)?;
    if !path.is_absolute() {
        return Err(ProcessDriverError::new(
            "runtime.fleet final-use profile path must be absolute",
        ));
    }
    let metadata = std::fs::symlink_metadata(&path).map_err(ProcessDriverError::from)?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_FLEET_PROCESS_ADMISSION_PROFILE_BYTES
    {''',
    '''fn load_profile(path: &Path) -> Result<ValidatedProfileV1, ProcessDriverError> {
    if !path.is_absolute() {
        return Err(ProcessDriverError::new(
            "runtime.fleet final-use profile path must be absolute",
        ));
    }
    let metadata = std::fs::symlink_metadata(path).map_err(ProcessDriverError::from)?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_FLEET_PROCESS_ADMISSION_PROFILE_BYTES
    {''',
    label="final-use profile",
)
text = replace_checked(
    text,
    '''        return Err(ProcessDriverError::new(
            "runtime.fleet final-use profile must be a bounded regular file",
        ));
    }
    #[cfg(unix)]''',
    '''        return Err(ProcessDriverError::new(
            "runtime.fleet final-use profile must be a bounded regular file",
        ));
    }
    let canonical = path.canonicalize().map_err(ProcessDriverError::from)?;
    if canonical != path {
        return Err(ProcessDriverError::new(
            "runtime.fleet final-use profile path must be canonical and symlink-free",
        ));
    }
    #[cfg(unix)]''',
    label="final-use profile",
)
text = replace_checked(
    text,
    '''    let profile: FleetProcessAdmissionProfileV1 =
        serde_json::from_slice(&std::fs::read(&path).map_err(ProcessDriverError::from)?)''',
    '''    let profile: FleetProcessAdmissionProfileV1 =
        serde_json::from_slice(&std::fs::read(&canonical).map_err(ProcessDriverError::from)?)''',
    label="final-use profile",
)
text = replace_checked(
    text,
    '''    if value.len() != 64 {
        return Err(ProcessDriverError::new(
            "runtime.fleet verifying key must be 64 lowercase hex digits",
        ));
    }
    let mut output = [0_u8; 32];''',
    '''    if value.len() != 64 || value.bytes().all(|byte| byte == b'0') {
        return Err(ProcessDriverError::new(
            "runtime.fleet verifying key must be 64 non-zero lowercase hex digits",
        ));
    }
    let mut output = [0_u8; 32];''',
    label="final-use profile",
)
text = replace_checked(
    text,
    '''fn canonical_physical_directory(
    path: PathBuf,
    label: &str,
) -> Result<PathBuf, ProcessDriverError> {
    if !path.is_absolute() {
        return Err(ProcessDriverError::new(format!("{label} must be absolute")));
    }
    let canonical = path.canonicalize().map_err(ProcessDriverError::from)?;
    let metadata = std::fs::symlink_metadata(&canonical).map_err(ProcessDriverError::from)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(ProcessDriverError::new(format!(
            "{label} must be a physical directory"
        )));
    }
    Ok(canonical)
}''',
    '''fn canonical_physical_directory(
    path: PathBuf,
    label: &str,
) -> Result<PathBuf, ProcessDriverError> {
    if !path.is_absolute() {
        return Err(ProcessDriverError::new(format!("{label} must be absolute")));
    }
    let metadata = std::fs::symlink_metadata(&path).map_err(ProcessDriverError::from)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(ProcessDriverError::new(format!(
            "{label} must be a physical directory"
        )));
    }
    let canonical = path.canonicalize().map_err(ProcessDriverError::from)?;
    if canonical != path {
        return Err(ProcessDriverError::new(format!(
            "{label} must be canonical and symlink-free"
        )));
    }
    Ok(canonical)
}''',
    label="final-use profile",
)
text = replace_checked(
    text,
    '''        assert!(decode_key(&"A".repeat(64)).is_err());
        assert_eq!(decode_key(&"0".repeat(64)).expect("shape-valid key"), [0; 32]);''',
    '''        assert!(decode_key(&"A".repeat(64)).is_err());
        assert!(decode_key(&"0".repeat(64)).is_err());''',
    label="final-use profile",
)
path.write_text(text, encoding="utf-8")

path = Path("codex-rs/hepta-supervisor/src/admission_driver.rs")
text = path.read_text(encoding="utf-8")
text = replace_checked(
    text,
    'ProcessIdentity::new(1, "never-spawned".into())',
    'ProcessIdentity::new(1, "never-spawned".to_string())',
    label="admission driver",
)
path.write_text(text, encoding="utf-8")
