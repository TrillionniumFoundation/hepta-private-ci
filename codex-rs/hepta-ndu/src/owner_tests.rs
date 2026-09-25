#![expect(
    clippy::expect_used,
    reason = "test fixture construction must fail immediately with a precise setup label"
)]

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::NduAuthenticatedOwnerV1;
use super::NduOwnerContextV1;
use super::NduOwnerError;
use super::NduOwnerMutationV1;
use super::NduProductionPolicyV1;
use crate::AggregationOperator;
use crate::AxisAggregationRule;
use crate::AxisDirection;
use crate::AxisLimit;
use crate::AxisValue;
use crate::ContributionSet;
use crate::EvaluationPolicyV1;
use crate::FeasibilityPosture;
use crate::NduProjectionJournalError;
use crate::NduProjectionKindV1;
use crate::NduProjectionStoreError;
use crate::RequiredOrganSet;
use crate::UtilityContribution;
use crate::UtilityProfile;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn policy() -> NduProductionPolicyV1 {
    let utility_profile = UtilityProfile {
        profile_id: id("production-utility-v1"),
        axis_registry_digest: digest("production-utility-axis-registry"),
        normalization_manifest_digest: digest("production-utility-normalization"),
        dimensions: vec![(id("success"), AxisDirection::Maximize)],
        risk_ceilings: vec![AxisLimit {
            axis: id("privacy-risk"),
            maximum: FixedQ32::ZERO,
        }],
        resource_ceilings: vec![AxisLimit {
            axis: id("compute"),
            maximum: FixedQ32::ONE,
        }],
        required_organs: RequiredOrganSet {
            organ_ids: vec![id("planner")],
        },
    };
    NduProductionPolicyV1 {
        evaluation_policy: EvaluationPolicyV1 {
            policy_id: id("production-policy-v1"),
            utility_rules: vec![AxisAggregationRule {
                axis: id("success"),
                operator: AggregationOperator::Sum,
            }],
            risk_rules: vec![AxisAggregationRule {
                axis: id("privacy-risk"),
                operator: AggregationOperator::Maximum,
            }],
            resource_rules: vec![AxisAggregationRule {
                axis: id("compute"),
                operator: AggregationOperator::Sum,
            }],
            uncertainty_rules: vec![AxisAggregationRule {
                axis: id("success"),
                operator: AggregationOperator::Maximum,
            }],
            pareto_absolute_tolerances: vec![AxisValue {
                axis: id("success"),
                value: FixedQ32::ZERO,
            }],
        },
        utility_profile,
        scalarization: None,
    }
}

fn contributions() -> ContributionSet {
    let objective = digest("objective");
    let generation = Generation::new(1).expect("generation");
    ContributionSet {
        objective_digest: objective,
        generation,
        contributions: vec![
            UtilityContribution {
                candidate_id: id("abstain"),
                organ_id: id("planner"),
                objective_digest: objective,
                generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: id("success"),
                    value: FixedQ32::ZERO,
                }],
                risk: vec![AxisValue {
                    axis: id("privacy-risk"),
                    value: FixedQ32::ZERO,
                }],
                resource: vec![AxisValue {
                    axis: id("compute"),
                    value: FixedQ32::ZERO,
                }],
                uncertainty: vec![AxisValue {
                    axis: id("success"),
                    value: FixedQ32::ZERO,
                }],
                support_digest: digest("abstain-support"),
            },
            UtilityContribution {
                candidate_id: id("work"),
                organ_id: id("planner"),
                objective_digest: objective,
                generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: id("success"),
                    value: FixedQ32::ONE,
                }],
                risk: vec![AxisValue {
                    axis: id("privacy-risk"),
                    value: FixedQ32::ZERO,
                }],
                resource: vec![AxisValue {
                    axis: id("compute"),
                    value: FixedQ32::ONE,
                }],
                uncertainty: vec![AxisValue {
                    axis: id("success"),
                    value: FixedQ32::ZERO,
                }],
                support_digest: digest("work-support"),
            },
        ],
    }
}

struct Fixture {
    owner: NduAuthenticatedOwnerV1,
    authority: codex_hepta_contracts::FinalUseAuthority,
    signing: SigningKey,
    next_nonce: u8,
    _store_dir: tempfile::TempDir,
    _authority_dir: tempfile::TempDir,
}

fn fixture() -> Fixture {
    fixture_with_host_generation(7)
}

fn fixture_with_host_generation(host_generation: u64) -> Fixture {
    let store_dir = tempfile::tempdir().expect("store tempdir");
    let authority_dir = tempfile::tempdir().expect("authority tempdir");
    std::fs::set_permissions(store_dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private store permissions");
    std::fs::set_permissions(authority_dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private authority permissions");

    let signing = SigningKey::from_bytes(&[91; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "ndu-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        head,
    )
    .expect("authority");

    let revocation_frontier_digest = Digest32::from_array(
        authority
            .revocation_head_sha256()
            .expect("current revocation head digest"),
    );
    let owner = NduAuthenticatedOwnerV1::open(
        store_dir.path(),
        authority.clone(),
        NduOwnerContextV1 {
            principal_id: id("agentd-principal"),
            owner_id: id("utility.ndu"),
            host_generation,
            principal_scope_digest: digest("principal-scope"),
            fence_digest: digest("host-fence"),
            revocation_frontier_digest,
        },
        policy(),
    )
    .expect("authenticated owner");

    Fixture {
        owner,
        authority,
        signing,
        next_nonce: 1,
        _store_dir: store_dir,
        _authority_dir: authority_dir,
    }
}

impl Fixture {
    fn sign(&mut self, mutation: &NduOwnerMutationV1, grant_id: &str) -> SignedFinalUseGrant {
        let binding = self.owner.final_use_binding(mutation).expect("binding");
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_millis() as u64;
        let mut nonce = [0_u8; 32];
        nonce[0] = self.next_nonce;
        self.next_nonce = self.next_nonce.checked_add(1).expect("nonce bound");
        let grant = FinalUseGrant {
            schema_version: 1,
            signer_id: "ndu-issuer".to_string(),
            authority_epoch: 1,
            grant_id: grant_id.to_string(),
            nonce,
            binding,
            not_before_unix_ms: now.saturating_sub(1_000),
            expires_at_unix_ms: now.saturating_add(60_000),
        };
        let signature = self
            .signing
            .sign(&grant.signing_bytes().expect("signing bytes"));
        SignedFinalUseGrant {
            grant,
            signature: signature.to_bytes().to_vec(),
        }
    }
}

fn append_mutation(label: &str) -> NduOwnerMutationV1 {
    NduOwnerMutationV1::AppendProjection {
        kind: NduProjectionKindV1::Preference,
        identity_digest: digest(&format!("{label}-identity")),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        projection_digest: digest(&format!("{label}-projection")),
    }
}

fn select_mutation(
    label: &str,
    expected_predecessor: Option<Digest32>,
    projection_digest: Digest32,
) -> NduOwnerMutationV1 {
    NduOwnerMutationV1::SelectProjection {
        identity_digest: digest(&format!("{label}-identity")),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        expected_predecessor,
        projection_digest,
    }
}

#[test]
fn owner_freezes_policy_and_evaluates_without_caller_supplied_relaxations() {
    let fixture = fixture();
    let receipt = fixture.owner.evaluate(contributions()).expect("evaluation");
    let replay = fixture.owner.evaluate(contributions()).expect("replay");
    assert!(!fixture.owner.production_policy_digest().is_zero());
    assert_eq!(
        receipt.evaluation().base.advisory_recommendation,
        Some(id("work"))
    );
    assert!(!receipt.source_context_digest().is_zero());
    assert!(!receipt.receipt_digest().is_zero());
    assert_eq!(receipt, replay, "same frozen owner context replays exactly");
}

#[test]
fn authenticated_evaluation_receipt_binds_the_original_owner_context() {
    let first = fixture_with_host_generation(7)
        .owner
        .evaluate(contributions())
        .expect("first evaluation");
    let second = fixture_with_host_generation(8)
        .owner
        .evaluate(contributions())
        .expect("second evaluation");

    assert_eq!(first.evaluation(), second.evaluation());
    assert_ne!(
        first.source_context_digest(),
        second.source_context_digest()
    );
    assert_ne!(first.receipt_digest(), second.receipt_digest());
}

#[test]
fn exact_signed_binding_is_required_for_durable_mutation() {
    let mut fixture = fixture();
    let first = append_mutation("first");
    let signed = fixture.sign(&first, "grant-first");

    let second = append_mutation("second");
    assert!(matches!(
        fixture.owner.apply_mutation(&signed, second),
        Err(NduOwnerError::Authority(
            codex_hepta_contracts::FinalUseError::BindingMismatch
        ))
    ));

    let signed = fixture.sign(&first, "grant-first-correct");
    fixture
        .owner
        .apply_mutation(&signed, first)
        .expect("authorized append");
}

#[test]
fn selection_grant_binds_expected_predecessor_and_stale_selection_rejects() {
    let mut fixture = fixture();
    let first = append_mutation("first");
    let first_projection = digest("first-projection");
    let signed = fixture.sign(&first, "grant-append-first");
    fixture
        .owner
        .apply_mutation(&signed, first)
        .expect("append first");

    let second = append_mutation("second");
    let second_projection = digest("second-projection");
    let signed = fixture.sign(&second, "grant-append-second");
    fixture
        .owner
        .apply_mutation(&signed, second)
        .expect("append second");

    let select_first = select_mutation("select-first", None, first_projection);
    let signed = fixture.sign(&select_first, "grant-select-first");
    fixture
        .owner
        .apply_mutation(&signed, select_first)
        .expect("select first");

    let stale = select_mutation("select-second-stale", None, second_projection);
    let stale_signed = fixture.sign(&stale, "grant-select-second-stale");
    let current = select_mutation(
        "select-second-stale",
        Some(first_projection),
        second_projection,
    );
    assert!(matches!(
        fixture.owner.apply_mutation(&stale_signed, current),
        Err(NduOwnerError::Authority(
            codex_hepta_contracts::FinalUseError::BindingMismatch
        ))
    ));
    assert!(matches!(
        fixture.owner.apply_mutation(&stale_signed, stale),
        Err(NduOwnerError::Store(NduProjectionStoreError::Journal(
            NduProjectionJournalError::SelectionPredecessorMismatch
        )))
    ));

    let current = select_mutation(
        "select-second-current",
        Some(first_projection),
        second_projection,
    );
    let signed = fixture.sign(&current, "grant-select-second-current");
    fixture
        .owner
        .apply_mutation(&signed, current)
        .expect("current predecessor selection");
    assert_eq!(
        fixture
            .owner
            .selected_projection_digest(digest("objective"), digest("subject"))
            .expect("selected query"),
        Some(second_projection)
    );
}

#[test]
fn live_revocation_frontier_blocks_previously_signed_write() {
    let mut fixture = fixture();
    let mutation = append_mutation("revoked");
    let signed = fixture.sign(&mutation, "grant-revoked");

    let mut revoked = BTreeSet::new();
    revoked.insert("grant-revoked".to_string());
    fixture
        .authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 1,
            revision: 2,
            revoked_grant_ids: revoked,
        })
        .expect("advance revocations");

    assert!(matches!(
        fixture.owner.apply_mutation(&signed, mutation),
        Err(NduOwnerError::Authority(
            codex_hepta_contracts::FinalUseError::Revoked
        ))
    ));
}

#[test]
fn unrelated_head_advance_rejects_a_stale_owner_context() {
    let mut fixture = fixture();
    let mutation = append_mutation("frontier-advanced");
    let signed = fixture.sign(&mutation, "grant-frontier-advanced");
    fixture
        .authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 1,
            revision: 2,
            revoked_grant_ids: BTreeSet::new(),
        })
        .expect("advance unrelated head");
    assert!(matches!(
        fixture.owner.apply_mutation(&signed, mutation),
        Err(NduOwnerError::RevocationFrontierMismatch)
    ));
}

#[test]
fn head_bound_product_selection_rejects_aba_without_consuming_grant()
-> Result<(), Box<dyn std::error::Error>> {
    let mut fixture = fixture();
    for label in ["first", "second"] {
        let mutation = append_mutation(label);
        let signed = fixture.sign(&mutation, &format!("append-{label}"));
        fixture.owner.apply_mutation(&signed, mutation)?;
    }
    let first = digest("first-projection");
    let second = digest("second-projection");
    let initial = select_mutation("initial-a", None, first);
    let grant = fixture.sign(&initial, "initial-a");
    fixture.owner.apply_mutation(&grant, initial)?;
    let old_head = fixture.owner.journal_head_digest()?;
    let stale = select_mutation("stale-b", Some(first), second);
    let mut stale_grant = fixture.sign(&stale, "stale-b");
    stale_grant.grant.binding = fixture.owner.final_use_binding_at_head(&stale, old_head)?;
    stale_grant.signature = fixture
        .signing
        .sign(&stale_grant.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    for (label, previous, selected) in [("current-b", first, second), ("returned-a", second, first)]
    {
        let mutation = select_mutation(label, Some(previous), selected);
        let grant = fixture.sign(&mutation, label);
        fixture.owner.apply_mutation(&grant, mutation)?;
    }
    assert_eq!(
        fixture
            .owner
            .selected_projection_digest(digest("objective"), digest("subject"))?,
        Some(first)
    );
    assert_ne!(fixture.owner.journal_head_digest()?, old_head);
    let capacity = fixture.authority.capacity()?;
    assert!(matches!(
        fixture
            .owner
            .apply_mutation_at_head(&stale_grant, stale, old_head),
        Err(NduOwnerError::JournalHeadMismatch)
    ));
    assert_eq!(fixture.authority.capacity()?, capacity);
    Ok(())
}

#[test]
fn head_bound_commit_can_be_queried_after_lost_ack_and_reopen()
-> Result<(), Box<dyn std::error::Error>> {
    let mut fixture = fixture();
    let mutation = append_mutation("lost-ack");
    let head = fixture.owner.journal_head_digest()?;
    let mut grant = fixture.sign(&mutation, "lost-ack");
    grant.grant.binding = fixture.owner.final_use_binding_at_head(&mutation, head)?;
    grant.signature = fixture
        .signing
        .sign(&grant.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    let entry = fixture
        .owner
        .apply_mutation_at_head(&grant, mutation.clone(), head)?;
    assert!(matches!(
        fixture.owner.apply_mutation_at_head(&grant, mutation, head),
        Err(NduOwnerError::JournalHeadMismatch)
    ));
    let current_head = fixture.owner.journal_head_digest()?;
    let capacity = fixture.authority.capacity()?;
    assert!(matches!(
        fixture
            .owner
            .apply_mutation_at_head(&grant, append_mutation("lost-ack"), current_head),
        Err(NduOwnerError::OperationAlreadyCommitted)
    ));
    assert_eq!(fixture.authority.capacity()?, capacity);
    let context = fixture.owner.context().clone();
    let root = fixture._store_dir.path().to_path_buf();
    drop(fixture.owner);
    let reopened = NduAuthenticatedOwnerV1::open(root, fixture.authority, context, policy())?;
    assert_eq!(
        reopened.mutation_result(entry.identity_digest)?,
        Some(entry)
    );
    Ok(())
}

#[test]
fn durable_owner_binding_rejects_policy_and_principal_substitution()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = fixture();
    let context = fixture.owner.context().clone();
    let root = fixture._store_dir.path().to_path_buf();
    drop(fixture.owner);
    let mut changed = policy();
    changed.utility_profile.profile_id = id("substituted-policy");
    assert!(matches!(
        NduAuthenticatedOwnerV1::open(&root, fixture.authority.clone(), context.clone(), changed),
        Err(NduOwnerError::InvalidContext(_))
    ));
    let mut wrong = context.clone();
    wrong.principal_id = id("another-principal");
    assert!(matches!(
        NduAuthenticatedOwnerV1::open(&root, fixture.authority.clone(), wrong, policy()),
        Err(NduOwnerError::InvalidContext(_))
    ));
    let mut next_generation = context;
    next_generation.host_generation += 1;
    next_generation.fence_digest = digest("next-generation-fence");
    let reopened =
        NduAuthenticatedOwnerV1::open(root, fixture.authority, next_generation, policy())?;
    assert_eq!(reopened.journal_head_digest()?, Digest32::ZERO);
    Ok(())
}

#[test]
fn stale_direct_owner_cannot_publish_an_authenticated_evaluation()
-> Result<(), Box<dyn std::error::Error>> {
    let fixture = fixture();
    fixture.authority.update_revocations(FinalUseRevocations {
        authority_epoch: 1,
        revision: 2,
        revoked_grant_ids: BTreeSet::new(),
    })?;
    assert!(matches!(
        fixture.owner.evaluate(contributions()),
        Err(NduOwnerError::RevocationFrontierMismatch)
    ));
    Ok(())
}

#[test]
fn product_lifecycle_is_rechecked_at_actual_mutation_entry()
-> Result<(), Box<dyn std::error::Error>> {
    let mut fixture = fixture();
    let mutation = append_mutation("late-fence");
    let identity = mutation.identity_digest();
    let head = fixture.owner.journal_head_digest()?;
    let mut grant = fixture.sign(&mutation, "late-fence");
    grant.grant.binding = fixture.owner.final_use_binding_at_head(&mutation, head)?;
    grant.signature = fixture
        .signing
        .sign(&grant.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    assert!(matches!(
        fixture
            .owner
            .apply_mutation_at_head_guarded(&grant, mutation, head, || Err(
                NduOwnerError::InvalidContext("product lifecycle fence")
            )),
        Err(NduOwnerError::InvalidContext("product lifecycle fence"))
    ));
    assert_eq!(fixture.owner.journal_head_digest()?, head);
    assert_eq!(fixture.owner.mutation_result(identity)?, None);
    Ok(())
}

#[test]
fn pending_owner_binding_recovers_only_an_empty_store() -> Result<(), Box<dyn std::error::Error>> {
    let fixture = fixture();
    let context = fixture.owner.context().clone();
    let root = fixture._store_dir.path().to_path_buf();
    drop(fixture.owner);
    std::fs::remove_file(root.join("owner-binding.v1"))?;
    std::fs::write(root.join("owner-binding.v1.tmp"), b"interrupted-bootstrap")?;
    let reopened = NduAuthenticatedOwnerV1::open(&root, fixture.authority, context, policy())?;
    assert_eq!(reopened.journal_head_digest()?, Digest32::ZERO);
    assert!(!root.join("owner-binding.v1.tmp").exists());
    assert_eq!(std::fs::metadata(root.join("owner-binding.v1"))?.len(), 32);
    Ok(())
}

#[test]
fn missing_owner_binding_never_adopts_committed_history() -> Result<(), Box<dyn std::error::Error>>
{
    let mut fixture = fixture();
    let mutation = append_mutation("bound-history");
    let grant = fixture.sign(&mutation, "bound-history");
    fixture.owner.apply_mutation(&grant, mutation)?;
    let context = fixture.owner.context().clone();
    let root = fixture._store_dir.path().to_path_buf();
    drop(fixture.owner);
    std::fs::remove_file(root.join("owner-binding.v1"))?;
    assert!(matches!(
        NduAuthenticatedOwnerV1::open(root, fixture.authority, context, policy()),
        Err(NduOwnerError::InvalidContext(
            "unbound historical store requires migration"
        ))
    ));
    Ok(())
}

#[test]
fn mutation_effect_fences_authority_updates_until_durable_entry_returns()
-> Result<(), Box<dyn std::error::Error>> {
    let mut fixture = fixture();
    let mutation = append_mutation("effect-fence");
    let identity = mutation.identity_digest();
    let head = fixture.owner.journal_head_digest()?;
    let mut grant = fixture.sign(&mutation, "effect-fence");
    grant.grant.binding = fixture.owner.final_use_binding_at_head(&mutation, head)?;
    grant.signature = fixture
        .signing
        .sign(&grant.grant.signing_bytes()?)
        .to_bytes()
        .to_vec();
    let authority = fixture.authority.clone();
    let update = FinalUseRevocations {
        authority_epoch: 1,
        revision: 2,
        revoked_grant_ids: BTreeSet::from(["effect-fence".to_string()]),
    };
    let entry = fixture
        .owner
        .apply_mutation_at_head_guarded(&grant, mutation, head, || {
            assert_eq!(
                authority.update_revocations(update.clone()),
                Err(FinalUseError::DispatchInProgress)
            );
            Ok(())
        })?;
    assert_eq!(fixture.owner.mutation_result(identity)?, Some(entry));
    authority.update_revocations(update)?;
    assert!(matches!(
        fixture.owner.evaluate(contributions()),
        Err(NduOwnerError::RevocationFrontierMismatch)
    ));
    Ok(())
}
