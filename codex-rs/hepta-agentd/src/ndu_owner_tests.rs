use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agent_protocol::NduControlRequestV1;
use codex_hepta_agent_protocol::NduControlResultV1;
use codex_hepta_agent_protocol::NduMutationOperationV1;
use codex_hepta_agent_protocol::NduMutationV1;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_ndu::AggregationOperator;
use codex_hepta_ndu::AxisAggregationRule;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisLimit;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::NduProjectionJournalError;
use codex_hepta_ndu::NduProjectionKindV1;
use codex_hepta_ndu::NduProjectionStoreError;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_types::FixedQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

type TestResult<T> = Result<T, Box<dyn std::error::Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn policy() -> TestResult<NduProductionPolicyV1> {
    let utility_profile = UtilityProfile {
        profile_id: id("production-utility-v1")?,
        axis_registry_digest: digest("axis-registry"),
        normalization_manifest_digest: digest("normalization"),
        dimensions: vec![(id("success")?, AxisDirection::Maximize)],
        risk_ceilings: vec![AxisLimit {
            axis: id("risk")?,
            maximum: FixedQ32::ZERO,
        }],
        resource_ceilings: vec![AxisLimit {
            axis: id("compute")?,
            maximum: FixedQ32::ONE,
        }],
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")?],
        },
    };
    Ok(NduProductionPolicyV1 {
        utility_profile,
        evaluation_policy: EvaluationPolicyV1 {
            policy_id: id("production-policy-v1")?,
            utility_rules: vec![AxisAggregationRule {
                axis: id("success")?,
                operator: AggregationOperator::Sum,
            }],
            risk_rules: vec![AxisAggregationRule {
                axis: id("risk")?,
                operator: AggregationOperator::Maximum,
            }],
            resource_rules: vec![AxisAggregationRule {
                axis: id("compute")?,
                operator: AggregationOperator::Sum,
            }],
            uncertainty_rules: vec![AxisAggregationRule {
                axis: id("success")?,
                operator: AggregationOperator::Maximum,
            }],
            pareto_absolute_tolerances: vec![AxisValue {
                axis: id("success")?,
                value: FixedQ32::ZERO,
            }],
        },
        scalarization: None,
    })
}

struct Fixture {
    agent_id: AgentId,
    host: Arc<AgentdNduOwnerHostV1>,
    authority: FinalUseAuthority,
    signing: SigningKey,
    nonce: u8,
    store: tempfile::TempDir,
    authority_dir: tempfile::TempDir,
}

fn fixture() -> TestResult<Fixture> {
    let store = tempfile::tempdir()?;
    let authority_dir = tempfile::tempdir()?;
    std::fs::set_permissions(store.path(), std::fs::Permissions::from_mode(0o700))?;
    std::fs::set_permissions(authority_dir.path(), std::fs::Permissions::from_mode(0o700))?;
    let signing_seed = format!(
        "ndu-owner-tests:{}:{}:{}",
        authority_dir.path().display(),
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos(),
        std::process::id(),
    );
    let signing_bytes = *digest(&signing_seed).as_array();
    let signing = SigningKey::from_bytes(&signing_bytes);
    let authority = FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "ndu-product-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000071")?;
    let host = AgentdNduOwnerHostV1::open(
        agent_id.clone(),
        7,
        AgentdNduOwnerBootstrapV1 {
            store_root: store.path().to_path_buf(),
            authority: authority.clone(),
            policy: policy()?,
        },
    )?;
    Ok(Fixture {
        agent_id,
        host,
        authority,
        signing,
        nonce: 1,
        store,
        authority_dir,
    })
}

impl Fixture {
    fn sign(
        &mut self,
        mutation: &NduOwnerMutationV1,
        grant_id: &str,
    ) -> TestResult<SignedFinalUseGrant> {
        let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis() as u64;
        let nonce_sequence = self.nonce;
        self.nonce = self.nonce.checked_add(1).ok_or("nonce bound")?;
        let nonce_material = format!(
            "ndu-owner-tests:{}:{}:{}:{}",
            grant_id,
            nonce_sequence,
            now,
            self.store.path().display(),
        );
        let nonce = *digest(&nonce_material).as_array();
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "ndu-product-issuer".to_string(),
            authority_epoch: 1,
            grant_id: grant_id.to_string(),
            nonce,
            binding: self.host.final_use_binding(mutation)?,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now.saturating_add(60_000),
        };
        let signature = self.signing.sign(&grant.signing_bytes()?);
        Ok(SignedFinalUseGrant {
            grant,
            signature: signature.to_bytes().to_vec(),
        })
    }
}

fn append(label: &str) -> NduOwnerMutationV1 {
    NduOwnerMutationV1::AppendProjection {
        kind: NduProjectionKindV1::Preference,
        identity_digest: digest(&format!("{label}-append")),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        projection_digest: digest(&format!("{label}-projection")),
    }
}

fn select(
    label: &str,
    expected_predecessor: Option<Digest32>,
    projection: Digest32,
) -> NduOwnerMutationV1 {
    NduOwnerMutationV1::SelectProjection {
        identity_digest: digest(&format!("{label}-select")),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        expected_predecessor,
        projection_digest: projection,
    }
}

fn external_admission(
    host: &AgentdNduOwnerHostV1,
    inner: NduControlRequestV1,
    request_id: &str,
    idempotency_key: &str,
) -> TestResult<NduControlRequestV1> {
    let context = host.context()?;
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let payload_digest = inner
        .canonical_payload_digest_v2()
        .map_err(std::io::Error::other)?;
    Ok(NduControlRequestV1::ExternalAdmissionV2 {
        schema_version: NduControlRequestV1::EXTERNAL_ADMISSION_SCHEMA_VERSION_V2,
        request_id: request_id.to_string(),
        idempotency_key: idempotency_key.to_string(),
        caller_id: "control-plane".to_string(),
        issued_at_unix_ms: now.saturating_sub(1),
        deadline_unix_ms: now.saturating_add(60_000),
        host_generation: context.host_generation,
        fence_digest: *context.fence_digest.as_array(),
        revocation_head_digest: *context.revocation_frontier_digest.as_array(),
        payload_digest,
        request: Box::new(inner),
        extensions: Vec::new(),
    })
}

#[test]
fn named_host_has_one_writer_and_recovers_selection() -> TestResult<()> {
    let mut fixture = fixture()?;
    fixture.host.require_identity(&fixture.agent_id, 7)?;
    assert!(matches!(
        fixture.host.require_identity(&fixture.agent_id, 8),
        Err(AgentdNduOwnerErrorV1::IdentityMismatch)
    ));
    let context = fixture.host.context()?;
    assert_eq!(context.owner_id, id("utility.ndu")?);
    assert!(!context.revocation_frontier_digest.is_zero());

    let first = append("first");
    let projection = digest("first-projection");
    let signed = fixture.sign(&first, "append-first")?;
    fixture.host.apply_mutation(&signed, first)?;
    let selected = select("first", None, projection);
    let signed = fixture.sign(&selected, "select-first")?;
    fixture.host.apply_mutation(&signed, selected)?;
    assert_eq!(
        fixture
            .host
            .selected_projection_digest(digest("objective"), digest("subject"))?,
        Some(projection)
    );

    let second = AgentdNduOwnerHostV1::open(
        fixture.agent_id.clone(),
        7,
        AgentdNduOwnerBootstrapV1 {
            store_root: fixture.store.path().to_path_buf(),
            authority: fixture.authority.clone(),
            policy: policy()?,
        },
    );
    assert!(matches!(
        second,
        Err(AgentdNduOwnerErrorV1::Owner(NduOwnerError::Store(
            NduProjectionStoreError::Busy
        )))
    ));

    let head = fixture.authority.revocation_head()?;
    let store_path = fixture.store.path().to_path_buf();
    let authority_path = fixture.authority_dir.path().to_path_buf();
    let agent_id = fixture.agent_id.clone();
    drop(fixture.host);
    drop(fixture.authority);
    let authority = FinalUseAuthority::open_state_dir(
        &authority_path,
        "ndu-product-issuer".to_string(),
        fixture.signing.verifying_key().to_bytes(),
        head,
    )?;
    let reopened = AgentdNduOwnerHostV1::open(
        agent_id,
        7,
        AgentdNduOwnerBootstrapV1 {
            store_root: store_path,
            authority,
            policy: policy()?,
        },
    )?;
    assert_eq!(
        reopened.selected_projection_digest(digest("objective"), digest("subject"))?,
        Some(projection)
    );
    Ok(())
}

#[test]
fn named_host_rejects_stale_selection_and_live_revocation() -> TestResult<()> {
    let mut fixture = fixture()?;
    let first = append("first");
    let first_projection = digest("first-projection");
    let signed = fixture.sign(&first, "append-first")?;
    fixture.host.apply_mutation(&signed, first)?;
    let second = append("second");
    let second_projection = digest("second-projection");
    let signed = fixture.sign(&second, "append-second")?;
    fixture.host.apply_mutation(&signed, second)?;
    let selected = select("first", None, first_projection);
    let signed = fixture.sign(&selected, "select-first")?;
    fixture.host.apply_mutation(&signed, selected)?;
    let stale = select("second", None, second_projection);
    let signed = fixture.sign(&stale, "select-second")?;
    assert!(matches!(
        fixture.host.apply_mutation(&signed, stale),
        Err(AgentdNduOwnerErrorV1::Owner(NduOwnerError::Store(
            NduProjectionStoreError::Journal(
                NduProjectionJournalError::SelectionPredecessorMismatch
            )
        )))
    ));

    fixture.authority.update_revocations(FinalUseRevocations {
        authority_epoch: 1,
        revision: 2,
        revoked_grant_ids: BTreeSet::from(["revoked-current".to_string()]),
    })?;
    let revoked = append("revoked-current");
    let signed = fixture.sign(&revoked, "revoked-current")?;
    assert!(matches!(
        fixture.host.apply_mutation(&signed, revoked),
        Err(AgentdNduOwnerErrorV1::Owner(NduOwnerError::Authority(
            FinalUseError::Revoked
        )))
    ));
    Ok(())
}

#[test]
fn external_admission_binds_live_owner_and_replay_identity() -> TestResult<()> {
    let fixture = fixture()?;
    let inner = NduControlRequestV1::Selection {
        objective: *digest("objective").as_array(),
        subject: *digest("subject").as_array(),
    };
    let admitted = external_admission(&fixture.host, inner, "read-selection", "idem-read")?;
    let duplicate = admitted.clone();
    let first = fixture.host.control(admitted, || Ok(()))?;
    assert!(matches!(
        first,
        NduControlResultV1::Selection {
            projection: None,
            ..
        }
    ));
    assert_eq!(fixture.host.control(duplicate, || Ok(()))?, first);

    let conflict = external_admission(
        &fixture.host,
        NduControlRequestV1::Outcome {
            identity: *digest("other-operation").as_array(),
        },
        "read-outcome",
        "idem-read",
    )?;
    assert!(matches!(
        fixture.host.control(conflict, || Ok(())),
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-008"))
    ));

    let mut wrong_fence = external_admission(
        &fixture.host,
        NduControlRequestV1::Selection {
            objective: *digest("objective").as_array(),
            subject: *digest("subject").as_array(),
        },
        "wrong-fence",
        "idem-wrong-fence",
    )?;
    if let NduControlRequestV1::ExternalAdmissionV2 { fence_digest, .. } = &mut wrong_fence {
        *fence_digest = *digest("different-live-fence").as_array();
    }
    assert!(matches!(
        fixture.host.control(wrong_fence, || Ok(())),
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-005"))
    ));

    let mut payload_drift = external_admission(
        &fixture.host,
        NduControlRequestV1::Selection {
            objective: *digest("objective").as_array(),
            subject: *digest("subject").as_array(),
        },
        "payload-drift",
        "idem-payload-drift",
    )?;
    if let NduControlRequestV1::ExternalAdmissionV2 { request, .. } = &mut payload_drift {
        *request = Box::new(NduControlRequestV1::Outcome {
            identity: *digest("substituted-payload").as_array(),
        });
    }
    assert!(matches!(
        fixture.host.control(payload_drift, || Ok(())),
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-006"))
    ));
    Ok(())
}

#[test]
fn admitted_failure_requires_reconciliation_before_retry() -> TestResult<()> {
    let fixture = fixture()?;
    let failed = external_admission(
        &fixture.host,
        NduControlRequestV1::Prepare {
            mutation: NduMutationV1 {
                operation: NduMutationOperationV1::AppendPreference,
                identity: *digest("prepare-identity").as_array(),
                objective: *digest("objective").as_array(),
                subject: *digest("subject").as_array(),
                projection: *digest("prepare-projection").as_array(),
                expected_predecessor: None,
            },
            expected_head: *digest("wrong-journal-head").as_array(),
        },
        "failed-prepare",
        "idem-failed-prepare",
    )?;
    let retry = failed.clone();
    assert!(matches!(
        fixture.host.control(failed, || Ok(())),
        Err(AgentdNduOwnerErrorV1::Owner(
            NduOwnerError::JournalHeadMismatch
        ))
    ));
    assert!(matches!(
        fixture.host.control(retry, || Ok(())),
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-010"))
    ));
    Ok(())
}

#[test]
fn named_host_exposes_read_only_metrics_without_a_final_use_grant() -> TestResult<()> {
    let fixture = fixture()?;
    let request = NduControlRequestV1::MetricsV1;
    assert!(!request.requires_mutation_admission());
    let first_head = fixture
        .host
        .control(NduControlRequestV1::Context, || Ok(()))?;
    let result = fixture.host.control(request, || Ok(()))?;
    assert!(matches!(
        result,
        NduControlResultV1::MetricsV1 {
            journal_bytes: Some(_),
            backup_age_seconds: None,
            ..
        }
    ));
    let final_head = fixture
        .host
        .control(NduControlRequestV1::Context, || Ok(()))?;
    assert_eq!(first_head, final_head);
    assert!(
        fixture
            .host
            .control(NduControlRequestV1::MetricsV1, || Err(
                AgentdNduOwnerErrorV1::NotReady
            ))
            .is_err()
    );
    Ok(())
}

#[test]
fn external_deadline_is_rechecked_after_owner_wait_before_replay() -> TestResult<()> {
    let fixture = fixture()?;
    let request = external_admission(
        &fixture.host,
        NduControlRequestV1::Context,
        "expire-at-lock",
        "expire-at-lock",
    )?;
    let (issued, deadline) = match &request {
        NduControlRequestV1::ExternalAdmissionV2 {
            issued_at_unix_ms,
            deadline_unix_ms,
            ..
        } => (*issued_at_unix_ms, *deadline_unix_ms),
        _ => return Err("expected external admission".into()),
    };
    let clock = std::cell::Cell::new(issued);
    let result = fixture.host.control_with_test_clock(
        request.clone(),
        || {
            clock.set(deadline + 1);
            Ok(())
        },
        || Ok(clock.get()),
    );
    assert!(matches!(
        result,
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-004"))
    ));
    // Reset only the deterministic test clock: no replay reservation was made.
    clock.set(issued);
    assert!(matches!(
        fixture
            .host
            .control_with_test_clock(request, || Ok(()), || Ok(clock.get()))?,
        NduControlResultV1::Context { .. }
    ));
    Ok(())
}

#[test]
fn external_deadline_is_rechecked_at_mutation_entry_without_effect() -> TestResult<()> {
    let mut fixture = fixture()?;
    let mutation = append("deadline-cut");
    let wire = NduMutationV1 {
        operation: NduMutationOperationV1::AppendPreference,
        identity: *digest("deadline-cut-append").as_array(),
        objective: *digest("objective").as_array(),
        subject: *digest("subject").as_array(),
        projection: *digest("deadline-cut-projection").as_array(),
        expected_predecessor: None,
    };
    let prepared = fixture.host.control(
        NduControlRequestV1::Prepare {
            mutation: wire.clone(),
            expected_head: [0; 32],
        },
        || Ok(()),
    )?;
    let binding = match prepared {
        NduControlResultV1::Prepared { binding, .. } => binding,
        _ => return Err("expected prepared binding".into()),
    };
    let mut grant = fixture.sign(&mutation, "deadline-cut-grant")?;
    grant.grant.binding = binding;
    grant.signature = fixture
        .signing
        .sign(&grant.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    let request = external_admission(
        &fixture.host,
        NduControlRequestV1::Apply {
            mutation: wire,
            expected_head: [0; 32],
            grant: Box::new(grant),
        },
        "expire-at-effect",
        "expire-at-effect",
    )?;
    let (issued, deadline) = match &request {
        NduControlRequestV1::ExternalAdmissionV2 {
            issued_at_unix_ms,
            deadline_unix_ms,
            ..
        } => (*issued_at_unix_ms, *deadline_unix_ms),
        _ => return Err("expected external admission".into()),
    };
    let clock = std::cell::Cell::new(issued);
    let calls = std::cell::Cell::new(0);
    let result = fixture.host.control_with_test_clock(
        request.clone(),
        || {
            calls.set(calls.get() + 1);
            if calls.get() == 2 {
                clock.set(deadline + 1);
            }
            Ok(())
        },
        || Ok(clock.get()),
    );
    assert_eq!(calls.get(), 2);
    assert!(matches!(
        result,
        Err(AgentdNduOwnerErrorV1::Owner(NduOwnerError::InvalidContext(
            "external admission expired at mutation entry"
        )))
    ));
    let outcome = fixture.host.control(
        NduControlRequestV1::Outcome {
            identity: *digest("deadline-cut-append").as_array(),
        },
        || Ok(()),
    )?;
    assert_eq!(outcome, NduControlResultV1::Outcome { entry: None });
    // A reserved operation is never re-admitted merely by resetting test time.
    clock.set(issued);
    assert!(matches!(
        fixture
            .host
            .control_with_test_clock(request, || Ok(()), || Ok(clock.get())),
        Err(AgentdNduOwnerErrorV1::Admission("NDU-ADMIT-010"))
    ));
    Ok(())
}

#[test]
fn metrics_v2_reports_storage_health_and_does_not_block_on_owner() -> TestResult<()> {
    let fixture = fixture()?;
    let result = fixture
        .host
        .control(NduControlRequestV1::MetricsV2 {}, || Ok(()))?;
    assert!(matches!(
        result,
        NduControlResultV1::MetricsV2 {
            storage_ready: Some(true),
            filesystem_profile: Some(_),
            memory_fallback_count: 0,
            backup_age_seconds: None,
            ..
        }
    ));
    let held = fixture
        .host
        .owner
        .lock()
        .map_err(|_| "poisoned test owner")?;
    let result = fixture
        .host
        .control(NduControlRequestV1::MetricsV2 {}, || Ok(()))?;
    assert!(matches!(
        result,
        NduControlResultV1::MetricsV2 {
            storage_ready: None,
            ..
        }
    ));
    drop(held);
    assert!(
        fixture
            .host
            .control(NduControlRequestV1::MetricsV2 {}, || Err(
                AgentdNduOwnerErrorV1::NotReady
            ))
            .is_err()
    );
    Ok(())
}
