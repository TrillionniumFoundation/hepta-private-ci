use std::ffi::OsString;
use std::io::Read;
use std::path::PathBuf;

use codex_hepta_operator_acceptance::CellSplitTargetHostEvidenceStoreV1;
use codex_hepta_operator_acceptance::CellSplitTargetHostEvidenceTrustPolicyV1;
use codex_hepta_operator_acceptance::PrepareRequest;
use codex_hepta_operator_acceptance::ReadReceiptRequest;
use codex_hepta_operator_acceptance::VerifyRequest;
use codex_hepta_operator_acceptance::prepare;
use codex_hepta_operator_acceptance::require_formal_environment;
#[cfg(unix)]
use codex_hepta_operator_acceptance::run_pinned_cell_split_execution_v1;
use codex_hepta_operator_acceptance::verify_and_seal;
use codex_hepta_operator_acceptance::verify_receipt;

const USAGE: &str = "usage:\n  hepta-operator-acceptance prepare        <qualification-root> <product-audit-root> <sidecar-root> <allowed-signers> <trust-policy> <externally-pinned-trust-policy-sha256>\n  hepta-operator-acceptance verify         <qualification-root> <product-audit-root> <sidecar-root> <allowed-signers> <trust-policy> <externally-pinned-trust-policy-sha256> <detached-signature>\n  hepta-operator-acceptance verify-receipt <qualification-root> <product-audit-root> <sidecar-root> <allowed-signers> <trust-policy> <externally-pinned-trust-policy-sha256>\n  hepta-operator-acceptance cell-split-execution transcript <private-config-json> <externally-pinned-config-sha256>\n  hepta-operator-acceptance target-host-evidence verify <evidence-json|-> <trust-policy-json> <externally-pinned-policy-sha256>\n  hepta-operator-acceptance target-host-evidence ingest <evidence-json|-> <trust-policy-json> <externally-pinned-policy-sha256>\n  hepta-operator-acceptance target-host-evidence store <evidence-json|-> <trust-policy-json> <externally-pinned-policy-sha256> <evidence-store-path>";

fn main() {
    if let Err(error) = run(std::env::args_os().collect()) {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

fn run(arguments: Vec<OsString>) -> Result<(), String> {
    if arguments.get(1).and_then(|value| value.to_str()) == Some("cell-split-execution") {
        return run_cell_split_execution_command(&arguments);
    }
    if arguments.get(1).and_then(|value| value.to_str()) == Some("target-host-evidence") {
        return run_target_host_evidence(&arguments);
    }
    verify_formal_entrypoint()?;
    let command = arguments
        .get(1)
        .and_then(|value| value.to_str())
        .ok_or_else(|| USAGE.to_string())?;
    match command {
        "prepare" if arguments.len() == 8 => {
            let qualification = PathBuf::from(&arguments[2]);
            let product_audit = PathBuf::from(&arguments[3]);
            let sidecar = PathBuf::from(&arguments[4]);
            let allowed_signers = PathBuf::from(&arguments[5]);
            let trust_policy = PathBuf::from(&arguments[6]);
            let policy_sha256 = arguments[7]
                .to_str()
                .ok_or_else(|| "trust-policy digest must be UTF-8".to_string())?;
            let prepared = prepare(PrepareRequest {
                allowed_signers_path: &allowed_signers,
                externally_pinned_trust_policy_sha256: policy_sha256,
                product_audit_root: &product_audit,
                qualification_root: &qualification,
                sidecar_root: &sidecar,
                trust_policy_path: &trust_policy,
            })
            .map_err(|error| error.to_string())?;
            println!(
                "{}",
                serde_json::to_string(&prepared).map_err(|error| error.to_string())?
            );
            Ok(())
        }
        "verify" if arguments.len() == 9 => {
            let qualification = PathBuf::from(&arguments[2]);
            let product_audit = PathBuf::from(&arguments[3]);
            let sidecar = PathBuf::from(&arguments[4]);
            let allowed_signers = PathBuf::from(&arguments[5]);
            let trust_policy = PathBuf::from(&arguments[6]);
            let policy_sha256 = arguments[7]
                .to_str()
                .ok_or_else(|| "trust-policy digest must be UTF-8".to_string())?;
            let signature = PathBuf::from(&arguments[8]);
            let sealed = verify_and_seal(VerifyRequest {
                allowed_signers_path: &allowed_signers,
                externally_pinned_trust_policy_sha256: policy_sha256,
                product_audit_root: &product_audit,
                qualification_root: &qualification,
                sidecar_root: &sidecar,
                signature_path: &signature,
                trust_policy_path: &trust_policy,
            })
            .map_err(|error| error.to_string())?;
            println!(
                "{}",
                serde_json::to_string(&sealed).map_err(|error| error.to_string())?
            );
            Ok(())
        }
        "verify-receipt" if arguments.len() == 8 => {
            let qualification = PathBuf::from(&arguments[2]);
            let product_audit = PathBuf::from(&arguments[3]);
            let sidecar = PathBuf::from(&arguments[4]);
            let allowed_signers = PathBuf::from(&arguments[5]);
            let trust_policy = PathBuf::from(&arguments[6]);
            let policy_sha256 = arguments[7]
                .to_str()
                .ok_or_else(|| "trust-policy digest must be UTF-8".to_string())?;
            let sealed = verify_receipt(ReadReceiptRequest {
                allowed_signers_path: &allowed_signers,
                externally_pinned_trust_policy_sha256: policy_sha256,
                product_audit_root: &product_audit,
                qualification_root: &qualification,
                sidecar_root: &sidecar,
                trust_policy_path: &trust_policy,
            })
            .map_err(|error| error.to_string())?;
            println!(
                "{}",
                serde_json::to_string(&sealed).map_err(|error| error.to_string())?
            );
            Ok(())
        }
        _ => Err(USAGE.to_string()),
    }
}

#[cfg(unix)]
fn run_cell_split_execution_command(arguments: &[OsString]) -> Result<(), String> {
    if arguments.len() != 5 {
        return Err(USAGE.to_string());
    }
    let action = arguments[2]
        .to_str()
        .ok_or_else(|| "cell-split action must be UTF-8".to_string())?;
    let pin = arguments[4]
        .to_str()
        .ok_or_else(|| "cell-split external pin must be UTF-8".to_string())?;
    let result = run_pinned_cell_split_execution_v1(action, &PathBuf::from(&arguments[3]), pin)?;
    println!(
        "{}",
        serde_json::to_string(&result).map_err(|error| error.to_string())?
    );
    Ok(())
}

#[cfg(not(unix))]
fn run_cell_split_execution_command(_arguments: &[OsString]) -> Result<(), String> {
    Err("cell-split Unix effect services are not available on this platform".to_string())
}

fn run_target_host_evidence(arguments: &[OsString]) -> Result<(), String> {
    let command = arguments
        .get(2)
        .and_then(|value| value.to_str())
        .ok_or_else(|| USAGE.to_string())?;
    match command {
        "verify" | "ingest" if arguments.len() == 6 => {
            let externally_pinned_policy_sha256 = arguments[5]
                .to_str()
                .ok_or_else(|| "target-host trust-policy pin must be UTF-8".to_string())?;
            let policy = CellSplitTargetHostEvidenceTrustPolicyV1::from_json_file_pinned(
                PathBuf::from(&arguments[4]),
                externally_pinned_policy_sha256,
            )
            .map_err(|error| error.to_string())?;
            let evidence = read_evidence_input(&arguments[3])?;
            let receipt = CellSplitTargetHostEvidenceStoreV1::verify_bytes(&evidence, &policy)
                .map_err(|error| error.to_string())?;
            println!(
                "{}",
                serde_json::to_string(&receipt).map_err(|error| error.to_string())?
            );
            Ok(())
        }
        "store" if arguments.len() == 7 => {
            let externally_pinned_policy_sha256 = arguments[5]
                .to_str()
                .ok_or_else(|| "target-host trust-policy pin must be UTF-8".to_string())?;
            let policy = CellSplitTargetHostEvidenceTrustPolicyV1::from_json_file_pinned(
                PathBuf::from(&arguments[4]),
                externally_pinned_policy_sha256,
            )
            .map_err(|error| error.to_string())?;
            let evidence = read_evidence_input(&arguments[3])?;
            let envelope = serde_json::from_slice(&evidence)
                .map_err(|error| format!("target-host evidence JSON decode failed: {error}"))?;
            let receipt = CellSplitTargetHostEvidenceStoreV1::persist(
                PathBuf::from(&arguments[6]),
                &envelope,
                &policy,
            )
            .map_err(|error| error.to_string())?;
            println!(
                "{}",
                serde_json::to_string(&receipt).map_err(|error| error.to_string())?
            );
            Ok(())
        }
        _ => Err(USAGE.to_string()),
    }
}

fn read_evidence_input(path: &OsString) -> Result<Vec<u8>, String> {
    if path == "-" {
        let mut bytes = Vec::new();
        std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .map_err(|error| format!("failed reading target-host evidence from stdin: {error}"))?;
        if bytes.len() > 1024 * 1024 {
            return Err("target-host evidence exceeds the 1 MiB read bound".to_string());
        }
        return Ok(bytes);
    }
    let path = PathBuf::from(path);
    codex_hepta_operator_acceptance::CellSplitTargetHostEvidenceStoreV1::read_input(&path)
        .map_err(|error| error.to_string())
}

fn verify_formal_entrypoint() -> Result<(), String> {
    require_formal_environment().map_err(|error| error.to_string())
}
