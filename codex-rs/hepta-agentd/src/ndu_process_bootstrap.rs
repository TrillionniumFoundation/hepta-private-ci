//! Explicit local and protected-host NDU bootstrap profiles.
//! A pinned descriptor selects policy, paths and independent feed trust.
//! Protected providers are supplied by the embedding host, never the wire.
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use crate::AgentdIdentity;
use crate::AgentdNduOwnerBootstrapV1;
use crate::AgentdNduOwnerErrorV1;
use crate::AgentdNduOwnerHostV1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseFrontier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_ndu::AggregationOperator;
use codex_hepta_ndu::AxisAggregationRule;
use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisLimit;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::EvaluationPolicyV1;
use codex_hepta_ndu::NduProductionPolicyV1;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::ScalarizationProfile;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;
use serde::Deserialize;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Descriptor {
    schema: String,
    trust_profile: String,
    agent_id: String,
    store_root: PathBuf,
    authority_directory: PathBuf,
    authority_signer: String,
    authority_key: [u8; 32],
    revocation_distributor: String,
    revocation_key: [u8; 32],
    revocation_update_path: PathBuf,
    policy: Policy,
    #[serde(default)]
    production_trust: Option<ProductionTrustDescriptor>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ProductionTrustDescriptor {
    caller_id: String,
    profile_digest: String,
}

/// Host-supplied providers for the explicitly named protected-host profile.
/// This value is not a deployment qualification or an attestation issuer. The
/// host must enroll the concrete clock and external CAS service independently;
/// neither a descriptor nor a wire request can manufacture those providers.
pub struct NduProductionHostTrustV1 {
    caller_id: StableId,
    profile_digest: Digest32,
    clock: Arc<dyn AuthorityClock>,
    frontier: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
}

impl NduProductionHostTrustV1 {
    pub fn new(
        caller_id: StableId,
        profile_digest: Digest32,
        clock: Arc<dyn AuthorityClock>,
        frontier: Arc<dyn AuthorityFrontierStore<FinalUseFrontier>>,
    ) -> Result<Self, AgentdNduOwnerErrorV1> {
        if profile_digest.is_zero() {
            return Err(invalid("production trust profile must not be zero"));
        }
        Ok(Self {
            caller_id,
            profile_digest,
            clock,
            frontier,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Policy {
    profile_id: String,
    policy_id: String,
    axis_registry_digest: String,
    normalization_manifest_digest: String,
    utility_axes: Vec<UtilityAxis>,
    risk_axes: Vec<LimitAxis>,
    resource_axes: Vec<LimitAxis>,
    required_organs: Vec<String>,
    scalarization: Option<Scalarization>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct UtilityAxis {
    id: String,
    direction: String,
    aggregation: String,
    uncertainty_aggregation: String,
    tolerance_raw: i64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LimitAxis {
    id: String,
    maximum_raw: i64,
    aggregation: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Scalarization {
    profile_id: String,
    weights: Vec<Weight>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Weight {
    axis: String,
    raw: i64,
}

fn invalid(message: impl ToString) -> AgentdNduOwnerErrorV1 {
    AgentdNduOwnerErrorV1::Bootstrap(message.to_string())
}
fn id(value: &str) -> Result<StableId, AgentdNduOwnerErrorV1> {
    StableId::new(value).map_err(invalid)
}
fn aggregation(value: &str) -> Result<AggregationOperator, AgentdNduOwnerErrorV1> {
    match value {
        "sum" => Ok(AggregationOperator::Sum),
        "maximum" => Ok(AggregationOperator::Maximum),
        "minimum" => Ok(AggregationOperator::Minimum),
        "require_equal" => Ok(AggregationOperator::RequireEqual),
        _ => Err(invalid("unregistered axis aggregation")),
    }
}

impl Policy {
    fn native(self) -> Result<NduProductionPolicyV1, AgentdNduOwnerErrorV1> {
        if self.utility_axes.is_empty()
            || self.utility_axes.len() > 64
            || self.risk_axes.len() > 64
            || self.resource_axes.len() > 64
            || self.required_organs.len() > 64
        {
            return Err(invalid("policy exceeds bounded axis/organ envelope"));
        }
        let mut dimensions = Vec::new();
        let mut utility_rules = Vec::new();
        let mut uncertainty_rules = Vec::new();
        let mut tolerances = Vec::new();
        for axis in self.utility_axes {
            let name = id(&axis.id)?;
            let direction = match axis.direction.as_str() {
                "maximize" => AxisDirection::Maximize,
                "minimize" => AxisDirection::Minimize,
                _ => return Err(invalid("unregistered axis direction")),
            };
            dimensions.push((name.clone(), direction));
            utility_rules.push(AxisAggregationRule {
                axis: name.clone(),
                operator: aggregation(&axis.aggregation)?,
            });
            uncertainty_rules.push(AxisAggregationRule {
                axis: name.clone(),
                operator: aggregation(&axis.uncertainty_aggregation)?,
            });
            tolerances.push(AxisValue {
                axis: name,
                value: FixedQ32::from_raw(axis.tolerance_raw),
            });
        }
        let limits = |axes: Vec<LimitAxis>| -> Result<_, AgentdNduOwnerErrorV1> {
            let mut ceilings = Vec::new();
            let mut rules = Vec::new();
            for axis in axes {
                let name = id(&axis.id)?;
                ceilings.push(AxisLimit {
                    axis: name.clone(),
                    maximum: FixedQ32::from_raw(axis.maximum_raw),
                });
                rules.push(AxisAggregationRule {
                    axis: name,
                    operator: aggregation(&axis.aggregation)?,
                });
            }
            Ok((ceilings, rules))
        };
        let (risk_ceilings, risk_rules) = limits(self.risk_axes)?;
        let (resource_ceilings, resource_rules) = limits(self.resource_axes)?;
        let scalarization = self
            .scalarization
            .map(|profile| -> Result<_, AgentdNduOwnerErrorV1> {
                if profile.weights.len() > 64 {
                    return Err(invalid("scalarization exceeds axis bound"));
                }
                Ok(ScalarizationProfile {
                    profile_id: id(&profile.profile_id)?,
                    weights: profile
                        .weights
                        .into_iter()
                        .map(|weight| {
                            Ok(AxisValue {
                                axis: id(&weight.axis)?,
                                value: FixedQ32::from_raw(weight.raw),
                            })
                        })
                        .collect::<Result<Vec<_>, AgentdNduOwnerErrorV1>>()?,
                })
            })
            .transpose()?;
        Ok(NduProductionPolicyV1 {
            utility_profile: UtilityProfile {
                profile_id: id(&self.profile_id)?,
                axis_registry_digest: self.axis_registry_digest.parse().map_err(invalid)?,
                normalization_manifest_digest: self
                    .normalization_manifest_digest
                    .parse()
                    .map_err(invalid)?,
                dimensions,
                risk_ceilings,
                resource_ceilings,
                required_organs: RequiredOrganSet {
                    organ_ids: self
                        .required_organs
                        .iter()
                        .map(|s| id(s))
                        .collect::<Result<_, _>>()?,
                },
            },
            evaluation_policy: EvaluationPolicyV1 {
                policy_id: id(&self.policy_id)?,
                utility_rules,
                risk_rules,
                resource_rules,
                uncertainty_rules,
                pareto_absolute_tolerances: tolerances,
            },
            scalarization,
        })
    }
}

pub(crate) struct NduRevocationSourceV1 {
    path: PathBuf,
    verifier: FinalUseRevocationFeedVerifier,
    pub(crate) trust_digest: Digest32,
    clock: Arc<dyn AuthorityClock>,
    pub(crate) production_caller: Option<StableId>,
}
impl NduRevocationSourceV1 {
    pub(crate) fn now_ms(&self) -> Result<u64, AgentdNduOwnerErrorV1> {
        self.clock.now_unix_ms().map_err(invalid)
    }
    fn current(&self) -> Result<SignedFinalUseRevocationUpdate, AgentdNduOwnerErrorV1> {
        serde_json::from_slice(&read_bounded(&self.path, 1_048_576)?).map_err(invalid)
    }
    /// Reauthenticate the feed at physical entry without advancing authority
    /// inside an active effect. A newer head rejects this operation; the next
    /// ingress installs it before any fresh admission.
    pub(crate) fn require_current(
        &self,
        authority: &FinalUseAuthority,
    ) -> Result<(), AgentdNduOwnerErrorV1> {
        let signed = self.current()?;
        let head = self
            .verifier
            .authenticated_head(&signed, self.now_ms()?)
            .map_err(invalid)?;
        if authority.revocation_head()? != head {
            return Err(AgentdNduOwnerErrorV1::RevocationAdvanced);
        }
        Ok(())
    }

    pub(crate) fn refresh(
        &self,
        authority: &FinalUseAuthority,
    ) -> Result<(), AgentdNduOwnerErrorV1> {
        let signed = self.current()?;
        let now = self.now_ms()?;
        let head = self
            .verifier
            .authenticated_head(&signed, now)
            .map_err(invalid)?;
        if authority.revocation_head()? != head {
            self.verifier
                .apply(authority, &signed, now)
                .map_err(invalid)?;
        }
        Ok(())
    }
}

/// Load the explicit local-deterministic profile. A descriptor requesting
/// production trust is rejected instead of silently using the process clock.
pub fn load_ndu_process_bootstrap_v1(
    path: &Path,
    expected_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<Arc<AgentdNduOwnerHostV1>, AgentdNduOwnerErrorV1> {
    load_bootstrap(
        path,
        expected_digest,
        &identity.agent_id,
        identity.spawn_generation,
        None,
    )
}

/// Compose the same named Agentd writer with a host-owned protected clock and
/// an externally durable authority frontier. This uses the existing runtime
/// attachment (`AgentdConfig::with_ndu_owner_host`) and private control socket,
/// not a parallel writer. Concrete provider qualification and projection-store
/// off-host anti-rollback evidence remain deployment obligations.
pub fn load_ndu_production_bootstrap_v2(
    path: &Path,
    expected_digest: Digest32,
    identity: &AgentdIdentity,
    trust: NduProductionHostTrustV1,
) -> Result<Arc<AgentdNduOwnerHostV1>, AgentdNduOwnerErrorV1> {
    load_bootstrap(
        path,
        expected_digest,
        &identity.agent_id,
        identity.spawn_generation,
        Some(trust),
    )
}

fn load_bootstrap(
    path: &Path,
    expected_digest: Digest32,
    agent_id: &AgentId,
    spawn_generation: u64,
    trust: Option<NduProductionHostTrustV1>,
) -> Result<Arc<AgentdNduOwnerHostV1>, AgentdNduOwnerErrorV1> {
    let bytes = read_bounded(path, 65_536)?;
    if expected_digest.is_zero() || Digest32::of_bytes(&bytes) != expected_digest {
        return Err(invalid("NDU descriptor digest mismatch"));
    }
    let descriptor: Descriptor = serde_json::from_slice(&bytes).map_err(invalid)?;
    if descriptor.agent_id != agent_id.as_str()
        || descriptor.authority_key == descriptor.revocation_key
        || spawn_generation == 0
    {
        return Err(invalid(
            "NDU agent identity or independent feed trust mismatch",
        ));
    }
    let (clock, frontier, production_caller, profile_digest) = match trust {
        Some(trust) => {
            let declared = descriptor
                .production_trust
                .as_ref()
                .ok_or_else(|| invalid("missing protected-host trust binding"))?;
            let declared_digest: Digest32 = declared.profile_digest.parse().map_err(invalid)?;
            if descriptor.schema != "hepta.agentd.ndu-bootstrap.v2"
                || descriptor.trust_profile != "protected-host-v1"
                || declared.caller_id != trust.caller_id.as_str()
                || declared_digest != trust.profile_digest
            {
                return Err(invalid(
                    "protected-host provider/descriptor binding mismatch",
                ));
            }
            (
                trust.clock,
                Some(trust.frontier),
                Some(trust.caller_id),
                trust.profile_digest,
            )
        }
        None => {
            if descriptor.schema != "hepta.agentd.ndu-bootstrap.v1"
                || descriptor.trust_profile != "local-deterministic"
                || descriptor.production_trust.is_some()
            {
                return Err(invalid(
                    "production profile requires host-owned trust providers",
                ));
            }
            (
                Arc::new(SystemAuthorityClock) as Arc<dyn AuthorityClock>,
                None,
                None,
                Digest32::ZERO,
            )
        }
    };
    // Reject the entire policy before either authority or projection-store I/O.
    let policy = descriptor.policy.native()?;
    codex_hepta_ndu::canonical_evaluation_policy_digest(
        &policy.utility_profile,
        &policy.evaluation_policy,
    )
    .map_err(invalid)?;
    if let Some(scalarization) = &policy.scalarization {
        codex_hepta_ndu::ValidatedScalarizationProfileV1::try_new(
            &policy.utility_profile,
            scalarization.clone(),
        )
        .map_err(invalid)?;
    }
    for directory in [&descriptor.store_root, &descriptor.authority_directory] {
        if !directory.is_absolute() || directory.canonicalize().map_err(invalid)? != *directory {
            return Err(invalid(
                "NDU owner directories must be canonical absolute paths",
            ));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if std::fs::metadata(directory)
                .map_err(invalid)?
                .permissions()
                .mode()
                & 0o077
                != 0
            {
                return Err(invalid("NDU owner directories must be private"));
            }
        }
    }
    let local_trust = Digest32::of_parts(&[
        b"hepta.agentd.ndu.trust.v1\0",
        &descriptor.authority_key,
        &descriptor.revocation_key,
        descriptor.authority_signer.as_bytes(),
        b"\0",
        descriptor.revocation_distributor.as_bytes(),
    ]);
    let trust_digest = production_caller.as_ref().map_or(local_trust, |caller| {
        Digest32::of_parts(&[
            b"hepta.agentd.ndu.protected-host-trust.v1\0",
            local_trust.as_array(),
            profile_digest.as_array(),
            caller.as_str().as_bytes(),
        ])
    });
    let source = NduRevocationSourceV1 {
        path: descriptor.revocation_update_path,
        verifier: FinalUseRevocationFeedVerifier::new(
            descriptor.revocation_distributor,
            descriptor.revocation_key,
        )
        .map_err(invalid)?,
        trust_digest,
        clock: clock.clone(),
        production_caller,
    };
    let signed = source.current()?;
    let head = source
        .verifier
        .authenticated_head(&signed, source.now_ms()?)
        .map_err(invalid)?;
    let authority = match frontier {
        Some(frontier) => FinalUseAuthority::open_state_dir_with_trust(
            &descriptor.authority_directory,
            descriptor.authority_signer,
            descriptor.authority_key,
            head,
            clock,
            frontier,
        )?,
        None => FinalUseAuthority::open_state_dir_with_clock(
            &descriptor.authority_directory,
            descriptor.authority_signer,
            descriptor.authority_key,
            head,
            clock,
        )?,
    };
    source.refresh(&authority)?;
    AgentdNduOwnerHostV1::open_with_feed(
        agent_id.clone(),
        spawn_generation,
        AgentdNduOwnerBootstrapV1 {
            store_root: descriptor.store_root,
            authority,
            policy,
        },
        Some(source),
    )
}

fn read_bounded(path: &Path, limit: u64) -> Result<Vec<u8>, AgentdNduOwnerErrorV1> {
    if !path.is_absolute() || path.canonicalize().map_err(invalid)? != path {
        return Err(invalid("NDU input must be a canonical absolute file"));
    }
    let metadata = std::fs::symlink_metadata(path).map_err(invalid)?;
    if !metadata.is_file() || metadata.len() > limit {
        return Err(invalid("NDU input type/size rejected"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o022 != 0 {
            return Err(invalid("NDU input is writable by other users"));
        }
    }
    let file = File::open(path).map_err(invalid)?;
    let metadata = file.metadata().map_err(invalid)?;
    if !metadata.is_file() || metadata.len() > limit {
        return Err(invalid("NDU opened input type/size rejected"));
    }
    let mut bytes = Vec::with_capacity(usize::try_from(metadata.len()).map_err(invalid)?);
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(invalid)?;
    if bytes.len() as u64 > limit {
        return Err(invalid("NDU growing input exceeded bound"));
    }
    Ok(bytes)
}

#[cfg(all(test, unix))]
#[path = "ndu_process_bootstrap_tests.rs"]
mod tests;
