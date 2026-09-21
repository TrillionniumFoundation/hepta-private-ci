//! Process-safe reconstruction of the opt-in plasticity runtime owner.
//!
//! The descriptor carries only host-selected paths, independent recovery witnesses,
//! trust configuration and bounded numeric configuration.  It never derives an
//! acknowledgement from a suspect store and it never falls back from reopen/resume
//! to a fresh bootstrap.

use std::fs::{File, OpenOptions};
use std::io::Read;
#[cfg(unix)]
use std::os::unix::fs::{MetadataExt, OpenOptionsExt};
use std::path::{Path, PathBuf};
use std::str::FromStr;
use std::sync::{Arc, Mutex, RwLock};

use codex_hepta_learning_artifacts::{
    ArtifactRegistry, RegistrySnapshotReceipt, read_registry_snapshot,
};
use codex_hepta_learning_ledger::{
    AuthenticatedPrincipalV1, DatasetSnapshotReceiptV3, DatasetSnapshotV2, DurableLedger,
    LearningEvidenceRoleV1, LearningEvidenceTrustV1, LearningEvidenceVerifierV1, LedgerAnchor,
    LedgerRecovery, TrustedLearningSignerV1, verify_dataset_snapshot_receipt_v3,
};
use codex_hepta_ndu::NduProjectionJournalV1;
use codex_hepta_neuron::{
    InhibitoryEdge, JournalAnchor, JournalScope, SparseConfig, SparseJournal,
};
use codex_hepta_types::{AuthorityPosture, Digest32, FixedQ32, Generation, StableId};
use serde::Deserialize;

use crate::{
    AgentdError, AgentdIdentity, PlasticityArtifactOwnerBindingV1,
    PlasticityDynamicOwnerEvidenceResolverV1, PlasticityDynamicSignalBindingV1,
    PlasticityOwnerEvidenceKindV1, PlasticityOwnerEvidencePolicyV1, PlasticityRuntimeBootstrapV1,
    bootstrap_agentd_plasticity_writer_v1, bootstrap_agentd_topology_writer_v1,
    reopen_agentd_plasticity_writer_v1, reopen_agentd_topology_writer_v1,
    resume_agentd_plasticity_writer_v1, resume_agentd_topology_writer_v1,
    ConcretePlasticityOwnerEvidenceResolverV1,
};

// A descriptor/recovery failure is terminal for this optional organ; callers must never\n// reinterpret it as permission to create a fresh, unanchored proposal history.\nconst DESCRIPTOR_SCHEMA: &str = "hepta.agentd.plasticity-bootstrap.v1";
const MAX_DESCRIPTOR_BYTES: u64 = 1_048_576;
const MAX_NDU_JOURNAL_BYTES: u64 = 2 * 1_048_576;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ProcessBootstrapDescriptorV1 {
    schema: String,
    agent_id: String,
    spawn_generation: u64,
    queue_capacity: usize,
    objective_digest: String,
    artifacts: ArtifactSnapshotDescriptorV1,
    ledger: LedgerDescriptorV1,
    dataset: DatasetReceiptDescriptorV1,
    ndu: NduDescriptorV1,
    neuron: NeuronDescriptorV1,
    signal_bindings: Vec<SignalBindingDescriptorV1>,
    trust: TrustDescriptorV1,
    owner_policy: OwnerPolicyDescriptorV1,
    parameter_registry: RegistryDescriptorV1,
    topology_registry: RegistryDescriptorV1,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ArtifactSnapshotDescriptorV1 {
    path: PathBuf,
    receipt: ArtifactSnapshotReceiptDescriptorV1,
    observed_at: u64,
    expires_at: u64,
    update_rule_artifact_id: String,
    mutation_policy_artifact_id: String,
    broadcast_artifact_id: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ArtifactSnapshotReceiptDescriptorV1 {
    binding: String,
    head_digest: String,
    file_digest: String,
    records: usize,
    encoded_bytes: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct LedgerDescriptorV1 {
    path: PathBuf,
    binding: String,
    max_records: usize,
    anchor_sequence: u64,
    anchor_chain_digest: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PrincipalDescriptorV1 {
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DatasetSnapshotDescriptorV1 {
    snapshot_id: String,
    ledger_head_digest: String,
    objective_digest: String,
    eligible_frontier: u64,
    outcome_watermark: u64,
    source_record_digests: Vec<String>,
    pending_outcomes: u32,
    censored_outcomes: u32,
    dataset_digest: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DatasetReceiptDescriptorV1 {
    snapshot: DatasetSnapshotDescriptorV1,
    producer: PrincipalDescriptorV1,
    correction_cut_digest: String,
    revocation_cut_digest: String,
    inclusion_policy_digest: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct NduDescriptorV1 {
    journal_path: PathBuf,
    subject_digest: String,
    owner_id: String,
    modulator_values_raw_q32: Vec<i64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct InhibitoryEdgeDescriptorV1 {
    source: usize,
    target: usize,
    weight_q24: i64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SparseConfigDescriptorV1 {
    model_digest: String,
    normalization_digest: String,
    generation: u64,
    width: usize,
    top_k: usize,
    temporal_decay_q24: i64,
    inhibition_gain_q24: i64,
    inhibition: Vec<InhibitoryEdgeDescriptorV1>,
    activity_decay_q24: i64,
    target_activity_q24: i64,
    threshold_rate_q24: i64,
    threshold_min_q24: i64,
    threshold_max_q24: i64,
    eligibility_decay_q24: i64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct NeuronDescriptorV1 {
    journal_path: PathBuf,
    owner_id: String,
    scope_digest: String,
    objective_digest: String,
    max_records: usize,
    anchor_sequence: u64,
    anchor_checkpoint_digest: String,
    config: SparseConfigDescriptorV1,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SignalBindingDescriptorV1 {
    layer_id: String,
    parameter_id: String,
    eligibility_index: u32,
    modulator_weights_raw_q32: Vec<i64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustedSignerDescriptorV1 {
    principal: PrincipalDescriptorV1,
    controller_id: String,
    verifying_key_hex: String,
    roles: Vec<String>,
    revoked_at: Option<u64>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustDescriptorV1 {
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    signers: Vec<TrustedSignerDescriptorV1>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnerPolicyDescriptorV1 {
    dataset_owner_id: String,
    update_rule_owner_id: String,
    modulator_owner_id: String,
    modulator_broadcast_owner_id: String,
    eligibility_owner_id: String,
    parameter_signal_owner_id: String,
    mutation_policy_owner_id: String,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "snake_case")]
enum RegistryOpenModeV1 {
    BootstrapNew,
    ResumeUnacknowledged,
    ReopenAnchored,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RegistryDescriptorV1 {
    mode: RegistryOpenModeV1,
    registry_path: PathBuf,
    anchor_path: PathBuf,
    scope_digest: String,
    maximum_records: usize,
}

/// Load one exact, host-selected process bootstrap.  The descriptor itself is not
/// authority: every durable owner and independent witness is reopened and checked
/// by its native implementation before a runtime owner is returned.
pub fn load_plasticity_process_bootstrap_v1(
    path: &Path,
    expected_descriptor_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<PlasticityRuntimeBootstrapV1, AgentdError> {
    require_absolute_regular_file(path, "plasticity bootstrap descriptor")?;
    let bytes = read_bounded(path, MAX_DESCRIPTOR_BYTES, "plasticity bootstrap descriptor")?;
    verify_descriptor_bytes(&bytes, expected_descriptor_digest)?;
    let descriptor: ProcessBootstrapDescriptorV1 = serde_json::from_slice(&bytes)?;
    if descriptor.schema != DESCRIPTOR_SCHEMA {
        return invalid("plasticity bootstrap descriptor schema mismatch");
    }
    if descriptor.agent_id != identity.agent_id.as_str()
        || descriptor.spawn_generation != identity.spawn_generation
    {
        return Err(AgentdError::GenerationFenced(
            "plasticity bootstrap descriptor does not match Agentd identity/generation".to_string(),
        ));
    }
    validate_process_path_separation(&descriptor)?;

    let objective_digest = digest(&descriptor.objective_digest, "objective digest")?;
    let artifacts = load_artifacts(&descriptor.artifacts)?;
    let ledger = load_ledger(&descriptor.ledger)?;
    let dataset = build_dataset_receipt(&descriptor.dataset)?;
    if dataset.snapshot.objective_digest != objective_digest {
        return invalid("dataset objective does not match plasticity descriptor");
    }
    verify_dataset_snapshot_receipt_v3(&dataset, descriptor.artifacts.observed_at)
        .map_err(|error| AgentdError::Invalid(format!("invalid dataset receipt: {error}")))?;
    let ledger_head = ledger
        .snapshot()
        .map_err(|error| AgentdError::Invalid(format!("learning ledger snapshot failed: {error}")))?
        .head_digest;
    if dataset.snapshot.ledger_head_digest != ledger_head {
        return invalid("dataset receipt does not bind the recovered learning ledger head");
    }

    let ndu_bytes = read_bounded(
        &descriptor.ndu.journal_path,
        MAX_NDU_JOURNAL_BYTES,
        "NDU projection journal",
    )?;
    let ndu_journal = NduProjectionJournalV1::reopen(&ndu_bytes)
        .map_err(|error| AgentdError::Invalid(format!("invalid NDU projection journal: {error}")))?;

    let neuron_scope_digest = digest(&descriptor.neuron.scope_digest, "neuron scope")?;
    let neuron_objective_digest = digest(&descriptor.neuron.objective_digest, "neuron objective")?;
    if neuron_objective_digest != objective_digest {
        return invalid("neuron objective does not match plasticity descriptor");
    }
    let neuron_config = sparse_config(&descriptor.neuron.config)?;
    let neuron_anchor = JournalAnchor {
        sequence: descriptor.neuron.anchor_sequence,
        checkpoint_digest: digest(
            &descriptor.neuron.anchor_checkpoint_digest,
            "neuron checkpoint anchor",
        )?,
    };
    let neuron_file = open_existing_rw(&descriptor.neuron.journal_path, "neuron journal")?;
    let neuron_journal = SparseJournal::open_anchored(
        neuron_file,
        neuron_config,
        JournalScope {
            scope_digest: neuron_scope_digest,
            objective_digest: neuron_objective_digest,
        },
        descriptor.neuron.max_records,
        neuron_anchor,
    )
    .map_err(|error| AgentdError::Invalid(format!("invalid anchored neuron journal: {error}")))?;

    let signal_bindings = descriptor
        .signal_bindings
        .iter()
        .map(signal_binding)
        .collect::<Result<Vec<_>, _>>()?;
    let dynamic = PlasticityDynamicOwnerEvidenceResolverV1::new(
        objective_digest,
        digest(&descriptor.ndu.subject_digest, "NDU subject")?,
        stable_id(&descriptor.ndu.owner_id, "NDU owner")?,
        stable_id(&descriptor.neuron.owner_id, "neuron owner")?,
        Arc::new(RwLock::new(ndu_journal)),
        descriptor
            .ndu
            .modulator_values_raw_q32
            .iter()
            .copied()
            .map(FixedQ32::from_raw)
            .collect(),
        Arc::new(Mutex::new(neuron_journal)),
        neuron_anchor,
        artifacts.clone(),
        stable_id(
            &descriptor.artifacts.broadcast_artifact_id,
            "broadcast artifact id",
        )?,
        signal_bindings,
        descriptor.artifacts.observed_at,
        descriptor.artifacts.expires_at,
    )
    .map_err(|error| AgentdError::Invalid(format!("invalid dynamic owner evidence: {error}")))?;

    let owner_evidence = ConcretePlasticityOwnerEvidenceResolverV1::new(
        dataset,
        artifacts.clone(),
        descriptor.artifacts.observed_at,
        descriptor.artifacts.expires_at,
        vec![
            PlasticityArtifactOwnerBindingV1 {
                kind: PlasticityOwnerEvidenceKindV1::UpdateRule,
                artifact_id: stable_id(
                    &descriptor.artifacts.update_rule_artifact_id,
                    "update rule artifact id",
                )?,
            },
            PlasticityArtifactOwnerBindingV1 {
                kind: PlasticityOwnerEvidenceKindV1::MutationPolicy,
                artifact_id: stable_id(
                    &descriptor.artifacts.mutation_policy_artifact_id,
                    "mutation policy artifact id",
                )?,
            },
        ],
        Box::new(dynamic),
    )
    .map_err(|error| AgentdError::Invalid(format!("invalid owner evidence composition: {error}")))?;

    let verifier = build_verifier(&descriptor.trust, objective_digest)?;
    verify_owner_policy_bindings(&descriptor, &artifacts, &dataset)?;
    let owner_policy = build_owner_policy(&descriptor.owner_policy)?;
    let (parameter_writer, parameter_anchor_store) =
        open_parameter_writer(&descriptor.parameter_registry)?;
    let (topology_writer, topology_anchor_store) =
        open_topology_writer(&descriptor.topology_registry)?;

    PlasticityRuntimeBootstrapV1::new(
        descriptor.queue_capacity,
        artifacts,
        ledger,
        Box::new(owner_evidence),
        owner_policy,
        verifier,
        parameter_writer,
        parameter_anchor_store,
        topology_writer,
        topology_anchor_store,
    )
}

fn load_artifacts(
    descriptor: &ArtifactSnapshotDescriptorV1,
) -> Result<ArtifactRegistry, AgentdError> {
    require_absolute_regular_file(&descriptor.path, "artifact registry snapshot")?;
    let receipt = RegistrySnapshotReceipt {
        binding: digest(&descriptor.receipt.binding, "artifact snapshot binding")?,
        head_digest: digest(&descriptor.receipt.head_digest, "artifact snapshot head")?,
        file_digest: digest(&descriptor.receipt.file_digest, "artifact snapshot file digest")?,
        records: descriptor.receipt.records,
        encoded_bytes: descriptor.receipt.encoded_bytes,
    };
    read_registry_snapshot(File::open(&descriptor.path)?, receipt)
        .map_err(|error| AgentdError::Invalid(format!("invalid artifact registry snapshot: {error}")))
}

fn load_ledger(descriptor: &LedgerDescriptorV1) -> Result<DurableLedger, AgentdError> {
    let file = open_existing_rw(&descriptor.path, "learning ledger")?;
    DurableLedger::recover(
        file,
        digest(&descriptor.binding, "learning ledger binding")?,
        descriptor.max_records,
        LedgerRecovery::Acknowledged(LedgerAnchor {
            sequence: descriptor.anchor_sequence,
            chain_digest: digest(&descriptor.anchor_chain_digest, "learning ledger anchor")?,
        }),
    )
    .map_err(|error| AgentdError::Invalid(format!("invalid anchored learning ledger: {error}")))
}

fn build_dataset_receipt(
    descriptor: &DatasetReceiptDescriptorV1,
) -> Result<DatasetSnapshotReceiptV3, AgentdError> {
    let snapshot = &descriptor.snapshot;
    Ok(DatasetSnapshotReceiptV3 {
        snapshot: DatasetSnapshotV2 {
            snapshot_id: stable_id(&snapshot.snapshot_id, "dataset snapshot id")?,
            ledger_head_digest: digest(&snapshot.ledger_head_digest, "dataset ledger head")?,
            objective_digest: digest(&snapshot.objective_digest, "dataset objective")?,
            eligible_frontier: snapshot.eligible_frontier,
            outcome_watermark: snapshot.outcome_watermark,
            source_record_digests: snapshot
                .source_record_digests
                .iter()
                .map(|value| digest(value, "dataset source record"))
                .collect::<Result<Vec<_>, _>>()?,
            pending_outcomes: snapshot.pending_outcomes,
            censored_outcomes: snapshot.censored_outcomes,
            dataset_digest: digest(&snapshot.dataset_digest, "dataset digest")?,
            authority: AuthorityPosture::DENY_ALL,
        },
        producer: principal(&descriptor.producer)?,
        correction_cut_digest: digest(
            &descriptor.correction_cut_digest,
            "dataset correction cut",
        )?,
        revocation_cut_digest: digest(
            &descriptor.revocation_cut_digest,
            "dataset revocation cut",
        )?,
        inclusion_policy_digest: digest(
            &descriptor.inclusion_policy_digest,
            "dataset inclusion policy",
        )?,
    })
}

fn principal(descriptor: &PrincipalDescriptorV1) -> Result<AuthenticatedPrincipalV1, AgentdError> {
    Ok(AuthenticatedPrincipalV1 {
        principal_id: stable_id(&descriptor.principal_id, "principal id")?,
        credential_chain_digest: digest(
            &descriptor.credential_chain_digest,
            "credential chain digest",
        )?,
        signing_key_digest: digest(&descriptor.signing_key_digest, "signing key digest")?,
        scope_digest: digest(&descriptor.scope_digest, "principal scope")?,
        authority_epoch: descriptor.authority_epoch,
        authenticated_at: descriptor.authenticated_at,
        expires_at: descriptor.expires_at,
    })
}

fn sparse_config(descriptor: &SparseConfigDescriptorV1) -> Result<SparseConfig, AgentdError> {
    Ok(SparseConfig {
        model_digest: digest(&descriptor.model_digest, "neuron model digest")?,
        normalization_digest: digest(
            &descriptor.normalization_digest,
            "neuron normalization digest",
        )?,
        generation: Generation::new(descriptor.generation)
            .map_err(|error| AgentdError::Invalid(format!("invalid neuron generation: {error}")))?,
        width: descriptor.width,
        top_k: descriptor.top_k,
        temporal_decay_q24: descriptor.temporal_decay_q24,
        inhibition_gain_q24: descriptor.inhibition_gain_q24,
        inhibition: descriptor
            .inhibition
            .iter()
            .map(|edge| InhibitoryEdge {
                source: edge.source,
                target: edge.target,
                weight_q24: edge.weight_q24,
            })
            .collect(),
        activity_decay_q24: descriptor.activity_decay_q24,
        target_activity_q24: descriptor.target_activity_q24,
        threshold_rate_q24: descriptor.threshold_rate_q24,
        threshold_min_q24: descriptor.threshold_min_q24,
        threshold_max_q24: descriptor.threshold_max_q24,
        eligibility_decay_q24: descriptor.eligibility_decay_q24,
    })
}

fn signal_binding(
    descriptor: &SignalBindingDescriptorV1,
) -> Result<PlasticityDynamicSignalBindingV1, AgentdError> {
    Ok(PlasticityDynamicSignalBindingV1 {
        layer_id: stable_id(&descriptor.layer_id, "signal layer id")?,
        parameter_id: stable_id(&descriptor.parameter_id, "signal parameter id")?,
        eligibility_index: descriptor.eligibility_index,
        modulator_weights: descriptor
            .modulator_weights_raw_q32
            .iter()
            .copied()
            .map(FixedQ32::from_raw)
            .collect(),
    })
}

fn build_verifier(
    descriptor: &TrustDescriptorV1,
    objective_digest: Digest32,
) -> Result<LearningEvidenceVerifierV1, AgentdError> {
    let trust_objective = digest(&descriptor.objective_digest, "trust objective")?;
    if trust_objective != objective_digest {
        return invalid("learning evidence trust objective mismatch");
    }
    let signers = descriptor
        .signers
        .iter()
        .map(|signer| {
            Ok(TrustedLearningSignerV1 {
                principal: principal(&signer.principal)?,
                controller_id: stable_id(&signer.controller_id, "signer controller id")?,
                verifying_key: parse_hex_32(&signer.verifying_key_hex, "verifying key")?,
                roles: signer
                    .roles
                    .iter()
                    .map(|role| match role.as_str() {
                        "generator" => Ok(LearningEvidenceRoleV1::Generator),
                        "observer" => Ok(LearningEvidenceRoleV1::Observer),
                        "evaluator" => Ok(LearningEvidenceRoleV1::Evaluator),
                        _ => invalid("unknown learning evidence role"),
                    })
                    .collect::<Result<Vec<_>, AgentdError>>()?,
                revoked_at: signer.revoked_at,
            })
        })
        .collect::<Result<Vec<_>, AgentdError>>()?;
    LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest(&descriptor.scope_digest, "trust scope")?,
        objective_digest: trust_objective,
        authority_epoch: descriptor.authority_epoch,
        signers,
    })
    .map_err(|error| AgentdError::Invalid(format!("invalid learning evidence trust: {error}")))
}

fn verify_owner_policy_bindings(
    descriptor: &ProcessBootstrapDescriptorV1,
    artifacts: &ArtifactRegistry,
    dataset: &DatasetSnapshotReceiptV3,
) -> Result<(), AgentdError> {
    let policy = &descriptor.owner_policy;
    if policy.dataset_owner_id != dataset.producer.principal_id.as_str()
        || policy.modulator_owner_id != descriptor.ndu.owner_id
        || policy.eligibility_owner_id != descriptor.neuron.owner_id
        || policy.parameter_signal_owner_id != descriptor.neuron.owner_id
    {
        return invalid("plasticity owner policy does not match authoritative owner identity");
    }

    for (artifact_id, expected_owner, label) in [
        (
            descriptor.artifacts.update_rule_artifact_id.as_str(),
            policy.update_rule_owner_id.as_str(),
            "update rule",
        ),
        (
            descriptor.artifacts.mutation_policy_artifact_id.as_str(),
            policy.mutation_policy_owner_id.as_str(),
            "mutation policy",
        ),
        (
            descriptor.artifacts.broadcast_artifact_id.as_str(),
            policy.modulator_broadcast_owner_id.as_str(),
            "modulator broadcast",
        ),
    ] {
        let artifact_id = stable_id(artifact_id, label)?;
        let manifest = artifacts
            .manifest(&artifact_id)
            .ok_or_else(|| AgentdError::Invalid(format!("{label} artifact is missing")))?;
        if manifest.producer_id.as_str() != expected_owner {
            return invalid(&format!("{label} owner policy does not match artifact producer"));
        }
    }
    Ok(())
}

fn build_owner_policy(
    descriptor: &OwnerPolicyDescriptorV1,
) -> Result<PlasticityOwnerEvidencePolicyV1, AgentdError> {
    PlasticityOwnerEvidencePolicyV1::from_rules(vec![
        (
            PlasticityOwnerEvidenceKindV1::Dataset,
            stable_id(&descriptor.dataset_owner_id, "dataset owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::UpdateRule,
            stable_id(&descriptor.update_rule_owner_id, "update rule owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::Modulator,
            stable_id(&descriptor.modulator_owner_id, "modulator owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::ModulatorBroadcast,
            stable_id(
                &descriptor.modulator_broadcast_owner_id,
                "modulator broadcast owner",
            )?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::Eligibility,
            stable_id(&descriptor.eligibility_owner_id, "eligibility owner")?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::ParameterSignal,
            stable_id(
                &descriptor.parameter_signal_owner_id,
                "parameter signal owner",
            )?,
        ),
        (
            PlasticityOwnerEvidenceKindV1::MutationPolicy,
            stable_id(
                &descriptor.mutation_policy_owner_id,
                "mutation policy owner",
            )?,
        ),
    ])
    .map_err(|error| AgentdError::Invalid(format!("invalid owner evidence policy: {error}")))
}

fn open_parameter_writer(
    descriptor: &RegistryDescriptorV1,
) -> Result<
    (
        codex_hepta_intelligence::AnchoredPlasticityWriterV1,
        crate::AgentdPlasticityAnchorStoreV1,
    ),
    AgentdError,
> {
    validate_distinct_registry_paths(descriptor)?;
    let scope = digest(&descriptor.scope_digest, "parameter registry scope")?;
    let result = match descriptor.mode {
        RegistryOpenModeV1::BootstrapNew => bootstrap_agentd_plasticity_writer_v1(
            create_new_rw(&descriptor.registry_path, "parameter proposal registry")?,
            create_new_rw(&descriptor.anchor_path, "parameter anchor journal")?,
            scope,
            descriptor.maximum_records,
        ),
        RegistryOpenModeV1::ResumeUnacknowledged => resume_agentd_plasticity_writer_v1(
            open_existing_rw(&descriptor.registry_path, "parameter proposal registry")?,
            open_existing_rw(&descriptor.anchor_path, "parameter anchor journal")?,
            scope,
            descriptor.maximum_records,
        ),
        RegistryOpenModeV1::ReopenAnchored => reopen_agentd_plasticity_writer_v1(
            open_existing_rw(&descriptor.registry_path, "parameter proposal registry")?,
            open_existing_rw(&descriptor.anchor_path, "parameter anchor journal")?,
            scope,
            descriptor.maximum_records,
        ),
    };
    result.map_err(|error| AgentdError::Invalid(format!("parameter registry recovery failed: {error}")))
}

fn open_topology_writer(
    descriptor: &RegistryDescriptorV1,
) -> Result<
    (
        crate::AgentdTopologyWriterV1,
        crate::AgentdTopologyAnchorStoreV1,
    ),
    AgentdError,
> {
    validate_distinct_registry_paths(descriptor)?;
    let scope = digest(&descriptor.scope_digest, "topology registry scope")?;
    let result = match descriptor.mode {
        RegistryOpenModeV1::BootstrapNew => bootstrap_agentd_topology_writer_v1(
            create_new_rw(&descriptor.registry_path, "topology proposal registry")?,
            create_new_rw(&descriptor.anchor_path, "topology anchor journal")?,
            scope,
            descriptor.maximum_records,
        ),
        RegistryOpenModeV1::ResumeUnacknowledged => resume_agentd_topology_writer_v1(
            open_existing_rw(&descriptor.registry_path, "topology proposal registry")?,
            open_existing_rw(&descriptor.anchor_path, "topology anchor journal")?,
            scope,
            descriptor.maximum_records,
        ),
        RegistryOpenModeV1::ReopenAnchored => reopen_agentd_topology_writer_v1(
            open_existing_rw(&descriptor.registry_path, "topology proposal registry")?,
            open_existing_rw(&descriptor.anchor_path, "topology anchor journal")?,
            scope,
            descriptor.maximum_records,
        ),
    };
    result.map_err(|error| AgentdError::Invalid(format!("topology registry recovery failed: {error}")))
}

fn validate_process_path_separation(
    descriptor: &ProcessBootstrapDescriptorV1,
) -> Result<(), AgentdError> {
    let paths = [
        descriptor.ledger.path.as_path(),
        descriptor.neuron.journal_path.as_path(),
        descriptor.parameter_registry.registry_path.as_path(),
        descriptor.parameter_registry.anchor_path.as_path(),
        descriptor.topology_registry.registry_path.as_path(),
        descriptor.topology_registry.anchor_path.as_path(),
    ];
    for (index, left) in paths.iter().enumerate() {
        for right in paths.iter().skip(index + 1) {
            if left == right {
                return invalid("plasticity mutable owner paths must be distinct");
            }
            if existing_paths_alias(left, right)? {
                return invalid("plasticity mutable owner paths alias the same file");
            }
        }
    }
    Ok(())
}

fn existing_paths_alias(left: &Path, right: &Path) -> Result<bool, AgentdError> {
    let left_metadata = match std::fs::symlink_metadata(left) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.into()),
    };
    let right_metadata = match std::fs::symlink_metadata(right) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(error) => return Err(error.into()),
    };
    if left_metadata.file_type().is_symlink() || right_metadata.file_type().is_symlink() {
        return invalid("plasticity mutable owner paths must not be symlinks");
    }
    #[cfg(unix)]
    {
        Ok(
            (left_metadata.dev(), left_metadata.ino())
                == (right_metadata.dev(), right_metadata.ino()),
        )
    }
    #[cfg(not(unix))]
    {
        let left = left.canonicalize()?;
        let right = right.canonicalize()?;
        Ok(left == right)
    }
}

fn validate_distinct_registry_paths(descriptor: &RegistryDescriptorV1) -> Result<(), AgentdError> {
    if !descriptor.registry_path.is_absolute() || !descriptor.anchor_path.is_absolute() {
        return invalid("proposal registry and anchor paths must be absolute");
    }
    if descriptor.registry_path == descriptor.anchor_path {
        return invalid("proposal registry and anchor journal must be distinct files");
    }
    Ok(())
}

fn read_bounded(path: &Path, maximum: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
    require_absolute_regular_file(path, label)?;
    let metadata = std::fs::metadata(path)?;
    if metadata.len() == 0 || metadata.len() > maximum {
        return invalid(&format!("{label} size is outside the allowed bound"));
    }
    let file = File::open(path)?;
    let capacity = usize::try_from(metadata.len())
        .map_err(|_| AgentdError::Invalid(format!("{label} is too large")))?;
    let mut bytes = Vec::with_capacity(capacity);
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != metadata.len() {
        return invalid(&format!("{label} changed while being read"));
    }
    Ok(bytes)
}

fn require_absolute_regular_file(path: &Path, label: &str) -> Result<(), AgentdError> {
    if !path.is_absolute() {
        return invalid(&format!("{label} path must be absolute"));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return invalid(&format!("{label} must be a regular non-symlink file"));
    }
    Ok(())
}

fn open_existing_rw(path: &Path, label: &str) -> Result<File, AgentdError> {
    require_absolute_regular_file(path, label)?;
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .map_err(Into::into)
}

fn create_new_rw(path: &Path, label: &str) -> Result<File, AgentdError> {
    if !path.is_absolute() {
        return invalid(&format!("{label} path must be absolute"));
    }
    let parent = path
        .parent()
        .ok_or_else(|| AgentdError::Invalid(format!("{label} has no parent")))?;
    let parent = parent.canonicalize()?;
    if path.parent() != Some(parent.as_path()) {
        return invalid(&format!("{label} parent must be canonical"));
    }
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    options.mode(0o600);
    options.open(path).map_err(Into::into)
}

fn verify_descriptor_bytes(
    bytes: &[u8],
    expected_descriptor_digest: Digest32,
) -> Result<(), AgentdError> {
    if expected_descriptor_digest.is_zero()
        || Digest32::of_bytes(bytes) != expected_descriptor_digest
    {
        return invalid("plasticity bootstrap descriptor digest mismatch");
    }
    Ok(())
}

fn digest(value: &str, label: &str) -> Result<Digest32, AgentdError> {
    Digest32::from_str(value)
        .map_err(|error| AgentdError::Invalid(format!("invalid {label}: {error}")))
}

fn stable_id(value: &str, label: &str) -> Result<StableId, AgentdError> {
    StableId::new(value.to_string())
        .map_err(|error| AgentdError::Invalid(format!("invalid {label}: {error}")))
}

fn parse_hex_32(value: &str, label: &str) -> Result<[u8; 32], AgentdError> {
    digest(value, label).map(Digest32::into_array)
}

fn invalid<T>(message: &str) -> Result<T, AgentdError> {
    Err(AgentdError::Invalid(message.to_string()))
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn descriptor_digest_rejects_byte_substitution() {
        let original = b"{\"schema\":\"hepta.agentd.plasticity-bootstrap.v1\"}";
        let expected = Digest32::of_bytes(original);
        assert!(verify_descriptor_bytes(original, expected).is_ok());
        assert!(verify_descriptor_bytes(b"tampered", expected).is_err());
        assert!(verify_descriptor_bytes(original, Digest32::ZERO).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn mutable_owner_hardlink_alias_is_rejected() {
        let directory = tempfile::tempdir().expect("tempdir");
        let left = directory.path().join("registry");
        let right = directory.path().join("anchor");
        std::fs::write(&left, b"registry").expect("write");
        std::fs::hard_link(&left, &right).expect("hard link");
        assert!(existing_paths_alias(&left, &right).expect("identity check"));
    }
}
