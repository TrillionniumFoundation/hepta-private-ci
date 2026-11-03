//! Ordinary initial cognitive reads without converting to evaluated admission.
//! The same loaded session and opaque selected material move into their original
//! runtime owners; failed attachment retains the session for explicit cleanup.

use super::*;
use codex_hepta_agentd::CurrentCognitiveRegistry;
use codex_hepta_agentd::InitialNeuralCognitiveBootstrapV2;
use codex_hepta_agentd::InitialNeuralCognitiveInferencePortV2;
use codex_hepta_agentd::InitialNeuralCognitiveObservationV2;
use codex_hepta_agentd::InitialNeuralCognitivePinV2;
use codex_hepta_agentd::InitialNeuralCognitiveRequestV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Generation;
use std::time::Duration;

struct InitialCurrentOwner {
    current: Arc<ArtifactOwnerCurrentReaderV1>,
    time: InitialAuthorityTime,
}

impl CurrentCognitiveRegistry for InitialCurrentOwner {
    fn current(
        &self,
    ) -> Result<codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1, String> {
        self.current
            .current_registry_view(self.time.now_seconds()?)
            .map_err(|error| error.to_string())
    }

    fn authority_clock(&self) -> Option<Arc<dyn codex_hepta_contracts::AuthorityClock>> {
        self.time.protected_clock()
    }
}

struct InitialCognitivePort {
    port: Arc<SmolLmNeuralReadPortV1>,
    identity: AgentdIdentity,
    pin: InitialNeuralCognitivePinV2,
    association: (Digest32, String, String),
}

impl InitialNeuralCognitiveInferencePortV2 for InitialCognitivePort {
    fn execute_initial(
        &self,
        request: &InitialNeuralCognitiveRequestV2,
        execution: &codex_hepta_agentd::NeuralCognitiveExecutionV1,
    ) -> Result<InitialNeuralCognitiveObservationV2, String> {
        execution.check()?;
        if request.owner_id != self.identity.agent_id
            || request.body_generation != self.identity.spawn_generation
            || request.pin != self.pin
            || execution.remaining()? > Duration::from_secs(2)
        {
            return Err("ordinary initial read differs from its original owner".to_owned());
        }
        self.port.with_measurements(|load, _| {
            material::validate_public_initial_load(load)?;
            if load.ready_digest() != self.association.0
                || load.parameter_file_digest() != self.pin.payload_digest
                || load.generation() != self.pin.generation.get()
                || load.control_load_ids()
                    != Some((self.association.1.as_str(), self.association.2.as_str()))
            {
                return Err("ordinary initial read lost its original settled load".to_owned());
            }
            Ok(())
        })??;
        let (scores_q32, execution_receipt_digest) = self.port.execute_initial(
            query::InitialReadPermitV1 {
                port: &self.port,
                selection_digest: self.pin.selection_digest,
            },
            &request.query,
            &request.action_ids,
            execution,
        )?;
        execution.check()?;
        Ok(InitialNeuralCognitiveObservationV2 {
            request: request.clone(),
            scores_q32,
            execution_receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

/// Load selected generation-one material and register its distinct ordinary
/// cognitive route. This consumes no evaluated-child credential and creates no
/// issuer, selector, CURRENT head or qualification. Only ordinary task execution
/// can establish later use; preparation alone is not that evidence.
pub async fn prepare_public_initial_smollm_agentd_v2(
    config: AgentdConfig,
    material: SelectedPublicInitialSmolLmMaterialV2,
    current: ArtifactOwnerCurrentReaderV1,
    inputs: SmolLmInitialHostInputsV1,
) -> Result<PreparedSmolLmAgentdV1, InitialSmolLmPreparationErrorV1> {
    let mut owner = prepare_public_initial_smollm_v2(config, material, current, inputs).await?;
    let family_digest = owner.physical.family_digest;
    let execution_profile_digest = owner.physical.execution_profile_digest;
    let result = (|| -> Result<(), String> {
        owner.startup_execution.check()?;
        let pin = owner.with_current_initial_load(|observed| {
            Ok(InitialNeuralCognitivePinV2 {
                payload_digest: observed.measured().parameter_file_digest(),
                generation: Generation::new(observed.measured().generation())
                    .map_err(|error| error.to_string())?,
                selection_digest: observed.selection_digest(),
                family_digest,
                execution_profile_digest,
            })
        })?;
        let port = owner
            .session
            .port
            .as_ref()
            .cloned()
            .ok_or("initial session is closed")?;
        let inference = Arc::new(InitialCognitivePort {
            port,
            identity: owner.identity().clone(),
            pin,
            association: owner
                .association
                .clone()
                .ok_or("initial load association unavailable")?,
        });
        let selected = owner
            .material
            .take()
            .ok_or("initial selected material unavailable")?;
        let InitialMaterial::Public(material) = selected else {
            return Err("ordinary public V2 route refuses historical V1 selection".to_owned());
        };
        owner.startup_execution.check()?;
        owner
            .config
            .attach_selected_initial_neural_cognitive_bootstrap(InitialNeuralCognitiveBootstrapV2 {
                material,
                current: Arc::new(InitialCurrentOwner {
                    current: Arc::clone(&owner.current),
                    time: owner.authority_time.clone(),
                }),
                family_digest,
                execution_profile_digest,
                inference,
            })
            .map_err(|error| error.to_string())?;
        owner.startup_execution.check()
    })();
    if let Err(reason) = result {
        return Err(InitialSmolLmPreparationErrorV1 {
            reason,
            retained: Some(Box::new(owner)),
        });
    }
    Ok(PreparedSmolLmAgentdV1 {
        config: owner.config,
        session: owner.session,
    })
}
