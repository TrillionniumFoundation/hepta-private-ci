//! Test-only persistence of the producer's complete original recovery inputs.
//! No secret keys are saved. Reopening verifies the original signed trust
//! distribution at the current time and recovers the existing acknowledged
//! ledger and Circuit source; it never creates or signs replacement inputs.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::BoundedCircuitDefinitionV2;
use codex_hepta_automation::CircuitExitV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningTrustDistributionV1;
use codex_hepta_learning_ledger::LearningTrustRootV1;
use codex_hepta_learning_ledger::LedgerRecovery;
use codex_hepta_learning_ledger::LedgerWitnessStore;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::SignedLearningTrustDistributionV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_neuron::CellCandidateKindV1;
use codex_hepta_neuron::CellCandidateMaskV1;
use codex_hepta_neuron::CellCandidateV1;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::CellScopeV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_neuron::InhibitoryEdge;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;

use super::fixture::Fixture;
use crate::AgentdIdentity;
use crate::CircuitCellBindingV1;
use crate::CircuitCellRegistryV1;
use crate::CircuitCellRouteV1;
use crate::CircuitTaskSourceInputV1;
use crate::DurableCircuitTaskSourceV1;

const INPUT_FILE: &str = "original-inputs.json";
const MAX_INPUT_BYTES: usize = 256 * 1024;

pub(super) struct Reopened {
    pub(super) identity: AgentdIdentity,
    pub(super) writer: LedgerWriter,
    pub(super) source: DurableCircuitTaskSourceV1<FileAnchorWitnessStore>,
}

#[derive(Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct OriginalInputs {
    version: u32,
    original_root: PathBuf,
    #[serde(with = "identity")]
    identity: AgentdIdentity,
    #[serde(with = "TrustRoot")]
    trust_root: LearningTrustRootV1,
    #[serde(with = "SignedDistribution")]
    signed_distribution: SignedLearningTrustDistributionV1,
    distribution_signing_bytes: Vec<u8>,
    #[serde(with = "digest")]
    ledger_binding: Digest32,
    ledger_limit: usize,
    #[serde(with = "SourceInput")]
    source_input: CircuitTaskSourceInputV1,
    #[serde(with = "Fence")]
    fence: TaskFlowFence,
    circuit: BoundedCircuitDefinitionV2,
    #[serde(with = "bindings")]
    bindings: Vec<CircuitCellBindingV1>,
    #[serde(with = "WitnessScope")]
    source_witness_scope: JournalScope,
    #[serde(with = "generation")]
    source_witness_generation: Generation,
    source_witness_limit: usize,
}

pub(super) fn save_inputs(fixture: &Fixture, root: &Path) -> anyhow::Result<()> {
    let original_root = root.canonicalize()?;
    anyhow::ensure!(
        original_root == fixture.directory.path().canonicalize()?,
        "different producer root"
    );
    let original = OriginalInputs {
        version: 1,
        original_root,
        identity: fixture.identity.clone(),
        trust_root: fixture.trust_root.clone(),
        signed_distribution: fixture.signed_distribution.clone(),
        distribution_signing_bytes: fixture.signed_distribution.signing_bytes()?,
        ledger_binding: fixture.ledger_binding,
        ledger_limit: fixture.ledger_limit,
        source_input: fixture.source_input.clone(),
        fence: fixture.fence.clone(),
        circuit: fixture.circuit.clone(),
        bindings: fixture.bindings.clone(),
        source_witness_scope: fixture.source_witness_scope,
        source_witness_generation: fixture.source_witness_generation,
        source_witness_limit: fixture.source_witness_limit,
    };
    let bytes = serde_json::to_vec(&original)?;
    anyhow::ensure!(bytes.len() <= MAX_INPUT_BYTES, "original input size limit");
    let decoded: OriginalInputs = serde_json::from_slice(&bytes)?;
    // Complete typed equality includes the original signature, signer list,
    // every runtime/calibration field, and the identity's full derived layout.
    anyhow::ensure!(
        decoded == original,
        "original input roundtrip changed a field"
    );
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(root.join(INPUT_FILE))?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    File::open(root)?.sync_all()?;
    anyhow::ensure!(
        read_inputs(root)? == original,
        "persisted original inputs changed"
    );
    Ok(())
}

fn existing_file(path: &Path, writable: bool) -> anyhow::Result<File> {
    let mut options = OpenOptions::new();
    options.read(true).write(writable);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW);
    }
    let file = options.open(path)?;
    let metadata = file.metadata()?;
    // FileAnchorWitnessStore::open initializes an empty file. Reject it before
    // calling that API so recovery cannot manufacture a replacement witness.
    anyhow::ensure!(
        metadata.is_file() && metadata.len() > 0,
        "missing original nonempty regular file: {path:?}"
    );
    Ok(file)
}

fn read_inputs(root: &Path) -> anyhow::Result<OriginalInputs> {
    let file = existing_file(&root.join(INPUT_FILE), false)?;
    let mut bytes = Vec::new();
    file.take(MAX_INPUT_BYTES as u64 + 1)
        .read_to_end(&mut bytes)?;
    anyhow::ensure!(bytes.len() <= MAX_INPUT_BYTES, "original input size limit");
    let original: OriginalInputs = serde_json::from_slice(&bytes)?;
    anyhow::ensure!(
        original.version == 1 && original.original_root == root.canonicalize()?,
        "original input version/root mismatch"
    );
    anyhow::ensure!(
        original.signed_distribution.signing_bytes()? == original.distribution_signing_bytes,
        "original trust signing bytes changed"
    );
    Ok(original)
}

pub(super) fn reopen_inputs(root: &Path) -> anyhow::Result<Reopened> {
    let original = read_inputs(root)?;
    let ledger_file = existing_file(&root.join("ledger"), true)?;
    let ledger_witness_file = existing_file(&root.join("ledger-witness"), true)?;
    let source_file = existing_file(&root.join("source-journal"), true)?;
    let source_witness_file = existing_file(&root.join("source-witness"), true)?;
    let current_time = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let trust = activate_learning_trust(
        &original.trust_root,
        original.signed_distribution,
        /*previous*/ None,
        current_time,
    )?;
    let ledger_witness = LedgerWitnessStore::recover(ledger_witness_file, original.ledger_binding)?;
    let ledger = DurableLedger::recover(
        ledger_file,
        original.ledger_binding,
        original.ledger_limit,
        LedgerRecovery::Acknowledged(ledger_witness.frontier()?.anchor),
    )?;
    let directory = File::open(root)?;
    let writer = LedgerWriter::from_durable(ledger, ledger_witness, trust, &directory, &directory)?;
    let registry = CircuitCellRegistryV1::new(original.circuit, original.bindings)?;
    let source_witness = FileAnchorWitnessStore::open(
        source_witness_file,
        original.source_witness_scope,
        original.source_witness_generation,
        original.source_witness_limit,
    )?;
    let source = DurableCircuitTaskSourceV1::recover(
        source_file,
        source_witness,
        &original.identity,
        &original.fence,
        &registry,
        vec![original.source_input],
    )?;
    Ok(Reopened {
        identity: original.identity,
        writer,
        source,
    })
}

// Remote serde definitions keep the product types free from test persistence
// APIs. All fields are explicit; a missing product field fails compilation.
mod digest {
    use super::*;
    pub(super) fn serialize<S: Serializer>(
        value: &Digest32,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value.as_array().serialize(serializer)
    }
    pub(super) fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Digest32, D::Error> {
        Ok(Digest32::from_array(<[u8; 32]>::deserialize(deserializer)?))
    }
}
mod stable_id {
    use super::*;
    pub(super) fn serialize<S: Serializer>(
        value: &StableId,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value.as_str().serialize(serializer)
    }
    pub(super) fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<StableId, D::Error> {
        StableId::new(String::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}
mod generation {
    use super::*;
    pub(super) fn serialize<S: Serializer>(
        value: &Generation,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value.get().serialize(serializer)
    }
    pub(super) fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<Generation, D::Error> {
        Generation::new(u64::deserialize(deserializer)?).map_err(serde::de::Error::custom)
    }
}
mod signature {
    use super::*;
    pub(super) fn serialize<S: Serializer>(
        value: &[u8; 64],
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        value.as_slice().serialize(serializer)
    }
    pub(super) fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<[u8; 64], D::Error> {
        Vec::<u8>::deserialize(deserializer)?
            .try_into()
            .map_err(|_| serde::de::Error::custom("signature must contain exactly 64 bytes"))
    }
}

mod identity {
    use super::*;
    #[derive(Serialize, Deserialize)]
    #[serde(deny_unknown_fields)]
    struct SavedIdentity {
        agent_id: AgentId,
        spawn_generation: u64,
        fleet_root: PathBuf,
        workspace: PathBuf,
        resources: ResourceBudget,
        home_root: PathBuf,
        run_root: PathBuf,
        control_socket: PathBuf,
        app_server_socket: PathBuf,
    }
    pub(super) fn serialize<S: Serializer>(
        value: &AgentdIdentity,
        serializer: S,
    ) -> Result<S::Ok, S::Error> {
        SavedIdentity {
            agent_id: value.agent_id.clone(),
            spawn_generation: value.spawn_generation,
            fleet_root: value.fleet_root.clone(),
            workspace: value.workspace.clone(),
            resources: value.resources.clone(),
            home_root: value.home_root.clone(),
            run_root: value.run_root.clone(),
            control_socket: value.control_socket.clone(),
            app_server_socket: value.app_server_socket.clone(),
        }
        .serialize(serializer)
    }
    pub(super) fn deserialize<'de, D: Deserializer<'de>>(
        deserializer: D,
    ) -> Result<AgentdIdentity, D::Error> {
        let value = SavedIdentity::deserialize(deserializer)?;
        // This is the existing side-effect-free path geometry, using the
        // producer's saved root and ID. It creates no directories or identity.
        let layout = HeptaFleetRoot::parse(value.fleet_root.clone())
            .map_err(serde::de::Error::custom)?
            .layout()
            .agent(&value.agent_id);
        Ok(AgentdIdentity {
            agent_id: value.agent_id,
            layout,
            spawn_generation: value.spawn_generation,
            fleet_root: value.fleet_root,
            workspace: value.workspace,
            resources: value.resources,
            home_root: value.home_root,
            run_root: value.run_root,
            control_socket: value.control_socket,
            app_server_socket: value.app_server_socket,
        })
    }
}

macro_rules! remote_vec {
    ($module:ident, $value:ty, $remote:literal) => {
        mod $module {
            use super::*;
            #[derive(Serialize, Deserialize)]
            #[serde(transparent)]
            struct Item(#[serde(with = $remote)] $value);
            pub(super) fn serialize<S: Serializer>(
                values: &[$value],
                serializer: S,
            ) -> Result<S::Ok, S::Error> {
                values
                    .iter()
                    .cloned()
                    .map(Item)
                    .collect::<Vec<_>>()
                    .serialize(serializer)
            }
            pub(super) fn deserialize<'de, D: Deserializer<'de>>(
                deserializer: D,
            ) -> Result<Vec<$value>, D::Error> {
                Ok(Vec::<Item>::deserialize(deserializer)?
                    .into_iter()
                    .map(|item| item.0)
                    .collect())
            }
        }
    };
}
remote_vec!(roles, LearningEvidenceRoleV1, "EvidenceRole");
remote_vec!(signers, TrustedLearningSignerV1, "TrustedSigner");
remote_vec!(masks, CellCandidateMaskV1, "CandidateMask");
remote_vec!(candidates, CellCandidateV1, "Candidate");
remote_vec!(inhibition, InhibitoryEdge, "Inhibition");
remote_vec!(routes, CircuitCellRouteV1, "Route");
remote_vec!(bindings, CircuitCellBindingV1, "Binding");

#[derive(Serialize, Deserialize)]
#[serde(remote = "LearningTrustRootV1", deny_unknown_fields)]
struct TrustRoot {
    #[serde(with = "stable_id")]
    root_id: StableId,
    #[serde(with = "digest")]
    scope_digest: Digest32,
    verifying_key: [u8; 32],
    valid_from: u64,
    expires_at: u64,
    revoked_at: Option<u64>,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "SignedLearningTrustDistributionV1", deny_unknown_fields)]
struct SignedDistribution {
    #[serde(with = "Distribution")]
    distribution: LearningTrustDistributionV1,
    #[serde(with = "stable_id")]
    root_id: StableId,
    issued_at: u64,
    expires_at: u64,
    #[serde(with = "signature")]
    signature: [u8; 64],
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "LearningTrustDistributionV1", deny_unknown_fields)]
struct Distribution {
    #[serde(with = "stable_id")]
    distribution_id: StableId,
    generation: u64,
    effective_at: u64,
    #[serde(with = "EvidenceTrust")]
    trust: LearningEvidenceTrustV1,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "LearningEvidenceTrustV1", deny_unknown_fields)]
struct EvidenceTrust {
    #[serde(with = "digest")]
    scope_digest: Digest32,
    #[serde(with = "digest")]
    objective_digest: Digest32,
    authority_epoch: u64,
    #[serde(with = "signers")]
    signers: Vec<TrustedLearningSignerV1>,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "TrustedLearningSignerV1", deny_unknown_fields)]
struct TrustedSigner {
    #[serde(with = "Principal")]
    principal: AuthenticatedPrincipalV1,
    #[serde(with = "stable_id")]
    controller_id: StableId,
    verifying_key: [u8; 32],
    #[serde(with = "roles")]
    roles: Vec<LearningEvidenceRoleV1>,
    revoked_at: Option<u64>,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "AuthenticatedPrincipalV1", deny_unknown_fields)]
struct Principal {
    #[serde(with = "stable_id")]
    principal_id: StableId,
    #[serde(with = "digest")]
    credential_chain_digest: Digest32,
    #[serde(with = "digest")]
    signing_key_digest: Digest32,
    #[serde(with = "digest")]
    scope_digest: Digest32,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "LearningEvidenceRoleV1")]
enum EvidenceRole {
    Generator,
    Observer,
    Evaluator,
    CreditAllocator,
    UnlearningAuthority,
    Selector,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CircuitTaskSourceInputV1", deny_unknown_fields)]
struct SourceInput {
    #[serde(with = "Scope")]
    scope: CellScopeV1,
    #[serde(with = "digest")]
    source_frontier: Digest32,
    #[serde(with = "digest")]
    objective_digest: Digest32,
    #[serde(with = "digest")]
    ndu_snapshot_digest: Digest32,
    monotonic_micros: u64,
    deadline_micros: u64,
    observation: Vec<u8>,
    #[serde(with = "masks")]
    candidates: Vec<CellCandidateMaskV1>,
    lease_duration_ms: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CellScopeV1", deny_unknown_fields)]
struct Scope {
    #[serde(with = "stable_id")]
    agent_id: StableId,
    #[serde(with = "stable_id")]
    cell_id: StableId,
    #[serde(with = "stable_id")]
    run_id: StableId,
    #[serde(with = "digest")]
    principal_digest: Digest32,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CellCandidateMaskV1", deny_unknown_fields)]
struct CandidateMask {
    #[serde(with = "stable_id")]
    candidate_id: StableId,
    allowed: bool,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "TaskFlowFence", deny_unknown_fields)]
struct Fence {
    owner_agent_id: AgentId,
    owner_id: String,
    owner_epoch: u64,
    generation: u64,
    fencing_token: String,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "JournalScope", deny_unknown_fields)]
struct WitnessScope {
    #[serde(with = "digest")]
    scope_digest: Digest32,
    #[serde(with = "digest")]
    objective_digest: Digest32,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CircuitCellBindingV1", deny_unknown_fields)]
struct Binding {
    program_id: String,
    node_id: String,
    #[serde(with = "CellDefinition")]
    cell: CellDefinitionV1,
    #[serde(with = "routes")]
    routes: Vec<CircuitCellRouteV1>,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CircuitCellRouteV1", deny_unknown_fields)]
struct Route {
    #[serde(with = "stable_id")]
    candidate_id: StableId,
    outcome: CircuitExitV2,
    selected_edges: Vec<String>,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CellDefinitionV1", deny_unknown_fields)]
struct CellDefinition {
    #[serde(with = "stable_id")]
    cell_id: StableId,
    #[serde(with = "digest")]
    bundle_digest: Digest32,
    #[serde(with = "digest")]
    state_schema_digest: Digest32,
    #[serde(with = "Runtime")]
    runtime: NeuronRuntimeConfigV1,
    #[serde(with = "Sparse")]
    native: SparseConfig,
    #[serde(with = "candidates")]
    candidates: Vec<CellCandidateV1>,
    max_input_bytes: usize,
    max_queue_age_micros: u64,
    max_resident_bytes: u64,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CellCandidateV1", deny_unknown_fields)]
struct Candidate {
    #[serde(with = "stable_id")]
    candidate_id: StableId,
    activation_index: usize,
    #[serde(with = "CandidateKind")]
    kind: CellCandidateKindV1,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "CellCandidateKindV1")]
enum CandidateKind {
    Action,
    Abstain,
    SlowPath,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronRuntimeConfigV1", deny_unknown_fields)]
struct Runtime {
    #[serde(with = "stable_id")]
    config_id: StableId,
    #[serde(with = "generation")]
    generation: Generation,
    #[serde(with = "stable_id")]
    model_id: StableId,
    #[serde(with = "digest")]
    model_manifest_digest: Digest32,
    #[serde(with = "digest")]
    encoder_digest: Digest32,
    #[serde(with = "digest")]
    head_digest: Digest32,
    #[serde(with = "digest")]
    weights_digest: Digest32,
    #[serde(with = "digest")]
    tokenizer_digest: Digest32,
    #[serde(with = "digest")]
    preprocessor_digest: Digest32,
    #[serde(with = "digest")]
    quantization_digest: Digest32,
    #[serde(with = "digest")]
    runtime_digest: Digest32,
    #[serde(with = "digest")]
    device_digest: Digest32,
    #[serde(with = "digest")]
    normalization_digest: Digest32,
    #[serde(with = "digest")]
    native_config_digest: Digest32,
    input_feature_dimension: usize,
    state_width: usize,
    modulator_dimension: usize,
    #[serde(with = "Calibration")]
    calibration: NeuronCalibrationProfileV1,
    #[serde(with = "ResourceEnvelope")]
    resource_envelope: NeuronResourceEnvelopeV1,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronCalibrationProfileV1", deny_unknown_fields)]
struct Calibration {
    #[serde(with = "digest")]
    calibration_artifact_digest: Digest32,
    #[serde(with = "digest")]
    ood_artifact_digest: Digest32,
    #[serde(with = "generation")]
    generation: Generation,
    valid_from_sequence: u64,
    expires_after_sequence: u64,
    zero_confidence_error_q24: i64,
    maximum_in_domain_error_q24: i64,
    minimum_confidence_ppm: u32,
    maximum_ood_ppm: u32,
    minimum_active_ppm: u32,
    maximum_active_ppm: u32,
    maximum_projection_count: u32,
    measured_ece_ppm: u32,
    maximum_ece_ppm: u32,
    measured_false_acceptance_ppm: u32,
    maximum_false_acceptance_ppm: u32,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "NeuronResourceEnvelopeV1", deny_unknown_fields)]
struct ResourceEnvelope {
    p95_latency_micros: u64,
    p99_latency_micros: u64,
    transient_allocation_bytes: u64,
    checkpoint_bytes: u64,
    write_amplification_ppm: u32,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "SparseConfig", deny_unknown_fields)]
struct Sparse {
    #[serde(with = "digest")]
    model_digest: Digest32,
    #[serde(with = "digest")]
    normalization_digest: Digest32,
    #[serde(with = "generation")]
    generation: Generation,
    width: usize,
    top_k: usize,
    temporal_decay_q24: i64,
    inhibition_gain_q24: i64,
    #[serde(with = "inhibition")]
    inhibition: Vec<InhibitoryEdge>,
    activity_decay_q24: i64,
    target_activity_q24: i64,
    threshold_rate_q24: i64,
    threshold_min_q24: i64,
    threshold_max_q24: i64,
    eligibility_decay_q24: i64,
}
#[derive(Serialize, Deserialize)]
#[serde(remote = "InhibitoryEdge", deny_unknown_fields)]
struct Inhibition {
    source: usize,
    target: usize,
    weight_q24: i64,
}
