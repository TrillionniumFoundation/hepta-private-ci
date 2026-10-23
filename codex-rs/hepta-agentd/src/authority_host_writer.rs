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
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;

pub(super) struct RegisteredWriter {
    pub(super) registration: HostAuthorityWriterRegistration,
    leases: AuthorityLeaseVerifier,
    pub(super) proof: HostSignedWriterAuthorizationV1,
}

impl RegisteredWriter {
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
                let now = clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms;
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
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        match (request.schema_version, request.operation.as_str()) {
            (1, HOST_WRITER_AUTHORIZATION_V1) | (2, HOST_AUTHORITY_OBSERVATION_V2) => {}
            _ => return Err(HostIssuerTransportError::InvalidRequest),
        }
        self.registration
            .with_live(&self.leases, |store_revision| {
                let proof = issuer.retained_writer_authorization(&self.registration)?;
                if proof != self.proof {
                    return Err(io::Error::other("retained writer proof changed"));
                }
                let revocations = issuer.revocations()?;
                // All blocking reads precede this final projection. Nothing after
                // it writes a clock or substitutes a durable future ceiling for now.
                let observation = clock.refresh_projection().map_err(io::Error::other)?;
                validate_observation_lease(
                    &self.registration.authority_lease,
                    &revocations,
                    observation.observed_unix_ms,
                )?;
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
            .map_err(unavailable)
    }
}
