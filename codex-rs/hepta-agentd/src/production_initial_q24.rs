//! Ordinary first-A product assembly from the existing original Root inputs.
//! It installs a real signed-task Circuit driver. The optional Ledger profile
//! uses actual Root-enrolled trust; later historical learning is a separate stage.

use super::*;
use crate::AgentdQ24CircuitTaskRuntimeV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::CircuitQ24TaskProfileV1;
use crate::OriginalRootInitialFeatureTargetV1;
use crate::RootGenerationInitialModeV1;

#[path = "production_initial_q24_clock.rs"]
mod clock;
#[path = "production_initial_q24_deployment.rs"]
mod deployment;
#[path = "production_initial_q24_files.rs"]
mod files;
#[path = "production_initial_q24_ledger_data.rs"]
mod ledger_data;
#[path = "production_initial_q24_ledger_files.rs"]
mod ledger_files;
#[path = "production_initial_q24_load.rs"]
mod load;
#[path = "production_initial_q24_writer.rs"]
pub(super) mod writer;

impl AgentdProductionLaunch {
    /// Select only the explicit `q24-initial` CLI profile. Every other original
    /// primary retains its existing composition. The explicit Ledger option
    /// consumes the original Root trust and external Observer role. It never
    /// infers an Outcome from task success or assembles post-A learning here.
    pub async fn assemble_original_initial_q24(
        mut self,
        config: AgentdConfig,
    ) -> Result<(Self, AgentdConfig), AgentdError> {
        let deployment = match &mut self.inputs.primary {
            PrimaryInputs::InitialQ24 { deployment } => deployment
                .take()
                .ok_or_else(|| refused("original Initial Q24 deployment was already consumed"))?,
            _ => return Ok((self, config)),
        };
        config.require_original_initial_q24_configuration()?;
        self.require_original_initial_q24_session(config.identity())?;
        let identity = config.identity().clone();
        let now = self.root.session.clock().now_unix_ms().map_err(refused)?;
        let inputs = tokio::task::spawn_blocking(move || load::open(deployment, &identity, now))
            .await
            .map_err(|_| refused("original Initial Q24 loader was lost"))??;
        self.require_original_initial_q24_session(config.identity())?;
        let handoff: crate::RootGenerationInitialHandoffV1 =
            self.take_generation_initial_handoff()?;
        let connection: crate::RootGenerationPublicationConnectionV1 =
            self.take_generation_publication_connection()?;
        let original: crate::OriginalRootGenerationInitialV1 = handoff
            .connect_until(
                connection,
                initial_remaining(self.session_end)?.min(Duration::from_millis(500)),
                self.session_end,
            )
            .await?;
        self.require_original_initial_q24_session(config.identity())?;
        let load::OriginalInputs {
            mut files,
            data,
            target,
            artifacts,
            task,
        } = inputs;
        if original.client.mode() != RootGenerationInitialModeV1::Reserve
            || original.client.mode() != data.initial.mode
            || original.client.profile().deployment.operation != data.initial.operation
        {
            return Err(refused(
                "original Initial Q24 mode or operation differs from Root",
            ));
        }
        let (authorities, selected) = original
            .client
            .open_original_artifact_authorities(&self.root, artifacts)?;
        let target = OriginalRootInitialFeatureTargetV1 {
            files: target,
            model: Arc::clone(&data.model),
            bundle: data.bundle.clone(),
            definition: data.source.definition.clone(),
            source: data.source.source.clone(),
        };
        let grants: Arc<crate::AgentdUnixFinalUseGrantProvider> = Arc::clone(&self.root.grants);
        let end = self.session_end;
        let published = tokio::task::spawn_blocking(move || {
            initial_remaining(end)?;
            clock::require_source_deadline(&target.source)?;
            let prepared: crate::PreparedRootInitialFeatureV1 =
                original.prepare_feature(authorities, selected, target)?;
            // After Root's durable Prepare, any grant/publication uncertainty
            // is retained recovery. It never retries with a new nonce or input.
            let result = (|| {
                initial_remaining(end)?;
                let signed =
                    grants
                        .request_grant(prepared.final_use_binding())
                        .map_err(|error| {
                            AgentdError::Protocol(format!("original Initial grant: {error}"))
                        })?;
                initial_remaining(end)?;
                prepared.publish(&signed)
            })();
            result.map_err(crate::root_generation_initial_client::uncertain_after_prepare)
        })
        .await
        .map_err(|_| refused("original Initial publication acknowledgement lost"))??;
        self.require_original_initial_q24_session(config.identity())?;
        let (published, ledger) = match data.ledger {
            Some(deployment) => {
                let root = self.root;
                let identity = config.identity().clone();
                let (root, published, ledger) = tokio::task::spawn_blocking(move || {
                    initial_remaining(end)?;
                    let trust =
                        published.read_original_initial_learning_trust(&root.session, &identity)?;
                    let ledger = ledger_files::open(deployment, trust, &mut files)?;
                    // The same Root files, trust window, CURRENT, Artifact
                    // selection and consumed FinalUse must still hold after IO.
                    drop(published.read_original_initial_learning_trust(&root.session, &identity)?);
                    initial_remaining(end)?;
                    Ok::<_, AgentdError>((root, published, ledger))
                })
                .await
                .map_err(|_| refused("original Ledger assembly acknowledgement lost"))??;
                self.root = root;
                (published, Some(ledger))
            }
            None => {
                drop(files);
                (published, None)
            }
        };
        self.require_original_initial_q24_session(config.identity())?;
        self.retain_original_initial_source_capture(&published)?;
        let profile = CircuitQ24TaskProfileV1 {
            files: task,
            source_mode: CircuitQ24TaskOpenModeV1::Create,
            published_task: published,
            fence: data.source.fence,
            circuit: data.source.circuit,
            routes: data.source.routes,
            bundle: data.bundle,
            model: data.model,
            worker_generation: data.worker_generation,
            maximum_cell_records: data.maximum_cell_records,
            queue_capacity: data.queue_capacity,
            clock: Arc::new(clock::sample),
        };
        let runtime = match ledger {
            Some(inputs) => {
                let crate::AgentdQ24LearningTaskRuntimeV1 { task, ledger } =
                    config.with_q24_learning_task_profile(profile, inputs)?;
                // Config/State owns the real producer until the actual joined
                // runtime drains. Do not keep a second producer past capture.
                drop(ledger);
                task
            }
            None => config.with_q24_circuit_task_profile(profile)?,
        };
        let AgentdQ24CircuitTaskRuntimeV1 {
            config,
            source,
            cell,
        } = runtime;
        // Only the configured runtime retains the original Source/Cell owners.
        // `run` must join all State/control futures before the zero-payload
        // Root capture hook. Leaked external owners still fail Root's flocks.
        drop((source, cell));
        self.require_original_initial_q24_session(config.identity())?;
        Ok((self, config))
    }

    fn require_original_initial_q24_session(
        &self,
        identity: &AgentdIdentity,
    ) -> Result<(), AgentdError> {
        initial_remaining(self.session_end)?;
        if self.root.bootstrap.registered_identity.identity()? != *identity {
            return Err(refused(
                "original Root Q24 identity differs from this daemon",
            ));
        }
        self.root
            .session
            .verifier()
            .verify_sender_process_binding(
                &self.root.session.authority(),
                &identity.agent_id,
                &self.root.bootstrap.writer.local_lease_id,
                self.root.bootstrap.writer.local_lease_generation,
                identity.spawn_generation,
            )
            .map_err(AgentdError::GenerationFenced)?;
        initial_remaining(self.session_end)?;
        Ok(())
    }
}

fn initial_remaining(end: Instant) -> Result<Duration, AgentdError> {
    end.checked_duration_since(Instant::now())
        .filter(|remaining| !remaining.is_zero() && *remaining <= Duration::from_secs(300))
        .ok_or_else(|| refused("original Root Initial lifetime expired"))
}

fn refused(message: impl std::fmt::Display) -> AgentdError {
    AgentdError::GenerationFenced(message.to_string())
}
