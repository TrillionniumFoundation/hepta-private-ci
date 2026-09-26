use std::collections::BTreeSet;
use std::fmt::Debug;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

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
use crate::NduProjectionKindV1;
use crate::RequiredOrganSet;
use crate::UtilityContribution;
use crate::UtilityProfile;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_some<T>(value: Option<T>, context: &str) -> T {
    match value {
        Some(value) => value,
        None => panic!("missing expected value: {context}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
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
    let generation = must(Generation::new(1));
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
    let store_dir = must(tempfile::tempdir());
    let authority_dir = must(tempfile::tempdir());
    must(std::fs::set_permissions(
        store_dir.path(),
        std::fs::Permissions::from_mode(0o700),
    ));
    must(std::fs::set_permissions(
        authority_dir.path(),
        std::fs::Permissions::from_mode(0o700),
    ));

    let signing = SigningKey::from_bytes(&[91; 32]);
    let head = FinalUseRevocations {
        authority_epoch: 1,
        revision: 1,
        revoked_grant_ids: BTreeSet::new(),
    };
    let authority = must(codex_hepta_contracts::FinalUseAuthority::open_state_dir(
        authority_dir.path(),
        "ndu-issuer".to_string(),
        signing.verifying_key().to_bytes(),
        head,
    ));

    let owner = must(NduAuthenticatedOwnerV1::open(
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
    ));

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
        let binding = must(self.owner.final_use_binding(mutation));
        let now = must(SystemTime::now().duration_since(UNIX_EPOCH)).as_millis() as u64;
        let mut nonce = [0_u8; 32];
        nonce[0] = self.next_nonce;
        self.next_nonce = must_some(self.next_nonce.checked_add(1), "nonce increment");
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
        let signature = self.signing.sign(&must(grant.signing_bytes()));
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
    let receipt = must(fixture.owner.evaluate(contributions()));
    assert!(!fixture.owner.production_policy_digest().is_zero());
    assert_eq!(receipt.base.advisory_recommendation, Some(id("work")));
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
    must(fixture.owner.apply_mutation(&signed, first));
}

#[test]
fn live_revocation_frontier_blocks_previously_signed_write() {
    let mut fixture = fixture();
    let mutation = append_mutation("revoked");
    let signed = fixture.sign(&mutation, "grant-revoked");

    let mut revoked = BTreeSet::new();
    revoked.insert("grant-revoked".to_string());
    must(fixture.authority.update_revocations(FinalUseRevocations {
        authority_epoch: 1,
        revision: 2,
        revoked_grant_ids: revoked,
    }));

    assert!(matches!(
        fixture.owner.apply_mutation(&signed, mutation),
        Err(NduOwnerError::Authority(
            codex_hepta_contracts::FinalUseError::Revoked
        ))
    ));
}
