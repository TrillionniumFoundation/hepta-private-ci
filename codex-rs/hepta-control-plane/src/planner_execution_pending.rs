//! Bounded, read-only inventory of unresolved durable planner dispatches.
//!
//! This module does not resolve requests, issue grants, invoke the effect owner
//! or redispatch an operation. It validates the existing durable claim/receipt
//! state machine and exposes only DENY_ALL evidence for a separately owned,
//! bounded reconciliation controller.

use std::collections::BTreeMap;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::PlannerEffectDispositionV1;
use super::PlannerExecutionError;
use super::PlannerTerminalReceiptV1;
use super::codec::decode_dispatch_claim;
use super::codec::decode_terminal_receipt;
use super::codec::store_error;
use super::codec::validate_existing_operation;
use crate::PlannerPendingDispatchPageV1;
use crate::PlannerPendingDispatchV1;
use crate::PlannerStoreRecordKindV1;
use crate::PlannerStoreRecordV1;
use crate::PlannerStoreV1;
use crate::MAX_PENDING_DISPATCH_PAGE_ITEMS_V1;

const DISPATCH_CLAIM_ENVELOPE_DOMAIN_V1: &[u8] =
    b"hepta.control.execution-dispatch-claim-envelope.v1";
const DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2: &[u8] =
    b"hepta.control.execution-dispatch-claim-envelope.v2";

impl PlannerStoreV1 {
    /// Return a bounded round-robin page of claims that still require
    /// effect-owner reconciliation.
    ///
    /// Conclusive operations are excluded. Claims with no receipt or an
    /// indeterminate latest receipt remain visible. A poisoned store fails
    /// closed, and every returned entry remains `DENY_ALL`.
    pub fn pending_dispatches_page(
        &self,
        after_sequence: Option<u64>,
        limit: usize,
    ) -> Result<PlannerPendingDispatchPageV1, PlannerExecutionError> {
        self.ensure_healthy()?;
        if limit == 0 || limit > MAX_PENDING_DISPATCH_PAGE_ITEMS_V1 {
            return Err(store_error("pending dispatch page limit is out of bounds"));
        }

        let mut claims = BTreeMap::new();
        for record in self
            .records()
            .iter()
            .filter(|record| is_dispatch_claim_record(record))
        {
            let claim = decode_dispatch_claim(record)?;
            let previous = claims.insert(
                claim.operation_identity_digest,
                PendingDispatchStateV1 {
                    claim_sequence: record.sequence,
                    claim_record_digest: record.record_digest,
                    request_digest: claim.request_digest,
                    grant_digest: claim.grant_digest,
                    final_payload_digest: claim.final_payload_digest,
                    latest_receipt: None,
                },
            );
            if previous.is_some() {
                return Err(store_error("duplicate durable dispatch claim"));
            }
        }

        for record in self.records().iter().filter(|record| {
            matches!(
                record.kind,
                PlannerStoreRecordKindV1::TerminalReceipt
                    | PlannerStoreRecordKindV1::Reconciliation
            )
        }) {
            let receipt = decode_terminal_receipt(record)?;
            let Some(state) = claims.get_mut(&receipt.operation_identity_digest) else {
                return Err(store_error(
                    "execution receipt exists without a durable dispatch claim",
                ));
            };
            validate_existing_operation(
                receipt.operation_identity_digest,
                receipt.request_digest,
                receipt.final_payload_digest,
                receipt.operation_identity_digest,
                state.request_digest,
                state.final_payload_digest,
            )?;
            if record.sequence <= state.claim_sequence {
                return Err(store_error("execution receipt precedes dispatch claim"));
            }
            if receipt.grant_digest != state.grant_digest {
                return Err(store_error(
                    "execution receipt grant does not match durable dispatch claim",
                ));
            }

            match record.kind {
                PlannerStoreRecordKindV1::TerminalReceipt => {
                    if state.latest_receipt.is_some() {
                        return Err(store_error(
                            "duplicate initial terminal receipt for durable dispatch",
                        ));
                    }
                }
                PlannerStoreRecordKindV1::Reconciliation => {
                    let Some(previous) = state.latest_receipt.as_ref() else {
                        return Err(store_error(
                            "reconciliation receipt exists without an initial observation",
                        ));
                    };
                    if previous.disposition != PlannerEffectDispositionV1::Indeterminate {
                        return Err(store_error(
                            "reconciliation cannot replace a conclusive terminal receipt",
                        ));
                    }
                }
                _ => unreachable!("receipt filter restricts record kinds"),
            }
            state.latest_receipt = Some(receipt);
        }

        let mut unresolved = claims
            .into_iter()
            .filter_map(|(operation_identity_digest, state)| {
                if matches!(
                    state
                        .latest_receipt
                        .as_ref()
                        .map(|receipt| receipt.disposition),
                    Some(
                        PlannerEffectDispositionV1::Succeeded
                            | PlannerEffectDispositionV1::Failed
                    )
                ) {
                    return None;
                }
                Some(PlannerPendingDispatchV1 {
                    claim_sequence: state.claim_sequence,
                    claim_record_digest: state.claim_record_digest,
                    operation_identity_digest,
                    request_digest: state.request_digest,
                    original_grant_digest: state.grant_digest,
                    final_payload_digest: state.final_payload_digest,
                    authority: AuthorityPosture::DENY_ALL,
                })
            })
            .collect::<Vec<_>>();
        unresolved.sort_by_key(|pending| pending.claim_sequence);

        if unresolved.is_empty() {
            return Ok(PlannerPendingDispatchPageV1 {
                items: Vec::new(),
                next_after_sequence: None,
                wrapped: false,
                authority: AuthorityPosture::DENY_ALL,
            });
        }

        let start = after_sequence.map_or(0, |cursor| {
            unresolved
                .iter()
                .position(|pending| pending.claim_sequence > cursor)
                .unwrap_or(0)
        });
        let count = limit.min(unresolved.len());
        let last_sequence = unresolved
            .last()
            .map_or(0, |pending| pending.claim_sequence);
        let wrapped = after_sequence.is_some_and(|cursor| {
            (start == 0 && cursor >= last_sequence) || start + count > unresolved.len()
        });
        let items = unresolved
            .iter()
            .cycle()
            .skip(start)
            .take(count)
            .cloned()
            .collect::<Vec<_>>();
        let next_after_sequence = items.last().map(|pending| pending.claim_sequence);

        Ok(PlannerPendingDispatchPageV1 {
            items,
            next_after_sequence,
            wrapped,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

struct PendingDispatchStateV1 {
    claim_sequence: u64,
    claim_record_digest: Digest32,
    request_digest: Digest32,
    grant_digest: Digest32,
    final_payload_digest: Digest32,
    latest_receipt: Option<PlannerTerminalReceiptV1>,
}

fn is_dispatch_claim_record(record: &PlannerStoreRecordV1) -> bool {
    record.kind == PlannerStoreRecordKindV1::Selection
        && (record
            .envelope
            .starts_with(DISPATCH_CLAIM_ENVELOPE_DOMAIN_V1)
            || record
                .envelope
                .starts_with(DISPATCH_CLAIM_ENVELOPE_DOMAIN_V2))
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::AuthorityPosture;
    use tempfile::tempdir;

    use super::super::PlannerTerminalReceiptSinkV1;
    use super::super::codec::digest_terminal_receipt;
    use super::super::codec::dispatch_claim_digest_v2;
    use super::super::codec::dispatch_claim_identity;
    use super::super::codec::encode_dispatch_claim_v2;
    use super::*;
    use crate::PlannerStoreConfigV1;
    use crate::PlannerStoreError;
    use crate::PlannerStoreFailpointV1;

    #[derive(Clone, Copy)]
    struct ClaimFixture {
        operation_identity_digest: Digest32,
        request_digest: Digest32,
        grant_digest: Digest32,
        final_payload_digest: Digest32,
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn append_claim(store: &mut PlannerStoreV1, name: &str) -> ClaimFixture {
        let claim = ClaimFixture {
            operation_identity_digest: digest(&format!("operation-{name}")),
            request_digest: digest(&format!("request-{name}")),
            grant_digest: digest(&format!("grant-{name}")),
            final_payload_digest: digest(&format!("payload-{name}")),
        };
        let claim_digest = dispatch_claim_digest_v2(
            claim.operation_identity_digest,
            claim.request_digest,
            claim.grant_digest,
            claim.final_payload_digest,
        );
        let claimed_at_micros = 1_000 + u64::try_from(store.records().len()).unwrap_or(0);
        let envelope = encode_dispatch_claim_v2(
            claim.operation_identity_digest,
            claim.request_digest,
            claim.grant_digest,
            claim.final_payload_digest,
            claimed_at_micros,
            claim_digest,
        );
        store
            .append_execution_record(
                PlannerStoreRecordKindV1::Selection,
                dispatch_claim_identity(claim.operation_identity_digest),
                claim_digest,
                &envelope,
            )
            .expect("append durable claim");
        claim
    }

    fn append_terminal(
        store: &mut PlannerStoreV1,
        claim: ClaimFixture,
        disposition: PlannerEffectDispositionV1,
        observed_at_micros: u64,
    ) {
        let outcome_digest = digest(&format!(
            "outcome-{}-{observed_at_micros}",
            claim.operation_identity_digest
        ));
        let receipt_digest = digest_terminal_receipt(
            claim.operation_identity_digest,
            claim.request_digest,
            claim.grant_digest,
            claim.final_payload_digest,
            disposition,
            outcome_digest,
            observed_at_micros,
        );
        let receipt = PlannerTerminalReceiptV1 {
            operation_identity_digest: claim.operation_identity_digest,
            request_digest: claim.request_digest,
            grant_digest: claim.grant_digest,
            final_payload_digest: claim.final_payload_digest,
            disposition,
            outcome_digest,
            observed_at_micros,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        };
        store
            .append_terminal_receipt(&receipt)
            .expect("append terminal receipt");
    }

    #[test]
    fn pending_dispatch_inventory_is_bounded_and_round_robin() {
        let directory = tempdir().expect("temporary planner store");
        let mut store =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default())
                .expect("open planner store");
        append_claim(&mut store, "first");
        append_claim(&mut store, "second");
        append_claim(&mut store, "third");

        let page = store
            .pending_dispatches_page(None, 2)
            .expect("first pending page");
        assert_eq!(page.items.len(), 2);
        assert!(!page.wrapped);
        assert!(!page.authority.grants_any());
        assert!(
            page.items
                .iter()
                .all(|pending| !pending.authority.grants_any())
        );
        assert!(page.items[0].claim_sequence < page.items[1].claim_sequence);

        let rotated = store
            .pending_dispatches_page(page.next_after_sequence, 2)
            .expect("rotated pending page");
        assert_eq!(rotated.items.len(), 2);
        assert!(rotated.wrapped);
        assert_eq!(rotated.items[1], page.items[0]);
        assert_ne!(rotated.items[0], page.items[0]);
    }

    #[test]
    fn pending_dispatch_inventory_excludes_conclusive_and_keeps_indeterminate() {
        let directory = tempdir().expect("temporary planner store");
        let mut store =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default())
                .expect("open planner store");
        let conclusive = append_claim(&mut store, "conclusive");
        append_terminal(
            &mut store,
            conclusive,
            PlannerEffectDispositionV1::Succeeded,
            2_000,
        );
        let indeterminate = append_claim(&mut store, "indeterminate");
        append_terminal(
            &mut store,
            indeterminate,
            PlannerEffectDispositionV1::Indeterminate,
            2_001,
        );

        let page = store
            .pending_dispatches_page(None, 8)
            .expect("pending inventory");
        assert_eq!(page.items.len(), 1);
        assert_eq!(
            page.items[0].operation_identity_digest,
            indeterminate.operation_identity_digest
        );
    }

    #[test]
    fn pending_dispatch_inventory_rejects_invalid_bounds_and_poisoned_state() {
        let directory = tempdir().expect("temporary planner store");
        let mut store =
            PlannerStoreV1::open(directory.path(), PlannerStoreConfigV1::default())
                .expect("open planner store");
        assert!(matches!(
            store.pending_dispatches_page(None, 0),
            Err(PlannerExecutionError::Store(message))
                if message.contains("limit is out of bounds")
        ));
        assert!(matches!(
            store.pending_dispatches_page(None, MAX_PENDING_DISPATCH_PAGE_ITEMS_V1 + 1),
            Err(PlannerExecutionError::Store(message))
                if message.contains("limit is out of bounds")
        ));

        store.set_failpoint(Some(
            PlannerStoreFailpointV1::AfterLogSyncBeforePublish,
        ));
        let error = store
            .append(
                PlannerStoreRecordKindV1::Decision,
                digest("poison-operation"),
                digest("poison-payload"),
                b"poison-envelope",
            )
            .expect_err("failpoint must poison store");
        assert!(matches!(
            error,
            PlannerStoreError::Failpoint(
                PlannerStoreFailpointV1::AfterLogSyncBeforePublish
            )
        ));
        assert!(matches!(
            store.pending_dispatches_page(None, 1),
            Err(PlannerExecutionError::Store(message))
                if message.contains("recovery required")
        ));
    }
}
