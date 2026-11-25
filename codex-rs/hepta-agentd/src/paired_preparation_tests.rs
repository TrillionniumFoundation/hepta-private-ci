//! Synthetic authority/metadata, real temporary SQLite journal and reopen.
//! The writer lease is explicitly synthetic. No original human/paired token,
//! participant or material is constructed. These controls exercise the journal
//! below the separately qualified original-turn verifier, not enrollment.
use super::*;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityToken;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

#[path = "paired_preparation_continuation_tests.rs"]
mod continuation;

impl PreparationJournal {
    // Preserve the original eight controls' metadata-only fixture API. The
    // actual receipt is created by the real writer and explicitly discarded.
    async fn retain_payload(
        &self,
        request: &PairedPreparationRequest,
        payload: PreparationPayload,
        preparing: &AtomicBool,
    ) -> Result<PairedPreparationResponse, AgentdError> {
        Ok(self
            .retain_original_receipt(request, payload, preparing)
            .await?
            .into_observation())
    }
}

struct SyntheticVerifier(AtomicBool);
impl ProductionAuthorityVerifier for SyntheticVerifier {
    fn verify(
        &self,
        authority: &ProductionAuthorityLease,
        expected: &AgentId,
    ) -> Result<(), String> {
        if self.0.load(Ordering::SeqCst)
            || &authority.agent_id != expected
            || authority.grant_digest != Sha256Digest::for_bytes(b"synthetic paired preparation")
        {
            return Err("synthetic writer authority revoked or different".into());
        }
        Ok(())
    }
}

struct Fixture {
    directory: TempDir,
    authority: ProductionAuthorityLease,
    verifier: Arc<SyntheticVerifier>,
}

impl Fixture {
    fn new() -> Self {
        Self {
            directory: TempDir::new().unwrap(),
            authority: ProductionAuthorityLease::from_verified_parts(
                AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18").unwrap(),
                Sha256Digest::for_bytes(b"synthetic paired preparation"),
                /*authority_epoch*/ 1,
                /*owner_epoch*/ 1,
                /*lease_expires_at_unix_seconds*/ 4_000_000_000,
                ProductionAuthorityToken::from_verified_bytes(b"synthetic paired token".to_vec())
                    .unwrap(),
            )
            .unwrap(),
            verifier: Arc::new(SyntheticVerifier(AtomicBool::new(false))),
        }
    }

    async fn journal(&self) -> PreparationJournal {
        let path = self.directory.path().join("fleet");
        std::fs::create_dir_all(&path).unwrap();
        let fleet = HeptaFleetRoot::parse(path.canonicalize().unwrap()).unwrap();
        let store = CognitiveStore::open(&fleet.layout().agent(&self.authority.agent_id))
            .await
            .unwrap();
        let writer = ProductionDurableWriter::open_with_live_verifier(
            store,
            self.authority.clone(),
            self.verifier.clone(),
            "synthetic-paired-owner",
            /*generation*/ 1,
        )
        .await
        .unwrap();
        PreparationJournal {
            writer: Arc::new(writer),
            registration: PairedPreparationRegistration {
                study: Digest32::of_bytes(b"synthetic study"),
                enrollment: Digest32::of_bytes(b"synthetic enrollment metadata"),
                frozen_materials: Digest32::of_bytes(b"synthetic frozen materials metadata"),
                principal_id: "synthetic-person".into(),
                policy_generation: Generation::new(1).unwrap(),
            },
            route: AgentdTextSessionConfig {
                control_socket: "/synthetic/agentd.sock".into(),
                agent_id: self.authority.agent_id.clone(),
                spawn_generation: 1,
                thread_id: "synthetic-original-thread".into(),
                app_server_session_id: "synthetic-original-session".into(),
                codex_home: "/synthetic/home".into(),
            },
        }
    }
}

fn request(journal: &PreparationJournal) -> PairedPreparationRequest {
    PairedPreparationRequest {
        original: PairedTurnRequest {
            turn_id: "synthetic-turn".into(),
            delivery_id: Digest32::of_bytes(b"synthetic delivery"),
            study: journal.registration.study,
            usage: PairedLearningDataUse::EvaluateOnlyAfterFreeze {
                freeze: Digest32::of_bytes(b"synthetic freeze"),
                task: Digest32::of_bytes(b"synthetic task commitment"),
            },
            expected_principal: journal.registration.principal_id.clone(),
        },
        operation: Digest32::of_bytes(b"synthetic requested operation"),
        materials: journal.registration.frozen_materials,
    }
}

fn payload(journal: &PreparationJournal, request: &PairedPreparationRequest) -> PreparationPayload {
    PreparationPayload {
        schema: "hepta.paired-learning.native-preparation.v1".into(),
        identity: request.identity(&journal.registration).unwrap(),
        original_route: journal.route.clone(),
        permission_revision: 1,
        expires_at_ms: 4_000_000_000_000,
        statement_sha256: Digest32::of_bytes(
            request
                .original
                .usage
                .consent_text(request.original.study)
                .as_bytes(),
        )
        .to_string(),
    }
}

#[tokio::test]
async fn one_original_delivery_has_one_real_preparation_and_read_only_repeat() {
    let fixture = Fixture::new();
    let journal = fixture.journal().await;
    let request = request(&journal);
    let first = journal
        .retain_payload(
            &request,
            payload(&journal, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    let PairedPreparationResponse::FreshPrepared(original) = first else {
        panic!("first original admission missing");
    };
    let repeat = journal
        .retain_payload(
            &request,
            payload(&journal, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    assert_eq!(original.state, LocalOutcomeState::Queued);
    assert_eq!(
        repeat,
        PairedPreparationResponse::RetainedReadOnly(original)
    );
}

#[tokio::test]
async fn changed_semantics_cannot_spend_the_same_delivery_again() {
    let fixture = Fixture::new();
    let journal = fixture.journal().await;
    let request = request(&journal);
    journal
        .retain_payload(
            &request,
            payload(&journal, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    let original = journal.retained(&request).await.unwrap();
    let mut changed = vec![request.clone(); 5];
    changed[0].operation = Digest32::of_bytes(b"another operation");
    changed[1].original.study = Digest32::of_bytes(b"another study");
    changed[2].original.expected_principal = "another-person".into();
    changed[3].materials = Digest32::of_bytes(b"another material");
    changed[4].original.usage = PairedLearningDataUse::TrainOnFailureAndCorrection {
        failure: Digest32::of_bytes(b"synthetic failure"),
        correction: Digest32::of_bytes(b"synthetic correction"),
    };
    for different in changed {
        assert_eq!(
            operation_id(different.original.delivery_id),
            operation_id(request.original.delivery_id)
        );
        assert!(journal.retained(&different).await.is_err());
    }
    assert_eq!(journal.retained(&request).await.unwrap(), original);
}

#[tokio::test]
async fn reopened_writer_observes_original_route_without_repreparing() {
    let fixture = Fixture::new();
    let journal = fixture.journal().await;
    let request = request(&journal);
    journal
        .retain_payload(
            &request,
            payload(&journal, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    let original = journal.retained(&request).await.unwrap();
    drop(journal);
    let mut reopened = fixture.journal().await;
    reopened.route.thread_id = "new-runtime-cannot-rebind-original-route".into();
    let response = reopened
        .retain_payload(
            &request,
            payload(&reopened, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    assert_eq!(
        response,
        PairedPreparationResponse::RetainedReadOnly(original.unwrap())
    );
}

#[tokio::test]
async fn concurrent_original_cas_and_unknown_state_never_create_a_second_admission() {
    let fixture = Fixture::new();
    let journal = fixture.journal().await;
    let request = request(&journal);
    let encoded = serde_json::to_string(&payload(&journal, &request)).unwrap();
    let intent = journal.intent(&request, &encoded).unwrap();
    let (left, right) = tokio::join!(
        journal
            .writer
            .prepare_operation(intent.clone(), TOPIC, encoded.clone()),
        journal.writer.prepare_operation(intent, TOPIC, encoded),
    );
    let (mut left, mut right) = (left.unwrap(), right.unwrap());
    assert_ne!(left.replayed, right.replayed);
    left.replayed = true;
    right.replayed = true;
    assert_eq!(left, right);
    journal
        .writer
        .mark_indeterminate(
            operation_id(request.original.delivery_id),
            "synthetic unknown effect observation",
        )
        .await
        .unwrap();
    let before = journal.writer.recovery_anchor().await.unwrap();
    let original = journal.retained(&request).await.unwrap().unwrap();
    assert_eq!(original.state, LocalOutcomeState::Indeterminate);
    assert_eq!(
        journal
            .retain_payload(
                &request,
                payload(&journal, &request),
                &AtomicBool::new(false)
            )
            .await
            .unwrap(),
        PairedPreparationResponse::RetainedReadOnly(original),
    );
    assert_eq!(journal.writer.recovery_anchor().await.unwrap(), before);
}

#[tokio::test]
async fn original_writer_revocation_blocks_new_admission_and_preserves_old_row() {
    let fixture = Fixture::new();
    let journal = fixture.journal().await;
    let request = request(&journal);
    journal
        .retain_payload(
            &request,
            payload(&journal, &request),
            &AtomicBool::new(false),
        )
        .await
        .unwrap();
    let original = journal.retained(&request).await.unwrap();
    fixture.verifier.0.store(true, Ordering::SeqCst);
    let mut next = request.clone();
    next.original.delivery_id = Digest32::of_bytes(b"synthetic next delivery");
    assert!(
        journal
            .retain_payload(&next, payload(&journal, &next), &AtomicBool::new(false))
            .await
            .is_err()
    );
    assert!(journal.retained(&request).await.is_err());
    fixture.verifier.0.store(false, Ordering::SeqCst);
    assert_eq!(journal.retained(&request).await.unwrap(), original);
    assert_eq!(journal.retained(&next).await.unwrap(), None);
}

#[tokio::test]
async fn cancellation_after_real_commit_returns_unknown_and_only_original_record() {
    let fixture = Fixture::new();
    let journal = Arc::new(fixture.journal().await);
    let request = request(&journal);
    let (client, mut lane) = channel(
        journal.writer.clone(),
        journal.registration.clone(),
        journal.route.clone(),
    )
    .unwrap();
    let call = request.clone();
    let caller = tokio::spawn(async move { client.prepare(call).await });
    let pending = lane.receiver.recv().await.unwrap();
    let preparing = Arc::clone(&pending.preparing);
    let cancellation = CancellationToken::new();
    let token = cancellation.clone();
    let (committed, entered) = oneshot::channel();
    let owner_journal = journal.clone();
    let call = request.clone();
    let owner = tokio::spawn(async move {
        pending
            .complete_on_owner(&token, async {
                let retained = owner_journal
                    .retain_payload(&call, payload(&owner_journal, &call), &preparing)
                    .await?;
                let _ = committed.send(());
                std::future::pending::<()>().await;
                Ok(retained)
            })
            .await;
    });
    entered.await.unwrap();
    cancellation.cancel();
    tokio::time::timeout(Duration::from_secs(1), owner)
        .await
        .unwrap()
        .unwrap();
    assert_eq!(
        caller.await.unwrap().unwrap(),
        PairedPreparationResponse::Unknown {
            operation_id: operation_id(request.original.delivery_id)
        }
    );
    let original = journal.retained(&request).await.unwrap().unwrap();
    assert_eq!(
        journal
            .retain_payload(
                &request,
                payload(&journal, &request),
                &AtomicBool::new(false)
            )
            .await
            .unwrap(),
        PairedPreparationResponse::RetainedReadOnly(original)
    );
}

#[tokio::test]
async fn lost_caller_after_real_commit_releases_owner_and_never_rearms() {
    struct Released(Option<oneshot::Sender<()>>);
    impl Drop for Released {
        fn drop(&mut self) {
            if let Some(reply) = self.0.take() {
                let _ = reply.send(());
            }
        }
    }
    let fixture = Fixture::new();
    let journal = Arc::new(fixture.journal().await);
    let request = request(&journal);
    let (client, mut lane) = channel(
        journal.writer.clone(),
        journal.registration.clone(),
        journal.route.clone(),
    )
    .unwrap();
    let call = request.clone();
    let caller = tokio::spawn(async move { client.prepare(call).await });
    let pending = lane.receiver.recv().await.unwrap();
    let preparing = Arc::clone(&pending.preparing);
    let (committed, entered) = oneshot::channel();
    let (released, observed) = oneshot::channel();
    let owner_journal = journal.clone();
    let call = request.clone();
    let owner = tokio::spawn(async move {
        pending
            .complete_on_owner(&CancellationToken::new(), async {
                let _release = Released(Some(released));
                let result = owner_journal
                    .retain_payload(&call, payload(&owner_journal, &call), &preparing)
                    .await?;
                let _ = committed.send(());
                std::future::pending::<()>().await;
                Ok(result)
            })
            .await;
    });
    entered.await.unwrap();
    caller.abort();
    assert!(caller.await.unwrap_err().is_cancelled());
    tokio::time::timeout(Duration::from_secs(1), observed)
        .await
        .unwrap()
        .unwrap();
    owner.await.unwrap();
    let original = journal.retained(&request).await.unwrap().unwrap();
    assert_eq!(
        journal
            .retain_payload(
                &request,
                payload(&journal, &request),
                &AtomicBool::new(false)
            )
            .await
            .unwrap(),
        PairedPreparationResponse::RetainedReadOnly(original)
    );
}

#[tokio::test]
async fn invalid_full_closed_and_expired_lanes_do_not_prepare_a_row() {
    let fixture = Fixture::new();
    let journal = fixture.journal().await;
    let request = request(&journal);
    let (client, mut lane) = channel(
        journal.writer.clone(),
        journal.registration.clone(),
        journal.route.clone(),
    )
    .unwrap();
    let client = Arc::new(client);
    let mut wrong = request.clone();
    wrong.original.expected_principal = "another-person".into();
    assert!(client.prepare(wrong).await.is_err());
    assert!(matches!(
        lane.receiver.try_recv(),
        Err(mpsc::error::TryRecvError::Empty)
    ));
    let caller = {
        let client = client.clone();
        let call = request.clone();
        tokio::spawn(async move { client.prepare(call).await })
    };
    tokio::time::timeout(Duration::from_secs(1), async {
        while client.sender.capacity() != 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(client.prepare(request.clone()).await.is_err());
    let mut pending = lane.receiver.recv().await.unwrap();
    pending.deadline = Instant::now() - Duration::from_secs(1);
    pending
        .complete_on_owner(&CancellationToken::new(), async {
            panic!("expired request reached preparation")
        })
        .await;
    assert!(caller.await.unwrap().is_err());
    drop(lane);
    assert!(client.prepare(request.clone()).await.is_err());
    assert_eq!(journal.retained(&request).await.unwrap(), None);
}
