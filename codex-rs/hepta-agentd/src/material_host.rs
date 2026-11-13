//! One non-Root Material host for already provisioned files, keys and peers.
//! Root-owned inherited configuration selects one original task and existing
//! ledger. No key, witness, trust distribution, Source or Outcome is invented.

use std::fs::File;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use codex_hepta_learning_ledger::{DurableLedger, LedgerRecovery, LedgerWitnessStore, LedgerWriter};
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

use crate::{AgentdError, CellQ24ModelFilesV1, LoadedCellQ24ModelV1,
    OriginalCellQ24MaterialReceiptFilesV1, OriginalCellQ24MaterialReceiptOwnersV1,
    OriginalCircuitPrefreezeSourceV1};

#[path = "material_host_config.rs"]
mod config;
#[path = "material_host_files.rs"]
mod files;
#[path = "material_host_trust.rs"]
mod trust;
#[path = "material_host_intake.rs"]
mod intake;
#[path = "material_host_workflow.rs"]
mod workflow;
#[path = "material_host_services.rs"]
mod services;

/// One actual connected purpose-specific channel. The protected configuration
/// fixes its peer; the original transport independently checks SO_PEERCRED and
/// the actual retained pidfd. A Root-created socketpair cannot impersonate the
/// separate Material process to its consumers.
pub struct OriginalMaterialChannelFilesV1 {
    pub stream: UnixStream,
    pub original_peer_pidfd: OwnedFd,
}

/// Every descriptor is preheld and consumed once. No path is opened, created,
/// replaced or searched by this entry point. Directories are existing custody
/// handles used by the original ledger's durability checks.
pub struct OriginalMaterialHostFilesV1 {
    pub configuration: File,
    pub evidence_trust: File,
    pub trust_root: File,
    pub signed_distribution: File,
    pub ledger: File,
    pub ledger_witness: File,
    pub ledger_directory: File,
    pub witness_directory: File,
    pub experience: File,
    pub experience_witness: File,
    pub dataset: File,
    pub dataset_witness: File,
    pub experience_key: File,
    pub dataset_key: File,
    pub baseline: CellQ24ModelFilesV1,
    pub source: OriginalMaterialChannelFilesV1,
    pub workflow: OriginalMaterialChannelFilesV1,
    pub experience_command: OriginalMaterialChannelFilesV1,
    pub dataset_command: OriginalMaterialChannelFilesV1,
    pub experience_readback: OriginalMaterialChannelFilesV1,
    pub dataset_readback: OriginalMaterialChannelFilesV1,
    pub dataset_source: OriginalMaterialChannelFilesV1,
}

/// Normal production entry, not a fixture. The four workflow messages carry
/// observations and already signed data; only the unchanged original intake,
/// freeze verifier and concrete Material pair may admit or sign anything.
/// On any error, retain the same files and original submitted signed request.
/// Recovery, witness repair and pair creation can have durable partial effects.
pub fn serve_original_material_host_from_files(files: OriginalMaterialHostFilesV1)
    -> Result<(), AgentdError>
{
    let entered = Instant::now();
    let configuration: config::Configuration = files::read_root(&files.configuration)?;
    configuration.require_process()?;
    let (startup_end, end) = files::original_ends(&configuration, entered)?;
    files::require_all(&files, &configuration)?;
    let trusted = trust::OriginalMaterialTrust::read(
        &files.evidence_trust, &files.trust_root, &files.signed_distribution,
        &configuration.trust, files::now()?,
    )?;
    let request = configuration.original_source_request(&trusted)?;
    let evidence = configuration.source_evidence.original()?;
    let identity = config::Configuration::original_identity(&configuration)?;
    if identity.agent_id.as_str() != request.source.scope.agent_id.as_str() {
        return Err(invalid("Material identity is not the fixed original task identity"));
    }
    let experience_key = files::read_key(files.experience_key, configuration.material.uid)?;
    let dataset_key = files::read_key(files.dataset_key, configuration.material.uid)?;
    for (key, actor) in [(&experience_key, &configuration.experience_actor),
        (&dataset_key, &configuration.dataset_actor)] {
        let signer = trust::OriginalMaterialTrust::signer(&trusted, &config::id(actor)?,
            LearningEvidenceRoleV1::Observer, files::now()?)?;
        if key.verifying_key().to_bytes() != signer.verifying_key {
            return Err(invalid("actual Material key differs from the original enrolled Observer"));
        }
    }
    files::remaining(startup_end)?;
    let binding = config::digest(&configuration.ledger_binding_digest)?;
    let witness = LedgerWitnessStore::recover(files.ledger_witness, binding).map_err(invalid)?;
    // The minimum is the original independent witness, never the suspect
    // ledger's own current head or an unacknowledged recovery fallback.
    let minimum = witness.frontier().map_err(invalid)?.anchor;
    let durable = DurableLedger::recover(files.ledger, binding,
        configuration.maximum_ledger_records, LedgerRecovery::Acknowledged(minimum)).map_err(invalid)?;
    let ledger = Arc::new(Mutex::new(LedgerWriter::from_durable(
        durable, witness, trusted.activation(), &files.ledger_directory, &files.witness_directory,
    ).map_err(invalid)?));
    trusted.require_window(files::now()?)?;
    let baseline = Arc::new(LoadedCellQ24ModelV1::open_files(files.baseline).map_err(invalid)?);
    let mut source = OriginalCircuitPrefreezeSourceV1::from_original_stream(
        request, evidence, identity, Arc::clone(&ledger), files.source.stream,
        configuration.source_root.original(), files.source.original_peer_pidfd,
        Duration::from_millis(500), files::remaining(end)?, startup_end,
    ).map_err(invalid)?;
    let (completed, ready) = workflow::complete_original_material(
        &configuration, &trusted, &mut source, &ledger, &baseline, files.workflow, end,
    )?;
    trusted.require_window(files::now()?)?;
    files::remaining(end)?;
    let experience_witness = FileAnchorWitnessStore::open(files.experience_witness,
        configuration.experience_witness.scope()?, configuration.experience_witness.generation()?,
        configuration.experience_witness.maximum_records).map_err(invalid)?;
    let dataset_witness = FileAnchorWitnessStore::open(files.dataset_witness,
        configuration.dataset_witness.scope()?, configuration.dataset_witness.generation()?,
        configuration.dataset_witness.maximum_records).map_err(invalid)?;
    let pair_files = OriginalCellQ24MaterialReceiptFilesV1 {
        experience: files.experience, experience_witness,
        dataset: files.dataset, dataset_witness,
    };
    let pair = match configuration.operation {
        config::Operation::Create => OriginalCellQ24MaterialReceiptOwnersV1::create(
            pair_files, completed, experience_key, dataset_key),
        config::Operation::Recover => OriginalCellQ24MaterialReceiptOwnersV1::recover(
            pair_files, completed, experience_key, dataset_key),
    }.map_err(invalid)?;
    files::remaining(end)?;
    let owner = OriginalCellQ24MaterialReceiptOwnersV1::into_original_prefreeze_source_command_owner(
        pair, source, baseline,
    ).map_err(invalid)?;
    trusted.require_window(files::now()?)?;
    files::remaining(end)?;
    workflow::PendingReady::acknowledge_original_pair(ready, &trusted)?;
    services::serve_original_material_channels(owner, &configuration, end,
        files.experience_command, files.dataset_command, files.experience_readback,
        files.dataset_readback, files.dataset_source)?;
    trusted.require_window(files::now()?)?;
    files::remaining(end)?;
    Ok(())
}

fn invalid(error: impl std::fmt::Display) -> AgentdError {
    AgentdError::Invalid(error.to_string())
}
