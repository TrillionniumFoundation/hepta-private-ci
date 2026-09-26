use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::ContractRegistryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::IdProfileV1;
use codex_hepta_types::NumericProfileDefinitionV1;
use codex_hepta_types::NumericProfileV1;
use codex_hepta_types::NumericSignalSchemaV1;
use codex_hepta_types::NumericSignalV1;
use codex_hepta_types::RegistryDefinitionV1;
use codex_hepta_types::RegistryKindV1;
use codex_hepta_types::SignalUnitV1;
use codex_hepta_types::StableId;
use codex_hepta_types::validate_id;
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
use crate::NduNumericAdmissionErrorV1;
use crate::NduNumericRegistryV1;
use crate::NduProjectionKindV1;
use crate::RequiredOrganSet;
use crate::UtilityContribution;
use crate::UtilityProfile;

#[expect(
    clippy::expect_used,
    reason = "required setup assertions in a cfg(test) fixture, never a production path"
)]
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

#[expect(
    clippy::expect_used,
    reason = "required setup assertions in a cfg(test) fixture, never a production path"
)]
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

#[expect(
    clippy::expect_used,
    reason = "required setup assertions in a cfg(test) fixture, never a production path"
)]
fn numeric_registry() -> (NduNumericRegistryV1, Digest32) {
    let normalization = RegistryDefinitionV1::new(
        RegistryKindV1::Normalization,
        validate_id("normalization:ndu-owner-v1", IdProfileV1::Normalization)
            .expect("normalization ID"),
        1,
        "unit=utility;source=ppm;target=signed-q32-nearest-ties-even-v1",
    )
    .expect("normalization definition");
    let normalization_digest = normalization.digest();
    let registry = ContractRegistryV1::new_with_numeric_profiles(
        vec![normalization],
        vec![
            NumericProfileDefinitionV1::canonical(NumericProfileV1::HnmfPpmTowardZero)
                .expect("source profile"),
            NumericProfileDefinitionV1::canonical(NumericProfileV1::SignedQ32NearestTiesEven)
                .expect("target profile"),
        ],
    )
    .expect("numeric registry");
    (
        NduNumericRegistryV1::new(registry).expect("NDU numeric registry"),
        normalization_digest,
    )
}

fn numeric_signal(normalization_digest: Digest32) -> NumericSignalV1 {
    NumericSignalV1 {
        schema: NumericSignalSchemaV1 {
            profile: NumericProfileV1::HnmfPpmTowardZero,
            unit: SignalUnitV1::Utility,
            shape: vec![1],
            minimum_raw: -1_000_000,
            maximum_raw: 1_000_000,
            normalization_digest,
        },
        values: vec![750_000],
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

#[expect(
    clippy::expect_used,
    reason = "required setup assertions in a cfg(test) fixture, never a production path"
)]
fn fixture() -> Fixture {
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

    let owner = NduAuthenticatedOwnerV1::open(
        store_dir.path(),
        authority.clone(),
        NduOwnerContextV1 {
            principal_id: id("agentd-principal"),
            owner_id: id("utility.ndu"),
            host_generation: 7,
            principal_scope_digest: digest("principal-scope"),
            fence_digest: digest("host-fence"),
            revocation_frontier_digest: digest("revocation-frontier"),
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

#[expect(
    clippy::expect_used,
    reason = "required setup assertions in a cfg(test) fixture, never a production path"
)]
fn fixture_with_numeric_registry() -> (Fixture, Digest32) {
    let store_dir = tempfile::tempdir().expect("store tempdir");
    let authority_dir = tempfile::tempdir().expect("authority tempdir");
    std::fs::set_permissions(store_dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private store permissions");
    std::fs::set_permissions(authority_dir.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private authority permissions");

    let signing = SigningKey::from_bytes(&[92; 32]);
    let authority = codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "ndu-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )
    .expect("authority");
    let (numeric_registry, normalization_digest) = numeric_registry();
    let mut production_policy = policy();
    production_policy
        .utility_profile
        .normalization_manifest_digest = normalization_digest;
    let owner = NduAuthenticatedOwnerV1::open_with_numeric_registry(
        store_dir.path(),
        authority.clone(),
        NduOwnerContextV1 {
            principal_id: id("agentd-principal"),
            owner_id: id("utility.ndu"),
            host_generation: 8,
            principal_scope_digest: digest("principal-scope"),
            fence_digest: digest("host-fence"),
            revocation_frontier_digest: digest("revocation-frontier"),
        },
        production_policy,
        numeric_registry,
    )
    .expect("registered authenticated owner");
    (
        Fixture {
            owner,
            authority,
            signing,
            next_nonce: 1,
            _store_dir: store_dir,
            _authority_dir: authority_dir,
        },
        normalization_digest,
    )
}

impl Fixture {
    #[expect(
        clippy::expect_used,
        reason = "test signing fixture must fail immediately on invalid fixture state"
    )]
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

#[test]
fn owner_freezes_policy_and_evaluates_without_caller_supplied_relaxations() {
    let fixture = fixture();
    let receipt = fixture.owner.evaluate(contributions()).expect("evaluation");
    assert!(!fixture.owner.production_policy_digest().is_zero());
    assert_eq!(receipt.base.advisory_recommendation, Some(id("work")));
}

#[test]
fn authenticated_owner_freezes_and_consumes_registered_numeric_generation() {
    let (fixture, normalization_digest) = fixture_with_numeric_registry();
    let registry_digest = fixture
        .owner
        .numeric_registry_digest()
        .expect("configured registry digest");
    let admitted = fixture
        .owner
        .admit_utility_signal(&numeric_signal(normalization_digest))
        .expect("registered utility admission");
    assert_eq!(admitted.registry_digest, registry_digest);
    assert_eq!(admitted.admission.registry_digest, registry_digest);
    assert_eq!(admitted.axis_values.len(), 1);
    assert_eq!(admitted.axis_values[0].axis, id("success"));
    assert_eq!(admitted.axis_values[0].value.raw(), 3_i64 << 30);
    assert!(!admitted.admission.admission_digest.is_zero());
}

#[test]
fn unconfigured_owner_cannot_claim_registry_admission() {
    let fixture = fixture();
    assert!(fixture.owner.numeric_registry_digest().is_none());
    assert!(matches!(
        fixture
            .owner
            .admit_utility_signal(&numeric_signal(digest("production-utility-normalization"))),
        Err(NduOwnerError::NumericAdmission(
            NduNumericAdmissionErrorV1::RegistryNotConfigured
        ))
    ));
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

#[expect(
    clippy::expect_used,
    reason = "required setup assertions in a cfg(test) fixture, never a production path"
)]
fn fixture_with_registry(registry: NduNumericRegistryV1, normalization: Digest32) -> Fixture {
    let mut fixture = fixture();
    let directory = tempfile::tempdir().expect("registered owner root");
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))
        .expect("private owner root");
    let mut bound_policy = policy();
    bound_policy.utility_profile.normalization_manifest_digest = normalization;
    let owner = NduAuthenticatedOwnerV1::open_with_numeric_registry(
        directory.path(),
        fixture.authority.clone(),
        fixture.owner.context().clone(),
        bound_policy,
        registry,
    )
    .expect("configured owner");
    fixture.owner = owner;
    fixture._store_dir = directory;
    fixture
}

#[test]
fn ordinary_owner_evaluate_consumes_registered_admission_and_binds_support() {
    let (registry, normalization) = numeric_registry();
    let fixture = fixture_with_registry(registry, normalization);
    let source = contributions();
    let plain = crate::evaluate_candidates_with_policy(
        source.clone(),
        fixture.owner.policy.utility_profile.clone(),
        fixture.owner.policy.scalarization.clone(),
        fixture.owner.policy.evaluation_policy.clone(),
    )
    .expect("plain arithmetic evaluation");
    let admitted = fixture
        .owner
        .evaluate(source.clone())
        .expect("ordinary owner evaluation");
    assert_eq!(admitted.base.evaluated_candidates.len(), 2);
    assert_eq!(
        admitted.base.advisory_recommendation,
        plain.base.advisory_recommendation
    );
    assert_ne!(admitted.evaluation_digest_v2, plain.evaluation_digest_v2);
    for (registered, raw) in admitted
        .base
        .evaluated_candidates
        .iter()
        .zip(&plain.base.evaluated_candidates)
    {
        assert_eq!(registered.utility, raw.utility);
        assert_ne!(registered.support_digest, raw.support_digest);
    }
    assert_eq!(
        admitted,
        fixture
            .owner
            .evaluate(source)
            .expect("deterministic repeat")
    );
}

#[test]
fn ordinary_owner_evaluate_rejects_missing_registry_definition() {
    let (registry, _) = numeric_registry();
    let fixture = fixture_with_registry(registry, digest("unregistered-normalization"));
    assert!(matches!(
        fixture.owner.evaluate(contributions()),
        Err(NduOwnerError::NumericAdmission(
            NduNumericAdmissionErrorV1::Conversion(
                codex_hepta_types::NumericConversionError::UnknownNormalization
            )
        ))
    ));
}

#[test]
fn ordinary_owner_admission_does_not_launder_empty_support_or_wrong_axes() {
    let (registry, normalization) = numeric_registry();
    let fixture = fixture_with_registry(registry, normalization);
    let mut source = contributions();
    source.contributions[0].support_digest = Digest32::ZERO;
    assert!(matches!(
        fixture.owner.evaluate(source),
        Err(NduOwnerError::Ndu(
            crate::NduError::EmptySupportDigest { .. }
        ))
    ));
    let mut source = contributions();
    source.contributions[0].utility[0].axis = id("substituted-axis");
    assert!(matches!(
        fixture.owner.evaluate(source),
        Err(NduOwnerError::NumericAdmission(
            NduNumericAdmissionErrorV1::AxisIdentityMismatch
        ))
    ));
}
