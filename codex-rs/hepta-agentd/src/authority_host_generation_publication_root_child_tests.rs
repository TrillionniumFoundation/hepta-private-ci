//! Dedicated non-Root child: actual original five-lane inputs, purpose handoff,
//! CURRENT client, consumed FinalUse dispatch, then read-only explicit recovery.

use super::*;
use anyhow::Context;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_contracts::dispatch_final_use_with_witness;
use pretty_assertions::assert_eq;

#[test]
#[ignore = "only the original UID0 component parent launches this dedicated child"]
fn original_publication_dedicated_uid_child() -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), 60001, 60001)?;
    let number: i32 = std::env::var("HEPTA_LEARNING_SERVICE_CHILD_FD")?.parse()?;
    let root: u32 = std::env::var("HEPTA_LEARNING_SERVICE_ROOT_PID")?.parse()?;
    anyhow::ensure!(
        number >= 3 && root != std::process::id(),
        "original inherited pair"
    );
    // SAFETY: this is the dedicated child process only; its whole run is bounded.
    unsafe { libc::alarm(60) };
    let state = std::env::var_os("HEPTA_LEARNING_SERVICE_STATE")
        .ok_or_else(|| anyhow::anyhow!("original protected state"))?;
    assert_eq!(
        std::fs::read_dir(state).unwrap_err().kind(),
        io::ErrorKind::PermissionDenied
    );
    // SAFETY: the original parent transfers this one inherited descriptor.
    let socket = unsafe { UnixDatagram::from_raw_fd(number) };
    const OBSERVATION_WORKERS: usize = 2;
    tokio::runtime::Builder::new_multi_thread().worker_threads(OBSERVATION_WORKERS)
        .enable_all().build()?.block_on(async {
        let mut original_head: Option<types::CurrentHead> = None;
        let mut published_head: Option<types::CurrentHead> = None;
        for phase in [Phase::Publish, Phase::Recover, Phase::RetiredSession, Phase::Revoked] {
            eprintln!("ROOT_PUBLICATION_CHILD phase={phase:?} step=receive-original-offers");
            let (mut sealed, root_pin) = crate::receive_root_production_handoff(socket.try_clone()?, LIFETIME)
                .with_context(|| format!("publication {phase:?}: receive original production handoff"))?;
            let mut raw = Vec::new();
            sealed.rewind()?;
            sealed.read_to_end(&mut raw)?;
            let original: HostAuthorityPublicBootstrapV1 = serde_json::from_slice(&raw)?;
            assert_eq!((original.root.pid, original.root.uid, original.consumer.uid), (root, 0, 60001));
            let identity = original.registered_identity.identity()
                .with_context(|| format!("publication {phase:?}: resolve original registered fleet/workspace identity"))?;
            sealed.rewind()?;
            let mut learning = crate::receive_root_learning_handoff(socket.try_clone()?, LIFETIME)
                .with_context(|| format!("publication {phase:?}: receive original learning handoff"))?;
            let publication = crate::receive_root_generation_publication_handoff(socket.try_clone()?, LIFETIME)
                .with_context(|| format!("publication {phase:?}: receive original publication handoff"))?;
            let timing = crate::root_authority_session::tests::component_phase_timing(
                "publication.child.five-lane-open", phase,
            );
            let mut production = crate::receive_root_production_inputs(
                sealed, root_pin, &identity, TIMEOUT, LIFETIME,
            ).await.with_context(|| format!("publication {phase:?}: connect original five-lane inputs"))?;
            drop(timing);
            eprintln!("ROOT_PUBLICATION_CHILD phase={phase:?} step=original-inputs-connected");
            assert_eq!(production.session.revocations()?, original.revocations);
            let connection = production.take_generation_publication_connection()
                .with_context(|| format!("publication {phase:?}: take original connection"))?;
            assert!(matches!(production.take_generation_publication_connection().err(),
                Some(crate::AgentdError::GenerationFenced(message)) if message.contains("already taken")));
            // Public bootstrap metadata cannot replace the sealed original
            // captured by this one connection capability.
            production.bootstrap.root.pid = std::process::id();
            let timing = crate::root_authority_session::tests::component_phase_timing(
                "publication.child.learning-checkpoint", phase,
            );
            raw.clear();
            learning.bootstrap.rewind()?;
            learning.bootstrap.read_to_end(&mut raw)?;
            let bundle: HostAuthorityLearningBootstrapV1 = serde_json::from_slice(&raw)?;
            assert_eq!(bundle.registered_identity.identity()
                .with_context(|| format!("publication {phase:?}: resolve original learning identity"))?, identity);
            let initial = bundle.decode_initial()?;
            let scope = bundle.frozen_scope(&initial)?.ok_or_else(|| anyhow::anyhow!("actual Cell scope"))?;
            let checkpoint = crate::AgentdLearningCheckpointClientV1::from_root_stream_scoped_v2(
                UnixStream::connect(&bundle.socket_path)?,
                crate::AgentdRootAuthorityPeer { pid: bundle.root.pid, boot_id: bundle.root.boot_id,
                    process_start_ticks: bundle.root.process_start_ticks },
                learning.root_pidfd, initial.clone(), TIMEOUT, LIFETIME, scope,
            ).with_context(|| format!("publication {phase:?}: connect original learning checkpoint"))?;
            let decision = record_component_decision(initial.clone())?;
            if matches!(phase, Phase::Publish) {
                assert_eq!(checkpoint.restore(&initial.request).await
                    .with_context(|| format!("publication {phase:?}: restore vacant original checkpoint"))?, None);
                checkpoint.checkpoint(Digest32::ZERO, &initial).await
                    .with_context(|| format!("publication {phase:?}: write original initial checkpoint"))?;
                let mut replay = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
                for receipt in &decision.snapshot().receipts {
                    let previous = replay.snapshot().head_digest;
                    replay.record(receipt.clone(), receipt.observed_unix_seconds)?;
                    assert_eq!(checkpoint.checkpoint(previous, replay.snapshot()).await
                        .with_context(|| format!("publication {phase:?}: write original component checkpoint"))?,
                        replay.snapshot().head_digest);
                }
            }
            assert_eq!(checkpoint.restore(&initial.request).await
                .with_context(|| format!("publication {phase:?}: restore original decision checkpoint"))?,
                Some(decision.snapshot().clone()));
            drop(timing);
            eprintln!("ROOT_PUBLICATION_CHILD phase={phase:?} step=learning-ready");
            // Neither Root late registration nor this child's publication
            // connection has occurred. Both real original services responded.
            assert_eq!(socket.send(b"LEARNING_AND_ORIGINAL_INPUTS_READY")?, 34);
            let timing = crate::root_authority_session::tests::component_phase_timing(
                "publication.child.root-enrollment-wait", phase,
            );
            let intent: types::UpdateIntent = data(&socket)
                .with_context(|| format!("publication {phase:?}: receive registered original intent"))?;
            drop(timing);
            let operation = learning_retained_task_operation_id_v1(&decision)?;
            assert_eq!(intent.operation_id, operation.as_str());
            let claims = production.bootstrap.consumers.device.local_state_dir.join("authority.claims");
            if matches!(phase, Phase::Revoked) {
                let revoked: codex_hepta_contracts::FinalUseRevocations = data(&socket)
                    .context("publication Revoked: receive original issuer revocation head")?;
                production.session.component_wait_for_original_revocations(
                    [&production.device, &production.notes], &revoked, TIMEOUT,
                ).await.context("publication Revoked: await original consumer and public feed barrier")?;
                let record = published_head.as_ref().and_then(|head| head.published.as_ref())
                    .ok_or_else(|| anyhow::anyhow!("original retained published record"))?;
                assert_eq!(production.device.verify_retained_use(&record.signed, &intent.binding()?, &record.witness).err(),
                    Some(FinalUseError::Revoked));
                let before = std::fs::read(&claims)?;
                assert_eq!(socket.send(b"STABLE")?, 6);
                control(&socket, b"CHECKED")?;
                assert!(publication.connect(connection, TIMEOUT, LIFETIME).await.is_err(),
                    "revoked original publication must not reconstruct a usable CURRENT client");
                assert_eq!(std::fs::read(&claims)?, before);
                assert_eq!(socket.send(b"DONE")?, 4);
                drop((checkpoint, production));
                continue;
            }
            let timing = crate::root_authority_session::tests::component_phase_timing(
                "publication.child.current-connect", phase,
            );
            let current = publication.connect(connection, TIMEOUT, LIFETIME).await
                .with_context(|| format!("publication {phase:?}: connect original CURRENT purpose"))?;
            drop(timing);
            eprintln!("ROOT_PUBLICATION_CHILD phase={phase:?} step=current-connected");
            assert!(!current.store.is_original_host(), "non-Root holds the real Root lane, never a writable directory");
            current.require_original_root_selection(decision.snapshot(), &operation,
                Digest32::from_array(intent.selection))
                .with_context(|| format!("publication {phase:?}: require original Root selection"))?;
            let before = current.store.load()
                .with_context(|| format!("publication {phase:?}: read original CURRENT"))?;
            if matches!(phase, Phase::Publish) {
                original_head = Some(before.clone());
                let mut prepared = before.clone();
                prepared.prepared = Some(intent.clone());
                let timing = crate::root_authority_session::tests::component_phase_timing(
                    "publication.child.prepare-current", phase,
                );
                current.store.replace(&before, &prepared)
                    .context("publication Publish: prepare original CURRENT")?;
                assert_eq!(current.store.load()
                    .context("publication Publish: read original prepared CURRENT")?, prepared);
                drop(timing);
                assert_eq!(socket.send(b"PREPARED")?, 8);
                control(&socket, b"GENESIS")?;
                let binding = intent.binding()?;
                let timing = crate::root_authority_session::tests::component_phase_timing(
                    "publication.child.request-grant", phase,
                );
                let signed = production.grants.request_grant(&binding)
                    .context("publication Publish: request original grant")?;
                drop(timing);
                let timing = crate::root_authority_session::tests::component_phase_timing(
                    "publication.child.claim-dispatch-publish", phase,
                );
                let token = claim_final_use(&production.device, &signed, &binding)
                    .context("publication Publish: claim original grant")?;
                let (result, witness) = dispatch_final_use_with_witness(
                    &production.device, token, &binding, |witness| -> Result<types::CurrentHead, crate::AgentdError> {
                        let next = types::CurrentHead {
                            schema_version: 1, current: intent.target.clone(), prepared: None, initial: None,
                            published: Some(types::Published { intent: intent.clone(), signed: signed.clone(),
                                witness: witness.clone(), signed_grant_digest: signed_grant_digest(&signed)?.into_array() }),
                        };
                        current.store.replace(&prepared, &next)?;
                        let actual = current.store.load()?;
                        assert_eq!(actual, next);
                        Ok(actual)
                    },
                ).context("publication Publish: dispatch original grant")?;
                let published = result.context("publication Publish: original CURRENT dispatch effect")?;
                drop(timing);
                assert_eq!(published.published.as_ref().map(|record| &record.witness), Some(&witness));
                assert_eq!(production.device.capacity()?.used_nonces, 1);
                let nonce = std::fs::read(&claims)?;
                assert_eq!(claim_final_use(&production.device, &signed, &binding).err(), Some(FinalUseError::AlreadyClaimed));
                let recovered = current.recover_operation(&intent.operation_id, intent.digest()?)?;
                let observed = current.read_operation(&recovered)?;
                let NeuronGenerationUpdateReadbackV1::Published(observed) = observed else {
                    anyhow::bail!("actual original publication was not retained");
                };
                assert_eq!(observed.signed_grant(), &signed);
                assert_eq!(observed.witness(), &witness);
                assert_eq!(std::fs::read(&claims)?, nonce);
                published_head = Some(published);
                assert_eq!(socket.send(b"STABLE")?, 6);
                control(&socket, b"CHECKED")?;
                let mut wrong = decision.snapshot().clone();
                wrong.request.source_run_id = StableId::new("wrong-original-learning-scope")?;
                wrong.head_digest = digest("wrong-original-learning-scope");
                let error = current.require_original_root_selection(&wrong, &operation,
                    Digest32::from_array(intent.selection)).unwrap_err();
                require_uncertain(error);
                require_uncertain(current.store.load().unwrap_err());
                assert_eq!(std::fs::read(&claims)?, nonce);
            } else {
                assert_eq!(Some(&before), published_head.as_ref());
                let nonce = std::fs::read(&claims)?;
                let recovered = current.recover_operation(&intent.operation_id, intent.digest()?)?;
                let NeuronGenerationUpdateReadbackV1::Published(readback) = current.read_operation(&recovered)? else {
                    anyhow::bail!("explicit recovery must observe published original");
                };
                assert_eq!(readback.target(), &intent.target);
                assert_eq!(production.device.capacity()?.used_nonces, 1);
                assert_eq!(std::fs::read(&claims)?, nonce);
                assert_eq!(socket.send(b"STABLE")?, 6);
                control(&socket, b"CHECKED")?;
                if matches!(phase, Phase::RetiredSession) {
                    // The connection's Arc cannot prolong the original session.
                    // Its actual Drop fences the same verifier before any new
                    // CURRENT exchange, even though this client still exists.
                    drop(production);
                    require_uncertain(current.store.load().unwrap_err());
                    require_uncertain(current.store.load().unwrap_err());
                    assert_eq!(std::fs::read(&claims)?, nonce);
                    drop((current, checkpoint));
                    assert_eq!(socket.send(b"DONE")?, 4);
                    continue;
                }
                let old = original_head.as_ref().ok_or_else(|| anyhow::anyhow!("original old generation"))?;
                let mut old_prepared = old.clone();
                old_prepared.prepared = Some(intent.clone());
                require_uncertain(current.store.replace(old, &old_prepared).unwrap_err());
                require_uncertain(current.store.load().unwrap_err());
                assert_eq!(std::fs::read(&claims)?, nonce);
            }
            drop(current);
            assert_eq!(socket.send(b"DONE")?, 4);
            drop((checkpoint, production));
        }
        Ok::<(), anyhow::Error>(())
    })?;
    println!(
        "ROOT_PUBLICATION_ORIGINAL lifecycle=passed actual_consumer_uid=60001 actual_consumer_pid={} original_root_pid={root} vacant_learning_before_late_enrollment=true actual_current_cas=true actual_claims=1 original_connection_taken_once=true original_session_drop_fences_current=true explicit_same_process_root_reopen=true ordinary_complete=0 independent_consumer=0 physical_cold_restart=0",
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
        if error.get_ref().is_some_and(<dyn std::error::Error + std::marker::Send + std::marker::Sync + 'static>::is::<crate::root_generation_current_client::RootGenerationPublicationUncertain>)),
        "original closed client must keep typed uncertainty: {error}"
    );
}
