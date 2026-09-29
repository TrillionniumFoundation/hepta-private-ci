#![cfg(unix)]
//! The original stateful/effect test belongs with an existing durable product host.
//! Workload and assertions are retained; the pure control crate no longer builds SQLite.
use codex_hepta_agent_components::contracts as codex_hepta_contracts;
use codex_hepta_agent_components::control_plane::*;
use codex_hepta_agent_components::types::AuthorityPosture;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;
use std::collections::BTreeSet;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;

#[path = "../../hepta-control-plane/src/organ_runtime_test_support.rs"]
mod support;
use support::*;

#[cfg(unix)]
#[derive(Debug)]
struct StatefulAcceptanceOwner {
    schema: u64,
    value: u64,
    retired: bool,
    fail_candidate: Option<Generation>,
    retire_candidate: Option<Generation>,
}

#[cfg(unix)]
impl StatefulAcceptanceOwner {
    fn new() -> Self {
        Self {
            schema: 1,
            value: 0,
            retired: false,
            fail_candidate: None,
            retire_candidate: None,
        }
    }

    fn record(&mut self, delta: u64) {
        assert!(!self.retired);
        self.value = self
            .value
            .checked_add(delta)
            .expect("bounded fixture history");
    }

    fn decode(snapshot: &[u8]) -> Result<(u64, u64, bool), OrganMigrationError> {
        if snapshot.len() != 17 {
            return Err(OrganMigrationError::Rejected);
        }
        let mut schema = [0_u8; 8];
        schema.copy_from_slice(&snapshot[..8]);
        let mut value = [0_u8; 8];
        value.copy_from_slice(&snapshot[8..16]);
        let retired = match snapshot[16] {
            0 => false,
            1 => true,
            _ => return Err(OrganMigrationError::Rejected),
        };
        Ok((
            u64::from_be_bytes(schema),
            u64::from_be_bytes(value),
            retired,
        ))
    }
}

#[cfg(unix)]
impl OrganStateMigrationV1 for StatefulAcceptanceOwner {
    fn snapshot(&mut self, _predecessor: Generation) -> Result<Vec<u8>, OrganMigrationError> {
        let mut bytes = Vec::with_capacity(17);
        bytes.extend_from_slice(&self.schema.to_be_bytes());
        bytes.extend_from_slice(&self.value.to_be_bytes());
        bytes.push(u8::from(self.retired));
        Ok(bytes)
    }

    fn migrate(
        &mut self,
        snapshot: &[u8],
        _predecessor: Generation,
        candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        let (schema, value, retired) = Self::decode(snapshot)?;
        self.schema = schema.checked_add(1).ok_or(OrganMigrationError::Rejected)?;
        self.value = value;
        self.retired = retired;
        if self.fail_candidate == Some(candidate) {
            self.value = self.value.saturating_add(1_000_000);
            return Err(OrganMigrationError::Callback(id(
                "stateful.migration.failed",
            )));
        }
        if self.retire_candidate == Some(candidate) {
            self.retired = true;
        }
        Ok(())
    }

    fn rollback(
        &mut self,
        snapshot: &[u8],
        _predecessor: Generation,
        _candidate: Generation,
    ) -> Result<(), OrganMigrationError> {
        let (schema, value, retired) = Self::decode(snapshot)?;
        self.schema = schema;
        self.value = value;
        self.retired = retired;
        Ok(())
    }
}

#[cfg(unix)]
fn acceptance_authority(
    operation: &codex_hepta_operations::DurableOperationIntentV1,
    nonce: u8,
) -> (
    codex_hepta_contracts::FinalUseAuthority,
    codex_hepta_contracts::SignedFinalUseGrant,
    tempfile::TempDir,
) {
    use codex_hepta_contracts::FinalUseGrant;
    use codex_hepta_contracts::FinalUseRevocations;
    use codex_hepta_contracts::SignedFinalUseGrant;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;
    use std::os::unix::fs::PermissionsExt;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    let signing = SigningKey::from_bytes(&[61; 32]);
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "architecture-acceptance-owner".to_owned(),
        authority_epoch: 11,
        grant_id: format!("architecture-acceptance-{nonce}"),
        nonce: [nonce; 32],
        binding: operation.final_use_binding(),
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now + 30_000,
    };
    let signature = signing
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    let directory = tempfile::tempdir().expect("authority tempdir");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("authority directory permissions");
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        directory.path(),
        "architecture-acceptance-owner".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 11,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    (
        authority,
        SignedFinalUseGrant { grant, signature },
        directory,
    )
}

#[cfg(unix)]
#[tokio::test]
async fn stateful_feature_history_replace_failure_retire_preserves_effect_idempotency() {
    use codex_hepta_operations::DispatchEffect;
    use codex_hepta_operations::DurableOperationError;
    use codex_hepta_operations::DurableOperationIntentV1 as OperationIntentV1;
    use codex_hepta_operations::DurableOperationState;
    use codex_hepta_operations::DurableOperationStore;
    use codex_hepta_operations::PrepareDisposition;
    use codex_hepta_operations::ReconciliationOutcome;
    use codex_hepta_operations::ReconciliationReceiptV1;
    use std::time::Duration;

    let events = Arc::new(Mutex::new(Vec::new()));
    let mut host = new_host(graph(), handlers(&events));
    start_host(&mut host);
    let baseline = host
        .dispatch_once(generation(7), &id("source"), 0, b"baseline")
        .expect("baseline dispatch");
    let baseline_unrelated = baseline
        .iter()
        .find(|delivery| delivery.target == id("target.b"))
        .expect("unrelated target")
        .output
        .clone();

    let mut state = StatefulAcceptanceOwner::new();
    for _ in 0..256 {
        state.record(1);
    }
    assert_eq!(state.value, 256);

    let mut generation_8 = graph();
    generation_8.generation = generation(8);
    host.replace_read_only_generation_with_migration(
        generation(7),
        generation_8,
        handlers(&events),
        &mut state,
    )
    .expect("stateful v2 cutover");
    assert_eq!(state.schema, 2);
    assert_eq!(state.value, 256);
    assert!(!state.retired);

    let mut failed_generation_9 = graph();
    failed_generation_9.generation = generation(9);
    state.fail_candidate = Some(generation(9));
    assert!(matches!(
        host.replace_read_only_generation_with_migration(
            generation(8),
            failed_generation_9,
            handlers(&events),
            &mut state,
        ),
        Err(OrganRuntimeError::CandidateMigrationFailed {
            rollback_error: None,
            ..
        })
    ));
    assert_eq!(host.generation(), generation(8));
    assert_eq!(state.schema, 2);
    assert_eq!(state.value, 256);
    assert!(
        host.dispatch_once(generation(8), &id("source"), 0, b"after-failed-upgrade")
            .is_ok()
    );

    state.fail_candidate = None;
    let mut generation_9 = graph();
    generation_9.generation = generation(9);
    host.replace_read_only_generation_with_migration(
        generation(8),
        generation_9,
        handlers(&events),
        &mut state,
    )
    .expect("stateful v3 cutover");
    assert_eq!(state.schema, 3);
    assert_eq!(state.value, 256);

    let directory = tempfile::tempdir().expect("operation tempdir");
    let path = directory.path().join("architecture-lifecycle.sqlite3");
    let effect_path = directory.path().join("effect.log");
    let operation = OperationIntentV1 {
        scope_id: id("scope:architecture.acceptance"),
        operation_id: id("operation:stateful-feature:publish"),
        expected_predecessor: None,
        destination: id("stateful.feature.effect"),
        payload_digest: Digest32::of_bytes(b"state-value-256"),
        owner_generation: generation(9),
    };
    let store = DurableOperationStore::open(&path)
        .await
        .expect("operation store");
    let prepared = store
        .prepare_intent(&operation)
        .await
        .expect("prepare effect");
    assert_eq!(prepared.disposition, PrepareDisposition::Inserted);
    assert_eq!(
        store
            .prepare_intent(&operation)
            .await
            .expect("idempotent prepare")
            .disposition,
        PrepareDisposition::AlreadyPresent
    );
    let claim = store
        .claim_next(
            &operation.destination,
            &id("worker:architecture.acceptance"),
            generation(9),
            Duration::from_secs(30),
        )
        .await
        .expect("claim effect")
        .expect("effect row");

    let mut forged = operation.clone();
    forged.payload_digest = Digest32::of_bytes(b"forged-payload");
    let (wrong_authority, wrong_grant, _wrong_dir) = acceptance_authority(&forged, 31);
    assert!(
        store
            .authorize_dispatch(&wrong_authority, &wrong_grant, &claim)
            .await
            .is_err(),
        "a grant bound to different payload bytes must not cross the effect boundary"
    );
    assert_eq!(
        store
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("operation after denied grant")
            .expect("operation row")
            .state,
        DurableOperationState::Prepared
    );

    let (authority, grant, _authority_dir) = acceptance_authority(&operation, 32);
    let authorized = store
        .authorize_dispatch(&authority, &grant, &claim)
        .await
        .expect("authorized effect");
    let effect_target = effect_path.clone();
    store
        .execute_authorized(authorized, move |_| {
            std::fs::write(&effect_target, b"applied-once\n").expect("effect write");
            DispatchEffect::Indeterminate {
                value: (),
                reason_digest: Digest32::of_bytes(b"ack-lost-after-effect"),
            }
        })
        .await
        .expect("unknown effect classification");
    assert_eq!(
        std::fs::read(&effect_path).expect("effect bytes"),
        b"applied-once\n"
    );
    assert_eq!(
        store
            .operation(&operation.scope_id, &operation.operation_id)
            .await
            .expect("unknown lookup")
            .expect("unknown row")
            .state,
        DurableOperationState::Indeterminate
    );
    store.close().await;

    let reopened = DurableOperationStore::open(&path)
        .await
        .expect("reopen after unknown effect");
    assert!(
        reopened
            .claim_next(
                &operation.destination,
                &id("worker:must-not-redeliver"),
                generation(10),
                Duration::from_secs(1),
            )
            .await
            .expect("post-crash claim query")
            .is_none(),
        "unknown effects must never be blindly redispatched"
    );
    assert_eq!(
        std::fs::read(&effect_path).expect("effect after reopen"),
        b"applied-once\n"
    );

    let terminal = ReconciliationReceiptV1 {
        outcome: ReconciliationOutcome::Applied,
        evidence_digest: Digest32::of_bytes(b"destination-observed-applied"),
        observer_id: id("observer:architecture.acceptance"),
        observer_generation: generation(9),
    };
    let settled = reopened
        .observe_terminal(&operation.scope_id, &operation.operation_id, &terminal)
        .await
        .expect("terminal reconciliation");
    assert_eq!(settled.state, DurableOperationState::Applied);
    assert_eq!(
        reopened
            .observe_terminal(&operation.scope_id, &operation.operation_id, &terminal)
            .await
            .expect("idempotent terminal reconciliation"),
        settled
    );
    let metrics = reopened.backlog_metrics().await.expect("backlog metrics");
    assert_eq!(metrics.active_operations, 0);
    assert_eq!(metrics.terminal_operations, 1);
    assert_eq!(
        reopened.prune_terminal(u64::MAX, 1).await.expect("prune"),
        1
    );
    assert!(matches!(
        reopened.prepare_intent(&operation).await,
        Err(DurableOperationError::Retired(_))
    ));
    reopened.close().await;

    let mut retired = graph();
    retired.generation = generation(10);
    retired.organs.remove(1);
    retired.initialization = vec![OrganEdge { from: 0, to: 1 }];
    retired.runtime = vec![RuntimeLinkV1 {
        output: OutputPort { organ: 0, port: 0 },
        input: InputPort { organ: 1, port: 0 },
        timing: DataflowTiming::Buffered,
    }];
    retired.fallback = vec![OrganEdge { from: 0, to: 1 }];
    retired.failure_domains.remove(1);
    retired.failure_domains[1].organ = 1;
    let retired_handlers: Vec<Box<dyn TrustedReadOnlyOrganV1>> = ["source", "target.b"]
        .into_iter()
        .map(|name| {
            Box::new(FixtureOrgan::new(name, Arc::clone(&events)))
                as Box<dyn TrustedReadOnlyOrganV1>
        })
        .collect();
    state.retire_candidate = Some(generation(10));
    host.replace_read_only_generation_with_migration(
        generation(9),
        retired,
        retired_handlers,
        &mut state,
    )
    .expect("retire stateful feature");
    assert_eq!(state.schema, 4);
    assert_eq!(state.value, 256);
    assert!(state.retired);

    assert_eq!(
        host.dispatch_once(generation(9), &id("source"), 0, b"stale-generation"),
        Err(OrganRuntimeError::GenerationMismatch {
            expected: generation(10),
            actual: generation(9),
        })
    );
    assert_eq!(
        host.dispatch_once(generation(10), &id("target.a"), 0, b"retired"),
        Err(OrganRuntimeError::UnknownSource {
            organ: id("target.a"),
        })
    );
    let current = host
        .dispatch_once(generation(10), &id("source"), 0, b"after-retirement")
        .expect("unrelated module remains live");
    assert_eq!(current.len(), 1);
    assert_eq!(current[0].target, id("target.b"));
    assert_eq!(current[0].output, baseline_unrelated);
    assert_eq!(current[0].authority, AuthorityPosture::DENY_ALL);
}
