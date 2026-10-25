use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_authbus::SignedMessageClaims;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::assert_eq;

use super::*;
use crate::RunPhase;

#[derive(Clone, Copy)]
pub(crate) enum ClockCase {
    Current,
    ElapsedDeadline,
    ExpiredSignature,
}

pub(crate) struct CurrentFixture {
    pub(crate) state: Arc<AgentdState>,
    pub(crate) registry: FleetRegistry,
    pub(crate) record: RunStartRecordV1,
    trust_file: PathBuf,
    pub(crate) key: SigningKey,
    _owner: tempfile::TempDir,
    _journal: tempfile::TempDir,
}

impl CurrentFixture {
    pub(crate) fn trust(&self, epoch: u64, revoked: bool) {
        let value = serde_json::json!({
            "schema_version": 1, "agent_id": self.state.identity.agent_id.as_str(),
            "issuer_id": self.record.authentication.issuer_id.as_str(), "key_epoch": epoch,
            "public_key_hex": self.key.verifying_key().as_bytes().iter()
                .map(|byte| format!("{byte:02x}")).collect::<String>(),
            "revoked": revoked, "thread_ids": []
        });
        std::fs::write(&self.trust_file, serde_json::to_vec(&value).unwrap()).unwrap();
        std::fs::set_permissions(&self.trust_file, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
}

pub(crate) async fn fixture(clock: ClockCase) -> CurrentFixture {
    let (owner, registry, previous) = super::isolation_tests::fixture().unwrap();
    let identity = previous.identity.clone();
    drop(previous);
    let state = AgentdState::new(identity, registry.clone(), /*event_capacity*/ 16).unwrap();
    state.refresh_generation().unwrap();
    let cognitive = CognitiveStore::open(&state.identity.layout).await.unwrap();
    state.attach_cognitive_store(Arc::new(cognitive)).unwrap();
    state.mark_runtime_prerequisites_ready().unwrap();
    state.mark_app_server_ready().unwrap();
    fixture_with_state(clock, owner, registry, Arc::new(state)).await
}

pub(crate) async fn fixture_with_state(
    clock: ClockCase,
    owner: tempfile::TempDir,
    registry: FleetRegistry,
    state: Arc<AgentdState>,
) -> CurrentFixture {
    let result = unadmitted_fixture_with_state(clock, owner, registry, state).await;
    // Expiry cases model an already-admitted run before its deadline passed;
    // the current reader uses the real clock, without a deadline sweep.
    let deadline = result.record.admission.deadline_unix_micros / 1000;
    result
        .state
        .runs
        .lock()
        .unwrap()
        .start_revalidated_run_start(deadline - 1, &result.record)
        .unwrap();
    result
}

pub(crate) async fn unadmitted_fixture_with_state(
    clock: ClockCase,
    owner: tempfile::TempDir,
    registry: FleetRegistry,
    state: Arc<AgentdState>,
) -> CurrentFixture {
    std::fs::set_permissions(owner.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    std::fs::set_permissions(
        &state.identity.home_root,
        std::fs::Permissions::from_mode(0o700),
    )
    .unwrap();
    let now = crate::authbus_ingress::now_ms().unwrap();
    let key = SigningKey::from_bytes(&[89; 32]);
    let mut record = crate::objective_runtime::tests::record(
        "run.current",
        /*sequence*/ 17,
        RunStartObjectiveDispositionV1::Compiled,
    );
    record.snapshot.generation = 2;
    record.snapshot.fence_digest =
        objective_run_fence(state.identity(), /*current_generation*/ 2)
            .parse()
            .unwrap();
    let deadline = if matches!(clock, ClockCase::ElapsedDeadline) {
        now - 1_000
    } else {
        now + 60_000
    };
    record.admission.deadline_unix_micros = deadline * 1_000;
    let claims = SignedMessageClaims {
        issuer_id: record.authentication.issuer_id.clone(),
        key_epoch: Generation::new(1).unwrap(),
        message_id: record.authentication.message_id.clone(),
        subject_id: StableId::new(state.identity.agent_id.as_str()).unwrap(),
        scope_digest: objective_run_scope(state.identity()),
        payload_digest: record.authentication.signed_body_digest,
        sequence: 17,
        expires_at_ms: if matches!(clock, ClockCase::ExpiredSignature) {
            now - 1_000
        } else {
            now + 120_000
        },
    };
    record.authentication.scope_digest = claims.scope_digest;
    record.authentication.expires_at_ms = claims.expires_at_ms;
    record.authentication.signature = key.sign(&claims.signing_bytes()).to_bytes();
    let (journal, host, record) = crate::objective_runtime::tests::current_host_with(record);
    state.objective_runtime.set(host).map_err(|_| ()).unwrap();
    let trust_file = state
        .identity
        .home_root
        .join("current-objective-trust.json");
    let result = CurrentFixture {
        state,
        registry,
        record,
        trust_file,
        key,
        _owner: owner,
        _journal: journal,
    };
    result.trust(/*epoch*/ 1, /*revoked*/ false);
    let home = codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(
        &result.state.identity.home_root,
    )
    .unwrap();
    let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
        &codex_state::SqliteConfig::from_sqlite_home(home),
    )
    .await
    .unwrap();
    let frontier = evidence.authbus_replay_frontier_digest().await.unwrap();
    drop(evidence);
    let checkpoint = result
        ._owner
        .path()
        .join("current-objective-checkpoint.json");
    std::fs::write(
        &checkpoint,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1, "agent_id": result.state.identity.agent_id.as_str(),
            "generation": 1, "digest": frontier.to_string()
        }))
        .unwrap(),
    )
    .unwrap();
    std::fs::set_permissions(&checkpoint, std::fs::Permissions::from_mode(0o600)).unwrap();
    let ingress = crate::authbus_ingress::TextIngress::open(
        result.state.identity(),
        result.trust_file.clone(),
        checkpoint,
    )
    .await
    .unwrap();
    result
        .state
        .authbus
        .set(Arc::new(ingress))
        .map_err(|_| ())
        .unwrap();
    result
}

#[tokio::test]
async fn current_read_is_owner_bound_read_only_and_explicitly_selected() {
    let f = fixture(ClockCase::Current).await;
    let before = f
        .state
        .runs
        .lock()
        .unwrap()
        .run_observation("run.current")
        .unwrap();
    let host = f.state.objective_runtime.get().unwrap();
    let journal_before = host
        .with_run_start(&f.record.snapshot.run_id, |_, head| Ok(head))
        .unwrap();
    let proof = f.state.checked_current_objective("run.current").unwrap();
    let repeated = f.state.checked_current_objective("run.current").unwrap();
    assert_eq!(proof.snapshot(), repeated.snapshot());
    assert_eq!(proof.binding_digest(), repeated.binding_digest());
    assert_eq!(
        proof.snapshot().subject_id.as_str(),
        f.state.identity.agent_id.as_str()
    );
    assert_eq!(
        proof.snapshot().objective_digest,
        f.record.snapshot.objective_digest
    );
    assert_eq!(proof.snapshot().run_revision, 1);
    assert_eq!(proof.snapshot().authority_epoch, 7);
    assert_eq!(proof.snapshot().fleet_generation, 2);
    f.state.revalidate_current_objective(&proof).unwrap();
    assert!(f.state.checked_current_objective("run.unknown").is_err());
    assert_eq!(
        f.state
            .runs
            .lock()
            .unwrap()
            .run_observation("run.current")
            .unwrap(),
        before
    );
    assert_eq!(
        host.with_run_start(&f.record.snapshot.run_id, |_, head| Ok(head))
            .unwrap(),
        journal_before
    );
    let other = fixture(ClockCase::Current).await;
    assert!(other.state.revalidate_current_objective(&proof).is_err());
}

#[tokio::test]
async fn current_read_rechecks_signature_epoch_and_fleet_without_readmission() {
    let f = fixture(ClockCase::Current).await;
    let proof = f.state.checked_current_objective("run.current").unwrap();
    f.trust(/*epoch*/ 1, /*revoked*/ true);
    assert!(f.state.revalidate_current_objective(&proof).is_err());
    f.trust(/*epoch*/ 2, /*revoked*/ false);
    assert!(f.state.checked_current_objective("run.current").is_err());
    f.trust(/*epoch*/ 1, /*revoked*/ false);
    f.registry
        .compare_and_transition(
            &f.state.identity.agent_id,
            /*expected_generation*/ 2,
            AgentLifecycle::Draining,
        )
        .unwrap();
    assert!(f.state.revalidate_current_objective(&proof).is_err());
    assert_eq!(
        f.state
            .runs
            .lock()
            .unwrap()
            .run("run.current")
            .unwrap()
            .phase,
        RunPhase::Cancelled
    );
    for clock in [ClockCase::ElapsedDeadline, ClockCase::ExpiredSignature] {
        let expired = fixture(clock).await;
        assert!(
            expired
                .state
                .checked_current_objective("run.current")
                .is_err()
        );
    }
}

#[tokio::test]
async fn released_and_readmitted_run_cannot_reuse_an_old_observation() {
    let f = fixture(ClockCase::Current).await;
    let proof = f.state.checked_current_objective("run.current").unwrap();
    let now = crate::authbus_ingress::now_ms().unwrap();
    let (_, cancelled) = f
        .state
        .runs
        .lock()
        .unwrap()
        .cancel_run(
            now,
            "run.current",
            /*expected_revision*/ 1,
            "test.cancel",
        )
        .unwrap();
    assert!(f.state.revalidate_current_objective(&proof).is_err());
    f.state
        .runs
        .lock()
        .unwrap()
        .remove_closed_run("run.current", cancelled.revision)
        .unwrap();
    assert!(f.state.checked_current_objective("run.current").is_err());
    f.state.start_current_run_start_record(&f.record).unwrap();
    let replacement = f.state.checked_current_objective("run.current").unwrap();
    assert_eq!(
        replacement.snapshot().run_revision,
        proof.snapshot().run_revision
    );
    assert!(replacement.snapshot().run_incarnation > proof.snapshot().run_incarnation);
    assert_ne!(replacement.binding_digest(), proof.binding_digest());
    assert!(f.state.revalidate_current_objective(&proof).is_err());
}
