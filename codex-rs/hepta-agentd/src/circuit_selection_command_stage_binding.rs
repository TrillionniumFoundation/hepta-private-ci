//! The concrete ordinary assembly moves its original, initially checked
//! Selector channel here. Actual opaque D/T complete the context, not the lease.

use std::sync::Mutex;

use codex_hepta_contracts::HostAuthorityPeerChannel;

use super::Channel;
use super::Error;
use super::OriginalCircuitSelectionCommandClientV1;
use super::OriginalCircuitSelectionCommandContextV1;
use super::now;
use super::require_clock;
use super::super::ordinary_stage_owners::Origin;
use crate::OriginalCellQ24MaterialCommandReceiptV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;

impl OriginalCircuitSelectionCommandClientV1 {
    pub(in super::super) fn bind_original_stage_channel(
        peer: HostAuthorityPeerChannel,
        material: &OriginalCellQ24MaterialReceiptConfigV1,
        dataset: &OriginalCellQ24MaterialCommandReceiptV1,
        training: &OriginalCellQ24TrainingCommandReceiptV1,
        origin: Origin,
    ) -> Result<Self, Error> {
        let started_at = now()?;
        let context = OriginalCircuitSelectionCommandContextV1::from_original_training(
            dataset.snapshot().clone(),
            material.scope.clone(),
            material.verifier.clone(),
            training,
        )?;
        if context.initial()? != material.initial {
            return Err(Error::Binding("same original initial Selector operation"));
        }
        let binding = context.binding(started_at)?;
        peer.check_peer_lifetime()?;
        let fresh = OriginalCellQ24MaterialCommandReceiptV1::require_original_dataset_context(
            dataset, material,
        ).map_err(|_| Error::Binding("same original Material before Selection"))?;
        require_clock(started_at, fresh)?;
        if context.binding(fresh)? != binding {
            return Err(Error::Binding("unchanged original Training signature"));
        }
        let execution_requested = match origin {
            Origin::Fresh => false,
            Origin::Recovered => true,
        };
        Ok(Self {
            channel: Mutex::new(Some(Channel { peer, next_request_id: 1, execution_requested })),
            context,
            binding,
            retained: Mutex::new(None),
        })
    }
}
