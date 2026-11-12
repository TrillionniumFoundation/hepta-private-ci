//! Bounded one-operation registry CAS under the actual retained Root writer.

use std::os::unix::net::UnixStream;
use std::time::Instant;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerTransportError;

use super::*;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct FactoryLease {
    pub(crate) epoch: u64,
    pub(crate) material: Option<String>,
    pub(crate) revocations: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Request {
    pub(crate) schema: u8,
    pub(crate) operation: String,
    pub(crate) request_id: u64,
    pub(crate) binding: String,
    pub(crate) command: Command,
}

#[derive(Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(crate) enum Command {
    Observe,
    Bind {
        expected: FactoryLease,
        material: String,
    },
    Confirm {
        expected: FactoryLease,
    },
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Response {
    pub(crate) schema: u8,
    pub(crate) operation: String,
    pub(crate) request_id: u64,
    pub(crate) binding: String,
    pub(crate) reply: Reply,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Reply {
    pub(crate) lease: FactoryLease,
    pub(crate) newly_bound: bool,
}

impl HostAuthorityService {
    pub(crate) fn serve_q24_model_factory(
        &self,
        factory: &RegisteredQ24ModelFactory,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
    ) -> io::Result<()> {
        self.serve_q24_model_factory_with_end(
            factory,
            config,
            registration,
            stream,
            policy,
            owner_pidfd,
            /*original_end*/ None,
        )
    }

    pub(crate) fn serve_q24_model_factory_until(
        &self,
        factory: &RegisteredQ24ModelFactory,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
        end: Instant,
    ) -> io::Result<()> {
        self.serve_q24_model_factory_with_end(
            factory,
            config,
            registration,
            stream,
            policy,
            owner_pidfd,
            Some(end),
        )
    }

    fn serve_q24_model_factory_with_end(
        &self,
        factory: &RegisteredQ24ModelFactory,
        config: &HostAuthorityServiceConfig,
        registration: &HostAuthorityRegistration,
        stream: UnixStream,
        policy: HostAuthorityPeerPolicy,
        owner_pidfd: OwnedFd,
        original_end: Option<Instant>,
    ) -> io::Result<()> {
        let mut next_request_id = 1;
        let pin = owner_pidfd.try_clone()?;
        let mut channel = HostAuthorityPeerChannel::from_stream(stream, policy, owner_pidfd)
            .map_err(io::Error::other)?;
        if let Some(end) = original_end {
            HostAuthorityPeerChannel::limit_original_end(&mut channel, end)
                .map_err(io::Error::other)?;
        }
        while channel
            .exchange(|bytes| {
                self.with_learning_profile(
                    config,
                    registration,
                    &pin,
                    &factory.learning,
                    |initial, proof| {
                        LiveFactoryProfile::require_context(
                            &factory.profile,
                            &self.identity,
                            &proof,
                            &initial,
                            &factory.learning.require_cell_scope(&initial)?,
                        )?;
                        let request: Request =
                            serde_json::from_slice(bytes).map_err(io::Error::other)?;
                        if request.schema != factory.profile.wire_schema()
                            || request.operation != factory.profile.purpose()
                            || request.binding != factory.profile.binding()
                            || request.request_id != next_request_id
                        {
                            return Err(io::Error::other("factory purpose/scope/sequence differs"));
                        }
                        next_request_id = next_request_id
                            .checked_add(1)
                            .ok_or_else(|| io::Error::other("factory sequence exhausted"))?;
                        let before = factory.current(config)?;
                        let revocations = Digest32::of_parts(&[
                            b"hepta.root.q24-factory-revocations.v1\0",
                            &serde_json::to_vec(&self.issuer.revocations()?)
                                .map_err(io::Error::other)?,
                        ])
                        .to_string();
                        let lease = FactoryLease {
                            epoch: before.epoch,
                            material: before.material.clone(),
                            revocations,
                        };
                        let now = self
                            .clock
                            .refresh_projection()
                            .map_err(io::Error::other)?
                            .observed_unix_ms
                            / 1000;
                        let (after, reply) = transition(&before, lease, request.command, now)?;
                        if after != before {
                            factory
                                .store
                                .compare_and_set(factory.profile.store_owner(), &before, &after)
                                .map_err(io::Error::other)?;
                        }
                        if factory.current(config)? != after {
                            return Err(io::Error::other("factory registry outcome uncertain"));
                        }
                        if reply.newly_bound
                            && self
                                .clock
                                .refresh_projection()
                                .map_err(io::Error::other)?
                                .observed_unix_ms
                                / 1000
                                >= factory.profile.expiry()
                        {
                            return Err(io::Error::other(
                                "factory binding crossed the original work deadline",
                            ));
                        }
                        serde_json::to_vec(&Response {
                            schema: factory.profile.wire_schema(),
                            operation: factory.profile.purpose().into(),
                            request_id: request.request_id,
                            binding: request.binding,
                            reply,
                        })
                        .map_err(io::Error::other)
                    },
                )
                .map_err(|_| HostIssuerTransportError::Unavailable)
            })
            .map_err(io::Error::other)?
        {}
        Ok(())
    }
}

fn transition(
    before: &FactoryRecord,
    lease: FactoryLease,
    command: Command,
    now: u64,
) -> io::Result<(FactoryRecord, Reply)> {
    before.validate()?;
    let mut after = before.clone();
    let mut result = Reply {
        lease,
        newly_bound: false,
    };
    match command {
        Command::Observe => {}
        Command::Confirm { expected } => {
            if expected != result.lease {
                return Err(io::Error::other("factory live authority or epoch changed"));
            }
        }
        Command::Bind { expected, material } => {
            if expected != result.lease {
                return Err(io::Error::other("factory bind predecessor changed"));
            }
            let digest = material.parse::<Digest32>().map_err(io::Error::other)?;
            if digest.is_zero() || digest.to_string() != material {
                return Err(io::Error::other(
                    "canonical original model material required",
                ));
            }
            match &before.material {
                Some(existing) if existing != &material => {
                    return Err(io::Error::other(
                        "factory already bound to different material",
                    ));
                }
                Some(_) => {}
                None => {
                    if now >= before.profile.expiry() {
                        return Err(io::Error::other(
                            "factory cannot bind new work after expiry",
                        ));
                    }
                    after.epoch = before
                        .epoch
                        .checked_add(1)
                        .ok_or_else(|| io::Error::other("factory epoch exhausted"))?;
                    after.material = Some(material);
                    result.lease.epoch = after.epoch;
                    result.lease.material = after.material.clone();
                    result.newly_bound = true;
                }
            }
        }
    }
    after.validate()?;
    Ok((after, result))
}

#[cfg(test)]
#[path = "authority_host_q24_model_transport_tests.rs"]
mod tests;
