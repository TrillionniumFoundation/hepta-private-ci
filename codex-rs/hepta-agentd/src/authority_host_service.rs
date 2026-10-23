//! Root service lanes for the single canonical issuer. Registration is a
//! launcher input; no peer can choose an identity, lease, signer or publisher.

use std::io;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixStream;
use std::sync::Arc;

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::HostAuthorityClock;
use codex_hepta_contracts::HostAuthorityClockProjection;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdIdentity;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::DeploymentFinalUseIssuer;

#[path = "authority_host_writer.rs"]
mod writer;
use writer::RegisteredWriter;

/// A lane is fixed by its private listener, never selected by a wire request.
#[derive(Clone, Copy, Debug)]
pub enum HostAuthorityLane {
    Observation,
    Issuer,
    Checkpoint,
}

/// Three lanes share this exact original issuer/key/head/sequence. The clock
/// and registered identity are retained by the root launcher, not supplied in
/// requests. Missing checkpoint registration never initializes a cut.
pub struct HostAuthorityService {
    issuer: Arc<DeploymentFinalUseIssuer>,
    clock: Arc<HostAuthorityClock>,
    identity: AgentdIdentity,
    writer: Option<RegisteredWriter>,
    notes: Option<crate::RootNotesGrantAdmission>,
}

impl HostAuthorityService {
    pub fn from_registered_owner(
        issuer: Arc<DeploymentFinalUseIssuer>,
        clock: Arc<HostAuthorityClock>,
        identity: AgentdIdentity,
    ) -> io::Result<Self> {
        if identity.spawn_generation == 0 {
            return Err(io::Error::other("registered spawn required"));
        }
        Ok(Self {
            issuer,
            clock,
            identity,
            writer: None,
            notes: None,
        })
    }

    /// Open a previously root-provisioned original writer proof. This does not
    /// create a lease/proof, select a peer identity or activate a publisher.
    pub fn with_registered_writer(
        mut self,
        registration: crate::HostAuthorityWriterRegistration,
        leases: codex_hepta_contracts::authority_lease::AuthorityLeaseVerifier,
    ) -> io::Result<Self> {
        self.writer = Some(RegisteredWriter::open(
            &self.issuer,
            &self.identity,
            registration,
            leases,
        )?);
        Ok(self)
    }

    /// Install one Root-created fixed Notes delegation for this same retained
    /// writer. The peer wire cannot create policy or select a lease identity.
    pub fn with_registered_notes(
        mut self,
        notes: crate::RootNotesGrantAdmission,
    ) -> io::Result<Self> {
        let writer = self.writer.as_ref()
            .ok_or_else(|| io::Error::other("registered writer required for Notes"))?;
        if !writer.matches_notes(&notes) {
            return Err(io::Error::other("Notes delegation writer mismatch"));
        }
        self.notes = Some(notes);
        Ok(self)
    }

    /// Serve one pre-accepted root-launcher channel until EOF or uncertainty.
    /// Independent lane threads keep observation out of an issuer work queue;
    /// underlying durability stalls still legitimately expire feed freshness.
    pub fn serve(
        &self,
        lane: HostAuthorityLane,
        stream: UnixStream,
        mut policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
    ) -> Result<(), HostIssuerTransportError> {
        let bound = match lane {
            HostAuthorityLane::Observation => 16 * 1024,
            HostAuthorityLane::Issuer => 64 * 1024,
            HostAuthorityLane::Checkpoint => 32 * 1024,
        };
        policy.request_bound = bound;
        policy.response_bound = bound;
        let mut channel = HostAuthorityPeerChannel::from_stream(stream, policy, owner_pidfd)?;
        while channel.exchange(|bytes| self.handle(lane, bytes))? {}
        Ok(())
    }

    fn handle(
        &self,
        lane: HostAuthorityLane,
        bytes: &[u8],
    ) -> Result<Vec<u8>, HostIssuerTransportError> {
        match lane {
            HostAuthorityLane::Observation => self.observe(bytes),
            HostAuthorityLane::Issuer => self.issue(bytes),
            // Until an independently registered protected head exists there is
            // no legitimate witness, implicit genesis or successful response.
            HostAuthorityLane::Checkpoint => Err(HostIssuerTransportError::Unavailable),
        }
    }

    fn observe(&self, bytes: &[u8]) -> Result<Vec<u8>, HostIssuerTransportError> {
        let request: ObservationRequest = decode(bytes)?;
        if request.operation != "runtime.authority.observation.v1" {
            return self
                .writer
                .as_ref()
                .ok_or(HostIssuerTransportError::Unavailable)?
                .observe(&self.issuer, &self.clock, &self.identity, &request);
        }
        if request.schema_version != 1 {
            return Err(HostIssuerTransportError::InvalidRequest);
        }
        self.issuer
            .with_live_lease(|lease| {
                if lease.binding.principal_id != self.identity.agent_id.as_str() {
                    return Err(io::Error::new(
                        io::ErrorKind::PermissionDenied,
                        "registered lease owner mismatch",
                    ));
                }
                let revocations = self.issuer.revocations()?;
                // The original lease fence remains held through these local reads.
                // Sample after durability work and refuse a lease expiring during it.
                // Do not do another clock-writing verification after this projection.
                let observation = self.clock.refresh_projection().map_err(io::Error::other)?;
                validate_observation_lease(lease, &revocations, observation.observed_unix_ms)?;
                encode_bounded(
                    &ObservationResponse {
                        schema_version: 1,
                        operation: "runtime.authority.observation.v1",
                        authority_epoch: revocations.authority_epoch,
                        revocations,
                        clock: observation.projection,
                        observed_unix_ms: observation.observed_unix_ms,
                        registered_agent_id: self.identity.agent_id.as_str(),
                        spawn_generation: self.identity.spawn_generation,
                    },
                    16 * 1024,
                )
                .map_err(io::Error::other)
            })
            .map_err(unavailable)
    }

    fn issue(&self, bytes: &[u8]) -> Result<Vec<u8>, HostIssuerTransportError> {
        let request: IssuerRequest = decode(bytes)?;
        match request {
            IssuerRequest::FinalUse {
                schema_version,
                binding,
            } => {
                if schema_version != 1 || bytes.len() > 16 * 1024 {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                let result = match &self.notes {
                    Some(notes) => notes.issue(&self.issuer, &binding),
                    None => self.issuer.issue(&binding),
                };
                let grant = match result {
                    Ok(grant) => grant,
                    Err(error) if error.kind() == io::ErrorKind::PermissionDenied => None,
                    Err(error) => return Err(unavailable(error)),
                };
                let revocations = self.issuer.revocations().map_err(unavailable)?;
                let observation = self.clock.refresh_projection().map_err(unavailable)?;
                if grant.as_ref().is_some_and(|grant| {
                    observation.observed_unix_ms >= grant.grant.expires_at_unix_ms
                }) {
                    return Err(HostIssuerTransportError::Unavailable);
                }
                let denied = grant.is_none();
                encode_bounded(
                    &FinalUseResponse {
                        schema_version: 1,
                        revocations,
                        grant,
                        denial_reason: denied.then_some("authorization_denied"),
                    },
                    64 * 1024,
                )
            }
            IssuerRequest::Objective {
                schema_version,
                body,
            } => {
                if schema_version != 1 {
                    return Err(HostIssuerTransportError::InvalidRequest);
                }
                let ingress = self
                    .writer
                    .as_ref()
                    .ok_or(HostIssuerTransportError::Unavailable)?
                    .sign_objective(&self.issuer, &self.identity, body)
                    .map_err(unavailable)?;
                let observation = self.clock.refresh_projection().map_err(unavailable)?;
                if observation.observed_unix_ms >= ingress.expires_at_ms {
                    return Err(HostIssuerTransportError::Unavailable);
                }
                encode_bounded(
                    &ObjectiveResponse {
                        schema_version: 1,
                        operation: "runtime.authbus.objective.signed.v1",
                        ingress,
                    },
                    64 * 1024,
                )
            }
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ObservationRequest {
    schema_version: u32,
    operation: String,
}

#[derive(Serialize)]
struct ObservationResponse<'a> {
    schema_version: u32,
    operation: &'static str,
    authority_epoch: u64,
    revocations: FinalUseRevocations,
    clock: HostAuthorityClockProjection,
    observed_unix_ms: u64,
    registered_agent_id: &'a str,
    spawn_generation: u64,
}

#[derive(Deserialize)]
#[serde(tag = "operation", deny_unknown_fields)]
enum IssuerRequest {
    #[serde(rename = "runtime.agentd.production_operation")]
    FinalUse {
        schema_version: u32,
        binding: FinalUseBinding,
    },
    #[serde(rename = "runtime.authbus.objective.sign.v1")]
    Objective {
        schema_version: u32,
        body: AuthBusObjectiveBody,
    },
}

#[derive(Serialize)]
struct FinalUseResponse {
    schema_version: u32,
    revocations: FinalUseRevocations,
    grant: Option<SignedFinalUseGrant>,
    denial_reason: Option<&'static str>,
}

#[derive(Serialize)]
struct ObjectiveResponse {
    schema_version: u32,
    operation: &'static str,
    ingress: AuthBusObjectiveIngress,
}

fn validate_observation_lease(
    lease: &codex_hepta_contracts::authority_lease::AuthorityLease,
    head: &FinalUseRevocations,
    post_io_unix_ms: u64,
) -> io::Result<()> {
    if lease.authority_epoch != head.authority_epoch
        || post_io_unix_ms < lease.issued_at_unix_ms
        || post_io_unix_ms >= lease.expires_at_unix_ms
    {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "lease no longer live after observation I/O",
        ));
    }
    Ok(())
}

fn decode<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, HostIssuerTransportError> {
    serde_json::from_slice(bytes).map_err(|_| HostIssuerTransportError::InvalidRequest)
}

fn encode_bounded(
    value: &impl Serialize,
    bound: usize,
) -> Result<Vec<u8>, HostIssuerTransportError> {
    let bytes = serde_json::to_vec(value).map_err(unavailable)?;
    if bytes.is_empty() || bytes.len() > bound {
        return Err(HostIssuerTransportError::Unavailable);
    }
    Ok(bytes)
}

fn unavailable(_: impl std::fmt::Display) -> HostIssuerTransportError {
    HostIssuerTransportError::Unavailable
}

#[cfg(test)]
#[path = "authority_host_service_tests.rs"]
mod tests;
