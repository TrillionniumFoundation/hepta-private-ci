//! Read only the original Root-pinned signed distribution on the same live
//! Initial lane. Peer data cannot supply a key, signer, role or trust path.

use std::time::Instant;

use super::*;
use crate::root_initial_learning_trust_data::LearningTrustPayloadV1;
use crate::root_initial_learning_trust_data::LearningTrustPinV1;

pub(crate) const LEARNING_TRUST_PURPOSE: &str = "runtime.circuit.learning-trust.read.v1";

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct LearningTrustResponseV1 {
    pub(crate) schema: u8,
    pub(crate) purpose: String,
    pub(crate) request_id: u64,
    pub(crate) profile: String,
    pub(crate) pin: LearningTrustPinV1,
    pub(crate) payload: LearningTrustPayloadV1,
}

pub(super) struct OriginalLearningTrustExchange<'a> {
    service: &'a HostAuthorityService,
    slot: &'a RegisteredGenerationInitial,
    config: &'a HostAuthorityServiceConfig,
    registration: &'a HostAuthorityRegistration,
    owner: &'a OwnedFd,
    end: Instant,
}

impl<'a> OriginalLearningTrustExchange<'a> {
    pub(super) fn new(
        service: &'a HostAuthorityService,
        slot: &'a RegisteredGenerationInitial,
        config: &'a HostAuthorityServiceConfig,
        registration: &'a HostAuthorityRegistration,
        owner: &'a OwnedFd,
        end: Instant,
    ) -> Self {
        Self {
            service,
            slot,
            config,
            registration,
            owner,
            end,
        }
    }

    pub(super) fn exchange(&self, request: &Request, sequence: &mut u64) -> io::Result<Vec<u8>> {
        let mut encoded = None;
        let result = self.service.with_initial_publication_context(
            self.config,
            self.registration,
            self.owner,
            |proof| {
                let slot = self.slot;
                if Instant::now() >= self.end
                    || request.schema != 1
                    || request.purpose != LEARNING_TRUST_PURPOSE
                    || request.request_id != *sequence
                    || request.profile != slot.profile.binding
                    || !matches!(&request.command, Command::ReadLearningTrust {})
                    || slot.profile.writer != proof
                    || slot.profile.identity
                        != crate::neuron_generation_process_identity_digest_v1(
                            &self.service.identity,
                        )
                        .map_err(io::Error::other)?
                        .to_string()
                {
                    return Err(io::Error::other("original learning trust context differs"));
                }
                *sequence = sequence
                    .checked_add(1)
                    .ok_or_else(|| io::Error::other("initial sequence exhausted"))?;
                slot.require_profile()?;
                let now = self
                    .service
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms;
                slot.require_selection(now)?;
                let revocations = self.service.issuer.revocations()?;
                let current = slot
                    .current
                    .try_lock()
                    .map_err(|_| io::Error::other("initial CURRENT busy"))?;
                let before = read_current(slot, current.as_ref())?;
                if before.is_none() || before.as_ref() == Some(&slot.profile.prepared) {
                    return Err(io::Error::other(
                        "published Initial CURRENT required for learning trust",
                    ));
                }
                require_observation(slot, before.as_ref(), &revocations)?;
                let original = slot
                    .learning_trust
                    .as_ref()
                    .ok_or_else(|| io::Error::other("original learning trust was not enrolled"))?;
                let response = LearningTrustResponseV1 {
                    schema: 1,
                    purpose: LEARNING_TRUST_PURPOSE.into(),
                    request_id: request.request_id,
                    profile: slot.profile.binding.clone(),
                    pin: original.pin.clone(),
                    payload: original.read_original_payload(now)?,
                };
                let raw = serde_json::to_vec(&response).map_err(io::Error::other)?;
                if raw.len() > 16 * 1024 {
                    return Err(io::Error::other("original learning trust response bound"));
                }
                slot.require_profile()?;
                let after = self
                    .service
                    .clock
                    .refresh_projection()
                    .map_err(io::Error::other)?
                    .observed_unix_ms;
                slot.require_selection(after)?;
                require_observation(slot, before.as_ref(), &revocations)?;
                if self.service.issuer.revocations()? != revocations
                    || read_current(slot, current.as_ref())? != before
                    || Instant::now() >= self.end
                {
                    return Err(io::Error::other(
                        "original learning trust read became uncertain",
                    ));
                }
                encoded = Some(raw);
                Ok(())
            },
        );
        if result.is_err() || Instant::now() >= self.end {
            self.slot.fence()?;
            result?;
            return Err(io::Error::other("original learning trust deadline expired"));
        }
        encoded.ok_or_else(|| io::Error::other("original learning trust reply absent"))
    }
}
