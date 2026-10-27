//! Read-only writer proof/observation lane. Registration is root-only and the
//! original registry dispatch fence covers every response, including I/O.

use super::*;
use crate::HOST_AUTHORITY_OBSERVATION_V2;
use crate::HOST_WRITER_AUTHORIZATION_V1;
use crate::HostAuthorityObservationResponseV2;
use crate::HostAuthorityWriterObservationV2;
use crate::HostAuthorityWriterRegistration;
use crate::HostSignedWriterAuthorizationV1;
use crate::HostWriterAuthorizationReadResponseV1;
use crate::root_failure_report::RootServiceDiagnostics;
use crate::root_failure_report::RootServicePhase;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;

pub(super) struct RegisteredWriter {
    pub(super) registration: HostAuthorityWriterRegistration,
    leases: AuthorityLeaseVerifier,
    pub(super) proof: HostSignedWriterAuthorizationV1,
}

impl RegisteredWriter {
    pub(super) fn exchange_consumer(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        clock: &HostAuthorityClock,
        backend: &crate::HostConsumerFrontier,
        bytes: &[u8],
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        self.registration
            .with_live(&self.leases, |_| {
                if issuer.retained_writer_authorization(&self.registration)? != self.proof {
                    return Err(io::Error::other("retained writer proof changed"));
                }
                let before = issuer.revocations()?;
                let response = backend.exchange(bytes, &before).map_err(io::Error::other)?;
                let after = issuer.revocations()?;
                if after != before {
                    return Err(io::Error::other(
                        "issuer head changed during consumer exchange",
                    ));
                }
                let now = clock.now_unix_ms().map_err(io::Error::other)?;
                validate_observation_lease(&self.registration.authority_lease, &after, now)?;
                Ok(response)
            })
            .map_err(unavailable)
    }

    pub(super) fn exchange_checkpoint(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        clock: &HostAuthorityClock,
        backend: &crate::HostCognitiveCheckpoint,
        bytes: &[u8],
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        self.registration
            .with_live(&self.leases, |_| {
                if issuer.retained_writer_authorization(&self.registration)? != self.proof {
                    return Err(io::Error::other("retained writer proof changed"));
                }
                let response = backend.exchange(bytes).map_err(io::Error::other)?;
                let head = issuer.revocations()?;
                // A checkpoint reply needs actual post-I/O lease validation,
                // not publication of a new future clock projection. The original
                // current-time API reloads the protected record and renews it
                // once only when that actual post-I/O reading requires renewal.
                let now = clock.now_unix_ms().map_err(io::Error::other)?;
                validate_observation_lease(&self.registration.authority_lease, &head, now)?;
                Ok(response)
            })
            .map_err(unavailable)
    }

    pub(super) fn open(
        issuer: &DeploymentFinalUseIssuer,
        identity: &AgentdIdentity,
        registration: HostAuthorityWriterRegistration,
        leases: AuthorityLeaseVerifier,
    ) -> io::Result<Self> {
        if registration.registered_agent_id != identity.agent_id
            || registration.spawn_generation != identity.spawn_generation
        {
            return Err(io::Error::other("registered writer identity mismatch"));
        }
        let proof = registration.with_live(&leases, |_| {
            issuer.retained_writer_authorization(&registration)
        })?;
        Ok(Self {
            registration,
            leases,
            proof,
        })
    }

    pub(super) fn sign_objective(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        identity: &AgentdIdentity,
        body: AuthBusObjectiveBody,
    ) -> io::Result<AuthBusObjectiveIngress> {
        issuer.sign_registered_writer_objective(
            identity,
            body,
            &self.registration,
            &self.leases,
            &self.proof,
        )
    }

    pub(super) fn observe(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        clock: &HostAuthorityClock,
        identity: &AgentdIdentity,
        request: &ObservationRequest,
        diagnostics: &RootServiceDiagnostics,
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        match (request.schema_version, request.operation.as_str()) {
            (1, HOST_WRITER_AUTHORIZATION_V1) | (2, HOST_AUTHORITY_OBSERVATION_V2) => {}
            _ => return Err(HostIssuerTransportError::InvalidRequest),
        }
        // Local scalar only. The outer serve reports after releasing its channel.
        let failed_phase = std::cell::Cell::new(RootServicePhase::WriterObservation);
        self.registration
            .with_live(&self.leases, |store_revision| {
                failed_phase.set(RootServicePhase::WriterProof);
                let proof = issuer.retained_writer_authorization(&self.registration)?;
                if proof != self.proof {
                    return Err(io::Error::other("retained writer proof changed"));
                }
                failed_phase.set(RootServicePhase::WriterRevocations);
                let revocations = issuer.revocations()?;
                // All blocking reads precede this final projection. Nothing after
                // it writes a clock or substitutes a durable future ceiling for now.
                failed_phase.set(RootServicePhase::WriterProjection);
                let observation = if request.operation == HOST_AUTHORITY_OBSERVATION_V2 {
                    // Cover the complete request-start freshness lifetime with
                    // the already durable projection. This is a fixed producer
                    // requirement, not a request-selected time allowance.
                    clock.observe_projection(std::time::Duration::from_nanos(
                        crate::root_observation_cache::MAX_AGE_NS,
                    ))
                } else {
                    clock.refresh_projection()
                }
                .map_err(io::Error::other)?;
                failed_phase.set(RootServicePhase::WriterLeaseAfter);
                validate_observation_lease(
                    &self.registration.authority_lease,
                    &revocations,
                    observation.observed_unix_ms,
                )?;
                failed_phase.set(RootServicePhase::WriterEncoding);
                if request.operation == HOST_WRITER_AUTHORIZATION_V1 {
                    return encode_bounded(
                        &HostWriterAuthorizationReadResponseV1 {
                            schema_version: 1,
                            operation: HOST_WRITER_AUTHORIZATION_V1.into(),
                            proof,
                        },
                        16 * 1024,
                    )
                    .map_err(io::Error::other);
                }
                encode_bounded(
                    &HostAuthorityObservationResponseV2 {
                        schema_version: 2,
                        operation: HOST_AUTHORITY_OBSERVATION_V2.into(),
                        authority_epoch: revocations.authority_epoch,
                        revocations,
                        clock: observation.projection,
                        observed_unix_ms: observation.observed_unix_ms,
                        registered_agent_id: identity.agent_id.clone(),
                        spawn_generation: identity.spawn_generation,
                        writer: HostAuthorityWriterObservationV2 {
                            authority_lease: self.registration.authority_lease.clone(),
                            store_revision,
                            authority_lease_sha256: proof.claims.authority_lease_sha256.clone(),
                            owner_epoch: self.registration.owner_epoch,
                            local_lease_id: self.registration.local_lease_id.clone(),
                            local_lease_generation: self.registration.local_lease_generation,
                            writer_authorization_sha256: proof.sha256()?,
                        },
                    },
                    16 * 1024,
                )
                .map_err(io::Error::other)
            })
            .inspect_err(|error| {
                diagnostics.record_writer(failed_phase.get(), error);
            })
            .map_err(unavailable)
    }
}
