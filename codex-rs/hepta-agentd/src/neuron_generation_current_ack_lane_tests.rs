//! Test-only borrowing of the already connected concrete Root store. No
//! constructor, authority replacement, stream extraction or reconnect exists.

use super::*;
use crate::root_generation_current_client::ack_lane_tests::AckLaneOrder;

impl CurrentStore {
    pub(crate) fn component_original_ack_lane_order(
        &self,
        order: AckLaneOrder,
    ) -> anyhow::Result<()> {
        let Store::Root(original) = &self.store else {
            anyhow::bail!("actual original Root current store required");
        };
        original.component_original_ack_lane_order(order)
    }
}
