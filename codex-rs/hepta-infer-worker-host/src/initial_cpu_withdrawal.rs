//! Fixed Root-only development withdrawal using the actual calibrated writer,
//! independently verified replacement and original artifact checkpoint/ACK.
use super::*;
use serde::Serialize;
use std::path::PathBuf;
#[path = "initial_cpu_withdrawal_issuance.rs"]
mod issuance;
#[path = "initial_cpu_withdrawal_source.rs"]
mod source;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema: String,
    owner: Source,
    replacement: Source,
    replacement_index: usize,
    calibration_publication: Source,
    calibration_archive: Source,
    calibration_trust_config: Source,
    ledger_directory: PathBuf,
    witness_directory: PathBuf,
    unlearning_private_key_path: PathBuf,
    record_id: String,
    lineage_id: String,
    source_record_id: String,
    artifact_id: String,
    reason_digest: String,
    expected_ledger_head: String,
    expected_artifact_head: String,
    delivery_targets: Vec<String>,
    previous_withdrawals: Vec<Notice>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Notice {
    notice_id: String,
    dataset_digest: String,
    source_tombstone_digest: String,
    authority_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    authority_epoch: u64,
    issued_at: u64,
}
impl Notice {
    fn native(&self) -> HostResult<DatasetWithdrawalNoticeV1> {
        Ok(DatasetWithdrawalNoticeV1 {
            notice_id: id(&self.notice_id)?,
            dataset_digest: digest(&self.dataset_digest)?,
            source_tombstone_digest: digest(&self.source_tombstone_digest)?,
            authority_id: id(&self.authority_id)?,
            credential_chain_digest: digest(&self.credential_chain_digest)?,
            signing_key_digest: digest(&self.signing_key_digest)?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
        })
    }
}

