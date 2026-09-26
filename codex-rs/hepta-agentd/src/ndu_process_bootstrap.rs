//! Explicit process bootstrap for the deterministic local-host baseline.
//! A pinned descriptor selects policy, paths and independent feed trust. This
//! profile does not assert a protected clock or an off-host rollback oracle.
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use crate::AgentdIdentity;
use crate::AgentdNduOwnerBootstrapV1;
use crate::AgentdNduOwnerErrorV1;
use crate::AgentdNduOwnerHostV1;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
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
}
impl NduRevocationSourceV1 {
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
            .authenticated_head(&signed, now_ms()?)
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
        let now = now_ms()?;
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

/// Load a descriptor whose digest was pinned by the trusted process launcher.
/// Only the explicit local baseline is supported; production trust is never
/// silently downgraded to a process clock and a local-only authority store.
pub fn load_ndu_process_bootstrap_v1(
    path: &Path,
    expected_digest: Digest32,
    identity: &AgentdIdentity,
) -> Result<Arc<AgentdNduOwnerHostV1>, AgentdNduOwnerErrorV1> {
    let bytes = read_bounded(path, 65_536)?;
    if expected_digest.is_zero() || Digest32::of_bytes(&bytes) != expected_digest {
        return Err(invalid("NDU descriptor digest mismatch"));
    }
    let descriptor: Descriptor = serde_json::from_slice(&bytes).map_err(invalid)?;
    if descriptor.schema != "hepta.agentd.ndu-bootstrap.v1"
        || descriptor.trust_profile != "local-deterministic"
        || descriptor.agent_id != identity.agent_id.as_str()
        || descriptor.authority_key == descriptor.revocation_key
    {
        return Err(invalid(
            "unsupported NDU profile, agent identity or non-independent feed trust",
        ));
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
    let source = NduRevocationSourceV1 {
        path: descriptor.revocation_update_path,
        verifier: FinalUseRevocationFeedVerifier::new(
            descriptor.revocation_distributor.clone(),
            descriptor.revocation_key,
        )
        .map_err(invalid)?,
        trust_digest: Digest32::of_parts(&[
            b"hepta.agentd.ndu.trust.v1\0",
            &descriptor.authority_key,
            &descriptor.revocation_key,
            descriptor.authority_signer.as_bytes(),
            b"\0",
            descriptor.revocation_distributor.as_bytes(),
        ]),
    };
    let signed = source.current()?;
    let head = source
        .verifier
        .authenticated_head(&signed, now_ms()?)
        .map_err(invalid)?;
    let authority = FinalUseAuthority::open_state_dir(
        &descriptor.authority_directory,
        descriptor.authority_signer,
        descriptor.authority_key,
        head,
    )?;
    source.refresh(&authority)?;
    AgentdNduOwnerHostV1::open_with_feed(
        identity.agent_id.clone(),
        identity.spawn_generation,
        AgentdNduOwnerBootstrapV1 {
            store_root: descriptor.store_root,
            authority,
            policy: descriptor.policy.native()?,
        },
        Some(source),
    )
}

fn now_ms() -> Result<u64, AgentdNduOwnerErrorV1> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(invalid)?
            .as_millis(),
    )
    .map_err(invalid)
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
