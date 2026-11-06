//! Additional paired controls for the same ordinary adapter and actual NPQ6 Node.
//! Original paired three tests and their budgets are unchanged. Readiness and
//! independently deployed trust remain explicit component qualifications.
use super::*;
#[path = "automation_effect_host_pq_npq6_chain_support.rs"]
mod support;
use support::Material;
use support::Ready;
use support::owner_released;
use support::resign_provider;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires freshly exported public NPQ6 material and exact Chain binary; selected paired gate"]
async fn ordinary_npq6_control_socket_executes_task_and_evaluator_then_cold_offline_receipt()
-> anyhow::Result<()> {
    let material = Material::read()?;
    for name in ["task", "evaluator"] {
        let Ready {
            fixture,
            setup,
            host,
            intent,
            grant,
            wire,
            provider_intent,
            namespace,
            block,
            now,
        } = material.prepare(name).await?;
        let control =
            ControlFixture::start(&fixture, fixture.store.clone(), Arc::clone(&host)).await?;
        let command = "ordinary-npq6-dispatch";
        let before = host
            .adapter
            .current_chain_observation(&provider_intent, Some(&wire))
            .await
            .context("actual NPQ6 ordinary pre-dispatch observation")?;
        assert!(!before.stored_exact);
        assert_eq!(before.block_id, block);
        let mut altered = grant.clone();
        altered.signature[0] ^= 1;
        let error = control
            .packet(&intent, &wire, &altered, command)
            .await
            .unwrap_err();
        assert!(error.to_string().contains("InvalidSignature"), "{error}");
        assert_eq!(host.authority.capacity()?.used_nonces, 0);
        assert!(
            fixture
                .store
                .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
                .await?
                .is_none()
        );
        let receipt = control.packet(&intent, &wire, &grant, command).await?;
        assert_eq!(
            receipt.observation,
            crate::AutomationEffectObservation::Succeeded
        );
        let pending = fixture
            .store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await?
            .context("exact durable attempt")?;
        assert_eq!(pending.owner_agent_id, fixture.identity.agent_id);
        assert_eq!(pending.intent_digest, intent.digest()?);
        assert_eq!(pending.payload_digest, intent.payload_digest);
        assert_eq!(pending.wire_payload.as_deref(), Some(wire.as_slice()));
        let original = fixture
            .store
            .read_authorized_taskflow_effect_receipt(&intent, command)
            .await?
            .context("original exact terminal receipt")?;
        assert_eq!(receipt.receipt_digest, original.receipt_digest);
        let after = host
            .adapter
            .current_chain_observation(&provider_intent, Some(&wire))
            .await
            .context("actual NPQ6 ordinary post-dispatch observation")?;
        assert!(after.stored_exact && after.active_chain_member);
        assert_eq!(after.block_id, block);
        assert_eq!(after.active_depth, Some(0));
        assert_eq!(
            after.payload_sha256.as_deref(),
            Some(intent.payload_digest.as_str())
        );
        assert!(!after.confirmation_policy_satisfied);
        assert!(!after.finality_authority && !after.execution_authority);
        let frontier = host.authority.frontier()?;
        assert_eq!(host.authority.capacity()?.used_nonces, 1);
        control.stop().await?;
        owner_released(&host).await?;
        fixture.store.close().await;
        drop(host);
        let store = AutomationStore::open(&fixture.identity.layout).await?;
        let reopened = Arc::new(AgentdAutomationEffectHost::open(
            &fixture.identity,
            &setup.config_path,
        )?);
        assert_eq!(reopened.authority.frontier()?, frontier);
        let control = ControlFixture::start(&fixture, store.clone(), Arc::clone(&reopened)).await?;
        // Offline replay must use the original durable receipt; it cannot
        // recreate a namespace or require a still-live grant/provider service.
        let retained = namespace.with_file_name("retained-receiver");
        anyhow::ensure!(!retained.exists());
        fs::rename(&namespace, &retained)?;
        setup.now.store(now + 90000, Ordering::SeqCst);
        drop(setup);
        let replay = control.packet(&intent, &wire, &grant, command).await?;
        assert_eq!(replay, receipt);
        assert_eq!(
            store
                .read_authorized_taskflow_effect_receipt(&intent, command)
                .await?,
            Some(original)
        );
        assert_eq!(reopened.authority.capacity()?.used_nonces, 1);
        assert!(!namespace.exists());
        assert!(
            control
                .packet(&intent, &wire, &grant, "different-command")
                .await
                .is_err()
        );
        control.stop().await?;
        owner_released(&reopened).await?;
        store.close().await;
        println!(
            "{}",
            serde_json::json!({"case":name,"real_npq6_packet":true,
            "original_control_socket":true,"signed_pq_final_use":true,"ordinary_adapter":true,
            "cold_offline_exact_receipt":true,"used_nonces":1,
            "provider_timeout_configuration_ms":30000,"server_io_timeout_configuration_ms":2000,
            "app_server_readiness_fixture_only":true,"independent_trust_deployment_qualified":false,
            "whole_node_rollback_protection":false,"production_activation":false})
        );
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires freshly exported incompatible real NPQ6 owner and exact Chain binary"]
async fn ordinary_npq6_started_child_context_refusal_stays_unknown_through_cold_reconciliation()
-> anyhow::Result<()> {
    let material = Material::read()?;
    let Ready {
        fixture,
        setup,
        host,
        intent,
        grant,
        wire,
        provider_intent,
        namespace,
        now,
        ..
    } = material.prepare("owner-mismatch").await?;
    let database = fs::read(namespace.join("native.sqlite"))?;
    let control = ControlFixture::start(&fixture, fixture.store.clone(), Arc::clone(&host)).await?;
    let receipt = control
        .packet(&intent, &wire, &grant, "ordinary-npq6-context-refusal")
        .await?;
    assert_ne!(
        receipt.observation,
        crate::AutomationEffectObservation::Succeeded
    );
    // This exact digest distinguishes post-start Unknown from NotDispatched.
    let unknown = receipt_from_dispatch(&provider_intent, &ProviderEffectDispatch::Unknown);
    assert_eq!(
        receipt.receipt_digest.as_ref(),
        Some(&unknown.receipt_digest)
    );
    assert_eq!(host.authority.capacity()?.used_nonces, 1);
    let pending = fixture
        .store
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .context("unknown attempt retained")?;
    assert_eq!(pending.wire_payload.as_deref(), Some(wire.as_slice()));
    assert!(pending.provider_effect_key.is_some());
    assert!(pending.provider_ack.is_none());
    assert_eq!(pending.owner_agent_id, fixture.identity.agent_id);
    assert_eq!(pending.payload_digest, intent.payload_digest);
    assert_eq!(fs::read(namespace.join("native.sqlite"))?, database);
    let frontier = host.authority.frontier()?;
    control.stop().await?;
    owner_released(&host).await?;
    fixture.store.close().await;
    drop(host);
    let store = AutomationStore::open(&fixture.identity.layout).await?;
    let reopened = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    assert_eq!(reopened.authority.frontier()?, frontier);
    assert!(matches!(
        reopened
            .reconcile(
                &store,
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                now + 2
            )
            .await?,
        AgentdAutomationEffectReconcileOutcome::Indeterminate
    ));
    let cold = store
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .context("cold unknown preserved")?;
    assert_eq!(cold.wire_payload, pending.wire_payload);
    assert_eq!(cold.provider_effect_key, pending.provider_effect_key);
    assert!(cold.provider_ack.is_none());
    assert_eq!(reopened.authority.capacity()?.used_nonces, 1);
    assert_eq!(fs::read(namespace.join("native.sqlite"))?, database);
    store.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires exact binary and freshly exported NPQ6 public configuration for real signed loader"]
async fn ordinary_npq6_signed_provider_rejects_tampered_contract_config_and_profile_before_effect()
-> anyhow::Result<()> {
    let material = Material::read()?;
    let Ready {
        fixture,
        mut setup,
        host,
        intent,
        ..
    } = material.prepare("provider-loader").await?;
    assert_eq!(host.authority.capacity()?.used_nonces, 0);
    drop(host);
    let original = setup.config.clone();
    for fault in 0..5 {
        setup.config = original.clone();
        let expected = match fault {
            0 => {
                setup.config["provider"]["chain_workers"] = serde_json::json!(2);
                setup.write_config()?;
                "NPQ6 PoN provider contract digest mismatch"
            }
            1 => {
                let signature = setup.config["contract_signature"]
                    .as_array_mut()
                    .context("signature")?;
                signature[0] =
                    serde_json::json!(signature[0].as_u64().context("signature byte")? ^ 1);
                setup.write_config()?;
                "" // A single bad signature byte in the otherwise known-good contract.
            }
            2 => {
                setup.config["provider"]["chain_application"]["application_profile"] =
                    serde_json::json!("legacy-task-v1");
                resign_provider(&mut setup)?;
                "explicit Linux NPQ6 application profile required"
            }
            3 => {
                setup.config["provider"]["chain_application"]["configuration_sha256"] =
                    serde_json::json!("00".repeat(32));
                resign_provider(&mut setup)?;
                "NPQ6 configuration digest mismatch"
            }
            4 => {
                setup.config["provider"]["chain_application"]["owner"] = serde_json::json!({
                    "profile":"witness_v4","writer_key":setup.config_path});
                resign_provider(&mut setup)?;
                "NPQ6 signed provider/configuration context mismatch"
            }
            _ => unreachable!(),
        };
        let trust_before = setup.trust_requests();
        let error =
            AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path).unwrap_err();
        if !expected.is_empty() {
            assert!(
                error.to_string().contains(expected),
                "fault {fault}: {error}"
            );
        }
        assert_eq!(
            setup.trust_requests(),
            trust_before,
            "provider refusal must precede opening final-use trust"
        );
        assert!(
            fixture
                .store
                .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
                .await?
                .is_none()
        );
    }
    setup.config = original;
    setup.write_config()?;
    let valid = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
    assert_eq!(valid.authority.capacity()?.used_nonces, 0);
    fixture.store.close().await;
    Ok(())
}
