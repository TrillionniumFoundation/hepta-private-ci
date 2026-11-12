//! One-way late binding inside the concrete ordinary assembly. Neither an
//! original signature nor a new context restarts the initially held deadline.

use std::sync::Mutex;

use codex_hepta_contracts::HostAuthorityPeerChannel;

use super::super::ordinary_stage_owners::Origin;
use super::Channel;
use super::Error;
use super::OriginalCircuitNextUseCommandClientV1;
use super::OriginalCircuitNextUseCommandContextV1;
use super::now;
use super::require_clock;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCircuitSelectionCommandReceiptV1;

impl OriginalCircuitNextUseCommandClientV1 {
    pub(in super::super) fn bind_original_evaluated_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        selection: &OriginalCircuitSelectionCommandReceiptV1,
        origin: Origin,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let original = selection.evaluated_receipt()
            .map_err(|_| Error::Binding("actual original evaluated Selector response"))?;
        let original = match origin {
            Origin::Fresh => original,
            Origin::Recovered => original.into_original_receipt_readback(),
        };
        let context = OriginalCircuitNextUseCommandContextV1::from_evaluated_selection(&original)?;
        let mut actual_dataset = context.selection.clone();
        actual_dataset.head_digest = actual_dataset.receipts[2].predecessor;
        actual_dataset.receipts.truncate(2);
        if context.initial()? != material.initial || &actual_dataset != dataset.snapshot()
            || context.scope != material.scope
            || context.verifier.trust_digest() != material.verifier.trust_digest()
            || context.verifier.scope_digest() != material.verifier.scope_digest()
            || context.verifier.objective_digest() != material.verifier.objective_digest() {
            return Err(Error::Binding("same original evaluated Dataset before NextUse"));
        }
        let binding = context.binding(started_at)?;
        peer.check_peer_lifetime()?;
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(dataset, material)
            .map_err(|_| Error::Binding("same original evaluated Material before NextUse"))?;
        require_clock(started_at, fresh)?;
        if context.binding(fresh)? != binding {
            return Err(Error::Binding("unchanged full original evaluated C predecessors"));
        }
        Ok(Self {
            channel: Mutex::new(Some(Channel { peer, next_request_id: 1,
                execution_requested: origin == Origin::Recovered })),
            context, binding, retained: Mutex::new(None),
        })
    }

    pub(in super::super) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        selection: &OriginalCircuitSelectionCommandReceiptV1,
        origin: Origin,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let context = OriginalCircuitNextUseCommandContextV1::from_original_selection(
            material.scope.clone(),
            material.verifier.clone(),
            selection,
        )?;
        let mut original_dataset = context.selection.clone();
        original_dataset.head_digest = original_dataset.receipts[2].predecessor;
        original_dataset.receipts.truncate(2);
        if context.initial()? != material.initial || &original_dataset != dataset.snapshot() {
            return Err(Error::Binding("same original Dataset before NextUse"));
        }
        let binding = context.binding(started_at)?;
        peer.check_peer_lifetime()?;
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        )
        .map_err(|_| Error::Binding("same original Material before NextUse"))?;
        require_clock(started_at, fresh)?;
        if context.binding(fresh)? != binding {
            return Err(Error::Binding(
                "unchanged original Training and Selection signatures",
            ));
        }
        let execution_requested = match origin {
            Origin::Fresh => false,
            Origin::Recovered => true,
        };
        Ok(Self {
            channel: Mutex::new(Some(Channel {
                peer,
                next_request_id: 1,
                execution_requested,
            })),
            context,
            binding,
            retained: Mutex::new(None),
        })
    }
}
