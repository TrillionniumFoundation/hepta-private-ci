//! Cold recovery verifies both logical effects and the original process exit.

use super::*;
use pretty_assertions::assert_eq;

pub(super) async fn recover(
    root: &Path,
    config: &HcsnProcessSupervisorConfig,
    config_bytes: &[u8],
    payload: &[u8],
) {
    let state = root.join("signed-cancel-state");
    let records: Dispatches =
        serde_json::from_slice(&fs::read(state.join("dispatches.json")).expect("dispatches"))
            .expect("JSON");
    let running: Running =
        serde_json::from_slice(&fs::read(state.join("running.json")).expect("running process"))
            .expect("JSON");
    let cancel_payload = fs::read(root.join("cancel-request.json")).expect("retained cancel bytes");
    let original = HcsnJobIdentityV1::for_taskflow(
        SCOPE,
        &records.start.intent.run_id,
        &records.start.intent.step_id,
        records.start.intent.payload_digest.clone(),
    )
    .expect("original signed dispatch identity");
    assert_eq!(
        (&running.observation.dispatch, &running.observation.target),
        (&original, &original)
    );
    assert_eq!(
        serde_json::from_slice::<HcsnJobIdentityV1>(&cancel_payload).expect("target"),
        running.observation.target
    );
    let fixture = Fixture::reopen(&state);
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("cold SQLite");
    assert_eq!(
        fixture
            .authority
            .capacity()
            .expect("cold nonce journal")
            .used_nonces,
        2
    );
    let pending = store
        .pending_authorized_taskflow_effects(8)
        .await
        .expect("pending effects");
    assert_eq!(pending.len(), 2);
    let mut receipts = Vec::new();
    for (record, wire, action, outcome, reconciled, run_state) in [
        (
            &records.start,
            payload,
            HcsnTaskFlowActionV1::Start,
            AuthorizedEffectOutcome::Failed,
            TaskFlowReconcileOutcome::Failed,
            TaskFlowRunState::Failed,
        ),
        (
            &records.cancel,
            cancel_payload.as_slice(),
            HcsnTaskFlowActionV1::Cancel,
            AuthorizedEffectOutcome::Succeeded,
            TaskFlowReconcileOutcome::Succeeded,
            TaskFlowRunState::Succeeded,
        ),
    ] {
        assert_ne!(record.parent_pid, std::process::id());
        assert_eq!(record.payload_sha256, Sha256Digest::for_bytes(wire));
        assert_eq!(record.config_sha256, Sha256Digest::for_bytes(config_bytes));
        assert!(matches!(
            fixture.authority.claim(
                &record.signed,
                &record.intent.final_use_binding().expect("binding")
            ),
            Err(FinalUseError::AlreadyClaimed)
        ));
        let retained = pending
            .iter()
            .find(|item| item.intent_digest == record.intent.digest().expect("intent digest"))
            .expect("same pending effect");
        let mut recovered_driver = driver(config, action);
        assert!(
            execute(
                &store,
                &fixture,
                &mut recovered_driver,
                record,
                wire,
                &record.signed
            )
            .await
            .is_err()
        );
        assert_eq!(
            recovered_driver.contacts, 0,
            "cold recovery must never redispatch a start or cancellation"
        );
        assert_eq!(
            recovered_driver
                .real
                .lookup(retained, b"substituted target"),
            AuthorizedProviderEffectLookup::Unresolved
        );
        let deadline = Instant::now() + Duration::from_secs(60);
        let terminal = loop {
            match recovered_driver.real.lookup(retained, wire) {
                AuthorizedProviderEffectLookup::Observed(receipt) => break receipt,
                AuthorizedProviderEffectLookup::Unresolved => {
                    assert!(
                        Instant::now() < deadline,
                        "cancel remains unknown; never retry"
                    );
                    tokio::time::sleep(Duration::from_millis(25)).await;
                }
                AuthorizedProviderEffectLookup::ProvenAbsent { .. } => {
                    panic!("no absence inference")
                }
            }
        };
        assert_eq!(terminal.outcome, outcome);
        let recovered = store
            .recover_authorized_taskflow_effect(
                &record.intent.run_id,
                &record.intent.step_id,
                record.intent.attempt,
                &fixture.owner,
                AuthorizedEffectRecovery::Observed(terminal.clone()),
                now_ms(),
            )
            .await
            .expect("reconcile same attempt");
        let AuthorizedEffectRecoveryResult::Observed(receipt) = recovered else {
            panic!("observed recovery required");
        };
        assert_eq!(
            (
                receipt.state,
                receipt.observation,
                receipt.final_outcome,
                receipt.receipt_digest.as_ref()
            ),
            (
                TaskFlowStepState::Reconciled,
                Some(TaskFlowStepObservation::Indeterminate),
                Some(reconciled),
                Some(&terminal.receipt_digest)
            )
        );
        assert_eq!(
            store
                .taskflow_run(&record.intent.run_id)
                .await
                .expect("run query")
                .expect("run")
                .state,
            run_state
        );
        assert_eq!(
            recovered_driver.real.lookup(retained, wire),
            AuthorizedProviderEffectLookup::Observed(terminal)
        );
        receipts.push(receipt);
    }
    let target = &running.observation.target;
    let job = config
        .durable_root
        .join("jobs")
        .join(Sha256Digest::for_bytes(target.key.as_str().as_bytes()).as_str());
    let raw = fs::read(job.join("terminal.json")).expect("terminal bytes");
    let terminal: serde_json::Value = serde_json::from_slice(&raw).expect("terminal JSON");
    let process = running
        .observation
        .process
        .as_ref()
        .expect("observed running process");
    assert_eq!(
        terminal["identity"],
        serde_json::to_value(target).expect("target JSON")
    );
    assert_eq!(
        terminal["process"],
        serde_json::to_value(process).expect("process JSON")
    );
    assert_eq!(
        (
            &terminal["state"],
            &terminal["reason"],
            &terminal["termination_confirmed"]
        ),
        (
            &serde_json::json!("cancelled"),
            &serde_json::json!("cancelled_worker_stopped"),
            &serde_json::json!(true)
        )
    );
    assert_eq!(
        fs::read_to_string(BOOT).expect("same boot"),
        running.boot_id
    );
    assert!(live_incarnation(
        &running.proc_stat,
        &running.boot_id,
        process
    ));
    let proc_after = match fs::read_to_string(format!("/proc/{}/stat", process.process_id)) {
        Ok(stat) => {
            assert!(
                !live_incarnation(&stat, &running.boot_id, process),
                "original worker is still live"
            );
            Some(stat)
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => panic!("cannot independently confirm original worker exit: {error}"),
    };
    for name in ["candidate.pt", "receipt.json", "handoff.bin", "failed.json"] {
        assert!(
            !job.join(target.output_id.as_str())
                .join(name)
                .try_exists()
                .expect("output inspection")
        );
    }
    for (name, digest) in [
        ("runner.json", &running.runner_sha256),
        ("worker.json", &running.worker_sha256),
    ] {
        assert_eq!(
            Sha256Digest::for_bytes(&fs::read(job.join(name)).expect("same process record")),
            *digest
        );
    }
    let start = HcsnSupervisorCommandV1::start(
        target.clone(),
        String::from_utf8(payload.to_vec()).expect("UTF-8"),
    )
    .expect("status identity");
    let mut supervisor = HcsnProcessSupervisor::new(config.clone()).expect("cold supervisor");
    let observation = supervisor
        .exchange(&start.status())
        .expect("terminal status");
    assert_eq!(
        observation,
        HcsnJobObservationV1 {
            state: HcsnJobStateV1::Cancelled,
            evidence: Some(HcsnJobEvidenceV1 {
                receipt_sha256: Sha256Digest::for_bytes(&raw),
                candidate_sha256: None,
                handoff_sha256: None
            }),
            ..running.observation.clone()
        }
    );
    assert_eq!(
        supervisor.exchange(&start.status()).expect("repeat status"),
        observation
    );
    for name in ["jobs", "cancellations"] {
        assert_eq!(
            fs::read_dir(config.durable_root.join(name))
                .expect("one retained effect")
                .count(),
            1
        );
    }
    assert!(
        store
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("settled effects")
            .is_empty()
    );
    assert_eq!(
        fixture
            .authority
            .capacity()
            .expect("no additional nonce consumed")
            .used_nonces,
        2
    );
    store.close().await;
    let settled = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopened terminal projection");
    for (record, receipt) in [&records.start, &records.cancel].into_iter().zip(&receipts) {
        assert_eq!(
            settled
                .read_authorized_taskflow_effect_receipt(&record.intent, &dispatch_command(record))
                .await
                .expect("exact terminal readback"),
            Some(receipt.clone())
        );
    }
    settled.close().await;
    write_new(
        &root.join("signed-cancel.json"),
        &serde_json::json!({
            "schema_version": 1, "status": "passed", "observation": observation, "taskflow_step_receipts": receipts,
            "request_file_sha256": records.start.payload_sha256, "cancel_request_sha256": records.cancel.payload_sha256,
            "supervisor_config_sha256": records.start.config_sha256, "parent_pid": records.start.parent_pid,
            "cold_native_pid": std::process::id(), "running": running, "proc_stat_after": proc_after,
            "invalid_signature_rejected_before_contact": true, "changed_payload_rejected_before_contact": true,
            "start_grant_cannot_cancel": true, "independent_worker_exit_verified": true,
            "historical_observations_preserved": true, "terminal_step_readback_exact": true,
            "lost_start_and_cancel_replies_injected": true, "consumed_nonces": 2, "replay_contacts": 0,
            "retained_job_count": 1, "retained_cancellation_count": 1,
            "host_registration_exercised": false, "authority_profile": "synthetic_ed25519_v1",
            "production_trust": false, "production_adoption": false, "optimizer_entry_proven": false,
            "scope": "signed Start and distinct Cancel; observed real CPU worker; confirmed termination and fresh native recovery; synthetic test trust",
        }),
    );
}
