//! Authenticated qualification path for calibrated intuition decisions.
//!
//! V1/V2 remain available for historical replay and shadow compatibility.  The
//! V3 path in this module is the production-qualification boundary: a caller
//! cannot choose policy thresholds, calibration/OOD quality claims, or candidate
//! completeness by merely supplying matching digests.  Every such claim is
//! bound to an independently pinned Ed25519 signer and the current generation.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::Verifier as _;
use ed25519_dalek::VerifyingKey;

use crate::calibrated::CalibratedActionCandidateV1;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::CalibratedIntuitionReceiptV1;
use crate::calibrated::CalibrationArtifactV1;
use crate::calibrated::CandidateSetCompletenessBindingV1;
use crate::calibrated::OodArtifactV1;
use crate::calibrated::RiskClass;
use crate::calibrated::canonical_calibrated_request_digest_v1;
use crate::calibrated::decide_calibrated_v2;

const QUALIFICATION_SIGNATURE_DOMAIN_V1: &[u8] =
    b"hepta.intuition.qualification-signature.v1";
const MAX_CALIBRATION_BINS: usize = 100;
const PPM: u128 = 1_000_000;

include!("qualified_types.rs");
include!("qualified_digests.rs");
include!("qualified_decision.rs");
include!("qualified_metrics.rs");

#[cfg(test)]
#[path = "qualified_tests.rs"]
mod tests;
