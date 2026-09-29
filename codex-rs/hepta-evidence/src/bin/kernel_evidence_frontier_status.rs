#![forbid(unsafe_code)]

use std::error::Error;
use std::ffi::OsString;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::LockedFileEvidenceFrontierBackend;

#[derive(Debug, Eq, PartialEq)]
struct StatusArguments {
    backend_root: PathBuf,
    backend_identity_sha256: Sha256Digest,
    local_rollback_root: PathBuf,
    store_id: String,
}

#[derive(Debug)]
struct CliError(String);

impl fmt::Display for CliError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl Error for CliError {}

fn main() -> Result<(), Box<dyn Error>> {
    let arguments = parse_arguments(std::env::args_os().skip(1))?;
    let mut backend = LockedFileEvidenceFrontierBackend::open_external(
        &arguments.backend_root,
        arguments.backend_identity_sha256,
        &arguments.local_rollback_root,
    )?;
    let status = backend.capacity_status(&arguments.store_id)?;
    println!("{}", serde_json::to_string(&status)?);
    Ok(())
}

fn parse_arguments(
    arguments: impl IntoIterator<Item = OsString>,
) -> Result<StatusArguments, CliError> {
    let mut backend_root = None;
    let mut backend_identity_sha256 = None;
    let mut local_rollback_root = None;
    let mut store_id = None;
    let mut arguments = arguments.into_iter();

    while let Some(flag) = arguments.next() {
        let value = arguments.next().ok_or_else(|| {
            CliError(format!("missing value for {}", flag.to_string_lossy()))
        })?;
        let slot = match flag.to_str() {
            Some("--backend-root") => &mut backend_root,
            Some("--backend-identity-sha256") => &mut backend_identity_sha256,
            Some("--local-rollback-root") => &mut local_rollback_root,
            Some("--store-id") => &mut store_id,
            _ => {
                return Err(CliError(format!(
                    "unsupported argument {}",
                    flag.to_string_lossy()
                )));
            }
        };
        if slot.replace(value).is_some() {
            return Err(CliError(format!(
                "duplicate argument {}",
                flag.to_string_lossy()
            )));
        }
    }

    let backend_root = PathBuf::from(required(backend_root, "--backend-root")?);
    let local_rollback_root = PathBuf::from(required(
        local_rollback_root,
        "--local-rollback-root",
    )?);
    if !backend_root.is_absolute() || !local_rollback_root.is_absolute() {
        return Err(CliError(
            "backend and local rollback roots must be absolute".to_string(),
        ));
    }
    let backend_identity_sha256 = required(
        backend_identity_sha256,
        "--backend-identity-sha256",
    )?
    .into_string()
    .map_err(|_| CliError("backend identity digest is not UTF-8".to_string()))?;
    let backend_identity_sha256 = Sha256Digest::parse(backend_identity_sha256)
        .map_err(|error| CliError(format!("invalid backend identity digest: {error}")))?;
    let store_id = required(store_id, "--store-id")?
        .into_string()
        .map_err(|_| CliError("store id is not UTF-8".to_string()))?;
    if store_id.is_empty() {
        return Err(CliError("store id must not be empty".to_string()));
    }

    Ok(StatusArguments {
        backend_root,
        backend_identity_sha256,
        local_rollback_root,
        store_id,
    })
}

fn required(value: Option<OsString>, flag: &str) -> Result<OsString, CliError> {
    value.ok_or_else(|| CliError(format!("missing required argument {flag}")))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_arguments() -> Vec<OsString> {
        vec![
            "--backend-root".into(),
            "/external/evidence".into(),
            "--backend-identity-sha256".into(),
            "11".repeat(32).into(),
            "--local-rollback-root".into(),
            "/var/lib/hepta".into(),
            "--store-id".into(),
            "store:production".into(),
        ]
    }

    #[test]
    fn accepts_one_complete_read_only_status_request() {
        let parsed = parse_arguments(valid_arguments()).expect("valid status arguments");
        assert_eq!(parsed.backend_root, PathBuf::from("/external/evidence"));
        assert_eq!(parsed.local_rollback_root, PathBuf::from("/var/lib/hepta"));
        assert_eq!(parsed.store_id, "store:production");
    }

    #[test]
    fn rejects_missing_duplicate_relative_and_unknown_arguments() {
        let mut missing = valid_arguments();
        missing.truncate(missing.len() - 2);
        assert!(parse_arguments(missing).is_err());

        let mut duplicate = valid_arguments();
        duplicate.extend(["--store-id".into(), "store:replacement".into()]);
        assert!(parse_arguments(duplicate).is_err());

        let mut relative = valid_arguments();
        relative[1] = "relative/backend".into();
        assert!(parse_arguments(relative).is_err());

        let mut unknown = valid_arguments();
        unknown.extend(["--activate".into(), "true".into()]);
        assert!(parse_arguments(unknown).is_err());
    }
}
