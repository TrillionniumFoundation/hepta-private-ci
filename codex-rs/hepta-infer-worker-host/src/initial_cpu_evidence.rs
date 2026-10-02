//! Historical installation measurements never renew themselves. A new Root
//! declaration and independently verified E2 lease authorize current model use.
use super::*;
use codex_hepta_agent_components::intelligence_eval::VerifiedInitialOperationalHistoryV1;
use codex_hepta_agent_components::intelligence_eval::VerifiedOperationalModelLeaseV2;
use codex_hepta_agent_components::intelligence_eval::inspect_initial_neuron_operational_history;
use codex_hepta_agent_components::intelligence_eval::inspect_operational_model_lease_v2;
use codex_hepta_agent_components::learning_ledger::VerifiedLearningEvidenceV1;
use std::sync::Arc;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ModelUseContinuation {
    installed_profile: Source,
    evaluation_config: Source,
    independent_report: Source,
    body_implementation: Source,
}

pub(super) enum InitialEvidence {
    Initial(VerifiedInitialOperationalEvidenceV1),
    Continued {
        history: VerifiedInitialOperationalHistoryV1,
        lease: Arc<VerifiedOperationalModelLeaseV2>,
        evaluation_config: Source,
        independent_report: Source,
        installed_profile: Source,
        body_implementation: Source,
    },
}

impl InitialEvidence {
    pub(super) fn read(
        continuation: Option<ModelUseContinuation>,
        configuration: &Source,
        report: &Source,
        profile: &Profile,
        profile_source: &Source,
    ) -> HostResult<Self> {
        match continuation {
            None => {
                let original = inspect_initial_neuron_operational_evidence(
                    &configuration.path,
                    digest(&configuration.digest)?,
                    &report.path,
                    digest(&report.digest)?,
                )?;
                if original.initial_product_profile_digest()
                    != Some(digest(&profile_source.digest)?)
                    || profile.frozen_at_ms > measured_at(original.measurements())?
                {
                    return Err(
                        "E did not independently bind this original frozen product profile".into(),
                    );
                }
                Ok(Self::Initial(original))
            }
            Some(current) => {
                let history = inspect_initial_neuron_operational_history(
                    &configuration.path,
                    digest(&configuration.digest)?,
                    &report.path,
                    digest(&report.digest)?,
                )?;
                let original: Profile =
                    serde_json::from_slice(&current.installed_profile.read(64 * 1024)?)?;
                original.validate_identity()?;
                renewal::verify_first_installation(&original)?;
                renewal::validate_unchanged_profile(&original, profile)?;
                if history.initial_product_profile_digest()
                    != Some(digest(&current.installed_profile.digest)?)
                    || original.frozen_at_ms > measured_at(history.measurements())?
                    || profile_source == &current.installed_profile
                {
                    return Err(
                        "continued model use differs from original physical installation".into(),
                    );
                }
                let lease = inspect_operational_model_lease_v2(
                    &current.evaluation_config.path,
                    digest(&current.evaluation_config.digest)?,
                    &current.independent_report.path,
                    digest(&current.independent_report.digest)?,
                )?;
                if profile.frozen_at_ms > measured_at(lease.measurements())?
                    || lease.binding().body_implementation_digest
                        != digest(&current.body_implementation.digest)?
                {
                    return Err("current Root model-use scope must precede independent E2".into());
                }
                current.body_implementation.read(1024 * 1024)?;
                let result = Self::Continued {
                    history,
                    lease: Arc::new(lease),
                    evaluation_config: current.evaluation_config,
                    independent_report: current.independent_report,
                    installed_profile: current.installed_profile,
                    body_implementation: current.body_implementation,
                };
                result.revalidate_current()?;
                Ok(result)
            }
        }
    }
    pub(super) fn measurements(&self) -> &Value {
        match self {
            Self::Initial(e) => e.measurements(),
            Self::Continued { history, .. } => history.measurements(),
        }
    }
    pub(super) fn current_measurements(&self) -> &Value {
        match self {
            Self::Initial(e) => e.measurements(),
            Self::Continued { lease, .. } => lease.measurements(),
        }
    }
    pub(super) fn evaluator(&self) -> &VerifiedLearningEvidenceV1 {
        match self {
            Self::Initial(e) => e.evaluator(),
            Self::Continued { lease, .. } => lease.evaluator(),
        }
    }
    pub(super) fn authentication_digest(&self) -> Digest32 {
        match self {
            Self::Initial(e) => e.authentication_digest(),
            Self::Continued { lease, .. } => lease.authentication_digest(),
        }
    }
    pub(super) fn model_manifest_digest(&self) -> Digest32 {
        match self {
            Self::Initial(e) => e.model_manifest_digest(),
            Self::Continued { history, .. } => history.model_manifest_digest(),
        }
    }
    pub(super) fn weights_digest(&self) -> Digest32 {
        match self {
            Self::Initial(e) => e.weights_digest(),
            Self::Continued { history, .. } => history.weights_digest(),
        }
    }
    pub(super) fn objective_digest(&self) -> Digest32 {
        match self {
            Self::Initial(e) => e.objective_digest(),
            Self::Continued { history, .. } => history.objective_digest(),
        }
    }
    pub(super) fn artifact_subject_digest(&self) -> HostResult<Digest32> {
        match self {
            Self::Initial(e) => Ok(e.objective_digest()),
            Self::Continued { lease, .. } => Ok(lease.binding().binding_digest()?),
        }
    }
    pub(super) fn expires_at(&self) -> u64 {
        match self {
            Self::Initial(e) => e.expires_at(),
            Self::Continued { lease, .. } => lease.expires_at(),
        }
    }
    pub(super) fn physical_profile_source<'a>(&'a self, original: &'a Source) -> &'a Source {
        match self {
            Self::Initial(_) => original,
            Self::Continued {
                installed_profile, ..
            } => installed_profile,
        }
    }
    pub(super) fn extend_historical_lineage(&self, lineage: &mut Vec<Digest32>) -> HostResult<()> {
        if let Self::Continued {
            history,
            installed_profile,
            ..
        } = self
        {
            lineage.push(history.authentication_digest());
            lineage.push(digest(&installed_profile.digest)?);
        }
        Ok(())
    }
    pub(super) fn operational_lease(&self) -> Option<&VerifiedOperationalModelLeaseV2> {
        match self {
            Self::Initial(_) => None,
            Self::Continued { lease, .. } => Some(lease),
        }
    }
    pub(super) fn current_model_use(&self) -> Option<(&VerifiedOperationalModelLeaseV2, &Source)> {
        match self {
            Self::Initial(_) => None,
            Self::Continued {
                lease,
                body_implementation,
                ..
            } => Some((lease, body_implementation)),
        }
    }
    pub(super) fn revalidate_current(&self) -> HostResult<()> {
        match self {
            Self::Initial(e) => e.revalidate_current(),
            Self::Continued {
                history,
                lease,
                installed_profile,
                body_implementation,
                ..
            } => {
                history.revalidate_integrity()?;
                installed_profile.read(64 * 1024)?;
                body_implementation.read(1024 * 1024)?;
                lease.revalidate_current()
            }
        }
    }
}

fn measured_at(value: &Value) -> HostResult<u64> {
    value["measured_at_ms"]
        .as_u64()
        .ok_or_else(|| "actual independent measured instant".into())
}
