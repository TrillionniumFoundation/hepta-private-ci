//! Dedicated actual UID60001 consumer. The existing initial publisher claims
//! and dispatches once. Recovery only reads original published bytes; it never
//! reclaims, executes a task, supplies a learning decision or resets CURRENT.

use super::*;
use anyhow::Context;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::claim_final_use;
use pretty_assertions::assert_eq;

#[test]
#[ignore = "only the actual original UID0 component parent launches this child"]
fn original_initial_dedicated_uid_child() -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), 60001, 60001)?;
    let descriptor: i32 = std::env::var("HEPTA_LEARNING_SERVICE_CHILD_FD")?.parse()?;
    let root: u32 = std::env::var("HEPTA_LEARNING_SERVICE_ROOT_PID")?.parse()?;
    anyhow::ensure!(
        descriptor >= 3 && root != std::process::id(),
        "original inherited pair"
    );
    // SAFETY: only the dedicated child process; the whole component is bounded.
    unsafe { libc::alarm(60) };
    let state = std::env::var_os("HEPTA_LEARNING_SERVICE_STATE")
        .ok_or_else(|| anyhow::anyhow!("original protected state"))?;
    assert_eq!(
        std::fs::read_dir(state).unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    // SAFETY: the original parent explicitly passes this one owned descriptor.
    let socket = unsafe { UnixDatagram::from_raw_fd(descriptor) };
    let mut observed_ack_loss = false;
    const OBSERVATION_WORKERS: usize = 2;
    tokio::runtime::Builder::new_multi_thread().worker_threads(OBSERVATION_WORKERS)
        .enable_all().build()?.block_on(async {
        let mut original_claims: Option<Vec<u8>> = None;
        for phase in [Phase::Publish, Phase::ReserveExisting, Phase::Recover, Phase::RetiredSession, Phase::Corrupt, Phase::Restored] {
            eprintln!("ROOT_INITIAL_CHILD phase={phase:?} stage=awaiting_original_handoffs");
            let (mut sealed, root_pin) =
                crate::receive_root_production_handoff(socket.try_clone()?, LIFETIME)
                    .with_context(|| format!("initial child {phase:?}: receiving original production handoff"))?;
            let mut bytes = Vec::new();
            sealed.rewind()?;
            sealed.read_to_end(&mut bytes)?;
            let original: HostAuthorityPublicBootstrapV1 = serde_json::from_slice(&bytes)?;
            assert_eq!((original.root.pid, original.root.uid, original.consumer.uid), (root, 0, 60001));
            let identity = original.registered_identity.identity()
                .with_context(|| format!("initial child {phase:?}: validating original registered filesystem identity"))?;
            sealed.rewind()?;
            let initial = crate::receive_root_generation_initial_handoff(socket.try_clone()?, LIFETIME)
                .with_context(|| format!("initial child {phase:?}: receiving original initial handoff"))?;
            let plan: Plan = data(&socket)
                .with_context(|| format!("initial child {phase:?}: receiving component plan"))?;
            assert_eq!(plan.phase, phase);
            let (journal, witness) = receive_target_files(&socket)
                .with_context(|| format!("initial child {phase:?}: receiving original target descriptors"))?;
            let mut production = crate::receive_root_production_inputs(
                sealed, root_pin, &identity, TIMEOUT, LIFETIME,
            ).await.with_context(|| format!("initial child {phase:?}: opening original five-lane inputs"))?;
            eprintln!("ROOT_INITIAL_CHILD phase={phase:?} stage=original_five_lane_inputs_open");
            let connection = production.take_generation_publication_connection()?;
            assert!(production.take_generation_publication_connection().is_err());
            let claims = production.bootstrap.consumers.device.local_state_dir.join("authority.claims");
            let original_artifacts = match plan.artifact_access {
                ArtifactAccess::OriginalWriter => Some(plan.artifacts.reopen(now_ms()?)
                    .with_context(|| format!("initial child {phase:?}: reopening original Artifact owner"))?),
                ArtifactAccess::OriginalReadView => {
                    // Root retains the actual writer, so a writer fallback is
                    // physically unavailable throughout this entire scenario.
                    let error = plan.artifacts.reopen(now_ms()?).err()
                        .ok_or_else(|| anyhow::anyhow!("retained original Artifact writer must stay locked"))?;
                    assert!(matches!(
                        error.downcast_ref::<codex_hepta_learning_artifacts::LearningArtifactOwnerServiceError>(),
                        Some(codex_hepta_learning_artifacts::LearningArtifactOwnerServiceError::Host(
                            codex_hepta_learning_artifacts::ArtifactOwnerHostError::WriterFenceBusy
                        ))
                    ), "original writer refusal: {error}");
                    None
                }
            };
            let (model, bundle, definition) = material::load(&plan.model_directory)
                .with_context(|| format!("initial child {phase:?}: loading actual model material"))?;
            let source = material::source(identity.agent_id.as_str())?;
            let target = crate::OriginalRootInitialFeatureTargetV1 {
                files: RootGenerationJournalInputsV1 {
                    journal, witness, config: plan.target.original_observer_config()?,
                },
                model, bundle: bundle.clone(), definition, source,
            };
            assert_eq!(socket.send(b"ORIGINAL_INPUTS_READY")?, 21);
            eprintln!("ROOT_INITIAL_CHILD phase={phase:?} stage=original_inputs_ready_sent");
            let enrolled: bool = data(&socket)
                .with_context(|| format!("initial child {phase:?}: awaiting original enrollment result"))?;
            if matches!(phase, Phase::ReserveExisting | Phase::Corrupt | Phase::Restored) {
                assert!(!enrolled, "existing CURRENT, actual corrupt or durably fenced original material rejected");
                assert_eq!(production.device.capacity()?.used_nonces, 1);
                assert_eq!(Some(std::fs::read(&claims)?), original_claims);
                drop((initial, connection, original_artifacts, target));
                assert_eq!(socket.send(b"STABLE")?, 6);
                control(&socket, b"CHECKED")
                    .with_context(|| format!("initial child {phase:?}: awaiting parent CHECKED"))?;
                assert_eq!(socket.send(b"DONE")?, 4);
                control(&socket, b"STOP")
                    .with_context(|| format!("initial child {phase:?}: awaiting parent STOP"))?;
                // These original refusal paths may already have fenced their
                // purpose. Do not demand fresh authority to close them.
                drop(production);
                assert_eq!(socket.send(b"CLOSED")?, 6);
                control(&socket, b"PHASE_COMPLETE")
                    .with_context(|| format!("initial child {phase:?}: awaiting original server completion"))?;
                continue;
            }
            assert!(enrolled);
            let initial = initial.connect(connection, TIMEOUT, LIFETIME).await
                .with_context(|| format!("initial child {phase:?}: connecting original initial lane"))?;
            let (authorities, selected) = match original_artifacts {
                Some((artifacts, selected)) => (
                    crate::AgentdGenerationUpdateAuthoritiesV1::new(
                        artifacts, Arc::new(production.device.clone()), production.session.clock(),
                    ).with_context(|| format!("initial child {phase:?}: binding original publication authorities"))?,
                    selected,
                ),
                None => {
                    let claims_before = std::fs::read(&claims)?;
                    let mut different = plan.artifacts.inputs()?;
                    different.storage_binding = Digest32::of_bytes(b"different-original-storage-binding");
                    assert!(initial.client.open_original_artifact_authorities(&production, different).is_err());
                    assert_eq!(std::fs::read(&claims)?, claims_before);
                    let (authorities, selected) = initial.client.open_original_artifact_authorities(
                        &production, plan.artifacts.inputs()?,
                    ).with_context(|| format!("initial child {phase:?}: binding original readonly Artifact view"))?;
                    assert!(authorities.artifacts.writer().is_err());
                    (authorities, selected)
                }
            };
            if phase == Phase::Publish {
                assert_eq!(production.device.capacity()?.used_nonces, 0);
                let prepared = initial.prepare_feature(authorities, selected, target)
                    .with_context(|| format!("initial child {phase:?}: preparing original Feature CURRENT"))?;
                let binding = prepared.final_use_binding().clone();
                let signed = production.grants.request_grant(&binding)
                    .with_context(|| format!("initial child {phase:?}: requesting original FinalUse grant"))?;
                let result = prepared.publish(&signed);
                if plan.lose_ack {
                    require_uncertain(result.err().ok_or_else(|| anyhow::anyhow!("controlled ACK must be lost"))?);
                    observed_ack_loss = true;
                } else {
                    let task = result
                        .with_context(|| format!("initial child {phase:?}: publishing original Feature CURRENT"))?;
                    task.require_bundle(&bundle)?;
                    drop(task);
                }
                assert_eq!(production.device.capacity()?.used_nonces, 1);
                assert_eq!(claim_final_use(&production.device, &signed, &binding).err(),
                    Some(FinalUseError::AlreadyClaimed));
                let bytes = std::fs::read(&claims)?;
                assert!(!bytes.is_empty());
                original_claims = Some(bytes);
            } else {
                let before = std::fs::read(&claims)?;
                assert_eq!(Some(&before), original_claims.as_ref());
                let task = initial.recover_feature(authorities, selected, target)
                    .with_context(|| format!("initial child {phase:?}: reading original published Feature"))?;
                task.require_bundle(&bundle)?;
                assert_eq!(production.device.capacity()?.used_nonces, 1);
                assert_eq!(std::fs::read(&claims)?, before);
                if phase == Phase::RetiredSession {
                    assert_eq!(socket.send(b"RETIRE_READY")?, 12);
                    control(&socket, b"RETIRE")
                        .with_context(|| format!("initial child {phase:?}: awaiting parent RETIRE"))?;
                    // Validate the retained task under the original serial
                    // permit, then let actual inputs/session Drop fence it.
                    crate::root_authority_session::tests::drop_original_production_after_idle(
                        production,
                        TIMEOUT,
                        || {
                            task.require_bundle(&bundle).map_err(io::Error::other)?;
                            Ok(())
                        },
                    ).await.with_context(|| format!("initial child {phase:?}: retiring original idle session"))?;
                    assert!(task.require_bundle(&bundle).is_err());
                    assert_eq!(std::fs::read(&claims)?, before);
                    drop(task);
                    assert_eq!(socket.send(b"STABLE")?, 6);
                    control(&socket, b"CHECKED")
                    .with_context(|| format!("initial child {phase:?}: awaiting parent CHECKED"))?;
                    assert_eq!(socket.send(b"DONE")?, 4);
                    control(&socket, b"STOP")
                        .with_context(|| format!("initial child {phase:?}: awaiting parent STOP"))?;
                    // The retained task was dropped before STABLE. No original
                    // purpose client or target file is held while waiting.
                    assert_eq!(socket.send(b"CLOSED")?, 6);
                    control(&socket, b"PHASE_COMPLETE")
                        .with_context(|| format!("initial child {phase:?}: awaiting original server completion"))?;
                    continue;
                }
                drop(task);
            }
            assert_eq!(socket.send(b"STABLE")?, 6);
            control(&socket, b"CHECKED")
                    .with_context(|| format!("initial child {phase:?}: awaiting parent CHECKED"))?;
            assert_eq!(Some(std::fs::read(&claims)?), original_claims);
            assert_eq!(socket.send(b"DONE")?, 4);
            control(&socket, b"STOP")
                .with_context(|| format!("initial child {phase:?}: awaiting parent STOP"))?;
            if phase == Phase::Publish && plan.lose_ack {
                // The original controlled ACK-loss lane must remain an error.
                drop(production);
            } else {
                crate::root_authority_session::tests::drop_original_production_after_idle(
                    production,
                    TIMEOUT,
                    || Ok(()),
                ).await.with_context(|| format!("initial child {phase:?}: closing original idle session"))?;
            }
            assert_eq!(socket.send(b"CLOSED")?, 6);
            control(&socket, b"PHASE_COMPLETE")
                .with_context(|| format!("initial child {phase:?}: awaiting original server completion"))?;
        }
        Ok::<(), anyhow::Error>(())
    })?;
    println!(
        "ROOT_INITIAL_ORIGINAL lifecycle=passed actual_consumer_uid=60001 actual_consumer_pid={} original_root_pid={root} separate_initial_purpose=true actual_current_initial_cas=true actual_claims=1 read_only_same_operation_recovery=true controlled_post_cas_ack_loss={observed_ack_loss} existing_current_refused=true sticky_restored_source_refused=true explicit_same_process_root_reopen=true ordinary_complete=0 independent_consumer=0 physical_cold_restart=0",
        std::process::id()
    );
    let mut released = [0];
    std::io::stdin().read_exact(&mut released)?;
    assert_eq!(released, [1]);
    Ok(())
}

fn require_uncertain(error: crate::AgentdError) {
    assert!(
        matches!(error, crate::AgentdError::Io(ref error)
        if error.get_ref().is_some_and(<dyn std::error::Error + std::marker::Send + std::marker::Sync + 'static>::is::<crate::root_generation_initial_client::RootGenerationInitialUncertain>)),
        "original Initial acknowledgement remains typed uncertain: {error}"
    );
}
