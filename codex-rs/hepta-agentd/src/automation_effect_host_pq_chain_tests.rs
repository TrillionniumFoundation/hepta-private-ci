//! Ordinary PQ admission through the original AutomationStore and real Chain.
//! Requires the unchanged native-pair environment; absent pins fail when selected.
//! Local signed trust services do not qualify independent production custody.

use super::super::super::pon_process::chain_tests::Chain;
use super::*;
use anyhow::Context;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires the exact Chain release binary; selected explicitly by paired native CI"]
async fn real_chain_ordinary_pq_packet_v1_dispatches_once_and_reads_original_receipt()
-> anyhow::Result<()> {
    let source = std::env::var("HEPTA_PON_CHAIN_SOURCE")?;
    anyhow::ensure!(
        source.len() == 40
            && source
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)),
        "missing exact Chain source identity"
    );
    let binary = PathBuf::from(std::env::var("HEPTA_PON_CHAIN_BINARY")?).canonicalize()?;
    let digest = Sha256Digest::parse(std::env::var("HEPTA_PON_CHAIN_SHA256")?)
        .map_err(anyhow::Error::msg)?;
    assert_eq!(Sha256Digest::for_bytes(&fs::read(&binary)?), digest);
    let genesis_time = SystemTime::now()
        .duration_since(UNIX_EPOCH)?
        .as_secs()
        .checked_sub(3600)
        .context("native Chain fixture clock")?;

    for backend in ["legacy-v2", "authenticated-v1"] {
        let fixture = Fixture::new().await?;
        let chain_root = tempfile::tempdir()?;
        let root = chain_root.path().canonicalize()?;
        let namespace = root.join("receiver");
        let chain = Chain {
            binary: binary.clone(),
            digest: digest.clone(),
            genesis_time,
            backend,
        };
        // Reuse the existing sealed command owner, 30-second deadline,
        // 64-KiB output bound and unchanged native packet generator.
        chain.call("status", &namespace, &[]).await?;
        let wire = chain
            .packet(
                "make",
                &namespace,
                &root.join("first.packet"),
                genesis_time + 10,
            )
            .await?;
        // The original inline interface remains too small for this exact
        // workload. The successor packet protocol is qualified separately.
        assert!(wire.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES);
        assert!(wire.len() <= crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES);
        let scope = Sha256Digest::for_bytes(b"ordinary-pq-real-chain");
        let mut setup = PqFixture::http("http://127.0.0.1:9", &scope)?;
        setup.config["contract_id"] = serde_json::json!("pq-real-chain-fixture");
        setup.config["provider"] = serde_json::json!({
            "provider_kind": "trillionnium-pon-local-v1",
            "chain_binary": binary, "chain_binary_sha256": digest.as_str(),
            "chain_store": namespace, "chain_state_backend": backend,
            "chain_genesis_time": genesis_time,
            "chain_evaluation_policy": "legacy-first-two-v3",
            "chain_task_profile": "legacy-task-v1",
            "chain_model_profile": "linear-expert-dev-v1",
            "chain_workers": 1, "chain_min_confirmation_depth": 1,
            "chain_min_confirmation_work_depth_hex": format!("{}02", "00".repeat(63)),
            "timeout_ms": 30_000,
        });
        let provider: ProviderConfig = serde_json::from_value(setup.config["provider"].clone())?;
        let mut contract = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
        contract.extend(serde_json::to_vec(&serde_json::json!({
            "provider_scope": setup.config["provider_scope"],
            "destination_id": setup.config["destination_id"],
            "final_use_scope_sha256": setup.config["final_use_scope_sha256"],
            "provider": provider,
        }))?);
        setup.sign_contract(&Sha256Digest::for_bytes(&contract))?;
        let mut intent = effect_intent(&scope);
        intent.payload_digest = Sha256Digest::for_bytes(&wire);
        prepare_effect(&fixture, NOW, &intent).await?;
        let key = ProviderEffectKey::for_taskflow_v2(
            "provider/fixture-v1",
            &fixture.identity.agent_id,
            &intent.run_id,
            &intent.step_id,
        )
        .map_err(|error| anyhow::anyhow!("{error:?}"))?;
        let provider_intent = ProviderEffectIntent::new(key.clone(), intent.payload_digest.clone());
        let host = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
        assert_eq!(
            host.authority.authentication_profile(),
            FinalUseAuthenticationProfile::MlDsa65V2
        );
        let before = host
            .adapter
            .current_chain_observation(&provider_intent, Some(&wire))
            .await
            .context("real pre-dispatch packet observation")?;
        assert!(!before.stored_exact);
        let grant = setup.grant(&intent, NOW + 30_000)?;
        assert!(matches!(
            host.execute(
                &fixture.store,
                &intent,
                &wire,
                &grant,
                "pq-real-chain-dispatch",
                NOW + 5,
            )
            .await,
            Err(AgentdError::Invalid(message))
                if message == "automation effect wire payload is empty or too large"
        ));
        assert_eq!(host.authority.capacity()?.used_nonces, 0);
        assert!(
            fixture.store
                .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
                .await?
                .is_none()
        );
        let permits = Arc::new(tokio::sync::Semaphore::new(/*permits*/ 2));
        let packet = crate::control_packet::AdmittedEffectPacketV1::read(
            &mut wire.as_slice(),
            u32::try_from(wire.len())?,
            &intent.payload_digest,
            Arc::clone(&permits),
            &crate::NeuralCognitiveExecutionV1::with_deadline(
                Instant::now() + Duration::from_secs(30),
                tokio_util::sync::CancellationToken::new(),
            ),
        ).await?;
        let receipt = host
            .execute_packet_v1(
                &fixture.store,
                &intent,
                &packet,
                &grant,
                "pq-real-chain-dispatch",
                NOW + 5,
            )
            .await?;
        assert_eq!(
            receipt.observation,
            Some(TaskFlowStepObservation::Succeeded)
        );
        let durable = fixture
            .store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
            .context("original durable provider attempt")?;
        assert_eq!(durable.owner_agent_id, fixture.identity.agent_id);
        assert_eq!(durable.intent_digest, intent.digest()?);
        assert_eq!(durable.payload_digest, intent.payload_digest);
        assert_eq!(durable.provider_effect_key.as_ref(), Some(&key));
        assert_eq!(durable.wire_payload.as_deref(), Some(wire.as_slice()));
        let included = host
            .adapter
            .current_chain_observation(&provider_intent, Some(&wire))
            .await
            .context("real dispatched packet observation")?;
        assert!(included.stored_exact && included.active_chain_member);
        assert_eq!(included.block_id, before.block_id);
        assert_eq!(included.active_depth, Some(0));
        assert_eq!(included.provider_effect_key.as_deref(), Some(key.as_str()));
        assert_eq!(
            included.payload_sha256.as_deref(),
            Some(intent.payload_digest.as_str())
        );
        assert!(!included.confirmation_policy_satisfied);
        assert!(!included.finality_authority && !included.execution_authority);
        // Bind the durable receipt to the exact native block identified before
        // dispatch, using the existing provider acknowledgement contract.
        let mut block_binding = b"trillionnium.pon.block.v1\0".to_vec();
        block_binding.extend_from_slice(before.block_id.as_bytes());
        let expected = AuthorizedEffectProviderReceipt::from_provider_ack(
            ProviderEffectAck::new(
                key.clone(),
                intent.payload_digest.clone(),
                Sha256Digest::for_bytes(&block_binding),
                ProviderEffectAckStatus::Completed,
            ),
            ProviderEffectAckSource::DispatchResponse,
        );
        assert_eq!(
            receipt.receipt_digest.as_ref(),
            Some(&expected.receipt_digest)
        );
        let consumed = host.authority.frontier()?;
        assert_eq!(host.authority.capacity()?.used_nonces, 1);
        assert_eq!(
            serde_json::from_slice::<FinalUseFrontier>(&fs::read(
                setup.root.path().join("frontier.json")
            )?)?,
            consumed
        );
        fixture.store.close().await;
        drop(host);
        let store = AutomationStore::open(&fixture.identity.layout).await?;
        let reopened = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
        assert_eq!(reopened.authority.frontier()?, consumed);
        assert_eq!(reopened.authority.capacity()?.used_nonces, 1);
        // All helper children have exited. Move only this test's own namespace
        // after loader validation, and stop the local trust services. Successful
        // exact terminal readback must not depend on either being available;
        // this is not a measurement of operating-system process-start counts.
        fs::rename(&namespace, root.join("retained-receiver"))?;
        setup.now.store(NOW + 90_000, Ordering::SeqCst);
        drop(setup);
        let replay = reopened
            .execute_packet_v1(
                &store,
                &intent,
                &packet,
                &grant,
                "pq-real-chain-dispatch",
                NOW + 90_000,
            )
            .await?;
        assert_eq!(replay, receipt);
        assert_eq!(reopened.authority.capacity()?.used_nonces, 1);
        assert!(!namespace.exists());
        let retained = store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
            .context("retained original provider attempt")?;
        assert_eq!(retained, durable);
        store.close().await;
        drop(packet);
        assert_eq!(permits.available_permits(), 2);
        println!(
            "PON_ORDINARY_PQ_PACKET_V1_PAIR {}",
            serde_json::json!({
                "chain_source": source, "binary_sha256": digest.as_str(), "backend": backend,
                "provider_effect_key": key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
                "packet_bytes": wire.len(), "ordinary_wire_limit": crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES,
                "packet_v1_limit": crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES,
                "legacy_inline_refused_before_consumption": true,
                "transport_version": "packet_v1", "control_socket_exercised": false,
                "included": included, "used_nonces": 1,
                "exact_terminal_readback_without_provider_or_trust": true,
                "process_start_count_measured": false, "chain_task_profile_is_pq": false,
                "independent_trust_deployment_qualified": false, "production_activation": false,
            })
        );
    }
    Ok(())
}
