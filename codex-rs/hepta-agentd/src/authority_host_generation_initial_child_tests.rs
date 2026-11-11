//! Dedicated actual UID60001 consumer. The existing initial publisher claims
//! and dispatches once. Recovery only reads original published bytes; it never
//! reclaims, executes a task, supplies a learning decision or resets CURRENT.

use super::*;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::claim_final_use;
use pretty_assertions::assert_eq;

#[test]
#[ignore = "only the actual original UID0 component parent launches this child"]
fn original_initial_dedicated_uid_child() -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), 60001, 60001)?;
    let descriptor: i32 = std::env::var("HEPTA_LEARNING_SERVICE_CHILD_FD")?.parse()?;
    let root: u32 = std::env::var("HEPTA_LEARNING_SERVICE_ROOT_PID")?.parse()?;
    anyhow::ensure!(descriptor >= 3 && root != std::process::id(), "original inherited pair");
    // SAFETY: only the dedicated child process; the whole component is bounded.
    unsafe { libc::alarm(60) };
    let state = std::env::var_os("HEPTA_LEARNING_SERVICE_STATE")
        .ok_or_else(|| anyhow::anyhow!("original protected state"))?;
    assert_eq!(std::fs::read_dir(state).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    // SAFETY: the original parent explicitly passes this one owned descriptor.
    let socket = unsafe { UnixDatagram::from_raw_fd(descriptor) };
    let mut observed_ack_loss = false;
    const OBSERVATION_WORKERS: usize = 2;
    tokio::runtime::Builder::new_multi_thread().worker_threads(OBSERVATION_WORKERS)
        .enable_all().build()?.block_on(async {
        let mut original_claims: Option<Vec<u8>> = None;
        for phase in [Phase::Publish, Phase::ReserveExisting, Phase::Recover, Phase::RetiredSession, Phase::Corrupt, Phase::Restored] {
            let (mut sealed, root_pin) =
                crate::receive_root_production_handoff(socket.try_clone()?, LIFETIME)?;
            let mut bytes = Vec::new();
            sealed.rewind()?;
            sealed.read_to_end(&mut bytes)?;
            let original: HostAuthorityPublicBootstrapV1 = serde_json::from_slice(&bytes)?;
            assert_eq!((original.root.pid, original.root.uid, original.consumer.uid), (root, 0, 60001));
            let identity = original.registered_identity.identity()?;
            sealed.rewind()?;
            let initial = crate::receive_root_generation_initial_handoff(socket.try_clone()?, LIFETIME)?;
            let plan: Plan = data(&socket)?;
            assert_eq!(plan.phase, phase);
            let (journal, witness) = receive_target_files(&socket)?;
            let mut production = crate::receive_root_production_inputs(
                sealed, root_pin, &identity, TIMEOUT, LIFETIME,
            ).await?;
            let connection = production.take_generation_publication_connection()?;
            assert!(production.take_generation_publication_connection().is_err());
            let claims = production.bootstrap.consumers.device.local_state_dir.join("authority.claims");
            // Only the same original Artifact writer is reopened, after the
            // parent released it and transferred its retained signed inputs.
            let (artifacts, selected) = plan.artifacts.reopen(now_ms()?)?;
            let (model, bundle, definition) = material::load(&plan.model_directory)?;
            let source = material::source(identity.agent_id.as_str())?;
            let target = crate::OriginalRootInitialFeatureTargetV1 {
                files: RootGenerationJournalInputsV1 {
                    journal, witness, config: plan.target.original_observer_config()?,
                },
                model, bundle: bundle.clone(), definition, source,
            };
            let authorities = crate::AgentdGenerationUpdateAuthoritiesV1::new(
                artifacts, Arc::new(production.device.clone()), production.session.clock(),
            )?;
            assert_eq!(socket.send(b"ORIGINAL_INPUTS_READY")?, 21);
            let enrolled: bool = data(&socket)?;
            if matches!(phase, Phase::ReserveExisting | Phase::Corrupt | Phase::Restored) {
                assert!(!enrolled, "existing CURRENT, actual corrupt or durably fenced original material rejected");
                assert_eq!(production.device.capacity()?.used_nonces, 1);
                assert_eq!(Some(std::fs::read(&claims)?), original_claims);
                drop((initial, connection, authorities, selected, target));
                assert_eq!(socket.send(b"STABLE")?, 6);
                control(&socket, b"CHECKED")?;
                assert_eq!(socket.send(b"DONE")?, 4);
                drop(production);
                continue;
            }
            assert!(enrolled);
            let initial = initial.connect(connection, TIMEOUT, LIFETIME).await?;
            if phase == Phase::Publish {
                assert_eq!(production.device.capacity()?.used_nonces, 0);
                let prepared = initial.prepare_feature(authorities, selected, target)?;
                let binding = prepared.final_use_binding().clone();
                let signed = production.grants.request_grant(&binding)?;
                let result = prepared.publish(&signed);
                if plan.lose_ack {
                    require_uncertain(result.err().ok_or_else(|| anyhow::anyhow!("controlled ACK must be lost"))?);
                    observed_ack_loss = true;
                } else {
                    let task = result?;
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
                let task = initial.recover_feature(authorities, selected, target)?;
                task.require_bundle(&bundle)?;
                assert_eq!(production.device.capacity()?.used_nonces, 1);
                assert_eq!(std::fs::read(&claims)?, before);
                if phase == Phase::RetiredSession {
                    // This actual session drop fences the shared live verifier;
                    // retaining the task/Current Arc cannot extend its authority.
                    drop(production);
                    assert!(task.require_bundle(&bundle).is_err());
                    assert_eq!(std::fs::read(&claims)?, before);
                    drop(task);
                    assert_eq!(socket.send(b"STABLE")?, 6);
                    control(&socket, b"CHECKED")?;
                    assert_eq!(socket.send(b"DONE")?, 4);
                    continue;
                }
                drop(task);
            }
            assert_eq!(socket.send(b"STABLE")?, 6);
            control(&socket, b"CHECKED")?;
            assert_eq!(Some(std::fs::read(&claims)?), original_claims);
            assert_eq!(socket.send(b"DONE")?, 4);
            drop(production);
        }
        Ok::<(), anyhow::Error>(())
    })?;
    println!("ROOT_INITIAL_ORIGINAL lifecycle=passed actual_consumer_uid=60001 actual_consumer_pid={} original_root_pid={root} separate_initial_purpose=true actual_current_initial_cas=true actual_claims=1 read_only_same_operation_recovery=true controlled_post_cas_ack_loss={observed_ack_loss} existing_current_refused=true sticky_restored_source_refused=true explicit_same_process_root_reopen=true ordinary_complete=0 independent_consumer=0 physical_cold_restart=0", std::process::id());
    let mut released = [0];
    std::io::stdin().read_exact(&mut released)?;
    assert_eq!(released, [1]);
    Ok(())
}

fn require_uncertain(error: crate::AgentdError) {
    assert!(matches!(error, crate::AgentdError::Io(ref error)
        if error.get_ref().is_some_and(|source|
            source.is::<crate::root_generation_initial_client::RootGenerationInitialUncertain>())),
        "original Initial acknowledgement remains typed uncertain: {error}");
}
