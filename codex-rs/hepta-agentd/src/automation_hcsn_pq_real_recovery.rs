//! Fresh-process recovery uses the actual Agentd host and its retained request.

use super::*;

#[cfg(test)]
pub(super) async fn recover(
    root: &Path,
    input: &SupervisorInput,
    config_bytes: &[u8],
    payload: &[u8],
) -> anyhow::Result<()> {
    let records: Dispatches = serde_json::from_slice(&fs::read(root.join("pq-dispatches.json"))?)?;
    let running: Running = serde_json::from_slice(&fs::read(root.join("pq-running.json"))?)?;
    let initial: Vec<Value> =
        serde_json::from_slice(&fs::read(root.join("pq-initial-receipts.json"))?)?;
    let cancel_payload = fs::read(root.join("cancel-request.json"))?;
    assert_ne!(records.parent_pid, std::process::id());
    assert_eq!(initial.len(), 2);
    assert_eq!(
        records.host_config_sha256,
        file_sha(&root.join("pq-host-config.json"))?
    );
    assert_eq!(
        records.supervisor_config_sha256,
        Sha256Digest::for_bytes(config_bytes)
    );
    assert_eq!(
        records.start.intent.payload_digest,
        Sha256Digest::for_bytes(payload)
    );
    assert_eq!(
        records.cancel.intent.payload_digest,
        Sha256Digest::for_bytes(&cancel_payload)
    );
    assert_ne!(
        records.start.signed.grant.nonce,
        records.cancel.signed.grant.nonce
    );
    assert_ne!(
        records.start.signed.grant.grant_id,
        records.cancel.signed.grant.grant_id
    );
    let original = HcsnJobIdentityV1::for_taskflow(
        SCOPE,
        &records.start.intent.run_id,
        &records.start.intent.step_id,
        records.start.intent.payload_digest.clone(),
    )?;
    let cancelled = HcsnJobIdentityV1::for_taskflow(
        SCOPE,
        &records.cancel.intent.run_id,
        &records.cancel.intent.step_id,
        records.cancel.intent.payload_digest.clone(),
    )?;
    assert_eq!(
        serde_json::from_slice::<HcsnJobIdentityV1>(&cancel_payload)?,
        original
    );
    assert_eq!(
        (&running.observation.dispatch, &running.observation.target),
        (&original, &original)
    );
    let identity = setup::identity(&root.join("agent-owner"), /*initialize*/ false)?;
    let host = AgentdAutomationEffectHost::open(&identity, &root.join("pq-host-config.json"))?;
    assert_eq!(
        host.authority.authentication_profile(),
        FinalUseAuthenticationProfile::MlDsa65V2
    );
    assert_eq!(host.authority.capacity()?.used_nonces, 2);
    let store = AutomationStore::open(&identity.layout).await?;
    let mut receipts = Vec::new();
    for (index, (effect, expected, run_state)) in [
        (
            &records.start,
            TaskFlowReconcileOutcome::Failed,
            TaskFlowRunState::Failed,
        ),
        (
            &records.cancel,
            TaskFlowReconcileOutcome::Succeeded,
            TaskFlowRunState::Succeeded,
        ),
    ]
    .into_iter()
    .enumerate()
    {
        assert!(matches!(
            host.authority
                .claim(&effect.signed, &effect.intent.final_use_binding()?),
            Err(FinalUseError::AlreadyClaimed)
        ));
        let deadline = Instant::now() + Duration::from_secs(60);
        let receipt = loop {
            match host
                .reconcile(
                    &store,
                    &effect.intent.run_id,
                    &effect.intent.step_id,
                    effect.intent.attempt,
                    NOW,
                )
                .await?
            {
                AgentdAutomationEffectReconcileOutcome::Observed(receipt) => break receipt,
                AgentdAutomationEffectReconcileOutcome::Indeterminate => {
                    anyhow::ensure!(
                        Instant::now() < deadline,
                        "original PQ host effect remains unknown; preserve attempt"
                    );
                    tokio::time::sleep(Duration::from_millis(25)).await;
                }
                AgentdAutomationEffectReconcileOutcome::ProvenAbsent => {
                    anyhow::bail!("status cannot prove provider absence")
                }
            }
        };
        let expected_observation = match expected {
            TaskFlowReconcileOutcome::Failed => TaskFlowStepObservation::Failed,
            TaskFlowReconcileOutcome::Succeeded => TaskFlowStepObservation::Succeeded,
            _ => anyhow::bail!("closed expected terminal set"),
        };
        assert!(
            receipt.final_outcome == Some(expected)
                || (receipt.final_outcome.is_none()
                    && receipt.observation == Some(expected_observation))
        );
        assert_eq!(
            serde_json::to_value(&receipt)?["observation"],
            initial[index]["observation"],
            "preserve the actual initial response, including any uncertainty"
        );
        assert_eq!(
            store
                .taskflow_run(&effect.intent.run_id)
                .await?
                .expect("original run")
                .state,
            run_state
        );
        receipts.push(receipt);
    }
    let job = input
        .durable_root
        .join("jobs")
        .join(Sha256Digest::for_bytes(original.key.as_str().as_bytes()).as_str());
    let raw = fs::read(job.join("terminal.json"))?;
    let terminal: Value = serde_json::from_slice(&raw)?;
    let process = running
        .observation
        .process
        .as_ref()
        .expect("observed live worker");
    assert_eq!(terminal["identity"], serde_json::to_value(&original)?);
    assert_eq!(terminal["process"], serde_json::to_value(process)?);
    assert_eq!(terminal["state"], "cancelled");
    assert_eq!(terminal["reason"], "cancelled_worker_stopped");
    assert_eq!(terminal["termination_confirmed"], true);
    assert_eq!(fs::read_to_string(BOOT)?, running.boot_id);
    assert!(live_incarnation(
        &running.proc_stat,
        &running.boot_id,
        process
    )?);
    let proc_after = match fs::read_to_string(format!("/proc/{}/stat", process.process_id)) {
        Ok(stat) => {
            anyhow::ensure!(
                !live_incarnation(&stat, &running.boot_id, process)?,
                "original worker remains live"
            );
            Some(stat)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => return Err(error.into()),
    };
    assert_eq!(file_sha(&job.join("runner.json"))?, running.runner_sha256);
    assert_eq!(file_sha(&job.join("worker.json"))?, running.worker_sha256);
    for name in ["candidate.pt", "receipt.json", "handoff.bin", "failed.json"] {
        assert!(
            !job.join(original.output_id.as_str())
                .join(name)
                .try_exists()?
        );
    }
    let mut supervisor = HcsnProcessSupervisor::new(input.config())?;
    let commands = [
        HcsnSupervisorCommandV1::start(original.clone(), String::from_utf8(payload.to_vec())?)?,
        HcsnSupervisorCommandV1::cancel(cancelled, original.clone())?,
    ];
    let mut observations = Vec::new();
    for (command, receipt) in commands.iter().zip(&receipts) {
        let expected = HcsnJobObservationV1 {
            schema_version: 1,
            dispatch: command.dispatch.clone(),
            target: original.clone(),
            state: HcsnJobStateV1::Cancelled,
            process: Some(process.clone()),
            evidence: Some(HcsnJobEvidenceV1 {
                receipt_sha256: Sha256Digest::for_bytes(&raw),
                candidate_sha256: None,
                handoff_sha256: None,
            }),
        };
        assert_eq!(supervisor.exchange(&command.status())?, expected);
        let bytes = serde_json::to_vec(&expected)?;
        assert_eq!(
            receipt.receipt_digest,
            Some(Sha256Digest::for_bytes(
                &[b"hepta.hcsn.observation.v1\0".as_slice(), &bytes].concat()
            ))
        );
        observations.push(expected);
    }
    for namespace in ["jobs", "cancellations"] {
        assert_eq!(fs::read_dir(input.durable_root.join(namespace))?.count(), 1);
    }
    assert_eq!(
        fs::read_dir(input.durable_root.join("taskflow-requests"))?.count(),
        2
    );
    assert!(
        store
            .pending_authorized_taskflow_effects(8)
            .await?
            .is_empty()
    );
    assert_eq!(host.authority.capacity()?.used_nonces, 2);
    store.close().await;
    let reopened = AutomationStore::open(&identity.layout).await?;
    fs::rename(
        root.join("pq-feed.json"),
        root.join("pq-feed-before-terminal-readback.json"),
    )?;
    support::write_private(
        &root.join("pq-services/clock.json"),
        &serde_json::to_vec(&(NOW + 120_000))?,
    )?;
    for ((effect, wire), expected) in [
        (&records.start, payload),
        (&records.cancel, cancel_payload.as_slice()),
    ]
    .into_iter()
    .zip(&receipts)
    {
        assert_eq!(
            reopened
                .read_authorized_taskflow_effect_receipt(&effect.intent, &effect.command())
                .await?,
            Some(expected.as_ref().clone())
        );
        assert_eq!(
            host.execute(
                &reopened,
                &effect.intent,
                wire,
                &effect.signed,
                &effect.command(),
                NOW + 120_000
            )
            .await?,
            **expected
        );
    }
    reopened.close().await;
    setup::write_new(
        &root.join("pq-host.json"),
        &serde_json::json!({
            "schema_version": 1, "status": "passed", "authority_profile": "production_ml_dsa65_v2",
            "initial_step_receipts": initial, "taskflow_step_receipts": receipts, "observations": observations,
            "running": running, "proc_stat_after": proc_after, "parent_pid": records.parent_pid,
            "cold_native_pid": std::process::id(), "host_config_sha256": records.host_config_sha256,
            "request_file_sha256": records.start.intent.payload_digest,
            "cancel_request_sha256": records.cancel.intent.payload_digest,
            "supervisor_config_sha256": records.supervisor_config_sha256,
            "consumed_nonces": 2, "retained_job_count": 1, "retained_cancellation_count": 1,
            "invalid_signature_rejected_before_contact": true, "start_grant_cannot_cancel": true,
            "changed_payload_rejected_before_contact": true, "independent_worker_exit_verified": true,
            "historical_observations_preserved": true, "lost_replies_injected": false,
            "cold_owner_recovery": true, "terminal_step_readback_exact": true,
            "expired_and_missing_feed_terminal_readback_exact": true, "optimizer_entry_proven": false,
            "host_registration_exercised": true, "agentd_daemon_booted": false, "authbus_ingress_exercised": false,
            "local_fixture_trust": true, "independent_custody_proven": false,
            "production_trust": false, "production_deployment": false, "production_adoption": false,
            "scope": "actual schema 3 host with ML-DSA local test trust, actual CPU worker Start/Cancel and fresh native owner recovery",
        }),
    )
}
