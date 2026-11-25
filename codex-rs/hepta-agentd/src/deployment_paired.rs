//! Original paired registration and optional fixed material custody.
//! Opening observes records only; the dedicated read has its own live boundary.
use super::*;
use crate::AgentdIdentity;
use crate::AuthBusTextIngress;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_contracts::authority_lease::AuthorityLeaseBinding;
use codex_hepta_contracts::authority_lease::AuthorityLeaseRegistry;
use codex_hepta_types::Digest32;

#[path = "deployment_paired_live.rs"]
mod live;
use live::PairedRootInspection;

#[path = "deployment_paired_entry.rs"]
mod entry;
pub(super) use entry::PairedMaterialEntriesV1;
use entry::PreparedMaterialEntry;
#[path = "deployment_paired_material.rs"]
mod material;
use material::FixedTrainingMaterials;
pub use material::PairedTrainingMaterialManifestV1;
#[path = "deployment_paired_consumer.rs"]
mod consumer;

/// Trusted launcher metadata, not proof of a human turn or material custody.
/// The original Registry must already contain the exact enrollment and effect.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct HostAuthorityPairedRegistration {
    pub preparation: crate::PairedPreparationRegistration,
    pub request: crate::PairedPreparationRequest,
    pub original_route: crate::text_session::AgentdTextSessionConfig,
    pub permission_revision: u64,
    pub human_expires_at_ms: u64,
    pub enrollment_revision: u64,
    pub effect_revision: u64,
    pub effect_lifetime_ms: u64,
}

/// Historical/current registration metadata only. It carries no use token,
/// queued receipt, grant, material, callback or permission for a later read.
#[derive(Debug, PartialEq, Eq)]
pub struct PairedRootObservation {
    pub original_delivery: Digest32,
    pub enrollment_revision: u64,
    pub effect_revision: u64,
    pub registry_revision: u64,
    pub observed_unix_ms: u64,
}

pub(crate) struct RegisteredRootPaired {
    issuer: Arc<DeploymentFinalUseIssuer>,
    registry: Arc<AuthorityLeaseRegistry>,
    writer: HostAuthorityWriterRegistration,
    proof: crate::HostSignedWriterAuthorizationV1,
    registration: HostAuthorityPairedRegistration,
    enrollment: AuthorityLease,
    effect: AuthorityLease,
    policy: DeploymentGrantPolicy,
    training_materials: Option<FixedTrainingMaterials>,
}

impl HostAuthorityPairedRegistration {
    fn bindings(
        &self,
        writer: &HostAuthorityWriterRegistration,
    ) -> io::Result<(
        AuthorityLeaseBinding,
        AuthorityLeaseBinding,
        DeploymentGrantPolicy,
    )> {
        writer.validate()?;
        self.request.original.validate().map_err(io::Error::other)?;
        let p = &self.preparation;
        let r = &self.request;
        if [
            p.study,
            p.enrollment,
            p.frozen_materials,
            r.operation,
            r.materials,
        ]
        .into_iter()
        .any(Digest32::is_zero)
            || r.original.study != p.study
            || r.original.expected_principal != p.principal_id
            || r.materials != p.frozen_materials
            || self.original_route.agent_id != writer.registered_agent_id
            || self.original_route.spawn_generation != writer.spawn_generation
            || self.original_route.thread_id.is_empty()
            || self.permission_revision == 0
            || self.permission_revision != writer.authority_lease.revision
            || self.human_expires_at_ms == 0
            || self.enrollment_revision == 0
            || self.effect_revision == 0
            || !(1..=10_000).contains(&self.effect_lifetime_ms)
        {
            return Err(denied(
                "paired registration differs from original writer or request",
            ));
        }
        match r.original.usage {
            crate::PairedLearningDataUse::RequestConsumerRun { operation, .. }
            | crate::PairedLearningDataUse::ReportConsumerOutcome { operation, .. }
                if operation != r.operation =>
            {
                return Err(denied("paired operation differs from exact purpose"));
            }
            crate::PairedLearningDataUse::TrainOnFailureAndCorrection { .. }
            | crate::PairedLearningDataUse::EvaluateOnlyAfterFreeze { .. }
            | crate::PairedLearningDataUse::RequestConsumerRun { .. }
            | crate::PairedLearningDataUse::ReportConsumerOutcome { .. } => {}
        }
        let scope = Digest32::of_bytes(&serde_json::to_vec(&(
            "hepta.paired-learning.preparation-scope.v1",
            p.study.to_string(),
            p.enrollment.to_string(),
            p.principal_id.as_str(),
        ))?)
        .into_array();
        let enrollment = AuthorityLeaseBinding {
            principal_id: p.principal_id.clone(),
            operation_class: "runtime.hepta.paired_enrollment.v1".into(),
            destination_id: crate::paired_preparation::DESTINATION.into(),
            scope_sha256: scope,
            payload_sha256: Digest32::of_bytes(&serde_json::to_vec(&(
                "hepta.paired-enrollment.registration.v1",
                p.study.to_string(),
                p.enrollment.to_string(),
                p.frozen_materials.to_string(),
                p.principal_id.as_str(),
                p.policy_generation.get(),
            ))?)
            .into_array(),
        };
        let effect = AuthorityLeaseBinding {
            principal_id: writer.registered_agent_id.as_str().into(),
            operation_class: "runtime.hepta.paired_material_use.v1".into(),
            destination_id: crate::paired_preparation::DESTINATION.into(),
            scope_sha256: scope,
            payload_sha256: Digest32::of_bytes(&serde_json::to_vec(&serde_json::json!({
                "schema":"hepta.paired-root.effect-registration.v1",
                "enrollment":enrollment, "enrollment_revision":self.enrollment_revision,
                "delivery":r.original.delivery_id.to_string(), "turn":r.original.turn_id,
                "operation":r.operation.to_string(), "materials":r.materials.to_string(),
                "purpose":r.original.usage.consent_text(p.study),
                "route":self.original_route, "permission_revision":self.permission_revision,
                "human_expires_at_ms":self.human_expires_at_ms,
            }))?)
            .into_array(),
        };
        let policy = DeploymentGrantPolicy {
            subject_id: writer.registered_agent_id.as_str().into(),
            destination_id: effect.destination_id.clone(),
            scope_sha256: scope,
            lifetime_ms: self.effect_lifetime_ms,
        };
        Ok((enrollment, effect, policy))
    }

    fn effect_id(&self) -> String {
        format!(
            "paired-effect.original-delivery.v1.{}",
            self.request.original.delivery_id
        )
    }

    fn enrollment_id(&self) -> io::Result<String> {
        let identity = serde_json::to_vec(&(
            "hepta.paired-enrollment.identity.v1",
            self.preparation.study.to_string(),
            self.preparation.principal_id.as_str(),
        ))?;
        Ok(format!(
            "paired-enrollment.v1.{}",
            Digest32::of_bytes(&identity)
        ))
    }
}

impl RegisteredRootPaired {
    pub(crate) fn from_registered(
        issuer: Arc<DeploymentFinalUseIssuer>,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        registration: HostAuthorityPairedRegistration,
    ) -> io::Result<Self> {
        // SAFETY: geteuid only reads the current kernel credential.
        if unsafe { libc::geteuid() } != 0 {
            return Err(denied(
                "paired registration requires the original Root launcher",
            ));
        }
        Self::open(issuer, registry, writer, registration)
    }

    fn open(
        issuer: Arc<DeploymentFinalUseIssuer>,
        registry: Arc<AuthorityLeaseRegistry>,
        writer: HostAuthorityWriterRegistration,
        registration: HostAuthorityPairedRegistration,
    ) -> io::Result<Self> {
        let (expected_enrollment, expected_effect, policy) = registration.bindings(&writer)?;
        let enrollment = registry
            .read_lease(&registration.enrollment_id()?)
            .map_err(root::lease_error)?
            .ok_or_else(|| denied("original paired enrollment missing"))?
            .lease;
        let effect = registry
            .read_lease(&registration.effect_id())
            .map_err(root::lease_error)?
            .ok_or_else(|| denied("original paired effect missing"))?
            .lease;
        if enrollment.binding != expected_enrollment
            || effect.binding != expected_effect
            || enrollment.revision != registration.enrollment_revision
            || effect.revision != registration.effect_revision
            || effect.issued_at_unix_ms < enrollment.issued_at_unix_ms
            || effect.issued_at_unix_ms < writer.authority_lease.issued_at_unix_ms
            || effect.expires_at_unix_ms > enrollment.expires_at_unix_ms
            || effect.expires_at_unix_ms > writer.authority_lease.expires_at_unix_ms
            || effect.expires_at_unix_ms > registration.human_expires_at_ms
            || effect
                .expires_at_unix_ms
                .checked_sub(effect.issued_at_unix_ms)
                .is_none_or(|length| length == 0 || length > registration.effect_lifetime_ms)
        {
            return Err(denied(
                "retained paired records differ; no replacement is allowed",
            ));
        }
        let proof = issuer.retained_writer_authorization(&writer)?;
        let owner = Self {
            issuer,
            registry,
            writer,
            proof,
            registration,
            enrollment,
            effect,
            policy,
            training_materials: None,
        };
        owner.observe()?;
        Ok(owner)
    }

    pub(crate) fn observe(&self) -> io::Result<PairedRootObservation> {
        self.inspect(PairedRootInspection::RegistrationOnly)
    }

    pub(crate) fn observe_original_human(
        &self,
        identity: &AgentdIdentity,
        ingress: &AuthBusTextIngress,
        held: &crate::authority_host_service::OriginalHumanLifetime<'_>,
    ) -> io::Result<PairedRootObservation> {
        self.inspect(PairedRootInspection::OriginalHuman {
            identity,
            ingress,
            held,
        })
    }

    fn inspect(&self, inspection: PairedRootInspection<'_>) -> io::Result<PairedRootObservation> {
        let pinned = self
            .issuer
            .lease
            .as_ref()
            .ok_or_else(|| denied("original protected issuer missing"))?;
        let verifier = self.registry.verifier();
        let token = |lease: &AuthorityLease| {
            verifier
                .verify_use(&lease.lease_id, lease.revision, &lease.binding)
                .map_err(root::lease_error)
        };
        pinned
            .verifier
            .with_pinned_issuer_paired_dispatch_boundary(
                pinned.identity(),
                (
                    token(&self.writer.authority_lease)?,
                    &self.writer.authority_lease.binding,
                ),
                (token(&self.effect)?, &self.effect.binding),
                (token(&self.enrollment)?, &self.enrollment.binding),
                |issuer, writer, effect, enrollment, entered_now, revision| {
                    if writer != &self.writer.authority_lease
                        || effect != &self.effect
                        || enrollment != &self.enrollment
                        || effect.expires_at_unix_ms > issuer.expires_at_unix_ms
                    {
                        return Err(denied("original paired dependency record changed"));
                    }
                    // Original lock order: Registry, then issuer request lock.
                    // This callback never reenters the Registry or reads material.
                    let _guard = self
                        .issuer
                        .request_lock
                        .lock()
                        .map_err(|_| denied("issuer fenced"))?;
                    let state = self
                        .issuer
                        .store
                        .load(STATE_OWNER)
                        .map_err(io::Error::other)?;
                    let routes: Vec<_> = state
                        .policies
                        .iter()
                        .filter(|policy| policy.destination_id == self.policy.destination_id)
                        .collect();
                    if routes != vec![&self.policy]
                        || self.issuer.retained_writer_authorization(&self.writer)? != self.proof
                    {
                        return Err(denied("original paired policy or writer proof changed"));
                    }
                    let now = self.issuer.clock.now_unix_ms().map_err(io::Error::other)?;
                    if now < entered_now
                        || [issuer, writer, effect, enrollment]
                            .iter()
                            .any(|lease| now >= lease.expires_at_unix_ms)
                        || now >= self.registration.human_expires_at_ms
                    {
                        return Err(denied(
                            "paired observation expired during original owner readback",
                        ));
                    }
                    let now = inspection.verify(self, &state, now)?;
                    if [issuer, writer, effect, enrollment]
                        .iter()
                        .any(|lease| now >= lease.expires_at_unix_ms)
                        || now >= self.registration.human_expires_at_ms
                    {
                        return Err(denied(
                            "paired dependencies expired during original human check",
                        ));
                    }
                    Ok(PairedRootObservation {
                        original_delivery: self.registration.request.original.delivery_id,
                        enrollment_revision: enrollment.revision,
                        effect_revision: effect.revision,
                        registry_revision: revision,
                        observed_unix_ms: now,
                    })
                },
            )
            .map_err(root::lease_error)?
    }
}

fn denied(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, message)
}

#[cfg(test)]
#[path = "deployment_paired_tests.rs"]
mod tests;
