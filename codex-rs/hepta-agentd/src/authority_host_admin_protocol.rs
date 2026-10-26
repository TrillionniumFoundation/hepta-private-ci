//! Bounded observations/selectors; none of these DTOs carries Root authority.
use serde::Deserialize;
use serde::Serialize;

pub const ROOT_ADMIN_FRAME_BOUND: usize = 16 * 1024;

/// Public identity of one actual Root lifetime, including a fresh episode nonce.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootAdminInstance {
    pub boot_id: String,
    pub root_pid: u32,
    pub process_start_ticks: u64,
    pub episode_nonce: [u8; 32],
}

/// A selector for the original live service, never a constructor for it.
#[derive(Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RootAdminRequest {
    pub schema_version: u32,
    pub expected_instance: RootAdminInstance,
    pub action: RootAdminAction,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum RootAdminAction {
    Observe {},
    ObserveIssuedNotesGrant {
        selection: crate::RootIssuedNotesGrantSelection,
    },
    RevokeWriter {
        expected_revision: u64,
        reason_sha256: [u8; 32],
    },
}

/// Original Current/lease/frontier evidence; this response cannot grant a use.
#[derive(Debug, Serialize)]
pub struct RootAdminObservation {
    pub instance: RootAdminInstance,
    pub writer: codex_hepta_contracts::authority_lease::AuthorityLeaseReadV1,
    pub writer_revocation:
        Option<codex_hepta_contracts::authority_lease::CapabilityRevocationReadV1>,
    pub lease_frontier: codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier,
    pub final_use_head: codex_hepta_contracts::FinalUseRevocations,
    pub physical_current: Option<crate::HostPhysicalCurrentObservation>,
}

#[derive(Debug, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum RootAdminResponse {
    Observed {
        observation: RootAdminObservation,
    },
    IssuedNotesGrantObserved {
        instance: RootAdminInstance,
        observation: crate::RootIssuedNotesGrantObservation,
    },
    WriterRevoked {
        instance: RootAdminInstance,
        receipt: codex_hepta_contracts::authority_lease::RevocationReceipt,
        lease_frontier: codex_hepta_contracts::authority_lease::AuthorityLeaseFrontier,
    },
}
