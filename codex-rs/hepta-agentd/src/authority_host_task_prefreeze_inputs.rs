//! Root-protected disclosure configuration exists before A. It contains no
//! RunStart, Decision, Source result, completed receipt or Dataset freeze.
//! The actual owner must still authenticate every Source/Cell observation.

use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_learning_ledger::{LearningEvidenceRoleV1, SignedLearningEvidenceV1,
    TrustedLearningSignerV1};
use codex_hepta_neuron::{CellCandidateMaskV1, CellScopeV1};
use codex_hepta_types::StableId;
use serde::Deserialize;

use super::{protocol, trust, wire};
use crate::{AgentdError, AgentdRootAuthorityPeer, CircuitTaskSourceInputV1,
    OriginalCellQ24MaterialReceiptConfigV1, OriginalCircuitPrefreezeSourceRequestV1,
    OriginalRootPrefreezeSourceRegistrationV1};
use crate::authority_host_config::{HostAuthorityRegistration, read_root_json};
use crate::HostAuthorityServiceConfig;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DisclosureFile {
    schema_version: u32,
    purpose: String,
    generation_operation_id: String,
    generation_intent_digest: String,
    task_digest: String,
    source: SourceInput,
    ledger_binding_digest: String,
    trust_root: PathBuf,
    signed_distribution: PathBuf,
    trust: trust::OriginalDistributionPin,
    generator_actor: String,
    experience_actor: String,
    dataset_actor: String,
    consumer: Consumer,
    nonce: [u8; 16],
    evidence: GeneratorEvidence,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Consumer {
    uid: u32, gid: u32, pid: u32, boot_id: String, process_start_ticks: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceInput {
    agent_id: String, cell_id: String, run_id: String,
    principal_digest: String, source_frontier: String, objective_digest: String,
    ndu_snapshot_digest: String, monotonic_micros: u64, deadline_micros: u64,
    observation: Vec<u8>, candidates: Vec<Candidate>, lease_duration_ms: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Candidate { candidate_id: String, allowed: bool }

impl SourceInput {
    fn original(self) -> Result<CircuitTaskSourceInputV1, AgentdError> {
        Ok(CircuitTaskSourceInputV1 {
            scope: CellScopeV1 {
                agent_id: StableId::new(self.agent_id).map_err(protocol)?,
                cell_id: StableId::new(self.cell_id).map_err(protocol)?,
                run_id: StableId::new(self.run_id).map_err(protocol)?,
                principal_digest: trust::digest(&self.principal_digest)?,
            },
            source_frontier: trust::digest(&self.source_frontier)?,
            objective_digest: trust::digest(&self.objective_digest)?,
            ndu_snapshot_digest: trust::digest(&self.ndu_snapshot_digest)?,
            monotonic_micros: self.monotonic_micros, deadline_micros: self.deadline_micros,
            observation: self.observation,
            candidates: self.candidates.into_iter().map(|candidate| {
                Ok(CellCandidateMaskV1 {
                    candidate_id: StableId::new(candidate.candidate_id).map_err(protocol)?,
                    allowed: candidate.allowed,
                })
            }).collect::<Result<_, AgentdError>>()?,
            lease_duration_ms: self.lease_duration_ms,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct GeneratorEvidence {
    evidence_id: String, principal_id: String, trust_digest: String,
    scope_digest: String, objective_digest: String, authority_epoch: u64,
    issued_at: u64, expires_at: u64, payload_digest: String, signature: String,
}

impl GeneratorEvidence {
    fn original(self) -> Result<SignedLearningEvidenceV1, AgentdError> {
        let signature = STANDARD_NO_PAD.decode(&self.signature).map_err(protocol)?;
        if signature.len() != 64 || STANDARD_NO_PAD.encode(&signature) != self.signature {
            return Err(protocol("original disclosure signature encoding differs"));
        }
        Ok(SignedLearningEvidenceV1 {
            evidence_id: StableId::new(self.evidence_id).map_err(protocol)?,
            principal_id: StableId::new(self.principal_id).map_err(protocol)?,
            role: LearningEvidenceRoleV1::Generator,
            trust_digest: trust::digest(&self.trust_digest)?,
            scope_digest: trust::digest(&self.scope_digest)?,
            objective_digest: trust::digest(&self.objective_digest)?,
            authority_epoch: self.authority_epoch, issued_at: self.issued_at,
            expires_at: self.expires_at, payload_digest: trust::digest(&self.payload_digest)?,
            signature: signature.try_into().map_err(|_| protocol("original disclosure signature width differs"))?,
        })
    }
}

/// Private retained data joins the pre-A enrollment to the later signed
/// Material configuration. This is not a public reader or a Source owner.
pub(crate) struct OriginalTaskPrefreezeState {
    trust: trust::OriginalSourceTrust,
    source: CircuitTaskSourceInputV1,
    experience: TrustedLearningSignerV1,
    dataset: TrustedLearningSignerV1,
}

pub(crate) fn prepare_original_task_prefreeze(
    config: &HostAuthorityServiceConfig, original: &HostAuthorityRegistration,
    disclosure_file: &Path, trusted_evidence: &Path,
    stream: UnixStream, original_consumer_pidfd: OwnedFd, startup_end: Instant,
) -> Result<(OriginalRootPrefreezeSourceRegistrationV1, OriginalTaskPrefreezeState), AgentdError> {
    wire::remaining(startup_end)?;
    let value: DisclosureFile = read_root_json(disclosure_file)?;
    if value.schema_version != 1
        || value.purpose != "hepta.root.original-task-prefreeze-disclosure.v1"
        || matches!(value.consumer.uid, 0 | u32::MAX)
        || matches!(value.consumer.gid, 0 | u32::MAX)
        || value.consumer.pid == original.peer_pid || value.consumer.pid == std::process::id()
        || value.nonce == [0; 16] || config.peer_uid == 0
    { return Err(protocol("protected original pre-freeze disclosure differs")); }
    let at = now()?;
    let trust = trust::OriginalSourceTrust::read_original_signed_distribution(trusted_evidence, &value.trust_root,
        &value.signed_distribution, &value.trust, at)?;
    let generator = trust.original_signer(&StableId::new(value.generator_actor).map_err(protocol)?,
        LearningEvidenceRoleV1::Generator, at)?;
    let experience = trust.original_signer(&StableId::new(value.experience_actor).map_err(protocol)?,
        LearningEvidenceRoleV1::Observer, at)?;
    let dataset = trust.original_signer(&StableId::new(value.dataset_actor).map_err(protocol)?,
        LearningEvidenceRoleV1::Observer, at)?;
    let consumer = AgentdRootAuthorityPeer { pid: value.consumer.pid,
        boot_id: value.consumer.boot_id, process_start_ticks: value.consumer.process_start_ticks };
    wire::Process::require_original(&wire::Process::from_peer(&consumer))?;
    crate::authority_host_runtime::verify_process_credentials(consumer.pid, value.consumer.uid, value.consumer.gid)?;
    crate::root_production_handoff::require_original_resident_process_pin(&original_consumer_pidfd, consumer.pid)?;
    let activated = trust.original_activation();
    let source = value.source.original()?;
    let request = OriginalCircuitPrefreezeSourceRequestV1 {
        generation_operation_id: value.generation_operation_id,
        generation_intent_digest: trust::digest(&value.generation_intent_digest)?,
        task_digest: trust::digest(&value.task_digest)?, source: source.clone(),
        ledger_binding_digest: trust::digest(&value.ledger_binding_digest)?,
        evidence_trust_digest: activated.verifier().trust_digest(),
        trust_distribution_digest: activated.distribution_digest(), trust_generation: activated.generation(),
        generator, experience_signer: experience.clone(), dataset_signer: dataset.clone(),
        consumer, consumer_uid: value.consumer.uid, nonce: value.nonce,
    };
    // The same fixed request is authenticated below, before its stream can be
    // served. Root's file authorizes disclosure; the Generator cannot choose a
    // different task, recipient or trust by sending a different signed request.
    let registration = OriginalRootPrefreezeSourceRegistrationV1::from_original_supervisor(
        request, activated, value.evidence.original()?, original_consumer_pidfd, stream, startup_end,
    )?;
    trust.require_original_distribution_window(now()?)?;
    wire::remaining(startup_end)?;
    Ok((registration, OriginalTaskPrefreezeState { trust, source, experience, dataset }))
}

impl OriginalTaskPrefreezeState {
    pub(crate) fn require_original_prefreeze_trust(&self) -> Result<(), AgentdError> {
        self.trust.require_original_distribution_window(now()?)?;
        Ok(())
    }

    pub(super) fn evidence(&self) -> &trust::OriginalHostTrust { &self.trust.evidence }

    pub(super) fn require_material(&self, material: &OriginalCellQ24MaterialReceiptConfigV1)
        -> Result<(), AgentdError>
    {
        self.trust.require_original_distribution_window(now()?)?;
        let initial = &material.initial;
        if material.verifier.trust_digest() != self.trust.evidence.verifier.trust_digest()
            || material.experience_signer != self.experience || material.dataset_signer != self.dataset
            || initial.owners.experience != self.experience.principal.principal_id
            || initial.owners.dataset != self.dataset.principal.principal_id
            || initial.owners.evidence_trust_digest != self.trust.evidence.verifier.trust_digest()
            || initial.request.agent_id != self.source.scope.agent_id
            || initial.request.cell_id != self.source.scope.cell_id
            || initial.request.source_run_id != self.source.scope.run_id
            || initial.request.principal_id.as_str() != self.source.scope.principal_digest.to_string()
            || initial.request.envelope.objective_digest != self.source.objective_digest
        { return Err(protocol("late Material differs from the original pre-freeze enrollment")); }
        Ok(())
    }
}

fn now() -> Result<u64, AgentdError> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH).map_err(protocol)?.as_secs())
}
