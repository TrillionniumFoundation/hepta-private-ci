//! Typed, authority-free Communication role adapter.
//!
//! Communication is a control-plane boundary, not a second transport
//! runtime. The existing CNS owner remains responsible for route admission,
//! generation fencing, delivery, retry, and durable message state. This
//! adapter validates the immutable envelope that may be handed to that owner
//! and emits replayable qualification evidence.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_control_plane::CnsRouteV1;
use codex_hepta_control_plane::MAX_ORGAN_MESSAGE_BYTES;
use codex_hepta_control_plane::cns_route_digest_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::CellAdapterContextV1;
use crate::CellRoleAdapterErrorV1;
use crate::CellRoleStepV1;
use crate::digest_bytes;
use crate::step_receipt;

pub const COMMUNICATION_SCHEMA_V1: &str = "hepta.cell-role.communication.v1";
pub const COMMUNICATION_OWNER_MODULE: &str = "hepta-cns::message-owner";

/// The typed payload envelope supplied to the CNS message owner. Payload
/// bytes themselves remain with the transport owner; this value carries only
/// their bounded digest and size.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommunicationMessageV1 {
    pub message_id: StableId,
    pub sender: StableId,
    pub recipient: StableId,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub sequence: u64,
    pub payload_digest: Digest32,
    pub idempotency_key_digest: Digest32,
    pub payload_bytes: usize,
    pub expiry_unix_ms: u64,
}

impl CommunicationMessageV1 {
    pub fn validate(&self) -> Result<(), CommunicationErrorV1> {
        for (label, id) in [
            ("message", &self.message_id),
            ("sender", &self.sender),
            ("recipient", &self.recipient),
        ] {
            if id.as_str().is_empty() {
                return Err(CommunicationErrorV1::EmptyId(label));
            }
        }
        for (label, digest) in [
            ("scope", self.scope_digest),
            ("payload", self.payload_digest),
            ("idempotency", self.idempotency_key_digest),
        ] {
            if digest.is_zero() {
                return Err(CommunicationErrorV1::EmptyDigest(label));
            }
        }
        if self.sequence == 0 {
            return Err(CommunicationErrorV1::InvalidSequence);
        }
        if self.payload_bytes > MAX_ORGAN_MESSAGE_BYTES {
            return Err(CommunicationErrorV1::PayloadTooLarge {
                actual: self.payload_bytes,
            });
        }
        if self.expiry_unix_ms == 0 {
            return Err(CommunicationErrorV1::InvalidExpiry);
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Result<Digest32, CommunicationErrorV1> {
        self.validate()?;
        Ok(digest_bytes(
            COMMUNICATION_SCHEMA_V1.as_bytes(),
            &[
                self.message_id.as_str().as_bytes(),
                self.sender.as_str().as_bytes(),
                self.recipient.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                self.scope_digest.as_array(),
                &self.sequence.to_be_bytes(),
                self.payload_digest.as_array(),
                self.idempotency_key_digest.as_array(),
                &(self.payload_bytes as u64).to_be_bytes(),
                &self.expiry_unix_ms.to_be_bytes(),
            ],
        ))
    }
}

/// Alias used by transport owners that call the envelope a message envelope.
pub type CommunicationEnvelopeV1 = CommunicationMessageV1;

/// Qualification emitted before the CNS owner accepts a message for route
/// admission. It is a replay/fence observation and grants no delivery power.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommunicationQualificationReceiptV1 {
    pub message_digest: Digest32,
    pub generation: Generation,
    pub scope_digest: Digest32,
    pub sequence: u64,
    pub predecessor_sequence: Option<u64>,
    pub observed_at_unix_ms: u64,
    pub fence_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CommunicationQualificationReceiptV1 {
    pub fn validate(&self) -> Result<(), CommunicationErrorV1> {
        if self.message_digest.is_zero()
            || self.scope_digest.is_zero()
            || self.fence_digest.is_zero()
        {
            return Err(CommunicationErrorV1::EmptyDigest("qualification"));
        }
        if self.sequence == 0 {
            return Err(CommunicationErrorV1::InvalidSequence);
        }
        if self.observed_at_unix_ms == 0 {
            return Err(CommunicationErrorV1::InvalidObservationTime);
        }
        if self.authority.grants_any() {
            return Err(CommunicationErrorV1::ReplayMismatch);
        }
        if let Some(previous) = self.predecessor_sequence
            && previous.checked_add(1) != Some(self.sequence)
        {
            return Err(CommunicationErrorV1::SequenceRegression {
                previous,
                current: self.sequence,
            });
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommunicationReplayReceiptV1 {
    pub message_digest: Digest32,
    pub replay_digest: Digest32,
    pub fence_digest: Digest32,
    pub matched: bool,
}

/// Binding handed to the existing CNS route owner. It connects a qualified
/// message to one admitted route and its current route fence, without
/// performing dispatch or changing the route table.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommunicationRouteBindingV1 {
    pub message_digest: Digest32,
    pub route_digest: Digest32,
    pub route_fence_digest: Digest32,
    pub generation: Generation,
    pub binding_digest: Digest32,
}

pub type CommunicationResultV1 = CommunicationMessageV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CommunicationErrorV1 {
    Adapter(CellRoleAdapterErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    GenerationMismatch,
    ScopeMismatch,
    InvalidRoute,
    InvalidSequence,
    SequenceRegression { previous: u64, current: u64 },
    PayloadTooLarge { actual: usize },
    InvalidExpiry,
    InvalidObservationTime,
    Expired,
    ReplayMismatch,
}

impl fmt::Display for CommunicationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CommunicationErrorV1 {}

impl From<CellRoleAdapterErrorV1> for CommunicationErrorV1 {
    fn from(error: CellRoleAdapterErrorV1) -> Self {
        Self::Adapter(error)
    }
}

impl From<CellRoleContractErrorV1> for CommunicationErrorV1 {
    fn from(error: CellRoleContractErrorV1) -> Self {
        Self::Adapter(CellRoleAdapterErrorV1::Contract(error))
    }
}

pub struct CommunicationAdapterV1;

impl CommunicationAdapterV1 {
    pub const OWNER_MODULE: &'static str = COMMUNICATION_OWNER_MODULE;

    /// Validate the typed message and project it into the common role receipt.
    /// The CNS transport owner still owns delivery and durable ordering.
    pub fn adapt(
        context: &CellAdapterContextV1,
        message: &CommunicationMessageV1,
    ) -> Result<CellRoleStepV1<CommunicationResultV1>, CommunicationErrorV1> {
        context.validate(CellRoleV1::Communication)?;
        message.validate()?;
        validate_context(context, message)?;
        let message_digest = message.content_digest()?;
        let state_successor_digest = digest_bytes(
            b"hepta.cell-role.communication-state.v1",
            &[
                context.state_predecessor_digest.as_array(),
                message_digest.as_array(),
                &message.sequence.to_be_bytes(),
            ],
        );
        let receipt = step_receipt(
            context,
            CellRoleV1::Communication,
            state_successor_digest,
            message_digest,
            0,
            0,
            CellStepStatusV1::Accepted,
        )?;
        Ok(CellRoleStepV1 {
            result: message.clone(),
            receipt,
        })
    }

    /// Check expiry and monotonic sequence before passing the envelope to the
    /// CNS message owner. `previous_sequence` comes from that owner's durable
    /// state; the adapter never stores or advances it.
    pub fn qualify(
        context: &CellAdapterContextV1,
        message: &CommunicationMessageV1,
        previous_sequence: Option<u64>,
        observed_at_unix_ms: u64,
    ) -> Result<CommunicationQualificationReceiptV1, CommunicationErrorV1> {
        context.validate(CellRoleV1::Communication)?;
        message.validate()?;
        validate_context(context, message)?;
        if observed_at_unix_ms == 0 {
            return Err(CommunicationErrorV1::InvalidObservationTime);
        }
        if observed_at_unix_ms > message.expiry_unix_ms {
            return Err(CommunicationErrorV1::Expired);
        }
        if let Some(previous) = previous_sequence {
            let expected = previous
                .checked_add(1)
                .ok_or(CommunicationErrorV1::InvalidSequence)?;
            if message.sequence != expected {
                return Err(CommunicationErrorV1::SequenceRegression {
                    previous,
                    current: message.sequence,
                });
            }
        }
        let message_digest = message.content_digest()?;
        let predecessor_bytes = previous_sequence.unwrap_or(0).to_be_bytes();
        let fence_digest = digest_bytes(
            b"hepta.cell-role.communication-fence.v1",
            &[
                message_digest.as_array(),
                &message.generation.get().to_be_bytes(),
                message.scope_digest.as_array(),
                &message.sequence.to_be_bytes(),
                &predecessor_bytes,
                &observed_at_unix_ms.to_be_bytes(),
            ],
        );
        Ok(CommunicationQualificationReceiptV1 {
            message_digest,
            generation: message.generation,
            scope_digest: message.scope_digest,
            sequence: message.sequence,
            predecessor_sequence: previous_sequence,
            observed_at_unix_ms,
            fence_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    /// Recompute a persisted qualification with the CNS owner's predecessor
    /// sequence and verify its generation/scope fence.
    pub fn replay(
        context: &CellAdapterContextV1,
        message: &CommunicationMessageV1,
        receipt: &CommunicationQualificationReceiptV1,
    ) -> Result<CommunicationReplayReceiptV1, CommunicationErrorV1> {
        receipt.validate()?;
        let replayed = Self::qualify(
            context,
            message,
            receipt.predecessor_sequence,
            receipt.observed_at_unix_ms,
        )?;
        let replay_digest = digest_bytes(
            b"hepta.cell-role.communication-replay.v1",
            &[
                replayed.message_digest.as_array(),
                replayed.fence_digest.as_array(),
            ],
        );
        Ok(CommunicationReplayReceiptV1 {
            message_digest: receipt.message_digest,
            replay_digest,
            fence_digest: replayed.fence_digest,
            matched: replayed == *receipt,
        })
    }

    /// Bind a qualified message to the exact CNS route and route-fence
    /// observation that the transport owner will use for delivery.
    pub fn bind_route(
        qualification: &CommunicationQualificationReceiptV1,
        route: &CnsRouteV1,
        route_fence_digest: Digest32,
    ) -> Result<CommunicationRouteBindingV1, CommunicationErrorV1> {
        qualification.validate()?;
        if route.generation != qualification.generation {
            return Err(CommunicationErrorV1::GenerationMismatch);
        }
        if route.cns.as_str().is_empty()
            || route.hierarchy_digest.is_zero()
            || route.source.system.as_str().is_empty()
            || route.source.organ.as_str().is_empty()
            || route.source.driver.as_str().is_empty()
            || route.targets.is_empty()
            || route.targets.iter().any(|target| {
                target.system.as_str().is_empty()
                    || target.organ.as_str().is_empty()
                    || target.driver.as_str().is_empty()
            })
        {
            return Err(CommunicationErrorV1::InvalidRoute);
        }
        if route_fence_digest.is_zero() {
            return Err(CommunicationErrorV1::EmptyDigest("route fence"));
        }
        let route_digest = cns_route_digest_v1(route);
        let binding_digest = digest_bytes(
            b"hepta.cell-role.communication-route-binding.v1",
            &[
                qualification.message_digest.as_array(),
                route_digest.as_array(),
                route_fence_digest.as_array(),
                qualification.fence_digest.as_array(),
            ],
        );
        Ok(CommunicationRouteBindingV1 {
            message_digest: qualification.message_digest,
            route_digest,
            route_fence_digest,
            generation: route.generation,
            binding_digest,
        })
    }
}

fn validate_context(
    context: &CellAdapterContextV1,
    message: &CommunicationMessageV1,
) -> Result<(), CommunicationErrorV1> {
    if context.generation != message.generation {
        return Err(CommunicationErrorV1::GenerationMismatch);
    }
    if context.scope_digest != message.scope_digest {
        return Err(CommunicationErrorV1::ScopeMismatch);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CellAdapterContextV1;
    use codex_hepta_control_plane::OrganPathV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::of_bytes(&[value])
    }

    fn context() -> CellAdapterContextV1 {
        CellAdapterContextV1 {
            cell_id: id("communication.cell"),
            generation: Generation::new(3).expect("generation"),
            scope_digest: digest(1),
            role: CellRoleV1::Communication,
            capability_digest: digest(2),
            input_frontier_digest: digest(3),
            state_predecessor_digest: digest(4),
            resource_receipt_digest: digest(5),
            evidence_digest: digest(6),
        }
    }

    fn message(sequence: u64) -> CommunicationMessageV1 {
        CommunicationMessageV1 {
            message_id: id("message.1"),
            sender: id("cell.sender"),
            recipient: id("cell.recipient"),
            generation: Generation::new(3).expect("generation"),
            scope_digest: digest(1),
            sequence,
            payload_digest: digest(7),
            idempotency_key_digest: digest(8),
            payload_bytes: 16,
            expiry_unix_ms: 200,
        }
    }

    #[test]
    fn communication_adapts_and_qualifies_without_authority() {
        let step = CommunicationAdapterV1::adapt(&context(), &message(1)).expect("step");
        assert_eq!(step.receipt.role, CellRoleV1::Communication);
        assert_eq!(step.receipt.authority, AuthorityPosture::DENY_ALL);
        let qualification =
            CommunicationAdapterV1::qualify(&context(), &message(1), None, 100).expect("qualify");
        assert_eq!(qualification.sequence, 1);
        assert_eq!(qualification.authority, AuthorityPosture::DENY_ALL);
    }

    #[test]
    fn communication_replay_binds_sequence_and_fence() {
        let qualification = CommunicationAdapterV1::qualify(&context(), &message(2), Some(1), 100)
            .expect("qualify");
        let replay = CommunicationAdapterV1::replay(&context(), &message(2), &qualification)
            .expect("replay");
        assert!(replay.matched);
        assert_eq!(replay.message_digest, qualification.message_digest);
        assert_eq!(replay.fence_digest, qualification.fence_digest);
    }

    #[test]
    fn communication_binds_to_the_existing_cns_route_fence() {
        let qualification =
            CommunicationAdapterV1::qualify(&context(), &message(1), None, 100).expect("qualify");
        let route = CnsRouteV1 {
            cns: id("cns.main"),
            generation: Generation::new(3).expect("generation"),
            hierarchy_digest: digest(10),
            source: OrganPathV1 {
                system: id("system.main"),
                organ: id("organ.source"),
                driver: id("driver.source"),
            },
            output_port: 0,
            targets: vec![OrganPathV1 {
                system: id("system.main"),
                organ: id("organ.target"),
                driver: id("driver.target"),
            }],
        };
        let binding = CommunicationAdapterV1::bind_route(&qualification, &route, digest(11))
            .expect("route binding");
        assert_eq!(binding.generation, Generation::new(3).expect("generation"));
        assert_eq!(binding.message_digest, qualification.message_digest);
        assert!(!binding.binding_digest.is_zero());
    }

    #[test]
    fn communication_rejects_scope_generation_sequence_and_expiry() {
        let mut wrong_scope = message(1);
        wrong_scope.scope_digest = digest(9);
        assert_eq!(
            CommunicationAdapterV1::qualify(&context(), &wrong_scope, None, 100),
            Err(CommunicationErrorV1::ScopeMismatch)
        );
        assert_eq!(
            CommunicationAdapterV1::qualify(&context(), &message(3), Some(1), 100),
            Err(CommunicationErrorV1::SequenceRegression {
                previous: 1,
                current: 3
            })
        );
        assert_eq!(
            CommunicationAdapterV1::qualify(&context(), &message(1), None, 201),
            Err(CommunicationErrorV1::Expired)
        );
    }
}
