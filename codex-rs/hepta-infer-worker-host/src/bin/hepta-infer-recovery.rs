use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_infer_core::control_contracts::SignedExecutionAuthorityBundle;
use codex_hepta_infer_core::control_contracts::TrustKey;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::recovery_contracts::SignedRecoveryIndeterminateRetirement;
use codex_hepta_infer_core::recovery_contracts::SignedRecoveryReconciliationReceipt;
use codex_hepta_infer_core::recovery_contracts::verify_execution_plan_for_recovery;
use codex_hepta_infer_core::recovery_contracts::verify_recovery_reconciliation_receipt;
use codex_hepta_infer_core::recovery_contracts::verify_recovery_retirement;
use serde::Deserialize;
use serde::de::DeserializeOwned;

const MAX_DOCUMENT_BYTES: u64 = 1024 * 1024;
const JOURNAL_CAPACITY: usize = 16_384;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustStoreDocument {
    schema_version: u32,
    keys: Vec<TrustKey>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Operation {
    Reconcile,
    Retire,
}

fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let mut args = std::env::args().skip(1);
    let operation = match args.next().as_deref() {
        Some("reconcile") => Operation::Reconcile,
        Some("retire") => Operation::Retire,
        Some("--help") | None => {
            print_help();
            return Ok(());
        }
        Some(value) => return Err(format!("unsupported recovery operation: {value}").into()),
    };
    let mut journal = None;
    let mut trust_store = None;
    let mut execution_bundle = None;
    let mut evidence = None;
    while let Some(flag) = args.next() {
        if flag == "--help" {
            print_help();
            return Ok(());
        }
        let value = args.next().ok_or("missing argument value")?;
        match flag.as_str() {
            "--journal" => journal = Some(PathBuf::from(value)),
            "--trust-store" => trust_store = Some(PathBuf::from(value)),
            "--execution-authority-bundle" => execution_bundle = Some(PathBuf::from(value)),
            "--evidence" => evidence = Some(PathBuf::from(value)),
            _ => return Err(format!("unknown argument: {flag}").into()),
        }
    }

    let journal = required_absolute(journal, "--journal")?;
    let trust_store = required_absolute(trust_store, "--trust-store")?;
    let execution_bundle = required_absolute(
        execution_bundle,
        "--execution-authority-bundle",
    )?;
    let evidence = required_absolute(evidence, "--evidence")?;

    let trust: TrustStoreDocument = read_owner_only_json(&trust_store, "trust store")?;
    if trust.schema_version != 1 {
        return Err("unsupported trust-store schema".into());
    }
    let signed_bundle: SignedExecutionAuthorityBundle =
        read_owner_only_json(&execution_bundle, "execution authority bundle")?;
    let recovery_plan = verify_execution_plan_for_recovery(&trust.keys, &signed_bundle)?;
    let now_unix_ms = unix_time_ms()?;
    let mut control = DurableInferenceControl::open(&journal, JOURNAL_CAPACITY)?;

    let record = match operation {
        Operation::Reconcile => {
            let signed: SignedRecoveryReconciliationReceipt =
                read_owner_only_json(&evidence, "reconciliation receipt")?;
            if signed.receipt.request_id != recovery_plan.request_id() {
                return Err("reconciliation receipt request does not match execution bundle".into());
            }
            let verified = verify_recovery_reconciliation_receipt(
                now_unix_ms,
                &trust.keys,
                &recovery_plan,
                &signed,
            )?;
            control.reconcile_native_recovery(
                recovery_plan.request_id(),
                &recovery_plan,
                &verified,
            )?
        }
        Operation::Retire => {
            let signed: SignedRecoveryIndeterminateRetirement =
                read_owner_only_json(&evidence, "retirement approval")?;
            if signed.retirement.request_id != recovery_plan.request_id() {
                return Err("retirement request does not match execution bundle".into());
            }
            let verified = verify_recovery_retirement(
                now_unix_ms,
                &trust.keys,
                &recovery_plan,
                &signed,
            )?;
            control.retire_native_indeterminate_recovery(
                recovery_plan.request_id(),
                &recovery_plan,
                &verified,
            )?
        }
    };

    println!("{}", serde_json::to_string(&record)?);
    Ok(())
}

fn print_help() {
    println!(
        "hepta-infer-recovery <reconcile|retire> --journal ABSOLUTE_PATH --trust-store ABSOLUTE_JSON --execution-authority-bundle ABSOLUTE_JSON --evidence ABSOLUTE_JSON\n\nNo force-release mode exists. `reconcile` requires a fresh signed terminal/usage receipt. `retire` requires two distinct operator signatures over the exact request, dispatch digest and current record revision."
    );
}

fn required_absolute(
    value: Option<PathBuf>,
    flag: &str,
) -> Result<PathBuf, Box<dyn std::error::Error + Send + Sync>> {
    let value = value.ok_or_else(|| format!("{flag} is required"))?;
    if !value.is_absolute() {
        return Err(format!("{flag} must be absolute").into());
    }
    Ok(value)
}

fn read_owner_only_json<T: DeserializeOwned>(
    path: &Path,
    label: &str,
) -> Result<T, Box<dyn std::error::Error + Send + Sync>> {
    let metadata = fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(format!("{label} must be a regular non-symlink file").into());
    }
    if metadata.len() == 0 || metadata.len() > MAX_DOCUMENT_BYTES {
        return Err(format!("{label} size is outside the accepted bound").into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(format!("{label} must be owner-only").into());
        }
    }
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

fn unix_time_ms() -> Result<u64, Box<dyn std::error::Error + Send + Sync>> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_millis()
        .try_into()?)
}
