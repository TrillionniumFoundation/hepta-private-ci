#![cfg(unix)]
//! Real kernel/SQLite tests for continuations of a lazy transport future.
//! No network, production keys or homeserver qualification is implied.

use std::collections::BTreeSet;
use std::error::Error;
use std::fs;
use std::fs::File;
use std::future::poll_fn;
use std::io::Read;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::task::Poll;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_protocol::MatrixRoomId;
use codex_hepta_matrix_protocol::MatrixTransactionId;
use codex_hepta_matrix_protocol::MatrixUserId;
use codex_hepta_matrix_protocol::outbox_id;
use codex_hepta_matrix_protocol::transaction_id;
use codex_hepta_matrix_sdk::MatrixAuthorityError;
use codex_hepta_matrix_sdk::MatrixFinalUseRequest;
use codex_hepta_matrix_sdk::MatrixGrantFuture;
use codex_hepta_matrix_sdk::MatrixOutboundAuthorizer;
use codex_hepta_matrix_sdk::MatrixOutboundIdentity;
use codex_hepta_matrix_sdk::MatrixOutboundTransport;
use codex_hepta_matrix_sdk::MatrixRawSendSeal;
use codex_hepta_matrix_sdk::MatrixSendFuture;
use codex_hepta_matrix_sdk::MatrixTransportError;
use codex_hepta_matrix_sdk::OutboxDispatchConfig;
use codex_hepta_matrix_sdk::dispatch_outbox_once;
use codex_hepta_matrix_store::MatrixAttemptFailureClass;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableConfig;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxDraft;
use codex_hepta_matrix_store::OutboxKind;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_matrix_store::RoomBindingDraft;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use tokio_util::sync::CancellationToken;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

#[derive(Clone, Copy, Eq, PartialEq)]
enum Interruption {
    None,
    Revoked,
    RevokedDuringConstruction,
    EpochChanged,
    FeedUnavailable,
    IdentityChanged,
    UnrelatedNonce,
}

fn now_ms() -> TestResult<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

// This Unix-only integration test obtains ephemeral signing keys and nonces
// from the kernel CSPRNG. No reusable test secret or predictable nonce is
// embedded in source or retained outside the test process.
fn next_test_material() -> TestResult<[u8; 32]> {
    let mut material = [0_u8; 32];
    File::open("/dev/urandom")?.read_exact(&mut material)?;
    Ok(material)
}

async fn fixture() -> TestResult<(
    TempDir,
    HeptaAgentLayout,
    MatrixDurableStore,
    MatrixTransactionId,
)> {
    let temp = TempDir::new()?;
    let root = temp.path().join("fleet");
    fs::create_dir_all(&root)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let layout = HeptaFleetRoot::parse(root.canonicalize()?)?
        .layout()
        .agent(&agent);
    let store = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    let room = MatrixRoomId::parse("!allowed:example.test")?;
    store
        .bind_room(&RoomBindingDraft {
            room_id: room.clone(),
            agent_user_id: MatrixUserId::parse("@agent:example.test")?,
            expected_revision: None,
            generation: 1,
            changed_at_ms: 1,
        })
        .await?;
    let logical = outbox_id(&agent, &room, "thread", "turn", "item", "final");
    let txn = transaction_id(&logical, /*revision*/ 1)?;
    store
        .enqueue_outbox(&OutboxDraft {
            logical_outbox_id: logical,
            revision: 1,
            txn_id: txn.clone(),
            room_id: room,
            kind: OutboxKind::Final,
            payload: b"complete".to_vec(),
            binding_revision: 1,
            generation: 1,
            created_at_ms: 2,
        })
        .await?;
    Ok((temp, layout, store, txn))
}

struct Authorizer {
    authority: FinalUseAuthority,
    key: SigningKey,
    _directory: TempDir,
    polls: Arc<AtomicU64>,
    constructions: Arc<AtomicU64>,
    changed: AtomicU64,
    interruption: Interruption,
}

impl Authorizer {
    fn new(
        polls: Arc<AtomicU64>,
        constructions: Arc<AtomicU64>,
        interruption: Interruption,
    ) -> TestResult<Self> {
        let directory = TempDir::new()?;
        fs::set_permissions(directory.path(), fs::Permissions::from_mode(0o700))?;
        let key = SigningKey::from_bytes(&next_test_material()?);
        let authority = FinalUseAuthority::open_state_dir(
            directory.path(),
            "matrix-pending-test".to_string(),
            key.verifying_key().to_bytes(),
            FinalUseRevocations {
                authority_epoch: 17,
                revision: 1,
                revoked_grant_ids: BTreeSet::new(),
            },
        )?;
        Ok(Self {
            authority,
            key,
            _directory: directory,
            polls,
            constructions,
            changed: AtomicU64::new(0),
            interruption,
        })
    }

    fn sign(
        &self,
        binding: FinalUseBinding,
        nonce: [u8; 32],
    ) -> Result<SignedFinalUseGrant, MatrixAuthorityError> {
        let now = now_ms().map_err(|_| MatrixAuthorityError::Unavailable)?;
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "matrix-pending-test".to_string(),
            authority_epoch: 17,
            grant_id: "pending-grant".to_string(),
            nonce,
            binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now.saturating_add(60_000),
        };
        let bytes = grant
            .signing_bytes()
            .map_err(|_| MatrixAuthorityError::InvalidBinding)?;
        let signature = self.key.sign(&bytes).to_bytes().to_vec();
        Ok(SignedFinalUseGrant { grant, signature })
    }
}

impl MatrixOutboundAuthorizer for Authorizer {
    fn authority(&self) -> &FinalUseAuthority {
        &self.authority
    }

    fn signed_grant<'a>(&'a self, request: &'a MatrixFinalUseRequest) -> MatrixGrantFuture<'a> {
        Box::pin(async move {
            let nonce = next_test_material().map_err(|_| MatrixAuthorityError::Unavailable)?;
            self.sign(request.binding.clone(), nonce)
        })
    }

    fn refresh_revocations(&self) -> Result<(), MatrixAuthorityError> {
        let boundary_crossed = if self.interruption == Interruption::RevokedDuringConstruction {
            self.constructions.load(Ordering::SeqCst) != 0
        } else {
            self.polls.load(Ordering::SeqCst) != 0
        };
        if !boundary_crossed || self.changed.swap(1, Ordering::SeqCst) != 0 {
            return Ok(());
        }
        match self.interruption {
            Interruption::Revoked
            | Interruption::RevokedDuringConstruction
            | Interruption::EpochChanged => self
                .authority
                .update_revocations(FinalUseRevocations {
                    authority_epoch: if self.interruption == Interruption::EpochChanged {
                        18
                    } else {
                        17
                    },
                    revision: 2,
                    revoked_grant_ids: BTreeSet::from(["pending-grant".to_string()]),
                })
                .map_err(|_| MatrixAuthorityError::Unavailable),
            Interruption::FeedUnavailable => Err(MatrixAuthorityError::Unavailable),
            Interruption::UnrelatedNonce => {
                let binding = FinalUseBinding {
                    subject_id: "other-subject".to_string(),
                    destination_id: "other-destination".to_string(),
                    request_sha256: [2; 32],
                    scope_sha256: [3; 32],
                    payload_sha256: [4; 32],
                };
                let nonce = next_test_material().map_err(|_| MatrixAuthorityError::Unavailable)?;
                let signed = self.sign(binding.clone(), nonce)?;
                self.authority
                    .claim(&signed, &binding)
                    .map_err(|_| MatrixAuthorityError::Unavailable)?;
                Ok(())
            }
            Interruption::None | Interruption::IdentityChanged => Ok(()),
        }
    }
}

struct Transport {
    polls: Arc<AtomicU64>,
    constructions: Arc<AtomicU64>,
    interruption: Interruption,
}

impl MatrixOutboundTransport for Transport {
    fn identity(&self) -> Result<MatrixOutboundIdentity, MatrixTransportError> {
        let rotated = self.interruption == Interruption::IdentityChanged
            && self.polls.load(Ordering::SeqCst) != 0;
        Ok(MatrixOutboundIdentity {
            homeserver_id: "https://example.test".to_string(),
            matrix_user_id: "@agent:example.test".to_string(),
            device_id: if rotated { "ROTATED" } else { "DEVICE" }.to_string(),
            session_generation: 1,
        })
    }

    fn send<'a>(
        &'a self,
        _record: &'a OutboxRecord,
        _seal: MatrixRawSendSeal,
    ) -> MatrixSendFuture<'a> {
        self.constructions.fetch_add(1, Ordering::SeqCst);
        Box::pin(poll_fn(move |context| {
            if self.polls.fetch_add(1, Ordering::SeqCst) == 0 {
                context.waker().wake_by_ref();
                Poll::Pending
            } else {
                Poll::Ready(
                    MatrixEventId::parse("$transport-accepted")
                        .map_err(|_| MatrixTransportError::ResponseLost),
                )
            }
        }))
    }
}

async fn check_interruption(interruption: Interruption) -> TestResult {
    let (_temp, layout, store, txn) = fixture().await?;
    let polls = Arc::new(AtomicU64::new(0));
    let constructions = Arc::new(AtomicU64::new(0));
    let authority = Authorizer::new(
        Arc::clone(&polls),
        Arc::clone(&constructions),
        interruption,
    )?;
    let transport = Transport {
        polls: Arc::clone(&polls),
        constructions: Arc::clone(&constructions),
        interruption,
    };
    let config = OutboxDispatchConfig {
        max_attempts: 1,
        ..OutboxDispatchConfig::default()
    };
    let stats = dispatch_outbox_once(
        &store,
        &transport,
        &authority,
        &config,
        &CancellationToken::new(),
        now_ms()?,
    )
    .await?;
    // Even on later revocation, immutable digest work is one per entry;
    // every transport poll still has a live authority/session/time check.
    assert_eq!(stats.entered_attempts, 1);
    assert_eq!(stats.payload_digest_checks, 1);
    assert_eq!(constructions.load(Ordering::SeqCst), 1);
    assert_eq!(
        stats.claim_to_first_poll_samples,
        u64::from(interruption != Interruption::RevokedDuringConstruction)
    );
    assert!(stats.dynamic_checks >= stats.transport_polls);
    assert_eq!(stats.transport_polls, polls.load(Ordering::SeqCst));
    let continuing = matches!(
        interruption,
        Interruption::None | Interruption::UnrelatedNonce
    );
    let expected_polls = if interruption == Interruption::RevokedDuringConstruction {
        0
    } else if continuing {
        2
    } else {
        1
    };
    assert_eq!(polls.load(Ordering::SeqCst), expected_polls);
    assert_eq!(
        (
            stats.sent,
            stats.permanent_failure,
            stats.transport_accepted
        ),
        (0, 0, u64::from(continuing))
    );
    let expected = if continuing {
        MatrixDispatchState::Accepted
    } else {
        MatrixDispatchState::Indeterminate
    };
    assert_eq!(
        store
            .dispatch_for_txn(&txn)
            .await?
            .ok_or("missing ledger")?
            .state,
        expected
    );
    if !continuing {
        assert!(
            store
                .dispatch_attempt_events(&txn)
                .await?
                .iter()
                .any(|event| {
                    event.failure_class == Some(MatrixAttemptFailureClass::ResponseLost)
                })
        );
    }
    let events = store.dispatch_attempt_events(&txn).await?;
    store.close().await;
    let reopened = MatrixDurableStore::open(&layout, MatrixDurableConfig::default()).await?;
    assert_eq!(
        reopened
            .dispatch_for_txn(&txn)
            .await?
            .ok_or("missing reopened ledger")?
            .state,
        expected
    );
    assert_eq!(reopened.dispatch_attempt_events(&txn).await?, events);
    reopened.close().await;
    Ok(())
}

#[tokio::test]
async fn revoked_while_pending_stops_polling_and_survives_reopen() -> TestResult {
    check_interruption(Interruption::Revoked).await
}

#[tokio::test]
async fn revocation_during_future_construction_blocks_first_transport_poll() -> TestResult {
    check_interruption(Interruption::RevokedDuringConstruction).await
}

#[tokio::test]
async fn epoch_change_while_pending_preserves_unknown_effect() -> TestResult {
    check_interruption(Interruption::EpochChanged).await
}

#[tokio::test]
async fn feed_failure_while_pending_preserves_unknown_effect() -> TestResult {
    check_interruption(Interruption::FeedUnavailable).await
}

#[tokio::test]
async fn device_change_while_pending_preserves_unknown_effect() -> TestResult {
    check_interruption(Interruption::IdentityChanged).await
}

#[tokio::test]
async fn unchanged_authority_resumes_without_a_new_effect_entry() -> TestResult {
    check_interruption(Interruption::None).await
}

#[tokio::test]
async fn another_nonce_claim_does_not_change_the_revocation_head() -> TestResult {
    check_interruption(Interruption::UnrelatedNonce).await
}
