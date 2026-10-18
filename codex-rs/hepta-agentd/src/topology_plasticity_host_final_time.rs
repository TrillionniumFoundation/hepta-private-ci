//! Owner-clock final use over the existing host frontiers and writer.
use super::*;
use codex_hepta_agent_components::intelligence::propose_authenticated_topology_plasticity_with_final_time_v1;

pub(crate) fn propose_agentd_topology_plasticity_with_clock_v1(
    mut request: TopologyPlasticityProductRequestV1,
    artifacts: &ArtifactRegistry,
    ledger: &DurableLedger,
    verifier: &LearningEvidenceVerifierV1,
    writer: &mut AgentdTopologyWriterV1,
    anchor_store: &mut AgentdTopologyAnchorStoreV1,
    now: u64,
    clock: &mut dyn FnMut() -> Result<u64, crate::AgentdError>,
) -> Result<TopologyPlasticityProductReceiptV1, AgentdTopologyHostErrorV1> {
    if writer.state() != AgentdTopologyWriterStateV1::Healthy {
        return Err(AgentdTopologyHostErrorV1::Poisoned);
    }
    let resolved = resolve_agentd_topology_admission_v1(
        &AgentdTopologyAdmissionInputV1 {
            baseline_id: request.admission.baseline_id.clone(),
            objective_digest: request.admission.objective_digest,
            selected_artifact_digest: request.selected_artifact_digest,
            window: request.window.clone(),
            baseline_generation: request.baseline_generation,
            candidate_generation: request.candidate_generation,
            generation_digest: request.admission.generation_digest,
            evaluation_receipt_digest: request.admission.evaluation_receipt_digest,
        },
        artifacts,
        ledger,
    )?;
    if resolved != request.admission {
        return Err(AgentdTopologyHostErrorV1::AdmissionDrift);
    }
    request.admission = resolved;

    let receipt = match propose_authenticated_topology_plasticity_with_final_time_v1(
        request,
        verifier,
        &mut writer.registry,
        now,
        &mut || {
            clock().map_err(|_| TopologyPlasticityProductErrorV1::Binding("host clock unavailable"))
        },
    ) {
        Ok(receipt) => receipt,
        Err(error) => {
            writer.state = if matches!(
                error,
                TopologyPlasticityProductErrorV1::Registry(
                    DurableTopologyRegistryErrorV1::Corrupt
                        | DurableTopologyRegistryErrorV1::Indeterminate
                        | DurableTopologyRegistryErrorV1::Poisoned
                        | DurableTopologyRegistryErrorV1::Io(_)
                ) | TopologyPlasticityProductErrorV1::MissingAnchor
            ) {
                AgentdTopologyWriterStateV1::Poisoned
            } else {
                AgentdTopologyWriterStateV1::Healthy
            };
            return Err(AgentdTopologyHostErrorV1::Product(error));
        }
    };
    writer.state = AgentdTopologyWriterStateV1::AppendPendingAnchor;
    if anchor_store
        .persist_anchor(writer.scope, writer.fence, receipt.next_registry_anchor)
        .is_err()
    {
        writer.state = AgentdTopologyWriterStateV1::Poisoned;
        return Err(AgentdTopologyHostErrorV1::AnchorPersistenceFailed);
    }
    writer.state = AgentdTopologyWriterStateV1::Healthy;
    Ok(receipt)
}
