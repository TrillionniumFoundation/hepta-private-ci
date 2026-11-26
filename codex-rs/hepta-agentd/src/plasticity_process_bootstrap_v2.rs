//! Reopen the same histories with their latest protected input context. This
//! entry uses the already held V2 Neuron host and never opens a V1 SparseJournal.
use super::*;

/// The caller supplies the already installed original V2 host. Latest context
/// selection remains Root-protected and is bound again to the original Round
/// when this owner starts. Existing histories must remain complete/anchored.
pub fn load_plasticity_process_bootstrap_v2(
    path: &Path,
    expected_descriptor_digest: Digest32,
    identity: &AgentdIdentity,
    context_path: &Path,
    context_digest: Digest32,
    host: Arc<crate::AgentdNeuronRuntimeV2Host>,
) -> Result<PlasticityRuntimeBootstrapV1, AgentdError> {
    let bytes = input_context::protected_context_bytes(
        path,
        expected_descriptor_digest,
        MAX_DESCRIPTOR_BYTES,
    )?;
    let descriptor: ProcessBootstrapDescriptorV1 = serde_json::from_slice(&bytes)?;
    if descriptor.schema != DESCRIPTOR_SCHEMA
        || descriptor.agent_id != identity.agent_id.as_str()
        || descriptor.spawn_generation != identity.spawn_generation
    {
        return invalid("original V2 process context identity");
    }
    validate_process_path_separation(&descriptor)?;
    let ledger = load_ledger(&descriptor.ledger)?;
    let context = input_context::load_input_context_v2(
        context_path,
        context_digest,
        identity,
        &ledger,
        host,
        crate::authbus_ingress::now_ms()?,
    )?;
    let (parameter_writer, parameter_anchor_store) =
        open_parameter_writer(&descriptor.parameter_registry)?;
    let (topology_writer, topology_anchor_store) =
        open_topology_writer(&descriptor.topology_registry)?;
    let mut bootstrap = PlasticityRuntimeBootstrapV1::new(
        descriptor.queue_capacity,
        context.artifacts,
        ledger,
        context.resolver,
        context.policy,
        context.verifier,
        parameter_writer,
        parameter_anchor_store,
        topology_writer,
        topology_anchor_store,
    )?;
    bootstrap.current_artifacts = Some(context.current_artifacts);
    bootstrap.input_context = Some((context.round, context.source));
    bootstrap.restore_input_context_on_start = true;
    if input_context::protected_context_bytes(
        path,
        expected_descriptor_digest,
        MAX_DESCRIPTOR_BYTES,
    )? != bytes
    {
        return invalid("original V2 bootstrap source changed");
    }
    Ok(bootstrap)
}
