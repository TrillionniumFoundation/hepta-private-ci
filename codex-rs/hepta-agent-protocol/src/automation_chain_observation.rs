//! Point-in-time task settlement comparisons, never model-install authority.

use codex_hepta_contracts::ProviderEffectIntent;
use serde::Deserialize;
use serde::Serialize;

use crate::AutomationEffectChainObservation;

pub const AUTOMATION_EFFECT_CHAIN_OBSERVATION_VERSION: u32 = 4;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutomationEffectTaskAcceptanceV1 {
    pub schema_version: u32,
    pub task_id: String,
    pub owner: String,
    pub provider: String,
    pub output_sha256: String,
    pub accept_tx_id: String,
    pub accepted_in_exact_packet: bool,
    pub current_status: String,
}

impl AutomationEffectTaskAcceptanceV1 {
    /// Validate the bounded native task-settlement shape; no capability follows.
    pub fn is_settled_in_exact_packet(&self) -> bool {
        self.schema_version == 1
            && self.accepted_in_exact_packet
            && self.current_status == "settled"
            && [
                &self.task_id,
                &self.owner,
                &self.provider,
                &self.output_sha256,
                &self.accept_tx_id,
            ]
            .into_iter()
            .all(|value| nonzero_digest(value))
    }
}

/// Independently retained expectations from the task/effect owner, not values
/// copied out of the observation being compared. `effect.payload_sha256` hashes
/// the exact original packet bytes; `block_id` uses the separate Chain domain.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExpectedAutomationTaskAcceptanceV1 {
    pub effect: ProviderEffectIntent,
    pub min_confirmation_depth: u64,
    pub min_confirmation_work_depth_hex: String,
    pub block_id: String,
    pub task_id: String,
    pub owner: String,
    pub provider: String,
    pub output_sha256: String,
    pub accept_tx_id: String,
}

impl AutomationEffectChainObservation {
    /// Compare one authenticated host observation with the original independently
    /// retained task and effect facts. This result is only a point-in-time match.
    /// Re-read current chain and artifact/withdrawal/selection owners before use;
    /// success grants no installation, export, FinalUse or replay permission.
    pub fn matches_expected_task_acceptance(
        &self,
        expected: &ExpectedAutomationTaskAcceptanceV1,
    ) -> bool {
        let Some(task) = &self.accepted_task else {
            return false;
        };
        let (Some(height), Some(depth), Some(work), Some(block_work)) = (
            self.block_height,
            self.active_depth,
            self.active_work_depth_hex.as_deref(),
            self.block_chainwork_hex.as_deref(),
        ) else {
            return false;
        };
        // This DTO follows the host's strict schema/context and exact-payload
        // checks. Preserve both fixed native read policies, not arbitrary
        // caller-supplied budgets. Growth walks one record plus two reads per
        // ancestor; maintenance lacks accepted_task and returned above.
        let membership_reads_valid = match self.active_membership_sql_budget {
            1024 => self
                .active_membership_sql_lookups
                .is_some_and(|lookups| (2..=1024).contains(&lookups)),
            8193 => depth
                .checked_mul(2)
                .and_then(|reads| reads.checked_add(1))
                .is_some_and(|reads| {
                    reads <= 8193 && self.active_membership_sql_lookups == Some(reads)
                }),
            _ => false,
        };
        self.schema_version == AUTOMATION_EFFECT_CHAIN_OBSERVATION_VERSION
            && self.owner_generation > 0
            && self.local_target_only
            && !self.global_absence_authority
            && !self.confirmation_authority
            && !self.finality_authority
            && !self.execution_authority
            && self.stored_exact
            && self.active_chain_member
            && self.confirmation_policy_satisfied
            && self.confirmation_policy_min_depth == expected.min_confirmation_depth
            && self.confirmation_policy_min_work_depth_hex
                == expected.min_confirmation_work_depth_hex
            && (1..=4096).contains(&self.confirmation_policy_min_depth)
            && self.active_tip_height.checked_sub(height) == Some(depth)
            && depth >= self.confirmation_policy_min_depth
            && membership_reads_valid
            && nonzero_digest(&self.active_tip)
            && (self.block_id == self.active_tip) == (height == self.active_tip_height)
            && work_difference_matches(&self.active_tip_chainwork_hex, block_work, work)
            && valid_work(&self.confirmation_policy_min_work_depth_hex)
            && self
                .confirmation_policy_min_work_depth_hex
                .bytes()
                .any(|byte| byte != b'0')
            && work >= self.confirmation_policy_min_work_depth_hex.as_str()
            && self.provider_effect_key.as_deref() == Some(expected.effect.key.as_str())
            && self.payload_sha256.as_deref() == Some(expected.effect.payload_sha256.as_str())
            && [
                &expected.block_id,
                &expected.task_id,
                &expected.owner,
                &expected.provider,
                &expected.output_sha256,
                &expected.accept_tx_id,
            ]
            .into_iter()
            .all(|value| nonzero_digest(value))
            && self.block_id == expected.block_id
            && task.is_settled_in_exact_packet()
            && task.task_id == expected.task_id
            && task.owner == expected.owner
            && task.provider == expected.provider
            && task.output_sha256 == expected.output_sha256
            && task.accept_tx_id == expected.accept_tx_id
    }
}

fn nonzero_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        && value.bytes().any(|byte| byte != b'0')
}

fn valid_work(value: &str) -> bool {
    value.len() == 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn work_difference_matches(tip: &str, block: &str, difference: &str) -> bool {
    if ![tip, block, difference].into_iter().all(valid_work) {
        return false;
    }
    let mut borrow = 0_u16;
    for offset in (0..128).step_by(2).rev() {
        // The canonical ASCII/length checks above make all slices and parses exact.
        let (Ok(left), Ok(right), Ok(expected)) = (
            u16::from_str_radix(&tip[offset..offset + 2], 16),
            u16::from_str_radix(&block[offset..offset + 2], 16),
            u16::from_str_radix(&difference[offset..offset + 2], 16),
        ) else {
            return false;
        };
        let right = right + borrow;
        let value = if left >= right {
            borrow = 0;
            left - right
        } else {
            borrow = 1;
            256 + left - right
        };
        if value != expected {
            return false;
        }
    }
    borrow == 0
}

#[cfg(test)]
#[path = "automation_chain_observation_tests.rs"]
mod tests;
