use super::*;

use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

type TestError = Box<dyn std::error::Error + Send + Sync>;

const PROVIDER_SCOPE: &str = "heptabao-test";
const SECRET: &[u8] = b"fixture-dynamic-secret";

#[derive(Debug)]
enum DispatchPlan {
    Completed {
        observation: BaoLeaseProviderObservation,
        secret: Option<Vec<u8>>,
    },
    Accepted,
    Rejected,
    Unknown,
}

#[derive(Debug)]
enum LookupPlan {
    Completed(BaoLeaseProviderObservation),
    Accepted,
    Rejected,
    NotFound,
    Conflict,
    Unknown,
}

#[derive(Debug)]
struct FakeState {
    dispatch_plan: Option<DispatchPlan>,
    lookup_plan: Option<LookupPlan>,
    dispatches: usize,
    lookups: usize,
    last_provider_operation_id_sha256: Option<Sha256Digest>,
}

#[derive(Clone, Debug)]
struct FakeProvider {
    supported: bool,
    state: Arc<Mutex<FakeState>>,
}

impl FakeProvider {
    fn supported() -> Self {
        Self {
            supported: true,
            state: Arc::new(Mutex::new(FakeState {
                dispatch_plan: None,
                lookup_plan: None,
                dispatches: 0,
                lookups: 0,
                last_provider_operation_id_sha256: None,
            })),
        }
    }

    fn unsupported() -> Self {
        Self {
            supported: false,
            state: Arc::new(Mutex::new(FakeState {
                dispatch_plan: None,
                lookup_plan: None,
                dispatches: 0,
                lookups: 0,
                last_provider_operation_id_sha256: None,
            })),
        }
    }

    fn set_dispatch(&self, plan: DispatchPlan) {
        if let Ok(mut state) = self.state.lock() {
            state.dispatch_plan = Some(plan);
        }
    }

    fn set_lookup(&self, plan: LookupPlan) {
        if let Ok(mut state) = self.state.lock() {
            state.lookup_plan = Some(plan);
        }
    }

    fn dispatches(&self) -> usize {
        self.state.lock().map_or(0, |state| state.dispatches)
    }

    fn lookups(&self) -> usize {
        self.state.lock().map_or(0, |state| state.lookups)
    }
}

impl BaoLeaseProvider for FakeProvider {
    fn provider_scope(&self) -> &str {
        PROVIDER_SCOPE
    }

    fn capability(&self) -> ProviderEffectIdempotencyCapability {
        if self.supported {
            ProviderEffectIdempotencyCapability::KeyAndStatusLookup
        } else {
            ProviderEffectIdempotencyCapability::Unsupported
        }
    }

    fn dispatch<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
        operation: &'a BaoLeaseOperation,
        _provider_payload: &'a [u8],
    ) -> ProviderEffectFuture<'a, BaoLeaseProviderDispatch> {
        let provider_operation_id_sha256 =
            Sha256Digest::for_bytes(operation.operation_id.as_bytes());
        let plan = match self.state.lock() {
            Ok(mut state) => {
                state.dispatches = state.dispatches.saturating_add(1);
                state.last_provider_operation_id_sha256 =
                    Some(provider_operation_id_sha256.clone());
                state.dispatch_plan.take().unwrap_or(DispatchPlan::Unknown)
            }
            Err(_) => DispatchPlan::Unknown,
        };
        let key = intent.key.clone();
        let payload_sha256 = intent.payload_sha256.clone();
        Box::pin(async move {
            match plan {
                DispatchPlan::Completed {
                    observation,
                    secret,
                } => BaoLeaseProviderDispatch::Ack {
                    ack: ProviderEffectAck::new(
                        key,
                        payload_sha256,
                        provider_operation_id_sha256,
                        ProviderEffectAckStatus::Completed,
                    ),
                    lease: Some(observation),
                    secret: match secret {
                        Some(bytes) => BaoIssuedSecret::new(bytes).ok(),
                        None => None,
                    },
                },
                DispatchPlan::Accepted => BaoLeaseProviderDispatch::Ack {
                    ack: ProviderEffectAck::new(
                        key,
                        payload_sha256,
                        provider_operation_id_sha256,
                        ProviderEffectAckStatus::Accepted,
                    ),
                    lease: None,
                    secret: None,
                },
                DispatchPlan::Rejected => BaoLeaseProviderDispatch::Ack {
                    ack: ProviderEffectAck::new(
                        key,
                        payload_sha256,
                        provider_operation_id_sha256,
                        ProviderEffectAckStatus::Rejected,
                    ),
                    lease: None,
                    secret: None,
                },
                DispatchPlan::Unknown => BaoLeaseProviderDispatch::Unknown,
            }
        })
    }

    fn lookup<'a>(
        &'a self,
        intent: &'a ProviderEffectIntent,
    ) -> ProviderEffectFuture<'a, BaoLeaseProviderLookup> {
        let (plan, prior_provider_operation_id) = match self.state.lock() {
            Ok(mut state) => {
                state.lookups = state.lookups.saturating_add(1);
                (
                    state.lookup_plan.take().unwrap_or(LookupPlan::Unknown),
                    state.last_provider_operation_id_sha256.clone(),
                )
            }
            Err(_) => (LookupPlan::Unknown, None),
        };
        let key = intent.key.clone();
        let payload_sha256 = intent.payload_sha256.clone();
        let provider_operation_id_sha256 = prior_provider_operation_id.unwrap_or_else(|| {
            Sha256Digest::for_bytes(format!("lookup:{}", key.as_str()).as_bytes())
        });
        Box::pin(async move {
            match plan {
                LookupPlan::Completed(observation) => BaoLeaseProviderLookup {
                    effect: ProviderEffectLookup::Ack(ProviderEffectAck::new(
                        key,
                        payload_sha256,
                        provider_operation_id_sha256,
                        ProviderEffectAckStatus::Completed,
                    )),
                    lease: Some(observation),
                },
                LookupPlan::Accepted => BaoLeaseProviderLookup {
                    effect: ProviderEffectLookup::Ack(ProviderEffectAck::new(
                        key,
                        payload_sha256,
                        provider_operation_id_sha256,
                        ProviderEffectAckStatus::Accepted,
                    )),
                    lease: None,
                },
                LookupPlan::Rejected => BaoLeaseProviderLookup {
                    effect: ProviderEffectLookup::Ack(ProviderEffectAck::new(
                        key,
                        payload_sha256,
                        provider_operation_id_sha256,
                        ProviderEffectAckStatus::Rejected,
                    )),
                    lease: None,
                },
                LookupPlan::NotFound => BaoLeaseProviderLookup {
                    effect: ProviderEffectLookup::NotFound,
                    lease: None,
                },
                LookupPlan::Conflict => BaoLeaseProviderLookup {
                    effect: ProviderEffectLookup::Conflict {
                        observed_payload_sha256: None,
                    },
                    lease: None,
                },
                LookupPlan::Unknown => BaoLeaseProviderLookup {
                    effect: ProviderEffectLookup::Unknown,
                    lease: None,
                },
            }
        })
    }
}

fn scope() -> [u8; 32] {
    Digest32::of_bytes(b"test-scope").into_array()
}

fn issue_request(operation_id: &str) -> BaoLeaseIssueRequest {
    BaoLeaseIssueRequest {
        operation_id: operation_id.to_string(),
        subject_id: "agent-one".to_string(),
        consumer_id: "model-provider".to_string(),
        namespace: "team/one".to_string(),
        role: "database/readonly".to_string(),
        scope_sha256: scope(),
        ttl_seconds: 60,
        renewable: true,
    }
}

fn observation(
    lease_id: &str,
    state: BaoSecretLeaseState,
    generation: u64,
    expires_at_unix_ms: u64,
) -> BaoLeaseProviderObservation {
    BaoLeaseProviderObservation {
        lease_id: lease_id.to_string(),
        state,
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms,
        renewable: true,
        generation,
        secret_sha256: Digest32::of_bytes(SECRET).into_array(),
    }
}

fn authority(root: &Path) -> Result<FinalUseAuthority, TestError> {
    let issuer = SigningKey::from_bytes(&[71; 32]);
    Ok(FinalUseAuthority::open_state_dir(
        &root.join("authority"),
        "owner".to_string(),
        issuer.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 3,
            revision: 1,
            revoked_grant_ids: Default::default(),
        },
    )?)
}

fn signed_grant(
    binding: FinalUseBinding,
    nonce_byte: u8,
    grant_id: &str,
) -> Result<SignedFinalUseGrant, TestError> {
    let issuer = SigningKey::from_bytes(&[71; 32]);
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "owner".to_string(),
        authority_epoch: 3,
        grant_id: grant_id.to_string(),
        nonce: [nonce_byte; 32],
        binding,
        not_before_unix_ms: now.saturating_sub(1_000),
        expires_at_unix_ms: now.saturating_add(30_000),
    };
    let signature = issuer.sign(&grant.signing_bytes()?).to_bytes().to_vec();
    Ok(SignedFinalUseGrant { grant, signature })
}

#[tokio::test]
async fn issue_is_durable_before_secret_delivery_and_duplicate_never_redispatches(
) -> Result<(), TestError> {
    let root = tempfile::tempdir()?;
    let state_dir = root.path().join("leases");
    let provider = FakeProvider::supported();
    provider.set_dispatch(DispatchPlan::Completed {
        observation: observation("lease-1", BaoSecretLeaseState::Active, 1, 61_000),
        secret: Some(SECRET.to_vec()),
    });
    let mut coordinator = BaoLeaseCoordinator::open(provider.clone(), &state_dir)?;
    let authority = authority(root.path())?;
    let request = issue_request("issue-one");
    let payload = br#"{"role":"database/readonly"}"#;
    let binding = coordinator.binding(&BaoLeaseRequest::Issue(request.clone()), payload)?;
    let grant = signed_grant(binding, 1, "grant-issue-1")?;

    let journal_path = state_dir.join("lease.journal");
    let mut durable_before_delivery = false;
    let mut consumed = false;
    let receipt = coordinator
        .request_secret_lease(&authority, &grant, &request, payload, |bytes| {
            consumed = bytes == SECRET;
            durable_before_delivery = std::fs::read_to_string(&journal_path)
                .map(|journal| journal.contains("lease-1") && !journal.contains("fixture-dynamic-secret"))
                .unwrap_or(false);
            Ok(())
        })
        .await?;
    assert!(consumed);
    assert!(durable_before_delivery);
    assert_eq!(receipt.state, ProviderEffectState::Completed);
    assert!(receipt.secret_delivered);
    assert!(receipt.physical_dispatch_attempted);
    assert_eq!(provider.dispatches(), 1);
    assert!(!serde_json::to_string(&receipt)?.contains("fixture-dynamic-secret"));

    let duplicate_binding =
        coordinator.binding(&BaoLeaseRequest::Issue(request.clone()), payload)?;
    let duplicate_grant = signed_grant(duplicate_binding, 2, "grant-issue-2")?;
    let duplicate = coordinator
        .request_secret_lease(&authority, &duplicate_grant, &request, payload, |_| {
            panic!("a completed dynamic secret must never be replayed from local state")
        })
        .await?;
    assert_eq!(duplicate.state, ProviderEffectState::Completed);
    assert!(!duplicate.secret_delivered);
    assert!(!duplicate.physical_dispatch_attempted);
    assert_eq!(provider.dispatches(), 1);

    let changed_payload = br#"{"role":"database/readonly","drift":true}"#;
    let changed_binding =
        coordinator.binding(&BaoLeaseRequest::Issue(request.clone()), changed_payload)?;
    let changed_grant = signed_grant(changed_binding, 3, "grant-issue-3")?;
    assert_eq!(
        coordinator
            .request_secret_lease(
                &authority,
                &changed_grant,
                &request,
                changed_payload,
                |_| Ok(())
            )
            .await,
        Err(BaoLeaseError::OperationConflict)
    );
    assert_eq!(provider.dispatches(), 1);
    Ok(())
}

#[tokio::test]
async fn unknown_issue_survives_restart_and_reconciles_without_reissue(
) -> Result<(), TestError> {
    let root = tempfile::tempdir()?;
    let state_dir = root.path().join("leases");
    let provider = FakeProvider::supported();
    provider.set_dispatch(DispatchPlan::Unknown);
    let authority = authority(root.path())?;
    let request = issue_request("issue-unknown");
    let payload = br#"{"role":"database/readonly"}"#;

    {
        let mut coordinator = BaoLeaseCoordinator::open(provider.clone(), &state_dir)?;
        let binding = coordinator.binding(&BaoLeaseRequest::Issue(request.clone()), payload)?;
        let grant = signed_grant(binding, 11, "grant-unknown-1")?;
        let receipt = coordinator
            .request_secret_lease(&authority, &grant, &request, payload, |_| {
                panic!("unknown provider outcome cannot release a secret")
            })
            .await?;
        assert_eq!(receipt.state, ProviderEffectState::Indeterminate);
        assert_eq!(provider.dispatches(), 1);
    }

    let mut coordinator = BaoLeaseCoordinator::open(provider.clone(), &state_dir)?;
    let retry_binding = coordinator.binding(&BaoLeaseRequest::Issue(request.clone()), payload)?;
    let retry_grant = signed_grant(retry_binding, 12, "grant-unknown-2")?;
    let retry = coordinator
        .request_secret_lease(&authority, &retry_grant, &request, payload, |_| {
            panic!("restart retry must not redispatch")
        })
        .await?;
    assert_eq!(retry.state, ProviderEffectState::Indeterminate);
    assert!(!retry.physical_dispatch_attempted);
    assert_eq!(provider.dispatches(), 1);

    provider.set_lookup(LookupPlan::Completed(observation(
        "lease-reconciled",
        BaoSecretLeaseState::Active,
        1,
        61_000,
    )));
    let reconcile_request = BaoLeaseReconcileRequest {
        operation_id: request.operation_id.clone(),
        subject_id: request.subject_id.clone(),
    };
    let reconcile_binding = coordinator.reconcile_binding(&reconcile_request)?;
    let reconcile_grant = signed_grant(reconcile_binding, 13, "grant-reconcile-1")?;
    let reconciled = coordinator
        .reconcile(&authority, &reconcile_grant, &reconcile_request)
        .await?;
    assert_eq!(reconciled.state, ProviderEffectState::Completed);
    assert!(!reconciled.secret_delivered);
    assert!(!reconciled.physical_dispatch_attempted);
    assert_eq!(provider.dispatches(), 1);
    assert_eq!(provider.lookups(), 1);
    assert_eq!(
        reconciled.lease.as_ref().map(|lease| lease.lease_id.as_str()),
        Some("lease-reconciled")
    );
    Ok(())
}

#[tokio::test]
async fn renew_and_revoke_are_generation_bound_and_deduplicated() -> Result<(), TestError> {
    let root = tempfile::tempdir()?;
    let state_dir = root.path().join("leases");
    let provider = FakeProvider::supported();
    let authority = authority(root.path())?;
    let mut coordinator = BaoLeaseCoordinator::open(provider.clone(), &state_dir)?;
    let issue = issue_request("issue-lifecycle");
    let issue_payload = b"issue";
    provider.set_dispatch(DispatchPlan::Completed {
        observation: observation("lease-life", BaoSecretLeaseState::Active, 1, 61_000),
        secret: Some(SECRET.to_vec()),
    });
    let issue_binding =
        coordinator.binding(&BaoLeaseRequest::Issue(issue.clone()), issue_payload)?;
    let issue_grant = signed_grant(issue_binding, 21, "grant-life-issue")?;
    coordinator
        .request_secret_lease(
            &authority,
            &issue_grant,
            &issue,
            issue_payload,
            |_| Ok(()),
        )
        .await?;

    let renew = BaoLeaseRenewRequest {
        operation_id: "renew-lifecycle".to_string(),
        subject_id: issue.subject_id.clone(),
        namespace: issue.namespace.clone(),
        lease_id: "lease-life".to_string(),
        scope_sha256: issue.scope_sha256,
        ttl_seconds: 120,
    };
    provider.set_dispatch(DispatchPlan::Completed {
        observation: observation("lease-life", BaoSecretLeaseState::Active, 2, 121_000),
        secret: None,
    });
    let renew_payload = b"renew";
    let renew_binding =
        coordinator.binding(&BaoLeaseRequest::Renew(renew.clone()), renew_payload)?;
    let renew_grant = signed_grant(renew_binding, 22, "grant-life-renew")?;
    let renewed = coordinator
        .renew(&authority, &renew_grant, &renew, renew_payload)
        .await?;
    assert_eq!(renewed.state, ProviderEffectState::Completed);
    assert_eq!(
        renewed.lease.as_ref().map(|lease| lease.generation),
        Some(2)
    );

    let duplicate_binding =
        coordinator.binding(&BaoLeaseRequest::Renew(renew.clone()), renew_payload)?;
    let duplicate_grant = signed_grant(duplicate_binding, 23, "grant-life-renew-2")?;
    let duplicate = coordinator
        .renew(&authority, &duplicate_grant, &renew, renew_payload)
        .await?;
    assert!(!duplicate.physical_dispatch_attempted);
    assert_eq!(provider.dispatches(), 2);

    let revoke = BaoLeaseRevokeRequest {
        operation_id: "revoke-lifecycle".to_string(),
        subject_id: issue.subject_id.clone(),
        namespace: issue.namespace.clone(),
        lease_id: "lease-life".to_string(),
        scope_sha256: issue.scope_sha256,
    };
    provider.set_dispatch(DispatchPlan::Completed {
        observation: observation("lease-life", BaoSecretLeaseState::Revoked, 3, 121_000),
        secret: None,
    });
    let revoke_payload = b"revoke";
    let revoke_binding =
        coordinator.binding(&BaoLeaseRequest::Revoke(revoke.clone()), revoke_payload)?;
    let revoke_grant = signed_grant(revoke_binding, 24, "grant-life-revoke")?;
    let revoked = coordinator
        .revoke(&authority, &revoke_grant, &revoke, revoke_payload)
        .await?;
    assert_eq!(
        revoked.lease.as_ref().map(|lease| lease.state),
        Some(BaoSecretLeaseState::Revoked)
    );
    assert_eq!(provider.dispatches(), 3);
    Ok(())
}

#[tokio::test]
async fn secret_digest_mismatch_is_quarantined_and_never_delivered() -> Result<(), TestError> {
    let root = tempfile::tempdir()?;
    let state_dir = root.path().join("leases");
    let provider = FakeProvider::supported();
    provider.set_dispatch(DispatchPlan::Completed {
        observation: observation("lease-bad-secret", BaoSecretLeaseState::Active, 1, 61_000),
        secret: Some(b"wrong-secret".to_vec()),
    });
    let authority = authority(root.path())?;
    let mut coordinator = BaoLeaseCoordinator::open(provider.clone(), &state_dir)?;
    let request = issue_request("issue-bad-secret");
    let payload = b"issue";
    let binding = coordinator.binding(&BaoLeaseRequest::Issue(request.clone()), payload)?;
    let grant = signed_grant(binding, 31, "grant-bad-secret")?;
    assert_eq!(
        coordinator
            .request_secret_lease(&authority, &grant, &request, payload, |_| {
                panic!("mismatched secret digest must never be delivered")
            })
            .await,
        Err(BaoLeaseError::SecretDigestMismatch)
    );
    let stored = coordinator
        .store
        .state()
        .operations
        .get(&request.operation_id)
        .ok_or("missing stored operation")?;
    assert_eq!(
        coordinator.store.state().effect.state(&stored.intent.key),
        Some(ProviderEffectState::Indeterminate)
    );
    assert_eq!(provider.dispatches(), 1);
    Ok(())
}

#[tokio::test]
async fn unsupported_provider_is_rejected_before_dispatch() -> Result<(), TestError> {
    let root = tempfile::tempdir()?;
    let provider = FakeProvider::unsupported();
    let authority = authority(root.path())?;
    let mut coordinator =
        BaoLeaseCoordinator::open(provider.clone(), &root.path().join("leases"))?;
    let request = issue_request("unsupported-provider");
    let payload = b"issue";
    let binding = coordinator.binding(&BaoLeaseRequest::Issue(request.clone()), payload)?;
    let grant = signed_grant(binding, 41, "grant-unsupported")?;
    assert_eq!(
        coordinator
            .request_secret_lease(&authority, &grant, &request, payload, |_| Ok(()))
            .await,
        Err(BaoLeaseError::UnsupportedProviderCapability)
    );
    assert_eq!(provider.dispatches(), 0);
    assert_eq!(provider.lookups(), 0);
    Ok(())
}

#[tokio::test]
async fn accepted_status_reconciles_to_completed_without_second_dispatch() -> Result<(), TestError> {
    let root = tempfile::tempdir()?;
    let provider = FakeProvider::supported();
    provider.set_dispatch(DispatchPlan::Accepted);
    let authority = authority(root.path())?;
    let mut coordinator =
        BaoLeaseCoordinator::open(provider.clone(), &root.path().join("leases"))?;
    let request = issue_request("accepted-provider");
    let payload = b"issue";
    let binding = coordinator.binding(&BaoLeaseRequest::Issue(request.clone()), payload)?;
    let grant = signed_grant(binding, 51, "grant-accepted")?;
    let accepted = coordinator
        .request_secret_lease(&authority, &grant, &request, payload, |_| Ok(()))
        .await?;
    assert_eq!(accepted.state, ProviderEffectState::Accepted);

    provider.set_lookup(LookupPlan::Completed(observation(
        "lease-accepted",
        BaoSecretLeaseState::Active,
        1,
        61_000,
    )));
    let reconcile = BaoLeaseReconcileRequest {
        operation_id: request.operation_id,
        subject_id: request.subject_id,
    };
    let binding = coordinator.reconcile_binding(&reconcile)?;
    let grant = signed_grant(binding, 52, "grant-accepted-reconcile")?;
    let completed = coordinator.reconcile(&authority, &grant, &reconcile).await?;
    assert_eq!(completed.state, ProviderEffectState::Completed);
    assert_eq!(provider.dispatches(), 1);
    assert_eq!(provider.lookups(), 1);
    Ok(())
}

#[test]
fn operation_key_is_stable_but_payload_drift_changes_intent_digest() -> Result<(), TestError> {
    let request = issue_request("stable-operation");
    let first = normalize_issue(&request, b"payload-a")?;
    let second = normalize_issue(&request, b"payload-b")?;
    let first_intent = intent_for(PROVIDER_SCOPE, &first)?;
    let second_intent = intent_for(PROVIDER_SCOPE, &second)?;
    assert_eq!(first_intent.key, second_intent.key);
    assert_ne!(first_intent.payload_sha256, second_intent.payload_sha256);
    Ok(())
}

#[test]
fn provider_rejected_and_lookup_nonterminals_are_distinct_fixture_shapes() {
    let _ = DispatchPlan::Rejected;
    let _ = LookupPlan::Accepted;
    let _ = LookupPlan::Rejected;
    let _ = LookupPlan::NotFound;
    let _ = LookupPlan::Conflict;
}
