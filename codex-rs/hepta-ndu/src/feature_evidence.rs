//! Evidence contracts for host-observed features, not a source authenticator.
//! The trusted host owns source observations and the frozen actor policy. A
//! digest binds that provenance; it does not turn caller assertions into facts.
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use crate::ContributionSet;
use crate::UtilityProfile;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
#[repr(u8)]
pub enum NduFeatureKindV1 {
    Utility = 0,
    Risk = 1,
    Resource = 2,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
#[repr(u8)]
pub enum NduFeatureOriginV1 {
    Measured = 0,
    Derived = 1,
    Defaulted = 2,
    Missing = 3,
    Structural = 4,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduFeatureEvidenceV1 {
    pub candidate_id: StableId,
    pub organ_id: StableId,
    pub kind: NduFeatureKindV1,
    pub axis: StableId,
    pub value: FixedQ32,
    pub origin: NduFeatureOriginV1,
    /// The host-observed contribution support, not a self-asserted certificate.
    pub source_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduActorScenarioV1 {
    pub candidate_id: StableId,
    pub actor_id: StableId,
    pub risk: FixedQ32,
    pub uncertainty: FixedQ32,
    pub source_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduEvidencePolicyV1 {
    pub policy_id: StableId,
    pub high_risk: bool,
    /// Explicit affected actors, not organ identities or purported reviewers.
    pub required_actors: Vec<StableId>,
    pub proxy_uncertainty_floor: FixedQ32,
    pub actor_risk_ceiling: FixedQ32,
    pub actor_uncertainty_ceiling: FixedQ32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduEvidenceErrorV1 {
    Policy,
    Capacity,
    FeatureCoverage,
    FeatureBinding,
    MissingFeature,
    ProxyUncertainty,
    ActorCoverage,
    ActorRisk,
    ActorUncertainty,
}

impl NduEvidenceErrorV1 {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::Policy => "NDU-EVID-001",
            Self::Capacity => "NDU-EVID-002",
            Self::FeatureCoverage => "NDU-EVID-003",
            Self::FeatureBinding => "NDU-EVID-004",
            Self::MissingFeature => "NDU-EVID-005",
            Self::ProxyUncertainty => "NDU-EVID-006",
            Self::ActorCoverage => "NDU-EVID-007",
            Self::ActorRisk => "NDU-EVID-008",
            Self::ActorUncertainty => "NDU-EVID-009",
        }
    }
}
impl fmt::Display for NduEvidenceErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl Error for NduEvidenceErrorV1 {}

pub fn canonical_ndu_evidence_policy_digest_v1(
    policy: &NduEvidencePolicyV1,
) -> Result<Digest32, NduEvidenceErrorV1> {
    let actors: BTreeSet<_> = policy.required_actors.iter().collect();
    if actors.len() != policy.required_actors.len()
        || actors.len() > 32
        || (policy.high_risk && actors.len() < 2)
        || policy.proxy_uncertainty_floor.raw() <= 0
        || policy.actor_risk_ceiling.raw() < 0
        || policy.actor_uncertainty_ceiling.raw() < 0
    {
        return Err(NduEvidenceErrorV1::Policy);
    }
    let mut bytes = b"hepta.ndu.evidence-policy.v1\0".to_vec();
    push_id(&mut bytes, &policy.policy_id);
    bytes.push(u8::from(policy.high_risk));
    for value in [
        policy.proxy_uncertainty_floor,
        policy.actor_risk_ceiling,
        policy.actor_uncertainty_ceiling,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&(actors.len() as u64).to_be_bytes());
    for actor in actors {
        push_id(&mut bytes, actor);
    }
    Ok(Digest32::of_bytes(&bytes))
}

/// Check complete feature and actor coverage, then bind the full canonical
/// manifest into every contribution support. Numerical policy validation still
/// occurs in the evaluator; this never selects a candidate or grants effects.
pub fn bind_contribution_evidence_v1(
    set: &ContributionSet,
    profile: &UtilityProfile,
    policy: &NduEvidencePolicyV1,
    features: &[NduFeatureEvidenceV1],
    scenarios: &[NduActorScenarioV1],
) -> Result<ContributionSet, NduEvidenceErrorV1> {
    use NduEvidenceErrorV1 as E;
    let policy_digest = canonical_ndu_evidence_policy_digest_v1(policy)?;
    if set.contributions.is_empty()
        || set.contributions.len() > 4096
        || features.len() > 4096 * 72
        || scenarios.len() > 128 * 32
    {
        return Err(E::Capacity);
    }
    let mut observations = BTreeMap::new();
    for feature in features {
        let key = (
            &feature.candidate_id,
            &feature.organ_id,
            feature.kind,
            &feature.axis,
        );
        if observations.insert(key, feature).is_some() {
            return Err(E::FeatureCoverage);
        }
    }
    let mut consumed = BTreeSet::new();
    let mut candidates = BTreeSet::new();
    for contribution in &set.contributions {
        candidates.insert(&contribution.candidate_id);
        if contribution.objective_digest != set.objective_digest
            || contribution.generation != set.generation
            || contribution.support_digest.is_zero()
        {
            return Err(E::FeatureBinding);
        }
        for (kind, values) in [
            (NduFeatureKindV1::Utility, &contribution.utility),
            (NduFeatureKindV1::Risk, &contribution.risk),
            (NduFeatureKindV1::Resource, &contribution.resource),
        ] {
            if values.len() > 32 {
                return Err(E::Capacity);
            }
            for axis in values {
                let key = (
                    &contribution.candidate_id,
                    &contribution.organ_id,
                    kind,
                    &axis.axis,
                );
                let feature = observations.get(&key).ok_or(E::FeatureCoverage)?;
                if !consumed.insert(key) {
                    return Err(E::FeatureCoverage);
                }
                if feature.value != axis.value
                    || feature.source_digest != contribution.support_digest
                {
                    return Err(E::FeatureBinding);
                }
                if feature.origin == NduFeatureOriginV1::Missing {
                    return Err(E::MissingFeature);
                }
                if feature.origin == NduFeatureOriginV1::Structural {
                    // Only the mathematical zero of the no-effect abstain
                    // candidate is structural; do not call it a measurement.
                    if contribution.candidate_id.as_str() != "abstain"
                        || feature.value != FixedQ32::ZERO
                    {
                        return Err(E::FeatureBinding);
                    }
                } else if feature.origin != NduFeatureOriginV1::Measured {
                    // Risk/resource proxies have no corresponding uncertainty
                    // channel in V1. Reject, never invent an exact observation.
                    if policy.high_risk || kind != NduFeatureKindV1::Utility {
                        return Err(E::ProxyUncertainty);
                    }
                    let uncertainty = contribution
                        .uncertainty
                        .iter()
                        .find(|value| value.axis == axis.axis)
                        .ok_or(E::ProxyUncertainty)?;
                    if uncertainty.value < policy.proxy_uncertainty_floor {
                        return Err(E::ProxyUncertainty);
                    }
                }
            }
        }
    }
    if consumed.len() != observations.len() || candidates.len() > 128 {
        return Err(E::FeatureCoverage);
    }
    if !profile.risk_ceilings.is_empty() && !policy.high_risk {
        return Err(E::Policy);
    }
    let mut actor_rows = BTreeMap::new();
    for row in scenarios {
        if !candidates.contains(&row.candidate_id)
            || row.candidate_id.as_str() == "abstain"
            || !policy.required_actors.contains(&row.actor_id)
            || row.source_digest.is_zero()
            || actor_rows
                .insert((&row.candidate_id, &row.actor_id), row)
                .is_some()
        {
            return Err(E::ActorCoverage);
        }
        if row.risk.raw() < 0 || row.risk > policy.actor_risk_ceiling {
            return Err(E::ActorRisk);
        }
        if row.uncertainty.raw() < 0 || row.uncertainty > policy.actor_uncertainty_ceiling {
            return Err(E::ActorUncertainty);
        }
    }
    for candidate in candidates
        .iter()
        .filter(|value| value.as_str() != "abstain")
    {
        for actor in &policy.required_actors {
            if !actor_rows.contains_key(&(*candidate, actor)) {
                return Err(E::ActorCoverage);
            }
        }
    }
    let mut bytes = b"hepta.ndu.feature-manifest.v1\0".to_vec();
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(set.objective_digest.as_array());
    bytes.extend_from_slice(&set.generation.get().to_be_bytes());
    bytes.extend_from_slice(&(observations.len() as u64).to_be_bytes());
    for feature in observations.values() {
        push_id(&mut bytes, &feature.candidate_id);
        push_id(&mut bytes, &feature.organ_id);
        push_id(&mut bytes, &feature.axis);
        bytes.push(feature.kind as u8);
        bytes.push(feature.origin as u8);
        bytes.extend_from_slice(&feature.value.raw().to_be_bytes());
        bytes.extend_from_slice(feature.source_digest.as_array());
    }
    bytes.extend_from_slice(&(actor_rows.len() as u64).to_be_bytes());
    for row in actor_rows.values() {
        push_id(&mut bytes, &row.candidate_id);
        push_id(&mut bytes, &row.actor_id);
        bytes.extend_from_slice(&row.risk.raw().to_be_bytes());
        bytes.extend_from_slice(&row.uncertainty.raw().to_be_bytes());
        bytes.extend_from_slice(row.source_digest.as_array());
    }
    let manifest = Digest32::of_bytes(&bytes);
    let mut bound = set.clone();
    for contribution in &mut bound.contributions {
        let mut bytes = b"hepta.ndu.feature-bound-support.v1\0".to_vec();
        bytes.extend_from_slice(contribution.support_digest.as_array());
        bytes.extend_from_slice(manifest.as_array());
        contribution.support_digest = Digest32::of_bytes(&bytes);
    }
    Ok(bound)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        AxisDirection, AxisValue, FeasibilityPosture, RequiredOrganSet, UtilityContribution,
    };
    use codex_hepta_types::Generation;

    fn id(name: &str) -> StableId {
        StableId::new(name).unwrap_or_else(|error| panic!("test id: {error}"))
    }
    fn digest(name: &str) -> Digest32 {
        Digest32::of_bytes(name.as_bytes())
    }
    fn fixture() -> (
        ContributionSet,
        UtilityProfile,
        NduEvidencePolicyV1,
        Vec<NduFeatureEvidenceV1>,
    ) {
        let generation =
            Generation::new(1).unwrap_or_else(|error| panic!("test generation: {error}"));
        let set = ContributionSet {
            objective_digest: digest("objective"),
            generation,
            contributions: ["abstain", "act"]
                .iter()
                .map(|name| UtilityContribution {
                    candidate_id: id(name),
                    organ_id: id("owner"),
                    objective_digest: digest("objective"),
                    generation,
                    feasibility: FeasibilityPosture::Feasible,
                    utility: vec![AxisValue {
                        axis: id("quality"),
                        value: FixedQ32::ONE,
                    }],
                    risk: vec![],
                    resource: vec![],
                    uncertainty: vec![AxisValue {
                        axis: id("quality"),
                        value: FixedQ32::ZERO,
                    }],
                    support_digest: digest(name),
                })
                .collect(),
        };
        let features = set
            .contributions
            .iter()
            .map(|value| NduFeatureEvidenceV1 {
                candidate_id: value.candidate_id.clone(),
                organ_id: value.organ_id.clone(),
                kind: NduFeatureKindV1::Utility,
                axis: id("quality"),
                value: FixedQ32::ONE,
                origin: NduFeatureOriginV1::Measured,
                source_digest: value.support_digest,
            })
            .collect();
        let profile = UtilityProfile {
            profile_id: id("profile"),
            axis_registry_digest: digest("axes"),
            normalization_manifest_digest: digest("units"),
            dimensions: vec![(id("quality"), AxisDirection::Maximize)],
            risk_ceilings: vec![],
            resource_ceilings: vec![],
            required_organs: RequiredOrganSet {
                organ_ids: vec![id("owner")],
            },
        };
        let policy = NduEvidencePolicyV1 {
            policy_id: id("evidence"),
            high_risk: false,
            required_actors: vec![],
            proxy_uncertainty_floor: FixedQ32::ONE,
            actor_risk_ceiling: FixedQ32::ONE,
            actor_uncertainty_ceiling: FixedQ32::ZERO,
        };
        (set, profile, policy, features)
    }

    #[test]
    fn missing_tampered_duplicate_and_proxy_features_fail_closed() -> Result<(), Box<dyn Error>> {
        let (mut set, profile, policy, mut features) = fixture();
        let measured = bind_contribution_evidence_v1(&set, &profile, &policy, &features, &[])?;
        assert_ne!(
            measured.contributions[0].support_digest,
            set.contributions[0].support_digest
        );
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features[..1], &[]),
            Err(NduEvidenceErrorV1::FeatureCoverage)
        );
        features[0].value = FixedQ32::ZERO;
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &[]),
            Err(NduEvidenceErrorV1::FeatureBinding)
        );
        features[0].value = FixedQ32::ONE;
        features[0].origin = NduFeatureOriginV1::Missing;
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &[]),
            Err(NduEvidenceErrorV1::MissingFeature)
        );
        features[0].origin = NduFeatureOriginV1::Derived;
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &[]),
            Err(NduEvidenceErrorV1::ProxyUncertainty)
        );
        set.contributions[0].uncertainty[0].value = FixedQ32::ONE;
        let derived = bind_contribution_evidence_v1(&set, &profile, &policy, &features, &[])?;
        assert_ne!(
            derived.contributions[0].support_digest,
            measured.contributions[0].support_digest
        );
        let first = features[0].clone();
        features.push(first);
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &[]),
            Err(NduEvidenceErrorV1::FeatureCoverage)
        );
        Ok(())
    }

    #[test]
    fn high_risk_requires_all_actors_and_rejects_risk_or_uncertainty() -> Result<(), Box<dyn Error>>
    {
        let (set, profile, mut policy, mut features) = fixture();
        policy.high_risk = true;
        assert_eq!(
            canonical_ndu_evidence_policy_digest_v1(&policy),
            Err(NduEvidenceErrorV1::Policy)
        );
        policy.required_actors = vec![id("user"), id("affected-party")];
        let mut actors: Vec<_> = policy
            .required_actors
            .iter()
            .map(|actor| NduActorScenarioV1 {
                candidate_id: id("act"),
                actor_id: actor.clone(),
                risk: FixedQ32::ZERO,
                uncertainty: FixedQ32::ZERO,
                source_digest: digest("actor-observation"),
            })
            .collect();
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &actors[..1]),
            Err(NduEvidenceErrorV1::ActorCoverage)
        );
        let original = bind_contribution_evidence_v1(&set, &profile, &policy, &features, &actors)?;
        features.reverse();
        actors.reverse();
        policy.required_actors.reverse();
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &actors)?,
            original
        );
        actors[0].risk = FixedQ32::from_raw(FixedQ32::ONE.raw() + 1);
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &actors),
            Err(NduEvidenceErrorV1::ActorRisk)
        );
        actors[0].risk = FixedQ32::ZERO;
        actors[0].uncertainty = FixedQ32::ONE;
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &actors),
            Err(NduEvidenceErrorV1::ActorUncertainty)
        );
        actors[0].uncertainty = FixedQ32::ZERO;
        features[0].origin = NduFeatureOriginV1::Defaulted;
        assert_eq!(
            bind_contribution_evidence_v1(&set, &profile, &policy, &features, &actors),
            Err(NduEvidenceErrorV1::ProxyUncertainty)
        );
        Ok(())
    }
}
