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
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_memory::CognitiveCheckpointReceipt;
use codex_hepta_memory::VerifiedCognitiveMaterial;

pub(super) struct RegisteredWriter {
    pub(super) registration: HostAuthorityWriterRegistration,
    leases: AuthorityLeaseVerifier,
    pub(super) proof: HostSignedWriterAuthorizationV1,
}

impl RegisteredWriter {
    pub(super) fn matches_notes(&self, notes: &crate::RootNotesGrantAdmission) -> bool {
        notes.matches_writer(&self.registration, &self.proof)
    }

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
        backend: &RegisteredCheckpoint,
        bytes: &[u8],
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        let material = backend.prepare_material(bytes).map_err(unavailable)?;
        self.registration
            .with_live(&self.leases, |_| {
                if issuer.retained_writer_authorization(&self.registration)? != self.proof {
                    return Err(io::Error::other("retained writer proof changed"));
                }
                let response = backend.backend.exchange_with_material(bytes, material.as_ref()).map_err(io::Error::other)?;
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

    pub(super) fn accept_material_registration(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        clock: &HostAuthorityClock,
        checkpoint: &RegisteredCheckpoint,
        expected: &codex_hepta_memory::CognitiveCheckpointHead,
        material: &crate::authority_host_material::PreparedCheckpointMaterial,
    ) -> io::Result<()> {
        self.registration.with_live(&self.leases, |_| {
            if issuer.retained_writer_authorization(&self.registration)? != self.proof
                || checkpoint.backend.retained_current_for_root().map_err(io::Error::other)? != *expected
            {
                return Err(io::Error::other("writer or Current changed during material registration"));
            }
            material.validate(b"root:initial-current-material:v1", &expected.last_current)?;
            let head = issuer.revocations()?;
            let now = clock.refresh_projection().map_err(io::Error::other)?.observed_unix_ms;
            validate_observation_lease(&self.registration.authority_lease, &head, now)
        })
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


impl RegisteredWriter {
    pub(super) fn adopt_material_checkpoint(
        &self,
        issuer: &DeploymentFinalUseIssuer,
        clock: &Arc<HostAuthorityClock>,
        directory: Arc<RootAuthorityDirectory>,
        previous: &CognitiveCheckpointReceipt,
        predecessor: &crate::RetiredCheckpointPublisher,
        registration: crate::HostCognitiveCheckpointRegistration,
        successor: &crate::RetainedCheckpointPublisher,
        material: &VerifiedCognitiveMaterial,
    ) -> io::Result<crate::HostCognitiveCheckpoint> {
        self.registration.with_live(&self.leases, |_| {
            if issuer.retained_writer_authorization(&self.registration)? != self.proof {
                return Err(io::Error::other("retained writer proof changed"));
            }
            let head = issuer.revocations()?;
            let backend = crate::HostCognitiveCheckpoint::adopt_retained_material_after_root_restart(
                directory, previous, predecessor, registration, successor, clock.clone(), material,
            ).map_err(io::Error::other)?;
            // A durable CAS may already have committed. Later uncertainty is
            // never reported as an unchanged predecessor or an installed lane.
            if issuer.retained_writer_authorization(&self.registration)? != self.proof
                || issuer.revocations()? != head
            {
                return Err(io::Error::other("canonical writer changed after recovery CAS"));
            }
            material.verify_unchanged().map_err(io::Error::other)?;
            let now = clock.now_unix_ms().map_err(io::Error::other)?;
            validate_observation_lease(&self.registration.authority_lease, &head, now)?;
            Ok(backend)
        })
    }
}
