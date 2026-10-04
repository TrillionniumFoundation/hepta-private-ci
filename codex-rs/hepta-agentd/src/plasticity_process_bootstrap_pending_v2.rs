//! Startup of the original plasticity writers before any Round has input facts.
//! No Dataset, NDU projection or V1 Neuron is opened by this purpose. Missing
//! facts cannot authorize a proposal; the original Round-fenced context loader
//! must later admit them against the same held V2 runtime and durable writers.
use super::*;
use crate::PlasticityOwnerEvidenceErrorV1;
use crate::PlasticityOwnerEvidenceQueryV1;
use crate::PlasticityOwnerEvidenceResolverV1;
use crate::VerifiedPlasticityOwnerEvidenceV1;

const SCHEMA: &str = "hepta.agentd.plasticity-pending-v2-bootstrap.v1";

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PendingV2Descriptor {
    schema: String,
    agent_id: String,
    spawn_generation: u64,
    queue_capacity: usize,
    objective_digest: String,
    artifacts: ArtifactSnapshotDescriptorV1,
    ledger: LedgerDescriptorV1,
    trust: TrustDescriptorV1,
    owner_policy: OwnerPolicyDescriptorV1,
    parameter_registry: RegistryDescriptorV1,
    topology_registry: RegistryDescriptorV1,
    /// An installer-selected, already admitted context for cold restoration.
    /// Its Round is checked again by the original runtime before it starts.
    #[serde(default)]
    input_context: Option<ContextSource>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ContextSource {
    path: PathBuf,
    digest: String,
}

pub(super) struct PendingV2Resolver;

impl PlasticityOwnerEvidenceResolverV1 for PendingV2Resolver {
    fn prepare_parameter_input(
        &self,
        _input: crate::AgentdPlasticityAdmissionInputV1,
        _now: u64,
    ) -> Result<crate::AgentdPlasticityAdmissionInputV1, PlasticityOwnerEvidenceErrorV1> {
        Err(PlasticityOwnerEvidenceErrorV1::Missing)
    }

    fn resolve(
        &self,
        _query: &PlasticityOwnerEvidenceQueryV1,
    ) -> Result<VerifiedPlasticityOwnerEvidenceV1, PlasticityOwnerEvidenceErrorV1> {
        Err(PlasticityOwnerEvidenceErrorV1::Missing)
    }
}

/// Reopen the installer-selected original Ledger and proposal histories. The
/// daemon must attach its actual V2 host before consuming this bootstrap. This
/// entry neither fabricates a Round nor accepts an unsigned Dataset as authority.
pub fn load_plasticity_process_bootstrap_pending_v2(
    path: &Path,
    pin: Digest32,
    identity: &AgentdIdentity,
) -> Result<PlasticityRuntimeBootstrapV1, AgentdError> {
    let bytes = input_context::protected_context_bytes(path, pin, MAX_DESCRIPTOR_BYTES)?;
    let descriptor: PendingV2Descriptor = serde_json::from_slice(&bytes)?;
    validate(&descriptor, identity)?;
    let artifacts = load_artifacts(&descriptor.artifacts)?;
    let policy = build_owner_policy(&descriptor.owner_policy)?;
    let verifier = build_verifier(
        &descriptor.trust,
        digest(&descriptor.objective_digest, "training objective")?,
    )?;
    let current = descriptor
        .artifacts
        .current_owner
        .as_ref()
        .ok_or_else(|| {
            AgentdError::Invalid("pending V2 requires the original CURRENT owner".into())
        })?
        .source()?;
    let policy_ids = [
        &descriptor.artifacts.update_rule_artifact_id,
        &descriptor.artifacts.mutation_policy_artifact_id,
        &descriptor.artifacts.broadcast_artifact_id,
    ]
    .map(|value| stable_id(value, "CURRENT policy"));
    let [update, mutation, broadcast] = policy_ids;
    let policy_ids = [update?, mutation?, broadcast?];
    let view = current
        .read_at(crate::authbus_ingress::now_ms()?)
        .map_err(|error| AgentdError::Invalid(format!("pending V2 CURRENT: {error}")))?;
    if view.receipt().head_digest != artifacts.head_digest()
        || policy_ids
            .iter()
            .any(|id| view.eligible_manifest(id) != artifacts.manifest(id))
    {
        return invalid("pending V2 snapshot differs from original CURRENT");
    }
    let ledger = load_ledger(&descriptor.ledger)?;
    let (parameter, parameter_anchor) = open_parameter_writer(&descriptor.parameter_registry)?;
    let (topology, topology_anchor) = open_topology_writer(&descriptor.topology_registry)?;
    let mut bootstrap = PlasticityRuntimeBootstrapV1::new(
        descriptor.queue_capacity,
        artifacts,
        ledger,
        Box::new(PendingV2Resolver),
        policy,
        verifier,
        parameter,
        parameter_anchor,
        topology,
        topology_anchor,
    )?
    .with_current_artifacts(current, policy_ids)?;
    bootstrap.requires_neuron_v2 = true;
    bootstrap.pending_v2_context = descriptor
        .input_context
        .map(|source| -> Result<_, AgentdError> {
            Ok((source.path, digest(&source.digest, "cold V2 context")?))
        })
        .transpose()?;
    if input_context::protected_context_bytes(path, pin, MAX_DESCRIPTOR_BYTES)? != bytes {
        return invalid("pending V2 bootstrap source changed");
    }
    Ok(bootstrap)
}

fn validate(
    descriptor: &PendingV2Descriptor,
    identity: &AgentdIdentity,
) -> Result<(), AgentdError> {
    if descriptor.schema != SCHEMA
        || descriptor.agent_id != identity.agent_id.as_str()
        || descriptor.spawn_generation != identity.spawn_generation
    {
        return invalid("pending V2 bootstrap identity/schema");
    }
    crate::plasticity_runtime::validate_plasticity_runtime_capacity(descriptor.queue_capacity)?;
    if let Some(source) = &descriptor.input_context
        && (!source.path.is_absolute() || digest(&source.digest, "cold V2 context")?.is_zero())
    {
        return invalid("pending V2 cold context Source");
    }
    validate_mutable_owner_paths(&[
        &descriptor.ledger.path,
        &descriptor.parameter_registry.registry_path,
        &descriptor.parameter_registry.anchor_path,
        &descriptor.topology_registry.registry_path,
        &descriptor.topology_registry.anchor_path,
    ])
}

#[cfg(test)]
#[path = "plasticity_process_bootstrap_pending_v2_tests.rs"]
mod tests;
