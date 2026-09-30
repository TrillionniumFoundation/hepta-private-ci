//! Typed ownership projections for AuthBus runtime metrics.
//!
//! The compatibility `AuthBusRuntimeSnapshot` remains flat, but exporters must
//! split it before assigning labels or rates. Process-lifetime counters are not
//! attributable to one authority database. Host-owned counters and histograms
//! belong to the exact authority instance whose snapshot produced them.

use serde::Serialize;

use crate::AuthBusLatencySummary;
use crate::AuthBusRuntimeSnapshot;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusProcessRuntimeSnapshot {
    pub owner_already_active_failures: u64,
    pub owner_unsafe_path_failures: u64,
    pub owner_storage_failures: u64,
    pub replay_rejections: u64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusAuthorityInstanceRuntimeSnapshot {
    pub checkpoint_sync_failures: u64,
    pub checkpoint_rollback_conflicts: u64,
    pub checkpoint_storage_failures: u64,
    pub authority_use_blocks: u64,
    pub mutation_attempts: u64,
    pub mutation_rejections: u64,
    pub mutation_outcome_unknown: u64,
    pub mutation_committed_reconciliation_required: u64,
    pub maintenance_ticks: u64,
    pub maintenance_failures: u64,
    pub recovery_incomplete_ticks: u64,
    pub mutation_latency: AuthBusLatencySummary,
    pub maintenance_latency: AuthBusLatencySummary,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct AuthBusRuntimeOwnershipSnapshot {
    pub process_runtime: AuthBusProcessRuntimeSnapshot,
    pub authority_instance: AuthBusAuthorityInstanceRuntimeSnapshot,
}

impl AuthBusRuntimeSnapshot {
    /// Separate process-global diagnostics from exact authority-instance data.
    /// Product-caller route and provider timings are intentionally absent: they
    /// remain owned by Agentd, Bao and their transport adapters.
    #[must_use]
    pub fn split_by_owner(&self) -> AuthBusRuntimeOwnershipSnapshot {
        AuthBusRuntimeOwnershipSnapshot {
            process_runtime: AuthBusProcessRuntimeSnapshot {
                owner_already_active_failures: self.owner_already_active_failures,
                owner_unsafe_path_failures: self.owner_unsafe_path_failures,
                owner_storage_failures: self.owner_storage_failures,
                replay_rejections: self.replay_rejections,
            },
            authority_instance: AuthBusAuthorityInstanceRuntimeSnapshot {
                checkpoint_sync_failures: self.checkpoint_sync_failures,
                checkpoint_rollback_conflicts: self.checkpoint_rollback_conflicts,
                checkpoint_storage_failures: self.checkpoint_storage_failures,
                authority_use_blocks: self.authority_use_blocks,
                mutation_attempts: self.mutation_attempts,
                mutation_rejections: self.mutation_rejections,
                mutation_outcome_unknown: self.mutation_outcome_unknown,
                mutation_committed_reconciliation_required: self
                    .mutation_committed_reconciliation_required,
                maintenance_ticks: self.maintenance_ticks,
                maintenance_failures: self.maintenance_failures,
                recovery_incomplete_ticks: self.recovery_incomplete_ticks,
                mutation_latency: self.mutation_latency,
                maintenance_latency: self.maintenance_latency,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_never_attributes_process_counters_to_authority_instance() {
        let flat = AuthBusRuntimeSnapshot {
            owner_already_active_failures: 1,
            owner_unsafe_path_failures: 2,
            owner_storage_failures: 3,
            checkpoint_sync_failures: 4,
            checkpoint_rollback_conflicts: 5,
            checkpoint_storage_failures: 6,
            authority_use_blocks: 7,
            mutation_attempts: 8,
            mutation_rejections: 9,
            mutation_outcome_unknown: 10,
            mutation_committed_reconciliation_required: 11,
            replay_rejections: 12,
            maintenance_ticks: 13,
            maintenance_failures: 14,
            recovery_incomplete_ticks: 15,
            mutation_latency: AuthBusLatencySummary {
                count: 16,
                p50_us: 17,
                p95_us: 18,
                p99_us: 19,
                max_us: 20,
            },
            maintenance_latency: AuthBusLatencySummary {
                count: 21,
                p50_us: 22,
                p95_us: 23,
                p99_us: 24,
                max_us: 25,
            },
        };
        let split = flat.split_by_owner();
        assert_eq!(split.process_runtime.replay_rejections, 12);
        assert_eq!(split.authority_instance.checkpoint_sync_failures, 4);
        assert_eq!(split.authority_instance.mutation_attempts, 8);
        assert_eq!(split.authority_instance.mutation_latency.max_us, 20);
    }
}
