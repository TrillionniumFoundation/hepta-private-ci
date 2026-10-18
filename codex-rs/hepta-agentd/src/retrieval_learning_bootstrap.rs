//! Recovery-only ordinary-process composition of the existing product writer.
//! The host pins the complete descriptor, including signed trust and a minimum
//! independently retained acknowledgement. Missing stores never become empty
//! stores. File placement does not itself establish independent retention.

use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agent_components::learning_ledger::DurableLedger;
use codex_hepta_agent_components::learning_ledger::LedgerRecovery;
use codex_hepta_agent_components::learning_ledger::LedgerWitnessStore;
use codex_hepta_agent_components::learning_ledger::LedgerWriter;
use codex_hepta_agent_components::types::Digest32;
use serde::Deserialize;

use crate::AgentdIdentity;
use crate::CognitiveRetrievalLearningSink;
use crate::cognitive_retrieval_learning::RetrievalLearningAdmission;

#[path = "retrieval_learning_files.rs"]
mod files;
#[path = "retrieval_learning_trust.rs"]
mod trust;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    schema: String,
    owner_id: String,
    body_generation: u64,
    ledger_path: PathBuf,
    witness_path: PathBuf,
    #[serde(deserialize_with = "trust::digest")]
    ledger_binding: Digest32,
    maximum_records: usize,
    minimum_acknowledged_sequence: u64,
    #[serde(deserialize_with = "trust::digest")]
    minimum_acknowledged_chain_digest: Digest32,
    trust: trust::Trust,
}

/// Explicit host launch inputs only, never a request field or an ambient path.
/// Provisioning/creation and protection of the independent witness remain with
/// the learning owner. A trust rotation requires a newly pinned host launch.
pub fn load_retrieval_learning_bootstrap_v1(
    path: &Path,
    expected_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<Arc<CognitiveRetrievalLearningSink>, String> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| error.to_string())?
        .as_secs();
    load_at(path, expected_digest, identity, now)
}

fn load_at(
    path: &Path,
    expected_digest: Digest32,
    identity: &AgentdIdentity,
    now: u64,
) -> Result<Arc<CognitiveRetrievalLearningSink>, String> {
    if expected_digest.is_zero() {
        return Err("retrieval learning descriptor requires a nonzero pin".to_string());
    }
    let raw = files::read(path, &identity.home_root, 65_536)?;
    if Digest32::of_bytes(&raw) != expected_digest {
        return Err("retrieval learning descriptor pin mismatch".to_string());
    }
    let descriptor: Descriptor = serde_json::from_slice(&raw).map_err(|error| error.to_string())?;
    if descriptor.schema != "hepta.agentd.retrieval-learning-bootstrap.v1"
        || descriptor.owner_id != identity.agent_id.as_str()
        || descriptor.body_generation != identity.spawn_generation
        || descriptor.body_generation == 0
        || descriptor.ledger_binding.is_zero()
        || !(1..=8192).contains(&descriptor.maximum_records)
        || descriptor.minimum_acknowledged_sequence > descriptor.maximum_records as u64
        || (descriptor.minimum_acknowledged_sequence == 0)
            != descriptor.minimum_acknowledged_chain_digest.is_zero()
        || descriptor.ledger_path.parent() == descriptor.witness_path.parent()
        || descriptor.ledger_path.starts_with(&identity.run_root)
        || descriptor.witness_path.starts_with(&identity.run_root)
        || path.starts_with(&identity.run_root)
    {
        return Err(
            "retrieval learning bootstrap identity, bounds or owner separation is invalid"
                .to_string(),
        );
    }
    let expires_at = descriptor.trust.admission_expires_at();
    let monotonic_expiry = std::time::Instant::now()
        .checked_add(std::time::Duration::from_secs(
            expires_at
                .checked_sub(now)
                .and_then(|remaining| remaining.checked_add(1))
                .ok_or("retrieval learning trust has no current lifetime")?,
        ))
        .ok_or("retrieval learning trust lifetime exceeded clock range")?;
    let trust = descriptor.trust.activate(now)?;
    let witness_file = files::open(
        &descriptor.witness_path,
        &identity.home_root,
        1_000_000,
        true,
    )?;
    let witness = LedgerWitnessStore::recover(witness_file, descriptor.ledger_binding)
        .map_err(|error| error.to_string())?;
    let frontier = witness.frontier().map_err(|error| error.to_string())?;
    if frontier.segment.is_some()
        || frontier.sealed
        || frontier.anchor.sequence < descriptor.minimum_acknowledged_sequence
    {
        return Err(
            "retrieval learning independent witness is stale or has another backend".to_string(),
        );
    }
    let ledger_file = files::open(
        &descriptor.ledger_path,
        &identity.home_root,
        8 * 1024 * 1024,
        true,
    )?;
    let ledger = if frontier.anchor.sequence == 0 {
        if !frontier.anchor.chain_digest.is_zero() {
            return Err("retrieval learning empty witness has a nonempty digest".to_string());
        }
        DurableLedger::recover_initialized_empty(
            ledger_file,
            descriptor.ledger_binding,
            descriptor.maximum_records,
        )
    } else {
        DurableLedger::recover(
            ledger_file,
            descriptor.ledger_binding,
            descriptor.maximum_records,
            LedgerRecovery::Acknowledged(frontier.anchor),
        )
    }
    .map_err(|error| error.to_string())?;
    if descriptor.minimum_acknowledged_sequence > 0 {
        let index = usize::try_from(descriptor.minimum_acknowledged_sequence - 1)
            .map_err(|error| error.to_string())?;
        if ledger
            .records()
            .map_err(|error| error.to_string())?
            .get(index)
            .map(|record| record.chain_digest)
            != Some(descriptor.minimum_acknowledged_chain_digest)
        {
            return Err(
                "retrieval learning minimum acknowledgement does not match history".to_string(),
            );
        }
    }
    let ledger_directory = File::open(
        descriptor
            .ledger_path
            .parent()
            .ok_or("missing ledger directory")?,
    )
    .map_err(|error| error.to_string())?;
    let witness_directory = File::open(
        descriptor
            .witness_path
            .parent()
            .ok_or("missing witness directory")?,
    )
    .map_err(|error| error.to_string())?;
    let writer = LedgerWriter::from_durable(
        ledger,
        witness,
        trust,
        &ledger_directory,
        &witness_directory,
    )
    .map_err(|error| error.to_string())?;
    Ok(Arc::new(CognitiveRetrievalLearningSink::with_admission(
        writer,
        RetrievalLearningAdmission {
            owner: identity.agent_id.clone(),
            body_generation: identity.spawn_generation,
            expires_at_unix_s: expires_at,
            expires_at: monotonic_expiry,
        },
    )))
}

#[cfg(all(test, unix))]
#[path = "retrieval_learning_bootstrap_tests.rs"]
mod tests;
