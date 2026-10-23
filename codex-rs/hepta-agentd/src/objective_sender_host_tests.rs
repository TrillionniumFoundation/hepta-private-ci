//! Original composition tests. This checkpoint is a test probe, not a
//! production authenticated host checkpoint or a qualification of that trust.

use super::fixture::EXPIRES;
use super::fixture::Fixture;
use super::*;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ObjectiveSenderCheckpointError;
use codex_hepta_memory::ObjectiveSenderError;
use codex_hepta_memory::ObjectiveSenderOrigin;
use codex_hepta_memory::ObjectiveSenderRequest;
use codex_hepta_memory::ObjectiveSenderWriterFence;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::sync::Mutex;
use std::sync::atomic::Ordering;

#[derive(Default)]
struct CheckpointProbe {
    seen: Mutex<Vec<(CognitiveRecoveryAnchor, ObjectiveSenderWriterFence)>>,
}

impl ObjectiveSenderCheckpoint for CheckpointProbe {
    async fn acknowledge_current(
        &self,
        current: &CognitiveRecoveryAnchor,
        writer: &ObjectiveSenderWriterFence,
    ) -> Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError> {
        self.seen
            .lock()
            .unwrap()
            .push((current.clone(), writer.clone()));
        Ok(current.clone())
    }
}

#[tokio::test]
async fn uninstalled_original_objective_sender_refuses_without_a_new_owner()
-> Result<(), Box<dyn Error>> {
    let (config, fixture) = Fixture::new().await?;
    let checkpoint = Arc::new(CheckpointProbe::default());
    assert!(matches!(
        config.original_objective_sender(Arc::clone(&checkpoint), Duration::from_secs(1)),
        Err(AgentdError::CognitiveWriteRuntimeUnavailable)
    ));
    assert!(checkpoint.seen.lock().unwrap().is_empty());
    assert!(config.production_writer_host().is_none());
    let store = CognitiveStore::open(&config.identity().layout).await?;
    assert_eq!(store.recovery_anchor().await?, fixture.cut);
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn installed_original_objective_sender_reuses_same_writer_and_live_verifier()
-> Result<(), Box<dyn Error>> {
    let (mut config, fixture) = Fixture::new().await?;
    let (inputs, probes, _peer) = fixture.inputs()?;
    let attachment = attach_production_operation_host(&mut config, inputs).await?;
    let checkpoint = Arc::clone(&probes.checkpoint);
    let sender = attachment.original_sender;
    let writer = config.production_writer_host().unwrap().writer();
    // The explicit compatibility getter remains available to trusted hosts.
    // The strict path above returns the same original writer/provider binding.
    let same_owner =
        config.original_objective_sender(Arc::clone(&checkpoint), Duration::from_secs(1))?;
    let before = writer.recovery_anchor().await?;
    assert_eq!(checkpoint.seen.lock().unwrap().len(), 1);
    assert_eq!(checkpoint.seen.lock().unwrap()[0].0, before);
    let original = serde_json::to_string(&serde_json::json!({
        "issuer_id": "composition-objective-issuer", "key_epoch": 1,
        "message_id": "composition-objective-message", "sequence": 1,
        "expires_at_ms": EXPIRES * 1_000, "signature_hex": "ab".repeat(64),
        "body": {
            "spawn_generation": config.identity().spawn_generation,
            "run_id": "composition-objective-run", "objective_revision": 1,
            "source_envelope_json": "{\"fixture\":\"original request\"}",
            "runtime_body_digest": "11".repeat(32), "preference_state_digest": "22".repeat(32),
            "model_tuple_digest": "33".repeat(32), "prompt_registry_digest": "44".repeat(32),
            "artifact_set_digest": "55".repeat(32), "authority_epoch": 13
        }
    }))?;
    let request = ObjectiveSenderRequest::from_original(
        original,
        ObjectiveSenderOrigin {
            agent_id: config.identity().agent_id.clone(),
            spawn_generation: config.identity().spawn_generation,
            request_id: 1,
            expected_peer_uid: 1_000,
            expected_peer_pid: 4_321,
            endpoint_identity: "/composition-fixture/original-agentd.sock".to_string(),
        },
    )?;
    let ticket = sender.retain_before_send(request).await?;
    // Ticket affinity requires the exact Arc, not just matching Agent/generation.
    // Success through the directly obtained host capability proves this bridge
    // retained the same original owner; no transport I/O is performed here.
    same_owner.mark_send_started(&ticket).await?;
    assert!(matches!(
        sender.mark_send_started(&ticket).await,
        Err(ObjectiveSenderError::SendPermissionUnavailable)
    ));
    let after = writer.recovery_anchor().await?;
    assert_ne!(before, after);
    assert_eq!(checkpoint.seen.lock().unwrap().len(), 2);
    assert_eq!(checkpoint.seen.lock().unwrap()[1].0, after);
    assert!(
        CognitiveStore::open(&config.identity().layout)
            .await
            .is_err()
    );
    probes.clock.now_ms.store(EXPIRES * 1_000, Ordering::SeqCst);
    assert!(
        config
            .original_objective_sender(checkpoint, Duration::from_secs(1))
            .is_err()
    );
    assert_eq!(probes.target.effects.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn retained_signed_body_hash_matches_original_agentd_wire_projection()
-> Result<(), Box<dyn Error>> {
    let (config, _fixture) = Fixture::new().await?;
    let origin = ObjectiveSenderOrigin {
        agent_id: config.identity().agent_id.clone(),
        spawn_generation: config.identity().spawn_generation,
        request_id: 1,
        expected_peer_uid: 1_000,
        expected_peer_pid: 4_321,
        endpoint_identity: "/composition-fixture/original-agentd.sock".to_string(),
    };
    // The actual original body has no optional fields. Exercise all of them,
    // preserving Unicode and digest spelling rather than inventing defaults.
    for source in ["{}", "{\"goal\":\"你好 🧠\",\"combining\":\"é\"}"] {
        for digest in ["ab".repeat(32), "aB".repeat(32)] {
            let body = AuthBusObjectiveBody {
                spawn_generation: config.identity().spawn_generation,
                run_id: "composition-original-body".to_string(),
                objective_revision: 7,
                source_envelope_json: source.to_string(),
                runtime_body_digest: digest,
                preference_state_digest: "22".repeat(32),
                model_tuple_digest: "33".repeat(32),
                prompt_registry_digest: "44".repeat(32),
                artifact_set_digest: "55".repeat(32),
                authority_epoch: 13,
            };
            let original_payload = crate::objective_runtime::objective_payload(
                config.identity(),
                &body,
                config.identity().spawn_generation,
            )?;
            assert_eq!(original_payload, serde_json::to_vec(&body)?);
            let mut ingress = AuthBusObjectiveIngress {
                issuer_id: "composition-original-issuer".to_string(),
                key_epoch: 3,
                message_id: "composition-original-message".to_string(),
                sequence: 9,
                expires_at_ms: EXPIRES * 1_000,
                signature_hex: "ab".repeat(64),
                body,
            };
            let raw = serde_json::to_string(&ingress)?;
            let retained = ObjectiveSenderRequest::from_original(raw.clone(), origin.clone())?;
            assert_eq!(
                retained.identity().signed_body_sha256,
                Sha256Digest::for_bytes(&original_payload)
            );
            assert_eq!(retained.exact_original(), raw.as_bytes());
            ingress.body.source_envelope_json.clear();
            assert!(
                crate::objective_runtime::objective_payload(
                    config.identity(),
                    &ingress.body,
                    config.identity().spawn_generation,
                )
                .is_err()
            );
            assert!(
                ObjectiveSenderRequest::from_original(
                    serde_json::to_string(&ingress)?,
                    origin.clone()
                )
                .is_err()
            );
        }
    }
    Ok(())
}
