use std::collections::BTreeSet;
use std::error::Error;
use std::os::unix::fs::PermissionsExt;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::ContractRegistryV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::NumericProfileDefinitionV1;
use codex_hepta_types::NumericProfileV1;
use codex_hepta_types::NumericSignalSchemaV1;
use codex_hepta_types::NumericSignalV1;
use codex_hepta_types::RegistryDefinitionV1;
use codex_hepta_types::RegistryKindV1;
use codex_hepta_types::SignalUnitV1;
use codex_hepta_types::StableId;
use codex_hepta_types::numeric_registry_v2::RegistrySnapshotIdentityV1;
use codex_hepta_types::numeric_registry_v2::rescale_signal_registered_receipt_v1;
use codex_hepta_types::numeric_registry_v2::rescale_signal_registered_v2;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::NduAuthenticatedOwnerV1;
use super::NduOwnerContextV1;
use super::NduOwnerError;
use super::NduProductionPolicyV1;
use crate::AggregationOperator;
use crate::AxisAggregationRule;
use crate::AxisDirection;
use crate::AxisValue;
use crate::ContributionSet;
use crate::EvaluationPolicyV1;
use crate::FeasibilityPosture;
use crate::NduNumericRegistryV1;
use crate::NduOwnerMutationV1;
use crate::RequiredOrganSet;
use crate::UtilityContribution;
use crate::UtilityProfile;
use crate::numeric_admission::utility_target_schema;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

fn id(value: &str) -> TestResult<StableId> {
    Ok(StableId::new(value)?)
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn unique_test_nonce(label: &str) -> TestResult<[u8; 32]> {
    static SEQUENCE: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let elapsed = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_nanos();
    let sequence = SEQUENCE.fetch_add(/*value*/ 1, std::sync::atomic::Ordering::Relaxed);
    let material = format!("{label}:{}:{elapsed}:{sequence}", std::process::id());
    Ok(*Digest32::of_bytes(material.as_bytes()).as_array())
}

struct Fixture {
    owner: NduAuthenticatedOwnerV1,
    registry: NduNumericRegistryV1,
    source: NumericSignalV1,
    authority: FinalUseAuthority,
    signing: SigningKey,
    root: tempfile::TempDir,
    _authority_root: tempfile::TempDir,
}

fn fixture(generation: u64) -> TestResult<Fixture> {
    let normalization = RegistryDefinitionV1::new(
        RegistryKindV1::Normalization,
        id("normalization:ndu-snapshot")?,
        /*version*/ 1,
        "unit=utility;scale=identity",
    )?;
    let normalization_digest = normalization.digest();
    let registry = NduNumericRegistryV1::new(ContractRegistryV1::new_with_numeric_profiles(
        vec![normalization],
        vec![
            NumericProfileDefinitionV1::canonical(NumericProfileV1::HnmfPpmTowardZero)?,
            NumericProfileDefinitionV1::canonical(NumericProfileV1::SignedQ32NearestTiesEven)?,
        ],
    )?)?;
    let policy = NduProductionPolicyV1 {
        utility_profile: UtilityProfile {
            profile_id: id("snapshot-utility")?,
            axis_registry_digest: digest("axes"),
            normalization_manifest_digest: normalization_digest,
            dimensions: vec![(id("success")?, AxisDirection::Maximize)],
            risk_ceilings: Vec::new(),
            resource_ceilings: Vec::new(),
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("planner")?],
            },
        },
        evaluation_policy: EvaluationPolicyV1 {
            policy_id: id("snapshot-policy")?,
            utility_rules: vec![AxisAggregationRule {
                axis: id("success")?,
                operator: AggregationOperator::Sum,
            }],
            risk_rules: Vec::new(),
            resource_rules: Vec::new(),
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
    };
    let root = tempfile::tempdir()?;
    let authority_root = tempfile::tempdir()?;
    for path in [root.path(), authority_root.path()] {
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(/*mode*/ 0o700))?;
    }
    let secret_key = [91; 32];
    let signing = SigningKey::from_bytes(&secret_key);
    let authority = FinalUseAuthority::open_state_dir(
        authority_root.path(),
        "ndu-snapshot-issuer".to_owned(),
        signing.verifying_key().to_bytes(),
        FinalUseRevocations {
            authority_epoch: 1,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
    )?;
    let snapshot =
        RegistrySnapshotIdentityV1::new(Generation::new(generation)?, registry.registry_digest())?;
    let owner = NduAuthenticatedOwnerV1::open_with_numeric_registry_snapshot(
        root.path(),
        authority.clone(),
        NduOwnerContextV1 {
            principal_id: id("agentd-principal")?,
            owner_id: id("utility.ndu")?,
            host_generation: 7,
            principal_scope_digest: digest("scope"),
            fence_digest: digest("fence"),
            revocation_frontier_digest: digest("revocations"),
        },
        policy,
        registry.clone(),
        snapshot,
    )?;
    let source = NumericSignalV1 {
        schema: NumericSignalSchemaV1 {
            profile: NumericProfileV1::HnmfPpmTowardZero,
            unit: SignalUnitV1::Utility,
            shape: vec![1],
            minimum_raw: -1_000_000,
            maximum_raw: 1_000_000,
            normalization_digest,
        },
        values: vec![750_000],
    };
    Ok(Fixture {
        owner,
        registry,
        source,
        authority,
        signing,
        root,
        _authority_root: authority_root,
    })
}

fn contributions() -> TestResult<ContributionSet> {
    let generation = Generation::new(/*value*/ 1)?;
    let objective_digest = digest("objective");
    let contributions = ["abstain", "work"]
        .into_iter()
        .map(|candidate| {
            Ok(UtilityContribution {
                candidate_id: id(candidate)?,
                organ_id: id("planner")?,
                objective_digest,
                generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: id("success")?,
                    value: FixedQ32::ONE,
                }],
                risk: Vec::new(),
                resource: Vec::new(),
                uncertainty: vec![AxisValue {
                    axis: id("success")?,
                    value: FixedQ32::ZERO,
                }],
                support_digest: digest(candidate),
            })
        })
        .collect::<TestResult<Vec<_>>>()?;
    Ok(ContributionSet {
        objective_digest,
        generation,
        contributions,
    })
}

#[test]
fn owner_v2_receipt_recomputes_against_independent_pin() -> TestResult {
    let fixture = fixture(/*generation*/ 7)?;
    let issued = fixture.owner.admit_utility_signal_v2(&fixture.source)?;
    let verified = fixture
        .owner
        .verify_utility_signal_v2(&fixture.source, issued.admission())?;
    assert_eq!(issued, verified);
    assert_eq!(
        fixture.owner.numeric_registry_snapshot(),
        Some(issued.admission().registry_snapshot())
    );
    let target = utility_target_schema(&fixture.owner.policy.utility_profile, &fixture.source)?;
    let (legacy_signal, legacy_receipt) = rescale_signal_registered_receipt_v1(
        &fixture.source,
        &target,
        fixture.registry.registry(),
    )?;
    assert_eq!(issued.signal(), &legacy_signal);
    assert_eq!(issued.admission().conversion(), &legacy_receipt.conversion);
    Ok(())
}

#[test]
fn owner_v2_rejects_self_valid_older_generation() -> TestResult {
    let old = fixture(/*generation*/ 7)?;
    let current = fixture(/*generation*/ 8)?;
    let issued = old.owner.admit_utility_signal_v2(&old.source)?;
    let target = utility_target_schema(&current.owner.policy.utility_profile, &current.source)?;
    issued
        .admission()
        .verify(&current.source, &target, current.registry.registry())?;
    assert!(matches!(
        current
            .owner
            .verify_utility_signal_v2(&current.source, issued.admission()),
        Err(NduOwnerError::InvalidContext("numeric snapshot receipt"))
    ));
    Ok(())
}

#[test]
fn owner_v2_rejects_same_generation_wrong_registry_and_changed_signal() -> TestResult {
    let fixture = fixture(/*generation*/ 7)?;
    let original = fixture.registry.registry();
    let mut definitions = original.entries().to_vec();
    definitions.push(RegistryDefinitionV1::new(
        RegistryKindV1::Schema,
        id("schema:extra")?,
        /*version*/ 1,
        "extra=definition",
    )?);
    let other = ContractRegistryV1::new_with_numeric_profiles(
        definitions,
        original.numeric_profiles().to_vec(),
    )?;
    let target = utility_target_schema(&fixture.owner.policy.utility_profile, &fixture.source)?;
    let (_, receipt) = rescale_signal_registered_v2(
        &fixture.source,
        &target,
        &other,
        Generation::new(/*value*/ 7)?,
    )?;
    assert!(
        fixture
            .owner
            .verify_utility_signal_v2(&fixture.source, &receipt)
            .is_err()
    );
    let issued = fixture.owner.admit_utility_signal_v2(&fixture.source)?;
    let mut substituted = fixture.source.clone();
    substituted.values[0] += 1;
    assert!(
        fixture
            .owner
            .verify_utility_signal_v2(&substituted, issued.admission())
            .is_err()
    );
    Ok(())
}

#[test]
fn invalid_snapshot_fails_before_opening_store() -> TestResult {
    let fixture = fixture(/*generation*/ 7)?;
    let root = fixture.root.path().join("must-not-open");
    let wrong =
        RegistrySnapshotIdentityV1::new(Generation::new(/*value*/ 7)?, digest("wrong registry"))?;
    let opened = NduAuthenticatedOwnerV1::open_with_numeric_registry_snapshot(
        &root,
        fixture.authority.clone(),
        fixture.owner.context().clone(),
        fixture.owner.policy.clone(),
        fixture.registry.clone(),
        wrong,
    );
    assert!(matches!(
        opened,
        Err(NduOwnerError::InvalidContext("numeric snapshot registry"))
    ));
    assert!(!root.exists());
    Ok(())
}

#[test]
fn explicit_v2_owner_cannot_silently_downgrade_and_legacy_stays_v1() -> TestResult {
    let fixture = fixture(/*generation*/ 7)?;
    assert!(matches!(
        fixture.owner.admit_utility_signal(&fixture.source),
        Err(NduOwnerError::InvalidContext(
            "V2 snapshot requires V2 admission"
        ))
    ));
    let root = tempfile::tempdir()?;
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(/*mode*/ 0o700))?;
    let legacy = NduAuthenticatedOwnerV1::open_with_numeric_registry(
        root.path(),
        fixture.authority.clone(),
        fixture.owner.context().clone(),
        fixture.owner.policy.clone(),
        fixture.registry.clone(),
    )?;
    assert_eq!(legacy.numeric_registry_snapshot(), None);
    assert!(legacy.admit_utility_signal_v2(&fixture.source).is_err());
    let old = legacy.admit_utility_signal(&fixture.source)?;
    let new = fixture.owner.admit_utility_signal_v2(&fixture.source)?;
    assert_eq!(&old.signal, new.signal());
    assert_eq!(old.axis_values.as_slice(), new.axis_values());
    Ok(())
}

#[test]
fn ordinary_evaluate_and_final_use_binding_commit_snapshot_generation() -> TestResult {
    let earlier = fixture(/*generation*/ 7)?;
    let later = fixture(/*generation*/ 8)?;
    assert_ne!(
        earlier.owner.production_policy_digest(),
        later.owner.production_policy_digest()
    );
    let input = contributions()?;
    let before = input.clone();
    let first = earlier.owner.evaluate(input.clone())?;
    let second = later.owner.evaluate(input.clone())?;
    assert_ne!(first, second);
    assert_eq!(input, before);
    let mutation = NduOwnerMutationV1::SelectProjection {
        identity_digest: digest("mutation"),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        projection_digest: digest("projection"),
    };
    let old_binding = earlier.owner.final_use_binding(&mutation)?;
    let new_binding = later.owner.final_use_binding(&mutation)?;
    assert_eq!(old_binding.request_sha256, new_binding.request_sha256);
    assert_ne!(old_binding.scope_sha256, new_binding.scope_sha256);
    assert_ne!(old_binding.payload_sha256, new_binding.payload_sha256);
    Ok(())
}

#[test]
fn snapshot_evaluation_keeps_missing_proof_and_axis_rejections() -> TestResult {
    let fixture = fixture(/*generation*/ 7)?;
    let mut input = contributions()?;
    input.contributions[0].support_digest = Digest32::ZERO;
    assert!(matches!(
        fixture.owner.evaluate(input),
        Err(NduOwnerError::Ndu(
            crate::NduError::EmptySupportDigest { .. }
        ))
    ));
    let mut input = contributions()?;
    input.contributions[0].utility[0].axis = id("unknown-axis")?;
    assert!(matches!(
        fixture.owner.evaluate(input),
        Err(NduOwnerError::InvalidContext("numeric admission"))
    ));
    Ok(())
}

#[test]
fn snapshot_bound_mutations_still_require_exact_existing_authority() -> TestResult {
    let mut earlier = fixture(/*generation*/ 7)?;
    let mut later = fixture(/*generation*/ 8)?;
    let mutation = NduOwnerMutationV1::AppendProjection {
        kind: crate::NduProjectionKindV1::Preference,
        identity_digest: digest("snapshot-bound-mutation"),
        objective_digest: digest("objective"),
        subject_digest: digest("subject"),
        projection_digest: digest("projection"),
    };
    let now = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)?
            .as_millis(),
    )?;
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "ndu-snapshot-issuer".to_owned(),
        authority_epoch: 1,
        grant_id: "snapshot-grant".to_owned(),
        nonce: unique_test_nonce("snapshot-grant")?,
        binding: earlier.owner.final_use_binding(&mutation)?,
        not_before_unix_ms: now.saturating_sub(/*rhs*/ 1_000),
        expires_at_unix_ms: now.saturating_add(/*rhs*/ 60_000),
    };
    let signature = earlier.signing.sign(&grant.signing_bytes()?);
    let signed = SignedFinalUseGrant {
        grant,
        signature: signature.to_bytes().to_vec(),
    };
    assert!(matches!(
        later.owner.apply_mutation(&signed, mutation.clone()),
        Err(NduOwnerError::Authority(_))
    ));
    earlier.owner.apply_mutation(&signed, mutation.clone())?;
    assert!(matches!(
        earlier.owner.apply_mutation(&signed, mutation),
        Err(NduOwnerError::Authority(_))
    ));
    Ok(())
}
