//! Evidence binding and fail-closed continuation for trusted read-only fanout.
//!
//! The synchronous host remains the sole dispatcher. This module does not
//! replay a target or grant authority. It gives a product owner a canonical
//! receipt digest to retain independently and a validated cursor identifying
//! the first incomplete route after an exact delivered prefix.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::HostedOrganStateV1;
use crate::OrganFanoutReceiptV1;
use crate::OrganRuntimeError;
use crate::OrganTargetDeliveryDispositionV1;
use crate::OrganTargetDeliveryReceiptV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OrganFanoutContinuationV1 {
    /// Digest the product owner must retain independently from the receipt.
    pub receipt_evidence_digest: Digest32,
    /// Exact attempt identity over generation, source, output port, payload and
    /// the complete ordered admitted route sequence.
    pub fanout_identity_digest: Digest32,
    pub predecessor_generation: Generation,
    pub next_route_index: usize,
    pub next_target: StableId,
    pub next_input_port: usize,
    pub next_delivery_identity_digest: Digest32,
    pub delivered_prefix_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OrganFanoutRecoveryErrorV1 {
    AuthorityEscalated,
    ReceiptEvidenceMismatch,
    InvalidTargetEvidence { route_index: usize },
    IncompleteDeliveredEvidence { route_index: usize },
    InvalidDispositionOrder { route_index: usize },
    ErrorDispositionMismatch,
    UnsupportedDispatchError,
    NoRetryTarget,
}

impl OrganFanoutReceiptV1 {
    /// Return the canonical digest a product owner can persist beside its own
    /// recovery record. Recomputing this digest from an untrusted receipt is not
    /// authentication; `continuation` requires the independently retained value.
    pub fn evidence_digest(&self) -> Result<Digest32, OrganFanoutRecoveryErrorV1> {
        if self.authority.grants_any() {
            return Err(OrganFanoutRecoveryErrorV1::AuthorityEscalated);
        }
        let fanout_identity_digest = fanout_identity_digest(self);
        let mut bytes = b"hepta.control.organ-fanout-evidence.v1\0".to_vec();
        bytes.extend_from_slice(fanout_identity_digest.as_array());
        push_usize(&mut bytes, self.targets.len());
        for (route_index, target) in self.targets.iter().enumerate() {
            bytes.extend_from_slice(
                delivery_identity_digest(fanout_identity_digest, route_index, target).as_array(),
            );
            bytes.push(match target.disposition {
                OrganTargetDeliveryDispositionV1::Delivered => 1,
                OrganTargetDeliveryDispositionV1::DeliveredOutputUnavailable => 2,
                OrganTargetDeliveryDispositionV1::Failed => 3,
                OrganTargetDeliveryDispositionV1::NotAttempted => 4,
            });
            push_optional_digest(&mut bytes, target.output_digest);
            push_optional_id(&mut bytes, target.fault_code.as_ref());
        }
        push_dispatch_error(&mut bytes, self.error.as_ref())?;
        Ok(Digest32::of_bytes(&bytes))
    }

    /// Validate an independently anchored receipt and return only the first
    /// incomplete route. The cursor remains `DENY_ALL`; the product owner must
    /// separately decide whether retry is safe and provide downstream
    /// idempotency. Missing output evidence for an already delivered route
    /// fails closed because replay could duplicate a completed call.
    pub fn continuation(
        &self,
        expected_evidence_digest: Digest32,
    ) -> Result<Option<OrganFanoutContinuationV1>, OrganFanoutRecoveryErrorV1> {
        let observed_evidence_digest = self.evidence_digest()?;
        if observed_evidence_digest != expected_evidence_digest {
            return Err(OrganFanoutRecoveryErrorV1::ReceiptEvidenceMismatch);
        }

        let first_incomplete = self.targets.iter().position(|target| {
            target.disposition != OrganTargetDeliveryDispositionV1::Delivered
        });
        let Some(first_incomplete) = first_incomplete else {
            if self.error.is_some() {
                return Err(OrganFanoutRecoveryErrorV1::ErrorDispositionMismatch);
            }
            for (route_index, target) in self.targets.iter().enumerate() {
                validate_delivered_target(target, route_index)?;
            }
            return Ok(None);
        };

        for (route_index, target) in self.targets[..first_incomplete].iter().enumerate() {
            if target.disposition == OrganTargetDeliveryDispositionV1::DeliveredOutputUnavailable {
                return Err(OrganFanoutRecoveryErrorV1::IncompleteDeliveredEvidence {
                    route_index,
                });
            }
            validate_delivered_target(target, route_index)?;
        }

        let next = &self.targets[first_incomplete];
        match next.disposition {
            OrganTargetDeliveryDispositionV1::DeliveredOutputUnavailable => {
                return Err(OrganFanoutRecoveryErrorV1::IncompleteDeliveredEvidence {
                    route_index: first_incomplete,
                });
            }
            OrganTargetDeliveryDispositionV1::Failed => {
                if next.output_digest.is_some() {
                    return Err(OrganFanoutRecoveryErrorV1::InvalidTargetEvidence {
                        route_index: first_incomplete,
                    });
                }
            }
            OrganTargetDeliveryDispositionV1::NotAttempted => {
                if next.output_digest.is_some() || next.fault_code.is_some() {
                    return Err(OrganFanoutRecoveryErrorV1::InvalidTargetEvidence {
                        route_index: first_incomplete,
                    });
                }
            }
            OrganTargetDeliveryDispositionV1::Delivered => unreachable!(),
        }
        for (offset, target) in self.targets[first_incomplete + 1..].iter().enumerate() {
            let route_index = first_incomplete + 1 + offset;
            if target.disposition != OrganTargetDeliveryDispositionV1::NotAttempted
                || target.output_digest.is_some()
                || target.fault_code.is_some()
            {
                return Err(OrganFanoutRecoveryErrorV1::InvalidDispositionOrder {
                    route_index,
                });
            }
        }

        let error = self
            .error
            .as_ref()
            .ok_or(OrganFanoutRecoveryErrorV1::ErrorDispositionMismatch)?;
        validate_dispatch_error(error, &self.targets, first_incomplete)?;

        let fanout_identity_digest = fanout_identity_digest(self);
        Ok(Some(OrganFanoutContinuationV1 {
            receipt_evidence_digest: observed_evidence_digest,
            fanout_identity_digest,
            predecessor_generation: self.generation,
            next_route_index: first_incomplete,
            next_target: next.target.clone(),
            next_input_port: next.input_port,
            next_delivery_identity_digest: delivery_identity_digest(
                fanout_identity_digest,
                first_incomplete,
                next,
            ),
            delivered_prefix_digest: delivered_prefix_digest(
                fanout_identity_digest,
                &self.targets[..first_incomplete],
            ),
            authority: AuthorityPosture::DENY_ALL,
        }))
    }
}

fn validate_delivered_target(
    target: &OrganTargetDeliveryReceiptV1,
    route_index: usize,
) -> Result<(), OrganFanoutRecoveryErrorV1> {
    if target.disposition != OrganTargetDeliveryDispositionV1::Delivered
        || target.output_digest.is_none()
        || target.fault_code.is_some()
    {
        return Err(OrganFanoutRecoveryErrorV1::InvalidTargetEvidence { route_index });
    }
    Ok(())
}

fn validate_dispatch_error(
    error: &OrganRuntimeError,
    targets: &[OrganTargetDeliveryReceiptV1],
    first_incomplete: usize,
) -> Result<(), OrganFanoutRecoveryErrorV1> {
    let next = targets
        .get(first_incomplete)
        .ok_or(OrganFanoutRecoveryErrorV1::NoRetryTarget)?;
    match error {
        OrganRuntimeError::HandleFailed { fault, delivered } => {
            if *delivered != first_incomplete
                || next.disposition != OrganTargetDeliveryDispositionV1::Failed
                || next.target != fault.organ
                || next.fault_code.as_ref() != Some(&fault.code)
            {
                return Err(OrganFanoutRecoveryErrorV1::ErrorDispositionMismatch);
            }
        }
        OrganRuntimeError::OutputTooLarge {
            organ, delivered, ..
        } => {
            if *delivered != first_incomplete
                || next.disposition != OrganTargetDeliveryDispositionV1::Failed
                || next.target != *organ
                || next.fault_code.is_some()
            {
                return Err(OrganFanoutRecoveryErrorV1::ErrorDispositionMismatch);
            }
        }
        OrganRuntimeError::GenerationMismatch { .. }
        | OrganRuntimeError::InputTooLarge { .. }
        | OrganRuntimeError::UnknownSource { .. }
        | OrganRuntimeError::OrganNotReady { .. }
        | OrganRuntimeError::InvalidOutputPort { .. }
        | OrganRuntimeError::UnroutedOutput { .. } => {
            if first_incomplete != 0
                || next.disposition != OrganTargetDeliveryDispositionV1::NotAttempted
            {
                return Err(OrganFanoutRecoveryErrorV1::ErrorDispositionMismatch);
            }
        }
        _ => return Err(OrganFanoutRecoveryErrorV1::UnsupportedDispatchError),
    }
    Ok(())
}

fn fanout_identity_digest(receipt: &OrganFanoutReceiptV1) -> Digest32 {
    let mut bytes = b"hepta.control.organ-fanout-identity.v1\0".to_vec();
    bytes.extend_from_slice(&receipt.generation.get().to_be_bytes());
    push_id(&mut bytes, &receipt.source);
    push_usize(&mut bytes, receipt.output_port);
    bytes.extend_from_slice(receipt.payload_digest.as_array());
    push_usize(&mut bytes, receipt.targets.len());
    for (route_index, target) in receipt.targets.iter().enumerate() {
        push_usize(&mut bytes, route_index);
        push_id(&mut bytes, &target.target);
        push_usize(&mut bytes, target.input_port);
    }
    Digest32::of_bytes(&bytes)
}

fn delivery_identity_digest(
    fanout_identity_digest: Digest32,
    route_index: usize,
    target: &OrganTargetDeliveryReceiptV1,
) -> Digest32 {
    let mut bytes = b"hepta.control.organ-delivery-identity.v1\0".to_vec();
    bytes.extend_from_slice(fanout_identity_digest.as_array());
    push_usize(&mut bytes, route_index);
    push_id(&mut bytes, &target.target);
    push_usize(&mut bytes, target.input_port);
    Digest32::of_bytes(&bytes)
}

fn delivered_prefix_digest(
    fanout_identity_digest: Digest32,
    targets: &[OrganTargetDeliveryReceiptV1],
) -> Digest32 {
    let mut bytes = b"hepta.control.organ-delivered-prefix.v1\0".to_vec();
    bytes.extend_from_slice(fanout_identity_digest.as_array());
    push_usize(&mut bytes, targets.len());
    for (route_index, target) in targets.iter().enumerate() {
        bytes.extend_from_slice(
            delivery_identity_digest(fanout_identity_digest, route_index, target).as_array(),
        );
        if let Some(output_digest) = target.output_digest {
            bytes.extend_from_slice(output_digest.as_array());
        }
    }
    Digest32::of_bytes(&bytes)
}

fn push_dispatch_error(
    bytes: &mut Vec<u8>,
    error: Option<&OrganRuntimeError>,
) -> Result<(), OrganFanoutRecoveryErrorV1> {
    let Some(error) = error else {
        bytes.push(0);
        return Ok(());
    };
    match error {
        OrganRuntimeError::GenerationMismatch { expected, actual } => {
            bytes.push(1);
            bytes.extend_from_slice(&expected.get().to_be_bytes());
            bytes.extend_from_slice(&actual.get().to_be_bytes());
        }
        OrganRuntimeError::InputTooLarge { actual } => {
            bytes.push(2);
            push_usize(bytes, *actual);
        }
        OrganRuntimeError::UnknownSource { organ } => {
            bytes.push(3);
            push_id(bytes, organ);
        }
        OrganRuntimeError::OrganNotReady { organ, state } => {
            bytes.push(4);
            push_id(bytes, organ);
            bytes.push(hosted_state_tag(*state));
        }
        OrganRuntimeError::InvalidOutputPort { organ, port } => {
            bytes.push(5);
            push_id(bytes, organ);
            push_usize(bytes, *port);
        }
        OrganRuntimeError::UnroutedOutput { organ, port } => {
            bytes.push(6);
            push_id(bytes, organ);
            push_usize(bytes, *port);
        }
        OrganRuntimeError::HandleFailed { fault, delivered } => {
            bytes.push(7);
            push_id(bytes, &fault.organ);
            push_id(bytes, &fault.code);
            push_usize(bytes, *delivered);
        }
        OrganRuntimeError::OutputTooLarge {
            organ,
            actual,
            delivered,
        } => {
            bytes.push(8);
            push_id(bytes, organ);
            push_usize(bytes, *actual);
            push_usize(bytes, *delivered);
        }
        _ => return Err(OrganFanoutRecoveryErrorV1::UnsupportedDispatchError),
    }
    Ok(())
}

fn hosted_state_tag(state: HostedOrganStateV1) -> u8 {
    match state {
        HostedOrganStateV1::Registered => 1,
        HostedOrganStateV1::Ready => 2,
        HostedOrganStateV1::Quarantined => 3,
        HostedOrganStateV1::Stopped => 4,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let value = value.as_str().as_bytes();
    push_usize(bytes, value.len());
    bytes.extend_from_slice(value);
}

fn push_usize(bytes: &mut Vec<u8>, value: usize) {
    let value = u64::try_from(value).expect("bounded organ values fit into u64");
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_id(bytes, value);
        }
        None => bytes.push(0),
    }
}
