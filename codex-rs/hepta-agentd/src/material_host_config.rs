//! Fixed data from an inherited Root0600 supervisor file. None of these
//! records is a Source publication, receipt, admission, grant or live owner.

use std::path::Component;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_neuron::{CellCandidateMaskV1, CellScopeV1, JournalScope};
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::{Digest32, Generation, StableId};
use serde::Deserialize;
use crate::{AgentdError, AgentdIdentity, AgentdRootAuthorityPeer, CellQ24DatasetRuleV1,
    CellQ24PrivateHeadV1, CircuitTaskSourceInputV1, HostAuthorityRegisteredIdentity,
    OriginalCircuitPrefreezeSourceRequestV1};
use super::{files, invalid, trust};

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum Operation { Create, Recover }

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Configuration {
    pub schema_version: u32,
    pub purpose: String,
    pub operation: Operation,
    pub material: Recipient,
    pub source_root: Peer,
    pub source_root_gid: u32,
    pub workflow_root: Peer,
    pub workflow_root_gid: u32,
    pub registered_identity: HostAuthorityRegisteredIdentity,
    pub startup_deadline_monotonic_ns: u64,
    pub lifetime_deadline_monotonic_ns: u64,
    pub generation_operation_id: String,
    pub generation_intent_digest: String,
    pub task_digest: String,
    pub source: SourceInput,
    pub ledger_binding_digest: String,
    pub maximum_ledger_records: usize,
    pub ledger_name: String,
    pub ledger_witness_name: String,
    pub trust: trust::TrustPin,
    pub generator_actor: String,
    pub experience_actor: String,
    pub dataset_actor: String,
    pub nonce: [u8; 16],
    pub source_evidence: trust::Evidence,
    pub experience_witness: Witness,
    pub dataset_witness: Witness,
    pub snapshot_id: String,
    pub update_scope: UpdateScope,
    pub update_rule: String,
    pub head: Head,
    pub unit_profile_digest: String,
    pub maximum_signature_lifetime_seconds: u64,
    pub experience_command: ServicePeer,
    pub dataset_command: ServicePeer,
    pub experience_readback: ServicePeer,
    pub dataset_readback: ServicePeer,
    pub dataset_source: ServicePeer,
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Peer { pub pid: u32, pub boot_id: String, pub process_start_ticks: u64 }

impl Peer {
    pub(super) fn original(&self) -> AgentdRootAuthorityPeer {
        AgentdRootAuthorityPeer { pid: self.pid, boot_id: self.boot_id.clone(),
            process_start_ticks: self.process_start_ticks }
    }
    pub(super) fn require_live(&self, uid: u32, gid: u32) -> Result<(), AgentdError> {
        files::require_process(self, uid, gid)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Recipient { pub uid: u32, pub gid: u32, pub peer: Peer }

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ServicePeer { pub uid: u32, pub gid: u32, pub peer: Peer }

impl ServicePeer {
    pub(super) fn policy_peer(&self) -> HostIssuerPeer {
        HostIssuerPeer { uid: self.uid, pid: self.peer.pid }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Witness {
    scope_digest: String, objective_digest: String, generation: u64,
    pub maximum_records: usize,
}
impl Witness {
    pub(super) fn scope(&self) -> Result<JournalScope, AgentdError> {
        Ok(JournalScope { scope_digest: digest(&self.scope_digest)?,
            objective_digest: digest(&self.objective_digest)? })
    }
    pub(super) fn generation(&self) -> Result<Generation, AgentdError> {
        Generation::new(self.generation).map_err(invalid)
    }
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum UpdateScope { Cell, Organ }
#[derive(Clone, Copy, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Head { Drive { index: u16 }, Prediction { index: u16 } }

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SourceInput {
    agent_id: String, cell_id: String, run_id: String, principal_digest: String,
    source_frontier: String, objective_digest: String, ndu_snapshot_digest: String,
    monotonic_micros: u64, deadline_micros: u64, observation: Vec<u8>,
    candidates: Vec<Candidate>, lease_duration_ms: u64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Candidate { candidate_id: String, allowed: bool }

impl SourceInput {
    pub(super) fn original(&self) -> Result<CircuitTaskSourceInputV1, AgentdError> {
        if self.observation.len() > 16_384 || self.candidates.is_empty() || self.candidates.len() > 128 {
            return Err(invalid("fixed Source data exceeds the original bounded profile"));
        }
        Ok(CircuitTaskSourceInputV1 {
            scope: CellScopeV1 { agent_id: id(&self.agent_id)?, cell_id: id(&self.cell_id)?,
                run_id: id(&self.run_id)?, principal_digest: digest(&self.principal_digest)? },
            source_frontier: digest(&self.source_frontier)?, objective_digest: digest(&self.objective_digest)?,
            ndu_snapshot_digest: digest(&self.ndu_snapshot_digest)?, monotonic_micros: self.monotonic_micros,
            deadline_micros: self.deadline_micros, observation: self.observation.clone(),
            candidates: self.candidates.iter().map(|c| Ok(CellCandidateMaskV1 {
                candidate_id: id(&c.candidate_id)?, allowed: c.allowed,
            })).collect::<Result<_, AgentdError>>()?, lease_duration_ms: self.lease_duration_ms,
        })
    }
}

impl Configuration {
    pub(super) fn require_process(&self) -> Result<(), AgentdError> {
        // SAFETY: these calls only read this process's actual credentials.
        let (uid, euid, gid, egid) = unsafe { (libc::getuid(), libc::geteuid(), libc::getgid(), libc::getegid()) };
        if self.schema_version != 1 || self.purpose != "hepta.original-material-host.supervisor.v1"
            || matches!(uid, 0 | u32::MAX) || uid != euid || matches!(gid, 0 | u32::MAX) || gid != egid
            || uid != self.material.uid || gid != self.material.gid
            || self.material.peer.pid != std::process::id() || self.nonce == [0; 16]
            || !(1..=8192).contains(&self.maximum_ledger_records)
            || self.source_root.pid == self.material.peer.pid || self.workflow_root.pid == self.material.peer.pid
            || !(1..=86_400).contains(&self.maximum_signature_lifetime_seconds)
            || self.source_root_gid == u32::MAX || self.workflow_root_gid == u32::MAX
        { return Err(invalid("Material requires the fixed actual nonRoot supervisor recipient")); }
        self.material.peer.require_live(uid, gid)?;
        self.source_root.require_live(0, self.source_root_gid)?;
        self.workflow_root.require_live(0, self.workflow_root_gid)?;
        for peer in [&self.experience_command, &self.dataset_command, &self.experience_readback,
            &self.dataset_readback, &self.dataset_source] {
            if peer.uid == uid || peer.peer.pid == self.material.peer.pid || peer.uid == u32::MAX || peer.gid == u32::MAX {
                return Err(invalid("Material cannot serve itself or a same-UID substitute"));
            }
            peer.peer.require_live(peer.uid, peer.gid)?;
        }
        self.experience_witness.generation()?;
        self.dataset_witness.generation()?;
        self.experience_witness.scope()?;
        self.dataset_witness.scope()?;
        if self.experience_witness.maximum_records == 0 || self.dataset_witness.maximum_records == 0 {
            return Err(invalid("original witness limit is absent"));
        }
        Ok(())
    }

    pub(super) fn original_identity(&self) -> Result<AgentdIdentity, AgentdError> {
        let identity = &self.registered_identity;
        // Public identity data from Root's full retained registration, not
        // AgentdConfig or filesystem custody. This lexical check confers no
        // canonical path proof, directory access or permission to reopen it.
        for path in [&identity.fleet_root, &identity.workspace] {
            if !path.is_absolute() || path.components().any(|p| !matches!(p, Component::RootDir | Component::Normal(_))) {
                return Err(invalid("original registered identity path has invalid shape"));
            }
        }
        if identity.spawn_generation == 0 { return Err(invalid("original spawn generation is absent")); }
        let layout = HeptaFleetRoot::parse(identity.fleet_root.clone()).map_err(invalid)?.layout().agent(&identity.agent_id);
        Ok(AgentdIdentity { agent_id: identity.agent_id.clone(), spawn_generation: identity.spawn_generation,
            fleet_root: identity.fleet_root.clone(), workspace: identity.workspace.clone(), resources: identity.resources.clone(),
            home_root: layout.home_root().to_path_buf(), run_root: layout.run_root().to_path_buf(),
            control_socket: layout.agentd_control_socket().to_path_buf(), app_server_socket: layout.app_server_socket().to_path_buf(), layout })
    }

    pub(super) fn original_source_request(&self, trust: &trust::OriginalMaterialTrust)
        -> Result<OriginalCircuitPrefreezeSourceRequestV1, AgentdError>
    {
        let at = files::now()?;
        trust.require_window(at)?;
        let activation = trust.activation();
        Ok(OriginalCircuitPrefreezeSourceRequestV1 {
            generation_operation_id: self.generation_operation_id.clone(),
            generation_intent_digest: digest(&self.generation_intent_digest)?, task_digest: digest(&self.task_digest)?,
            source: self.source.original()?, ledger_binding_digest: digest(&self.ledger_binding_digest)?,
            evidence_trust_digest: activation.verifier().trust_digest(),
            trust_distribution_digest: activation.distribution_digest(), trust_generation: activation.generation(),
            generator: trust.signer(&id(&self.generator_actor)?, LearningEvidenceRoleV1::Generator, at)?,
            experience_signer: trust.signer(&id(&self.experience_actor)?, LearningEvidenceRoleV1::Observer, at)?,
            dataset_signer: trust.signer(&id(&self.dataset_actor)?, LearningEvidenceRoleV1::Observer, at)?,
            consumer: self.material.peer.original(), consumer_uid: self.material.uid, nonce: self.nonce,
        })
    }

    pub(super) fn rule(&self) -> Result<CellQ24DatasetRuleV1, AgentdError> {
        Ok(CellQ24DatasetRuleV1 { head: match self.head {
            Head::Drive { index } => CellQ24PrivateHeadV1::Drive { index },
            Head::Prediction { index } => CellQ24PrivateHeadV1::Prediction { index },
        }, unit_profile_digest: digest(&self.unit_profile_digest)? })
    }
}

pub(super) fn digest(value: &str) -> Result<Digest32, AgentdError> {
    let parsed = value.parse::<Digest32>().map_err(invalid)?;
    if parsed.to_string() != value { return Err(invalid("noncanonical original digest")); }
    Ok(parsed)
}
pub(super) fn id(value: &str) -> Result<StableId, AgentdError> { StableId::new(value).map_err(invalid) }
