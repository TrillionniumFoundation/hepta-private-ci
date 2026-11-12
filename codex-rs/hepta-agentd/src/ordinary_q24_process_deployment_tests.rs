//! Faithful public Source/Cell input preimages shared by the actual Root and
//! ordinary daemon. This encoder creates neither a receipt nor an owner.

use std::path::Path;
use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_neuron::CellCandidateKindV1;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_types::Digest32;
use serde_json::Value;
use serde_json::json;

use crate::AgentdIdentity;
use crate::CircuitTaskSourceInputV1;

pub(super) struct OriginalAFilePaths {
    pub(super) source: PathBuf,
    pub(super) source_witness: PathBuf,
    pub(super) cell: PathBuf,
    pub(super) cell_witness: PathBuf,
    pub(super) ledger: PathBuf,
    pub(super) ledger_witness: PathBuf,
    pub(super) signatures: PathBuf,
    pub(super) signature_witness: PathBuf,
    pub(super) inference: PathBuf,
    pub(super) generator_key: PathBuf,
}

impl OriginalAFilePaths {
    pub(super) fn new(data: &Path, witness: &Path) -> Self {
        Self {
            source: data.join("a-source.journal"),
            source_witness: witness.join("a-source.witness"),
            cell: data.join("a-cell.journal"),
            cell_witness: witness.join("a-cell.witness"),
            ledger: data.join("a-ledger.journal"),
            ledger_witness: witness.join("a-ledger.witness"),
            signatures: data.join("a-signatures.journal"),
            signature_witness: witness.join("a-signatures.witness"),
            inference: data.join("a-inference-control"),
            generator_key: data.join("a-original-generator.key"),
        }
    }

    pub(super) fn business_files(&self) -> Vec<PathBuf> {
        [
            &self.source,
            &self.source_witness,
            &self.cell,
            &self.cell_witness,
            &self.ledger,
            &self.ledger_witness,
            &self.signatures,
            &self.signature_witness,
            &self.inference,
            &self.generator_key,
        ]
        .into_iter()
        .cloned()
        .collect()
    }

    pub(super) fn cell_data(&self, objective: Digest32) -> Value {
        json!({
            "journal": self.cell,
            "witness": self.cell_witness,
            "witness_scope": digest("ordinary-original-cell"),
            "witness_objective": objective.into_array(),
            "witness_generation": 1,
            "witness_records": 128
        })
    }

    pub(super) fn source_data(
        &self,
        identity: &AgentdIdentity,
        definition: &CellDefinitionV1,
        source: &CircuitTaskSourceInputV1,
        ledger_deployment: &Path,
    ) -> anyhow::Result<Value> {
        let (mut circuit, mut bindings) = crate::circuit_cell::tests::configuration();
        let original = bindings
            .first_mut()
            .ok_or_else(|| anyhow::anyhow!("original finite route absent"))?;
        original.cell = definition.clone();
        circuit.parameter_bundle_digest =
            Sha256Digest::parse(definition.bundle_digest.to_string())?;
        circuit.route_policy_digest = crate::circuit_cell_route_policy_digest_v1(&bindings)?;
        let routes = &bindings[0].routes;
        let mut cell = self.cell_data(source.objective_digest);
        cell["maximum_records"] = json!(4);
        Ok(json!({
            "schema_version": 1,
            "purpose": "runtime.circuit.single-q24-source-deployment.v1",
            "source_journal": self.source,
            "source_witness": self.source_witness,
            "cell_files": cell,
            "ledger_deployment": ledger_deployment,
            "witness_scope": digest("ordinary-original-source"),
            "witness_objective": source.objective_digest.into_array(),
            "witness_generation": 1,
            "witness_records": 128,
            "fence": {
                "owner_id": "ordinary-original-circuit-owner",
                "owner_epoch": 1,
                "generation": identity.spawn_generation.checked_add(1)
                    .ok_or_else(|| anyhow::anyhow!("original Circuit generation overflow"))?,
                "fencing_token": "ordinary-original-circuit-fence"
            },
            "circuit": circuit,
            "routes": routes.iter().map(|route| json!({
                "candidate_id": route.candidate_id.as_str(),
                "outcome": route.outcome,
                "selected_edges": route.selected_edges
            })).collect::<Vec<_>>(),
            "definition": definition_data(definition),
            "source": {
                "cell_id": source.scope.cell_id.as_str(),
                "run_id": source.scope.run_id.as_str(),
                "principal_digest": source.scope.principal_digest.into_array(),
                "source_frontier": source.source_frontier.into_array(),
                "objective_digest": source.objective_digest.into_array(),
                "ndu_snapshot_digest": source.ndu_snapshot_digest.into_array(),
                "monotonic_micros": source.monotonic_micros,
                "deadline_micros": source.deadline_micros,
                "observation": source.observation,
                "candidates": source.candidates.iter().map(|mask| json!({
                    "candidate_id": mask.candidate_id.as_str(), "allowed": mask.allowed
                })).collect::<Vec<_>>(),
                "lease_duration_ms": source.lease_duration_ms
            }
        }))
    }
}

pub(super) fn digest(value: &str) -> [u8; 32] {
    Digest32::of_bytes(value.as_bytes()).into_array()
}

fn definition_data(cell: &CellDefinitionV1) -> Value {
    let r = &cell.runtime;
    let c = &r.calibration;
    let e = &r.resource_envelope;
    let n = &cell.native;
    let calibration = json!({
        "calibration_artifact_digest": c.calibration_artifact_digest.into_array(),
        "ood_artifact_digest": c.ood_artifact_digest.into_array(), "generation": c.generation.get(),
        "valid_from_sequence": c.valid_from_sequence, "expires_after_sequence": c.expires_after_sequence,
        "zero_confidence_error_q24": c.zero_confidence_error_q24,
        "maximum_in_domain_error_q24": c.maximum_in_domain_error_q24,
        "minimum_confidence_ppm": c.minimum_confidence_ppm, "maximum_ood_ppm": c.maximum_ood_ppm,
        "minimum_active_ppm": c.minimum_active_ppm, "maximum_active_ppm": c.maximum_active_ppm,
        "maximum_projection_count": c.maximum_projection_count, "measured_ece_ppm": c.measured_ece_ppm,
        "maximum_ece_ppm": c.maximum_ece_ppm,
        "measured_false_acceptance_ppm": c.measured_false_acceptance_ppm,
        "maximum_false_acceptance_ppm": c.maximum_false_acceptance_ppm
    });
    let envelope = json!({
        "p95_latency_micros": e.p95_latency_micros, "p99_latency_micros": e.p99_latency_micros,
        "transient_allocation_bytes": e.transient_allocation_bytes,
        "checkpoint_bytes": e.checkpoint_bytes, "write_amplification_ppm": e.write_amplification_ppm
    });
    let runtime = json!({
        "config_id": r.config_id.as_str(), "generation": r.generation.get(),
        "model_id": r.model_id.as_str(), "model_manifest_digest": r.model_manifest_digest.into_array(),
        "encoder_digest": r.encoder_digest.into_array(), "head_digest": r.head_digest.into_array(),
        "weights_digest": r.weights_digest.into_array(), "tokenizer_digest": r.tokenizer_digest.into_array(),
        "preprocessor_digest": r.preprocessor_digest.into_array(),
        "quantization_digest": r.quantization_digest.into_array(),
        "runtime_digest": r.runtime_digest.into_array(), "device_digest": r.device_digest.into_array(),
        "normalization_digest": r.normalization_digest.into_array(),
        "native_config_digest": r.native_config_digest.into_array(),
        "input_feature_dimension": r.input_feature_dimension, "state_width": r.state_width,
        "modulator_dimension": r.modulator_dimension,
        "calibration": calibration, "resource_envelope": envelope
    });
    let native = json!({
        "model_digest": n.model_digest.into_array(), "normalization_digest": n.normalization_digest.into_array(),
        "generation": n.generation.get(), "width": n.width, "top_k": n.top_k,
        "temporal_decay_q24": n.temporal_decay_q24, "inhibition_gain_q24": n.inhibition_gain_q24,
        "inhibition": n.inhibition.iter().map(|edge| json!({
            "source": edge.source, "target": edge.target, "weight_q24": edge.weight_q24
        })).collect::<Vec<_>>(),
        "activity_decay_q24": n.activity_decay_q24, "target_activity_q24": n.target_activity_q24,
        "threshold_rate_q24": n.threshold_rate_q24, "threshold_min_q24": n.threshold_min_q24,
        "threshold_max_q24": n.threshold_max_q24, "eligibility_decay_q24": n.eligibility_decay_q24
    });
    json!({
        "cell_id": cell.cell_id.as_str(),
        "bundle_digest": cell.bundle_digest.into_array(),
        "state_schema_digest": cell.state_schema_digest.into_array(),
        "max_input_bytes": cell.max_input_bytes,
        "max_queue_age_micros": cell.max_queue_age_micros,
        "max_resident_bytes": cell.max_resident_bytes,
        "candidates": cell.candidates.iter().map(|candidate| json!({
            "candidate_id": candidate.candidate_id.as_str(),
            "activation_index": candidate.activation_index,
            "kind": match candidate.kind {
                CellCandidateKindV1::Action => "action",
                CellCandidateKindV1::Abstain => "abstain",
                CellCandidateKindV1::SlowPath => "slow_path",
            }
        })).collect::<Vec<_>>(),
        "runtime": runtime, "native": native
    })
}

#[test]
fn ordinary_q24_public_source_preimage_preserves_actual_definition_and_task() -> anyhow::Result<()>
{
    let directory = tempfile::tempdir()?;
    let (_, _, definition) = super::super::material::model(directory.path())?;
    let source = super::super::material::source("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let paths = OriginalAFilePaths::new(directory.path(), directory.path());
    let fleet = codex_hepta_paths::HeptaFleetRoot::parse(directory.path().join("fleet"))?;
    let agent = codex_hepta_contracts::AgentId::parse(source.scope.agent_id.as_str())?;
    let layout = fleet.layout().agent(&agent);
    let identity = AgentdIdentity {
        agent_id: agent,
        spawn_generation: 1,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace: directory.path().into(),
        resources: codex_hepta_fleet::ResourceBudget::local_default(),
        home_root: layout.home_root().into(),
        run_root: layout.run_root().into(),
        control_socket: layout.agentd_control_socket().into(),
        app_server_socket: layout.app_server_socket().into(),
        layout,
    };
    let value = paths.source_data(
        &identity,
        &definition,
        &source,
        &directory.path().join("ledger.json"),
    )?;
    let decoded = crate::OriginalSingleQ24SourceConfigurationV1::from_original_deployment_bytes(
        &serde_json::to_vec(&value)?,
        &identity,
    )?;
    pretty_assertions::assert_eq!(decoded.definition, definition);
    pretty_assertions::assert_eq!(decoded.source, source);
    pretty_assertions::assert_eq!(decoded.source_journal, paths.source);
    pretty_assertions::assert_eq!(decoded.source_witness, paths.source_witness);
    decoded.registry()?;
    Ok(())
}
