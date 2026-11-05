//! Cold rollback of all Automation/FinalUse files and the real Chain namespace.
//! The clock and CAS frontier remain live outside that rollback boundary. Their
//! fixture keys and services do not qualify independent production custody.

use super::*;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::os::unix::fs::PermissionsExt;

#[derive(Clone, Copy, Debug)]
enum FutureEvent {
    ConsumedNonce,
    RevokedGrant,
}

#[derive(Debug, Eq, PartialEq)]
enum ClosedEntry {
    Directory(u32),
    File(u32, u64, Sha256Digest),
}

// Call only after closing the SQLx pool, dropping every FinalUse owner and
// awaiting each native provider child. Refuse symlinks and special files.
fn copy_closed_tree(source: &Path, destination: &Path) -> anyhow::Result<()> {
    let metadata = fs::symlink_metadata(source)?;
    anyhow::ensure!(metadata.is_dir() && !destination.exists());
    fs::create_dir(destination)?;
    fs::set_permissions(destination, metadata.permissions())?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let target = destination.join(entry.file_name());
        let kind = entry.file_type()?;
        if kind.is_dir() {
            copy_closed_tree(&entry.path(), &target)?;
        } else {
            anyhow::ensure!(kind.is_file(), "nonregular cold-state entry");
            fs::copy(entry.path(), &target)?;
            fs::set_permissions(&target, entry.metadata()?.permissions())?;
            fs::File::open(&target)?.sync_all()?;
        }
    }
    fs::File::open(destination)?.sync_all()?;
    Ok(())
}

fn closed_tree_image(root: &Path) -> anyhow::Result<BTreeMap<PathBuf, ClosedEntry>> {
    let mut image = BTreeMap::new();
    let mut pending = vec![PathBuf::new()];
    let mut total_bytes = 0u64;
    while let Some(relative) = pending.pop() {
        // These bounds cover only test snapshots, not any production protocol.
        anyhow::ensure!(image.len() < 512, "cold fixture has too many files");
        let path = root.join(&relative);
        let metadata = fs::symlink_metadata(&path)?;
        let mode = metadata.permissions().mode() & 0o7777;
        let entry = if metadata.is_dir() {
            for child in fs::read_dir(&path)? {
                pending.push(relative.join(child?.file_name()));
            }
            ClosedEntry::Directory(mode)
        } else {
            anyhow::ensure!(metadata.is_file(), "nonregular cold-state entry");
            total_bytes = total_bytes
                .checked_add(metadata.len())
                .context("snapshot size")?;
            anyhow::ensure!(total_bytes <= 64 * 1024 * 1024, "cold fixture is too large");
            let bytes = fs::read(path)?;
            assert_eq!(u64::try_from(bytes.len())?, metadata.len());
            ClosedEntry::File(mode, metadata.len(), Sha256Digest::for_bytes(&bytes))
        };
        image.insert(relative, entry);
    }
    Ok(image)
}

fn require_final_use_closed(authority_root: &Path) -> anyhow::Result<()> {
    let lock = fs::File::options()
        .read(true)
        .write(true)
        .open(authority_root.join("authority.lock"))?;
    lock.try_lock()
        .map_err(|error| anyhow::anyhow!("FinalUse owner still open: {error}"))?;
    drop(lock);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[ignore = "requires exact Chain release binary; selected by paired native CI"]
async fn real_chain_pq_packet_v1_full_local_rollback_is_rejected_by_retained_frontier()
-> anyhow::Result<()> {
    // The runner binds this declared source to its exact checkout/build. Each
    // pair gets a separate result; this test verifies the actual ELF digest.
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
        for event in [FutureEvent::ConsumedNonce, FutureEvent::RevokedGrant] {
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
            chain.call("status", &namespace, &[]).await?;
            let wire = chain
                .packet(
                    "make",
                    &namespace,
                    &root.join("first.packet"),
                    genesis_time + 10,
                )
                .await?;
            assert_eq!(wire.len(), 49_508);
            anyhow::ensure!(
                wire.len() > crate::MAX_AUTOMATION_EFFECT_WIRE_BYTES
                    && wire.len() <= crate::MAX_AUTOMATION_EFFECT_PACKET_V1_BYTES
            );
            let scope = Sha256Digest::for_bytes(b"pq-packet-control-cold-rollback");
            let mut setup = PqFixture::http("http://127.0.0.1:9", &scope)?;
            setup.config["contract_id"] = serde_json::json!("pq-packet-rollback-chain");
            setup.config["provider"] = serde_json::json!({
                "provider_kind": "trillionnium-pon-local-v1",
                "chain_binary": binary, "chain_binary_sha256": digest.as_str(),
                "chain_store": namespace, "chain_state_backend": backend,
                "chain_genesis_time": genesis_time, "chain_evaluation_policy": "legacy-first-two-v3",
                "chain_task_profile": "legacy-task-v1", "chain_model_profile": "linear-expert-dev-v1",
                "chain_workers": 1, "chain_min_confirmation_depth": 1,
                "chain_min_confirmation_work_depth_hex": format!("{}02", "00".repeat(63)),
                "timeout_ms": 30_000,
            });
            let provider: ProviderConfig =
                serde_json::from_value(setup.config["provider"].clone())?;
            let mut contract = b"hepta.agentd.pon-provider-contract.pq.v3\0".to_vec();
            contract.extend(serde_json::to_vec(&serde_json::json!({
                "provider_scope": setup.config["provider_scope"],
                "destination_id": setup.config["destination_id"],
                "final_use_scope_sha256": setup.config["final_use_scope_sha256"],
                "provider": provider,
            }))?);
            setup.sign_contract(&Sha256Digest::for_bytes(&contract))?;
            let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
            setup.now.store(now, Ordering::SeqCst);
            setup.publish_feed(&setup.feed(setup.head.clone(), now - 1000, now + 60_000)?)?;
            let original_config = fs::read(&setup.config_path)?;
            let original_feed = fs::read(&setup.feed_path)?;
            let mut intent = effect_intent(&scope);
            intent.payload_digest = Sha256Digest::for_bytes(&wire);
            prepare_effect(&fixture, now.saturating_sub(10), &intent).await?;
            let grant = setup.grant_at(&intent, now - 1000, now + 30_000)?;
            let original_grant = serde_json::to_vec(&grant)?;
            let key = ProviderEffectKey::for_taskflow_v2(
                "provider/fixture-v1",
                &fixture.identity.agent_id,
                &intent.run_id,
                &intent.step_id,
            )
            .map_err(|error| anyhow::anyhow!("{error:?}"))?;
            let provider_intent =
                ProviderEffectIntent::new(key.clone(), intent.payload_digest.clone());
            let initial = AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path)?;
            assert_eq!(
                initial.authority.authentication_profile(),
                FinalUseAuthenticationProfile::MlDsa65V2
            );
            assert_eq!(initial.authority.capacity()?.used_nonces, 0);
            let original_frontier = initial.authority.frontier()?;
            assert!(
                !initial
                    .adapter
                    .current_chain_observation(&provider_intent, Some(&wire),)
                    .await
                    .context("native pre-snapshot observation")?
                    .stored_exact
            );

            // AutomationStore owns the only SQLite pool in this rollback
            // boundary. FinalUse is a separately locked file journal. Every
            // native Chain call above has exited before either tree is copied.
            drop(initial);
            fixture.store.close().await;
            let automation_root = fixture.identity.layout.automation_root();
            let authority_root = automation_root.join("final-use-authority");
            require_final_use_closed(&authority_root)?;
            assert_eq!(
                fixture.store.path(),
                automation_root.join("automation_1.sqlite3")
            );
            let snapshots = tempfile::tempdir()?;
            let automation_copy = snapshots.path().join("automation");
            let provider_copy = snapshots.path().join("receiver");
            let original_automation = closed_tree_image(&automation_root)?;
            let original_authority = closed_tree_image(&authority_root)?;
            let original_provider = closed_tree_image(&namespace)?;
            copy_closed_tree(&automation_root, &automation_copy)?;
            copy_closed_tree(&namespace, &provider_copy)?;
            assert_eq!(closed_tree_image(&automation_copy)?, original_automation);
            assert_eq!(closed_tree_image(&provider_copy)?, original_provider);

            let store = AutomationStore::open(&fixture.identity.layout).await?;
            let host = Arc::new(AgentdAutomationEffectHost::open(
                &fixture.identity,
                &setup.config_path,
            )?);
            assert_eq!(host.authority.frontier()?, original_frontier);
            let control = ControlFixture::start(&fixture, store.clone(), Arc::clone(&host)).await?;
            let command = "pq-packet-rollback-future";
            match event {
                FutureEvent::ConsumedNonce => {
                    let receipt = control.packet(&intent, &wire, &grant, command).await?;
                    assert_eq!(
                        receipt.observation,
                        crate::AutomationEffectObservation::Succeeded
                    );
                    let durable = store
                        .authorized_taskflow_effect_attempt(
                            &intent.run_id,
                            &intent.step_id,
                            intent.attempt,
                        )
                        .await?
                        .context("durable full packet before rollback")?;
                    assert_eq!(durable.wire_payload.as_deref(), Some(wire.as_slice()));
                    assert_eq!(durable.provider_effect_key.as_ref(), Some(&key));
                    let terminal = store
                        .read_authorized_taskflow_effect_receipt(&intent, command)
                        .await?
                        .context("terminal receipt before rollback")?;
                    assert_eq!(receipt.receipt_digest, terminal.receipt_digest);
                    assert_eq!(host.authority.capacity()?.used_nonces, 1);
                    let observation = host
                        .adapter
                        .current_chain_observation(&provider_intent, Some(&wire))
                        .await
                        .context("native consumed-state observation")?;
                    assert!(observation.stored_exact && observation.active_chain_member);
                }
                FutureEvent::RevokedGrant => {
                    let mut revoked = setup.head.clone();
                    revoked.revision += 1;
                    revoked
                        .revoked_grant_ids
                        .insert(grant.grant.grant_id.clone());
                    setup.publish_feed(&setup.feed(
                        revoked.clone(),
                        now - 1000,
                        now + 60_000,
                    )?)?;
                    let refused = control
                        .packet(&intent, &wire, &grant, command)
                        .await
                        .unwrap_err();
                    assert!(refused.to_string().contains("Revoked"), "{refused}");
                    assert_eq!(host.authority.revocation_head()?, revoked);
                    assert_eq!(host.authority.capacity()?.used_nonces, 0);
                    assert!(
                        !host
                            .adapter
                            .current_chain_observation(&provider_intent, Some(&wire),)
                            .await
                            .context("native revoked-state observation")?
                            .stored_exact
                    );
                }
            }
            let future_frontier = host.authority.frontier()?;
            let future_used_nonces = host.authority.capacity()?.used_nonces;
            assert_ne!(future_frontier, original_frontier);
            let frontier_path = setup.root.path().join("frontier.json");
            let retained_frontier_bytes = fs::read(&frontier_path)?;
            assert_eq!(
                serde_json::from_slice::<FinalUseFrontier>(&retained_frontier_bytes)?,
                future_frontier
            );

            control.stop().await?;
            tokio::time::timeout(Duration::from_secs(2), async {
                while Arc::strong_count(&host) != 1 {
                    tokio::task::yield_now().await;
                }
            })
            .await?;
            store.close().await;
            drop(host);
            require_final_use_closed(&authority_root)?;
            // Keep the advanced evidence intact. Rename only closed owners,
            // then restore whole cold trees at their exact configured paths.
            fs::rename(
                &automation_root,
                automation_root.with_file_name("rollback-retained-automation"),
            )?;
            fs::rename(&namespace, root.join("retained-receiver"))?;
            copy_closed_tree(&automation_copy, &automation_root)?;
            copy_closed_tree(&provider_copy, &namespace)?;
            // Replay the original signed bytes; never sign restored state.
            write_private(&setup.config_path, &original_config)?;
            write_private(&setup.feed_path, &original_feed)?;
            assert_eq!(fs::read(&setup.config_path)?, original_config);
            assert_eq!(fs::read(&setup.feed_path)?, original_feed);
            assert_eq!(serde_json::to_vec(&grant)?, original_grant);
            assert_eq!(closed_tree_image(&automation_root)?, original_automation);
            assert_eq!(closed_tree_image(&namespace)?, original_provider);
            assert_eq!(fs::read(&frontier_path)?, retained_frontier_bytes);

            // Reopen real AutomationStore to prove the attempt and terminal
            // evidence actually disappeared with the full local rollback.
            // SQLite may update its own bookkeeping during this open, so its
            // exact cold image was checked above, before opening any pool.
            let restored_store = AutomationStore::open(&fixture.identity.layout).await?;
            for _ in 0..2 {
                assert!(
                    restored_store
                        .authorized_taskflow_effect_attempt(
                            &intent.run_id,
                            &intent.step_id,
                            intent.attempt,
                        )
                        .await?
                        .is_none()
                );
                assert!(
                    restored_store
                        .read_authorized_taskflow_effect_receipt(&intent, command,)
                        .await?
                        .is_none()
                );
                match AgentdAutomationEffectHost::open(&fixture.identity, &setup.config_path) {
                    Err(AgentdError::Invalid(message)) => {
                        assert_eq!(
                            message,
                            "PQ automation effect authority: AntiRollbackViolation"
                        );
                    }
                    Err(error) => anyhow::bail!("wrong rollback refusal: {error}"),
                    Ok(_) => anyhow::bail!("ordinary PQ owner accepted rolled-back local state"),
                }
                require_final_use_closed(&authority_root)?;
                assert_eq!(fs::read(&frontier_path)?, retained_frontier_bytes);
                assert_eq!(closed_tree_image(&authority_root)?, original_authority);
                assert_eq!(closed_tree_image(&namespace)?, original_provider);
            }
            restored_store.close().await;
            println!(
                "{}",
                serde_json::json!({
                    "case": "ordinary-pq-full-local-rollback",
                    "backend": backend, "future_event": format!("{event:?}"),
                    "chain_source": source, "chain_binary_sha256": digest.as_str(),
                    "wire_bytes": wire.len(), "wire_sha256": intent.payload_digest.as_str(),
                    "restored_full_automation_and_final_use": true,
                    "restored_full_chain_namespace": true,
                    "retained_external_frontier": future_frontier,
                    "future_used_nonces_before_restore": future_used_nonces,
                    "ordinary_loader_antirollback_refusals": 2,
                    "provider_files_unchanged_after_restore": true,
                    "startup_evidence_recovery_executed": false,
                    "readiness_is_component_fixture": true,
                    "independent_trust_deployment_qualified": false,
                    "chain_task_profile_is_pq": false,
                    "energy_cost_measured": false,
                    "production_activation_qualified": false,
                })
            );
        }
    }
    Ok(())
}
